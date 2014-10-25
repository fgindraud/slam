import slam_ext
import pickle

### Utils ###

class TransformException (Exception):
    pass
class LayoutException (Exception):
    pass

def class_str (instance):
    return type (instance).__name__ + "(" + ", ".join ([n + "=" + str (v) for n, v in instance.__dict__.items ()]) + ")"

# Directions
Dir = slam_ext.Dir
Dir.invert = slam_ext.Dir_invert
Dir.__str__ = slam_ext.Dir_str

# Pair of objects
class Pair (object):
    def __init__ (self, a, b = None):
        """ Takes a pair of values, or an iterable """
        if b == None: self.x, self.y = a
        else: self.x, self.y = a, b

    def copy (self): return Pair (self)
    def swap (self): return Pair (self.y, self.x)
    def __add__ (self, other): return Pair (self.x + other.x, self.y + other.y)
    def __neg__ (self): return Pair (-self.x, -self.y)
    def __sub__ (self, other): return self + (-other)

    def __eq__ (self, other): return self.x == other.x and self.y == other.y
    def __ne__ (self, other): return not (self == other)
    def __str__ (self): return "(%s,%s)" % (str (self.x), str (self.y))
    def __repr__ (self): return "(%s,%s)" % (repr (self.x), repr (self.y))
    def __iter__ (self): return iter ((self.x, self.y))

# Transformation
class Transform (object):
    rotations = { 0: False, 90: True, 180: False, 270: True }
    """
    Transformation is internally a reflection on x coordinates followed by a trigonometric rotation
    Externally, rotate(), reflectx/y() return a new transformation based on the current one
    """
    def __init__ (self, rx = False, rot = 0): self.reflect, self.rotation = rx, rot
    def copy (self): return Transform (self.reflect, self.rotation)

    def rotate (self, rot):
        if (rot % 360) not in Transform.rotations: raise TransformException ("unsupported rotation")
        return Transform (self.reflect, (self.rotation + rot) % 360)
    def reflectx (self): return Transform (not self.reflect, (self.rotation + 180) % 360 if self.inverted () else self.rotation)
    def reflecty (self): return Transform (not self.reflect, self.rotation if self.inverted () else (self.rotation + 180) % 360)

    def inverted (self): return Transform.rotations[self.rotation]
    def rectangle_size (self, size): return size.swap () if self.inverted () else size.copy ()

    def dump (self): return (self.reflect, self.rotation)
    @staticmethod
    def load (data): return Transform (*data)
    __str__ = class_str

### Layouts ###

class AbstractLayout (object):
    """
    Abstract Layout model supported by the manager
    Every output listed is enabled, and has a transformation attached to it
    Relations are duplicated (a < b && b > a)
    """
    class Output (object):
        def __init__ (self, tr = Transform (), neighbours = {}): self.transform, self.neighbours = tr, neighbours
        def copy (self): return Output (self.transform.copy (), self.neighbours.copy ())

        def rel (self, neighbour): return self.neighbours.get (neighbour, Dir.none)

        def dump (self): return (self.transform.dump (), self.neighbours)
        @staticmethod
        def load (data): return Output (Transform.load (data[0]), data[1])
        __str__ = class_str

    def __init__ (self, outputs = {}): self.outputs = outputs
    def copy (self): return AbstractLayout (dict ([(n, o.copy ()) for n, o in self.outputs.items ()])) # deep copy

    def dump (self): return dict ([(name, output.dump ()) for name, output in self.outputs.items ()])
    @staticmethod
    def load (data): return AbstractLayout (dict ([(name, Output.load (d)) for name, d in data.items ()]))
    def __str__ (self): return "AbstractLayout{\n" + "".join (["\t%s => %s\n" % (n, str (o)) for n, o in self.outputs.items ()]) + "}"

class Config (object):
    """
    Manages a set of abstracts layouts for a given tag set
    """
    def __init__ (self):
        self.layouts = dict () # frozenset( (name,edid=null) ) -> AbstractLayout ()

    def dump (self): pass
    @staticmethod
    def load (data): pass

class Manager (object):
    """
    Manages a set of configs
    """
    def __init__ (self, backend):
        self.configs = dict () # frozenset ( str ) -> Config ()
        self.current_tags = set () #
        self.current_concrete_layout = None

        self.backend = backend
        self.backend.attach (lambda t: self.backend_changed (t))

    def backend_changed (self, new_concrete_layout):
        print str (new_concrete_layout)
        print str (new_concrete_layout.to_abstract ())

    def dump (self):
        """ Output all stored layouts as a string (uses pickle) """
        pass
    @staticmethod
    def load (data):
        """ Loads all stored layouts from a string (uses pickle) """
        pass


### Concrete Layout ###

class ConcreteLayout (object):
    """
    Concrete layout reprensenting the backend state.
    Layout is described by sizes and absolute positions
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
        __str__ = class_str

    def __init__ (self, outputs = {}, vss = Pair (0, 0)):
        self.outputs, self.virtual_screen_size = outputs, vss
        self.manual = False

    def key (self):
        return frozenset ([(name, o.edid) for name, o in self.outputs.items ()])

    def __str__ (self):
        outputs = ["\t%s => %s\n" % (n, str (o)) for n, o in self.outputs.items ()]
        return "ConcreteLayout(vss=%s, manual=%d){\n%s}" % (self.virtual_screen_size, self.manual, "".join (outputs))

    def compute_manual_flag (self, preferred_sizes_by_output):
        outputs = set (self.outputs.items ())
        self.manual = False
        for name, o in outputs:
            self.manual |= not o.enabled # disabled outputs
            self.manual |= preferred_sizes_by_output[name] != o.base_size # not preferred mode
            # overlap check
            end_corner = o.position + o.size ()
            for n2, o2 in outputs - set ([(name, o)]):
                self.manual |= end_corner.x <= o2.position.x and end_corner.y <= o2.position.y
            # mirroring covered by the overlap check (mirrored outputs will overlap)

    # Import/export
    @staticmethod
    def from_abstract (abstract, virtual_screen_min, virtual_screen_max, preferred_sizes_by_output):
        """
        Builds a new backend layout object from an abstract layout and external info
        Absolute layout positionning uses the c++ isl extension
        """
        concrete = ConcreteLayout (dict ([(name, Output (enabled = True, transform = o.transform.copy (), base_size = preferred_sizes_by_output[name])) for name, o in abstract.outputs.items ()]))
        # Compute absolute layout
        names = abstract.outputs.keys ()
        constraints = [ [ abstract.outputs[na].rel (nb) for nb in names ] for na in names ]
        r = slam_ext.screen_layout (virtual_screen_min, virtual_screen_max, [concrete.outputs[n].size () for n in names], constraints)
        if r == None: return None
        # Fill result
        concrete.virtual_screen_size = Pair (r[0])
        for i, name in zip (range (len (names)), names): concrete.outputs[name].position = Pair (r[1][i])
        return concrete

    def to_abstract (self):
        """
        Two screen are considered related if their borders are touching in the absolute layout
        """
        if self.manual: raise LayoutException ("cannot abstract ConcreteLayout in manual mode")
        outputs = set (self.outputs.items ())
        abstract = AbstractLayout (dict ([(name, AbstractLayout.Output (o.transform.copy ())) for name, o in outputs]))
        # Extract neighbouring relations
        for na, oa in outputs:
            for nb, ob in outputs - set ([(na, oa)]):
                oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
                if oa_corner.x == ob.position.x and (oa.position.y < ob_corner.y or oa_corner.y > ob.position.y): abstract.outputs[na].neighbours[nb], abstract.outputs[nb].neighbours[na] = Dir.left, Dir.right
                if oa_corner.y == ob.position.y and (oa.position.x < ob_corner.x or oa_corner.x > ob.position.x): abstract.outputs[na].neighbours[nb], abstract.outputs[nb].neighbours[na] = Dir.above, Dir.under
        return abstract

