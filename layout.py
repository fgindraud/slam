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

import sys
import itertools

import slam_ext

import pickle
import util
from util import Pair

logger = util.setup_logger (__name__)

### Utils ###

# Base exceptions. Fatal error should not be caught.
class LayoutError (Exception): pass
class LayoutFatalError (Exception): pass

# Backend errors
class BackendError (LayoutError): pass
class BackendFatalError (LayoutFatalError): pass

# Directions

class Dir:
    """ Convention between c++ extension and python """
    # values
    none = 0
    left = 1
    right = 2
    above = 3
    under = 4
    
    @staticmethod
    def iter ():
        return range (5)

    # utils
    @staticmethod
    def invert (d):
        return slam_ext.Dir_invert (d)

    @staticmethod
    def str (d):
        return slam_ext.Dir_str (d)

# Transformation
class Transform (util.AttributeEquality):
    rotations = { 0: False, 90: True, 180: False, 270: True }
    """
    Transformation is internally a reflection on x coordinates followed by a trigonometric rotation
    Externally, rotate(), reflectx/y() return a new transformation based on the current one
    Not modifiable, only creates new instances
    """
    def __init__ (self, rx = False, rot = 0):
        self.reflect = rx
        self.rotation = rot
    
    # Dump / load
    @staticmethod
    def load (data): return Transform (*data)
    def dump (self): return (self.reflect, self.rotation)

    # Derived transformation generators
    def rotate (self, rot):
        if (rot % 360) not in Transform.rotations:
            raise LayoutFatalError ("unsupported rotation")
        return Transform (self.reflect, (self.rotation + rot) % 360)

    def reflectx (self):
        return Transform (not self.reflect, (self.rotation + 180) % 360 if self.inverted () else self.rotation)
    def reflecty (self):
        return Transform (not self.reflect, self.rotation if self.inverted () else (self.rotation + 180) % 360)

    # Misc
    def inverted (self):
        return Transform.rotations[self.rotation]
    def rectangle_size (self, size):
        return size.swap () if self.inverted () else size

    def __str__ (self):
        return ("R" if self.reflect else "") + str (self.rotation)

    def __hash__ (self):
        # Make object hashable (for Database.generate_statistical_layout)
        return hash ((self.reflect, self.rotation))

### AbstractLayout ###

class AbstractLayout (object):
    """
    Abstract Layout model used in the database.

    A layout is a set of outputs (represented by their EDID), their transformations, and relations between them.
    It can represent multiple physical layouts if same outputs are plugged into different plugs.

    Relations are duplicated (a < b && b > a).
    """
    class Output (object):
        def __init__ (self, **kwd):
            self.transform = kwd.get ("transform", Transform ())
            self.neighbours = kwd.get ("neighbours", {})

        # Load / dump
        @staticmethod
        def load (data): return AbstractLayout.Output (transform = Transform.load (data[0]), neighbours = data[1])
        def dump (self): return (self.transform.dump (), self.neighbours)

        def rel (self, neighbour):
            return self.neighbours.get (neighbour, Dir.none)

    def __init__ (self, **kwd):
        self.outputs = kwd.get ("outputs", {})
    
    # Load / dump 
    @staticmethod
    def load (data): return AbstractLayout (outputs = {edid: AbstractLayout.Output.load (d) for edid, d in data.items ()})
    def dump (self): return {edid: output.dump () for edid, output in self.outputs.items ()}

    def set_relation (self, edid_a, rel, edid_b):
        self.outputs[edid_a].neighbours[edid_b] = rel
        self.outputs[edid_b].neighbours[edid_a] = Dir.invert (rel)

    def key (self):
        """ Key for Database is set of edid """
        return frozenset (self.outputs.keys ())

### ConcreteLayout ###

class ConcreteLayout (util.AttributeEquality):
    """
    Concrete layout representing a simplified backend state.
    
    A layout is a set of output (by plug), that may be enabled (actively used) or not.
    Each output has sizes and absolute positions (only meaningful if enabled).

    Some non-layout additionnal info from the backend is stored, like preferred sizes and EDID
    """
    class Output (util.AttributeEquality):
        def __init__ (self, **kwd):
            # Layout info by output
            self.enabled = kwd.get ("enabled", False)
            self.transform = kwd.get ("transform", Transform ())
            self.base_size = kwd.get ("base_size", Pair (0, 0))
            self.position = kwd.get ("position", Pair (0, 0))

            # Additionnal data from backend
            self.preferred_size = kwd.get ("preferred_size", Pair (0, 0))
            self.edid = kwd.get ("edid", None)
        
        def size (self):
            return self.transform.rectangle_size (self.base_size)

        def __str__ (self):
            return "{}: {}, tr({}), pos({:s}), size({:s}|{:s})".format (
                    self.edid, {False:"D",True:"E"}[self.enabled],
                    self.transform, self.position,
                    self.base_size, self.preferred_size)

    def __init__ (self, **kwd):
        # Layout data
        self.outputs = kwd.get ("outputs", {})
        self.virtual_screen_size = kwd.get ("vs_size", Pair (0, 0))
        
        # Additionnal info : screen size limits
        self.virtual_screen_min = kwd.get ("vs_min", Pair (0, 0))
        self.virtual_screen_max = kwd.get ("vs_max", Pair (sys.maxsize, sys.maxsize))

    # State checks

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
        for oa, ob in itertools.combinations (self.outputs.values (), 2):
            oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
            if not (ob.position.x >= oa_corner.x or ob.position.y >= oa_corner.y or oa.position.x >= ob_corner.x or oa.position.y >= ob_corner.y):
                return True
        return False
    
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
    
    # Edid / name info

    def connected_edids (self):
        """
        Returns set of connected outputs Edid
        Ignores outputs without Edid, and merge duplicates
        """
        return frozenset (o.edid for o in self.outputs.values () if o.edid is not None)

    def edid (self, name):
        return self.outputs[name].edid

    def name_map (self):
        return {o.edid: name for name, o in self.outputs.items ()}
    
    # Pretty print

    def __str__ (self):
        outputs = (map ("\t{0[0]} ({0[1]})\n".format, self.outputs.items ()))
        return "ConcreteLayout(vss={:s}, vs_min={:s}, vs_max={:s}){{\n{}}}".format (
                self.virtual_screen_size, self.virtual_screen_min, self.virtual_screen_max,
                "".join (outputs))

    # Import/export

    def from_abstract (self, abstract):
        """
        Builds a new backend layout object from an abstract layout and current additionnal info
        Absolute layout positionning uses the c++ isl extension

        It assumes the ConcreteLayout base object has correct Edid (bijection name <-> edid)
        """
        names = self.name_map ()

        def make_entry (edid, o):
            size = self.outputs[names[edid]].preferred_size
            output = ConcreteLayout.Output (enabled = True, transform = o.transform, base_size = size, edid = edid, preferred_size = size)
            return (names[edid], output)
        concrete = ConcreteLayout (vs_min = self.virtual_screen_min, vs_max = self.virtual_screen_max,
                outputs = dict (make_entry (*entry) for entry in abstract.outputs.items ()))
        
        # Compute absolute layout
        edids = abstract.outputs.keys ()
        constraints = [[abstract.outputs[ea].rel (eb) for eb in edids] for ea in edids]
        sizes = [concrete.outputs[names[e]].size () for e in edids]
        result = slam_ext.screen_layout (self.virtual_screen_min, self.virtual_screen_max, sizes, constraints)
        if result is None:
            raise LayoutError ("unable to compute concrete positions")

        # Fill result
        concrete.virtual_screen_size = Pair (result[0])
        for i, edid in enumerate (edids):
            concrete.outputs[names[edid]].position = Pair (result[1][i])
        return concrete

    def to_abstract (self):
        """
        Build an AbstractLayout from a ConcreteLayout.
        Two screen are considered related if their borders are touching in the ConcreteLayout
        """
        if self.manual ():
            raise LayoutFatalError ("cannot abstract manual ConcreteLayout in manual")
        outputs = self.outputs.values ()
        abstract = AbstractLayout (outputs = {o.edid: AbstractLayout.Output (transform = o.transform) for o in outputs})

        # Extract neighbouring relations for each pair of outputs
        for oa, ob in itertools.permutations (outputs, 2):
            oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
            if oa_corner.x == ob.position.x and oa.position.y < ob_corner.y and oa_corner.y > ob.position.y:
                abstract.set_relation (oa.edid, Dir.left, ob.edid)
            if oa_corner.y == ob.position.y and oa.position.x < ob_corner.x and oa_corner.x > ob.position.x:
                abstract.set_relation (oa.edid, Dir.above, ob.edid)
        return abstract

### Database ###

class Database (object):
    version = 4
    """
    Database of layouts
    Can be stored/loaded from/to files
    Format v4 is:
        * int : version number
        * list of abstractlayout object dumps : layouts
        * relation_counters dict : (output_nameA, relation, output_nameB) for every pair of outputs
    """
    def __init__ (self):
        # Database : frozenset(edids) -> AbstractLayout ()
        self.layouts = {}
        
        # Relation usage counters : (nameA, rel, nameB) -> int | with nameA < nameB
        self.relation_counters = {}

    # database access and update

    def get_layout (self, key):
        try:
            return self.layouts[key]
        except KeyError:
            raise LayoutError ("layout for [{}] not found in database".format (",".join (key))) from None

    def successfully_applied (self, abstract, concrete):
        # update database
        self.layouts[abstract.key ()] = abstract

        # increment statistics counters
        for na, nb in itertools.permutations (concrete.outputs, 2):
            # increment relation usage counter
            relation = abstract.outputs[concrete.edid (na)].rel (concrete.edid (nb))
            key = (na, relation, nb)
            self.relation_counters[key] = 1 + self.relation_counters.get (key, 0)

    # default

    def generate_statistical_layout (self, concrete, edid_set):
        """ Generates a layout using statistics """
        abstract = self.generate_default_layout (edid_set)
       
        # Set relation between two outputs screens as the most frequently used between the two outputs plugs
        for na, nb in itertools.combinations (concrete.outputs):
            # Find relation with max use.
            def count (d):
                return self.relation_counters.get ((na, d, nb), 0) + self.relation_counters.get ((nb, Dir.invert (d), na), 0)
            most_used = max (Dir.iter (), key = count)
            if count (most_used) > 0:
                abstract.set_relation (self.edid (na), choice, self.edid (nb))

        # For each known Edid, set transformation as the most frequent in the database
        for edid in abstract.outputs:
            pass

        return abstract

    def generate_default_layout (self, edid_set):
        """ Generates a default layout with no relations or transformation """
        return AbstractLayout (outputs = {edid: AbstractLayout.Output () for edid in edid_set})
    
    # store / load

    def load (self, buf):
        """ Read the database with layouts from buf (pickle format) """
        # check version
        version = pickle.load (buf)
        if not isinstance (version, int):
            raise ValueError ("incorrect database format : version = {}".format (version))
        if version != Database.version:
            raise ValueError ("incorrect database version : {} (expected {})".format (version, Database.version))

        # get layout database
        layout_dump_list = pickle.load (buf)
        for layout_dump in layout_dump_list:
            layout = AbstractLayout.load (layout_dump)
            self.layouts[layout.key ()] = layout

        # get relation_counters
        self.relation_counters = pickle.load (buf)
                
    def store (self, buf):
        """ Outputs manager database into buffer object (pickle format) """
        # version
        pickle.dump (int (Database.version), buf)

        # database
        layout_dump_list = [abstract.dump () for abstract in self.layouts.values ()]
        pickle.dump (layout_dump_list, buf)

        # relation_counters
        pickle.dump (self.relation_counters, buf)

### Manager ###

class Manager (Database):
    """ Manages the database and backend """
    def __init__ (self):
        super (Manager, self).__init__ ()

    def start (self, backend):
        # Init with default empty layout
        self.current_concrete_layout = ConcreteLayout ()

        # Attach to backend, will force an update of the current_concrete_layout
        self.backend = backend
        self.backend.attach (lambda concrete: self.backend_changed (concrete))

    # Callback

    def backend_changed (self, new_concrete_layout):
        """ Backend callback, called for each hardware state change.  """

        logger.info ("backend changed")
        logger.debug ("current " + str (self.current_concrete_layout))
        logger.debug ("new " + str (new_concrete_layout))

        if new_concrete_layout == self.current_concrete_layout:
            return self.action_same_as_before ()

        if not new_concrete_layout.edid_valid ():
            return self.action_manual (new_concrete_layout, " (wrong or missing Edid data)")

        edid_set = new_concrete_layout.connected_edids ()
        if edid_set != self.current_concrete_layout.connected_edids ():
            # New output set, apply a layout
            self.action_apply_from_table (new_concrete_layout, edid_set)
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

    # Failure management discussion, by exception type:
    #
    # LayoutError:
    #   * layout not found > use default
    #   * layout with stupid relations > use default
    #   * screen limits so tight it will never fit > using default will fail too anyway, so use default
    # BackendError:
    #   * invalid time > x state changed, abort modification. event_loop will reload state and see what to do then
    #   * crtc allocation error > crtc shortage. using default state will also fail, so abort modification
    # (Layout|Backend)FatalError:
    #   * invalid program state, bail out, do not catch
    # <other, like xcb badmatch>:
    #   * Badmatch should be avoided by backend, so abort if one goes through
    
    def helper_apply_abstract (self, abstract, new_concrete_layout):
        # Compute ConcreteLayout and apply it to backend
        concrete = new_concrete_layout.from_abstract (abstract)
        self.backend.apply_concrete_layout (concrete)

        # Update manager data on success
        self.current_concrete_layout = concrete
        self.successfully_applied (abstract, concrete)

    def action_apply_from_table (self, new_concrete_layout, edid_set):
        # Try to apply stored layout
        logger.info ("apply from table [{}]".format (",".join (edid_set)))
        try:
            return self.helper_apply_abstract (self.get_layout (edid_set), new_concrete_layout)
        except LayoutError as e:
            logger.info ("unable apply from table: {}".format (e))
        except BackendError as e:
            logger.error ("unable to apply to backend, abort change: {}".format (e))
            return # Abort change
        
        return self.action_apply_statistical_layout (new_concrete_layout, edid_set)
    
    def action_apply_statistical_layout (self, new_concrete_layout, edid_set):
        # Build a default config with no relation
        logger.info ("apply statistical layout [{}]".format (",".join (new_concrete_layout.outputs)))
        try:
            return self.helper_apply_abstract (self.generate_statistical_layout (new_concrete_layout, edid_set), new_concrete_layout)
        except LayoutError as e:
            logger.info ("unable to apply statistical layout: {}".format (e))
        except BackendError as e:
            logger.error ("unable to apply to backend, abort change: {}".format (e))
            return # Abort change
            
        return self.action_apply_default_layout (new_concrete_layout, edid_set)

    def action_apply_default_layout (self, new_concrete_layout, edid_set):
        # Build a default config with no relation
        logger.info ("apply default layout")
        try:
            self.helper_apply_abstract (self.generate_default_layout (edid_set), new_concrete_layout)
        except (LayoutError, BackendError) as e:
            # Provide detailed error if we failed with this default one, as it should only fail in the backend
            logger.exception ("unable to apply default layout, abort change: {}".format (e))

    def action_store_and_normalize (self, new_concrete_layout):
        # Update database
        logger.info ("store and normalize")
        try:
            self.helper_apply_abstract (new_concrete_layout.to_abstract (), new_concrete_layout)
        except BackendError as e:
            # Should not fail due to layout problems, so let these exceptions through
            logger.error ("unable to apply to backend, abort change: {}".format (e))

