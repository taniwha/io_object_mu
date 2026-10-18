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
    bone.use_envelope_multiply = False
    bone.use_deform = True
    # Honor inherit flags stored on the MuObject (set on re-import from Blender
    # custom props) — .mu itself does not store these.
    inherit_rot = getattr(bone_obj, "use_inherit_rotation", True)
    inherit_scale = getattr(bone_obj, "inherit_scale", 'FULL')
    if hasattr(bone, "use_inherit_rotation"):
        bone.use_inherit_rotation = bool(inherit_rot)
    if hasattr(bone, "inherit_scale"):
        bone.inherit_scale = inherit_scale if inherit_scale in {
            'FULL', 'FIX_SHEAR', 'ALIGNED', 'AVERAGE', 'NONE'} else 'FULL'
    bone.use_local_location = False
    if hasattr(bone, "use_relative_parent"):
        bone.use_relative_parent = False
    if hasattr(bone, "use_cyclic_offset"):
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

def _lookup_bone(mu, bname):
    """Resolve a SMR bone name to a MuObject (path-aware fallback)."""
    bone = mu.objects.get(bname)
    if bone:
        return bone
    # Fallback: unique path suffix match (handles rare name collisions)
    matches = [o for p, o in mu.object_paths.items()
               if p.rsplit("/", 1)[-1] == bname]
    if len(matches) == 1:
        return matches[0]
    return None

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
    col = getattr(mu, "collection", None) or col
    skin.bindPose_obj = create_data_object(col, name + ".bindPose",
                                           skin.bindPose, None)
    ctx.view_layer.objects.active = skin.bindPose_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    resolved = []
    for i, bname in enumerate(bone_names):
        bone = _lookup_bone(mu, bname)
        if bone is None:
            print(f"WARNING: bindPose bone '{bname}' not in hierarchy "
                  f"(skin={name}); creating empty bone")
            # Synthetic minimal MuObject-like stub for edit bone creation
            class _Stub:
                pass
            stub = _Stub()
            stub.transform = type("T", (), {
                "name": bname,
                "localPosition": Vector((0, 0, 0)),
                "localRotation": Quaternion((1, 0, 0, 0)),
                "localScale": Vector((1, 1, 1)),
            })()
            bone = stub
        if i < len(skin.mesh.bindPoses):
            m = skin.mesh.bindPoses[i].inverted()
        else:
            m = Matrix.Identity(4)
        pb = create_bone(bone, skin.bindPose.edit_bones)
        pb.matrix = m
        if hasattr(bone, "poseBone") or not isinstance(bone, type):
            try:
                bone.poseBone = pb.name
            except Exception:
                pass
        resolved.append((bname, bone))
    bpy.ops.object.mode_set(mode='OBJECT')

    for bname, bone in resolved:
        if bname not in skin.bindPose_obj.pose.bones:
            continue
        posebone = skin.bindPose_obj.pose.bones[bname]
        owner = getattr(bone, "owner", None)
        arm_obj = getattr(owner, "armature_obj", None) if owner else None
        # Also try bone.armature (set by create_armature)
        if not isinstance(arm_obj, bpy.types.Object):
            arm = getattr(bone, "armature", None)
            arm_obj = getattr(arm, "armature_obj", None) if arm else None
        if not isinstance(arm_obj, bpy.types.Object):
            print(f"WARNING: no control armature_obj for bone '{bname}' "
                  f"(owner={getattr(getattr(owner, 'transform', None), 'name', None)}); "
                  f"skipping COPY_TRANSFORMS")
            continue
        constraint = posebone.constraints.new('COPY_TRANSFORMS')
        constraint.target = arm_obj
        constraint.subtarget = bname
    # don't clutter the main collection if importing to a different collection
    try:
        ctx.layer_collection.collection.objects.unlink(skin.bindPose_obj)
    except Exception:
        pass
    #however, do need to link the bindPose armature to the import collection
    if skin.bindPose_obj.name not in mu.collection.objects:
        mu.collection.objects.link(skin.bindPose_obj)

def find_bones(mu, skins, siblings, merge_roots=False):
    siblings = set(siblings)
    skins = set(skins)
    bones = set()
    for skin in skins:
        bone_names = skin.skinned_mesh_renderer.bones
        for bname in bone_names:
            bone = _lookup_bone(mu, bname)
            if bone:
                bones.add(bone)
            else:
                print(f"WARNING: SMR bone '{bname}' not found in hierarchy "
                      f"(skin={skin.transform.name})")
    roots = set()
    for b in bones:
        # File-root bones have parent=None — they MUST count as roots.
        # Previously only "parent not in bones" was used, so absorbing the
        # file root into `bones` (SMR lists Drill_Fixed etc.) left no top
        # root; climb stopped on a mid-joint (joint37) and the real root
        # was then bone-parented UNDER that joint's armature (TriBitDrill).
        if not b.parent or b.parent not in bones:
            roots.add(b)
    #print(list(map(lambda b: b.transform.name if b.transform else 'None', bones)))
    #print(list(map(lambda b: b.transform.name if b.transform else 'None', roots)))
    prev_roots = set()
    while len(roots) > 1 and roots ^ prev_roots:
        prev_roots = set(roots)
        for b in list(prev_roots):
            if not b:
                continue
            if not merge_roots and (b in siblings or (b.parent and b.parent in skins)):
                continue
            # Never climb away from a true file root
            if not b.parent:
                continue
            roots.discard(b)
            bones.add(b.parent)
            roots.add(b.parent)
    parents = set()
    for b in roots:
        if not b:
            continue
        if b.parent:
            parents.add(b.parent)
        else:
            # Root-of-file bone owns its own armature
            parents.add(b)
    # Prefer a single armature owner when merge_roots collapsed the tree
    if merge_roots and len(parents) > 1:
        # Climb parents to a common ancestor when possible
        common = None
        for p in parents:
            chain = []
            n = p
            while n:
                chain.append(n)
                n = n.parent
            if common is None:
                common = chain
            else:
                common_set = set(common)
                common = [n for n in chain if n in common_set]
        if common:
            parents = {common[0]}

    def _is_ancestor(ancestor, node):
        n = getattr(node, "parent", None)
        while n:
            if n is ancestor:
                return True
            n = getattr(n, "parent", None)
        return False

    #print(list(map(lambda b: b.transform.name if b.transform else 'None', parents)))
    for b in bones:
        if not b:
            continue
        p = b.parent
        while p and p not in parents:
            p = p.parent
        if p is None and parents:
            # Assign to a single parent if only one armature owner
            if len(parents) == 1:
                p = next(iter(parents))
        # Never make an ancestor of the owner into a bone of that owner
        # (inverts the Blender hierarchy: Drill_Fixed under joint36).
        if p is not None and _is_ancestor(b, p):
            # b is above the armature owner — not a pose bone
            b.owner = None
            continue
        b.owner = p
        if p and b is not p:
            if not hasattr(p, "armature_bones"):
                p.armature_bones = set()
            if b not in p.armature_bones:
                p.armature_bones.add(b)
            # Never assign armature_obj = MuObject; create_armature sets the
            # real Blender Object later.

    return bones, roots, parents

def make_matrix(transform):
    mat = rotate(transform.localRotation)
    mat = translate(transform.localPosition) @ mat
    return mat

def create_armature(mu, armobj, roots):
    armobj.matrix = make_matrix(armobj.transform)

    name = armobj.transform.name
    # Keep Blender Armature datablock on a dedicated attr so bone.armature
    # (MuObject owner link) can never overwrite it.
    arm_data = bpy.data.armatures.new(name)
    arm_data.show_axes = True
    armobj.armature_data = arm_data
    armobj.armature = arm_data  # legacy alias used elsewhere
    ctx = bpy.context
    # Prefer the import collection — layer_collection can be None/invalid
    # after test harness collection wipes.
    col = getattr(mu, "collection", None)
    if col is None:
        lc = getattr(ctx, "layer_collection", None)
        col = getattr(lc, "collection", None) if lc else None
    if col is None:
        col = ctx.scene.collection
    save_active = ctx.view_layer.objects.active
    armobj.armature_obj = create_data_object(col, name, arm_data,
                                             armobj.transform)

    ctx.view_layer.objects.active = armobj.armature_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    # Owner must not be treated as one of its own bones (would clobber
    # armobj.armature = Blender Armature with armobj itself).
    bone_set = {b for b in armobj.armature_bones if b is not armobj}
    armobj.armature_bones = bone_set

    def _bone_rest_matrix(b):
        """Local matrix including intermediate non-bone Unity parents (e.g. SMR -90°)."""
        mat = make_matrix(b.transform)
        p = b.parent
        while p is not None and p is not armobj and p not in bone_set:
            mat = make_matrix(p.transform) @ mat
            p = p.parent
        return mat

    for b in bone_set:
        b.matrix = _bone_rest_matrix(b)
        # Pose-space correction vs Unity local; identity keeps location
        # round-trip as (import: loc-lloc) / (export: loc+lloc).
        b.relRotation = Quaternion((1, 0, 0, 0))
        b.armature = armobj
        b.bone = create_bone(b, arm_data.edit_bones)
    rootBones = set()
    for b in bone_set:
        if b.parent in bone_set:
            b.bone.parent = b.parent.bone
        else:
            rootBones.add(b)
        b.force_import = False
        for c in b.children:
            if c not in bone_set:
                b.force_import = True
    process_armature(armobj, rootBones)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Edit bones cannot store Unity localScale — put it on pose bones.
    # Channel order matches animation property_map (Unity Y↔Z ↔ Blender).
    # Critical for TriBitDrill: DrillFixed=10, drill_root=0.01 (net 0.1).
    for b in bone_set:
        bname = b.bone if isinstance(b.bone, str) else getattr(b.bone, "name", None)
        if not bname:
            continue
        pb = armobj.armature_obj.pose.bones.get(bname)
        if not pb:
            continue
        ls = b.transform.localScale
        pb.scale = Vector((ls[0], ls[2], ls[1]))

    # don't clutter the main collection if importing to a different collection
    try:
        ctx.layer_collection.collection.objects.unlink(armobj.armature_obj)
    except Exception:
        pass
    ctx.view_layer.objects.active = save_active

    return armobj.armature_obj

def process_skins(mu, skins, siblings, merge_roots=False):
    bones, roots, parents = find_bones(mu, skins, siblings, merge_roots=merge_roots)
    for armobj in parents:
        if not hasattr(armobj, "armature_bones") or not armobj.armature_bones:
            continue
        #print(armobj.transform.name,
        #      list(map(lambda b: b.transform.name, armobj.armature_bones)))
        create_armature(mu, armobj, roots)

def is_armature(obj):
    # In Unity, it seems that an object with a SkinnedMeshRenderer is the
    # armature, and bones can be children of the SMR object, or even siblings
    if hasattr(obj, "skinned_mesh_renderer"):
        if obj.skinned_mesh_renderer.bones:
            return True
    return False

def force_armature_hierarchy(mu, muobj):
    """Build a single armature from the whole hierarchy (force_armature UI flag)."""
    if hasattr(muobj, "armature_obj"):
        return
    bones = set()
    def collect(o):
        for c in o.children:
            bones.add(c)
            collect(c)
    collect(muobj)
    if not bones:
        return
    muobj.armature_bones = bones
    for b in bones:
        b.owner = muobj
    create_armature(mu, muobj, {b for b in bones if b.parent == muobj or b.parent not in bones})
