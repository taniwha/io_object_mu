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
from ..utils import create_data_object, translate, scale, rotate

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

def create_armature_modifier(obj, name, armature):
    mod = obj.modifiers.new(name=name, type='ARMATURE')
    mod.use_apply_on_spline = False
    mod.use_bone_envelopes = False
    mod.use_deform_preserve_volume = False # silly Unity :P
    mod.use_multi_modifier = False
    mod.use_vertex_groups = True
    mod.object = armature

def parent_to_bone(child, armature, bone):
    child.parent = armature
    child.parent_type = 'BONE'
    child.parent_bone = bone
    child.matrix_parent_inverse[1][3] = -BONE_LENGTH

def create_bone(bone_obj, edit_bones):
    xform = bone_obj.transform
    bone = edit_bones.new(xform.name)
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

def process_armature(armobj, rootBones):
    def process_bone(obj, mat):
        mat = mat @ obj.matrix
        obj.bone.matrix = mat
        y = BONE_LENGTH
        obj.bone.tail = mat @ Vector((0, y, 0))
        for child in obj.children:
            if hasattr(child, "armature") and child.armature == armobj:
                process_bone(child, mat)
        # must not keep references to bones when the armature leaves edit mode,
        # so keep the bone's name instead (which is what's needed for bone
        # parenting anway)
        obj.bone = obj.bone.name

    mat = Matrix.Identity(4)
    #the armature object has no bone
    for rootBone in rootBones:
        process_bone(rootBone, mat)

def create_bindPose(mu, muobj, skin):
    bone_names = skin.bones
    for i in range(len(skin.mesh.bindPoses)):
        bp = skin.mesh.bindPoses[i]
        bp = Matrix((bp[0:4], bp[4:8], bp[8:12], bp[12:16]))
        skin.mesh.bindPoses[i] = Matrix_YZ @ bp @ Matrix_YZ
    ctx = bpy.context
    col = ctx.layer_collection.collection
    name = muobj.transform.name
    skin.bindPose = bpy.data.armatures.new(name + ".bindPose")
    skin.bindPose.show_axes = True
    skin.bindPose_obj = create_data_object(col, name + ".bindPose",
                                           skin.bindPose, None)
    ctx.view_layer.objects.active = skin.bindPose_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    for i, bname in enumerate(bone_names):
        bone = mu.objects[bname]
        m = skin.mesh.bindPoses[i].inverted()
        pb = create_bone (bone, skin.bindPose.edit_bones)
        pb.matrix = m
        bone.poseBone = pb.name
    bpy.ops.object.mode_set(mode='OBJECT')

    for bname in bone_names:
        bone = mu.objects[bname]
        posebone = skin.bindPose_obj.pose.bones[bname]
        constraint = posebone.constraints.new('COPY_TRANSFORMS')
        constraint.target = bone.owner.armature_obj
        constraint.subtarget = bname
    # don't clutter the main collection if importing to a different collection
    ctx.layer_collection.collection.objects.unlink(skin.bindPose_obj)
    #however, do need to link the bindPose armature to the import collection
    mu.collection.objects.link(skin.bindPose_obj)

def find_bones(mu, skins, siblings):
    siblings = set(siblings)
    bones = set()
    for skin in skins:
        bone_names = skin.skinned_mesh_renderer.bones
        for bname in bone_names:
            bones.add(mu.objects[bname])

    roots = set()
    for b in bones:
        if b.parent not in bones:
            roots.add(b)
    prev_roots = set()
    while len(roots) > 1 and roots ^ prev_roots:
        prev_roots = set(roots)
        for b in prev_roots:
            if b in siblings:
                continue
            roots.remove(b)
            bones.add(b.parent)
            roots.add(b.parent)
    parents = set()
    for b in roots:
        parents.add(b.parent)
    for b in bones:
        p = b.parent
        while p not in parents:
            p = p.parent
        b.owner = p
        if not hasattr(p, "armature_bones"):
            p.armature_bones = set()
        p.armature_bones.add(b)
    return bones, roots, parents

def make_matrix(transform):
    mat = rotate(transform.localRotation)
    mat = translate(transform.localPosition) @ mat
    return mat

def create_armature(mu, armobj, roots):
    armobj.matrix = make_matrix(armobj.transform)

    name = armobj.transform.name
    armobj.armature = bpy.data.armatures.new(name)
    armobj.armature.show_axes = True
    ctx = bpy.context
    col = ctx.layer_collection.collection
    save_active = ctx.view_layer.objects.active
    armobj.armature_obj = create_data_object(col, name, armobj.armature,
                                             armobj.transform)

    ctx.view_layer.objects.active = armobj.armature_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    for b in armobj.armature_bones:
        b.matrix = make_matrix(b.transform)
        b.relRotation = Quaternion((1, 0, 0, 0))
        b.armature = armobj
        b.bone = create_bone(b, armobj.armature.edit_bones)
    rootBones = set()
    for b in armobj.armature_bones:
        if b.parent in armobj.armature_bones:
            b.bone.parent = b.parent.bone
        else:
            rootBones.add(b)
        b.force_import = False
        for c in b.children:
            if c not in armobj.armature_bones:
                b.force_import = True
    process_armature(armobj, rootBones)
    bpy.ops.object.mode_set(mode='OBJECT')

    # don't clutter the main collection if importing to a different collection
    ctx.layer_collection.collection.objects.unlink(armobj.armature_obj)
    ctx.view_layer.objects.active = save_active

    return armobj.armature_obj

def process_skins(mu, skins, siblings):
    bones, roots, parents = find_bones(mu, skins, siblings)
    for armobj in parents:
        print(armobj.transform.name,
              list(map(lambda b: b.transform.name, armobj.armature_bones)))
        create_armature(mu, armobj, roots)

def is_armature(obj):
    # In Unity, it seems that an object with a SkinnedMeshRenderer is the
    # armature, and bones can be children of the SMR object, or even siblings
    if hasattr(obj, "skinned_mesh_renderer"):
        if obj.skinned_mesh_renderer.bones:
            return True
    return False
