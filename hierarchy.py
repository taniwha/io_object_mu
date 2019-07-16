from mu import Mu
import sys

def check_transform(obj, level):
    flags = ""
    flags += (" m" if hasattr(obj, "shared_mesh") else "")
    flags += (" r" if hasattr(obj, "renderer") else "")
    flags += (" s" if hasattr(obj, "skinned_mesh_renderer") else "")
    flags += (" c" if hasattr(obj, "collider") else "")
    print("    " * level + obj.transform.name + flags)

def check_obj(obj, level = 0):
    check_transform(obj, level)
    for o in obj.children:
        check_obj(o, level + 1)

for fname in sys.argv[1:]:
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    check_obj(mu.obj)
