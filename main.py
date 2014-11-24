#!/usr/bin/env python

# Copyright (c) 2013-2015 Francois GINDRAUD
# 
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

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
    def __init__ (self, backend):
        self.backend = backend
    def fileno (self): return sys.stdin.fileno ()
    def activate (self):
        """ Pick one line a time, and check for keywords """
        line = sys.stdin.readline ()
        if "backend" in line: print (self.backend.dump ())
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
            config_manager.load (io.FileIO (db_file, "r"))
    except FileNotFoundError:
        logger.warn ("database file '{}' not found".format (db_file))
    except layout.DatabaseLoadError as e:
        logger.error ("database file '{}' unreadable: {}".format (db_file, e))
   
    try:
        with xcb_backend.Backend (dpi=96) as backend:
            cmd = StdinCmd (backend)
            config_manager.start (backend)
            util.Daemon.event_loop (backend, cmd)
    finally:
        # Store database in any case
        with io.FileIO (db_file, "w") as db:
            logger.info ("storing layouts into '{}'".format (db_file))
            config_manager.store (db)
