#!/usr/bin/env python
'''
Daemon to manage multi monitors
'''

import sys
import io

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

# Config
log_file = "slam.log"
db_file = "database"

# Entry point
if __name__ == "__main__":
    logger = util.setup_root_logging (log_file)
    
    config_manager = layout.Manager ()
    try:
        # Try loading database
        with io.FileIO (db_file, "r") as db:
            logger.info ("loading layouts from '{}'".format (db_file))
            config_manager.load (db)
    except FileNotFoundError:
        logger.warn ("database file '{}' not found".format (db_file))
   
    try:
        with xcb_backend.Backend (dpi=96) as backend:
            cmd = StdinCmd (backend, config_manager)
            config_manager.start (backend)
            util.Daemon.event_loop (backend, cmd)
    finally:
        # Store database in any case
        with io.FileIO (db_file, "w") as db:
            logger.info ("storing layouts into '{}'".format (db_file))
            config_manager.dump (db)
