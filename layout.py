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
Layout manager part.
"""

import slam_ext
import sys
import pickle
import util
from util import Pair

logger = util.setup_logger (__name__)

### Utils ###

class TransformException (Exception): pass
class LayoutException (Exception): pass
class BackendError (Exception): pass
class BackendFatalError (Exception): pass

# Directions
Dir = slam_ext.Dir
Dir.invert = slam_ext.Dir_invert
Dir.__str__ = slam_ext.Dir_str

# Transformation
class Transform (object):
    rotations = { 0: False, 90: True, 180: False, 270: True }
    """
    Transformation is internally a reflection on x coordinates followed by a trigonometric rotation
    Externally, rotate(), reflectx/y() return a new transformation based on the current one
    Not modifiable, only creates new instances
    """
    # Init / copy
    def __init__ (self, rx = False, rot = 0): self.reflect, self.rotation = rx, rot
    def copy (self): return Transform (self.reflect, self.rotation)
    
    # Dump / load
    @staticmethod
    def load (data): return Transform (*data)
    def dump (self): return (self.reflect, self.rotation)

    # Derived transformation generators
    def rotate (self, rot):
        if (rot % 360) not in Transform.rotations: raise TransformException ("unsupported rotation")
        return Transform (self.reflect, (self.rotation + rot) % 360)
    def reflectx (self): return Transform (not self.reflect, (self.rotation + 180) % 360 if self.inverted () else self.rotation)
    def reflecty (self): return Transform (not self.reflect, self.rotation if self.inverted () else (self.rotation + 180) % 360)

    # Size conversion / equality / str
    def rectangle_size (self, size): return size.swap () if self.inverted () else size.copy ()
    def inverted (self): return Transform.rotations[self.rotation]
    def __eq__ (self, other): return self.rotation == other.rotation and self.reflect == other.reflect
    def __str__ (self): return ("R" if self.reflect else "") + str (self.rotation)

### AbstractLayout ###

class AbstractLayout (object):
    """
    Abstract Layout model used in the database.

    A layout is a set of outputs (represented by their EDID), their transformations, and relations between them.
    It can represent multiple physical layouts if same outputs are plugged into different plugs.

    Relations are duplicated (a < b && b > a).
    """
    class Output (object):
        # Init / deep copy
        def __init__ (self, **kwd):
            self.transform = kwd.get ("transform", Transform ())
            self.neighbours = kwd.get ("neighbours", {})
        def copy (self):
            return Output (transform = self.transform.copy (), neighbours = self.neighbours.copy ())

        # Load / dump
        @staticmethod
        def load (data): return AbstractLayout.Output (transform = Transform.load (data[0]), neighbours = data[1])
        def dump (self): return (self.transform.dump (), self.neighbours)

        # Get info
        def rel (self, neighbour): return self.neighbours.get (neighbour, Dir.none)
        __str__ = util.class_str

    # Init / deep copy
    def __init__ (self, **kwd): self.outputs = kwd.get ("outputs", {})
    def copy (self): return AbstractLayout (outputs = {edid: o.copy () for edid, o in self.outputs.items ()})
    
    # Load / dump 
    @staticmethod
    def load (data): return AbstractLayout (outputs = {edid: AbstractLayout.Output.load (d) for edid, d in data.items ()})
    def dump (self): return {edid: output.dump () for edid, output in self.outputs.items ()}

    def set_relation (self, edid_a, rel, edid_b):
        if rel == Dir.none:
            # Compress Database by removing Dir.none entries
            del self.outputs[edid_a].neighbours[edid_b]
            del self.outputs[edid_b].neighbours[edid_a]
        else:
            self.outputs[edid_a].neighbours[edid_b] = rel
            self.outputs[edid_b].neighbours[edid_a] = rel.invert ()

    def key (self):
        """ Key for Database is set of edid """
        return frozenset (self.outputs.keys ())

    def __str__ (self): return "AbstractLayout{\n" + "".join ("\t%s => %s\n" % (n, str (o)) for n, o in self.outputs.items ()) + "}"

### ConcreteLayout ###

class ConcreteLayout (object):
    """
    Concrete layout representing a simplified backend state.
    
    A layout is a set of output (by plug), that may be enabled (actively used) or not.
    Each output has sizes and absolute positions (only meaningful if enabled).

    Some non-layout additionnal info from the backend is stored, like preferred sizes and EDID
    """
    class Output (object):
        def __init__ (self, **kwd):
            # layout info by output
            self.enabled = kwd.get ("enabled", False)
            self.transform = kwd.get ("transform", Transform ())
            self.base_size = kwd.get ("base_size", Pair (0, 0))
            self.position = kwd.get ("position", Pair (0, 0))

            # additionnal data from backend
            self.preferred_size = kwd.get ("preferred_size", Pair (0, 0))
            self.edid = kwd.get ("edid", None)
        
        def size (self): return self.transform.rectangle_size (self.base_size)
        def __eq__ (self, other): return vars (self) == vars (other)
        __str__ = util.class_str

    def __init__ (self, **kwd):
        # Layout data
        self.outputs = kwd.get ("outputs", {})
        self.virtual_screen_size = kwd.get ("vs_size", Pair (0, 0))
        
        # Additionnal info : screen size limits
        self.virtual_screen_min = kwd.get ("vs_min", Pair (0, 0))
        self.virtual_screen_max = kwd.get ("vs_max", Pair (sys.maxsize, sys.maxsize))

    # Equality, Manual check
    
    def __eq__ (self, other):
        return vars (self) == vars (other)

    def manual (self):
        """
        Returns True if this layout cannot be represented by an AbstractLayout.
        Reasons are: disabled outputs, invalid Edid data, non-preferred mode, mirroring / overlapping
        """
        if any (not o.enabled for o in self.outputs.values ()):
            return True
        if not self.edid_valid ():
            return True
        if any (o.preferred_size != o.base_size for o in self.outputs.values ()):
            return True
        
        # Check for overlap (and mirroring that is included in overlap)
        outputs = self.outputs.items ()
        for na, oa in outputs:
            oa_corner = oa.position + oa.size ()
            for nb, ob in outputs:
                if na < nb: # only check each screen pair once
                    ob_corner = ob.position + ob.size ()
                    if not (ob.position.x >= oa_corner.x or ob.position.y >= oa_corner.y or oa.position.x >= ob_corner.x or oa.position.y >= ob_corner.y):
                        return True
        return False
    
    # Edid check and listing
    
    def edid_valid (self):
        """
        Returns True if the set of connected output has sufficient Edid data for the manager
        That means that each output has a unique Edid
        """
        edid_list = [o.edid for o in self.outputs.values ()]
        if None in edid_list:
            return False
        if len (edid_list) != len (frozenset (edid_list)):
            return False # Collision test
        return True
    
    def connected_edids (self):
        """
        Returns set of connected outputs Edid
        Ignores outputs without Edid, and merge duplicates
        """
        return frozenset (o.edid for o in self.outputs.values () if o.edid is not None)
    
    # Pretty print

    def __str__ (self):
        outputs = ("\t%s => %s\n" % (n, str (o)) for n, o in self.outputs.items ())
        return "ConcreteLayout(vss=%s){\n%s}" % (self.virtual_screen_size, "".join (outputs))

    # Import/export

    def from_abstract (self, abstract):
        """
        Builds a new backend layout object from an abstract layout and current additionnal info
        Absolute layout positionning uses the c++ isl extension

        It assumes the ConcreteLayout base object has correct Edid (bijection name <-> edid)
        """
        edid_to_name = {o.edid: name for name, o in self.outputs.items ()}

        def make_entry (edid, o):
            name = edid_to_name[edid]
            size = self.outputs[name].preferred_size
            output = ConcreteLayout.Output (enabled = True, transform = o.transform.copy (), base_size = size, edid = edid, preferred_size = size)
            return (name, output)
        concrete = ConcreteLayout (outputs = dict (make_entry (*entry) for entry in abstract.outputs.items ()))
        
        # Compute absolute layout
        edids = abstract.outputs.keys ()
        constraints = [ [ abstract.outputs[ea].rel (eb) for eb in edids ] for ea in edids ]
        sizes = [ concrete.outputs[edid_to_name[e]].size () for e in edids ]
        result = slam_ext.screen_layout (self.virtual_screen_min, self.virtual_screen_max, sizes, constraints)
        if result is None:
            return None

        # Fill result
        concrete.virtual_screen_size = Pair (result[0])
        for i, edid in enumerate (edids):
            concrete.outputs[edid_to_name[edid]].position = Pair (result[1][i])
        return concrete

    def to_abstract (self):
        """
        Build an AbstractLayout from a ConcreteLayout.
        Two screen are considered related if their borders are touching in the ConcreteLayout
        """
        if self.manual ():
            raise LayoutException ("cannot abstract manual ConcreteLayout in manual")
        outputs = self.outputs.values ()
        abstract = AbstractLayout (outputs = {o.edid: AbstractLayout.Output (transform = o.transform.copy ()) for o in outputs})

        # Extract neighbouring relations
        for oa in outputs:
            for ob in outputs:
                if oa != ob:
                    oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
                    if oa_corner.x == ob.position.x and oa.position.y < ob_corner.y and oa_corner.y > ob.position.y:
                        abstract.set_relation (oa.edid, Dir.left, ob.edid)
                    if oa_corner.y == ob.position.y and oa.position.x < ob_corner.x and oa_corner.x > ob.position.x:
                        abstract.set_relation (oa.edid, Dir.above, ob.edid)
        return abstract

### Database ###

class DatabaseLoadError (Exception):
    pass

class Database (object):
    version = 3
    """
    Database of layouts
    Can be stored/loaded from/to files
    Format v3 is:
        * int : version number
        * list of abstractlayout object dumps : layouts
        * 
    """
    def __init__ (self):
        # Database : frozenset(edids) -> AbstractLayout ()
        self.layouts = dict ()
        
        # Statistics :
        self.relation_statistics = None

    # database access and update

    def get_layout (self, key):
        return self.layouts.get (key, None)

    def successfully_applied (self, abstract, concrete):
        self.layouts[abstract.key ()] = abstract

    # default

    def generate_default_layout (self, edid_set):
        # For now, generate one without any relation.
        #TODO : take stats over all configs to find relations
        return AbstractLayout (outputs = {edid: AbstractLayout.Output () for edid in edid_set})
    
    # store / load

    def load (self, buf):
        """ Fill the database with layouts from buf (pickle format) """
        try:
            # check version
            version = pickle.load (buf)
            if not isinstance (version, int):
                raise DatabaseLoadError ("incorrect database format : version = {}".format (version))
            if version != Database.version:
                raise DatabaseLoadError ("incorrect database version : {} (expected {})".format (version, Database.version))

            # get layout database
            layout_dump_list = pickle.load (buf)
            for layout_dump in layout_dump_list:
                try:
                    layout = AbstractLayout.load (layout_dump)
                except Exception as e:
                    raise DatabaseLoadError ("unpacking error: {}".format (e))
                self.layouts[layout.key ()] = layout
                
        except (OSError, EOFError) as e:
            raise DatabaseLoadError ("io error: {}".format (e))
        except pickle.PickleError as e:
            raise DatabaseLoadError ("pickle error: {}".format (e))

    def store (self, buf):
        """ Outputs manager database into buffer object (pickle format) """
        # version
        pickle.dump (int (Database.version), buf)

        # database
        layout_dump_list = [abstract.dump () for abstract in self.layouts.values ()]
        pickle.dump (layout_dump_list, buf)

### Manager ###

class Manager (Database):
    """
    Manages a set of configs
    """
    # Init
    
    def __init__ (self):
        super (Manager, self).__init__ ()

    def start (self, backend):
        self.current_concrete_layout = ConcreteLayout () # init with default empty layout

        self.backend = backend
        self.backend.attach (lambda l: self.backend_changed (l))

    # Callback

    def backend_changed (self, new_concrete_layout):
        """
        Backend callback, called for each hardware state change.
        """
        logger.info ("backend changed")
        logger.debug (str (new_concrete_layout))

        if new_concrete_layout == self.current_concrete_layout:
            return self.action_same_as_before ()

        if not new_concrete_layout.edid_valid ():
            return self.action_manual (new_concrete_layout, " (wrong or missing Edid data)")

        edid_set = new_concrete_layout.connected_edids ()
        if edid_set != self.current_concrete_layout.connected_edids ():
            # New output set, apply a layout
            if self.get_layout (edid_set):
                self.action_apply_from_table (new_concrete_layout, edid_set)
            else:
                self.action_apply_default_layout (new_concrete_layout, edid_set)
        else:
            # Same output set
            if new_concrete_layout.manual ():
                self.action_manual (new_concrete_layout)
            else:
                self.action_store_and_normalize (new_concrete_layout)
    
    # do nothing actions

    def action_same_as_before (self):
        # We are being notified of our last update to backend
        logger.info ("do nothing (same layout as before)")
       
    def action_manual (self, new_concrete_layout, postfix = ""):
        # Entering manual mode, just keep current_concrete_layout updated
        logger.warn ("do nothing, manual mode{}".format (postfix))
        self.current_concrete_layout = new_concrete_layout

    # apply config actions

    def helper_apply_abstract (self, abstract, new_concrete_layout):
        concrete = new_concrete_layout.from_abstract (abstract)
        self.backend.apply_concrete_layout (concrete)

        self.current_concrete_layout = concrete
        self.successfully_applied (abstract, concrete)

    def action_apply_from_table (self, new_concrete_layout, edid_set):
        # Try to apply stored layout
        logger.info ("apply from table")
        try:
            self.helper_apply_abstract (self.get_layout (edid_set), new_concrete_layout)
        except:
            logger.exception ("failed to apply from table")
            raise

    def action_apply_default_layout (self, new_concrete_layout, edid_set):
        # Build a default config with no relation
        logger.info ("apply default layout")
        try:
            self.helper_apply_abstract (self.generate_default_layout (edid_set), new_concrete_layout)
        except:
            logger.exception ("failed to apply default layout")
            raise

    def action_store_and_normalize (self, new_concrete_layout):
        # Update database
        logger.info ("store and normalize")
        try:
            self.helper_apply_abstract (new_concrete_layout.to_abstract (), new_concrete_layout)
        except:
            logger.exception ("failed to store and normalize")
            raise


