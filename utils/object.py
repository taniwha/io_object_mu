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

def set_transform(obj, transform):
    obj.rotation_mode = 'QUATERNION'
    if transform:
        obj.location = Vector(transform.localPosition)
        obj.rotation_quaternion = Quaternion(transform.localRotation)
        obj.scale = Vector(transform.localScale)
    else:
        obj.location = Vector((0, 0, 0))
        obj.rotation_quaternion = Quaternion((1,0,0,0))
        obj.scale = Vector((1,1,1))

def create_data_object(collection, name, data, transform):
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    set_transform(obj, transform)
    return obj

#FIXME horible hack to work around blender 2.8 not (yet) allowing control
# over render/preview when converting an object to a mesh
def collect_modifiers(obj):
    modifiers = []
    for mod in obj.modifiers:
        if mod.show_viewport and not mod.show_render:
            modifiers.append(mod)
    return modifiers

def collect_armature_modifiers(obj):
    modifiers = []
    for mod in obj.modifiers:
        if type(mod) == bpy.types.ArmatureModifier:
            modifiers.append(mod)
    return modifiers

def collect_collections(scene):
    def recurse(col, collist):
        if (col.hide_viewport and not col.hide_render):
            collist.append(col)
        for c in col.children:
            recurse(c, collist)
    collections = []
    recurse(scene.collection, collections)
    return collections

def collect_objects(name, obj):
    def add_to_collection(collection, obj):
        collection.objects.link (obj)
        for child in obj.children:
            add_to_collection(collection, child)
    collection = bpy.data.collections.new(name)
    add_to_collection(collection, obj)
    return collection

def collect_hierarchy_objects(root):
    def collect(objects, obj):
        objects.extend(obj.children)
        for child in obj.children:
            collect(objects, child)
    objects = [root]
    collect(objects, root)
    return objects
