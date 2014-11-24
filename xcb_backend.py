# Copyright (c) 2013-2015 Francois GINDRAUD
# 
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
XCB interface part of the daemon.
- Keeps a valid copy of the xrandr state (updating it on events)
- Can generate and apply layouts from this state
- Signal the config manager when the current state changed
"""

import operator
import functools
import struct
import xcffib, xcffib.xproto, xcffib.randr

import util
import layout
from util import Pair
from layout import BackendError, BackendFatalError

logger = util.setup_logger (__name__)

class Backend (util.Daemon):
    ##################
    # Main Interface #
    #################

    def __init__ (self, **kwd):
        """
        Backend init. Optionnal arguments :
            dpi :
                By default X11 forces a 96 dpi to not bother with it. It affects the reported size of the virtual screen.
                if set to a value, force this value
                if not set (default), infer dpi from physical screen info
            screen, display :
                override X11 default connect information
        """
        self.dpi = kwd.get ("dpi", None)
        self.update_callback = lambda _: 0
        self.init_randr_connection (**kwd)

    def __enter__ (self): return self
    def __exit__ (self, type, value, tb): self.conn.disconnect ()
    
    def fileno (self): return self.conn.get_file_descriptor ()

    def activate (self):
        """ Daemon callback """
        while self.flush_notify ():
            self.reload_state ()
            self.update_callback (self.to_concrete_layout ())
        return True # continue

    def dump (self):
        """ Returns internal state debug info as a string """
        acc = "Screen: {:s}\n".format (self.screen_size)
        acc += "Modes\n"
        for mode in self.screen_res.modes:
            acc += "\t{0}\t{1[0]:s}  {1[1]}Hz\n".format (mode.id, mode_info (mode))
        acc += "CRTCs\n"
        for c in self.screen_res.crtcs:
            info = self.crtcs[c]
            acc += "\t{}\t{:s}+{:s}\n".format (c, Pair.from_size (info), Pair.from_struct (info))
            acc += "\t|\tOutput[active]: {}\n".format (util.sequence_stringify (info.possible, highlight = lambda o: o in info.outputs))
            acc += "\t|\tRotations[current]: {}\n".format (info.transform)
            acc += "\t\\\tMode: {}\n".format (info.mode)
        acc += "Outputs\n"
        for o in self.screen_res.outputs:
            info = self.outputs[o]
            if info.connection == xcffib.randr.Connection.Connected:
                acc += "\t{}\t{}\tConnected\n".format (o, info.name)
                acc += "\t|\tSize: {:p}\n".format (Pair.from_size (info, "mm_{}"))
                acc += "\t|\tCrtcs[active]: {}\n".format (util.sequence_stringify (info.crtcs, highlight = lambda c: c == info.crtc))
                acc += "\t|\tClones: {}\n".format (util.sequence_stringify (info.clones))
                acc += "\t|\tModes[pref]: {}\n".format (util.sequence_stringify (enumerate (info.modes), highlight = lambda t: t[0] < info.num_preferred, stringify = lambda t: t[1]))
                acc += "\t\\\tProperties:\n"
                for name, prop in info.props.items ():
                    acc += "\t\t\t{}: {}\n".format (name, prop)
            else:
                acc += "\t{}\t{}\tDisconnected\n".format (o, info.name)
        return acc
    
    ############################
    # Layout Manager Interface #
    ############################

    def attach (self, callback):
        """ Register the callback from the manager """
        self.update_callback = callback
        callback (self.to_concrete_layout ()) # initial call to let the manager update itself

    def apply_concrete_layout (self, concrete):
        """ Set up a concretelayout from the manager in X """
        self._apply_concrete_layout (concrete)
        self.activate_manually () # Handle our own notifications

    ####################
    # XRandR internals #
    ####################

    randr_version = Pair (1, 3)

    def init_randr_connection (self, **kwd):
        """ Starts connection, construct an initial state, setup events. """
        # Connection
        self.conn = xcffib.connect (display = kwd.get ("display"))
        
        # Randr init
        self.conn.randr = self.conn (xcffib.randr.key)
        version = Pair.from_struct (self.conn.randr.QueryVersion (*Backend.randr_version).reply (), "major_version", "minor_version")
        if (not version >= Backend.randr_version):
            raise BackendFatalError ("version: requested >= {}, got {}".format (Client.randr_version, version))

        # Properties query object
        self.prop_manager = Properties (self.conn) # TODO

        # Internal state 
        screen_setup = self.conn.setup.roots[kwd.get ("screen", self.conn.pref_screen)]
        self.root = screen_setup.root
        
        limits = self.conn.randr.GetScreenSizeRange (self.root).reply ()
        self.screen_limit_min = Pair.from_size (limits, "min_{}")
        self.screen_limit_max = Pair.from_size (limits, "max_{}")
        
        self.reload_state ()

        # Randr register for events
        masks = xcffib.randr.NotifyMask.ScreenChange | xcffib.randr.NotifyMask.CrtcChange
        masks |= xcffib.randr.NotifyMask.OutputChange | xcffib.randr.NotifyMask.OutputProperty
        self.conn.randr.SelectInput (self.root, masks)
        self.conn.flush ()

    def reload_state (self):
        """ Updates the state by reloading everything """
        # Clean everything
        self.screen_res, self.screen_size, self.screen_transform = None, None, None
        self.crtcs, self.outputs = {}, {}
        # Screen ressources and size range
        cookie_res = self.conn.randr.GetScreenResourcesCurrent (self.root)
        cookie_size = self.conn.core.GetGeometry (self.root)
        self.screen_res = cookie_res.reply ()
        self.screen_size = Pair.from_size (cookie_size.reply ())
        # Crtc and Outputs
        crtc_req, output_req = {}, {}
        for c in self.screen_res.crtcs: crtc_req[c] = self.conn.randr.GetCrtcInfo (c, self.screen_res.config_timestamp)
        for o in self.screen_res.outputs: output_req[o] = self.conn.randr.GetOutputInfo (o, self.screen_res.config_timestamp)
        for c in self.screen_res.crtcs:
            self.crtcs[c] = check_reply (crtc_req[c].reply ())
            self.crtcs[c].transform = XcbTransform.from_xcffib_struct (self.crtcs[c])
        for o in self.screen_res.outputs:
            self.outputs[o] = check_reply (output_req[o].reply ())
            self.outputs[o].name = bytearray (self.outputs[o].name).decode ()
            if self.is_connected (o): self.outputs[o].props = self.prop_manager.get_properties (o)

    def flush_notify (self):
        """ Discards all events, returns True if one was from Randr """
        had_randr_event = False
        ev = self.conn.poll_for_event ()
        while ev:
            if isinstance (ev, (xcffib.randr.ScreenChangeNotifyEvent, xcffib.randr.NotifyEvent)):
                had_randr_event = True # Only generate new config if we received randr notifications
            if isinstance (ev, xcffib.randr.ScreenChangeNotifyEvent):
                logger.debug ("[notify] ScreenChange = {:s}, {:p} | {}".format (Pair.from_size (ev), Pair.from_size (ev, "m{}"), XcbTransform (ev.rotation)))
            if isinstance (ev, xcffib.randr.NotifyEvent):
                if ev.subCode == xcffib.randr.Notify.CrtcChange:
                    logger.debug ("[notify] CrtcChange[{}] = {:s}+{:s} | {}".format (ev.u.cc.crtc, Pair.from_size (ev.u.cc), Pair.from_struct (ev.u.cc), XcbTransform (ev.u.cc.rotation)))
                if ev.subCode == xcffib.randr.Notify.OutputChange:
                    logger.debug ("[notify] OutputChange[{}] = crtc[{}]".format (ev.u.oc.output, ev.u.oc.crtc))
                if ev.subCode == xcffib.randr.Notify.OutputProperty:
                    logger.debug ("[notify] OutputProperty[{}]".format (ev.u.op.output))
            ev = self.conn.poll_for_event ()
        return had_randr_event

    def to_concrete_layout (self):
        """
        Convert current X state into ConcreteLayout
        """
        def find_best_mode_size (o_data):
            return max (map (self.mode_by_id, self.preferred_mode_ids (o_data))) [0]
        def make_output_entry (o_id):
            xcb_o_data = self.outputs[o_id]
            layout_output = layout.ConcreteLayout.Output (edid = xcb_o_data.props["EDID"], preferred_size = find_best_mode_size (xcb_o_data))
            crtc = self.crtcs.get (xcb_o_data.crtc, None)
            if crtc and self.mode_exists (crtc.mode):
                layout_output.enabled = True
                layout_output.base_size = self.mode_by_id (crtc.mode) [0]
                layout_output.position = Pair.from_struct (crtc)
                layout_output.transform = crtc.transform.to_slam ()
            return (xcb_o_data.name, layout_output)
        
        return layout.ConcreteLayout (
                outputs = dict (make_output_entry (o_id) for o_id in self.outputs if self.is_connected (o_id)),
                vs_size = self.screen_size, vs_min = self.screen_limit_min, vs_max = self.screen_limit_max)
   
    def _apply_concrete_layout (self, concrete):
        """
        Internal function that push a ConcreteLayout to X
        """
        output_id_by_name = {self.outputs[o].name: o for o in self.outputs}
        enabled_outputs = [n for n in concrete.outputs if concrete.outputs[n].enabled]
        new_output_by_crtc = dict.fromkeys (self.crtcs)
        
        ### Allocate Crtcs ###
        unallocated = set (enabled_outputs)
        def try_allocate_crtc (c_id, o_name):
            # Test if crtc / output not already allocated
            if new_output_by_crtc[c_id] is None and o_name in unallocated:
                # Does it fits into the Crtc ?
                transform = XcbTransform.from_slam (concrete.outputs[o_name].transform, self.crtcs[c_id].rotations)
                if transform.valid () and output_id_by_name[o_name] in self.crtcs[c_id].possible:
                    new_output_by_crtc[c_id] = o_name
                    unallocated.remove (o_name)

        for o_name in enabled_outputs: # outputs already enabled may keep the same crtc if not clones
            for c_id in self.crtcs:
                if output_id_by_name[o_name] in self.crtcs[c_id].outputs:
                    try_allocate_crtc (c_id, o_name)

        for o_name in enabled_outputs: # allocate the remaining outputs
            if o_name in unallocated:
                for c_id in self.crtcs:
                    try_allocate_crtc (c_id, o_name)

        if len (unallocated) > 0:
            raise BackendError ("crtc allocation (tmp = {}) failed for outputs {}".format (new_output_by_crtc, list (unallocated)))

        ### Apply config utility functions ###
        timestamp = self.screen_res.timestamp
        c_timestamp = self.screen_res.config_timestamp

        def resize_screen (virtual_size):
            dpi = 96 # x default
            if self.dpi is not None:
                dpi = self.dpi # override setup
            else:
                # extract from screen info : dpi is average (with screen area coeffs) of screens dpi
                dpmm_acc, coeff_acc = 0, 0
                for n in enabled_outputs:
                    phy = Pair.from_size (self.outputs[output_id_by_name[n]], "mm_{}")
                    virt = concrete.outputs[n].base_size
                    if phy.w > 0 and phy.h > 0:
                        coeff = virt.w * virt.h
                        dpmm_acc += coeff * (virt.w / (phy.w + 0.5) + virt.h / (phy.h + 0.5))
                        coeff_acc += coeff * 2
                if coeff_acc > 0 and dpmm_acc > 0:
                    dpi = 25.4 * dpmm_acc / coeff_acc
            # resizing
            phy = virtual_size.map (lambda d: int (d * 25.4 / dpi))
            logger.debug ("[send] SetScreenSize = {:s}, {:p}".format (virtual_size, phy))
            self.conn.randr.SetScreenSizeChecked (self.root, virtual_size.w, virtual_size.h, phy.w, phy.h).check ()
        
        def set_crtc (t, c_id, pos, mode, tr, outputs):
            logger.debug ("[send] SetCrtcConfig[{}] = {} | {}".format (c_id, outputs, tr))
            return check_reply (self.conn.randr.SetCrtcConfig (c_id, t, c_timestamp, pos.x, pos.y, mode, tr.mask, outputs).reply ()).timestamp
        def disable_crtc (t, c_id):
            return set_crtc (timestamp, c_id, Pair (0, 0), 0, XcbTransform (), [])
        def assign_crtc (t, c_id, o_name):
            o_data, o_id = concrete.outputs[o_name], output_id_by_name[o_name]
            return set_crtc (t, c_id, o_data.position, self.find_mode_id (o_data.base_size, o_id), XcbTransform.from_slam (o_data.transform), [o_id])

        ### Apply config, Grabbing the server to make the update atomic ###
        self.conn.core.GrabServerChecked ().check ()
        try:
            # resize screen to max of (before, after) to avoid setcrtc() fails during modification
            before, after = self.screen_size, concrete.virtual_screen_size
            temporary = after.map (max, before)
            resize_screen (temporary)

            # apply the new crtc config in 3 steps to avoid temporarily allocating the same output to two crtcs
            for c_id in self.crtcs:
                if new_output_by_crtc[c_id] == None and self.crtcs[c_id].num_outputs > 0: # first disable now unused crtcs
                    timestamp = disable_crtc (timestamp, c_id)
            for c_id in self.crtcs:
                if new_output_by_crtc[c_id] != None and self.crtcs[c_id].num_outputs > 1: # apply new config to clones crtcs to free outputs
                    timestamp = assign_crtc (timestamp, c_id, new_output_by_crtc[c_id])
            for c_id in self.crtcs:
                if new_output_by_crtc[c_id] != None and self.crtcs[c_id].num_outputs <= 1: # apply new config to unused or single crtcs. as the allocation phase keeps older choices, there should be no collision here
                    timestamp = assign_crtc (timestamp, c_id, new_output_by_crtc[c_id])
            
            # TODO disable stupid modes (panning, crtctransform, etc)
            if temporary != after: 
                resize_screen (after)
        finally:
            self.conn.core.UngrabServerChecked ().check ()

    ###########
    # Helpers #
    ###########

    def is_connected (self, o_id):
        return self.outputs[o_id].connection == xcffib.randr.Connection.Connected
    
    def mode_by_id (self, m_id):
        try: return mode_info (next (m for m in self.screen_res.modes if m.id == m_id))
        except: raise BackendFatalError ("mode {} not found".format (m_id))
    
    def mode_exists (self, m_id):
        return len ([m for m in self.screen_res.modes if m.id == m_id]) == 1
    
    def preferred_mode_ids (self, o_data):
        if o_data.num_preferred > 0: return (o_data.modes[i] for i in range (o_data.num_preferred))
        else: return o_data.modes
    
    def find_mode_id (self, size, o_id):
        mode, freq = 0, 0
        for m_id in self.preferred_mode_ids (self.outputs[o_id]):
            (sz, f) = self.mode_by_id (m_id)
            if sz == size and f > freq:
                mode, freq = m_id, f
        if mode == 0: raise BackendFatalError ("no matching mode for size {} and output {}".format (size, self.outputs[o_id].name))
        return mode

def mode_info (mode):
    """ Extract size and frequency from X mode info """
    freq = int (mode.dot_clock / (mode.htotal * mode.vtotal)) if mode.htotal > 0 and mode.vtotal > 0 else 0
    return (Pair.from_size (mode), freq)

def check_reply (reply):
    """ Raise exception if reply status is not ok """
    e = xcffib.randr.SetConfig
    if reply.status == e.Success: return reply
    elif reply.status == e.InvalidConfigTime: raise BackendError ("invalid config timestamp")
    elif reply.status == e.InvalidTime: raise BackendError ("invalid timestamp")
    else: raise BackendFatalError ("Request failed")


class XcbTransform (object):
    """
    Stores X rotation & rotation capability masks.
    X format : reflections (xy), then trigo rotation : (rx, ry, rot), as a bitmask (xcffib.randr.Rotation)
    """
    class StaticData (object):
        def __init__ (self):
            self.cls = xcffib.randr.Rotation

            self.flags_by_name = {attr: getattr (self.cls, attr) for attr in util.class_attributes (self.cls)}
            self.all_flags = functools.reduce (operator.__or__, self.flags_by_name.values ())
            
            self.flags_by_rotation_value = {rot: self.flags_by_name["Rotate_" + str (rot)] for rot in layout.Transform.rotations}

    static = StaticData ()

    # Constructors

    def __init__ (self, mask = static.cls.Rotate_0, allowed_masks = static.all_flags):
        """ Init with explicit masks """
        self.mask = mask
        self.allowed_masks = allowed_masks

    @staticmethod
    def from_xcffib_struct (st):
        """ Extract masks from xcffib struct """
        return XcbTransform (st.rotation, st.rotations)

    @staticmethod
    def from_slam (slam, allowed_masks = static.all_flags):
        """ Build from Slam rotation """
        st = XcbTransform.static
        return XcbTransform (st.flags_by_rotation_value[slam.rotation] | (st.cls.Reflect_X if slam.reflect else 0), allowed_masks)

    # Conversion, validity, pretty print

    def to_slam (self):
        """ Convert to slam Transform """
        try: [rot] = (r for r, mask in self.static.flags_by_rotation_value.items () if mask & self.mask)
        except ValueError: raise BackendFatalError ("xcffib transformation has 0 or >1 rotation flags")

        slam = layout.Transform ()
        if self.mask & self.static.cls.Reflect_X: slam = slam.reflectx ()
        if self.mask & self.static.cls.Reflect_Y: slam = slam.reflecty ()
        return slam.rotate (rot)

    def valid (self):
        """ Check if current mask is within the capability mask """
        return self.allowed_masks & self.mask == self.mask

    def __str__ (self):
        allowed_flags = ((n, f) for n, f in sorted (self.static.flags_by_name.items ()) if f & self.allowed_masks)
        return util.sequence_stringify (allowed_flags, highlight = lambda t: t[1] & self.mask, stringify = lambda t: t[0])

##################
# Xcb properties #
##################

class Properties:
    def __init__ (self, conn):
        self.conn = conn
        # Get atoms of property names
        watched_properties = [ "EDID", "BACKLIGHT" ]
        self.atoms = dict ((name, self.conn.core.InternAtom (False, len (name), name).reply ().atom) for name in watched_properties)

    def get_properties (self, output):
        try:
            return dict ((name, getattr (self, "get_" + name.lower ()) (output, atom)) for name, atom in self.atoms.items ())
        except BackendError as e:
            raise BackendError ("output {}: ".format (output) + str (e))
        except BackendFatalError as e:
            raise BackendFatalError ("output {}: ".format (output) + str (e))


    @staticmethod
    def not_found (reply): return reply.format == 0 and reply.type == xcffib.xproto.Atom._None and reply.bytes_after == 0 and reply.num_items == 0

    def get_backlight (self, output, prop_atom):
        """
        Backlight Xcb property (value, lowest, highest)
        """
        # Data : backlight value
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcffib.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): return None
        if not (data.format > 0 and data.type == xcffib.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items == 1): raise BackendFatalError ("invalid BACKLIGHT value formatting")
        (value,) = struct.unpack_from ({ 8: "b", 16: "h", 32: "i" } [data.format], bytearray (data.data))
        
        # Config : backlight value range
        config = self.conn.randr.QueryOutputProperty (output, prop_atom).reply ()
        if not (config.range and len (config.validValues) == 2): raise BackendFatalError ("invalid BACKLIGHT config")
        lowest, highest = config.validValues
        if not (lowest <= value and value <= highest): raise BackendFatalError ("BACKLIGHT value out of bounds")
        return (value, lowest, highest)

    def get_edid (self, output, prop_atom):
        """
        EDID (unique device identifier) Xcb property (str)
        The bytes 8-15 are enough for identification, the rest is mode data
        """
        # Data
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcffib.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): return None
        if not (data.format == 8 and data.type == xcffib.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items > 0): raise BackendFatalError ("invalid EDID value formatting")
        if data.data[:8] != [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]: raise BackendFatalError ("EDID lacks 1.3 constant header")
        return ''.join (map ("{:02X}".format, data.data[8:16]))
