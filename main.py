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
    """Command line testing tool"""
    def __init__ (self, backend):
        self.backend = backend
    
    def fileno (self):
        return sys.stdin.fileno ()
    
    def activate (self):
        """Check for keywords in the next line"""
        line = sys.stdin.readline ()
        if "backend" in line:
            print (self.backend.dump ())
        if "exit" in line:
            return False
        return True

# Config
log_file = "slam.log"
db_file = "database"

# Entry point
if __name__ == "__main__":
    logger = util.setup_root_logging (log_file)
    
    config_manager = layout.Manager ()

    # Try loading database file.
    # On failure we will just have an empty database, and start from zero.
    try:
        with io.FileIO (db_file, "r") as db:
            config_manager.load (io.FileIO (db_file, "r"))
            logger.info ("loaded database from '{}'".format (db_file))
    except FileNotFoundError:
        logger.warn ("database file '{}' not found".format (db_file))
    except Exception as e:
        logger.error ("unable to load database file '{}': {}".format (db_file, e))
   
    # Launch backend and event loop, and ensure we will write the database at exit
    try:
        with xcb_backend.Backend (dpi=96) as backend:
            cmd = StdinCmd (backend)
            config_manager.start (backend)
            util.Daemon.event_loop (backend, cmd)
    except Exception:
        logger.exception ("fatal error")
    finally:
        with io.FileIO (db_file, "w") as db:
            config_manager.store (db)
            logger.info ("stored database into '{}'".format (db_file))
