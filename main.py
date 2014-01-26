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

import sys, os, select
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
class XrandrState:
    '''
    Holds a copy of the current randr state.

    Update policy:
    * root window: assumed constant
    * screen:
        * current size can only be obtained from the screen event, so update sizes on this event
        * maximum size: refresh on ScreenChangeNotifyEvent TODO
    * screenRessources:
        * ScreenChangeNotifyEvent: check if new config_timestamp is different from stored
    * crtcs_info: invalidate specific crtc on CrtcChange
    * outputs_info: invalidate specific output on OutputChange
    * outputs_properties: TODO
    '''
    def __init__ (self, initialScreenData):
        self.root = initialScreenData.root
        # Initial Screen size
        self.screen_size = initialScreenData.width_in_pixels, initialScreenData.height_in_pixels
        self.screen_size_phy = initialScreenData.width_in_millimeters, initialScreenData.height_in_millimeters
        # Valid flags for data
    
    def on_screen_change (self, ev):
        # Update screen sizes
        self.screen_size = ev.width, ev.height
        self.screen_size_phy = ev.mwidth, ev.mheight
        
        print ('ScreenChange (t=%d, ct=%d, size=%dx%d)' % (ev.timestamp, ev.config_timestamp, ev.width, ev.height))
    def on_crtc_change (self, ev):
        print ('CrtcChange (t=%d)' % ev.timestamp)
    def on_output_change (self, ev):
        print ('OutputChange (t=%d, ct=%d)' % (ev.timestamp, ev.config_timestamp))
    def on_output_property (self, ev):
        print ('OutputProperty (t=%d)' % ev.timestamp)

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
        self.state = XrandrState (self.conn.get_setup ().roots[screen])
        
        # Randr register for events
        masks = xcb.randr.NotifyMask.ScreenChange | xcb.randr.NotifyMask.CrtcChange
        masks |= xcb.randr.NotifyMask.OutputChange | xcb.randr.NotifyMask.OutputProperty
        self.randr.SelectInput (self.state.root, masks)
        self.conn.flush ()
    
    def fileno (self): return self.conn.get_file_descriptor ()
    def cleanup (self): self.conn.disconnect ()

    def pending_events (self):
        while True:
            ev = self.conn.poll_for_event ()
            if not ev: return
            yield ev
    def activate (self):
        for ev in self.pending_events ():
            if isinstance (ev, xcb.randr.ScreenChangeNotifyEvent): self.state.on_screen_change (ev)
            elif isinstance (ev, xcb.randr.NotifyEvent):
                if ev.subCode == xcb.randr.Notify.CrtcChange: self.state.on_crtc_change (ev.u.cc)
                elif ev.subCode == xcb.randr.Notify.OutputChange: self.state.on_output_change (ev.u.oc)
                elif ev.subCode == xcb.randr.Notify.OutputProperty: self.state.on_output_property (ev.u.op)
                else: raise Exception ('Unhandled xcb.randr.NotifyEvent subcode %d' % ev.subCode)
            else: raise Exception ('Unexpected X message')
        return True

    def screen_info (self):
        # Request info
        res = self.randr.GetScreenResourcesCurrent (self.state.root).reply ()
        crtc_req = {}
        for crtc in res.crtcs:
            crtc_req[crtc] = self.randr.GetCrtcInfo (crtc, res.config_timestamp)
        output_req = {}
        for output in res.outputs:
            output_req[output] = self.randr.GetOutputInfo (output, res.config_timestamp)

        # Screen
        print ("Screen {2}: {0[0]}x{0[1]}, {1[0]}mm x {1[1]}mm".format (self.state.screen_size, self.state.screen_size_phy, 0))

        # Modes
        for mode in res.modes:
            mode_flags = "" #class_attr (xcb.randr.ModeFlag, lambda a: True)
            freq = mode.dot_clock / (mode.htotal * mode.vtotal)
            formatting = "\tMode %d  \t%dx%d  \t%f\t%s"
            args = mode.id, mode.width, mode.height, freq, mode_flags
            print (formatting % args)
 
        # Crtc
        for crtc in res.crtcs:
            info = crtc_req[crtc].reply ()
            if info.status != xcb.randr.SetConfig.Success: raise Exception ("old config")
            print ("\tCRTC %d" % crtc)
            print ("\t\t%dx%d+%d+%d" % (info.width, info.height, info.x, info.y))
            print ("\t\tOutput[active]: %s" % set_to_text (info.possible, lambda o: o in info.outputs))
            has_rot = lambda r: r & info.rotations
            rot_enabled = lambda r: r & info.rotation
            print ("\t\tRotations[current]: %s" % class_attr (xcb.randr.Rotation, has_rot, rot_enabled))
            print ("\t\tMode: %d" % info.mode)

        # Outputs
        for output in res.outputs:
            info = output_req[output].reply ()
            if info.status != xcb.randr.SetConfig.Success: raise Exception ("old config")
            name = str (bytearray (info.name))
            conn_status = class_attr (xcb.randr.Connection, lambda c: c == info.connection)
            print ("\tOutput %d %s (%s)" % (output, name, conn_status))
            if info.connection == xcb.randr.Connection.Connected:
                print ("\t\tPhy size: %dmm x %dmm" % (info.mm_width, info.mm_height))
                print ("\t\tCrtcs[active]: %s" % set_to_text (info.crtcs, lambda c: c == info.crtc))
                print ("\t\tClones: %s" % set_to_text (info.clones))
                str_f = lambda i: str (info.modes[i])
                is_preferred = lambda i : i < info.num_preferred
                print ("\t\tModes[pref]: %s" % set_to_text (range (len (info.modes)), is_preferred, str_f))

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
    xconn = XRandrClient ()
    cmd = StdinCmd (xconn)
    try:
        event_loop ([xconn, cmd])
    finally:
        xconn.cleanup ()
    sys.exit (0)
