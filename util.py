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

"""
Utilities
"""

import operator
import select
import logging, logging.handlers

# Logging

def setup_root_logging (filename = None):
    root = logging.getLogger ()
    root.setLevel (logging.DEBUG)
    formatter = logging.Formatter (style = "{", fmt = "{asctime} :: {levelname} :: {name} :: {message}")
    
    if filename:
        file_output = logging.handlers.RotatingFileHandler ("slam.log", "a", 1000000, 1)
        file_output.setLevel (logging.DEBUG)
        file_output.setFormatter (formatter)
        root.addHandler (file_output)

    stream_output = logging.StreamHandler ()
    stream_output.setLevel (logging.DEBUG)
    stream_output.setFormatter (formatter)
    root.addHandler (stream_output)

    return root

def setup_logger (module_name):
    return logging.getLogger (module_name)

logger = setup_logger (__name__)

# Pair

class Pair (tuple):
    """ Utility type for a pair of values """
    def __new__ (cls, a, b = None):
        """ Takes a pair of values, or an iterable """
        if b != None: a = (a, b)
        return super (Pair, cls).__new__ (cls, a)
   
    @staticmethod
    def from_struct (st, xkey = "x", ykey = "y"):
        """ Construct a Pair by querying xkey/ykey (default x/y) fields in a structure """
        return Pair (getattr (st, xkey), getattr (st, ykey))
    @staticmethod
    def from_size (st, formatting = "{}"):
        """ Construct a Pair by taking (optionnaly formatted) width/height fields in the given class """
        return Pair.from_struct (st, formatting.format ("width"), formatting.format ("height"))

    def __getattr__ (self, attr):
        """ Provide x/y/w/h quick access """
        if attr in ["x", "w"]: return self[0]
        elif attr in ["y", "h"]: return self[1]
        else: raise AttributeError ("Pair doesn't support '{}' attr (only x/y/w/h)".format (attr))

    def copy (self): return Pair (self)
    def swap (self): return Pair (self.y, self.x)
    def __add__ (self, other): return Pair (self.x + other.x, self.y + other.y)
    def __neg__ (self): return Pair (-self.x, -self.y)
    def __sub__ (self, other): return self + (-other)

    def map (self, func, *others):
        """ Apply func to tuples of firsts and second arguments to [self+others] and build the result """
        return Pair (map (func, self, *others))

    def __format__ (self, spec):
        """ Pretty printing, with two str.format flags for integers sizes """
        if spec == "s": return "{}x{}".format (self.x, self.y)
        elif spec == "p": return "{}mm x {}mm".format (self.x, self.y)
        else: return str (self)

# Daemon

class DaemonLoopException (Exception):
    """ Exception for infinite reactivation loop """
    pass

class Daemon (object):
    """
    Daemon objects that listen to file descriptors and can be activated when new data is available
    A daemon can ask to be reactivated immediately even if no new data is available.
    A counter ensure that reactivations does not loop undefinitely.

    Must be implemented for each subclass :
        int fileno () : returns file descriptor
        bool activate () : do stuff, and returns False to stop the event loop
    """
    def activate_manually (self):
        """ Ask the event loop to activate us again """
        self._flag_to_be_activated = True

    def _to_be_activated (self):
        try: return self._flag_to_be_activated
        except AttributeError: return False

    def _reset_activation_counter (self): self._activation_counter = 0
    def _activate (self):
        try:
            self._activation_counter += 1
            if self._activation_counter > 10:
                raise DaemonLoopException
        except AttributeError: pass # ignore activation counter if not in loop
        return self.activate ()

    @staticmethod
    def event_loop (*daemons):
        """ Start the event loop """
        while True:
            # Activate selected deamons
            map (Daemon._reset_activation_counter, daemons)
            while any (map (Daemon._to_be_activated, daemons)):
                d = next (filter (Daemon._to_be_activated, daemons))
                d._flag_to_be_activated = False
                if d._activate () == False: return
            # Detect fileno-activated deamons
            new_data, _, _ = select.select (daemons, [], [])
            for d in new_data:
                d._flag_to_be_activated = True

# Class introspection and pretty print

def class_attributes (cls):
    """ Return all class attributes (usually class constants) """
    return [attr for attr in dir (cls) if not callable (attr) and not attr.startswith ("__")]

def sequence_stringify (iterable, highlight = lambda t: False, stringify = str):
    """ Print and join all elements of <iterable>, highlighting those matched by <highlight : obj -> bool> """
    def formatting (data):
        return ("[{}]" if highlight (data) else "{}").format (stringify (data))
    return " ".join (map (formatting, iterable))


def class_str (instance):
    return type (instance).__name__ + "(" + ", ".join (map (lambda i: i[0] + "=" + str (i[1]), instance.__dict__.items ())) + ")"

