import sys

from mu import Mu
from utils import vect
from quickhull.rawmesh import RawMesh
from quickhull.binary import BinaryWriter

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

def transform_verts(transform, mesh_verts):
    verts = [None] * len(mesh_verts)
    for i, v in enumerate(mesh_verts):
        #v = transform.transformPoint(v)
        verts[i] = v[0], v[2], v[1]
    return verts

def collect_verts(obj, parent):
    x = obj.transform
    transform = Transform(x.localPosition, x.localRotation, x.localScale, parent)
    verts = []
    if hasattr(obj, "shared_mesh") and hasattr(obj, "renderer"):
        verts = transform_verts(transform, obj.shared_mesh.verts)
    elif hasattr(obj, "skinned_mesh_renderer"):
        verts = transform_verts(transform_verts, obj.skinned_mesh_renderer.mesh.verts)
    for o in obj.children:
        verts.extend(collect_verts(o, transform))
    return verts

    

fname =sys.argv[1]
mu = Mu()
if not mu.read(fname):
    print(f"could not read: {fname}")
    sys.exit(1)
rm = RawMesh()
rm.verts = collect_verts(mu.obj, Transform((0, 0, 0), (1, 0, 0, 0), (1, 1, 1)))
bw = BinaryWriter(open(sys.argv[2], "wb"))
rm.write(bw)
bw.close()
