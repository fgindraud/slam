import slam_ext
import pickle

### Utils ###

class TransformException (Exception):
    pass
class LayoutException (Exception):
    pass

# Directions
Dir = slam_ext.Dir
Dir.invert = slam_ext.Dir_invert
Dir.__str__ = slam_ext.Dir_str

# Pair of objects
class Pair (object):
    def __init__ (self, x, y = None):
        """ Takes a pair of values, or an iterable """
        if y == None: x, y = x
        self.x, self.y = x, y
    
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
    def rectangle_size (self, size): return size.swap () if self.inverted () else Pair (size)

    def dump (self): return (self.reflect, self.rotation)
    @staticmethod def load (data): return Transform (*data)

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

        def dump (self): return (self.transform.dump (), self.neighbours)
        @staticmethod def load (data): return Output (Transform.load (data[0]), data[1])

    def __init__ (self, outputs = {}):
        if isinstance (arg, AbstractLayout): # copy
            self.outputs = dict ([(name, Output (o)) for name, o in arg.outputs.items ()])
        else: # init, treating arg as an iterable with list of output names
            self.outputs = dict ([(name, Output (arg)) for name in arg]) # init with empty layout

    def copy (self):
        pass

    def dump (self): return dict ([(name, output.dump ()) for name, output in self.outputs.items ()])
    @staticmethod def load (data): return AbstractLayout (dict ([(name, Output.load (d)) for name, d in data.items ()]))

class Config (object):
    """
    Manages a set of abstracts layouts for a given tag set
    """
    def __init__ (self):
        self.layouts = dict () # frozenset( (name,edid=null) ) -> Layout ()

    def dump (self): pass
    def load (self, data): pass

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
        pass

    def dump (self):
        """ Output all stored layouts as a string (uses pickle) """
        pass
    def load (self, data):
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
        def __init__ (self):
            self.enabled = False # if false, ignore every other parameter
            self.transform = Transform ()
            self.base_size = Pair (0, 0)
            self.position = Pair (0, 0)
            self.edid = None # only filled by backend when signaling a new layout
        def size (self): return self.transform.rectangle_size (self.base_size)

    def __init__ (self, output_set):
        self.outputs = dict ([(name, Output ()) for name in output_set]) # init with empty layout
        self.virtual_screen_size = Pair (0, 0)
        self.manual = False

    def key (self):
        return frozenset ([(name, o.edid) for name, o in self.outputs])

    def compute_manual_flag (self, preferred_sizes_by_output):
        self.manual = False
        for name, o in self.outputs.items ():
            self.manual |= not o.enabled # disabled outputs
            self.manual |= preferred_sizes_by_output[name] != o.base_size # not preferred mode
            # overlap check
            end_corner = o.position + o.size ()
            for n2, o2 in self.outputs.items ():
                if n2 != name:
                    self.manual |= end_corner.x <= o2.position.x and end_corner.y <= o2.position.y
            # mirroring covered by the overlap check (mirrored outputs will overlap)

    # Import/export
    @staticmethod
    def from_abstract (abstract, virtual_screen_min, virtual_screen_max, preferred_sizes_by_output):
        """
        Builds a new backend layout object from an abstract layout and external info
        Absolute layout positionning uses the c++ isl extension
        """
        # Copy common struct data
        concrete = ConcreteLayout (abstract.outputs) # empty init, set as non manual
        for name, o in concrete.outputs.items ():
            o.enabled, o.transform, o.base_size = True, abstract.outputs[name].transform.copy (), preferred_sizes_by_output[name]
        # Compute absolute layout
        names = concrete.outputs.keys ()
        constraints = [ [ abstract.outputs[na].neighbours[nb] for nb in names ] for na in names ]
        r = slam_ext.screen_layout (virtual_screen_min, virtual_screen_max, [o.size () for o in concrete.outputs.values ()], constraints)
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
        # Copy common struct data
        abstract = AbstractLayout (self.outputs)
        for name, o in self.outputs.items (): abstract.outputs[name].transform = o.transform.copy ()
        # Extract neighbouring relations
        outputs = set (self.outputs.items ())
        for na, oa in outputs:
            for nb, ob in outputs - set ([(na, oa)]):
                oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
                if oa_corner.x == ob.position.x and (oa.position.y < ob_corner.y or oa_corner.y > ob.position.y): abstract.outputs[na].neighbours[nb], abstract.outputs[nb].neighbours[na] = Dir.left, Dir.right
                if oa_corner.y == ob.position.y and (oa.position.x < ob_corner.x or oa_corner.x > ob.position.x): abstract.outputs[na].neighbours[nb], abstract.outputs[nb].neighbours[na] = Dir.above, Dir.under
        return abstract

