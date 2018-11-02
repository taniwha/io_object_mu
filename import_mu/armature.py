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

BONE_LENGTH = 0.1

def create_vertex_groups(obj, bones, weights):
    mesh = obj.data
    for bone in bones:
        obj.vertex_groups.new(name=bone)
    for vind, weight in enumerate(weights):
        for i in range(4):
            bind, bweight = weight.indices[i], weight.weights[i]
            if bweight != 0:
                obj.vertex_groups[bind].add((vind,), bweight, 'ADD')

def create_armature_modifier(obj, mu):
    mod = obj.modifiers.new(name='Armature', type='ARMATURE')
    mod.use_apply_on_spline = False
    mod.use_bone_envelopes = False
    mod.use_deform_preserve_volume = False # silly Unity :P
    mod.use_multi_modifier = False
    mod.use_vertex_groups = True
    mod.object = mu.armature_obj

def create_bone(bone_obj, edit_bones):
    xform = bone_obj.transform
    bone_obj.bone = bone = edit_bones.new(xform.name)
    # actual positions and orientations will be sorted out when building
    # the hierarchy
    bone.head = Vector((0, 0, 0))
    bone.tail = bone.head + Vector((0, BONE_LENGTH, 0))
    bone.use_connect = False
    bone.use_inherit_rotation = True
    bone.use_inherit_scale = True
    bone.use_local_location = True
    bone.use_relative_parent = False
    return bone

def process_armature(mu):
    def process_bone(mu, obj, position, rotation):
        xform = obj.transform
        obj.bone.head = rotation @ Vector(xform.localPosition) + position
        rot = Quaternion(xform.localRotation)
        lrot = rotation @ rot
        y = BONE_LENGTH
        obj.bone.tail = obj.bone.head + lrot @ Vector((0, y, 0))
        obj.bone.align_roll(lrot @ Vector((0, 0, 1)))
        for child in obj.children:
            process_bone(mu, child, obj.bone.head, lrot)
        # must not keep references to bones when the armature leaves edit mode,
        # so keep the bone's name instead (which is what's needed for bone
        # parenting anway)
        obj.bone = obj.bone.name

    pos = Vector((0, 0, 0))
    rot = Quaternion((1, 0, 0, 0))
    #the root object has no bone
    for child in mu.obj.children:
        process_bone(mu, child, pos, rot)

def create_armature(mu):
    def create_bone_hierarchy(mu, obj, parent):
        bone = create_bone(obj, mu.armature.edit_bones)
        bone.parent = parent
        for child in obj.children:
            create_bone_hierarchy(mu, child, bone)

    name = mu.obj.transform.name
    mu.armature = bpy.data.armatures.new(name)
    mu.armature.show_axes = True
    from . import create_data_object #FIXME circular reference
    mu.armature_obj = create_data_object(name, mu.armature, mu.obj.transform)
    ctx = bpy.context
    ctx.layer_collection.collection.objects.link(mu.armature_obj)
    #need to set the active object so edit mode can be entered
    ctx.view_layer.objects.active = mu.armature_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)

    # the armature itself is the root object
    #FIXME any properties on the root object are lost, however, the root
    #object is supposed to be an empty, so it may not matter
    for child in mu.obj.children:
        create_bone_hierarchy (mu, child, None)

    process_armature(mu)
    bpy.ops.object.mode_set(mode='OBJECT')

def needs_armature(mu):
    def has_skinned_mesh(obj):
        if hasattr(obj, "skinned_mesh_renderer"):
            return True
        for child in obj.children:
            if has_skinned_mesh(child):
                return True
        return False
    return has_skinned_mesh(mu.obj)
