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
from mathutils import Quaternion
from math import pi

from .. import properties
from ..mu import Mu
from ..mu import MuObject, MuTransform, MuTagLayer, MuRenderer, MuLight
from ..mu import MuCamera
from ..attachnode import AttachNode
from ..utils import strip_nnn

from .mesh import make_mesh
from .collider import make_collider
from .animation import collect_animations, find_path_root, make_animations
from .material import make_material
from .cfgfile import generate_cfg
from .volume import model_volume

def make_transform(obj):
    transform = MuTransform()
    transform.name = strip_nnn(obj.name)
    transform.localPosition = obj.location
    if obj.rotation_mode != 'QUATERNION':
      transform.localRotation = obj.rotation_euler.to_quaternion()
    else:
      transform.localRotation = obj.rotation_quaternion
    transform.localScale = obj.scale
    return transform

def make_tag_and_layer(obj):
    tl = MuTagLayer()
    tl.tag = obj.muproperties.tag
    tl.layer = obj.muproperties.layer
    return tl

def make_renderer(mu, mesh):
    rend = MuRenderer()
    #FIXME shadows
    rend.materials = []
    for mat in mesh.materials:
        if mat.mumatprop.shaderName:
            if mat.name not in mu.materials:
                mu.materials[mat.name] = make_material(mu, mat)
            rend.materials.append(mu.materials[mat.name].index)
    if not rend.materials:
        return None
    return rend

def make_light(mu, light, obj):
    mulight = MuLight()
    mulight.type = ('SPOT', 'SUN', 'POINT', 'AREA').index(light.type)
    mulight.color = tuple(light.color) + (1.0,)
    mulight.range = light.distance
    mulight.intensity = light.energy
    mulight.spotAngle = 0.0
    mulight.cullingMask = properties.GetPropMask(obj.muproperties.cullingMask)
    if light.type == 'SPOT':
        mulight.spotAngle = light.spot_size * 180 / pi
    return mulight

def make_camera(mu, camera, obj):
    mucamera = MuCamera()
    clear = obj.muproperties.clearFlags
    flags = ('SKYBOX', 'COLOR', 'DEPTH', 'NOTHING').index(clear)
    mucamera.clearFlags = flags + 1
    mucamera.backgroundColor = obj.muproperties.backgroundColor
    mucamera.cullingMask = properties.GetPropMask(obj.muproperties.cullingMask)
    mucamera.orthographic = camera.type == 'ORTHO'
    mucamera.fov = camera.angle * 180 / pi
    mucamera.near = camera.clip_start
    mucamera.far = camera.clip_end
    mucamera.depth = obj.muproperties.depth
    return mucamera

light_types = {
    bpy.types.PointLight,
    bpy.types.SunLight,
    bpy.types.SpotLight,
    bpy.types.HemiLight,
    bpy.types.AreaLight
}

exportable_types = {bpy.types.Mesh, bpy.types.Camera} | light_types

def is_group_root(obj, group):
    print(obj.name)
    while obj.parent:
        obj = obj.parent
        print(obj.name, obj.users_group)
        if group.name not in obj.users_group:
            return False
    return True

def make_obj(mu, obj, special, path = ""):
    muobj = MuObject()
    muobj.transform = make_transform (obj)
    if path:
        path += "/"
    path += muobj.transform.name
    mu.object_paths[path] = muobj
    muobj.tag_and_layer = make_tag_and_layer(obj)
    if not obj.data:
        name = strip_nnn(obj.name)
        if name[:5] == "node_":
            n = AttachNode(obj, mu.inverse)
            mu.nodes.append(n)
            if not n.keep_transform():
                return None
            # Blender's empties use the +Z axis for single-arrow display, so
            # that is the most natural orientation for nodes in blender.
            # However, KSP uses the transform's +Z (Unity) axis which is
            # Blender's +Y, so rotate 90 degrees around local X to go from
            # Blender to KSP
            rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
            muobj.transform.localRotation = muobj.transform.localRotation @ rot
        elif name in ["CoMOffset", "CoPOffset", "CoLOffset"]:
            setattr(mu, name, (mu.inverse @ obj.matrix_world.col[3])[:3])
        pass
    if not obj.data and obj.dupli_group:
        group = obj.dupli_group
        for o in group.objects:
            # while KSP models (part/prop/internal) will have only one root
            # object, grouping might be used for other purposes (eg, greeble)
            # so support multiple group root objects
            if not is_group_root(o, group):
                continue
            #easiest way to deal with dupli_offset is to temporarily shift
            #the object by the offset and then restor the object's location
            loc = o.location
            o.location -= group.dupli_offset
            child = make_obj(mu, o, special, path)
            o.location = loc
            if child:
                muobj.children.append(child)
    elif obj.muproperties.collider and obj.muproperties.collider != 'MU_COL_NONE':
        # colliders are children of the object representing the transform so
        # they are never exported directly.
        pass
    elif obj.data:
        if type(obj.data) == bpy.types.Mesh:
            muobj.shared_mesh = make_mesh(mu, obj)
            muobj.renderer = make_renderer(mu, obj.data)
        elif type(obj.data) in light_types:
            muobj.light = make_light(mu, obj.data, obj)
            # Blender points spotlights along local -Z, unity along local +Z
            # which is Blender's +Y, so rotate -90 degrees around local X to
            # go from Blender to Unity
            rot = Quaternion((0.5**0.5,-0.5**0.5,0,0))
            muobj.transform.localRotation = muobj.transform.localRotation @ rot
        elif type(obj.data) == bpy.types.Camera:
            muobj.camera = make_camera(mu, obj.data, obj)
            # Blender points camera along local -Z, unity along local +Z
            # which is Blender's +Y, so rotate -90 degrees around local X to
            # go from Blender to Unity
            rot = Quaternion((0.5**0.5,-0.5**0.5,0,0))
            muobj.transform.localRotation = muobj.transform.localRotation @ rot
    for o in obj.children:
        muprops = o.muproperties
        if muprops.modelType in special:
            if special[muprops.modelType](mu, o):
                continue
        if muprops.collider and muprops.collider != 'MU_COL_NONE':
            muobj.collider = make_collider(mu, o)
            continue
        if (o.data and type(o.data) not in exportable_types):
            continue
        child = make_obj(mu, o, special, path)
        if child:
            muobj.children.append(child)
    return muobj

def add_internal(mu, obj):
    if not mu.internal:
        mu.internal = obj
    return True

def add_prop(mu, obj):
    mu.props.append(obj)
    return True

special_modelTypes = {
    'NONE': {},
    'PART': {'INTERNAL':add_internal},
    'PROP': {},
    'INTERNAL': {'PROP':add_prop},
}

def export_object(obj, filepath):
    animations = collect_animations(obj)
    anim_root = find_path_root(animations)
    mu = Mu()
    mu.name = strip_nnn(obj.name)
    mu.object_paths = {}
    mu.materials = {}
    mu.textures = {}
    mu.nodes = []
    mu.props = []
    mu.internal = None
    mu.type = obj.muproperties.modelType
    mu.CoMOffset = None
    mu.CoPOffset = None
    mu.CoLOffset = None
    mu.inverse = obj.matrix_world.inverted()
    mu.obj = make_obj(mu, obj, special_modelTypes[mu.type])
    mu.materials = list(mu.materials.values())
    mu.materials.sort(key=lambda x: x.index)
    mu.textures = list(mu.textures.values())
    mu.textures.sort(key=lambda x: x.index)
    if anim_root:
        anim_root_obj = mu.object_paths[anim_root]
        anim_root_obj.animation = make_animations(mu, animations, anim_root)
    mu.write(filepath)
    mu.skin_volume, mu.ext_volume = model_volume(obj)
    generate_cfg(mu, filepath)
    return mu
