from mu import Mu
import sys

def check_obj(obj):
    dirty = False
    if hasattr(obj, "light"):
        if obj.light.cullingMask != 0x8001:
            obj.light.cullingMask = 0x8001
            dirty = True
    for child in obj.children:
        dirty |= check_obj(child)
    return dirty

def find_lights(fname):
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    if check_obj(mu.obj):
        print(fname)
        mu.write(fname+".new")

for f in sys.argv[1:]:
    try:
        find_lights(f)
    except:
        pass
