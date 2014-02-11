#!/usr/bin/env python2
"""
XCB interface part of the multi monitor daemon.
- Keeps a valid copy of the xrandr state (updating it on events)
- Can generate and apply configurations from this state
- Signal the config manager when the current state changed
"""

import struct # To pack or unpack data from xcb requests
import xcb, xcb.xproto, xcb.randr

##################
# Xcb properties #
##################

def prop_value_not_found (reply):
    return reply.format == 0 and reply.type == xcb.xproto.Atom._None and reply.bytes_after == 0 and reply.num_items == 0

class PropBacklight (object):
    """ Backlight Xcb property """
    atom = "BACKLIGHT"
    def __init__ (self, atom, output, conn):
        """ Constructs the backlight property by querying the Xcb randr connection conn for values """
        
        # Config : backlight value range
        config = conn.randr.QueryOutputProperty (output, atom).reply ()
        if not (config.range and len (config.validValues) == 2): raise Exception ("Randr: invalid BACKLIGHT config")
        self.lowest, self.highest = config.validValues[0], config.validValues[1]

        # Data : backlight value
        data = conn.randr.GetOutputProperty (output, atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if prop_value_not_found (data): raise Exception ("Randr: BACKLIGHT property not found")
        if not (data.format > 0 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items == 1):
            raise Exception ("Randr: invalid BACKLIGHT value formatting")
        
        if data.format == 8: (self.value,) = struct.unpack_from ("b", bytearray (data.data))
        elif data.format == 16: (self.value,) = struct.unpack_from ("h", bytearray (data.data))
        elif data.format == 32: (self.value,) = struct.unpack_from ("i", bytearray (data.data))
        else: raise Exception ("Randr: invalid BACKLIGHT value formatting")
        
        if not (self.lowest <= self.value and self.value <= self.highest): raise Exception ("Randr: BACKLIGHT value out of bounds")

    def __str__ (self):
        return "BACKLIGHT: %d [%d-%d]" % (self.value, self.lowest, self.highest)

class PropEDID (object):
    """ EDID (unique device identifier) Xcb property """
    atom = "EDID"
    def __init__ (self, atom, output, conn):
        """ Constructs the backlight property by querying the Xcb randr connection conn for values """
        # Config : ignore
        # Data
        data = conn.randr.GetOutputProperty (output, atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if prop_value_not_found (data): raise Exception ("Randr: EDID property not found")
        if not (data.format == 8 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items > 0):
            raise Exception ("Randr: invalid EDID value formatting")
        self.str = ''.join (["%x" % b for b in data.data])

    def __str__ (self):
        return "EDID:" + self.str

class OutputProperties:
    """
    Store the set of properties for an output
    Uses the Prop* classes to query the properties themselves, depending on the atom name
    """
    prop_classes = [PropBacklight, PropEDID]
    properties = dict ((getattr (c, "atom"), c) for c in prop_classes) # Dynamic dict of atom names to prop classes

    def __init__ (self, output, conn):
        """
        Fill the class with properties of the given output, by querying the connection conn
        Each property named 'name' will be available as class.name if present
        """
        for atom in conn.randr.ListOutputProperties (output).reply ().atoms:
            name = str (bytearray (conn.core.GetAtomName (atom).reply ().name))
            if name in OutputProperties.properties: # Add prop if tracked
                self[name] = OutputProperties.properties[name] (atom, output, conn)
    
    def __setitem__ (self, key, value): self.__dict__[key] = value
    def __getitem__ (self, key): return self.__dict__[key]
    def __contains__ (self, key): return key in self.__dict__
    def __iter__ (self): return iter (self.__dict__)
    
    def info (self):
        """ Return list of text version of properties """
        return [str (self[prop]) for prop in self]

######################
# Pretty print utils #
######################

def iterable_str (iterable, func_highlight = lambda e: False, func_str = str):
    """ Stringify an iterable object, highlighting some elements depending on func_highlight. """
    return ' '.join (["[%s]" % func_str (v) if func_highlight (v) else func_str (v) for v in iterable])

def class_attrs_iterable_str (class_name, func_filter_attr, func_highlight = lambda e: False):
    """ Stringify class constants, filter only a part of them, and print them with highlighting """
    func_keep_attr = lambda a: not callable (a) and not a.startswith ('__') and func_filter_attr (getattr (class_name, a))
    attrs = [attr for attr in dir (class_name) if func_keep_attr (attr)]
    return iterable_str (attrs, lambda a: func_highlight (getattr (class_name, a)))

#################
# Xrandr Client #
#################

def check_reply (reply, restart = False):
    """ Check a Xcb reply with a status field (for error or for outdated timestamps) """
    if reply.status == xcb.randr.SetConfig.Failed: raise Exception ("Randr: request failed")
    elif reply.status != xcb.randr.SetConfig.Success: return (reply, True)
    else: return (reply, restart)

class Client (object):
    """
    RandR client. Stores the connection to X server, and keeps a copy of the randr screen state.
    """
    randr_version = 1, 3

    def __init__ (self, display=None, screen=0):
        """
        Starts connection, and construct the state.
        display is the possible display name
        screen is the screen number
        """
        # Connection
        self.conn = xcb.connect (display=display)
        
        # Randr init
        self.conn.randr = self.conn (xcb.randr.key)
        version_reply = self.conn.randr.QueryVersion (*Client.randr_version).reply ()
        version = version_reply.major_version, version_reply.minor_version
        if (not version >= Client.randr_version):
            msg_format = "RandR version: requested >= {0[0]}.{0[1]}, got {1[0]}.{1[1]}"
            raise Exception (msg_format.format (Client.randr_version, version))

        # Internal state
        self.screen = screen
        self.update_state ()
        
        # Randr register for events
        masks = xcb.randr.NotifyMask.ScreenChange | xcb.randr.NotifyMask.CrtcChange
        masks |= xcb.randr.NotifyMask.OutputChange | xcb.randr.NotifyMask.OutputProperty
        self.conn.randr.SelectInput (self.root, masks)
        self.conn.flush ()
    
    def fileno (self): return self.conn.get_file_descriptor ()
    def cleanup (self): self.conn.disconnect ()

    def pending_events (self):
        """ Iterable with list of pending events """
        ev = self.conn.poll_for_event ()
        while ev:
            yield ev
            ev = self.conn.poll_for_event ()

    def activate (self):
        """
        Call when a new event arrives.
        Will process events and update the state.
        """
        # Get events (now just print info)
        for ev in self.pending_events ():
            if True:
                if isinstance (ev, xcb.randr.ScreenChangeNotifyEvent): print ("ScreenChange")
                if isinstance (ev, xcb.randr.NotifyEvent):
                    if ev.subCode == xcb.randr.Notify.CrtcChange: print ("CrtcChange[%d]" % ev.u.cc.crtc)
                    if ev.subCode == xcb.randr.Notify.OutputChange: print ("OutputChange[%d]" % ev.u.oc.output)
                    if ev.subCode == xcb.randr.Notify.OutputProperty: print ("OutputProperty[%d]" % ev.u.op.output)
        # Update whole state
        self.update_state ()
        return True

    def update_state (self):
        """
        Updates the state.
        For now, it reloads everything, which is not efficient but simple.
        Efficiency is not a big problem as randr events are seldom.
        """
        restart = True
        while restart:
            restart = False
            # Clean everything
            self.screen_setup = None
            self.root = None
            self.screen_res = None
            self.crtcs = dict ()
            self.outputs = dict ()
            # Setup
            self.screen_setup = self.conn.get_setup ().roots[self.screen]
            self.root = self.screen_setup.root
            # Screen ressources
            self.screen_res = self.conn.randr.GetScreenResourcesCurrent (self.root).reply ()
            # Crtc and Outputs
            crtc_req = dict ()
            output_req = dict ()
            for c in self.screen_res.crtcs: crtc_req[c] = self.conn.randr.GetCrtcInfo (c, self.screen_res.config_timestamp)
            for o in self.screen_res.outputs: output_req[o] = self.conn.randr.GetOutputInfo (o, self.screen_res.config_timestamp)
            for c in self.screen_res.crtcs: self.crtcs[c], restart = check_reply (crtc_req[c].reply (), restart)
            for o in self.screen_res.outputs:
                self.outputs[o], restart = check_reply (output_req[o].reply (), restart)
                self.outputs[o].name = str (bytearray (self.outputs[o].name))
            # Properties (only some of them are watched)
            for o in self.screen_res.outputs: self.outputs[o].props = OutputProperties (o, self.conn)

    def state_info (self):
        """ Pretty prints the Xcb state copy """
        # Screen
        print ("Screen: %dx%d" % (self.screen_setup.width_in_pixels, self.screen_setup.height_in_pixels))
        # Modes
        for mode in self.screen_res.modes:
            mode_flags = "" #class_attr (xcb.randr.ModeFlag, lambda a: True)
            freq = mode.dot_clock / (mode.htotal * mode.vtotal)
            formatting = "\tMode %d  \t%dx%d  \t%f\t%s"
            args = mode.id, mode.width, mode.height, freq, mode_flags
            print (formatting % args)
        # Crtc
        for c in self.screen_res.crtcs:
            info = self.crtcs[c]
            print ("\tCRTC %d" % c)
            print ("\t\t%dx%d+%d+%d" % (info.width, info.height, info.x, info.y))
            print ("\t\tOutput[active]: %s" % iterable_str (info.possible, lambda o: o in info.outputs))
            has_rot = lambda r: r & info.rotations
            rot_enabled = lambda r: r & info.rotation
            print ("\t\tRotations[current]: %s" % class_attrs_iterable_str (xcb.randr.Rotation, has_rot, rot_enabled))
            print ("\t\tMode: %d" % info.mode)
        # Outputs
        for o in self.screen_res.outputs:
            info = self.outputs[o]
            conn_status = class_attrs_iterable_str (xcb.randr.Connection, lambda c: c == info.connection)
            print ("\tOutput %d %s (%s)" % (o, info.name, conn_status))
            if info.connection == xcb.randr.Connection.Connected:
                print ("\t\tPhy size: %dmm x %dmm" % (info.mm_width, info.mm_height))
                print ("\t\tCrtcs[active]: %s" % iterable_str (info.crtcs, lambda c: c == info.crtc))
                print ("\t\tClones: %s" % iterable_str (info.clones))
                mode_id_str = lambda i: str (info.modes[i])
                mode_id_preferred = lambda i : i < info.num_preferred
                print ("\t\tModes[pref]: %s" % iterable_str (range (len (info.modes)), mode_id_preferred, mode_id_str))
                print ("\t\tProperties:\n" + "\n".join (["\t\t\t" + s for s in info.props.info ()]))


    ## EXPERIMENTAL
    def move_down (self):
        # Change crtc
        data = self.conn.randr.GetCrtcInfo (64, self.screen_res.config_timestamp).reply ()
        print (self.conn.randr.SetCrtcConfig (64, self.screen_res.timestamp, self.screen_res.config_timestamp,
                0, 900, data.mode, data.rotation, data.num_outputs, data.outputs).reply ().status)

        # Change screen size
        dpi = (25.4 * self.screen_setup.width_in_pixels) / self.screen_setup.width_in_millimeters
        print ("dpi %f" % dpi)
        self.conn.randr.SetScreenSize (self.root, 1920, 1980, 1920 * 25.4 / dpi, 1980 * 25.4 / dpi)
        self.conn.flush ()
