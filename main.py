#!/usr/bin/env python2
"""
Daemon to manage multi monitors
"""

import sys, os
import xcb, xcb.xproto, xcb.randr

# Stuff
class DoStuff:
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


    def check_randr_version (self):
        expected = (1, 2)
        version_reply = self.randr.QueryVersion (*expected).reply ()
        version = (version_reply.major_version, version_reply.minor_version)
        if (not version >= expected):
            text = "RandR version: needs >= {0[0]}.{0[1]}, got {1[0]}.{1[1]}".format (expected, version)
            raise Exception (text)

    def loop (self):
        return
        while True:
            try:
                event = self.conn.wait_for_event ()
            except xcb.ProtocolException as e:
                print "Protocol error %s received!" % e.__class__.__name__
                break
            finally:
                self.conn.disconnect ()

# Entry point
if __name__ == "__main__":
    xconn = DoStuff ()
    xconn.loop ()
    sys.exit (0)
