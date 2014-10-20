import slam_ext
import pickle

'''
Layout : for a given set of output, layout relations and rotations
LayoutSet : stores layout for each set of output
LayoutManager : stores layout sets for each set of tag
BackendLayout : a concretised layout with coordinates
'''

### Utils ###

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


### Layouts ###

class Layout (object):
    '''
    Abstract Layout, without sizes
    Only has transformations for screens, and relations between them
    Relations are duplicated (a < b && b > a)
    '''
    class Output (object):
        def __init__ (self, output_set):
            self.enabled = False
            self.transposed = False # x/y swap before rotation
            self.rotation = 0 # 0, 90, 180, 270
            self.neighbours = dict ([(name, Dir.none) for name in output_set]) # empty relation set

        def dump (self):
            return (self.enabled, self.transposed, self.rotation, self.neighbours)
        def load (self, data):
            (self.enabled, self.transposed, self.rotation, self.neighbours) = data

    def __init__ (self, output_set):
        self.outputs = dict ([(name, Output (output_set)) for name in output_set]) # init with empty layout

    def dump (self):
        return dict ([(name, output.dump ()) for name, output in self.outputs.items ()])
    def load (self, data):
        pass

class Config (object):
    '''
    Manages a set of layouts for a given tag set
    '''
    def __init__ (self):
        self.layouts = dict () # frozenset( (name,edid=null) ) -> Layout ()

    def dump (self): pass
    def load (self, data): pass

class Manager (object):
    '''
    Manages a set of configs
    '''
    def __init__ (self):
        self.configs = dict () # frozenset ( str ) -> Config ()
        self.current_tags = set () #

        self.current_backend_layout = None

    def backend_layout_changed (self, backend_layout):
        pass

    def dump (self):
        ''' Output all stored layouts as a string (uses pickle) '''
        pass
    def load (self, data):
        ''' Loads all stored layouts from a string (uses pickle) '''
        pass


### Backend Layout ###

class BackendLayout (object):
    '''
    Instanciated Layout, with sizes and absolute positions
    '''
    class Output (object):
        rotations = { 0: False, 90: True, 180: False, 270: True }
        def __init__ (self):
            self.enabled = False
            self.transposed = False
            self.rotation = 0
            self.base_size = Pair (0, 0)
            self.position = Pair (0, 0)
        def size (self):
            return self.base_size.swap () if Output.rotations[self.rotation] is not self.transposed else base_size

    def __init__ (self, output_set):
        self.outputs = dict ([(name, Output ()) for name in output_set]) # init with empty layout
        self.screen_size = Pair (0, 0)

    # Import/export
    @staticmethod
    def from_layout (layout, vscreen_min, vscreen_max, sizes):
        '''
        Builds a new backend layout object from an abstract layout and external info
        Absolute layout positionning uses the c++ isl extension
        '''
        # Copy common struct data
        r = BackendLayout (layout.outputs) # empty init
        for name, o in r.outputs.items ():
            t = layout.outputs[name]
            (o.enabled, o.transposed, o.rotation) = (t.enabled, t.transposed, t.rotation)
            o.base_size = sizes[name]
        # Compute absolute layout
        enabled_outputs = [name for name, o in r.outputs.items () if o.enabled]
        enabled_sizes = [r.outputs[n].size () for n in enabled_outputs]
        constraints = [ [ layout.outputs[na].neighbours[nb] for nb in enabled_outputs ] for na in enabled_outputs ]
        res = slam_ext.screen_layout (vscreen_min, vscreen_max, enabled_sizes, constraints)
        if res == None: return None
        # Fill result
        r.screen_size = Pair (res[0])
        for i in range (len (enabled_outputs)): r.outputs[enabled_outputs[i]].position = Pair (res[1][i])
        return r

    def to_layout (self):
        '''
        Two screen are considered related if their borders are touching in the absolute layout
        '''
        # Copy base info
        r = Layout (self.outputs)
        for name, o in self.outputs.items ():
            t = r.outputs[name]
            (t.enabled, t.transposed, t.rotation) = (o.enabled, o.transposed, o.rotation)
        # Extract neighbouring relations
        for na, oa in self.outputs.items ():
            for nb, ob in self.outputs.items ():
                if oa.enabled and ob.enabled and na != nb:
                    oa_corner, ob_corner = oa.position + oa.size (), ob.position + ob.size ()
                    if oa_corner.x == ob.position.x and (oa.position.y < ob_corner.y or oa_corner.y > ob.position.y): oa.neighbours[nb], ob.neighbours[na] = Dir.left, Dir.right
                    if oa_corner.y == ob.position.y and (oa.position.x < ob_corner.x or oa_corner.x > ob.position.x): oa.neighbours[nb], ob.neighbours[na] = Dir.above, Dir.under
        return r

