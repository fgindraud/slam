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
Frontend
'''

import sys
import os
import io
import signal
import errno
import logging

from . import util
from . import layout
from . import xcb_backend

def default_configuration (config_dict):
    """ Complete the config dict with default setup """ 
    def ensure_path_writable (path):
        dir_path = os.path.dirname (path)
        if dir_path != "":
            os.makedirs (dir_path, exist_ok = True)

    default_working_dir = "~/.config/slam/"

    # Logging
    if config_dict.setdefault ("log_file", default_working_dir + "log") is not None:
        ensure_path_writable (config_dict["log_file"])
    config_dict.setdefault ("log_level", logging.INFO)

    # Database
    config_dict.setdefault ("db_file", default_working_dir + "database")
    ensure_path_writable (config_dict["db_file"])

    # Backend
    config_dict.setdefault ("backend_module", xcb_backend)
    config_dict.setdefault ("backend_args", {})

def start (**config):
    """
    Start the daemon.

    Config parameters : see slam.default_configuration
    """
    default_configuration (config)
    logger = util.setup_root_logging (config["log_file"], config["log_level"])

    config_manager = layout.Manager ()

    # Try loading database file.
    # On failure we will just have an empty database, and start from zero.
    db_file = config["db_file"]
    try:
        with io.FileIO (db_file, "r") as db:
            config_manager.load (io.FileIO (db_file, "r"))
            logger.info ("loaded database from '{}'".format (db_file))
    except FileNotFoundError:
        logger.warn ("database file '{}' not found".format (db_file))
    except Exception as e:
        logger.error ("unable to load database file '{}': {}".format (db_file, e))

    # Launch backend and event loop
    # Ensure we will write the database at exit :
    #   * finally block will catch normal end and exceptions
    #   * signal handler for SIGTERM will call exit, which uses an exception
    try:
        def sigterm_handler (sig, stack):
            sys.exit ()
        signal.signal (signal.SIGTERM, sigterm_handler)

        backend = config["backend_module"].Backend (**config["backend_args"])
        try:
            config_manager.start (backend)
            util.Daemon.event_loop (backend)
        finally:
            backend.cleanup ()

    except Exception:
        logger.exception ("fatal error")
    finally:
        with io.FileIO (db_file, "w") as db:
            config_manager.store (db)
            logger.info ("stored database into '{}'".format (db_file))

