from mu import Mu
import sys

def check_clip(clip, props, clips, path):
    for curve in clip.curves:
        props.add(curve.property)

        if clip.name not in clips:
            clips[clip.name] = {}
        curves = clips[clip.name]
        if curve.path not in curves:
            curves[curve.path] = {}
        properties = curves[curve.path]
        if not hasattr(curve, "keys") or not curve.keys:
            properties[curve.property] = "0 static"
        else:
            count = len(curve.keys)
            properties[curve.property] = f"{count} static"
            initValue = curve.keys[0].value
            for k in curve.keys:
                if k.value != initValue:
                    properties[curve.property] = f"{count} animated"

def check_obj(obj, props, anims, path):
    if path:
        path = path + "/"
    path = path + obj.transform.name
    for o in obj.children:
        check_obj(o, props, anims, path)
    if hasattr(obj, "animation"):
        anims[path] = {}
        for clip in obj.animation.clips:
            check_clip(clip, props, anims[path], path)

def find_props(fname, props, anims):
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    check_obj(mu.obj, props, anims, "")

for f in sys.argv[1:]:
    props = set()
    anims = {}
    find_props(f, props, anims)
    if not props:
        continue
    print(f)
    props = list(props)
    props.sort()
    for p in props:
        print(p)
    objs = list(anims.keys())
    objs.sort()
    for o in objs:
        print(f"{o}")
        clips = list(anims[o].keys())
        clips.sort()
        for c in clips:
            print(f"    {c}")
            paths = list(anims[o][c].keys())
            paths.sort()
            for p in paths:
                print(f"        {p}")
                props = list(anims[o][c][p].keys())
                props.sort()
                for pr in props:
                    print(f"            {pr}: {anims[o][c][p][pr]}")
