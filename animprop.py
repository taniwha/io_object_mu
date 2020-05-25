from mu import Mu
import sys
from pprint import pprint

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
            properties[curve.property] = ["0 static", []]
        else:
            count = len(curve.keys)
            properties[curve.property] = [f"{count} static", [None] * count]
            initValue = curve.keys[0].value
            for i, k in enumerate(curve.keys):
                properties[curve.property][1][i] = k.value
                if k.value != initValue or k.tangent[0] or k.tangent[1]:
                    properties[curve.property][0] = f"{count} animated"

def check_obj(obj, props, anims, path, mu):
    if path:
        path = path + "/"
    path = path + obj.transform.name
    mu.objects[path] = obj
    for o in obj.children:
        check_obj(o, props, anims, path, mu)
    if hasattr(obj, "animation"):
        anims[path] = {}
        for clip in obj.animation.clips:
            check_clip(clip, props, anims[path], path)

def find_props(fname, props, anims):
    mu = Mu()
    mu.objects = {}
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    check_obj(mu.obj, props, anims, "", mu)
    return mu

def nice(tup):
    return "(" + ", ".join(map(lambda t:f"{t:6.3f}", tup)) + ")"

for f in sys.argv[1:]:
    props = set()
    anims = {}
    mu = find_props(f, props, anims)
    #pprint(mu.objects)
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
        """for c in clips:
            print(f"    {c}")
            paths = list(anims[o][c].keys())
            paths.sort()
            for p in paths:
                print(f"        {p}")
                props = list(anims[o][c][p].keys())
                props.sort()
                for pr in props:
                    print(f"            {pr}: {anims[o][c][p][pr][0]}")"""
        for c in clips:
            print(f"    {c}")
            paths = list(anims[o][c].keys())
            paths.sort()
            for p in paths:
                propset = anims[o][c][p]
                if not p:
                    path = o
                else:
                    path = "/".join([o, p])
                obj = mu.objects[path]
                loc = obj.transform.localPosition
                rot = obj.transform.localRotation
                scale = obj.transform.localScale
                #put back into unity format
                loc = [loc[0],loc[2],loc[1]]
                rot = [-rot[1],-rot[3],-rot[2],rot[0]]
                scale = [scale[0],scale[2],scale[1]]
                print(f"        {p}")
                print(f"            {obj.transform.name}")
                print(f"                 {nice(loc)} {nice(rot)} {nice(scale)}")
                count = 0
                for pr in propset:
                    count = max(count, len(propset[pr][1]))
                for i in range(count):
                    if ("m_LocalPosition.x" in propset
                        and i < len(propset["m_LocalPosition.x"][1])):
                        loc[0] = propset["m_LocalPosition.x"][1][i]
                    if ("m_LocalPosition.y" in propset
                        and i < len(propset["m_LocalPosition.y"][1])):
                        loc[1] = propset["m_LocalPosition.y"][1][i]
                    if ("m_LocalPosition.z" in propset
                        and i < len(propset["m_LocalPosition.z"][1])):
                        loc[2] = propset["m_LocalPosition.z"][1][i]
                    if ("m_LocalScale.x" in propset
                        and i < len(propset["m_LocalScale.x"][1])):
                        scale[0] = propset["m_LocalScale.x"][1][i]
                    if ("m_LocalScale.y" in propset
                        and i < len(propset["m_LocalScale.y"][1])):
                        scale[1] = propset["m_LocalScale.y"][1][i]
                    if ("m_LocalScale.z" in propset
                        and i < len(propset["m_LocalScale.z"][1])):
                        scale[2] = propset["m_LocalScale.z"][1][i]
                    if ("m_LocalRotation.x" in propset
                        and i < len(propset["m_LocalRotation.x"][1])):
                        rot[0] = propset["m_LocalRotation.x"][1][i]
                    if ("m_LocalRotation.y" in propset
                        and i < len(propset["m_LocalRotation.y"][1])):
                        rot[1] = propset["m_LocalRotation.y"][1][i]
                    if ("m_LocalRotation.z" in propset
                        and i < len(propset["m_LocalRotation.z"][1])):
                        rot[2] = propset["m_LocalRotation.z"][1][i]
                    if ("m_LocalRotation.w" in propset
                        and i < len(propset["m_LocalRotation.w"][1])):
                        rot[3] = propset["m_LocalRotation.w"][1][i]
                    print(f"            {i:4d} {nice(loc)} {nice(rot)} {nice(scale)}")
