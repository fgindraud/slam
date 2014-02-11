#!/usr/bin/env python2
'''
Daemon to manage multi monitors

Wanted features:
* Automatically use monitor on connection
    * First : basic system, just put it on right or left in default mode
    * After : Use EDID to match configs
        * First plug in : add it on right or left, then save config based on current state
        * After : select a config according to set of EDID in the system
    * Config : output tree, primary + right/up/left/bottom, alignement to parent monitor
* Manual adjustement dbus calls
    * For now guess from current config
* Backlight management
    * Manage backlight values (scaling log/lin, ...) of every monitor with backlight (> config)
    * Dbus calls to increase/decrease backlight
    * Dbus calls to set again hardware values to soft ones (and call that from ACPI handler after lid button or power cord change, because this is sometimes messed up)
* Background image management based on config

* Config: set_of_edid + set_of_flags (train, work, ...)
'''

import sys, os, select, struct
import xcb, xcb.xproto, xcb.randr
import time

def set_to_text (values, highlight = None, str_f = str):
    text_parts = []
    if highlight: text_parts = ["[%s]" % str_f (val) if highlight (val) else str_f (val) for val in values]
    else: text_parts = [str_f (val) for val in values]
    return ' '.join (text_parts)

def class_attr (className, showAttr, highlight = None):
    keep_attr = lambda a: not callable (a) and not a.startswith ('__') and showAttr (getattr (className, a))
    attrs = [attr for attr in dir (className) if keep_attr (attr)]
    
    if highlight: return set_to_text (attrs, lambda a: highlight (getattr (className, a)))
    else: return set_to_text (attrs)

# Xcb
def randr_check (val, restart):
    if val.status == xcb.randr.SetConfig.Failed: raise Exception ("Randr: request failed")
    elif val.status != xcb.randr.SetConfig.Success: return (val, True)
    else: return (val, restart)

class XPropBacklight:
    atom = "BACKLIGHT"
    def __init__ (self, atom, output, conn):
        # Config (for range bounds)
        config = conn.QueryOutputProperty (output, atom).reply ()
        if not (config.range and len (config.validValues) == 2): raise Exception ("Randr: invalid BACKLIGHT config")
        self.lowest, self.highest = config.validValues[0], config.validValues[1]
        # Data
        data = conn.GetOutputProperty (output, atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if data.format == 0 and data.type == xcb.xproto.Atom._None and data.bytes_after == 0 and data.num_items == 0:
            raise Exception ("Randr: BACKLIGHT property not found")
        if not (data.format > 0 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items == 1):
            raise Exception ("Randr: invalid BACKLIGHT value formatting")
        if data.format == 8: (self.value,) = struct.unpack_from ("b", bytearray (data.data))
        if data.format == 16: (self.value,) = struct.unpack_from ("h", bytearray (data.data))
        if data.format == 32: (self.value,) = struct.unpack_from ("i", bytearray (data.data))
        if not (self.lowest <= self.value and self.value <= self.highest): raise Exception ("Randr: BACKLIGHT value out of bounds")
    def __str__ (self):
        return "BACKLIGHT: %d [%d-%d]" % (self.value, self.lowest, self.highest)

class XPropEDID:
    atom = "EDID"
    def __init__ (self, atom, output, conn):
        # ignore config
        data = conn.GetOutputProperty (output, atom, xcb.xproto.GetPropertyType.Any, 0, 10000, False, False).reply ()
        if data.format == 0 and data.type == xcb.xproto.Atom._None and data.bytes_after == 0 and data.num_items == 0:
            raise Exception ("Randr: EDID property not found")
        if not (data.format == 8 and data.type == xcb.xproto.Atom.INTEGER and data.bytes_after == 0 and data.num_items > 0):
            raise Exception ("Randr: invalid EDID value formatting") # EDID format, be strict
        self.string = ''.join (["%x" % b for b in data.data])
    def __str__ (self):
        return "EDID:" + self.string

class XOutputProperties:
    prop_classes = [XPropBacklight, XPropEDID]
    properties = dict ((getattr (c, "atom"), c) for c in prop_classes)
    def __init__ (self):
        for prop in XOutputProperties.properties:
            self.__dict__[prop] = None
    def insert (self, prop_name, atom, output, conn):
        if prop_name in XOutputProperties.properties:
            self.__dict__[prop_name] = XOutputProperties.properties[prop_name] (atom, output, conn)
    def info (self):
        return [str (self.__dict__[prop]) for prop in XOutputProperties.properties if self.__dict__[prop]]

class XRandrClient:
    '''
    RandR client, storing the connection to X server.
    '''
    randr_version = 1, 3

    def __init__ (self, display=None, screen=0):
        # Connection
        self.conn = xcb.connect (display=display)
        
        # Randr init
        self.randr = self.conn (xcb.randr.key)
        version_reply = self.randr.QueryVersion (*XRandrClient.randr_version).reply ()
        version = version_reply.major_version, version_reply.minor_version
        if (not version >= XRandrClient.randr_version):
            msg_format = "RandR version: requested >= {0[0]}.{0[1]}, got {1[0]}.{1[1]}"
            raise Exception (msg_format.format (XRandrClient.randr_version, version))

        # Internal state
        self.screen = screen
        self.update_state ()
        
        # Randr register for events
        masks = xcb.randr.NotifyMask.ScreenChange | xcb.randr.NotifyMask.CrtcChange
        masks |= xcb.randr.NotifyMask.OutputChange | xcb.randr.NotifyMask.OutputProperty
        self.randr.SelectInput (self.root, masks)
        self.conn.flush ()
    
    def fileno (self): return self.conn.get_file_descriptor ()
    def cleanup (self): self.conn.disconnect ()

    def pending_events (self):
        ev = self.conn.poll_for_event ()
        while ev:
            yield ev
            ev = self.conn.poll_for_event ()
    def activate (self):
        # Get events (now just print info)
        for ev in self.pending_events ():
            if isinstance (ev, xcb.randr.ScreenChangeNotifyEvent): print ("ScreenChange")
            if isinstance (ev, xcb.randr.NotifyEvent):
                if ev.subCode == xcb.randr.Notify.CrtcChange: print ("CrtcChange[%d]" % ev.u.cc.crtc)
                if ev.subCode == xcb.randr.Notify.OutputChange: print ("OutputChange[%d]" % ev.u.oc.output)
                if ev.subCode == xcb.randr.Notify.OutputProperty: print ("OutputProperty[%d]" % ev.u.op.output)
        # Update whole state
        self.update_state ()
        return True

    def update_state (self):
        ''' Reloads everything, not efficient but simple '''
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
            self.screen_res = self.randr.GetScreenResourcesCurrent (self.root).reply ()
            # Crtc and Outputs
            crtc_req = dict ()
            output_req = dict ()
            for c in self.screen_res.crtcs: crtc_req[c] = self.randr.GetCrtcInfo (c, self.screen_res.config_timestamp)
            for o in self.screen_res.outputs: output_req[o] = self.randr.GetOutputInfo (o, self.screen_res.config_timestamp)
            for c in self.screen_res.crtcs: self.crtcs[c], restart = randr_check (crtc_req[c].reply (), restart)
            for o in self.screen_res.outputs:
                self.outputs[o], restart = randr_check (output_req[o].reply (), restart)
                self.outputs[o].name = str (bytearray (self.outputs[o].name))
            # Properties (only some of them are watched)
            op_atoms_req = dict ()
            for o in self.screen_res.outputs: op_atoms_req[o] = self.randr.ListOutputProperties (o)
            for o in self.screen_res.outputs:
                self.outputs[o].props = XOutputProperties ()
                for atom in op_atoms_req[o].reply ().atoms:
                    name = str (bytearray (self.conn.core.GetAtomName (atom).reply ().name))
                    self.outputs[o].props.insert (name, atom, o, self.randr)

    def screen_info (self):
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
            print ("\t\tOutput[active]: %s" % set_to_text (info.possible, lambda o: o in info.outputs))
            has_rot = lambda r: r & info.rotations
            rot_enabled = lambda r: r & info.rotation
            print ("\t\tRotations[current]: %s" % class_attr (xcb.randr.Rotation, has_rot, rot_enabled))
            print ("\t\tMode: %d" % info.mode)
        # Outputs
        for o in self.screen_res.outputs:
            info = self.outputs[o]
            conn_status = class_attr (xcb.randr.Connection, lambda c: c == info.connection)
            print ("\tOutput %d %s (%s)" % (o, info.name, conn_status))
            if info.connection == xcb.randr.Connection.Connected:
                print ("\t\tPhy size: %dmm x %dmm" % (info.mm_width, info.mm_height))
                print ("\t\tCrtcs[active]: %s" % set_to_text (info.crtcs, lambda c: c == info.crtc))
                print ("\t\tClones: %s" % set_to_text (info.clones))
                str_f = lambda i: str (info.modes[i])
                is_preferred = lambda i : i < info.num_preferred
                print ("\t\tModes[pref]: %s" % set_to_text (range (len (info.modes)), is_preferred, str_f))
                print ("\t\tProperties:\n" + "\n".join (["\t\t\t" + s for s in info.props.info ()]))


    ## EXPERIMENTAL
    def move_down (self):
        res = self.randr.GetScreenResourcesCurrent (self.root_window).reply ()
        
        # Change crtc
        data = self.randr.GetCrtcInfo (64, res.config_timestamp).reply ()
        print (self.randr.SetCrtcConfig (64, res.timestamp, res.config_timestamp,
                0, 900, data.mode, data.rotation, data.num_outputs, data.outputs).reply ().status)

        # Change screen size
        dpi = (25.4 * self.screen.width_in_pixels) / self.screen.width_in_millimeters
        print ("dpi %f" % dpi)
        self.randr.SetScreenSize (self.root_window, 1920, 1980, 1920 * 25.4 / dpi, 1980 * 25.4 / dpi)
        self.conn.flush ()

# Commands
class StdinCmd:
    def __init__ (self, randr):
        self.randr = randr
    def fileno (self):
        return sys.stdin.fileno ()
    def activate (self):
        line = sys.stdin.readline ()
        if "info" in line: self.randr.screen_info ()
        if "test" in line: self.randr.move_down ()
        if "exit" in line: return False
        return True

# Main event loop
def event_loop (object_list):
    '''
    Use select to wait for objects representing FD ressources.
    Requires for each object:
        int fileno () method
        bool activate () method : returning False stops the loop
    '''
    while True:
        activated, _, _ = select.select (object_list, [], [])
        for obj in activated:
            if not obj.activate (): return

# Entry point
if __name__ == "__main__":
    xclient = XRandrClient ()
    cmd = StdinCmd (xclient)
    try:
        event_loop ([xclient, cmd])
    finally:
        xclient.cleanup ()
    sys.exit (0)
