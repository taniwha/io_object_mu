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
import math
from mathutils import Vector, Quaternion
from math import pi
from .light import light_power
import importlib
from ..utils import action_compat as _action_compat_mod
importlib.reload(_action_compat_mod)
from ..utils.action_compat import (
    fcurve_new, iter_action_fcurves, push_action_to_nla, apply_mu_curve_wrap,
    apply_mu_clip_wrap_to_strip, mu_wrap_name, count_action_fcurves,
    actions_clip_length,
)

#mess with the heads of 6.28... fans :P
tau = pi / 180

# Collected during create_action; printed once at end of import (no timer spam)
MU_IMPORT_CLIPS = []
MU_IMPORT_GENERATION = 0
_MU_SUMMARY_DONE_GEN = -1
_MU_PLAY_TIMER_GEN = -1


property_map = {
    "m_LocalPosition.x": ("obj", "location", 0, 1, 3),
    "m_LocalPosition.y": ("obj", "location", 2, 1, 3),
    "m_LocalPosition.z": ("obj", "location", 1, 1, 3),
    "m_LocalRotation.x": ("obj", "rotation_quaternion", 1, -1, 4),
    "m_LocalRotation.y": ("obj", "rotation_quaternion", 3, -1, 4),
    "m_LocalRotation.z": ("obj", "rotation_quaternion", 2, -1, 4),
    "m_LocalRotation.w": ("obj", "rotation_quaternion", 0, 1, 4),
    "m_LocalScale.x": ("obj", "scale", 0, 1, 3),
    "m_LocalScale.y": ("obj", "scale", 2, 1, 3),
    "m_LocalScale.z": ("obj", "scale", 1, 1, 3),
    "localEulerAnglesRaw.x": ("obj", "rotation_euler", 0, -tau, 3),
    "localEulerAnglesRaw.y": ("obj", "rotation_euler", 2, -tau, 3),
    "localEulerAnglesRaw.z": ("obj", "rotation_euler", 1, -tau, 3),
    "m_Intensity": ("data", "energy", 0, light_power),
    "m_Color.r": ("data", "color", 0, 1),
    "m_Color.g": ("data", "color", 1, 1),
    "m_Color.b": ("data", "color", 2, 1),
    "m_Color.a": ("data", "color", 3, 1),
    # Unity Light.enabled — stored as custom prop for round-trip
    "m_Enabled": ("obj", '["mu_light_enabled"]', 0, 1),
}

# Unity AudioSource properties commonly animated in PartTools clips (AT_AUDIO_SOURCE=3)
_AUDIO_PROPS = {
    "m_Volume", "m_Pitch", "m_SpatialBlend", "panLevelCustomCurve",
    "m_Pan2D", "minDistance", "maxDistance", "dopplerLevel", "spread",
    "m_PlayOnAwake", "m_Loop", "m_Mute", "m_BypassEffects",
    "m_BypassListenerEffects", "m_BypassReverbZones", "reverbZoneMixCustomCurve",
    "volume", "pitch", "spatialBlend", "minVolume", "maxVolume", "rolloffFactor",
}


def _audio_prop_key(unity_prop: str) -> str:
    safe = unity_prop.replace(".", "_").replace("[", "_").replace("]", "_")
    return "mu_audio_" + safe


def audio_property(obj, prop):
    """Map AudioSource curve → Object ID property for lossless round-trip."""
    if not obj or not prop:
        return None
    base = prop.split(".")[0]
    if prop not in _AUDIO_PROPS and base not in _AUDIO_PROPS:
        # Accept unknown m_* floats that are not transform/light/material
        if not (prop.startswith("m_") or prop in ("volume", "pitch")):
            return None
        if prop.startswith("m_Local") or prop.startswith("m_Color") or prop.startswith("m_Intensity"):
            return None
    key = _audio_prop_key(prop)
    if key not in obj:
        try:
            obj[key] = 0.0
        except Exception:
            return None
    # RNA path for custom properties on Object
    return obj, f'["{key}"]', 0

vector_map = {
    "r": 0, "g": 1, "b": 2, "a":3,
    "x": 0, "y": 1, "z": 2, "w":3,  # shader props not read as quaternions
}

def property_index(properties, prop):
    for i, p in enumerate(properties):
        if p.name == prop:
            return i
    return None

def _parse_texture_anim_prop(prop):
    """Map Unity texture anim names → (tex_name, attr, rna_index).

    Supported forms:
      _MainTex.offset.x / .offset.y / .scale.x / .scale.y
      _MainTex_ST.r/.g/.b/.a  (scale.xy, offset.xy)
    ``_TexelSize`` is Unity texture metadata — not stored on MuTextureProperties.
    """
    if not prop:
        return None
    if len(prop) == 3 and prop[1] in ("offset", "scale") and prop[2] in ("x", "y"):
        return prop[0], prop[1], 0 if prop[2] == "x" else 1
    if len(prop) == 2 and prop[0].endswith("_ST") and prop[1] in vector_map:
        base = prop[0][:-3]  # strip "_ST"
        idx = vector_map[prop[1]]
        if idx < 2:
            return base, "scale", idx
        return base, "offset", idx - 2
    if len(prop) == 2 and prop[0].endswith("_TexelSize"):
        return None
    return None

def _ensure_texture_prop(mat, tex_name):
    props = mat.mumatprop.texture.properties
    if tex_name in props:
        return property_index(props, tex_name)
    item = props.add()
    item.name = tex_name
    try:
        item.scale = (1.0, 1.0)
        item.offset = (0.0, 0.0)
    except Exception:
        pass
    return property_index(props, tex_name)

def _shader_property_on_mat(mat, prop):
    if not mat or not hasattr(mat, "mumatprop"):
        return None
    mumat = mat.mumatprop
    # Texture offset/scale / _ST (before generic color/vector lookup)
    tex_parsed = _parse_texture_anim_prop(prop)
    if tex_parsed is not None:
        tex_name, attr, rna_index = tex_parsed
        prop_index = _ensure_texture_prop(mat, tex_name)
        if prop_index is None:
            return None
        path = "mumatprop.texture.properties[%d].%s" % (prop_index, attr)
        return mat, path, rna_index
    if len(prop) >= 1 and (prop[0].endswith("_TexelSize")
                           or (len(prop) >= 2 and prop[0].endswith("_ST"))):
        # Unmapped texture metadata (e.g. TexelSize) — quiet skip
        return None
    for subpath in ["color", "vector", "float2", "float3", "texture"]:
        propset = getattr(mumat, subpath)
        if prop[0] not in propset.properties:
            continue
        if subpath == "texture":
            # Bare texture name without .offset/.scale/_ST — nothing to animate
            return None
        if subpath[:5] == "float":
            rnaIndex = 0
        else:
            if len(prop) < 2:
                return None
            rnaIndex = vector_map[prop[1]]
        propIndex = property_index(propset.properties, prop[0])
        path = "mumatprop.%s.properties[%d].value" % (subpath, propIndex)
        return mat, path, rnaIndex
    return None

def shader_property(obj, prop):
    """Find animated shader prop on obj, its mesh children, or any loaded material."""
    prop = prop.split(".")
    if not obj:
        return None

    def materials_on(o):
        if o and type(getattr(o, "data", None)) == bpy.types.Mesh and o.data.materials:
            for mat in o.data.materials:
                if mat:
                    yield mat

    def search_obj(o, depth=0):
        for mat in materials_on(o):
            hit = _shader_property_on_mat(mat, prop)
            if hit:
                return hit
        if depth < 4 and o:
            for c in o.children:
                hit = search_obj(c, depth + 1)
                if hit:
                    return hit
            # Also look at siblings via parent (gimbal anim → body material)
            if depth == 0 and o.parent:
                for s in o.parent.children:
                    if s is o:
                        continue
                    hit = search_obj(s, depth + 1)
                    if hit:
                        return hit
        return None

    hit = search_obj(obj)
    if hit:
        return hit
    # Fallback: any material in the file that has this property (emissive
    # curves often target a transform whose mesh is a sibling/cousin).
    for mat in bpy.data.materials:
        hit = _shader_property_on_mat(mat, prop)
        if hit:
            return hit
    # Last resort: synthesize the color/texture prop on the nearest mesh
    # material so export keeps the curves (KSP animates _EmissiveColor even
    # when the material chunk did not list it; same for texture offset/_ST).
    if prop and prop[0].startswith("_"):
        tex_parsed = _parse_texture_anim_prop(prop)

        def _synth_and_hit(mat):
            if not mat or not hasattr(mat, "mumatprop"):
                return None
            if tex_parsed is not None:
                _ensure_texture_prop(mat, tex_parsed[0])
            elif prop[0] not in mat.mumatprop.color.properties:
                item = mat.mumatprop.color.properties.add()
                item.name = prop[0]
                try:
                    item.value = (1.0, 1.0, 1.0, 1.0)
                except Exception:
                    pass
            return _shader_property_on_mat(mat, prop)

        for mat in list(materials_on(obj)):
            hit = _synth_and_hit(mat)
            if hit:
                return hit
        if obj and obj.parent:
            for s in obj.parent.children:
                for mat in materials_on(s):
                    hit = _synth_and_hit(mat)
                    if hit:
                        return hit
        for mat in bpy.data.materials:
            hit = _synth_and_hit(mat)
            if hit:
                return hit
    return None

def _convert_empty_to_light(obj, light_type='SPOT'):
    """Blender Empties cannot hold a Light datablock (only Image/None).
    Replace the Empty with a LIGHT object, preserving hierarchy + props.
    Returns (light_datablock, new_object).
    """
    if obj.type == 'LIGHT' and obj.data:
        return obj.data, obj
    light = bpy.data.lights.new(obj.name + ".light", light_type)
    name = obj.name
    collections = list(obj.users_collection)
    parent = obj.parent
    parent_type = obj.parent_type
    parent_bone = obj.parent_bone
    matrix_local = obj.matrix_local.copy()
    children = [(c, c.matrix_local.copy()) for c in obj.children]
    custom = {}
    for k in obj.keys():
        if k == "_RNA_UI":
            continue
        try:
            custom[k] = obj[k]
        except Exception:
            pass
    # Preserve KSP object props when present
    tag = layer = None
    try:
        tag = obj.muproperties.tag
        layer = obj.muproperties.layer
    except Exception:
        pass

    new_obj = bpy.data.objects.new(name, light)
    for col in collections:
        try:
            col.objects.link(new_obj)
        except Exception:
            pass
    new_obj.parent = parent
    new_obj.parent_type = parent_type
    if parent_type == 'BONE' and parent_bone:
        new_obj.parent_bone = parent_bone
    new_obj.matrix_local = matrix_local
    for c, ml in children:
        c.parent = new_obj
        c.matrix_local = ml
    for k, v in custom.items():
        try:
            new_obj[k] = v
        except Exception:
            pass
    if tag is not None:
        try:
            new_obj.muproperties.tag = tag
            new_obj.muproperties.layer = layer
        except Exception:
            pass
    # Created only so Blender can host light anim curves — source .mu had no
    # Light component. Export must not emit MuLight (CockpitStandard etc.).
    new_obj["mu_synth_light"] = 1
    # Remove old empty (unlink first)
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
    return light, new_obj


def _find_action_fcurve(action, data_path, index):
    for fc in iter_action_fcurves(action):
        try:
            if fc.data_path == data_path and int(fc.array_index) == int(index):
                return fc
        except Exception:
            continue
    return None


def _incoming_keys_match(fc, keys, mult, fps, frame0):
    """True when this F-curve already stores the same Unity keys."""
    try:
        existing = list(fc.keyframe_points)
    except Exception:
        return False
    if len(existing) != len(keys):
        return False
    for kp, key in zip(existing, keys):
        try:
            x = float(key.time) * fps + frame0
            y = float(key.value) * float(mult)
        except Exception:
            return False
        if abs(float(kp.co[0]) - x) > 1e-3 or abs(float(kp.co[1]) - y) > 1e-4:
            return False
    return True


def create_fcurve(action, curve, propmap, datablock, rest_value=None):
    if datablock is None:
        print(f"WARNING: skip fcurve {propmap[0]!r} — no datablock")
        return None
    dp, ind, mult = propmap
    fps = bpy.context.scene.render.fps
    keys = list(curve.keys)
    frame0 = float(bpy.context.scene.frame_start)
    existing = _find_action_fcurve(action, dp, ind)
    if existing is not None:
        if _incoming_keys_match(existing, keys, mult, fps, frame0):
            return existing
        try:
            existing.keyframe_points.clear()
        except Exception:
            pass
        fc = existing
    else:
        try:
            fc = fcurve_new(action, datablock, dp, index=ind)
        except RuntimeError as exc:
            fc = _find_action_fcurve(action, dp, ind)
            if fc is None:
                print("WARNING: duplicate curve skipped (%s): %s" % (dp, exc))
                return None
            if _incoming_keys_match(fc, keys, mult, fps, frame0):
                return fc
            try:
                fc.keyframe_points.clear()
            except Exception:
                pass
    # Unity AnimationCurve Clamp: before the first key the value is the *first
    # key's value*, not the GO bind pose. Padding with bind (deployed gear /
    # open hatch) made LandingGear Large/Medium/Small start with the wheel out
    # on a closed bay, then snap shut at the first key. Prefer first-key pad
    # (Unity Clamp). ``rest_value`` (bind) is only a fallback when the first
    # key is unreadable.
    frame0 = float(bpy.context.scene.frame_start)
    pad_value = None
    if keys and float(keys[0].time) > 1e-4:
        try:
            pad_value = float(keys[0].value) * float(mult)
        except Exception:
            pad_value = None
        if pad_value is None and rest_value is not None:
            try:
                pad_value = float(rest_value)
            except Exception:
                pad_value = None
    need_rest = pad_value is not None and math.isfinite(float(pad_value))
    fc.keyframe_points.add(len(keys) + (1 if need_rest else 0))

    def _safe_handle_delta(tangent, dist):
        """Unity stepped/constant keys often store ±Inf tangents — keep Blender finite."""
        if dist == 0 or not math.isfinite(dist):
            return 10.0, 0.0
        dx = dist * fps
        raw = tangent * dist * mult
        if not math.isfinite(raw) or abs(raw) > 1e6:
            return dx, 0.0
        return dx, raw

    def _write_kp(i, x, y, tan_in, tan_out, dist_in, dist_out):
        if not math.isfinite(x):
            x = float(i)
        if not math.isfinite(y):
            y = 0.0
        fc.keyframe_points[i].co = x, y
        fc.keyframe_points[i].handle_left_type = 'FREE'
        fc.keyframe_points[i].handle_right_type = 'FREE'
        dx, dy = _safe_handle_delta(tan_in, dist_in)
        fc.keyframe_points[i].handle_left = x - dx, y - dy
        dx, dy = _safe_handle_delta(tan_out, dist_out)
        fc.keyframe_points[i].handle_right = x + dx, y + dy

    off = 0
    if need_rest:
        _write_kp(0, frame0, float(pad_value), 0.0, 0.0, 0.0, 0.0)
        off = 1

    for i, key in enumerate(keys):
        x = key.time * fps + frame0
        y = key.value * mult
        dist_in = 0.0
        dist_out = 0.0
        tan_in = 0.0
        tan_out = 0.0
        if i > 0:
            dist_in = (key.time - keys[i - 1].time) / 3
            tan_in = key.tangent[0]
        elif need_rest:
            dist_in = key.time / 3
            tan_in = key.tangent[0]
        if i < len(keys) - 1:
            dist_out = (keys[i + 1].time - key.time) / 3
            tan_out = key.tangent[1]
        _write_kp(i + off, x, y, tan_in, tan_out, dist_in, dist_out)
    return fc


_GARBAGE_PATH_MARKERS = (
    "|mesh:",
    "|Dupli|",
    "Dupli|",
)


def _is_garbage_anim_path(mu_path: str) -> bool:
    """Paths that must never become hierarchy nodes (Blender Dupli / mesh tags)."""
    p = mu_path or ""
    if not p:
        return False
    for m in _GARBAGE_PATH_MARKERS:
        if m in p:
            return True
    leaf = p.rstrip("/").split("/")[-1]
    if leaf.startswith("mesh:"):
        return True
    return False


def _resolve_existing_anim_target(mu, mu_path: str, host_path: str = ""):
    """Map a Unity curve path to an existing MuObject without creating stubs.

    Order:
      1. exact key in object_paths
      2. host_path + relative path
      3. any object_paths entry ending with the relative path
      4. unique leaf-name match under the host prefix
    """
    if not mu_path:
        return None, ""
    if mu_path in mu.object_paths:
        return mu.object_paths[mu_path], mu_path
    rel = (host_path + "/" + mu_path) if host_path else mu_path
    if rel in mu.object_paths:
        return mu.object_paths[rel], rel
    cpath = mu_path.rstrip("/")
    matches = [
        p for p in mu.object_paths
        if p == cpath or p.endswith("/" + cpath)
    ]
    if len(matches) == 1:
        return mu.object_paths[matches[0]], matches[0]
    leaf = cpath.split("/")[-1]
    if leaf:
        leaf_hits = []
        for p, obj in mu.object_paths.items():
            if p.rsplit("/", 1)[-1] != leaf:
                continue
            if host_path and not (p == host_path or p.startswith(host_path + "/")):
                continue
            leaf_hits.append(p)
        if len(leaf_hits) == 1:
            return mu.object_paths[leaf_hits[0]], leaf_hits[0]
    return None, ""


def _orphan_attach_host(mu, host_path: str):
    """MuObject that owns the Animation component (fallback for orphan curves)."""
    if host_path and host_path in mu.object_paths:
        return mu.object_paths[host_path], host_path
    parts = [s for s in (host_path or "").split("/") if s]
    while parts:
        p = "/".join(parts)
        if p in mu.object_paths:
            return mu.object_paths[p], p
        parts.pop()
    for p, obj in mu.object_paths.items():
        if getattr(obj, "animation", None) is not None:
            return obj, p
    if mu.object_paths:
        p = next(iter(mu.object_paths))
        return mu.object_paths[p], p
    return None, ""


def _ensure_path_object(mu, mu_path):
    """Create stub MuObjects + Blender empties for clip paths missing in the .mu hierarchy."""
    if mu_path in mu.object_paths:
        return mu.object_paths[mu_path]
    parts = mu_path.split("/")
    # Find longest existing prefix
    parent = None
    parent_path = ""
    built = []
    for i, part in enumerate(parts):
        built.append(part)
        p = "/".join(built)
        if p in mu.object_paths:
            parent = mu.object_paths[p]
            parent_path = p
            continue
        # Need a new node under parent
        class _T:
            pass
        class _O:
            pass
        stub = _O()
        stub.transform = _T()
        stub.transform.name = part
        stub.transform.localPosition = Vector((0, 0, 0))
        stub.transform.localRotation = Quaternion((1, 0, 0, 0))
        stub.transform.localScale = Vector((1, 1, 1))
        stub.children = []
        stub.components = []
        stub.path = p
        stub.parent = parent
        # Anim-only: never force into exported hierarchy (non-destructive).
        stub.force_import = False
        stub.mu = mu
        col = getattr(mu, "collection", None) or bpy.context.scene.collection
        bobj = bpy.data.objects.new(part, None)
        bobj.empty_display_type = 'PLAIN_AXES'
        try:
            bobj.empty_display_size = 0.01
        except Exception:
            pass
        col.objects.link(bobj)
        # Prefer empty host, then control/bindPose armature, then walk
        # ancestors — bone-only MuObjects have neither bobj nor armature_obj,
        # which left TriBitDrill's ``shake`` as a second import root.
        parent_bl = None
        if parent is not None:
            parent_bl = getattr(parent, "bobj", None) or getattr(
                parent, "armature_obj", None)
            if parent_bl is None:
                walk = parent
                while walk is not None and parent_bl is None:
                    parent_bl = getattr(walk, "bobj", None) or getattr(
                        walk, "armature_obj", None)
                    walk = getattr(walk, "parent", None)
        if parent_bl is None:
            # Orphan stubs become extra import roots (Beacon1 1→6). Attach under
            # the nearest non-stub object of this import, or the collection root.
            try:
                iid = str(getattr(mu, "import_id", "") or "")
                for o in bpy.data.objects:
                    try:
                        if iid and str(o.get("mu_import_id") or "") != iid:
                            continue
                        if o.get("mu_anim_stub"):
                            continue
                    except Exception:
                        continue
                    if o is bobj:
                        continue
                    # Prefer a true top-level model object
                    try:
                        if o.parent is None or str(
                                getattr(o.parent, "get", lambda *_: None)(
                                    "mu_import_id") or "") != iid:
                            parent_bl = o
                            break
                    except Exception:
                        parent_bl = o
                        break
            except Exception:
                parent_bl = None
        if parent_bl is not None:
            bobj.parent = parent_bl
        stub.bobj = bobj
        try:
            # Stubs keep clip curves for round-trip but must not affect
            # viewport framing / GIF motion bounds (stale capsule/hatch).
            bobj["mu_anim_stub"] = 1
            bobj.hide_render = True
            bobj.hide_viewport = True
            bobj.hide_set(True)
            if getattr(mu, "import_id", None):
                bobj["mu_import_id"] = str(mu.import_id)
        except Exception:
            pass
        mu.object_paths[p] = stub
        mu.objects.setdefault(part, stub)
        if parent is not None:
            if not hasattr(parent, "children") or parent.children is None:
                parent.children = []
            parent.children.append(stub)
        print(f"INFO: Created missing anim path node: {p}")
        parent = stub
        parent_path = p
    return mu.object_paths.get(mu_path)


def _control_armature_obj(muobj):
    arm = getattr(muobj, "armature", None)
    arm_obj = getattr(arm, "armature_obj", None) if arm else None
    if not isinstance(arm_obj, bpy.types.Object):
        owner = getattr(muobj, "owner", None)
        arm_obj = getattr(owner, "armature_obj", None) if owner else None
    return arm_obj if isinstance(arm_obj, bpy.types.Object) else None


def _bone_pose_anim_ok(arm_obj, bone_name):
    if not arm_obj or not bone_name:
        return False
    try:
        n = arm_obj.name or ""
    except Exception:
        n = ""
    if n.endswith(".bindPose") or ".bindPose." in n:
        return False
    try:
        return bone_name in arm_obj.data.bones
    except Exception:
        return False


def _ensure_anim_object_host(mu, mu_path, muobj):
    """Return a Blender object for object-space clip curves on ``mu_path``.

    Clip paths that only exist for animation (spring bones referenced by
    SkinnedMeshRenderer but absent from the transform tree) get hidden stub
    empties on first import. After export/reimport the curve paths often match
    bindPose bones instead — pose keys on bindPose are not collected on export,
    so keep using a dedicated object-space host like the first import.
    """
    if getattr(muobj, "bobj", None):
        return muobj.bobj
    existing = mu.object_paths.get(mu_path)
    if existing is not None and getattr(existing, "bobj", None):
        return existing.bobj
    stub = _ensure_path_object(mu, mu_path)
    if stub is not None and getattr(stub, "bobj", None):
        return stub.bobj
    name = mu_path.rsplit("/", 1)[-1] if mu_path else "anim"
    try:
        tname = getattr(getattr(muobj, "transform", None), "name", None)
        if tname:
            name = str(tname)
    except Exception:
        pass
    col = getattr(mu, "collection", None) or bpy.context.scene.collection
    bobj = bpy.data.objects.new(name, None)
    bobj.empty_display_type = 'PLAIN_AXES'
    col.objects.link(bobj)
    try:
        bobj["mu_anim_stub"] = 1
        bobj.hide_render = True
        bobj.hide_viewport = True
        try:
            bobj.hide_set(True)
        except Exception:
            pass
    except Exception:
        pass
    parent_bl = None
    parts = (mu_path or "").split("/")
    for i in range(len(parts) - 1, 0, -1):
        anc = mu.object_paths.get("/".join(parts[:i]))
        if anc is None:
            continue
        parent_bl = getattr(anc, "bobj", None) or getattr(
            anc, "armature_obj", None)
        if parent_bl is not None:
            break
    if parent_bl is None:
        # Same fallback as _ensure_path_object — never leave anim hosts as
        # extra import roots (Beacon1).
        try:
            iid = str(getattr(mu, "import_id", "") or "")
            for o in bpy.data.objects:
                try:
                    if iid and str(o.get("mu_import_id") or "") != iid:
                        continue
                    if o.get("mu_anim_stub"):
                        continue
                except Exception:
                    continue
                if o is bobj:
                    continue
                parent_bl = o
                break
        except Exception:
            parent_bl = None
    if parent_bl is not None:
        bobj.parent = parent_bl
    try:
        if getattr(mu, "import_id", None):
            bobj["mu_import_id"] = str(mu.import_id)
    except Exception:
        pass
    try:
        muobj.bobj = bobj
    except Exception:
        pass
    return bobj

def create_action(mu, path, clip, host=None):
    #print(clip.name)
    actions = {}
    bones = set()
    retargets = set()
    for curve in clip.curves:
        if not curve.keys:
            # Unity empty AnimationCurves evaluate to 0 and are common in
            # partial PartTools clips — nothing useful to put in Blender.
            # Keeping them would require sidecar metadata; skipping is safe.
            print("INFO: Curve has no keys (skipped)")
            continue
        path_retarget = False
        if not curve.path:
            mu_path = path
            # Self-targeted curves (path="") must use the Animation host.
            # Duplicate sibling names (RCSBlock Angled×4 RCSthruster) collide
            # in object_paths — looking up by path alone binds every clip to
            # the last sibling and drops glow on the other nozzles.
            if host is not None:
                muobj = host
            elif mu_path in mu.object_paths:
                muobj = mu.object_paths[mu_path]
            else:
                muobj = _ensure_path_object(mu, mu_path)
                if muobj is None:
                    if not hasattr(mu, "bad_paths"):
                        mu.bad_paths = set()
                    if mu_path not in mu.bad_paths:
                        mu.bad_paths.add(mu_path)
                        print("Unknown path: %s" % (mu_path))
                    continue
        else:
            # Curves are usually relative to the Animation host, but some
            # Squad parts store root-absolute paths — never double-prefix.
            rel = "/".join([path, curve.path]) if path else curve.path
            if rel in mu.object_paths:
                mu_path = rel
            elif curve.path in mu.object_paths:
                mu_path = curve.path
            else:
                mu_path = rel
            resolved = None
            base = curve.path.rstrip("/").split("/")[-1] if curve.path else ""
            if mu_path not in mu.object_paths:
                # Unity often uses a short relative name (e.g. "spotlight") while
                # the GO lives deeper (…/Lamp/spotlight). Resolve by unique
                # basename under the anim host before synthesizing stubs.
                # Multi-segment paths (capsule/hatch) must match as a path
                # suffix — basename-only binding retargets IVA hatch clips onto
                # the wrong GO (90° + huge mid-clip position keys).
                cpath = (curve.path or "").rstrip("/")
                multi = "/" in cpath
                if base:
                    under = [p for p in mu.object_paths
                             if (p == base or p.endswith("/" + base))
                             and (not path or p == path or p.startswith(path + "/"))]
                    if multi:
                        under = [p for p in under
                                 if p == cpath or p.endswith("/" + cpath)]
                    if len(under) == 1:
                        resolved = under[0]
                    else:
                        any_match = [p for p in mu.object_paths
                                     if p == base or p.endswith("/" + base)]
                        if multi:
                            any_match = [p for p in any_match
                                         if p == cpath or p.endswith("/" + cpath)]
                        if len(any_match) == 1:
                            resolved = any_match[0]
                if resolved:
                    mu_path = resolved
            if mu_path not in mu.object_paths:
                # Intermediate parents often missing in IVA .mu (clip path
                # capsule/hatch vs real GO mk1PodInternal/…/hatch). Fall back
                # to a unique leaf under the anim host before synthesizing a
                # hidden stub (stubs eat hatch rotation while the mesh sits
                # still).
                if not resolved and base:
                    leaf = [p for p in mu.object_paths
                            if (p == base or p.endswith("/" + base))
                            and (not path or p == path or p.startswith(path + "/"))]
                    if len(leaf) == 1:
                        resolved = leaf[0]
                    elif len(leaf) > 1:
                        meshish = []
                        for p in leaf:
                            mo = mu.object_paths.get(p)
                            if mo is None:
                                continue
                            if (hasattr(mo, "shared_mesh")
                                    or hasattr(mo, "renderer")
                                    or (getattr(mo, "bobj", None) is not None
                                        and getattr(mo.bobj, "type", None) == "MESH")):
                                meshish.append(p)
                        if len(meshish) == 1:
                            resolved = meshish[0]
                    if resolved:
                        mu_path = resolved
                        # Alias so later curves / stubs find the real GO
                        try:
                            mu.object_paths[rel] = mu.object_paths[resolved]
                        except Exception:
                            pass
                if resolved:
                    # Clip authored under a missing parent (capsule/…). Leaf
                    # mesh has a different bind pose — rebase rotation later.
                    path_retarget = True
            if mu_path not in mu.object_paths:
                # Non-destructive: resolve existing GO, orphan garbage paths on
                # the Animation host, else hidden stub (not written to .mu tree).
                resolved_obj, resolved_path = _resolve_existing_anim_target(
                    mu, curve.path or mu_path, path or "")
                if resolved_obj is not None:
                    muobj = resolved_obj
                    mu_path = resolved_path
                elif _is_garbage_anim_path(curve.path or mu_path or ""):
                    muobj, mu_path_host = _orphan_attach_host(mu, path or "")
                    if muobj is None:
                        if not hasattr(mu, "bad_paths"):
                            mu.bad_paths = set()
                        if mu_path not in mu.bad_paths:
                            mu.bad_paths.add(mu_path)
                            print("INFO: Skip garbage anim path (no host): %s"
                                  % (curve.path or mu_path))
                        continue
                    mu_path = mu_path_host
                    # Do NOT set path_retarget — that skips loc/scale keys.
                    # Orphan curves keep all channels on the host Action.
                else:
                    muobj = _ensure_path_object(mu, mu_path)
                    if muobj is None:
                        muobj, mu_path_host = _orphan_attach_host(mu, path or "")
                        if muobj is None:
                            if not hasattr(mu, "bad_paths"):
                                mu.bad_paths = set()
                            if mu_path not in mu.bad_paths:
                                mu.bad_paths.add(mu_path)
                                print("Unknown path: %s" % (mu_path))
                            continue
                        mu_path = mu_path_host
            else:
                muobj = mu.object_paths[mu_path]
            if curve.path and not path_retarget:
                leaf = curve.path.rstrip("/").split("/")[-1]
                try:
                    mname = str(getattr(getattr(muobj, "transform", None), "name", "") or "")
                except Exception:
                    mname = ""
                if leaf and mname and mname != leaf:
                    # Prefer resolve before creating alt stubs
                    alt_path = "/".join([p for p in (path, curve.path) if p])
                    alt_obj, alt_resolved = _resolve_existing_anim_target(
                        mu, curve.path, path or "")
                    if alt_obj is not None:
                        muobj = alt_obj
                        mu_path = alt_resolved
                    elif not _is_garbage_anim_path(alt_path):
                        alt = _ensure_path_object(mu, alt_path)
                        if alt is not None:
                            muobj = alt
                            mu_path = alt_path
            # Multi-segment clip path bound to a GO whose hierarchy path does
            # not end with that clip path (capsule/hatch → …/hatch): retarget.
            cpath = (curve.path or "").rstrip("/")
            if "/" in cpath and muobj is not None:
                real = (getattr(muobj, "path", None) or mu_path or "").rstrip("/")
                if real != cpath and not real.endswith("/" + cpath):
                    path_retarget = True
            if path_retarget:
                # Loc/scale keys are in the missing parent's local space
                # (IVA hatch loc ≈ (−4,−1,0.7) vs mesh (0,0.66,0.43)). Applying
                # them teleports the door; keep mesh bind for those channels.
                prop = curve.property or ""
                if prop.startswith("m_LocalPosition") or prop.startswith(
                        "m_LocalScale"):
                    continue
                try:
                    muobj._mu_anim_retarget = True
                except Exception:
                    pass
        dppref = ""
        use_pose_bone = False
        if hasattr(muobj, "bone"):
            bname = str(getattr(muobj, "bone", "") or "")
            arm_obj = _control_armature_obj(muobj)
            if _bone_pose_anim_ok(arm_obj, bname):
                obj = arm_obj
                dppref = f'pose.bones["{bname}"].'
                use_pose_bone = True
            else:
                obj = _ensure_anim_object_host(mu, mu_path, muobj)
        elif hasattr(muobj, "bobj") and muobj.bobj:
            obj = muobj.bobj
        else:
            # Animated node without mesh/collider — synthesize an empty host.
            # Must use _ensure_anim_object_host so the empty is tagged
            # mu_anim_stub, gets mu_import_id, and is parented under the model.
            # A bare bpy.data.objects.new left unparented top-level empties
            # that inflated Roots after reimport (Beacon1 1→6).
            print("INFO: No blender object at path: %s (creating empty)" % (mu_path))
            obj = _ensure_anim_object_host(mu, mu_path, muobj)
            if obj is None:
                col = getattr(mu, "collection", None) or bpy.context.scene.collection
                name = getattr(getattr(muobj, "transform", None), "name", None) or "anim"
                obj = bpy.data.objects.new(str(name), None)
                col.objects.link(obj)
                try:
                    obj["mu_anim_stub"] = 1
                    obj.hide_render = True
                    obj.hide_viewport = True
                    if getattr(mu, "import_id", None):
                        obj["mu_import_id"] = str(mu.import_id)
                except Exception:
                    pass
                muobj.bobj = obj
        if curve.property[:-2] == "localEulerAnglesRaw":
            obj.rotation_mode = 'YXZ'
        is_shader_curve = False
        is_audio_curve = False
        if curve.property not in property_map:
            sp = shader_property(obj, curve.property)
            if not sp:
                ap = audio_property(obj, curve.property)
                if not ap:
                    print("%s: Unknown property: %s" % (mu_path, curve.property))
                    continue
                obj, dp, rnaIndex = ap
                propmap = dp, rnaIndex, 1
                subpath = "obj"
                is_audio_curve = True
                use_pose_bone = False
                dppref = ""
            else:
                obj, dp, rnaIndex = sp
                propmap = dp, rnaIndex, 1
                subpath = "obj"
                is_shader_curve = True
                # Material ID fcurves must NOT use pose.bones[] prefixes
                use_pose_bone = False
                dppref = ""
        else:
            propmap = property_map[curve.property]
            subpath, propmap = propmap[0], propmap[1:]
        fullpropmap = (dppref + propmap[0],) + propmap[1:3]
        # Blender Object that owns NLA. Light curves must stay on the Object
        # (data_path "data.energy" etc.) — never on the Light datablock alone,
        # or export collects Object NLA + Light.action and reimport doubles
        # clips as "Spot Light.data" rows (LTV / GeminiInt2 regression).
        nla_owner = obj
        if subpath != "obj":
            data = getattr(obj, subpath, None)
            # Light curves need a Light datablock. Blender Empties cannot hold
            # lights (Object.data only accepts Image/None for EMPTY).
            if subpath == "data":
                if obj.type == 'EMPTY':
                    old_obj = obj
                    light, new_obj = _convert_empty_to_light(obj, 'SPOT')
                    if getattr(muobj, "bobj", None) is old_obj:
                        muobj.bobj = new_obj
                    try:
                        for _p, _mo in list(getattr(mu, "object_paths", {}).items()):
                            if getattr(_mo, "bobj", None) is old_obj:
                                _mo.bobj = new_obj
                    except Exception:
                        pass
                    for _k, (_act, _o) in list(actions.items()):
                        if _o is old_obj:
                            actions[_k] = (_act, new_obj)
                    obj = new_obj
                    nla_owner = new_obj
                    if "mu_light_enabled" not in obj:
                        obj["mu_light_enabled"] = 1.0
                    data = light
                elif obj.type == 'LIGHT':
                    nla_owner = obj
                    data = obj.data
                if data is None:
                    print(f"{mu_path}: skip curve {curve.property} — no light datablock")
                    continue
                # Animate through the Object: data_path "data.energy" / "data.color"
                # so one Action+NLA on the Object round-trips without .data splits.
                fullpropmap = (dppref + "data." + propmap[0],) + propmap[1:3]
                # keep obj = Object (nla_owner); do NOT switch to Light datablock
            else:
                obj = data
        if obj is None:
            print(f"{mu_path}: skip curve {curve.property} — no datablock")
            continue
        if curve.property == "m_Enabled":
            # Do NOT assign to `host` — that parameter is the MuAnimation owner
            # MuObject for path="" curves (spotLightMk1 emissive). Overwriting
            # it with a Blender Object caused AttributeError on .transform.
            try:
                light_obj = muobj.bobj if getattr(muobj, "bobj", None) else None
                if light_obj is not None and "mu_light_enabled" not in light_obj:
                    light_obj["mu_light_enabled"] = 1.0
            except Exception:
                pass
        try:
            host_name = str(getattr(getattr(muobj, "transform", None), "name", "") or "")
        except Exception:
            host_name = ""
        if not host_name:
            host_name = (muobj.bobj.name if getattr(muobj, "bobj", None)
                         else getattr(nla_owner, "name", None)
                         or getattr(obj, "name", "obj"))
        if is_audio_curve:
            # Own bucket — sharing "mat" with shader curves lost the single
            # AudioSource fcurve on GeminiInt2 reimport (Aud 1→0, Curves 17→16).
            kind = "aud"
        elif is_shader_curve:
            # Keep material curves off transform actpaths.
            kind = "mat"
        elif subpath == "data":
            # Dedicated light bucket (not ".data" panel rows, not merged with
            # transform on the same GO).
            kind = "lit"
        else:
            kind = subpath or "obj"
        # Prefer Unity ``curve.path`` so progressive resolve/retarget of
        # ``mu_path`` does not split one target's quaternion into 2 Actions
        # (1+3 fcurves) — that inflated Clips= on first import and dropped
        # after merge on reexport (mk1Pod, sspx docking, TriBit Impact…).
        unity_rel = (curve.path or "").strip()
        if unity_rel:
            act_base = unity_rel
        elif mu_path:
            act_base = str(mu_path).strip()
        else:
            act_base = path or ""
        # Export writes curve paths relative to the Animation host. First import
        # of a stock .mu often keeps absolute / longer paths → extra actpath
        # keys; reimport of our export uses relative paths → fewer Actions
        # (GeminiInt2 Clips 9→8, Curves=17). Normalize to host-relative form.
        host_path = (path or "").strip().rstrip("/")
        if host_path and act_base:
            if act_base == host_path:
                act_base = ""
            elif act_base.startswith(host_path + "/"):
                act_base = act_base[len(host_path) + 1:]
            else:
                leaf = host_path.rsplit("/", 1)[-1]
                if leaf and act_base.startswith(leaf + "/"):
                    act_base = act_base[len(leaf) + 1:]
                elif leaf and act_base == leaf:
                    act_base = ""
        # Stable key: relative unity path + kind (no host_name — renames on Light).
        actpath = "/".join([act_base or "_root", kind])
        # Human-readable Action name still includes host for the panel.
        objname = ".".join([str(host_name or "obj"), kind])
        if actpath not in actions:
            act = bpy.data.actions.new(objname)
            owner_for_nla = nla_owner
            if owner_for_nla is None or not hasattr(owner_for_nla, "animation_data"):
                owner_for_nla = getattr(muobj, "bobj", None)
            if owner_for_nla is None:
                owner_for_nla = obj
            actions[actpath] = act, owner_for_nla
            try:
                act["mu_unity_curve_path"] = curve.path or ""
            except Exception:
                pass
            try:
                # Lossless export path for missing/garbage Unity targets
                if _is_garbage_anim_path(curve.path or ""):
                    act["mu_orphan_curve"] = 1
                elif getattr(owner_for_nla, "get", None) and owner_for_nla.get("mu_anim_stub"):
                    act["mu_orphan_curve"] = 1
                elif mu_path and mu_path in mu.object_paths:
                    mo = mu.object_paths[mu_path]
                    b = getattr(mo, "bobj", None)
                    if b is not None and b.get("mu_anim_stub"):
                        act["mu_orphan_curve"] = 1
            except Exception:
                pass
        act, _stored_owner = actions[actpath]
        # create_fcurve: obj is Object (light via data.*) or datablock (mat)
        if is_shader_curve or is_audio_curve:
            # Preserve Unity renderer-relative path (shared materials may be
            # attached to a different mesh than the clip path, e.g. obj_gimbal).
            try:
                act["mu_unity_curve_path"] = curve.path or ""
            except Exception:
                pass
            # Preserve exact Unity property name (offset.x vs _ST.r, etc.)
            try:
                act["mu_uprop:%s:%d" % (fullpropmap[0], fullpropmap[1])] = (
                    curve.property)
            except Exception:
                pass
            if is_audio_curve:
                try:
                    act["mu_atype:%s:%d" % (fullpropmap[0], fullpropmap[1])] = 3
                except Exception:
                    pass
        rest_value = None
        if (not use_pose_bone and not is_shader_curve and not is_audio_curve
                and hasattr(muobj, "transform") and muobj.transform is not None):
            try:
                dp0 = propmap[0]
                idx = int(propmap[1])
                xform = muobj.transform
                if dp0 == "location":
                    rest_value = float(xform.localPosition[idx])
                elif dp0 == "rotation_quaternion":
                    rest_value = float(xform.localRotation[idx])
                elif dp0 == "scale":
                    rest_value = float(xform.localScale[idx])
            except Exception:
                rest_value = None
        fcurve = create_fcurve(act, curve, fullpropmap, obj, rest_value=rest_value)
        if fcurve is None:
            continue
        # Preserve MuCurve.wrapMode (pre, post) for non-destructive export
        try:
            wm = getattr(curve, "wrapMode", None)
            if wm is not None:
                pre = int(wm[0]) if isinstance(wm, (tuple, list)) else int(wm)
                post = int(wm[1]) if isinstance(wm, (tuple, list)) and len(wm) > 1 else pre
                apply_mu_curve_wrap(act, fcurve, pre, post)
        except Exception:
            pass
        # Only transform channels (location/rotation/scale) carry a 4th
        # "component count" entry. Light/material props are shorter tuples —
        # never feed them into bone-space fcurve rebasing (turboJet crash).
        if use_pose_bone and len(propmap) >= 4:
            if not hasattr(muobj, "fcurves"):
                muobj.fcurves = {}
            if propmap[0] not in muobj.fcurves:
                muobj.fcurves[propmap[0]] = [None] * propmap[3]
            muobj.fcurves[propmap[0]][propmap[1]] = fcurve
            bones.add(muobj)
        elif (getattr(muobj, "_mu_anim_retarget", False)
                and not use_pose_bone and not is_shader_curve
                and not is_audio_curve and len(propmap) >= 4
                and propmap[0] == "rotation_quaternion"):
            if not hasattr(muobj, "fcurves"):
                muobj.fcurves = {}
            if propmap[0] not in muobj.fcurves:
                muobj.fcurves[propmap[0]] = [None] * propmap[3]
            muobj.fcurves[propmap[0]][propmap[1]] = fcurve
            retargets.add(muobj)
    for muobj in bones:
        xform = muobj.transform
        rrot = muobj.relRotation
        if "location" in muobj.fcurves:
            location = muobj.fcurves["location"]
            lloc = Vector(muobj.transform.localPosition)
            if None in location:
                print("INFO: Skipping incomplete location fcurve set")
            else:
                n = min(len(location[i].keyframe_points) for i in range(3))
                if n == 0:
                    print("INFO: Skipping empty location fcurve set")
                else:
                    if (len(location[0].keyframe_points) != n
                            or len(location[1].keyframe_points) != n
                            or len(location[2].keyframe_points) != n):
                        print("INFO: Location fcurve key counts differ — "
                              f"converting first {n} keys")
                    for i in range(n):
                        def transformkey(kval, i=i):
                            xk = getattr(location[0].keyframe_points[i], kval)
                            yk = getattr(location[1].keyframe_points[i], kval)
                            zk = getattr(location[2].keyframe_points[i], kval)
                            loc = Vector((xk.y, yk.y, zk.y))
                            loc = rrot @ (loc - lloc)
                            (xk.y, yk.y, zk.y) = loc
                        transformkey("co")
                        transformkey("handle_left")
                        transformkey("handle_right")
        if "rotation_quaternion" in muobj.fcurves:
            rotation = muobj.fcurves["rotation_quaternion"]
            lrot = Quaternion(muobj.transform.localRotation).inverted()
            if None in rotation:
                print("INFO: Skipping incomplete rotation fcurve set")
            elif ((len(rotation[0].keyframe_points)
                  != len(rotation[1].keyframe_points))
                  or (len(rotation[0].keyframe_points)
                      != len(rotation[2].keyframe_points))
                  or (len(rotation[0].keyframe_points)
                      != len(rotation[3].keyframe_points))):
                print("INFO: Skipping mismatched rotation fcurve set")
            else:
                for i in range(len(rotation[0].keyframe_points)):
                    def rotkey(kval):
                        wk = getattr(rotation[0].keyframe_points[i], kval)
                        xk = getattr(rotation[1].keyframe_points[i], kval)
                        yk = getattr(rotation[2].keyframe_points[i], kval)
                        zk = getattr(rotation[3].keyframe_points[i], kval)
                        q = Quaternion((wk.y, xk.y, yk.y, zk.y))
                        q = lrot @ q
                        (wk.y, xk.y, yk.y, zk.y) = q
                    rotkey("co")
                    rotkey("handle_left")
                    rotkey("handle_right")
    # IVA hatch etc.: clip rest is identity under missing capsule/; mesh bind
    # is ~90°. Rebase so t=0 keeps the flush door and motion stays relative.
    for muobj in retargets:
        rotation = (getattr(muobj, "fcurves", None) or {}).get(
            "rotation_quaternion")
        if not rotation or None in rotation:
            continue
        if ((len(rotation[0].keyframe_points)
              != len(rotation[1].keyframe_points))
              or (len(rotation[0].keyframe_points)
                  != len(rotation[2].keyframe_points))
              or (len(rotation[0].keyframe_points)
                  != len(rotation[3].keyframe_points))):
            continue
        try:
            mesh_rest = Quaternion(muobj.transform.localRotation)
        except Exception:
            continue
        try:
            w0 = rotation[0].keyframe_points[0].co.y
            x0 = rotation[1].keyframe_points[0].co.y
            y0 = rotation[2].keyframe_points[0].co.y
            z0 = rotation[3].keyframe_points[0].co.y
            clip_rest = Quaternion((w0, x0, y0, z0))
            if clip_rest.magnitude < 1e-8:
                continue
            clip_rest.normalize()
            delta = mesh_rest @ clip_rest.inverted()
        except Exception:
            continue
        for i in range(len(rotation[0].keyframe_points)):
            def retarget_rotkey(kval, i=i, delta=delta):
                wk = getattr(rotation[0].keyframe_points[i], kval)
                xk = getattr(rotation[1].keyframe_points[i], kval)
                yk = getattr(rotation[2].keyframe_points[i], kval)
                zk = getattr(rotation[3].keyframe_points[i], kval)
                q = Quaternion((wk.y, xk.y, yk.y, zk.y))
                q = delta @ q
                (wk.y, xk.y, yk.y, zk.y) = q
            retarget_rotkey("co")
            retarget_rotkey("handle_left")
            retarget_rotkey("handle_right")
        try:
            print("INFO: Rebased retargeted rotation onto mesh bind (%s)"
                  % (getattr(muobj, "path", "?"),))
        except Exception:
            pass
    # MuAnimation component metadata (autoPlay + selected clip name)
    mu_anim = getattr(host, "animation", None) if host is not None else None
    auto_play = 0
    selected_clip = ""
    if mu_anim is not None:
        try:
            auto_play = int(bool(getattr(mu_anim, "autoPlay", False)))
        except Exception:
            auto_play = 0
        try:
            selected_clip = str(getattr(mu_anim, "clip", "") or "")
        except Exception:
            selected_clip = ""
    host_bobj = getattr(host, "bobj", None) if host is not None else None
    if host_bobj is not None:
        try:
            host_bobj["mu_animation_autoplay"] = auto_play
            host_bobj["mu_animation_clip"] = selected_clip
            host_bobj["mu_animation_host"] = path
        except Exception:
            pass

    wrap_mode = 1
    try:
        wrap_mode = int(getattr(clip, "wrapMode", 1))
    except Exception:
        wrap_mode = 1
    if wrap_mode == 0:  # Unity Default → Once for UI / NLA
        wrap_mode = 1
    # Only legal Unity clip wrap modes; anything else (e.g. stream corruption
    # from a previous bad export) falls back to Once so we do not bake Ping-Pong
    # onto every clip and destroy keys.
    if wrap_mode not in (1, 2, 4, 8):
        wrap_mode = 1

    # Registry for a single compact console line at end of import
    try:
        MU_IMPORT_CLIPS.append({
            "name": str(clip.name),
            "auto_play": int(auto_play),
            "wrap": int(wrap_mode),
            "host": str(path or ""),
        })
    except Exception:
        pass

    # When every curve was skipped (missing targets, empty keys, unsupported
    # props) the panel still needs a tagged Action so mutate/export can round-
    # trip clip name + wrap + autoPlay (Combined / LR87 / Viking Propulsion).
    if not actions:
        holder = host_bobj
        if holder is None and host is not None:
            holder = getattr(host, "bobj", None)
        if holder is None:
            try:
                holder = _ensure_anim_object_host(mu, path or "", host)
            except Exception:
                holder = None
        if holder is not None:
            try:
                act = bpy.data.actions.new(str(clip.name or "clip") or "clip")
                actions["__meta__/" + str(clip.name or "clip")] = act, holder
            except Exception:
                pass

    # Drop Actions that ended up with zero fcurves when the clip already has
    # real curves. A failed create_fcurve after actpath allocation left empty
    # NLA rows that inflated Clips= on first import and vanished on reimport
    # (GeminiInt2 9→8 with Curves=17 stable). Keep a lone meta Action (LR87).
    try:
        from ..utils.action_compat import count_action_fcurves as _ncurves
    except Exception:
        def _ncurves(a):
            try:
                return len(list(a.fcurves))
            except Exception:
                return 0
    nonempty = {
        k: (a, o) for k, (a, o) in actions.items()
        if a is not None and int(_ncurves(a) or 0) > 0
    }
    if nonempty:
        # Remove empty Actions from bpy so they do not linger in the .blend
        for k, (a, o) in list(actions.items()):
            if k in nonempty:
                continue
            try:
                bpy.data.actions.remove(a)
            except Exception:
                pass
        actions = nonempty

    clip_len = 0.0
    try:
        clip_len = float(actions_clip_length([a for a, _o in actions.values()]) or 0)
    except Exception:
        clip_len = 0.0

    for name in actions:
        act, obj = actions[name]
        # Resolve live Object (Empty may have been replaced by LIGHT mid-loop)
        try:
            _ = obj.name
            _ = obj.animation_data
        except ReferenceError:
            fixed = None
            try:
                bname = act.get("mu_nla_owner") or act.get("mu_anim_bobj")
                if bname:
                    fixed = bpy.data.objects.get(str(bname))
            except Exception:
                fixed = None
            if fixed is None and host is not None:
                fixed = getattr(host, "bobj", None)
            if fixed is None:
                print("WARNING: skip NLA push — owner Object was removed (%r)" % (name,))
                continue
            obj = fixed
            actions[name] = act, obj
        except Exception:
            # Not an Object (e.g. leftover Light datablock) — try host / muobj
            fixed = None
            if host is not None:
                fixed = getattr(host, "bobj", None)
            if fixed is None:
                try:
                    fixed = bpy.data.objects.get(str(getattr(obj, "name", "") or ""))
                except Exception:
                    fixed = None
            if fixed is None:
                print("WARNING: skip NLA push — no Object owner (%r)" % (name,))
                continue
            obj = fixed
            actions[name] = act, obj
        # Remember which Mu hierarchy node owned this Animation component so
        # export can restore multiple MuAnimation hosts (nested clips).
        try:
            act["mu_anim_host"] = path
            act["mu_clip_name"] = clip.name
            try:
                import_id = str(getattr(mu, "import_id", "") or "")
                if import_id:
                    act["mu_import_id"] = import_id
            except Exception:
                pass
            # Isolated per Action — never shared across clips/hosts
            wm = int(wrap_mode)
            if wm == 0:
                wm = 1
            if wm not in (1, 2, 4, 8):
                wm = 1
            act["mu_clip_wrap_mode"] = wm
            act["mu_auto_play"] = int(auto_play)
            act["mu_import_gen"] = int(MU_IMPORT_GENERATION)
            if clip_len > 0:
                act["mu_clip_length"] = clip_len
            if selected_clip:
                act["mu_animation_clip"] = selected_clip
        except Exception:
            pass
        # Unique Blender object name — required when siblings share a Unity
        # path (RCSBlock Angled×4 RCSthruster). Export groups by this.
        try:
            bobj = getattr(host, "bobj", None) if host is not None else None
            if bobj is not None and getattr(bobj, "name", None):
                act["mu_anim_bobj"] = bobj.name
        except Exception:
            pass
        try:
            act["mu_nla_owner"] = obj.name
        except Exception:
            pass
        track, strip = push_action_to_nla(obj, act, clip.name)
        if strip is not None:
            apply_mu_clip_wrap_to_strip(strip, wrap_mode)
        # Re-assert wrap after apply (Ping-Pong bake must not alter stored mode)
        try:
            wm = int(wrap_mode)
            if wm == 0:
                wm = 1
            if wm not in (1, 2, 4, 8):
                wm = 1
            act["mu_clip_wrap_mode"] = wm
        except Exception:
            pass
        # NlaTrack may not support IDProperties (Blender 5); Action holds host.

def create_object_paths(mu):
    # New import batch — reset console summary registry
    global MU_IMPORT_CLIPS, MU_IMPORT_GENERATION
    MU_IMPORT_CLIPS = []
    MU_IMPORT_GENERATION += 1

    def recurse (mu, obj, parent_names, parent):
        obj.parent = parent
        obj.mu = mu
        name = obj.transform.name
        parent_names.append(name)
        obj.path = "/".join(parent_names)
        mu.objects[name] = obj
        mu.object_paths[obj.path] = obj
        for child in obj.children:
            recurse(mu, child, parent_names, obj)
        parent_names.pop()
    mu.objects = {}
    mu.object_paths = {}
    mu.bad_paths = set()
    recurse(mu, mu.obj, [], None)

def _preview_clip_score(name):
    """Lower = better default viewport clip (stowed / closed pose).

    KSP often ships Deploy then Running/Drill/Grab. NLA push order is not
    reliable (MiniDrill pushes Drill before Deploy), so prefer deploy/extend
    over operate / grab / glow clips.
    """
    n = (name or "").lower().replace(" ", "_")
    if any(k in n for k in ("deploy", "extend", "retract", "unfold", "open", "close")):
        return 0
    if any(k in n for k in ("glow", "heat", "emissive", "light", "noozle", "nozzle")):
        return 1
    if "servo" in n or n in ("servooperate", "servo_operate"):
        return 2
    if any(k in n for k in ("grab", "operate", "running", "spin", "rotate", "loop")):
        return 3
    # Bare "Drill" / "*_drill" without deploy → treat as secondary (operate/FX)
    if n == "drill" or n.endswith("_drill") or n.startswith("drill_"):
        return 3
    return 1


def ordered_clip_names(names):
    """Stable Deploy → glow/heat → operate/grab order for GIF / NLA playback."""
    uniq = []
    seen = set()
    for n in names:
        if not n or n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return sorted(uniq, key=lambda n: (_preview_clip_score(n), uniq.index(n)))


def _mu_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default


def _import_id_for_generation(gen):
    for act in bpy.data.actions:
        try:
            if int(act.get("mu_import_gen", -1)) != int(gen):
                continue
        except Exception:
            continue
        try:
            iid = str(act.get("mu_import_id") or "")
            if iid:
                return iid
        except Exception:
            pass
    return ""


def _collect_entries_for_generation(gen, import_id=""):
    """Build panel-style entry rows from Actions tagged with mu_import_gen."""
    try:
        from ..mu_browser.panels import _is_preview_action
    except Exception:
        _is_preview_action = None
    entries = []
    seen = set()
    for act in bpy.data.actions:
        try:
            if int(act.get("mu_import_gen", -1)) != int(gen):
                continue
        except Exception:
            continue
        if _is_preview_action is not None:
            try:
                if _is_preview_action(act):
                    continue
            except Exception:
                pass
        if import_id:
            try:
                aid = str(act.get("mu_import_id") or "")
            except Exception:
                aid = ""
            if aid and aid != str(import_id):
                continue
        try:
            ptr = act.as_pointer()
        except Exception:
            ptr = id(act)
        if ptr in seen:
            continue
        seen.add(ptr)
        owner = ""
        try:
            owner = str(act.get("mu_nla_owner") or act.get("mu_anim_bobj") or "")
        except Exception:
            owner = ""
        try:
            clip_name = str(act.get("mu_clip_name") or act.name or "?")
        except Exception:
            clip_name = act.name or "?"
        try:
            wrap = int(act.get("mu_clip_wrap_mode", 1) or 1)
        except Exception:
            wrap = 1
        try:
            autoplay = bool(int(act.get("mu_auto_play", 0) or 0))
        except Exception:
            autoplay = False
        try:
            anim_host = str(act.get("mu_anim_host") or "")
        except Exception:
            anim_host = ""
        try:
            anim_bobj = str(act.get("mu_anim_bobj") or "")
        except Exception:
            anim_bobj = ""
        entries.append({
            "action": act,
            "clip_name": clip_name,
            "owner": owner,
            "wrap": wrap,
            "autoplay": autoplay,
            "anim_host": anim_host,
            "anim_bobj": anim_bobj,
        })
    return entries


def _summary_entries_for_generation(gen):
    """Same Action rows as the MU Animation panel (preview / FX filtered)."""
    try:
        from ..mu_browser.panels import collect_mu_animation_entries_by_import_id
    except Exception:
        collect_mu_animation_entries_by_import_id = None

    import_id = _import_id_for_generation(gen)
    entries = []
    if collect_mu_animation_entries_by_import_id is not None and import_id:
        entries = collect_mu_animation_entries_by_import_id(import_id)
    if not entries:
        entries = _collect_entries_for_generation(gen, import_id)
    return entries, import_id


def _entry_curve_wrap_name(act):
    """Dominant MuCurve wrap for one Action (``Mixed`` if curves disagree)."""
    try:
        from ..mu_browser.panels import _curve_wrap_of_action
        cw = int(_curve_wrap_of_action(act))
    except Exception:
        cw = 8
    if cw == 0:
        return "Mixed"
    return mu_wrap_name(cw)


def _stats_from_entries(entries, import_id=""):
    """Panel header counts from the same entry list the INFO tail uses."""
    try:
        from ..mu_browser.panels import mu_animation_entry_stats
    except Exception:
        mu_animation_entry_stats = None
    if mu_animation_entry_stats is not None and entries:
        return mu_animation_entry_stats(entries, import_id)

    host_keys = set()
    clip_rows = len(entries)
    curve_count = 0
    for ent in entries:
        act = ent.get("action")
        owner = ent.get("owner") or ""
        try:
            from ..mu_browser.panels import _host_key_of_action
            host_keys.add(_host_key_of_action(act, owner))
        except Exception:
            pass
        if act is not None:
            try:
                curve_count += int(count_action_fcurves(act))
            except Exception:
                pass
    roots = 0
    if import_id:
        try:
            from ..mu_browser.panels import _count_import_roots
            roots = _count_import_roots(import_id)
        except Exception:
            roots = 0
    if roots == 0 and host_keys:
        roots = 1
    return roots, len(host_keys), clip_rows, curve_count


def _summary_stats_for_generation(gen):
    """Same rules as MU Animation panel (mu_animation_entry_stats)."""
    entries, import_id = _summary_entries_for_generation(gen)
    return _stats_from_entries(entries, import_id)


def _summary_host_label(ent):
    from ..utils import strip_nnn
    def _clean(name):
        name = str(name or "")
        if not name:
            return ""
        try:
            return strip_nnn(name) or name
        except Exception:
            return name
    # Prefer authored Unity host path leaf (stable across export rename)
    path = str(ent.get("anim_host") or "")
    if path:
        leaf = _clean(path.rstrip("/").split("/")[-1])
        if leaf:
            return leaf
    bobj = _clean(ent.get("anim_bobj") or "")
    if bobj:
        return bobj
    return _clean(ent.get("owner") or "") or "host"


def _classify_fcurve_data_path(data_path):
    """Return one of: 'xf' | 'mat' | 'lit' | 'aud' | 'bone' | 'other'."""
    dp = (data_path or "").strip()
    if not dp:
        return "other"
    if "mu_audio_" in dp:
        return "aud"
    if dp.startswith("mumatprop.") or ".mumatprop." in dp:
        return "mat"
    if dp.startswith("pose.bones"):
        return "bone"
    # Light datablock paths (energy / color) or Object-space data.* / enabled
    if (dp in ("energy", "color") or dp.startswith("color")
            or dp.startswith("data.energy") or dp.startswith("data.color")
            or "mu_light_enabled" in dp):
        return "lit"
    # Transform on Object
    if dp in ("location", "rotation_quaternion", "rotation_euler", "scale"):
        return "xf"
    return "other"


def _curve_type_counts_from_entries(entries):
    """Count fcurves by Mu/Unity channel class across panel entries."""
    from collections import Counter
    from ..utils.action_compat import iter_action_fcurves
    counts = Counter()
    for ent in entries:
        act = ent.get("action")
        if act is None:
            continue
        try:
            for fc in iter_action_fcurves(act):
                if fc is None:
                    continue
                counts[_classify_fcurve_data_path(getattr(fc, "data_path", "") or "")] += 1
        except Exception:
            pass
    return counts


def _preview_counts_for_import_id(import_id):
    """Viewport-only preview Actions (not written to .mu)."""
    fx = lit = rob = 0
    if not import_id:
        return fx, lit, rob
    try:
        from ..mu_browser.panels import (
            collect_mu_preview_entries_by_import_id,
            _preview_section_of,
        )
        for ent in collect_mu_preview_entries_by_import_id(import_id) or []:
            sec = _preview_section_of(ent)
            if sec == "lights":
                lit += 1
            elif sec == "robotics":
                rob += 1
            else:
                fx += 1
    except Exception:
        pass
    return fx, lit, rob


def format_mu_animation_summary(gen=None, include_preview=True):
    """Compact INFO one-liner for panel rows + AP / clip wrap / curve wrap.

    Header (MuAnimation round-trip contract):
      Roots= Hosts= Clips= Curves= Xf= Mat= Lit= Aud= [Bone=]
    Optional second field (viewport only, not in .mu):
      FX= LitP= Rob=
    Tail: host.clip AP=… WM=… CW=… (stacked =N)
    """
    from collections import OrderedDict

    if gen is None:
        gen = int(MU_IMPORT_GENERATION)
    entries, import_id = _summary_entries_for_generation(gen)
    n_roots, n_hosts, n_clips, n_curves = _stats_from_entries(entries, import_id)
    type_counts = _curve_type_counts_from_entries(entries)
    n_xf = int(type_counts.get("xf", 0) + type_counts.get("bone", 0))
    n_mat = int(type_counts.get("mat", 0))
    n_lit = int(type_counts.get("lit", 0))
    n_aud = int(type_counts.get("aud", 0))
    # Keep Bone visible only when non-zero (armatures); otherwise fold into Xf
    n_bone = int(type_counts.get("bone", 0))

    stacked = OrderedDict()

    def _stack(host, clip, ap, wm, cw):
        key = (host, clip, ap, wm, cw)
        stacked[key] = stacked.get(key, 0) + 1

    for ent in entries:
        act = ent.get("action")
        host = _summary_host_label(ent)
        clip = str(ent.get("clip_name") or "?")
        ap = "yes" if ent.get("autoplay") else "no"
        try:
            wm = mu_wrap_name(int(ent.get("wrap") or 1))
        except Exception:
            wm = "?"
        _stack(host, clip, ap, wm, _entry_curve_wrap_name(act))

    if not stacked:
        for c in list(MU_IMPORT_CLIPS):
            host = _summary_host_label({
                "anim_host": c.get("host") or "",
                "anim_bobj": "",
                "owner": "",
            })
            clip = str(c.get("name") or "?")
            ap = "yes" if c.get("auto_play") else "no"
            wm = mu_wrap_name(int(c.get("wrap") or 1))
            _stack(host, clip, ap, wm, "Clamp")

    parts = []
    for (host, clip, ap, wm, cw), n in stacked.items():
        label = "%s.%s" % (host, clip)
        if n > 1:
            label = "%s=%d" % (label, n)
        parts.append("%s AP=%s WM=%s CW=%s" % (label, ap, wm, cw))

    # MuAnimation contract (must survive .mu round-trip)
    prefix = (
        "INFO: Roots=%d Hosts=%d Clips=%d Curves=%d Xf=%d Mat=%d Lit=%d Aud=%d"
        % (n_roots, n_hosts, n_clips, n_curves, n_xf, n_mat, n_lit, n_aud)
    )
    if n_bone:
        # Bone channels are already in Xf; optional explicit tag for debugging
        prefix = "%s Bone=%d" % (prefix, n_bone)

    # Viewport previews (never written to .mu) — ignored by roundtrip test
    if include_preview and import_id:
        fx, lit_p, rob = _preview_counts_for_import_id(import_id)
        if fx or lit_p or rob:
            prefix = "%s | FX=%d LitP=%d Rob=%d" % (prefix, fx, lit_p, rob)

    if not parts:
        return prefix
    return "%s | %s" % (prefix, " | ".join(parts))


def print_mu_animation_summary(force=False):
    """Print ``format_mu_animation_summary`` once per import generation."""
    global _MU_SUMMARY_DONE_GEN
    if not force:
        return
    try:
        gen = int(MU_IMPORT_GENERATION)
        if gen == int(_MU_SUMMARY_DONE_GEN):
            return
        print(format_mu_animation_summary(gen))
        _MU_SUMMARY_DONE_GEN = gen
    except Exception as e:
        print("WARN: MU anim summary failed: %s" % (e,))


def _nla_belongs_to_gen(id_data, gen):
    """True if this object/material has an NLA Action from this import batch."""
    ad = getattr(id_data, "animation_data", None)
    if not ad:
        return False
    try:
        tracks = list(ad.nla_tracks)
    except Exception:
        tracks = []
    for track in tracks:
        try:
            strips = list(track.strips)
        except Exception:
            strips = []
        for strip in strips:
            act = getattr(strip, "action", None)
            if act is None:
                continue
            try:
                if int(act.get("mu_import_gen", -1)) == int(gen):
                    return True
            except Exception:
                continue
    return False


def _import_has_autoplay(gen):
    """Auto Play only for the .mu just imported — not leftovers in the scene."""
    gen = int(gen)
    for act in bpy.data.actions:
        try:
            if int(act.get("mu_import_gen", -1)) != gen:
                continue
        except Exception:
            continue
        if _mu_int(act.get("mu_auto_play", 0), 0):
            return True
        try:
            bname = act.get("mu_anim_bobj")
            if bname:
                bobj = bpy.data.objects.get(str(bname))
                if bobj is not None and _mu_int(
                        bobj.get("mu_animation_autoplay", 0), 0):
                    return True
        except Exception:
            pass
    for rec in list(MU_IMPORT_CLIPS):
        if _mu_int(rec.get("auto_play", 0), 0):
            return True
    return False


def finalize_animation_preview():
    """Blender 5 keeps the last pushed Action as ``ad.action``.

    Clear the active Action and unmute the best preview clip. Prefer the
    MuAnimation selected clip when autoPlay is set, otherwise Deploy/stowed
    heuristic. Mute the rest (e.g. Drill_Running).

    Playback starts only when THIS import has Auto Play. A later import
    without Auto Play must not unpause the timeline (or re-mute older NLA).
    """
    global _MU_PLAY_TIMER_GEN
    try:
        gen = int(MU_IMPORT_GENERATION)
    except Exception:
        gen = 0
    has_autoplay = _import_has_autoplay(gen)
    try:
        from ..tools.display import animations_are_off
        if animations_are_off():
            has_autoplay = False
    except Exception:
        pass

    if has_autoplay:
        try:
            bpy.context.scene.frame_set(int(bpy.context.scene.frame_start))
        except Exception:
            pass

    def _finalize(id_data):
        if not _nla_belongs_to_gen(id_data, gen):
            return
        ad = getattr(id_data, "animation_data", None)
        if not ad or not ad.nla_tracks:
            return
        names = [t.name for t in ad.nla_tracks if t.name]
        if not names:
            return
        # Prefer MuAnimation selected clip / autoPlay when present
        keep = None
        autoplay_clip = None
        component_clip = None
        for track in ad.nla_tracks:
            for strip in track.strips:
                act = strip.action
                if act is None:
                    continue
                cname = act.get("mu_clip_name", track.name)
                if act.get("mu_animation_clip"):
                    component_clip = str(act["mu_animation_clip"])
                ap = int(act.get("mu_auto_play", 0) or 0)
                if not ap:
                    try:
                        bname = act.get("mu_anim_bobj")
                        if bname:
                            bobj = bpy.data.objects.get(str(bname))
                            if bobj is not None:
                                ap = int(bobj.get("mu_animation_autoplay", 0) or 0)
                    except Exception:
                        ap = 0
                if ap:
                    autoplay_clip = cname
        if autoplay_clip and autoplay_clip in names:
            keep = autoplay_clip
        elif component_clip and component_clip in names:
            keep = component_clip
        if not keep:
            keep = ordered_clip_names(names)[0]
        for track in ad.nla_tracks:
            track.mute = (track.name != keep)
        try:
            ad.action = None
        except Exception:
            pass
        try:
            if hasattr(ad, "use_nla"):
                ad.use_nla = True
        except Exception:
            pass

    for obj in bpy.data.objects:
        _finalize(obj)
    for mat in bpy.data.materials:
        _finalize(mat)

    try:
        from ..tools.display import animations_are_off, apply_animations_off
        if animations_are_off():
            apply_animations_off(bpy.context.scene, True)
            _MU_PLAY_TIMER_GEN = -1
            has_autoplay = False
    except Exception:
        pass

    if has_autoplay:
        _MU_PLAY_TIMER_GEN = gen

        def _start_animation():
            # A newer import (or one without Auto Play) cancels this start.
            if int(_MU_PLAY_TIMER_GEN) != gen:
                return None
            try:
                for window in bpy.context.window_manager.windows:
                    screen = window.screen
                    if screen is None:
                        continue
                    with bpy.context.temp_override(window=window, screen=screen):
                        if not screen.is_animation_playing:
                            bpy.ops.screen.animation_play()
                        return None
            except Exception as e:
                print(f"WARNING: Could not start MU Auto Play: {e}")
            return None
        try:
            bpy.app.timers.register(_start_animation, first_interval=0.25)
        except Exception:
            pass
    else:
        # Do not let a pending Auto Play timer from the previous .mu unpause.
        _MU_PLAY_TIMER_GEN = -1
    # Engine / heat: restore EmissionMap (undo white-bypass) + soft blackbody
    try:
        from ..shader.shader import (
            ensure_heat_emissive_map_visible,
            enhance_heat_blackbody_preview,
        )
    except Exception:
        ensure_heat_emissive_map_visible = None
        enhance_heat_blackbody_preview = None
    if ensure_heat_emissive_map_visible:
        for mat in bpy.data.materials:
            ad = getattr(mat, "animation_data", None)
            if not ad or not ad.nla_tracks:
                continue
            heatish = False
            for track in ad.nla_tracks:
                n = (track.name or "").lower()
                if any(k in n for k in ("heat", "emissive", "glow", "noozle", "nozzle")):
                    heatish = True
                    break
            if not heatish:
                continue
            try:
                ensure_heat_emissive_map_visible(mat)
            except Exception:
                pass
            if enhance_heat_blackbody_preview:
                try:
                    enhance_heat_blackbody_preview(mat)
                except Exception:
                    pass

    # Console summary runs from import_mu after _tag_import_objects (needs mu_import_id).
