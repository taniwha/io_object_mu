from mu import Mu
import sys

def check_clip(clip, props):
    for curve in clip.curves:
        print(curve.path)
        props.add(curve.property)

def check_obj(obj, props):
    for o in obj.children:
        check_obj(o, props)
    if hasattr(obj, "animation"):
        for clip in obj.animation.clips:
            check_clip(clip, props)

def find_props(fname, props):
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    check_obj(mu.obj, props)

for f in sys.argv[1:]:
    props = set()
    try:
        find_props(f, props)
    except:
        pass
    if not props:
        continue
    print(f)
    props = list(props)
    props.sort()
    for p in props:
        print(p)
