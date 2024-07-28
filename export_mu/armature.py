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
from ..utils import strip_nnn, collect_armature_modifiers

from .export import make_obj_core
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


def export_bone(bone, mu, armature, bone_children, path, parent_tag_and_layer=None):
    if path:
        path += "/"
    path += bone.name
    mubone = MuObject()
    obj = bone_children.get(bone.name)
    armature.bone_paths[f'pose.bones["{bone.name}"]'] = path
    mubone.transform = bone_transform(bone, obj)
    
    if obj:
        make_obj_core(mu, obj, path, mubone)
    else:
        mubone.tag_and_layer = MuTagLayer()
        if parent_tag_and_layer:
            # inherent parent tag and layer
            mubone.tag_and_layer.tag = parent_tag_and_layer.tag
            mubone.tag_and_layer.layer = parent_tag_and_layer.layer
        else:
            mubone.tag_and_layer.tag = "Untagged"
            mubone.tag_and_layer.layer = 0
    
    mu.object_paths[path] = mubone
    
    for child in bone.children:
        muchild = export_bone(child, mu, armature, bone_children, path, mubone.tag_and_layer)
        mubone.children.append(muchild)
    
    return mubone

def find_bone_children(obj):
    bone_children = {}
    for child in obj.children:
        if child.parent_type == 'BONE':
            if child.parent_bone not in bone_children:
                bone_children[child.parent_bone] = []
            bone_children[child.parent_bone].append(child)
    return bone_children

def find_deform_children(obj):
    deform_children = []
    for child in obj.children:
        for mod in child.modifiers:
            if (type(mod) == bpy.types.ArmatureModifier
                and mod.object == obj):
                deform_children.append(child)
    return deform_children

def handle_armature(obj, muobj, mu):
    armature = obj.data
    bone_children = find_bone_children(obj)
    path = mu.path
    muobj.bone_paths = {}
    muobj.animated_bones = set()
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
