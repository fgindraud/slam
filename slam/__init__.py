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

# Config and start

def default_configuration (config_dict):
    from pathlib import Path
    import logging
    from . import xcb_backend
    """
    Complete the config dict with default setup.
    Also normalize Paths to use pathlib.
    """

    default_working_dir = Path.home ().joinpath(".config", "slam")
    def normalize_or_default_path (key, default_path):
        f = config_dict.get (key)
        if f is None:
            f = default_path
        else:
            f = Path (f)
        f.parent.mkdir (parents=True, exist_ok=True)
        config_dict[key] = f

    # Logging
    normalize_or_default_path ("log_file", default_working_dir.joinpath ("log"))
    config_dict.setdefault ("log_level", logging.INFO)

    # Database
    normalize_or_default_path ("db_file", default_working_dir.joinpath ("database"))

    # Backend
    config_dict.setdefault ("backend_module", xcb_backend)
    config_dict.setdefault ("backend_args", {})

    # Oneshot mode (start, apply config, stop)
    config_dict.setdefault ("oneshot", False)

def start (**config):
    """
    Start the daemon.

    Config parameters : see slam.default_configuration
    """
    from . import util
    from . import layout

    default_configuration (config)
    logger = util.setup_root_logging (config["log_file"], config["log_level"])
    logger.info ("SESSION START")

    # Try loading database file.
    # On failure we will just have an empty database, and start from zero.
    config_manager = layout.Manager (config["db_file"])

    # Launch backend and event loop
    # db_file is written at each modification of database to avoid failures
    try:
        backend = config["backend_module"].Backend (**config["backend_args"])
        try:
            config_manager.start (backend)
            if not config["oneshot"]:
                util.Daemon.event_loop (backend)
        except Exception:
            # Log backend detailed state in case of error
            logger.error ("logging backend state:\n" + backend.dump ())
            raise
        finally:
            backend.cleanup ()

    except Exception:
        # Log all top level errors
        logger.exception ("fatal error")
    finally:
        logger.info ("SESSION END")

