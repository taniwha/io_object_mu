from mu import Mu
from utils import vect
import sys

def nice(tup):
    return "(" + ", ".join(map(lambda t:f"{t:.3f}", tup)) + ")"

class Transform:
    def __init__(self, loc, rot, scale, parent=None):
        rot = rot[0],rot[1:4]
        if parent:
            self.loc = parent.transformPoint(loc)
            self.rot = parent.transformRotation(rot)
            self.scale = parent.transformScale(scale)
        else:
            self.loc = loc
            self.rot = rot
            self.scale = scale
    def transformPoint(self, p):
        p = vect.mul(self.scale, p)
        p = vect.qmul(self.rot, p)
        p = vect.add(self.loc, p)
        return p
    def transformRotation(self, r):
        r = vect.qmul(self.rot, r)
        return r
    def transformScale(self, s):
        s = vect.mul(self.scale, s)
        s = vect.qmul(self.rot, s)
        return s
    def to_str(self):
        r = self.rot[0:1]+self.rot[1]
        return f"[{nice(self.loc)}, {nice(r)}, {nice(self.scale)}]"

def check_transform(obj, level, parent):
    x = obj.transform
    transform = Transform(x.localPosition, x.localRotation, x.localScale, parent)
    flags = ""
    flags += (" m" if hasattr(obj, "shared_mesh") else "")
    flags += (" r" if hasattr(obj, "renderer") else "")
    flags += (" s" if hasattr(obj, "skinned_mesh_renderer") else "")
    flags += (" c" if hasattr(obj, "collider") else "")
    #print("    " * level + obj.transform.name + flags + "\t" + transform.to_str())
    print("    " * level + obj.transform.name + flags)
    return transform

def check_obj(obj, parent, level = 0):
    transform = check_transform(obj, level, parent)
    for o in obj.children:
        check_obj(o, transform, level + 1)

for fname in sys.argv[1:]:
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    check_obj(mu.obj, Transform((0,0,0), (1,0,0,0), (1,1,1)))
