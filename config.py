import slam_ext
import math

# Pair of objects
class Pair (object):
    def __init__ (self, x = None, y = None):
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

# Directions
Dir = slam_ext.Dir
Dir.invert = slam_ext.Dir_invert
Dir.__str__ = slam_ext.Dir_str

# Rotation
class Rotation (object):
    """ Stores rotation (degrees) and mirroring state (x, y) """
    rotations = { 0: False, 90: True, 180: False, 270: True }
    
    def __init__ (self):
        self.rot = 0
        self.mirror = Pair (False, False)
    def true_size (self, base_size):
        """ Compute size of screen after rotation """
        return base_size.swap () if Rotation.rotations[self.rot] else base_size

class Output (object):
    def __init__ (self):
        # System constant properties
        self.name = ""
        self.base_size = Pair (0, 0)
        self.edid = None
        
        # User
        self.enabled = False
        self.rotation = Rotation ()
        self.position = Pair (0, 0)
        
        # Props
        self.backlight = None # (value, lowest, highest)

    def size (self): return self.rotation.true_size (self.base_size)
    def identifier (self): return self.name + (":" + self.edid if self.edid else "")

class Config (object):
    def __init__ (self):
        self.virtual_screen_size = Pair (0, 0)
        self.output_by_name = dict ()
        self.output_relations = dict () # map : name pair -> Dir
   
    def add_relation (self, sa, sb, relation):
        self.output_relations[sa, sb] = relation
        self.output_relations[sb, sa] = relation.invert ()

    def key (self):
        """ Key for ConfigManager """
        return frozenset ([o.identifier () for o in self.output_by_name.values ()])

    def compute_absolute_positions (self, vscreen_min, vscreen_max):
        # Convert arguments
        outputs = [o for o in self.output_by_name.values () if o.enabled]
        constraints = []
        for i in range (len (outputs)):
            for j in range (i):
                d = self.output_relations.get ((outputs[i].name, outputs[j].name))
                if d != Dir.none:
                    constraints.append ((i, d, j))
        # Compute
        r = slam_ext.screen_layout (vscreen_min, vscreen_max, [o.size () for o in outputs], constraints)
        if r == None: raise Exception ("unable to compute valid layout")
        # Convert back results
        self.virtual_screen_size = Pair (r[0])
        for i in range (len (outputs)): outputs[i].position = Pair (r[1][i])

    def compute_relations (self):
        # Add relations to screens that are border to border
        outputs = [o for o in self.output_by_name.values () if o.enabled]
        self.output_relations.clear ()
        for oa in outputs:
            for ob in outputs:
                if oa.name != ob.name:
                    oa_bottomright, ob_topleft = oa.position + oa.size (), ob.position
                    if oa_bottomright.x == ob_topleft.x: self.add_relation (oa.name, ob.name, Dir.left)
                    if oa_bottomright.y == ob_topleft.y: self.add_relation (oa.name, ob.name, Dir.above)

class ConfigManager (object):
    def __init__ (self, layout_backend):
        self.layout_backend = layout_backend
        self.virtual_screen_limits = layout_backend.get_virtual_screen_limits ()
        layout_backend.set_config_changed_callback (lambda new_config: self.config_changed (new_config))

        self.current_config = None
        self.configurations = dict ()

    def config_changed (self, new_config):
        pass

    def set_config (self, conf):
        self.configurations[conf.key ()] = conf

