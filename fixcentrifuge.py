from mu import Mu
import sys

def check_clip(clip):
    i = len(clip.curves)
    while i > 0:
        i -= 1
        curve = clip.curves[i]
        if curve.path == "Center_Cylinder/coll torus":
            print("deleting " + curve.path + ", " + curve.property)
            del clip.curves[i]
            continue
        if curve.path[:-1] == "Center_Cylinder/coll torus/coll_torus":
            if curve.property[:-1] == "m_LocalPosition.":
                print("deleting " + curve.path + ", " + curve.property)
                del clip.curves[i]
                continue
            if curve.property == "m_LocalScale.y":
                print("deleting " + curve.path + ", " + curve.property)
                del clip.curves[i]
                continue

broken_xforms = [
    "coll torus",
    "coll_torus1",
    "coll_torus2",
    "coll_torus3",
    "coll_torus4",
    "coll_torus5",
    "coll_torus6",
    "coll_torus7",
    "coll_torus8",
]

def check_transform(obj):
    if obj.transform.name in broken_xforms:
        print("zeroing lp for " + obj.transform.name)
        obj.transform.localPosition = 0, 0, 0

def check_obj(obj):
    for o in obj.children:
        check_obj(o)
    check_transform(obj)
    if hasattr(obj, "animation"):
        for clip in obj.animation.clips:
            check_clip(clip)

fname = "centrifuge.mu"
mu = Mu()
if not mu.read(fname):
    print("could not read: " + fname)
    raise
check_obj(mu.obj)
mu.write("output.mu")
