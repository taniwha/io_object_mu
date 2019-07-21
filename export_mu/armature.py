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

from ..mu import MuObject, MuTransform, MuTagLayer
from ..utils import strip_nnn

from .export import make_obj_core, exported_objects
from .mesh import create_skinned_mesh

def bone_transform(bone, obj):
    matrix = bone.matrix_local
    if bone.parent:
        matrix = bone.parent.matrix_local.inverted() @ matrix
    transform = MuTransform()
    transform.name = bone.name
    transform.localPosition = matrix.translation
    transform.localRotation = matrix.to_quaternion()
    transform.localScale = matrix.to_scale()
    return transform


def export_bone(bone, mu, armature, bone_children, path):
    if path:
        path += "/"
    path += bone.name
    mubone = MuObject()
    obj = bone_children.get(bone.name)
    armature.bone_paths[f'pose.bones["{bone.name}"]'] = path
    mubone.transform = bone_transform (bone, obj)
    if obj:
        make_obj_core(mu, obj, path, mubone)
    else:
        mubone.tag_and_layer = MuTagLayer()
        #FIXME inherit parent tag and layer
        mubone.tag_and_layer.tag = "Untagged"
        mubone.tag_and_layer.layer = 0
        mu.object_paths[path] = mubone
    for child in bone.children:
        muchild = export_bone(child, mu, armature, bone_children, path)
        mubone.children.append(muchild)
    return mubone

def find_bone_children(obj):
    bone_children = {}
    for child in obj.children:
        if child.parent_type == 'BONE':
            #FIXME(?) for now, only one direct child is suported
            bone_children[child.parent_bone] = child
    return bone_children

def find_deform_children(obj):
    deform_children = []
    for child in obj.children:
        for mod in child.modifiers:
            if (type(mod) == bpy.types.ArmatureModifier
                and mod.object == obj):
                deform_children.append(child)
    return deform_children

def find_bindpose_children(obj):
    bindpose_children = []
    for child in obj.children:
        print(child.name, type(child.data))
        if type(child.data) == bpy.types.Armature:
            if child.name[-9:] == ".bindPose":
                bindpose_children.append(child)
    return bindpose_children

def handle_armature(obj, muobj, mu):
    armature = obj.data
    bone_children = find_bone_children(obj)
    deform_children = find_deform_children(obj)
    exported_objects.update(deform_children)
    if len(deform_children) > 1:
        mu.messages.append(({'WARNING'}, "too many deform children, ignoring excess"))
        deform_children = deform_children[:1]
    bindpose_children = find_bindpose_children(obj)
    exported_objects.update(bindpose_children)
    if len(bindpose_children) > 1:
        mu.messages.append(({'WARNING'}, "too many bind-pose armatures, ignoring excess"))
        bindpose_children = bindpose_children[:1]
    bindposes = map(lambda o: o.data, bindpose_children)
    path = mu.path
    if deform_children:
        smr = create_skinned_mesh(deform_children[0], mu, armature, bindposes)
        muobj.skinned_mesh_renderer = smr
    muobj.bone_paths = {}
    muobj.path = path
    for bone in armature.bones:
        if bone.parent:
            #not a root bone
            continue
        mubone = export_bone(bone, mu, muobj, bone_children, path)
        muobj.children.append(mubone)
    return muobj

type_handlers = {
    bpy.types.Armature: handle_armature
}
