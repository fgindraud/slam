"""
XCB interface part of the multi monitor daemon.
- Keeps a valid copy of the xrandr state (updating it on events)
- Can generate and apply configurations from this state
- Signal the config manager when the current state changed
"""

import struct # To pack or unpack data from xcb requests
import xcb, xcb.xproto, xcb.randr

import layout

class RandrError (Exception):
    pass

class Backend (object):
    randr_version = 1, 3

    ##################
    # Main Interface #
    #################

    def __init__ (self, display=None, screen=0):
        self.init_randr_connection (display, screen)
        self.update_callback = None
    def cleanup (self):
        self.conn.disconnect ()

    def fileno (self): return self.conn.get_file_descriptor ()

    def activate (self):
        self.flush_messages ()
        self.reload_state ()
        if self.update_callback: self.update_callback (self.to_concrete_layout ())
        return True

    ###########################
    # ConfigManager Interface #
    ###########################

    def get_virtual_screen_min_size (self):
        return layout.Pair (self.screen_limits.min_width, self.screen_limits.min_height)
    def get_virtual_screen_max_size (self):
        return layout.Pair (self.screen_limits.max_width, self.screen_limits.max_height)
    def get_preferred_sizes_by_output (self):
        """ returns the best size for each output (biggest) """
        def convert_mode (mode): return layout.Pair (mode.width, mode.height)
        return dict ([(o.name, convert_mode (self.mode_by_id (o.modes[0]))) for o in self.outputs.values ()])

    def attach (self, callback):
        self.update_callback = callback
        callback (self.to_concrete_layout ()) # initial call to let the manager update itself

    def apply_concrete_layout (self, concrete):
        pass # Lot of stuff to do

    ####################
    # XRandR internals #
    ####################

    def init_randr_connection (self, display, screen):
        """ Starts connection, construct an initial state, setup events. """
        # Connection
        self.conn = xcb.connect (display=display)
        
        # Randr init
        self.conn.randr = self.conn (xcb.randr.key)
        version_reply = self.conn.randr.QueryVersion (*Backend.randr_version).reply ()
        version = version_reply.major_version, version_reply.minor_version
        if (not version >= LayoutBackend.randr_version):
            msg_format = "version: requested >= {0[0]}.{0[1]}, got {1[0]}.{1[1]}"
            raise RandrError (msg_format.format (Client.randr_version, version))

        # Properties query object
        self.prop_manager = Properties (self.conn)

        # Internal state
        self.screen = screen
        self.reload_state ()

        # Randr register for events
        masks = xcb.randr.NotifyMask.ScreenChange | xcb.randr.NotifyMask.CrtcChange
        masks |= xcb.randr.NotifyMask.OutputChange | xcb.randr.NotifyMask.OutputProperty
        self.conn.randr.SelectInput (self.root, masks)
        self.conn.flush ()

    def reload_state (self):
        """ Updates the state by reloading everything """
        failed = False
        # Clean everything
        self.screen_setup = None
        self.screen_limits = None
        self.root = None
        self.screen_res = None
        self.crtcs = dict ()
        self.outputs = dict ()
        # Setup
        self.screen_setup = self.conn.get_setup ().roots[self.screen]
        self.root = self.screen_setup.root
        # Screen ressources and size range
        cookie_res = self.conn.randr.GetScreenResourcesCurrent (self.root)
        cookie_size = self.conn.randr.GetScreenSizeRange (self.root)
        self.screen_res = cookie_res.reply ()
        self.screen_limits = cookie_size.reply ()
        # Crtc and Outputs
        crtc_req = dict ()
        output_req = dict ()
        for c in self.screen_res.crtcs: crtc_req[c] = self.conn.randr.GetCrtcInfo (c, self.screen_res.config_timestamp)
        for o in self.screen_res.outputs: output_req[o] = self.conn.randr.GetOutputInfo (o, self.screen_res.config_timestamp)
        for c in self.screen_res.crtcs: self.crtcs[c], failed = check_reply (crtc_req[c].reply (), failed)
        for o in self.screen_res.outputs:
            self.outputs[o], failed = check_reply (output_req[o].reply (), failed)
            self.outputs[o].name = str (bytearray (self.outputs[o].name))
            if self.is_output_connected (o): self.outputs[o].props = self.prop_manager.get_properties (o)
        return not failed

    def flush_messages (self):
        def pending_events ():
            ev = self.conn.poll_for_event ()
            while ev:
                yield ev
                ev = self.conn.poll_for_event ()
        for ev in pending_events ():
            if isinstance (ev, xcb.randr.ScreenChangeNotifyEvent): print ("ScreenChange")
            if isinstance (ev, xcb.randr.NotifyEvent):
                if ev.subCode == xcb.randr.Notify.CrtcChange: print ("CrtcChange[%d]" % ev.u.cc.crtc)
                if ev.subCode == xcb.randr.Notify.OutputChange: print ("OutputChange[%d]" % ev.u.oc.output)
                if ev.subCode == xcb.randr.Notify.OutputProperty: print ("OutputProperty[%d]" % ev.u.op.output)

    # export part
    def is_output_enabled (self, o):
        c = self.outputs[o].crtc
        return c in self.crtcs and self.crtcs[c].mode != 0
    def mode_by_id (self, i):
        for mode in self.screen_res.modes:
            if mode.id == i: return mode
        raise RandrError ("mode %d not found" % i)
    def to_concrete_layout (self):
        connected_output_ids = [i for i in self.outputs if self.outputs[i].connection == xcb.randr.Connection.Connected]
        concrete = layout.ConcreteLayout ([self.outputs[i].name for i in connected_output_ids])
        for i in connected_output_ids:
            xcb_output = self.outputs[i]
            layout_output = concrete.outputs[xcb_output.name]
            layout_output.edid, layout_output.enabled = xcb_output.props["EDID"], self.is_output_enabled (i)
            if layout_output.enabled:
                crtc = self.crtcs[output.crtc]
                mode = self.mode_by_id (crtc.mode)
                layout_output.base_size = layout.Pair (mode.width, mode.height)
                layout_output.position = layout.Pair (crtc.x, crtc.y)
                layout_output.transposed, layout_output.rotation = False, 0



### EXPERIMENTAL
#def move_down (self):
#    # Change crtc
#    data = self.conn.randr.GetCrtcInfo (64, self.screen_res.config_timestamp).reply ()
#    print (self.conn.randr.SetCrtcConfig (64, self.screen_res.timestamp, self.screen_res.config_timestamp,
#            0, 900, data.mode, data.rotation, data.num_outputs, data.outputs).reply ().status)
#
#    # Change screen size
#    dpi = (25.4 * self.screen_setup.width_in_pixels) / self.screen_setup.width_in_millimeters
#    print ("dpi %f" % dpi)
#    self.conn.randr.SetScreenSize (self.root, 1920, 1980, 1920 * 25.4 / dpi, 1980 * 25.4 / dpi)
#    self.conn.flush ()


##################
# Xrandr helpers #
##################

def check_reply (reply, restart = False):
    """ Check a Xcb reply with a status field (for error or for outdated timestamps) """
    if reply.status == xcb.randr.SetConfig.Failed: raise RandrError ("request failed")
    elif reply.status != xcb.randr.SetConfig.Success: return (reply, True)
    else: return (reply, restart)

class Transform (object):
    """
    Xcb : reflections (xy), then trigo rotation : (rx, ry, rot), as a bitmask (xcb.randr.Rotation)
    Slam : reflect x, then trigo rotation : (rx, rot)
    """
    xcb_masks = dict ([(r, getattr (xcb.randr.Rotation, "Rotate_" + str (r))) for r in layout.Transform.rotations])

    @staticmethod
    def xcb_to_slam (mask):
        rx, ry = bool (mask & xcb.randr.Rotation.Reflect_X), bool (mask & xcb.randr.Rotation.Reflect_Y)
        try: [rot] = [r for r, m in Transform.xcb_masks.items () if m & mask]
        except: raise RandrError ("output has no rotation flag")


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
        """ Backlight Xcb property (value, lowest, highest) """
        # Data : backlight value
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): return None

        if not (data.format > 0 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items == 1): raise RandrError ("invalid BACKLIGHT value formatting")
        (value,) = struct.unpack_from ({ 8: "b", 16: "h", 32: "i" } [data.format], bytearray (data.data))
        
        # Config : backlight value range
        config = self.conn.randr.QueryOutputProperty (output, prop_atom).reply ()
        if not (config.range and len (config.validValues) == 2): raise RandrError ("invalid BACKLIGHT config")
        lowest, highest = config.validValues
        if not (lowest <= value and value <= highest): raise RandrError ("BACKLIGHT value out of bounds")
        
        return (value, lowest, highest)

    def get_edid (self, output, prop_atom):
        """ EDID (unique device identifier) Xcb property (str) """
        # Data
        data = self.conn.randr.GetOutputProperty (output, prop_atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if Properties.not_found (data): raise RandrError ("EDID property not found")
        if not (data.format == 8 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items > 0): raise RandrError ("invalid EDID value formatting")
        return ''.join (["%x" % b for b in data.data])

#############################
# Xrandr state pretty print #
#############################

def iterable_str (iterable, func_highlight = lambda e: False, func_str = str):
    """ Stringify an iterable object, highlighting some elements depending on func_highlight. """
    return " ".join (["[%s]" % func_str (v) if func_highlight (v) else func_str (v) for v in iterable])

def class_attrs_iterable_str (class_name, func_filter_attr, func_highlight = lambda e: False):
    """ Stringify class constants, filter only a part of them, and print them with highlighting """
    func_keep_attr = lambda a: not callable (a) and not a.startswith ('__') and func_filter_attr (getattr (class_name, a))
    attrs = [attr for attr in dir (class_name) if func_keep_attr (attr)]
    return iterable_str (attrs, lambda a: func_highlight (getattr (class_name, a)))

def print_state (state):
    """ Pretty prints the Xcb state copy """
    # Screen
    print ("Screen: %dx%d" % (state.screen_setup.width_in_pixels, state.screen_setup.height_in_pixels))
    # Modes
    for mode in state.screen_res.modes:
        mode_flags = "" #class_attr (xcb.randr.ModeFlag, lambda a: True)
        freq = mode.dot_clock / (mode.htotal * mode.vtotal)
        formatting = "\tMode %d  \t%dx%d  \t%f\t%s"
        args = mode.id, mode.width, mode.height, freq, mode_flags
        print (formatting % args)
    # Crtc
    for c in state.screen_res.crtcs:
        info = state.crtcs[c]
        print ("\tCRTC %d" % c)
        print ("\t\t%dx%d+%d+%d" % (info.width, info.height, info.x, info.y))
        print ("\t\tOutput[active]: %s" % iterable_str (info.possible, lambda o: o in info.outputs))
        has_rot = lambda r: r & info.rotations
        rot_enabled = lambda r: r & info.rotation
        print ("\t\tRotations[current]: %s" % class_attrs_iterable_str (xcb.randr.Rotation, has_rot, rot_enabled))
        print ("\t\tMode: %d" % info.mode)
    # Outputs
    for o in state.screen_res.outputs:
        info = state.outputs[o]
        conn_status = class_attrs_iterable_str (xcb.randr.Connection, lambda c: c == info.connection)
        print ("\tOutput %d %s (%s)" % (o, info.name, conn_status))
        if info.connection == xcb.randr.Connection.Connected:
            print ("\t\tPhy size: %dmm x %dmm" % (info.mm_width, info.mm_height))
            print ("\t\tCrtcs[active]: %s" % iterable_str (info.crtcs, lambda c: c == info.crtc))
            print ("\t\tClones: %s" % iterable_str (info.clones))
            mode_id_str = lambda i: str (info.modes[i])
            mode_id_preferred = lambda i : i < info.num_preferred
            print ("\t\tModes[pref]: %s" % iterable_str (range (len (info.modes)), mode_id_preferred, mode_id_str))
            print ("\t\tProperties:\n" + "\n".join (["\t\t\t" + name + ": "  + str (prop) for name, prop in info.props.items ()]))
