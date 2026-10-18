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

from .export import make_obj_core, make_obj
from .mesh import create_skinned_mesh, handle_mesh

def is_bindpose_armature(obj):
    """Blender-only helper armature created on import — must not be written to .mu."""
    if not obj or type(obj.data) != bpy.types.Armature:
        return False
    name = strip_nnn(obj.name)
    if name.endswith(".bindPose") or ".bindPose." in name:
        return True
    # Import creates COPY_TRANSFORMS on every pose bone → control armature
    try:
        for pbone in obj.pose.bones:
            for c in pbone.constraints:
                if (c.type == 'COPY_TRANSFORMS' and c.target
                        and c.target != obj
                        and type(getattr(c.target, "data", None)) == bpy.types.Armature):
                    return True
    except Exception:
        pass
    return False

def bindpose_base_name(obj):
    name = strip_nnn(obj.name)
    if name.endswith(".bindPose"):
        return name[:-len(".bindPose")]
    return name

def bone_transform(bone, arm_obj):
    # Respect inherit flags: when scale is not inherited, use a parent matrix
    # with unit scale so the exported local scale matches pose evaluation.
    matrix = bone.matrix_local.copy()
    if bone.parent:
        parent_mat = bone.parent.matrix_local.copy()
        inherit_scale = getattr(bone, "inherit_scale", 'FULL')
        if inherit_scale == 'NONE':
            # Remove parent scale contribution
            loc, rot, _sca = parent_mat.decompose()
            parent_mat = rot.to_matrix().to_4x4()
            parent_mat.translation = loc
        matrix = parent_mat.inverted() @ matrix
    transform = MuTransform()
    transform.name = bone.name
    transform.localPosition = matrix.translation
    transform.localRotation = matrix.to_quaternion()
    # Edit-bone matrices are unit-scale; Unity localScale lives on pose bones
    # (import uses Blender scale = (ux, uz, uy)).
    transform.localScale = matrix.to_scale()
    if arm_obj is not None and bone.name in arm_obj.pose.bones:
        ps = arm_obj.pose.bones[bone.name].scale
        transform.localScale = Vector((ps[0], ps[2], ps[1]))
    return transform


def export_bone(bone, mu, muobj, bone_children, path, arm_obj,
                parent_tag_and_layer=None):
    # path is the parent Mu path; make_obj_core appends transform.name itself.
    parent_path = path
    if path:
        path = path + "/" + bone.name
    else:
        path = bone.name
    mubone = MuObject()
    objs = bone_children.get(bone.name) or []
    if not isinstance(objs, (list, tuple)):
        objs = [objs]
    first = objs[0] if objs else None
    muobj.bone_paths[f'pose.bones["{bone.name}"]'] = path
    mubone.transform = bone_transform(bone, arm_obj)

    if first:
        # Merge first bone-child into the bone GO (Unity-style); extra children
        # become MuObjects under the bone — never pass a list to make_obj_core.
        make_obj_core(mu, first, parent_path, mubone)
        for extra in objs[1:]:
            child = make_obj(mu, extra, path)
            if child:
                mubone.children.append(child)
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
        muchild = export_bone(
            child, mu, muobj, bone_children, path, arm_obj,
            mubone.tag_and_layer)
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

def handle_bindpose(obj, muobj, mu):
    """Export bindPose as the original SMR owner node (no second armature)."""
    muobj.transform.name = bindpose_base_name(obj)
    # Restore Unity SMR local transform stored at import (often -90° X)
    try:
        if "mu_smr_rotation" in obj:
            muobj.transform.localPosition = Vector(obj["mu_smr_location"])
            muobj.transform.localRotation = Quaternion(obj["mu_smr_rotation"])
            muobj.transform.localScale = Vector(obj["mu_smr_scale"])
    except Exception:
        pass
    # Prefer skinned mesh child (*.skin); fall back to any mesh with ArmatureModifier
    skins = []
    others = []
    for child in obj.children:
        mods = collect_armature_modifiers(child) if child.data and type(child.data) == bpy.types.Mesh else []
        if mods:
            skins.append(child)
        else:
            others.append(child)
    if skins:
        # SMR lives on this node (Unity/KSP style); mark skins exported so
        # make_obj_core does not recurse into them as separate objects.
        handle_mesh(skins[0], muobj, mu)
        for s in skins:
            mu.exported_objects.add(s)
        # Extra skins become child MuObjects
        for s in skins[1:]:
            child = make_obj(mu, s, mu.path)
            if child:
                muobj.children.append(child)
    # Non-skin children are left for make_obj_core's normal recursion
    return muobj

def handle_armature(obj, muobj, mu):
    if is_bindpose_armature(obj):
        return handle_bindpose(obj, muobj, mu)

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
        mubone = export_bone(bone, mu, muobj, bone_children, path, obj)
        muobj.children.append(mubone)
    # Skin meshes parented under a sibling bindPose are exported when that
    # bindPose is visited; deform children directly under control are rare.
    for child in find_deform_children(obj):
        if child in mu.exported_objects:
            continue
        muchild = make_obj(mu, child, path)
        if muchild:
            muobj.children.append(muchild)
    return muobj

type_handlers = {
    bpy.types.Armature: handle_armature
}
