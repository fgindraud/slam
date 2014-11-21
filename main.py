#!/usr/bin/env python
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
'''

import sys

import layout
import xcb_backend
import util

# Commands
class StdinCmd (util.Daemon):
    """ Very simple command line testing tool """
    def __init__ (self, backend, cm):
        self.backend, self.cm = backend, cm
    def fileno (self): return sys.stdin.fileno ()
    def activate (self):
        """ Pick one line a time, and check for keywords """
        line = sys.stdin.readline ()
        if "backend" in line: print (self.backend.dump ())
        if "test" in line: self.cm.test (line)
        if "exit" in line: return False
        return True

# Entry point
if __name__ == "__main__":
    logger = util.setup_root_logging ("slam.log")
    config_manager = layout.Manager ()
    with xcb_backend.Backend (dpi=96) as backend:
        cmd = StdinCmd (backend, config_manager)
        config_manager.start (backend)
        util.Daemon.event_loop (backend, cmd)
        sys.exit (0)
