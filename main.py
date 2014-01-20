#!/usr/bin/env python2
"""
Daemon to manage multi monitors
"""

import sys, os, select
import xcb, xcb.xproto, xcb.randr

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
class XRandr:
    def __init__ (self, display=None):
        # Connection
        self.conn = xcb.connect (display=display)
        
        # randr
        self.randr = self.conn (xcb.randr.key)
        self.check_randr_version ()

        self.screen = self.conn.get_setup ().roots[0]
        self.root_window = self.screen.root
        
        masks = xcb.randr.NotifyMask.ScreenChange | xcb.randr.NotifyMask.CrtcChange
        masks |= xcb.randr.NotifyMask.OutputChange | xcb.randr.NotifyMask.OutputProperty
        self.randr.SelectInput (self.root_window, masks)

        # info on background

        # Flush pending requests
        self.conn.flush ()
    
    def fileno (self): return self.conn.get_file_descriptor ()
    def cleanup (self): self.conn.disconnect ()
    
    def activate (self):
        ev = self.conn.poll_for_event ()
        while ev:
            # Determine randr event type
            if isinstance (ev, xcb.randr.ScreenChangeNotifyEvent): self.event_screen_change (ev)
            elif isinstance (ev, xcb.randr.NotifyEvent):
                if ev.subCode == xcb.randr.Notify.CrtcChange: self.event_crtc_change (ev.u.cc)
                elif ev.subCode == xcb.randr.Notify.OutputChange: self.event_output_change (ev.u.oc)
                elif ev.subCode == xcb.randr.Notify.OutputProperty: self.event_output_property (ev.u.op)
                else: raise Exception ('Unexpected xcb.randr.NotifyEvent subcode %d' % ev.subCode)
            else: raise Exception ('Unexpected X message')
            ev = self.conn.poll_for_event ()
        return True

    def check_randr_version (self):
        expected = 1, 3
        version_reply = self.randr.QueryVersion (*expected).reply ()
        version = version_reply.major_version, version_reply.minor_version
        if (not version >= expected):
            text = "RandR version: needs >= {0[0]}.{0[1]}, got {1[0]}.{1[1]}".format (expected, version)
            raise Exception (text)

    def event_screen_change (self, ev): # screen-wide configuration change (includes ctrc & output_change)
        print ('ev:ScreenChange')
        self.screen = self.conn.get_setup ().roots[0]
    def event_crtc_change (self, ev): # TODO
        print ('ev:CrtcChange')
    def event_output_change (self, ev): # output remove, add, or conf change
        print ('ev:OutputChange')
    def event_output_property (self, ev): # output local property change
        print ('ev:OutputProperty')

    def screen_info (self):
        while True:
            # Request info
            res = self.randr.GetScreenResourcesCurrent (self.root_window).reply ()
            crtc_req = {}
            for crtc in res.crtcs:
                crtc_req[crtc] = self.randr.GetCrtcInfo (crtc, res.config_timestamp)
            output_req = {}
            for output in res.outputs:
                output_req[output] = self.randr.GetOutputInfo (output, res.config_timestamp)

            # Screen
            sizes_pix = self.screen.width_in_pixels, self.screen.height_in_pixels
            sizes_phy = self.screen.width_in_millimeters, self.screen.height_in_millimeters
            print ("Screen {2}: {0[0]}x{0[1]}, {1[0]}mm x {1[1]}mm".format (sizes_pix, sizes_phy, 0))

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
                if info.status != xcb.randr.SetConfig.Success: continue
                print ("\tCRTC %d" % crtc)
                print ("\t\t%dx%d+%d+%d" % (info.width, info.height, info.x, info.y))
                print ("\t\tOutput[active]: %s" % set_to_text (info.possible, lambda o: o in info.outputs))
                has_rot = lambda r: r & info.rotations
                current_rot = lambda r: r == info.rotation
                print ("\t\tRotations[current]: %s" % class_attr (xcb.randr.Rotation, has_rot, current_rot))
                print ("\t\tMode: %d" % info.mode)

            # Outputs
            for output in res.outputs:
                info = output_req[output].reply ()
                if info.status != xcb.randr.SetConfig.Success: continue
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
            break


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
    """
    Use select to wait for objects representing FD ressources.
    Requires for each object:
        int fileno () method
        bool activate () method : returning False stops the loop
    """
    cont = True
    while cont:
        activated, _, _ = select.select (object_list, [], [])
        for obj in activated:
            cont = obj.activate ()

# Entry point
if __name__ == "__main__":
    xconn = XRandr ()
    cmd = StdinCmd (xconn)
    try:
        event_loop ([xconn, cmd])
    finally:
        xconn.cleanup ()
    sys.exit (0)
