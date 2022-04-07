from mu import Mu
from utils import vect
import sys

def nice(tup):
    return "(" + ", ".join(map(lambda t:f"{t:6.3f}", tup)) + ")"

class Transform:
    def __init__(self, loc, rot, scale, parent=None):
        rot = rot[0],rot[1:4]
        self.loc = loc
        self.rot = rot
        self.scale = scale
        self.wloc = loc
        self.wrot = rot
        self.wscale = scale
        if parent:
            self.wloc = parent.transformPoint(loc)
            self.wrot = parent.transformRotation(rot)
            self.wscale = parent.transformScale(scale)
    def transformPoint(self, p):
        p = vect.mul(self.wscale, p)
        p = vect.qmul(self.wrot, p)
        p = vect.add(self.wloc, p)
        return p
    def transformDirection(self, d):
        return vect.qmul(self.wrot, d)
    def transformRotation(self, r):
        r = vect.qmul(self.wrot, r)
        return r
    def transformScale(self, s):
        s = vect.mul(self.wscale, s)
        s = vect.qmul(self.wrot, s)
        return s
    def to_str(self, world):
        if world:
            r = self.wrot[0:1]+self.wrot[1]
            return f"[{nice(self.wloc)}, {nice(r)}, {nice(self.wscale)}]"
        else:
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
    flags += (" a" if hasattr(obj, "animation") else "")
    if hasattr(obj, "tag_and_layer"):
        if obj.tag_and_layer.tag and obj.tag_and_layer.tag != "Untagged":
            flags += " " + obj.tag_and_layer.tag
        if obj.tag_and_layer.layer:
            flags += " " + str(obj.tag_and_layer.layer)
    print("    " * level + obj.transform.name + flags)
    #print("    " * level + obj.transform.name + flags + "\t" + transform.to_str(False))
    #print("    " * level + "\t" + transform.to_str(True))
    #print("    " * level + "\t  X:" + nice(transform.transformDirection((1,0,0))))
    #print("    " * level + "\t  Y:" + nice(transform.transformDirection((0,1,0))))
    #print("    " * level + "\t  Z:" + nice(transform.transformDirection((0,0,1))))
    #print("    " * level + obj.transform.name + flags)
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
