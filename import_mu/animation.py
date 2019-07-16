# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

import bpy

property_map = {
    "m_LocalPosition.x": ("obj", "location", 0, 1),
    "m_LocalPosition.y": ("obj", "location", 2, 1),
    "m_LocalPosition.z": ("obj", "location", 1, 1),
    "m_LocalRotation.x": ("obj", "rotation_quaternion", 1, -1),
    "m_LocalRotation.y": ("obj", "rotation_quaternion", 3, -1),
    "m_LocalRotation.z": ("obj", "rotation_quaternion", 2, -1),
    "m_LocalRotation.w": ("obj", "rotation_quaternion", 0, 1),
    "m_LocalScale.x": ("obj", "scale", 0, 1),
    "m_LocalScale.y": ("obj", "scale", 2, 1),
    "m_LocalScale.z": ("obj", "scale", 1, 1),
    "m_Intensity": ("data", "energy", 0, 1),
    "m_Color.r": ("data", "color", 0, 1),
    "m_Color.g": ("data", "color", 1, 1),
    "m_Color.b": ("data", "color", 2, 1),
    "m_Color.a": ("data", "color", 3, 1),
}

vector_map = {
    "r": 0, "g": 1, "b": 2, "a":3,
    "x": 0, "y": 1, "z": 2, "w":3,  # shader props not read as quaternions
}

def property_index(properties, prop):
    for i, p in enumerate(properties):
        if p.name == prop:
            return i
    return None

def shader_property(obj, prop):
    prop = prop.split(".")
    if not obj or type(obj.data) != bpy.types.Mesh:
        return None
    if not obj.data.materials:
        return None
    for mat in obj.data.materials:
        mumat = mat.mumatprop
        for subpath in ["color", "vector", "float2", "float3", "texture"]:
            propset = getattr(mumat, subpath)
            if prop[0] in propset.properties:
                if subpath == "texture":
                    print("animated texture properties not yet supported")
                    print(prop)
                    return None
                if subpath[:5] == "float":
                    rnaIndex = 0
                else:
                    rnaIndex = vector_map[prop[1]]
                propIndex = property_index(propset.properties, prop[0])
                path = "mumatprop.%s.properties[%d].value" % (subpath, propIndex)
                return mat, path, rnaIndex
    return None

def create_fcurve(action, curve, propmap):
    dp, ind, mult = propmap
    fps = bpy.context.scene.render.fps
    fc = action.fcurves.new(data_path = dp, index = ind)
    fc.keyframe_points.add(len(curve.keys))
    for i, key in enumerate(curve.keys):
        x,y = key.time * fps + bpy.context.scene.frame_start, key.value * mult
        fc.keyframe_points[i].co = x, y
        fc.keyframe_points[i].handle_left_type = 'FREE'
        fc.keyframe_points[i].handle_right_type = 'FREE'
        if i > 0:
            dist = (key.time - curve.keys[i - 1].time) / 3
            dx, dy = dist * fps, key.tangent[0] * dist * mult
        else:
            dx, dy = 10, 0.0
        fc.keyframe_points[i].handle_left = x - dx, y - dy
        if i < len(curve.keys) - 1:
            dist = (curve.keys[i + 1].time - key.time) / 3
            dx, dy = dist * fps, key.tangent[1] * dist * mult
        else:
            dx, dy = 10, 0.0
        fc.keyframe_points[i].handle_right = x + dx, y + dy
    return True

def create_action(mu, path, clip):
    #print(clip.name)
    actions = {}
    for curve in clip.curves:
        if not curve.keys:
            print("Curve has no keys")
            continue
        if not curve.path:
            mu_path = path
        else:
            mu_path = "/".join([path, curve.path])
        if (mu_path not in mu.object_paths):
            print("Unknown path: %s" % (mu_path))
            continue
        muobj = mu.object_paths[mu_path]
        dppref = ""
        if hasattr(muobj, "bone"):
            obj = muobj.armature.armature_obj
            dppref = f'pose.bones["{muobj.bone}"].'
        elif hasattr(muobj, "bobj"):
            obj = muobj.bobj
        else:
            print("No blender object at path: %s" % (mu_path))
            continue

        if curve.property not in property_map:
            sp = shader_property(obj, curve.property)
            if not sp:
                print("%s: Unknown property: %s" % (mu_path, curve.property))
                continue
            obj, dp, rnaIndex = sp
            propmap = dp, rnaIndex, 1
            subpath = "obj"
        else:
            propmap = property_map[curve.property]
            subpath, propmap = propmap[0], propmap[1:]
        propmap = (dppref + propmap[0],) +  propmap[1:]

        objname = ".".join([obj.name, subpath])

        if subpath != "obj":
            obj = getattr (obj, subpath)

        name = objname
        if name not in actions:
            actions[name] = bpy.data.actions.new(name), obj
        act, obj = actions[name]
        if not create_fcurve(act, curve, propmap):
            continue
    for name in actions:
        act, obj = actions[name]
        if not obj.animation_data:
            obj.animation_data_create()
        track = obj.animation_data.nla_tracks.new()
        track.name = clip.name
        track.strips.new(act.name, 1.0, act)

def create_object_paths(mu):
    def recurse (mu, obj, parent_names, parent):
        obj.parent = parent
        obj.mu = mu
        name = obj.transform.name
        parent_names.append(name)
        obj.path = "/".join(parent_names)
        mu.objects[name] = obj
        mu.object_paths[obj.path] = obj
        for child in obj.children:
            recurse(mu, child, parent_names, obj)
        parent_names.pop()
    mu.objects = {}
    mu.object_paths = {}
    recurse(mu, mu.obj, [], None)
