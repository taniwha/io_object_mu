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
from mathutils import Vector, Quaternion

from .. import properties
from ..mu import Mu
from ..mu import MuObject, MuTransform, MuTagLayer
from ..utils import strip_nnn

from .animation import collect_animations, find_path_root, make_animations
from .collider import make_collider
from .cfgfile import generate_cfg
from .volume import model_volume

def make_transform(obj):
    transform = MuTransform()
    transform.name = strip_nnn(obj.name)
    transform.localPosition = Vector(obj.location)
    if obj.rotation_mode != 'QUATERNION':
      transform.localRotation = obj.rotation_euler.to_quaternion()
    else:
      transform.localRotation = Quaternion(obj.rotation_quaternion)
    transform.localScale = Vector(obj.scale)
    return transform

def make_tag_and_layer(obj):
    tl = MuTagLayer()
    tl.tag = obj.muproperties.tag
    tl.layer = obj.muproperties.layer
    return tl

type_handlers = {} # filled in by the modules that handle the obj.data types
exported_objects = set()

def is_collider(obj):
    muprops = obj.muproperties
    if muprops.collider and muprops.collider != 'MU_COL_NONE':
        return True
    return False

def find_single_collider(objects):
    colliders = []
    for o in objects:
        if is_collider(o):
            colliders.append(o)
    if len(colliders) == 1:
        return colliders[0]
    return None

def make_obj_core(mu, obj, path, muobj):
    if path:
        path += "/"
    path += muobj.transform.name
    mu.object_paths[path] = muobj
    muobj.tag_and_layer = make_tag_and_layer(obj)
    if is_collider(obj):
        exported_objects.add(obj)
        muobj.collider = make_collider(mu, obj)
        return muobj
    elif type(obj.data) in type_handlers:
        mu.path = path  #needs to be reset as a type handler might modify it
        muobj = type_handlers[type(obj.data)](obj, muobj, mu)
        if not muobj:
            # the handler decided the object should not be exported
            return None
    exported_objects.add(obj)
    col = find_single_collider(obj.children)
    if col:
        exported_objects.add(col)
        muobj.collider = make_collider(mu, col)
    for o in obj.children:
        if o in exported_objects:
            # the object has already been exported
            continue
        muprops = o.muproperties
        #check whether the object should be exported (eg, props should not be
        #exported as part of an IVA, and IVAs should not be exported as part
        #of a part (that sounds odd)
        if muprops.modelType in mu.special:
            if mu.special[muprops.modelType](mu, o):
                continue
        child = make_obj(mu, o, path)
        if child:
            muobj.children.append(child)
    return muobj

def make_obj(mu, obj, path):
    if obj in exported_objects:
        # the object has already been "exported"
        return None
    muobj = MuObject()
    muobj.transform = make_transform (obj)
    return make_obj_core(mu, obj, path, muobj)

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
    exported_objects.clear()
    animations = collect_animations(obj)
    anim_root = find_path_root(animations)
    mu = Mu()
    mu.name = strip_nnn(obj.name)
    mu.object_paths = {}
    mu.materials = {}
    mu.textures = {}
    mu.nodes = []
    mu.props = []
    mu.messages = []
    mu.internal = None
    mu.type = obj.muproperties.modelType
    mu.CoMOffset = None
    mu.CoPOffset = None
    mu.CoLOffset = None
    mu.inverse = obj.matrix_world.inverted()
    mu.special = special_modelTypes[mu.type]
    mu.obj = make_obj(mu, obj, "")
    mu.materials = list(mu.materials.values())
    mu.materials.sort(key=lambda x: x.index)
    mu.textures = list(mu.textures.values())
    mu.textures.sort(key=lambda x: x.index)
    if anim_root and anim_root in mu.object_paths:
        anim_root_obj = mu.object_paths[anim_root]
        anim_root_obj.animation = make_animations(mu, animations, anim_root)
    mu.write(filepath)
    mu.skin_volume, mu.ext_volume = model_volume(obj)
    generate_cfg(mu, filepath)
    return mu
