import slam_ext
import math

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

    def __str__ (self): return "(%s,%s)" % (str (self.x), str (self.y))
    def __repr__ (self): return "(%s,%s)" % (repr (self.x), repr (self.y))
    def tuple (self): return self.x, self.y

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
        
        # User settings
        self.enabled = False
        self.rotation = Rotation ()

    def size (self): return self.rotation.true_size (self.base_size)
    def identifier (self): return self.name + (":" + self.edid if self.edid else "")

class Config (object):
    def __init__ (self):
        self.output_by_name = dict ()
        self.output_relations = dict () # map : name pair -> Dir
   
    def add_relation (self, sa, sb, relation):
        self.output_relations[sa, sb] = relation
        self.output_relations[sb, sa] = relation.invert ()

    def key (self):
        """ Key for ConfigManager """
        return frozenset ([o.identifier () for o in self.output_by_name.values ()])

    def relations_to_absolute_positions (self, vscreen_limits):
        """
        Compute absolute positions of screen layout :
            int Pair : vscreen size
            screen-name -> int Pair : positions of screens
        """
        # Convert arguments
        outputs = [o for o in self.output_by_name.values () if o.enabled]
        constraints = []
        for i in range (len (outputs)):
            for j in range (i):
                d = self.output_relations.get ((outputs[i].name, outputs[j].name))
                if d != Dir.none:
                    constraints.append ((i, d, j))
        # Compute
        r = slam_ext.screen_layout (vscreen_limits.tuple (), [o.size ().tuple () for o in outputs], constraints)
        if r == None: raise Exception ("unable to compute valid layout")
        # Convert back results
        vscreen_size, screen_pos = r
        return (Pair (vscreen_size), dict ([(outputs[i].name, Pair (screen_pos[i])) for i in range (len (outputs))]))

    def relations_from_absolute_positions (self, screen_positions):
        """ Extracts some relations from absolute position """
        # Add relations to screens that are border to border
        self.output_relations.clear ()
        for san in screen_positions:
            for sbn in screen_positions:
                if san != sbn:
                    sa_bottomright, sb_topleft = screen_positions[san] + self.output_by_name[san].size (), screen_positions[sbn]
                    if sa_bottomright.x == sb_topleft.x: self.add_relation (san, sbn, Dir.left)
                    if sa_bottomright.y == sb_topleft.y: self.add_relation (san, sbn, Dir.above)


class ConfigManager (object):
    def __init__ (self, vscreen_limits):
        self.vscreen_limits = vscreen_limits
        self.configurations = dict () 

    def set_config (self, conf):
        self.configurations[conf.key ()] = conf

