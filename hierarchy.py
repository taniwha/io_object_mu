from mu import Mu
import sys

def check_transform(obj, level):
    print("    " * level + obj.transform.name + (" c" if hasattr(obj, "collider") else ""))

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
