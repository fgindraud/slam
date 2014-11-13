"""
XCB interface part of the multi monitor daemon.
- Keeps a valid copy of the xrandr state (updating it on events)
- Can generate and apply configurations from this state
- Signal the config manager when the current state changed
"""

import struct # To pack or unpack data from xcb requests
import xcb, xcb.xproto, xcb.randr

import layout
from layout import BackendError as RandrError, BackendFatalError as RandrFatalError

class Backend (object):
    randr_version = 1, 3

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
        self.init_randr_connection (**kwd)
        self.update_callback = None
    def cleanup (self):
        self.conn.disconnect ()

    def fileno (self): return self.conn.get_file_descriptor ()

    def activate (self):
        if self.handle_messages ():
            self.reload_state ()
            if self.update_callback: self.update_callback (self.to_concrete_layout ())
        return True # continue

    def debug_info (self):
        return dump_state (self)

    ###########################
    # ConfigManager Interface #
    ###########################

    def get_virtual_screen_min_size (self): return layout.Pair (self.screen_limits.min_width, self.screen_limits.min_height)
    def get_virtual_screen_max_size (self): return layout.Pair (self.screen_limits.max_width, self.screen_limits.max_height)
    def get_preferred_sizes_by_output (self):
        """ Returns the best size for each output (biggest and fastest) """
        def find_best (o_data):
            (w, h, _) = max (mode_info (self.mode_by_id (m_id)) for m_id in self.preferred_mode_ids (o_data))
            return layout.Pair (w, h)
        return dict ((o.name, find_best (o)) for o in self.outputs.values () if len (o.modes) > 0)

    def attach (self, callback):
        self.update_callback = callback
        callback (self.to_concrete_layout ()) # initial call to let the manager update itself

    def use_concrete_layout (self, concrete):
        self.apply_concrete_layout (concrete)

    def flush (self):
        if self.handle_messages ():
            self.reload_state ()

    ####################
    # XRandR internals #
    ####################

    def init_randr_connection (self, **kwd):
        """ Starts connection, construct an initial state, setup events. """
        # Connection
        self.conn = xcb.connect (display = kwd.get ("display"))
        
        # Randr init
        self.conn.randr = self.conn (xcb.randr.key)
        version_reply = self.conn.randr.QueryVersion (*Backend.randr_version).reply ()
        version = version_reply.major_version, version_reply.minor_version
        if (not version >= Backend.randr_version):
            raise RandrFatalError ("version: requested >= %s, got %s" % (str (Client.randr_version), str (version)))

        # Properties query object
        self.prop_manager = Properties (self.conn)

        # Internal state 
        screen_setup = self.conn.get_setup ().roots[kwd.get ("screen", self.conn.pref_screen)]
        self.root = screen_setup.root
        self.screen_size = layout.Pair (screen_setup.width_in_pixels, screen_setup.height_in_pixels)
        self.screen_rotation = layout.Transform () # FIXME assume screen is not rotated at startup (GetScreenInfo is broken)
        self.reload_state ()

        # Randr register for events
        masks = xcb.randr.NotifyMask.ScreenChange | xcb.randr.NotifyMask.CrtcChange
        masks |= xcb.randr.NotifyMask.OutputChange | xcb.randr.NotifyMask.OutputProperty
        self.conn.randr.SelectInput (self.root, masks)
        self.conn.flush ()

    def reload_state (self):
        """ Updates the state by reloading everything """
        # Clean everything
        self.screen_res, self.screen_limits = None, None
        self.crtcs, self.outputs = {}, {}
        # Screen ressources and size range
        cookie_res = self.conn.randr.GetScreenResourcesCurrent (self.root)
        cookie_size = self.conn.randr.GetScreenSizeRange (self.root)
        self.screen_res = cookie_res.reply ()
        self.screen_limits = cookie_size.reply ()
        # Crtc and Outputs
        crtc_req, output_req = {}, {}
        for c in self.screen_res.crtcs: crtc_req[c] = self.conn.randr.GetCrtcInfo (c, self.screen_res.config_timestamp)
        for o in self.screen_res.outputs: output_req[o] = self.conn.randr.GetOutputInfo (o, self.screen_res.config_timestamp)
        for c in self.screen_res.crtcs: self.crtcs[c] = check_reply (crtc_req[c].reply ())
        for o in self.screen_res.outputs:
            self.outputs[o] = check_reply (output_req[o].reply ())
            self.outputs[o].name = str (bytearray (self.outputs[o].name))
            if self.is_connected (o): self.outputs[o].props = self.prop_manager.get_properties (o)

    def handle_messages (self):
        ev = hadevent = self.conn.poll_for_event ()
        while ev:
            if isinstance (ev, xcb.randr.ScreenChangeNotifyEvent):
                # update screen size as we cannot query it naturally, along with rotation
                self.screen_rotation = Transform.xcb_to_slam (ev.rotation)
                self.screen_size = layout.Pair (ev.width, ev.height)
                phy_size = layout.Pair (ev.mwidth, ev.mheight)
                print ("ScreenChange = (sz = %s, phy = %s, rot = %s)" % (str (self.screen_size), str (phy_size), str (self.screen_rotation)))
            if isinstance (ev, xcb.randr.NotifyEvent):
                if ev.subCode == xcb.randr.Notify.CrtcChange:
                    print ("CrtcChange[%d] = %dx%d+%d+%d" % (ev.u.cc.crtc, ev.u.cc.width, ev.u.cc.height, ev.u.cc.x, ev.u.cc.y))
                if ev.subCode == xcb.randr.Notify.OutputChange:
                    print ("OutputChange[%d] = crtc[%d]" % (ev.u.oc.output, ev.u.oc.crtc))
                if ev.subCode == xcb.randr.Notify.OutputProperty:
                    print ("OutputProperty[%d]" % ev.u.op.output)
            ev = self.conn.poll_for_event ()
        return hadevent != None

    def to_concrete_layout (self):
        # TODO handle strange case
        def make_entry (o_id):
            x_o = self.outputs[o_id]
            l_o = layout.ConcreteLayout.Output (edid = x_o.props["EDID"])
            c = self.crtcs.get (x_o.crtc, None)
            if c and self.mode_exists (c.mode):
                l_o.enabled, l_o.base_size, l_o.position, l_o.transform = True, self.mode_size_by_id (c.mode), layout.Pair (c.x, c.y), Transform.xcb_to_slam (c.rotation)
            return (x_o.name, l_o)
        concrete = layout.ConcreteLayout (outputs = dict (make_entry (o_id) for o_id in self.outputs if self.is_connected (o_id)), vss = self.screen_size.copy ())
        concrete.compute_manual_flag (self.get_preferred_sizes_by_output ())
        return concrete
   
    def apply_concrete_layout (self, concrete):
        ### Allocate Crtcs ###
        output_id_by_name = dict ((self.outputs[o].name, o) for o in self.outputs)
        new_output_by_crtc = dict ((c_id, None) for c_id in self.crtcs)
        enabled_outputs = [n for n in concrete.outputs if concrete.outputs[n].enabled]
        unallocated = set (enabled_outputs)
        def try_allocate_crtc (c_id, o_name):
            if new_output_by_crtc[c_id] == None and o_name in unallocated:
                xcb_rot_mask = Transform.slam_to_xcb (concrete.outputs[o_name].transform)
                if xcb_rot_mask & self.crtcs[c_id].rotations == xcb_rot_mask and output_id_by_name[o_name] in self.crtcs[c_id].possible:
                    new_output_by_crtc[c_id] = o_name
                    unallocated.remove (o_name)
        for o_name in enabled_outputs: # outputs already enabled may keep the same crtc
            for c_id in self.crtcs:
                if output_id_by_name[o_name] in self.crtcs[c_id].outputs:
                    try_allocate_crtc (c_id, o_name)
        for o_name in enabled_outputs: # allocate the remaining outputs
            if o_name in unallocated:
                for c_id in self.crtcs:
                    try_allocate_crtc (c_id, o_name)
        if len (unallocated) > 0:
            raise RandrError ("crtc allocation (tmp = %s) failed for outputs %s" % (str (new_output_by_crtc), str (list (unallocated))))

        ### Apply config ###
        timestamp = self.screen_res.timestamp
        c_timestamp = self.screen_res.config_timestamp
        def resize_screen (size):
            dpi = 96 # x default
            if self.dpi != None:
                dpi = self.dpi # override setup
            else:
                # extract from screen info : dpi is average (with screen area coeffs) of screens dpi
                dpmm_acc, coeff_acc = 0, 0
                for n in enabled_outputs:
                    o_data, c_o_data = self.outputs[output_id_by_name[n]], concrete.outputs[n]
                    if o_data.mm_width > 0 and o_data.mm_height > 0:
                        coeff = c_o_data.base_size.x * c_o_data.base_size.y
                        dpmm_acc += coeff * (c_o_data.base_size.x / (o_data.mm_width + 0.5) + c_o_data.base_size.y / (o_data.mm_height + 0.5))
                        coeff_acc += coeff * 2
                if coeff_acc > 0 and dpmm_acc > 0:
                    dpi = 25.4 * dpmm_acc / coeff_acc
            # resizing
            phy = layout.Pair (map (lambda d: int (d * 25.4 / dpi), size))
            print ("SetScreenSize(%dx%d, %dx%d)" % (size.x, size.y, phy.x, phy.y))
            self.conn.randr.SetScreenSizeChecked (self.root, size.x, size.y, phy.x, phy.y).check ()
        def set_crtc (t, c_id, pos, mode, tr, outputs):
            print "SetCrtcConfig(%d, %s, %s)" % (c_id, str (tr), str (outputs))
            return check_reply (self.conn.randr.SetCrtcConfig (c_id, t, c_timestamp, pos.x, pos.y, mode, tr, len (outputs), outputs).reply ()).timestamp
        def disable_crtc (t, c_id):
            return set_crtc (timestamp, c_id, layout.Pair (0, 0), 0, xcb.randr.Rotate_0, [])
        def assign_crtc (t, c_id, o_name):
            o_data, o_id = concrete.outputs[o_name], output_id_by_name[o_name]
            return set_crtc (t, c_id, o_data.position, self.find_mode_id (o_data.base_size, o_id), Transform.slam_to_xcb (o_data.transform), [o_id])

        self.conn.core.GrabServerChecked ().check ()
        try:
            # resize screen to max of (before, after) to avoid setcrtc() fails during modification
            before, after = self.screen_rotation.rectangle_size (self.screen_size), concrete.virtual_screen_size
            temporary = layout.Pair (map (max, after, before))
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

    def is_connected (self, o_id):
        return self.outputs[o_id].connection == xcb.randr.Connection.Connected
    
    def mode_by_id (self, m_id):
        try:
            [mode] = (m for m in self.screen_res.modes if m.id == m_id)
            return mode
        except: raise RandrFatalError ("mode %d not found" % m_id)
    def mode_size_by_id (self, m_id):
        m = self.mode_by_id (m_id)
        return layout.Pair (m.width, m.height)
    def mode_exists (self, m_id):
        return len ([m for m in self.screen_res.modes if m.id == m_id]) == 1
    def preferred_mode_ids (self, o_data):
        if o_data.num_preferred > 0: return (o_data.modes[i] for i in range (o_data.num_preferred))
        else: return o_data.modes
    def find_mode_id (self, size, o_id):
        mode, freq = 0, 0
        for m_id in self.preferred_mode_ids (self.outputs[o_id]):
            (w, h, f) = mode_info (self.mode_by_id (m_id))
            if w == size.x and h == size.y and f > freq:
                mode, freq = m_id, freq
        if mode == 0: raise RandrFatalError ("no matching mode for size %s and output %s" % (str (size), self.outputs[o_id].name))
        return mode


def mode_info (mode):
    if mode.htotal > 0 and mode.vtotal > 0: return (mode.width, mode.height, int (mode.dot_clock / (mode.htotal * mode.vtotal)))
    else: return (mode.width, mode.height, 0)

def check_reply (reply):
    e = xcb.randr.SetConfig
    if reply.status == e.Success: return reply
    elif reply.status == e.InvalidConfigTime: raise RandrError ("invalid config timestamp")
    elif reply.status == e.InvalidTime: raise RandrError ("invalid timestamp")
    else: raise RandrFatalError ("Request failed")

class Transform (object):
    """
    Xcb : reflections (xy), then trigo rotation : (rx, ry, rot), as a bitmask (xcb.randr.Rotation)
    Slam : reflect x, then trigo rotation : (rx, rot)
    """
    xcb_masks = dict ((r, getattr (xcb.randr.Rotation, "Rotate_" + str (r))) for r in layout.Transform.rotations)

    @staticmethod
    def xcb_to_slam (mask):
        try: [rot] = (r for r, m in Transform.xcb_masks.items () if m & mask)
        except: raise RandrFatalError ("xcb transformation has 0 or >1 rotation flags")
        slam = layout.Transform ()
        if mask & xcb.randr.Rotation.Reflect_X: slam = slam.reflectx ()
        if mask & xcb.randr.Rotation.Reflect_Y: slam = slam.reflecty ()
        return slam.rotate (rot)

    @staticmethod
    def slam_to_xcb (slam):
        return Transform.xcb_masks[slam.rotation] | (xcb.randr.Rotation.Reflect_X if slam.reflect else 0)

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
    def not_found (reply): return reply.format == 0 and reply.type == xcb.xproto.Atom._None and reply.bytes_after == 0 and reply.num_items == 0

    def get_backlight (self, output, prop_atom):
        """
        Backlight Xcb property (value, lowest, highest)
        """
        # Data : backlight value
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): return None
        if not (data.format > 0 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items == 1): raise RandrFatalError ("invalid BACKLIGHT value formatting")
        (value,) = struct.unpack_from ({ 8: "b", 16: "h", 32: "i" } [data.format], bytearray (data.data))
        # Config : backlight value range
        config = self.conn.randr.QueryOutputProperty (output, prop_atom).reply ()
        if not (config.range and len (config.validValues) == 2): raise RandrFatalError ("invalid BACKLIGHT config")
        lowest, highest = config.validValues
        if not (lowest <= value and value <= highest): raise RandrFatalError ("BACKLIGHT value out of bounds")
        return (value, lowest, highest)

    def get_edid (self, output, prop_atom):
        """
        EDID (unique device identifier) Xcb property (str)
        """
        # Data
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): raise RandrError ("EDID property not found")
        if not (data.format == 8 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items > 0): raise RandrFatalError ("invalid EDID value formatting")
        return ''.join (["%x" % b for b in data.data])

###########################
# Xrandr state debug info #
###########################

def iterable_str (iterable, func_highlight = lambda e: False, func_str = str):
    """ Stringify an iterable object, highlighting some elements depending on func_highlight. """
    return " ".join (["[%s]" % func_str (v) if func_highlight (v) else func_str (v) for v in iterable])

def class_attrs_iterable_str (class_name, func_filter_attr, func_highlight = lambda e: False):
    """ Stringify class constants, filter only a part of them, and print them with highlighting """
    func_keep_attr = lambda a: not callable (a) and not a.startswith ('__') and func_filter_attr (getattr (class_name, a))
    attrs = [attr for attr in dir (class_name) if func_keep_attr (attr)]
    return iterable_str (attrs, lambda a: func_highlight (getattr (class_name, a)))

def dump_state (state):
    """ Pretty dump of Xcb state """
    # Screen
    acc = "Screen %dx%d\n" % (state.screen_size.x, state.screen_size.y)
    acc += "Rotation: %s\n" % str (state.screen_rotation)
    # Modes
    acc += "Modes\n"
    for mode in state.screen_res.modes:
        mode_flags = "" #class_attr (xcb.randr.ModeFlag, lambda a: True)
        freq = mode.dot_clock / (mode.htotal * mode.vtotal)
        acc += "\t%d\t%dx%d\t%f\t%s\n" % (mode.id, mode.width, mode.height, freq, mode_flags)
    # Crtc
    acc += "CRTCs\n"
    for c in state.screen_res.crtcs:
        info = state.crtcs[c]
        acc += "\t%d\t%dx%d+%d+%d\n" % (c, info.width, info.height, info.x, info.y)
        acc += "\t\tOutput[active]: %s\n" % iterable_str (info.possible, lambda o: o in info.outputs)
        has_rot = lambda r: r & info.rotations
        rot_enabled = lambda r: r & info.rotation
        acc += "\t\tRotations[current]: %s\n" % class_attrs_iterable_str (xcb.randr.Rotation, has_rot, rot_enabled)
        acc += "\t\tMode: %d\n" % info.mode
    # Outputs
    acc += "Outputs\n"
    for o in state.screen_res.outputs:
        info = state.outputs[o]
        conn_status = class_attrs_iterable_str (xcb.randr.Connection, lambda c: c == info.connection)
        acc += "\t%d\t%s (%s)\n" % (o, info.name, conn_status)
        if info.connection == xcb.randr.Connection.Connected:
            acc += "\t\tPhy size: %dmm x %dmm\n" % (info.mm_width, info.mm_height)
            acc += "\t\tCrtcs[active]: %s\n" % iterable_str (info.crtcs, lambda c: c == info.crtc)
            acc += "\t\tClones: %s\n" % iterable_str (info.clones)
            mode_id_str = lambda i: str (info.modes[i])
            mode_id_preferred = lambda i : i < info.num_preferred
            acc += "\t\tModes[pref]: %s\n" % iterable_str (range (len (info.modes)), mode_id_preferred, mode_id_str)
            acc += "\t\tProperties:\n"
            for name, prop in info.props.items ():
                acc += "\t\t\t%s: %s\n" % (name, str (prop))
    return acc
