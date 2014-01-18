#!/usr/bin/env python2
"""
Daemon to manage multi monitors
"""

import sys, os, select
import xcb, xcb.xproto, xcb.randr

# Xcb
class XRandr:
    def __init__ (self, display=''):
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

    def check_randr_version (self):
        expected = 1, 2
        version_reply = self.randr.QueryVersion (*expected).reply ()
        version = version_reply.major_version, version_reply.minor_version
        if (not version >= expected):
            text = "RandR version: needs >= {0[0]}.{0[1]}, got {1[0]}.{1[1]}".format (expected, version)
            raise Exception (text)

    def event_screen_change (self, ev): # screen-wide configuration change (includes ctrc & output_change)
        print ('ScreenChange')
    def event_crtc_change (self, ev): # TODO
        print ('CrtcChange')
    def event_output_change (self, ev): # output remove, add, or conf change
        print ('OutputChange')
    def event_output_property (self, ev): # output local property change
        print ('OutputProperty')

# Main event loop
def event_loop (object_list):
    """
    Use select to wait for objects representing FD ressources.
    Requires for each object:
        fileno () method
        activate () method
    """
    while True:
        activated, _, _ = select.select (object_list, [], [])
        for obj in activated:
            obj.activate ()

# Entry point
if __name__ == "__main__":
    xconn = XRandr ()
    try:
        event_loop ([xconn])
    finally:
        xconn.cleanup ()
    sys.exit (0)
