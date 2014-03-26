import slam_ext

# Config
class Pair (object):
    def __init__ (self, x = 0, y = 0): self.x, self.y = x, y
    def __add__ (self, other): return Pair (self.x + other.x, self.y + other.y)
    def __str__ (self): return "(%s,%s)" % (str (self.x), str (self.y))

class Config (object):
    def __init__ (self):
        self.output_by_name = dict ()
    
    def key (self):
        pass

# Entry point
if __name__ == "__main__":
    print slam_ext.screen_layout ((32000,32000), [(1600, 900), (1920, 1080)], [(0, slam_ext.dir.left, 1)])
