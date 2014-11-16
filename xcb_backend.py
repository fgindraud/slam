"""
XCB interface part of the multi monitor daemon.
- Keeps a valid copy of the xrandr state (updating it on events)
- Can generate and apply configurations from this state
- Signal the config manager when the current state changed
"""

import struct
from functools import reduce
import xcffib, xcffib.xproto, xcffib.randr

from util import *
import layout
from layout import BackendError, BackendFatalError

class Backend (object):
    ##################
    # Main Interface #
    #################

    def __init__ (self, **kwd):
        """
        By default X11 forces a 96 dpi to not bother with it. It affects the reported size of the virtual screen.
        if "dpi" is set to a value, force this dpi value.
        if not set (default), infer dpi from physical screen info
        """
        self.dpi = kwd.get ("dpi", None)
        self.debug_enabled = kwd.get ("debug", True)

        self.update_callback = lambda _: 0
        self.init_randr_connection (**kwd)
    def cleanup (self):
        self.conn.disconnect ()

    def fileno (self): return self.conn.get_file_descriptor ()

    def activate (self):
        turns = 0
        while self.flush_notify ():
            turns += 1
            if turns > 10:
                raise BackendFatalError ("activation infinite loop")
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
            acc += "\t|\tOutput[active]: {}\n".format (sequence_stringify (info.possible, highlight = lambda o: o in info.outputs))
            acc += "\t|\tRotations[current]: {}\n".format (info.transform)
            acc += "\t\\\tMode: {}\n".format (info.mode)
        acc += "Outputs\n"
        for o in self.screen_res.outputs:
            info = self.outputs[o]
            if info.connection == xcffib.randr.Connection.Connected:
                acc += "\t{}\t{}\tConnected\n".format (o, info.name)
                acc += "\t|\tSize: {:p}\n".format (Pair.from_size (info, "mm_{}"))
                acc += "\t|\tCrtcs[active]: {}\n".format (sequence_stringify (info.crtcs, highlight = lambda c: c == info.crtc))
                acc += "\t|\tClones: {}\n".format (sequence_stringify (info.clones))
                acc += "\t|\tModes[pref]: {}\n".format (sequence_stringify (enumerate (info.modes), highlight = lambda t: t[0] < info.num_preferred, stringify = lambda t: t[1]))
                acc += "\t\\\tProperties:\n"
                for name, prop in info.props.items ():
                    acc += "\t\t\t{}: {}\n".format (name, prop)
            else:
                acc += "\t{}\t{}\tDisconnected\n".format (o, info.name)
        return acc
    
    ###########################
    # ConfigManager Interface #
    ###########################

    def get_virtual_screen_min_size (self): return Pair.from_size (self.screen_limits, "min_{}")
    def get_virtual_screen_max_size (self): return Pair.from_size (self.screen_limits, "max_{}")
    def get_preferred_sizes_by_output (self):
        """ Returns the best size for each output (biggest and fastest) """
        def find_best (o_data):
            return max (self.mode_by_id (m_id) for m_id in self.preferred_mode_ids (o_data)) [0]
        return dict ((o.name, find_best (o)) for o in self.outputs.values () if len (o.modes) > 0)

    def attach (self, callback):
        self.update_callback = callback
        callback (self.to_concrete_layout ()) # initial call to let the manager update itself

    def use_concrete_layout (self, concrete):
        # TODO reactivate
        self.apply_concrete_layout (concrete)

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
        self.reload_state ()

        # Randr register for events
        masks = xcffib.randr.NotifyMask.ScreenChange | xcffib.randr.NotifyMask.CrtcChange
        masks |= xcffib.randr.NotifyMask.OutputChange | xcffib.randr.NotifyMask.OutputProperty
        self.conn.randr.SelectInput (self.root, masks)
        self.conn.flush ()

    def reload_state (self):
        """ Updates the state by reloading everything """
        # Clean everything
        self.screen_res, self.screen_limits, self.screen_size, self.screen_transform = None, None, None, None
        self.crtcs, self.outputs = {}, {}
        # Screen ressources and size range
        cookie_res = self.conn.randr.GetScreenResourcesCurrent (self.root)
        cookie_size_range = self.conn.randr.GetScreenSizeRange (self.root)
        cookie_size = self.conn.core.GetGeometry (self.root)
        self.screen_res = cookie_res.reply ()
        self.screen_limits = cookie_size_range.reply ()
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
        ev = hadevent = self.conn.poll_for_event ()
        while ev:
            if isinstance (ev, xcffib.randr.ScreenChangeNotifyEvent):
                self.debug ("[notify] ScreenChange = {:s}, {:p} | {}".format (Pair.from_size (ev), Pair.from_size (ev, "m{}"), XcbTransform (ev.rotation)))
            if isinstance (ev, xcffib.randr.NotifyEvent):
                if ev.subCode == xcffib.randr.Notify.CrtcChange:
                    self.debug ("[notify] CrtcChange[{}] = {:s}+{:s} | {}".format (ev.u.cc.crtc, Pair.from_size (ev.u.cc), Pair.from_struct (ev.u.cc), XcbTransform (ev.u.cc.rotation)))
                if ev.subCode == xcffib.randr.Notify.OutputChange: self.debug ("[notify] OutputChange[{}] = crtc[{}]".format (ev.u.oc.output, ev.u.oc.crtc))
                if ev.subCode == xcffib.randr.Notify.OutputProperty: self.debug ("[notify] OutputProperty[{}]".format (ev.u.op.output))
            ev = self.conn.poll_for_event ()
        return hadevent != None

    def to_concrete_layout (self):
        def make_entry (o_id):
            x_o = self.outputs[o_id]
            l_o = layout.ConcreteLayout.Output (edid = x_o.props["EDID"])
            c = self.crtcs.get (x_o.crtc, None)
            if c and self.mode_exists (c.mode):
                l_o.enabled, l_o.base_size, l_o.position, l_o.transform = True, self.mode_by_id (c.mode) [0], Pair.from_struct (c), c.transform.to_slam ()
            return (x_o.name, l_o)
        concrete = layout.ConcreteLayout (outputs = dict (make_entry (o_id) for o_id in self.outputs if self.is_connected (o_id)), vss = self.screen_size.copy ())
        concrete.compute_manual_flag (self.get_preferred_sizes_by_output ())
        return concrete
   
    def apply_concrete_layout (self, concrete):
        ### Allocate Crtcs ###
        output_id_by_name = dict ((self.outputs[o].name, o) for o in self.outputs)
        new_output_by_crtc = dict.fromkeys (self.crtcs)
        enabled_outputs = [n for n in concrete.outputs if concrete.outputs[n].enabled]
        unallocated = set (enabled_outputs)
        def try_allocate_crtc (c_id, o_name):
            if new_output_by_crtc[c_id] == None and o_name in unallocated:
                if XcbTransform.from_slam (concrete.outputs[o_name].transform, self.crtcs[c_id].rotations).valid () and output_id_by_name[o_name] in self.crtcs[c_id].possible:
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

        ### Apply config ###
        timestamp = self.screen_res.timestamp
        c_timestamp = self.screen_res.config_timestamp

        def resize_screen (virtual_size):
            dpi = 96 # x default
            if self.dpi != None:
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
            self.debug ("[send] SetScreenSize = {:s}, {:p}".format (virtual_size, phy))
            self.conn.randr.SetScreenSizeChecked (self.root, virtual_size.w, virtual_size.h, phy.w, phy.h).check ()
        
        def set_crtc (t, c_id, pos, mode, tr, outputs):
            self.debug ("[send] SetCrtcConfig[{}] = {} | {}".format (c_id, outputs, tr))
            return check_reply (self.conn.randr.SetCrtcConfig (c_id, t, c_timestamp, pos.x, pos.y, mode, tr.mask, outputs).reply ()).timestamp
        def disable_crtc (t, c_id):
            return set_crtc (timestamp, c_id, Pair (0, 0), 0, XcbTransform (), [])
        def assign_crtc (t, c_id, o_name):
            o_data, o_id = concrete.outputs[o_name], output_id_by_name[o_name]
            return set_crtc (t, c_id, o_data.position, self.find_mode_id (o_data.base_size, o_id), XcbTransform.from_slam (o_data.transform), [o_id])

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
            if temporary != after: resize_screen (after)
            self.conn.flush ()
        finally:
            self.conn.core.UngrabServerChecked ().check ()

    ###########
    # Helpers #
    ###########

    def debug (self, msg):
        if self.debug_enabled:
            print (msg)

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
    freq = int (mode.dot_clock / (mode.htotal * mode.vtotal)) if mode.htotal > 0 and mode.vtotal > 0 else 0
    return (Pair.from_size (mode), freq)

def check_reply (reply):
    e = xcffib.randr.SetConfig
    if reply.status == e.Success: return reply
    elif reply.status == e.InvalidConfigTime: raise BackendError ("invalid config timestamp")
    elif reply.status == e.InvalidTime: raise BackendError ("invalid timestamp")
    else: raise BackendFatalError ("Request failed")

class XcbTransform (object):
    """
    Xcb : reflections (xy), then trigo rotation : (rx, ry, rot), as a bitmask (xcffib.randr.Rotation)
    Slam : reflect x, then trigo rotation : (rx, rot)
    """
    flags = dict ((a, getattr (xcffib.randr.Rotation, a)) for a in class_attributes (xcffib.randr.Rotation))
    all_flags_or = reduce (operator.__or__, flags.values ())
    slam_to_mask = dict ((r, getattr (xcffib.randr.Rotation, "Rotate_" + str (r))) for r in layout.Transform.rotations)

    def __init__ (self, mask = xcffib.randr.Rotation.Rotate_0, allowed_masks = all_flags_or):
        self.mask = mask
        self.allowed_masks = allowed_masks
    @staticmethod
    def from_xcffib_struct (st):
        return XcbTransform (st.rotation, st.rotations)
    @staticmethod
    def from_slam (slam, allowed_masks = all_flags_or):
        return XcbTransform (XcbTransform.slam_to_mask[slam.rotation] | (xcffib.randr.Rotation.Reflect_X if slam.reflect else 0), allowed_masks)

    def to_slam (self):
        try: [rot] = (r for r, m in XcbTransform.slam_to_mask.items () if m & self.mask)
        except: raise BackendFatalError ("xcffib transformation has 0 or >1 rotation flags")
        slam = layout.Transform ()
        if self.mask & xcffib.randr.Rotation.Reflect_X: slam = slam.reflectx ()
        if self.mask & xcffib.randr.Rotation.Reflect_Y: slam = slam.reflecty ()
        return slam.rotate (rot)

    def valid (self):
        return self.allowed_masks & self.mask == self.mask

    def __str__ (self):
        allowed_flags = ((n, f) for n, f in XcbTransform.flags.items () if f & self.allowed_masks)
        return sequence_stringify (allowed_flags, highlight = lambda t: t[1] & self.mask, stringify = lambda t: t[0])

##################
# Xcb properties #
##################

class Properties:
    def __init__ (self, conn):
        self.conn = conn
        # Get atoms of property names
        watched_properties = [ "EDID", "BACKLIGHT" ]
        self.atoms = dict ((name, self.conn.core.InternAtom (False, len (name), name).reply ().atom) for name in watched_properties)

    def get_properties (self, output): return dict ((name, getattr (self, "get_" + name.lower ()) (output, atom)) for name, atom in self.atoms.items ())

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
        """
        # Data
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcffib.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): raise BackendError ("EDID property not found")
        if not (data.format == 8 and data.type == xcffib.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items > 0): raise BackendFatalError ("invalid EDID value formatting")
        return ''.join ("{:x}".format (b) for b in data.data)
