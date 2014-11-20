import slam_ext
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
    def __init__ (self, rx = False, rot = 0): self.reflect, self.rotation = rx, rot
    def copy (self): return Transform (self.reflect, self.rotation)
    @staticmethod
    def load (data): return Transform (*data)
    def dump (self): return (self.reflect, self.rotation)

    def rotate (self, rot):
        if (rot % 360) not in Transform.rotations: raise TransformException ("unsupported rotation")
        return Transform (self.reflect, (self.rotation + rot) % 360)
    def reflectx (self): return Transform (not self.reflect, (self.rotation + 180) % 360 if self.inverted () else self.rotation)
    def reflecty (self): return Transform (not self.reflect, self.rotation if self.inverted () else (self.rotation + 180) % 360)

    def rectangle_size (self, size): return size.swap () if self.inverted () else size.copy ()
    
    def inverted (self): return Transform.rotations[self.rotation]
    def __eq__ (self, other): return self.rotation == other.rotation and self.reflect == other.reflect
    __str__ = util.class_str

### Layouts ###

class AbstractLayout (object):
    """
    Abstract Layout model supported by the manager
    Every output listed is enabled, and has a transformation attached to it
    Relations are duplicated (a < b && b > a)
    """
    class Output (object):
        def __init__ (self, **kwd):
            self.transform = kwd.get ("transform", Transform ())
            self.neighbours = kwd.get ("neighbours", {})
            self.edid = kwd.get ("edid", None)
        def copy (self): return Output (transform = self.transform.copy (), neighbours = self.neighbours.copy (), edid = self.edid)
        @staticmethod
        def load (data): return Output (transform = Transform.load (data[0]), neighbours = data[1], edid = data[2])
        def dump (self): return (self.transform.dump (), self.neighbours, self.edid)

        def rel (self, neighbour): return self.neighbours.get (neighbour, Dir.none)
        __str__ = util.class_str

    def __init__ (self, **kwd): self.outputs = kwd.get ("outputs", {})
    def copy (self): return AbstractLayout (outputs = dict ((n, o.copy ()) for n, o in self.outputs.items ())) # deep copy
    @staticmethod
    def load (data): return AbstractLayout (outputs = dict ((name, Output.load (d)) for name, d in data.items ()))
    def dump (self): return dict ((name, output.dump ()) for name, output in self.outputs.items ())

    def set_relation (self, na, rel, nb):
        self.outputs[na].neighbours[nb] = rel
        self.outputs[nb].neighbours[na] = rel.invert ()

    def key (self): return Manager.key (self.outputs)
    def __str__ (self): return "AbstractLayout{\n" + "".join ("\t%s => %s\n" % (n, str (o)) for n, o in self.outputs.items ()) + "}"

class ConcreteLayout (object):
    """
    Concrete layout representing a simplified backend state.
    Each output has sizes and absolute positions, if it is enabled.
    If 'manual' is true, this layout cannot be represented by an AbstractLayout (due to disabled outputs, overlapping, non-preferred mode, mirroring)
    """
    class Output (object):
        def __init__ (self, **kwd):
            self.enabled = kwd.get ("enabled", False)
            self.transform = kwd.get ("transform", Transform ())
            self.base_size = kwd.get ("base_size", Pair (0, 0))
            self.position = kwd.get ("position", Pair (0, 0))
            self.edid = kwd.get ("edid", None)
        
        def size (self): return self.transform.rectangle_size (self.base_size)
        def __eq__ (self, other): return vars (self) == vars (other)
        __str__ = util.class_str

    def __init__ (self, **kwd):
        self.outputs = kwd.get ("outputs", {})
        self.virtual_screen_size = kwd.get ("vss", Pair (0, 0))
        self.manual = False

    def key (self): return Manager.key (self.outputs)
    def __eq__ (self, other): return vars (self) == vars (other)
        
    def __str__ (self):
        outputs = ("\t%s => %s\n" % (n, str (o)) for n, o in self.outputs.items ())
        return "ConcreteLayout(vss=%s, manual=%d){\n%s}" % (self.virtual_screen_size, self.manual, "".join (outputs))

    def compute_manual_flag (self, preferred_sizes_by_output):
        outputs = self.outputs.items ()
        self.manual = False
        for name, o in outputs:
            self.manual |= not o.enabled # disabled outputs
            self.manual |= preferred_sizes_by_output[name] != o.base_size # not preferred mode
            # overlap check
            o_corner = o.position + o.size ()
            for nt, ot in outputs:
                if name < nt: # only check each screen pair once
                    ot_corner = ot.position + ot.size ()
                    self.manual |= not (ot.position.x >= o_corner.x or ot.position.y >= o_corner.y or o.position.x >= ot_corner.x or o.position.y >= ot_corner.y)
            # mirroring covered by the overlap check (mirrored outputs will overlap)

    # Import/export
    @staticmethod
    def from_abstract (abstract, virtual_screen_min, virtual_screen_max, preferred_sizes_by_output):
        """
        Builds a new backend layout object from an abstract layout and external info
        Absolute layout positionning uses the c++ isl extension
        """
        def make_output (name, o):
            return ConcreteLayout.Output (enabled = True, transform = o.transform.copy (), base_size = preferred_sizes_by_output[name], edid = o.edid)
        concrete = ConcreteLayout (outputs = dict ((name, make_output (name, o)) for name, o in abstract.outputs.items ()))
        # Compute absolute layout
        names = abstract.outputs.keys ()
        constraints = [ [ abstract.outputs[na].rel (nb) for nb in names ] for na in names ]
        r = slam_ext.screen_layout (virtual_screen_min, virtual_screen_max, [concrete.outputs[n].size () for n in names], constraints)
        # Fill result
        if r == None: return None
        concrete.virtual_screen_size = Pair (r[0])
        for i, name in enumerate (names): concrete.outputs[name].position = Pair (r[1][i])
        return concrete

    def to_abstract (self):
        """
        Build an AbstractLayout from a ConcreteLayout.
        Two screen are considered related if their borders are touching in the ConcreteLayout
        """
        if self.manual: raise LayoutException ("cannot abstract ConcreteLayout in manual mode")
        outputs = self.outputs.items ()
        abstract = AbstractLayout (outputs = dict ((name, AbstractLayout.Output (transform = o.transform.copy (), edid = o.edid)) for name, o in outputs))
        # Extract neighbouring relations
        for na, oa in outputs:
            for nb, ob in outputs:
                if na != nb:
                    oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
                    if oa_corner.x == ob.position.x and oa.position.y < ob_corner.y and oa_corner.y > ob.position.y: abstract.set_relation (na, Dir.left, nb)
                    if oa_corner.y == ob.position.y and oa.position.x < ob_corner.x and oa_corner.x > ob.position.x: abstract.set_relation (na, Dir.above, nb)
        return abstract

### Manager ###

class Manager (object):
    """
    Manages a set of configs
    """
    @staticmethod
    def key (output_dict):
        """ Key for the manager map """
        return frozenset ((name, o.edid) for name, o in output_dict.items ())

    def __init__ (self):
        self.layouts = dict () # frozenset( (name,edid=null) ) -> AbstractLayout ()
    
    @staticmethod
    def load (data):
        """ Loads all stored layouts from a string (uses pickle) """
        pass

    def dump (self):
        """ Output all stored layouts as a string (uses pickle) """
        pass

    def start (self, backend):
        self.current_concrete_layout = ConcreteLayout () # init with default empty layout

        self.backend = backend
        self.backend.attach (lambda t: self.backend_changed (t))

    def backend_changed (self, new_concrete_layout):


        print (str (new_concrete_layout))
        if not new_concrete_layout.manual: print (str (new_concrete_layout.to_abstract ()))

        self.current_concrete_layout = new_concrete_layout

    def test (self, line):
        rot = 0
        for s, r in {"left": 90, "right": 270, "down": 180}.items ():
            if s in line: rot = r
        #a = AbstractLayout (outputs = {"LVDS1": AbstractLayout.Output (), "VGA1": AbstractLayout.Output (transform = Transform ().rotate (rot))})
        #a.set_relation ("LVDS1", Dir.left, "VGA1")
        a = AbstractLayout (outputs = {"LVDS1": AbstractLayout.Output (transform = Transform ().rotate (rot), edid = self.current_concrete_layout.outputs["LVDS1"].edid)})
        c = ConcreteLayout.from_abstract (a, self.backend.get_virtual_screen_min_size (), self.backend.get_virtual_screen_max_size (), self.backend.get_preferred_sizes_by_output ())
        self.backend.apply_concrete_layout (c)

