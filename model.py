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
import sys
import os

import bpy
from mathutils import Vector,Matrix,Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import PointerProperty, CollectionProperty

from .cfgnode import ConfigNode, ConfigNodeError
from .import_mu import import_mu

loaded_models_object = None
parts_object = None

def select_objects(obj):
    obj.select = True
    for o in obj.children:
        select_objects(o)

def hide_objects(obj):
    obj.hide = True
    for o in obj.children:
        hide_objects(o)

def show_objects(obj):
    obj.hide = False
    for o in obj.children:
        show_objects(o)

def copy_objects(obj):
    new_obj = obj.copy()
    bpy.context.scene.objects.link(new_obj)
    for o in obj.children:
        no = copy_objects(o)
        no.parent = new_obj
    return new_obj

def load_models(nodes):
    global loaded_models_object
    if not loaded_models_object:
        loaded_models_object = bpy.data.objects.new("loaded_models", None)
        bpy.context.scene.objects.link(loaded_models_object)
        loaded_models_object.hide = True
    objects = []
    for n in nodes:
        model = n.GetValue("model")
        position = Vector((0, 0, 0))
        rotation = Vector((0, 0, 0))
        scale = Vector((1, 1, 1))
        if n.HasValue("position"):
            position = parse_vector(n.GetValue("position"))
        if n.HasValue("rotation"):
            rotation = parse_vector(n.GetValue("rotation"))
        if n.HasValue("scale"):
            scale = parse_vector(n.GetValue("scale"))
        if model not in loaded_models:
            path = os.path.join(gamedata, model) + ".mu"
            m = import_mu(path, False)
            hide_objects(m)
            loaded_models[model] = m
            m.parent = loaded_models_object
        obj = copy_objects(loaded_models[model])
        obj.location = position
        # blender is right-handed, KSP is left-handed
        # FIXME: it might be better to convert the given euler rotation
        # to a quaternion (for consistency)
        obj.rotation_mode = 'XZY'
        obj.rotation_euler = -rotation
        obj.scale = scale
        objects.append(obj)
    if len(objects) > 1:
        obj = bpy.data.objects.new("something", None)
        bpy.context.scene.objects.link(obj)
        obj.hide = True
        for o in objects:
            o.parent = obj
    else:
        obj = objects[0]
    return obj

def loaded_models_scene():
    if "loaded_models" not in bpy.data.scenes:
        return bpy.data.scenes.new("loaded_models")
    return bpy.data.scenes["loaded_models"]

def group_objects(name, obj):
    def add_to_group(group, obj):
        group.objects.link (obj)
        for child in obj.children:
            add_to_group(group, child)
    group = bpy.data.groups.new(name)
    add_to_group(group, obj)
    return group

class Model:
    @classmethod
    def Preloaded(cls):
        preloaded = {}
        for g in bpy.data.groups:
            if g.name[:6] == "model:":
                url = g.name[6:]
                preloaded[url] = Model(None, url)
        return preloaded
    def __init__(self, path, url):
        groupname = "model:" + url
        if groupname in bpy.data.groups:
            group = bpy.data.groups["model:" + url]
        else:
            scene = loaded_models_scene()
            obj = import_mu(scene, path, False)
            obj.location = Vector((0, 0, 0))
            obj.rotation_quaternion = Quaternion((1,0,0,0))
            obj.scale = Vector((1,1,1))
            group = group_objects("model:" + url, obj)
        self.model = group
    def instantiate(self, name, loc, rot, scale):
        obj = bpy.data.objects.new(name, None)
        obj.dupli_type='GROUP'
        obj.dupli_group=self.model
        obj.location = loc
        obj.scale = scale
        if type(rot) == Vector:
            # blender is right-handed, KSP is left-handed
            # FIXME: it might be better to convert the given euler rotation
            # to a quaternion (for consistency)
            # this assumes the rot vector came straight from a ksp cfg file
            obj.rotation_mode = 'XZY'
            obj.rotation_euler = -rot
        else:
            obj.rotation_mode = 'QUATERNION'
            obj.rotation_quaternion = rot
        return obj
