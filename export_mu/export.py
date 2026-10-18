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
from ..utils import strip_nnn, collect_collections, unity_export_name

from .animation import (
    collect_animations, collect_orphan_stub_animations,
    find_path_root, make_animations, group_animations_by_host,
)
from .collider import make_collider
from .cfgfile import generate_cfg
from .export_util import is_collider
from .volume import model_volume

def make_transform(obj):
    transform = MuTransform()
    transform.name = unity_export_name(obj)
    # Prefer Unity locals stored before bindPose SMR-space bake (colliders)
    try:
        if "mu_unity_rotation" in obj:
            transform.localPosition = Vector(obj["mu_unity_location"])
            transform.localRotation = Quaternion(obj["mu_unity_rotation"])
            transform.localScale = Vector(obj["mu_unity_scale"])
            return transform
    except Exception:
        pass
    transform.localPosition = Vector(obj.location)
    if obj.rotation_mode != 'QUATERNION':
      transform.localRotation = obj.rotation_euler.to_quaternion()
    else:
      transform.localRotation = Quaternion(obj.rotation_quaternion)
    transform.localScale = Vector(obj.scale)
    return transform

def make_tag_and_layer(obj):
    tl = MuTagLayer()
    tl.tag = obj.muproperties.tag
    tl.layer = obj.muproperties.layer
    return tl

type_handlers = {} # filled in by the modules that handle the obj.data types

def _object_has_animation(obj):
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return False
    if ad.action:
        return True
    return any(getattr(t, "strips", None) for t in ad.nla_tracks)

def find_single_collider(objects):
    colliders = []
    for o in objects:
        if is_collider(o):
            colliders.append(o)
    if len(colliders) == 1 and not colliders[0].muproperties.separate:
        col = colliders[0]
        # Never inline a collider that still owns a hierarchy (common in
        # Serenity parts: BoxCollider on an intermediate GO with meshes under
        # it). Inlining would mark it exported and drop all descendants.
        if col.children:
            return None
        # SP-10C etc.: separate Unity GOs named "collider 1" carry Mesh +
        # MeshCollider and have their own transform animation. Inlining them
        # drops object_paths entries and breaks clip export.
        if _object_has_animation(col):
            return None
        if col.type == 'MESH' and col.data and len(col.data.vertices) > 0:
            return None
        mat = col.matrix_local
        mat = mat - mat.Identity(4)
        sum = 0
        for i in range(4):
            for j in range(4):
                sum += mat[i][j]**2
        if sum < 1e-9:
            return col
    return None

def make_obj_core(mu, obj, path, muobj):
    if path:
        path += "/"
    # Disambiguate sibling Unity names after strip_nnn (Omni1∧ + Omni1∧collider
    # used to both become Omni1 and overwrite object_paths / drop content —
    # bluedog_Surveyor_Omnis).
    leaf = muobj.transform.name or "object"
    candidate = path + leaf
    if candidate in mu.object_paths:
        n = 1
        while True:
            alt = "%s.%03d" % (leaf, n)
            if path + alt not in mu.object_paths:
                leaf = alt
                muobj.transform.name = leaf
                break
            n += 1
            if n > 999:
                break
    path = path + leaf
    muobj.path = path
    mu.object_paths[path] = muobj
    # Unique Blender name → MuObject (duplicate Unity sibling names collide in
    # object_paths; material glow hosts need this map — RCSBlock×4 thrusters).
    if not hasattr(mu, "blender_to_mu"):
        mu.blender_to_mu = {}
    try:
        mu.blender_to_mu[obj.name] = muobj
    except Exception:
        pass
    muobj.tag_and_layer = make_tag_and_layer(obj)
    # Collider on a GO that also has children/mesh must keep exporting the
    # hierarchy (Serenity GoExOb etc.). Pure collider leaf → early out.
    if is_collider(obj):
        muobj.collider = make_collider(mu, obj)
        has_exportable_kids = any(
            (not is_collider(c) or c.children)
            and ".preview" not in c.name
            and ".fx_preview" not in c.name
            and ".fx_emitter" not in c.name
            and not c.get("mu_fx_preview")
            for c in obj.children
        )
        if not has_exportable_kids and type(obj.data) not in type_handlers:
            mu.exported_objects.add(obj)
            # Still allow particles on a pure-collider leaf
            from .empty import _particles_from_id_prop
            particles = _particles_from_id_prop(obj)
            if particles is not None:
                muobj.particles = particles
            return muobj
    if type(obj.data) in type_handlers:
        mu.path = path  #needs to be reset as a type handler might modify it
        new_muobj = type_handlers[type(obj.data)](obj, muobj, mu)
        if not new_muobj:
            # the handler decided the object should not be exported
            return None
        # Keep object_paths in sync if the handler replaced the MuObject
        if new_muobj is not muobj:
            mu.object_paths[path] = new_muobj
        muobj = new_muobj
    # Particles may live on mesh/empty/armature hosts (Unity ParticleEmitter GO)
    if not getattr(muobj, "particles", None):
        from .empty import _particles_from_id_prop
        particles = _particles_from_id_prop(obj)
        if particles is not None:
            muobj.particles = particles
    mu.exported_objects.add(obj)
    col = find_single_collider(obj.children)
    if col:
        mu.exported_objects.add(col)
        muobj.collider = make_collider(mu, col)
    for o in obj.children:
        if o in mu.exported_objects:
            # the object has already been exported
            continue
        # Objects parented to bones are exported via export_bone
        if o.parent_type == 'BONE':
            continue
        # Blender-only particle preview / collider gizmo meshes
        if (".preview" in o.name or ".fx_preview" in o.name
                or ".fx_emitter" in o.name or ".cfg_preview" in o.name
                or o.name.startswith("mesh:")
                or o.get("mu_fx_preview")):
            mu.exported_objects.add(o)
            continue
        # Anim-only stubs from import (missing/garbage Unity paths). Keep NLA
        # for curve export via collect_animations; never emit as MuObjects so
        # hierarchy matches the original .mu (ladder-2 tanks/colliders etc.).
        try:
            if o.get("mu_anim_stub"):
                mu.exported_objects.add(o)
                continue
        except Exception:
            pass
        # Export Active Variant: omit GAMEOBJECTS branches hidden by preview
        if getattr(mu, "bake_active_variant", False) and o.get("mu_variant_hidden"):
            mu.exported_objects.add(o)
            continue
        # A "<name>.bindPose" armature sibling that shares this object's own
        # base name is the *same* source GameObject, just split into two
        # Blender objects on import (eg. a GO with both a Collider and a
        # SkinnedMeshRenderer becomes "<name>∧" + "<name>" collider +
        # "<name>.bindPose" armature). Merge its SMR component back into
        # this muobj instead of emitting a duplicate nested MuObject with
        # the same name: a duplicate name confuses bone/hierarchy lookup on
        # reimport and causes the container's scale to be applied twice to
        # everything beneath it (eg. TriBitDrill's DrillBase 100x stretch).
        from .armature import is_bindpose_armature, bindpose_base_name
        if (type(o.data) == bpy.types.Armature and is_bindpose_armature(o)
                and bindpose_base_name(o) == muobj.transform.name
                and not getattr(muobj, "skinned_mesh_renderer", None)):
            mu.exported_objects.add(o)
            from .armature import handle_armature
            handle_armature(o, muobj, mu)
            # handle_armature/handle_bindpose only claims the skin mesh(es);
            # any other child of the bindPose armature (rare) still needs
            # the normal recursion make_obj_core would have given it.
            for o2 in o.children:
                if o2 in mu.exported_objects or o2.parent_type == 'BONE':
                    continue
                if (".preview" in o2.name or ".fx_preview" in o2.name
                        or ".fx_emitter" in o2.name
                        or o2.name.startswith("mesh:")
                        or o2.get("mu_fx_preview")):
                    mu.exported_objects.add(o2)
                    continue
                if (getattr(mu, "bake_active_variant", False)
                        and o2.get("mu_variant_hidden")):
                    mu.exported_objects.add(o2)
                    continue
                child = make_obj(mu, o2, path)
                if child:
                    muobj.children.append(child)
            continue
        child = make_obj(mu, o, path)
        if child:
            muobj.children.append(child)
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
    # Strip Blender-only .bindPose suffix before path registration
    from .armature import is_bindpose_armature, bindpose_base_name
    if type(obj.data) == bpy.types.Armature and is_bindpose_armature(obj):
        muobj.transform.name = bindpose_base_name(obj)
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

def _mu_target_for_blender_name(mu, val):
    """Map a Blender object name to its exported MuObject (no prefix collisions)."""
    mapping = getattr(mu, "blender_to_mu", {}) or {}
    if not val:
        return None
    hit = mapping.get(val)
    if hit is not None:
        return hit
    val_s = strip_nnn(val)
    matches = []
    seen = set()
    for bname, mobj in mapping.items():
        if mobj is None:
            continue
        ptr = id(mobj)
        if ptr in seen:
            continue
        # Only Blender's .001 uniquifier of the *same* datablock, not ht2 vs ht2_JEM
        if bname.startswith(val + ".") or val.startswith(bname + "."):
            seen.add(ptr)
            matches.append(mobj)
            continue
        if val_s and strip_nnn(bname) == val_s:
            seen.add(ptr)
            matches.append(mobj)
    if len(matches) == 1:
        return matches[0]
    return None


def _merge_animation_clips(dst, src):
    """Append src clips into dst, combining curves when names already exist."""
    if dst is None or src is None:
        return dst
    existing = {}
    for clip in getattr(dst, "clips", None) or []:
        existing[clip.name] = clip
    for clip in getattr(src, "clips", None) or []:
        prev = existing.get(clip.name)
        if prev is None:
            dst.clips.append(clip)
            existing[clip.name] = clip
        else:
            prev.curves.extend(clip.curves)
    if not getattr(dst, "clip", None) and getattr(src, "clip", None):
        dst.clip = src.clip
    return dst


def export_object(obj, filepath, bake_active_variant=False):
    animations = collect_animations(obj)
    collect_orphan_stub_animations(obj, animations)
    anim_root = find_path_root(animations)
    mu = Mu()
    mu.exported_objects = set()
    mu.bake_active_variant = bool(bake_active_variant)
    mu.name = strip_nnn(obj.name)
    mu.object_paths = {}
    mu.blender_to_mu = {}
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
    # (Former WARNING "suggest buffer empty…" fired for nearly every stock
    # part whose clips share a single-segment LCA — noise, not an error.)
    mu.inverse = obj.matrix_world.inverted()
    mu.special = special_modelTypes[mu.type]
    mu.obj = make_obj(mu, obj, "")
    # Particle emitters (esp. Squad/FX) reference materials without a MeshRenderer.
    # Pull those materials/textures into the export so the .mu matches stock.
    try:
        import json
        from .material import make_material
        for o in bpy.data.objects:
            raw = o.get("mu_particle_materials") if hasattr(o, "get") else None
            if not raw and not o.get("mu_particles"):
                continue
            names = []
            if raw:
                try:
                    names = json.loads(raw) if isinstance(raw, str) else list(raw)
                except Exception:
                    names = []
            if not names and o.get("mu_particles"):
                # Fallback: any loaded particle-shader material
                for mat in bpy.data.materials:
                    sn = getattr(getattr(mat, "mumatprop", None), "shaderName", "") or ""
                    if "particle" in sn.lower():
                        names.append(mat.name)
            for n in names:
                mat = bpy.data.materials.get(n)
                if mat is None:
                    continue
                key = mat.name
                if key not in mu.materials:
                    mu.materials[key] = make_material(mu, mat)
    except Exception as e:
        mu.messages.append(({'WARNING'}, f"particle materials export: {e}"))
    mu.materials = list(mu.materials.values())
    mu.materials.sort(key=lambda x: x.index)
    mu.textures = list(mu.textures.values())
    mu.textures.sort(key=lambda x: x.index)
    # Prefer per-host MuAnimation (from import metadata); fall back to single LCA root.
    host_groups = group_animations_by_host(animations, anim_root)
    for host_key, host_anims in host_groups.items():
        target = None
        target_path = None
        kind, val = host_key if (
            isinstance(host_key, tuple) and len(host_key) == 2
        ) else ("path", host_key)
        if kind == "bobj":
            target = _mu_target_for_blender_name(mu, val)
            if target is not None:
                target_path = getattr(target, "path", None) or anim_root
        else:
            target_path = val if val in mu.object_paths else anim_root
            if target_path and target_path in mu.object_paths:
                target = mu.object_paths[target_path]
        if target is None:
            continue
        if not target_path:
            target_path = getattr(target, "path", None) or anim_root or ""
        new_anim = make_animations(mu, host_anims, target_path)
        if hasattr(target, "animation") and target.animation and target.animation.clips:
            _merge_animation_clips(target.animation, new_anim)
        else:
            target.animation = new_anim
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
