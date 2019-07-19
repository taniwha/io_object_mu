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
from mathutils import Vector, Quaternion, Matrix
from ..utils import create_data_object

BONE_LENGTH = 0.1
#matrix for converting between LHS and RHS (works either direction)
Matrix_YZ = Matrix(((1,0,0,0),
                    (0,0,1,0),
                    (0,1,0,0),
                    (0,0,0,1)))

def create_vertex_groups(obj, bones, weights):
    mesh = obj.data
    for bone in bones:
        obj.vertex_groups.new(name=bone)
    for vind, weight in enumerate(weights):
        for i in range(4):
            bind, bweight = weight.indices[i], weight.weights[i]
            if bweight != 0:
                obj.vertex_groups[bind].add((vind,), bweight, 'ADD')

def create_armature_modifier(obj, armobj):
    mod = obj.modifiers.new(name='Armature', type='ARMATURE')
    mod.use_apply_on_spline = False
    mod.use_bone_envelopes = False
    mod.use_deform_preserve_volume = False # silly Unity :P
    mod.use_multi_modifier = False
    mod.use_vertex_groups = True
    mod.object = armobj.armature_obj

def create_bone(bone_obj, edit_bones):
    xform = bone_obj.transform
    bone_obj.bone = bone = edit_bones.new(xform.name)
    # actual positions and orientations will be sorted out when building
    # the hierarchy
    bone.head = Vector((0, 0, 0))
    bone.tail = bone.head + Vector((0, BONE_LENGTH, 0))
    bone.use_connect = False
    bone.use_inherit_rotation = True
    bone.use_envelope_multiply = False
    bone.use_deform = True
    bone.use_inherit_scale = True
    bone.use_local_location = False
    bone.use_relative_parent = False
    bone.use_cyclic_offset = False
    return bone

def process_armature(armobj):
    def process_bone(obj, position, rotation):
        xform = obj.transform
        obj.bone.head = rotation @ Vector(xform.localPosition) + position
        rot = Quaternion(xform.localRotation)
        lrot = rotation @ rot
        y = BONE_LENGTH
        obj.bone.tail = obj.bone.head + lrot @ Vector((0, y, 0))
        obj.bone.align_roll(lrot @ Vector((0, 0, 1)))
        for child in obj.children:
            if hasattr(child, "armature") and child.armature == armobj:
                process_bone(child, obj.bone.head, lrot)
        # must not keep references to bones when the armature leaves edit mode,
        # so keep the bone's name instead (which is what's needed for bone
        # parenting anway)
        obj.bone = obj.bone.name

    pos = Vector((0, 0, 0))
    rot = Quaternion((1, 0, 0, 0))
    #the armature object has no bone
    for child in armobj.children:
        if hasattr(child, "bone"):
            process_bone(child, pos, rot)

def find_bones(armobj):
    bone_names = set()
    multi_skin_reported = False
    for child in armobj.children:
        if hasattr(child, "skinned_mesh_renderer"):
            if bone_names and not multi_skin_reported:
                multi_skin_reported = True
                armobj.mu.messages.append(({'WARNING'}, f"Multiple skinned meshes on {obj.name}, things may go pear-shaped"))
            bone_names |= set(child.skinned_mesh_renderer.bones)
            for i, bname in enumerate(child.skinned_mesh_renderer.bones):
                bone = armobj.mu.objects[bname]
                bp = child.skinned_mesh_renderer.mesh.bindPoses[i]
                bp = Matrix((bp[0:4], bp[4:8], bp[8:12], bp[12:16]))
                bone.bindPose = Matrix_YZ @ bp @ Matrix_YZ
    bones = set()
    for bname in bone_names:
        bones.add(armobj.mu.objects[bname])

    prev_bones = set()
    while bones - prev_bones:
        prev_bones = bones
        bones = set()
        for b in prev_bones:
            bones.add(b)
            while b.parent != armobj:
                b = b.parent
                bones.add(b)
    #print(list(map(lambda b: b.transform.name, bones)))

    return bones

def create_armature(armobj):
    name = armobj.transform.name
    armobj.armature = bpy.data.armatures.new(name)
    armobj.armature.show_axes = True
    armobj.armature_obj = create_data_object(name, armobj.armature,
                                             armobj.transform)
    ctx = bpy.context
    ctx.layer_collection.collection.objects.link(armobj.armature_obj)
    #need to set the active object so edit mode can be entered
    ctx.view_layer.objects.active = armobj.armature_obj

    bones = find_bones(armobj)

    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    for b in bones:
        b.armature = armobj
        create_bone(b, armobj.armature.edit_bones)
    for b in bones:
        if hasattr(b.parent, "bone"):
            b.bone.parent = b.parent.bone
    process_armature(armobj)

    bpy.ops.object.mode_set(mode='OBJECT')
    return armobj.armature_obj

def is_armature(obj):
    for comp in ["shared_mesh", "renderer", "skinned_mesh_renderer",
                 "collider", "camera", "light"]:
        if hasattr(obj, comp):
            return False
    sm = []
    for child in obj.children:
        if hasattr(child, "skinned_mesh_renderer"):
            if child.skinned_mesh_renderer.bones:
                return True
    return False
