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
from ..utils import strip_nnn, collect_collections

from .animation import collect_animations, find_path_root, make_animations
from .collider import make_collider
from .cfgfile import generate_cfg
from .export_util import is_collider
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
    def create_tag_layer(single_obj):
        try:
            # ORIGINAL code - working animations (patch 1)
            tl = MuTagLayer()
            tl.tag = single_obj.muproperties.tag # original: tl.tag = obj.muproperties.tag
            tl.layer = single_obj.muproperties.layer # original: tl.layer = obj.muproperties.layer
            return tl
        except AttributeError as e:
            print(f"Error processing object: {e}")
            return None
    # ALTERNATIVE code - handle damaged animations to export !!! (patch 1)
    try:
        if isinstance(obj, list):
            return [create_tag_layer(single_obj) for single_obj in obj if create_tag_layer(single_obj) is not None]
        else:
            return create_tag_layer(obj)
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

type_handlers = {} # filled in by the modules that handle the obj.data types

def find_single_collider(objects):
    colliders = []
    for o in objects:
        if is_collider(o):
            colliders.append(o)
    if len(colliders) == 1 and not colliders[0].muproperties.separate:
        mat = colliders[0].matrix_local
        mat = mat - mat.Identity(4)
        sum = 0
        for i in range(4):
            for j in range(4):
                sum += mat[i][j]**2
        if sum < 1e-9:
            return colliders[0]
    return None

def make_obj_core(mu, obj, path, muobj):
    try:
        # ORIGINAL code - working animations (patch 2)
        if path:
            path += "/"
        path += muobj.transform.name
        mu.object_paths[path] = muobj
        muobj.tag_and_layer = make_tag_and_layer(obj)
        if is_collider(obj):
            mu.exported_objects.add(obj)
            muobj.collider = make_collider(mu, obj)
            return muobj
        elif type(obj.data) in type_handlers:
            mu.path = path  #needs to be reset as a type handler might modify it
            muobj = type_handlers[type(obj.data)](obj, muobj, mu)
            if not muobj:
                # the handler decided the object should not be exported
                return None
        mu.exported_objects.add(obj)
        col = find_single_collider(obj.children)
        if col:
            mu.exported_objects.add(col)
            muobj.collider = make_collider(mu, col)
        for o in obj.children:
            if o in mu.exported_objects:
                # the object has already been exported
                continue
            child = make_obj(mu, o, path)
            if child:
                muobj.children.append(child)
        return muobj
    except TypeError as e:
        if "unhashable type: 'list'" in str(e):
            print(f"Warning: {e}. Switching to alternative code.")
            # ALTERNATIVE code - handle damaged animations to export !!! (patch 2)
            def process_single_obj(single_obj, muobj):
                if path:
                    current_path = path + "/"
                else:
                    current_path = ""
                current_path += single_obj.name  # Changed from single_obj.transform.name to single_obj.name
                mu.object_paths[current_path] = muobj
                muobj.tag_and_layer = make_tag_and_layer(single_obj)
                if is_collider(single_obj):
                    mu.exported_objects.add(single_obj)
                    muobj.collider = make_collider(mu, single_obj)
                    return muobj
                elif type(single_obj.data) in type_handlers:
                    mu.path = current_path  # needs to be reset as a type handler might modify it
                    updated_muobj = type_handlers[type(single_obj.data)](single_obj, muobj, mu)
                    if not updated_muobj:
                        # the handler decided the object should not be exported
                        return None
                    muobj = updated_muobj
                mu.exported_objects.add(single_obj)
                col = find_single_collider(single_obj.children)
                if col:
                    mu.exported_objects.add(col)
                    muobj.collider = make_collider(mu, col)
                for o in single_obj.children:
                    if o in mu.exported_objects:
                        # the object has already been exported
                        continue
                    child = make_obj(mu, o, current_path)
                    if child:
                        muobj.children.append(child)
                return muobj

            if isinstance(obj, list):
                for single_obj in obj:
                    muobj = process_single_obj(single_obj, muobj)
            else:
                muobj = process_single_obj(obj, muobj)
            return muobj
            
def make_obj(mu, obj, path, extra=None):
    if obj in mu.exported_objects:
        # the object has already been "exported"
        return None
    muprops = obj.muproperties
    #check whether the object should be exported (eg, props should not be
    #exported as part of an IVA, and IVAs should not be exported as part
    #of a part (that sounds odd), volumes should not be exported as part
    # of anything
    if muprops.modelType in mu.special:
        mu.path = path  #needs to be reset as a type handler might modify it
        if mu.special[muprops.modelType](mu, obj, extra):
            return None
    muobj = MuObject()
    muobj.transform = make_transform (obj)
    return make_obj_core(mu, obj, path, muobj)

def calc_volumes(mu):
    for tag in mu.volumes:
        volume = mu.volumes[tag]
        for i, obj in enumerate(volume):
            volume[i] = model_volume(obj)
        mu.volumes[tag] = [sum(f) for f in zip(*volume)]

def add_internal(mu, obj, extra):
    mu.internals.append(obj)
    return True

def add_prop(mu, obj, extra):
    mu.props.append((mu.path, obj))
    return True

def add_model(mu, obj, extra):
    mu.models.append((mu.path, obj, extra))
    return True

def add_volume(mu, obj, extra):
    tag = obj.muproperties.tag
    if tag not in mu.volumes:
        mu.volumes[tag] = []
    mu.volumes[tag].append(obj)
    return True

special_modelTypes = {
    'NONE': {},
    'PART': {'INTERNAL':add_internal, 'VOLUME':add_volume, 'MODEL':add_model},
    'PROP': {'MODEL':add_model},
    'INTERNAL': {'PROP':add_prop, 'MODEL':add_model},
    'MODEL': {'VOLUME':add_volume},
    'STATIC': {},
    'UTILITY': {},
    'VOLUME': {},
}

def export_object(obj, filepath):
    animations = collect_animations(obj)
    anim_root = find_path_root(animations)
    mu = Mu()
    mu.exported_objects = set()
    mu.name = strip_nnn(obj.name)
    mu.object_paths = {}
    mu.materials = {}
    mu.textures = {}
    mu.nodes = []
    mu.props = []
    mu.models = []
    mu.volumes = {}
    mu.messages = []
    mu.internals = []
    mu.type = obj.muproperties.modelType
    if mu.type == 'NONE':
        mu.type = bpy.context.scene.musceneprops.modelType
    mu.CoMOffset = None
    mu.CoPOffset = None
    mu.CoLOffset = None
    mu.anim_root = anim_root
    if anim_root and "/" not in anim_root:
        mu.messages.append(({'WARNING'}, "suggest buffer empty between root object and animated objects"))
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
    mu.skin_volume, mu.ext_volume = model_volume(obj, mu.special)
    calc_volumes(mu)
    generate_cfg(mu, filepath)
    return mu

def enable_collections():
    collections = collect_collections(bpy.context.scene)
    for col in collections:
        col.hide_viewport = False
    return collections

def restore_collections(collections):
    for col in collections:
        col.hide_viewport = True
