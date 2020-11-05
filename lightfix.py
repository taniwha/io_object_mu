from mu import Mu
import sys

def check_obj(obj):
    """
    Check if the given object is an object.

    Args:
        obj: (todo): write your description
    """
    dirty = False
    if hasattr(obj, "light"):
        if obj.light.cullingMask != 0x828001:
            obj.light.cullingMask = 0x828001
            dirty = True
    for child in obj.children:
        dirty |= check_obj(child)
    return dirty

def find_lights(fname):
    """
    Finds the roots file

    Args:
        fname: (str): write your description
    """
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    sys.stdout.write("checking " + fname)
    if check_obj(mu.obj):
        mu.write(fname+".new")
        print(" fixed")
    else:
        print(" ok")

for f in sys.argv[1:]:
    try:
        find_lights(f)
    except:
        pass
