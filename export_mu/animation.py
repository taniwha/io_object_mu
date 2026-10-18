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
from math import pi
from mathutils import Vector, Quaternion

from ..mu import MuAnimation, MuClip, MuCurve, MuKey
from ..utils import strip_nnn, normalize_mu_curve_path, unity_export_name
from ..utils.action_compat import iter_action_fcurves, get_mu_curve_wrap, iter_export_keyframes, read_mu_clip_wrap, restore_all_pingpong_for_export

from .light import light_types, light_power

# Inverse of import_mu.animation.tau (degrees <-> radians for Euler curves)
_rad2deg = -180.0 / pi

def _mumatprop_data_path(data_path):
    """Return data_path starting at mumatprop…, stripping pose.bones[] if present."""
    if not data_path:
        return None
    if data_path.startswith("mumatprop."):
        return data_path
    marker = ".mumatprop."
    if marker in data_path:
        # Legacy bad imports: pose.bones["X"].mumatprop...
        return "mumatprop." + data_path.split(marker, 1)[1]
    return None

def _action_has_mumatprop(action):
    for curve in iter_action_fcurves(action):
        dp_full = _mumatprop_data_path(curve.data_path)
        if not dp_full:
            continue
        dp = dp_full.split(".")
        if len(dp) > 1 and dp[1] in ["color", "vector", "float2", "float3",
                                       "texture"]:
            return True
    return False

def _is_fx_preview_anim(action_or_track):
    """Viewport-only particle/FX Actions must not round-trip into .mu clips."""
    if action_or_track is None:
        return False
    try:
        if action_or_track.get("mu_fx_preview"):
            return True
    except Exception:
        pass
    try:
        if action_or_track.get("mu_color_changer_preview"):
            return True
    except Exception:
        pass
    try:
        name = getattr(action_or_track, "name", "") or ""
        if name.endswith(".fx_preview") or name.startswith("mu_fx_"):
            return True
        if name.startswith("ColorChangerLights"):
            return True
    except Exception:
        pass
    return False


def shader_animations(mat, path):
    animations = {}
    if not mat.animation_data:
        return animations
    seen = set()

    def add_track(track_or_action, clip_name):
        action = track_or_action
        if not isinstance(action, bpy.types.Action):
            if _is_fx_preview_anim(track_or_action):
                return
            if not getattr(track_or_action, "strips", None):
                return
            action = track_or_action.strips[0].action
        if not action or not _action_has_mumatprop(action):
            return
        if _is_fx_preview_anim(action):
            return
        # Shared materials are visited once per mesh user — dedupe Actions
        key = action.as_pointer()
        if key in seen:
            return
        seen.add(key)
        # Prefer Mu clip name stored at import
        name = clip_name
        try:
            if "mu_clip_name" in action and action["mu_clip_name"]:
                name = action["mu_clip_name"]
        except Exception:
            pass
        dkey = _clip_dict_key(name, path, action)
        if dkey not in animations:
            animations[dkey] = []
        animations[dkey].append((track_or_action, path, mat))

    for track in mat.animation_data.nla_tracks:
        add_track(track, track.name)
    # Also pick up an action assigned directly (no NLA)
    if mat.animation_data.action:
        act = mat.animation_data.action
        clip = act.get("mu_clip_name") if hasattr(act, "get") else None
        add_track(act, clip or act.name)
    return animations

def _clip_dict_key(clip_name, path, action=None):
    """Unique dict key so sibling hosts sharing a clip name stay separate.

    MuClip.name written to .mu is still the plain clip_name; the suffix is
    only used while collecting/exporting so wrapMode cannot bleed across
    orange-empty hosts (four antennas all named \"antenna\").
    """
    host_tag = ""
    if action is not None:
        try:
            host_tag = (action.get("mu_anim_bobj")
                        or action.get("mu_nla_owner")
                        or action.get("mu_anim_host")
                        or "")
        except Exception:
            host_tag = ""
        if not host_tag:
            try:
                if "mu_anim_bobj" in action:
                    host_tag = action["mu_anim_bobj"]
                elif "mu_nla_owner" in action:
                    host_tag = action["mu_nla_owner"]
                elif "mu_anim_host" in action:
                    host_tag = action["mu_anim_host"]
            except Exception:
                pass
    if not host_tag:
        host_tag = path or ""
    # Action pointer makes the key unique even when tags are missing/duplicate
    ap = ""
    try:
        if action is not None:
            ap = str(action.as_pointer())
    except Exception:
        pass
    return "%s\x00%s\x00%s" % (clip_name, host_tag, ap)


def _clip_name_from_key(key):
    """Extract the real MuClip name from a composite collection key."""
    if not key:
        return key
    if "\x00" in key:
        return key.split("\x00", 1)[0]
    return key


def _host_autoplay_from_animations(animations, anim_root=""):
    """Read MuAnimation.autoPlay from the Animation GO (per-host, not per-clip).

    Sibling hosts may share an identical clip name but differ in autoPlay.
    The host empty's ``mu_animation_autoplay`` is authoritative after UI edits.
    Prefer the object whose ``mu_animation_host`` matches this anim_root so a
    leftover flag on an animated child cannot flip the host.
    """
    root_leaf = ""
    if anim_root:
        root_leaf = strip_nnn(str(anim_root).rstrip("/").split("/")[-1])
    best = None  # (score, autoplay)
    seen_bobjs = set()
    for entries in animations.values():
        for data in entries:
            track, _path, _typ = data
            action = track if isinstance(track, bpy.types.Action) else None
            if action is None and not isinstance(track, bpy.types.Action):
                try:
                    strips = getattr(track, "strips", None)
                    action = strips[0].action if strips else None
                except Exception:
                    action = None
            if action is None:
                continue
            bname = None
            try:
                bname = action.get("mu_anim_bobj") or action.get("mu_nla_owner")
            except Exception:
                bname = None
            if not bname:
                continue
            bname = str(bname)
            if bname in seen_bobjs:
                continue
            seen_bobjs.add(bname)
            try:
                bobj = bpy.data.objects.get(bname)
                if bobj is None or "mu_animation_autoplay" not in bobj:
                    continue
                ap = bool(int(bobj.get("mu_animation_autoplay", 0) or 0))
                tagged = ""
                try:
                    tagged = str(bobj.get("mu_animation_host") or "")
                except Exception:
                    tagged = ""
                score = 1
                if anim_root and tagged == anim_root:
                    score = 3
                elif tagged:
                    score = 2
                elif root_leaf and strip_nnn(bobj.name) == root_leaf:
                    score = 2
                if best is None or score > best[0]:
                    best = (score, ap)
            except Exception:
                pass
    if best is not None:
        return best[1]
    # Hosts without an orange empty (eg. S6_SAW/Root P6_unlock) only store AP on Actions.
    action_votes = []
    for entries in animations.values():
        for data in entries:
            track, _path, _typ = data
            action = track if isinstance(track, bpy.types.Action) else None
            if action is None and not isinstance(track, bpy.types.Action):
                try:
                    strips = getattr(track, "strips", None)
                    action = strips[0].action if strips else None
                except Exception:
                    action = None
            if action is None or "mu_auto_play" not in action:
                continue
            try:
                tagged = str(action.get("mu_anim_host") or "")
            except Exception:
                tagged = ""
            if anim_root and tagged and tagged != anim_root:
                continue
            try:
                action_votes.append(bool(int(action.get("mu_auto_play", 0) or 0)))
            except Exception:
                pass
    if action_votes:
        from collections import Counter
        return bool(Counter(action_votes).most_common(1)[0][0])
    return None


def _merge_entries_by_clip_name(animations):
    """One MuClip per Unity clip name (host groups are already split).

    Import creates one Blender Action per animated target; those must round-trip
    as a single MuClip or KSP ``animationName = airlock`` sees duplicates.
    """
    merged = {}
    for dict_key, entries in animations.items():
        clip_name = _clip_name_from_key(dict_key)
        if clip_name not in merged:
            merged[clip_name] = []
        merged[clip_name].extend(entries)
    return merged


def object_animations(obj, path):
    animations = {}
    typ = "obj"
    if type(obj) in light_types:
        typ = "lit"
    elif type(obj.data) == bpy.types.Armature:
        #print(obj.name)
        typ = "arm"
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:
            if _is_fx_preview_anim(track):
                continue
            if track.strips:
                # Multiple NLA tracks can share a clip name (one Action per
                # animated target created at import). Collect ALL of them —
                # keyed by (clip_name, host, action) so siblings stay separate.
                strip_act = track.strips[0].action
                if _is_fx_preview_anim(strip_act):
                    continue
                key = _clip_dict_key(track.name, path, strip_act)
                if key not in animations:
                    animations[key] = []
                animations[key].append((track, path, typ))
        # if nla_tracks exist, then action will be an nla track that has been
        # opened for tweaking, so export action only if there are no nla tracks
        if not animations and obj.animation_data.action:
            action = obj.animation_data.action
            if not _is_fx_preview_anim(action):
                key = _clip_dict_key(action.name, path, action)
                animations[key] = [(action, path, typ)]
    return animations

def extend_animations(animations, anims):
    for a in anims:
        if a not in animations:
            animations[a] = []
        animations[a].extend(anims[a])

def _mu_export_path(obj, parent_path):
    """Build the hierarchy path as it will appear in the exported .mu.

    bindPose armatures collapse to their base name; *.skin meshes are folded
    into that same MuObject — keep the parent path so material clips resolve.
    """
    from .armature import is_bindpose_armature, bindpose_base_name
    name = unity_export_name(obj)
    if type(obj.data) == bpy.types.Armature and is_bindpose_armature(obj):
        seg = bindpose_base_name(obj)
    elif (name.endswith(".skin") and obj.parent
          and type(getattr(obj.parent, "data", None)) == bpy.types.Armature
          and is_bindpose_armature(obj.parent)):
        return parent_path
    else:
        seg = name
    if parent_path:
        return parent_path + "/" + seg
    return seg

def bindpose_object_animations(obj, path):
    """Object-space Mu clips on bindPose NLA (OuterSleeve sleeves, TriBitDrill bone clips).

    Any Action on bindPose that belongs to a MuClip (has mu_clip_name or mu_anim_host)
    is exported as object-space, because bindPose is not a control armature.
    """
    animations = {}
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return animations
    for track in ad.nla_tracks:
        if _is_fx_preview_anim(track):
            continue
        if not track.strips:
            continue
        strip_act = track.strips[0].action
        if _is_fx_preview_anim(strip_act):
            continue
        try:
            if not (strip_act.get("mu_clip_name") or strip_act.get("mu_anim_host")):
                continue
        except Exception:
            continue
        # All Actions on bindPose that are Mu clips are exported as object-space
        try:
            curve_path = strip_act.get("mu_unity_curve_path") or path
            if curve_path is not None:
                curve_path = str(curve_path)
        except Exception:
            curve_path = path
        key = _clip_dict_key(track.name, curve_path, strip_act)
        if key not in animations:
            animations[key] = []
        animations[key].append((track, curve_path, "obj"))
    return animations


def collect_animations(obj, path=""):
    from .armature import is_bindpose_armature
    animations = {}
    # Anim stubs are not written to the .mu hierarchy, but their NLA must still
    # export with the original Unity curve paths (ladder-2 orphan targets etc.).
    try:
        if obj.get("mu_anim_stub"):
            extend_animations(
                animations, stub_object_animations(obj, path))
            for o in obj.children:
                # Children of a stub keep the Unity-relative path context —
                # do not append the stub's Blender name into the hierarchy path.
                extend_animations(animations, collect_animations(o, path))
            return animations
    except Exception:
        pass
    path = _mu_export_path(obj, path)
    if type(obj.data) == bpy.types.Armature and is_bindpose_armature(obj):
        extend_animations(animations, bindpose_object_animations(obj, path))
    else:
        extend_animations(animations, object_animations(obj, path))
    if type(obj.data) == bpy.types.Mesh:
        for mat in obj.data.materials:
            if mat:  # material slot may be empty
                extend_animations(animations, shader_animations(mat, path))
    if type(obj.data) in light_types:
        extend_animations(animations, object_animations(obj.data, path))
    for o in obj.children:
        extend_animations(animations, collect_animations(o, path))
    return animations


def stub_object_animations(obj, path):
    """Export NLA on mu_anim_stub empties using stored Unity curve paths.

    ``object_animations`` would pass the parent hierarchy path (or ""), which
    either misses ``mu_unity_curve_path`` (non-empty parent) or loses the
    orphan entirely when the stub sits outside the export tree.
    """
    animations = {}
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return animations
    for track in ad.nla_tracks:
        if _is_fx_preview_anim(track):
            continue
        if not track.strips:
            continue
        strip_act = track.strips[0].action
        if _is_fx_preview_anim(strip_act):
            continue
        try:
            curve_path = strip_act.get("mu_unity_curve_path") or path or ""
            if curve_path is not None:
                curve_path = str(curve_path)
        except Exception:
            curve_path = path or ""
        key = _clip_dict_key(track.name, curve_path, strip_act)
        if key not in animations:
            animations[key] = []
        animations[key].append((track, curve_path, "obj"))
    return animations


def collect_orphan_stub_animations(root, animations):
    """Merge NLA from top-level mu_anim_stub empties sharing this import.

    Path synthesis can leave stubs with ``parent=None`` when intermediate
    MuObjects are bone-only (TriBitDrill shake). Those never appear under
    ``collect_animations(root)``.
    """
    try:
        iid = str(root.get("mu_import_id") or "")
    except Exception:
        iid = ""
    if not iid:
        return animations
    for obj in bpy.data.objects:
        try:
            if not obj.get("mu_anim_stub"):
                continue
            if str(obj.get("mu_import_id") or "") != iid:
                continue
        except Exception:
            continue
        if obj.parent is not None:
            # Already walked via collect_animations if under root
            continue
        if obj == root:
            continue
        extend_animations(animations, stub_object_animations(obj, ""))
    return animations


def find_path_root(animations):
    paths = {}
    for clip in animations:
        for data in animations[clip]:
            objects = data[1].split("/")
            p = paths
            for o in objects:
                if not o in p:
                    p[o] = {}
                p = p[o]
            # flag the path as having animation data so that the first object
            # with animation data is found when all objects form a vine
            # instead of a tree
            p[None] = {}
    path_root = ""
    p = paths
    while len(p) == 1:
        o = list(p)[0]
        if o == None:
            break
        if path_root:
            path_root += "/"
        path_root += o
        p = p[o]
    return path_root

def make_key(key, mult):
    fps = bpy.context.scene.render.fps
    mukey = MuKey()
    x, y = key.co
    mukey.time = (x - bpy.context.scene.frame_start) / fps
    mukey.value = y * mult
    if not math.isfinite(mukey.time):
        mukey.time = 0.0
    if not math.isfinite(mukey.value):
        mukey.value = 0.0
    lx, ly = key.handle_left
    dx = (x - lx) / fps
    dy = (y - ly) * mult
    t1 = (dy / dx) if abs(dx) > 1e-12 and math.isfinite(dx) and math.isfinite(dy) else 0.0
    rx, ry = key.handle_right
    dx = (rx - x) / fps
    dy = (ry - y) * mult
    t2 = (dy / dx) if abs(dx) > 1e-12 and math.isfinite(dx) and math.isfinite(dy) else 0.0
    # Unity stepped keys / bad Blender handles → keep packable floats
    if not math.isfinite(t1) or abs(t1) > 1e6:
        t1 = 0.0
    if not math.isfinite(t2) or abs(t2) > 1e6:
        t2 = 0.0
    mukey.tangent = [t1, t2]
    mukey.tangentMode = 0
    return mukey

property_map = {
    "location":(
        ("m_LocalPosition.x", 1, 0),
        ("m_LocalPosition.z", 1, 0),
        ("m_LocalPosition.y", 1, 0),
    ),
    "rotation_quaternion":(
        ("m_LocalRotation.w", 1, 0),
        ("m_LocalRotation.x", -1, 0),
        ("m_LocalRotation.z", -1, 0),
        ("m_LocalRotation.y", -1, 0),
    ),
    "scale":(
        ("m_LocalScale.x", 1, 0),
        ("m_LocalScale.z", 1, 0),
        ("m_LocalScale.y", 1, 0),
    ),
    "color":(
        ("m_Color.r", 1, 2),
        ("m_Color.g", 1, 2),
        ("m_Color.b", 1, 2),
        ("m_Color.a", 1, 2),#probably not used
    ),
    "energy":(
        ("m_Intensity", 1/light_power, 2),
    ),
    # Object-space light curves (import keeps Action on Object, not Light DB)
    "data.color":(
        ("m_Color.r", 1, 2),
        ("m_Color.g", 1, 2),
        ("m_Color.b", 1, 2),
        ("m_Color.a", 1, 2),
    ),
    "data.energy":(
        ("m_Intensity", 1/light_power, 2),
    ),
    "rotation_euler":(
        ("localEulerAnglesRaw.x", _rad2deg, 0),
        ("localEulerAnglesRaw.z", _rad2deg, 0),
        ("localEulerAnglesRaw.y", _rad2deg, 0),
    ),
    '["mu_light_enabled"]':(
        ("m_Enabled", 1, 2),
    ),
}

def _anim_host_of(track_or_action, fallback_path):
    """Return host key for grouping MuAnimation clips.

    Prefers ``mu_anim_bobj`` (unique Blender object name) so duplicate Unity
    sibling names (RCSBlock×4 RCSthruster / antenna×4) do not collapse to
    one host. Then ``mu_anim_host`` path, then ``mu_nla_owner``, then the
    full entry path (never only the first hierarchy segment — that merged
    sibling antennas and forced a single shared wrapMode).
    Returns ``("bobj", name)`` or ``("path", path)``.
    """
    try:
        action = track_or_action
        if not isinstance(action, bpy.types.Action):
            strips = getattr(track_or_action, "strips", None)
            action = strips[0].action if strips else None
        if action is not None:
            try:
                bname = action.get("mu_anim_bobj") if hasattr(action, "get") else None
                if not bname and "mu_anim_bobj" in action:
                    bname = action["mu_anim_bobj"]
                if bname:
                    return ("bobj", str(bname))
            except Exception:
                pass
            try:
                host_path = action.get("mu_anim_host") if hasattr(action, "get") else None
                if not host_path and "mu_anim_host" in action:
                    host_path = action["mu_anim_host"]
                if host_path:
                    return ("path", str(host_path))
            except Exception:
                pass
            try:
                nla_owner = action.get("mu_nla_owner") if hasattr(action, "get") else None
                if not nla_owner and "mu_nla_owner" in action:
                    nla_owner = action["mu_nla_owner"]
                if nla_owner:
                    return ("bobj", str(nla_owner))
            except Exception:
                pass
    except (TypeError, KeyError, IndexError, AttributeError):
        pass
    # Full path — not path.split("/")[0] — so siblings stay separate hosts
    return ("path", fallback_path if fallback_path else "")


def _norm_mu_path(path):
    """Compare Unity paths ignoring Blender .NNN uniquifiers on segments."""
    parts = [strip_nnn(s) for s in str(path or "").split("/") if s]
    return "/".join(parts)


def group_animations_by_host(animations, default_root):
    """Split collected animations into per-host groups for nested MuAnimation.

    Each distinct Animation host (sibling antennas etc.) gets its own group so
    identical clip names keep independent wrapMode values.
    """
    groups = {}
    for clip_name, entries in animations.items():
        for entry in entries:
            track, path, typ = entry
            # Prefer full entry path as fallback so siblings do not share a host key
            host = _anim_host_of(track, path or default_root or "")
            if host not in groups:
                groups[host] = {}
            if clip_name not in groups[host]:
                groups[host][clip_name] = []
            groups[host][clip_name].append(entry)
    if not groups and default_root:
        groups[("path", default_root)] = animations
    return groups

vector_map={
    "color": (".r", ".g", ".b", ".a"),
    "vector": (".x", ".y", ".z", ".w"),
}

_texture_vector_suffix = {
    ("scale", 0): ".scale.x",
    ("scale", 1): ".scale.y",
    ("offset", 0): ".offset.x",
    ("offset", 1): ".offset.y",
}

def make_curve(mu, muobj, curve, path, typ, action=None, anim_root=None):
    mucurve = MuCurve()
    mucurve.path = path
    # Material curves may end up on an object NLA track — detect by data_path
    if typ in {"obj", "lit", "arm"} and curve.data_path.startswith("mumatprop."):
        return None  # collected via shader_animations instead
    if typ in {"obj", "lit"}:
        # AudioSource ID props: ["mu_audio_…"] round-trip (AT_AUDIO_SOURCE=3)
        dp = curve.data_path or ""
        if ("mu_audio_" in dp) and (dp not in property_map):
            stored = None
            if action is not None:
                try:
                    key = "mu_uprop:%s:%d" % (dp, curve.array_index)
                    if key in action:
                        stored = action[key]
                except Exception:
                    stored = None
                if not stored:
                    # Blender may normalize data_path quoting; try stripped form
                    try:
                        raw_dp = dp.strip().strip('["]')
                        key2 = "mu_uprop:%s:%d" % (raw_dp, curve.array_index)
                        if key2 in action:
                            stored = action[key2]
                        key3 = 'mu_uprop:["%s"]:%d' % (raw_dp, curve.array_index)
                        if not stored and key3 in action:
                            stored = action[key3]
                    except Exception:
                        pass
            if not stored:
                # Reconstruct Unity name from mu_audio_<name>
                raw = (dp or "").strip().strip('["]')
                if raw.startswith("mu_audio_"):
                    stored = raw[len("mu_audio_"):]
                else:
                    return None
            property = str(stored)
            mult = 1
            ctyp = 3
            mucurve.path = path
            mucurve.property = property
            mucurve.type = ctyp
            wm = get_mu_curve_wrap(action, curve) if action is not None else (8, 8)
            # MuCurve.wrapMode must be exactly two ints (pre, post) — otherwise
            # the binary stream shifts and later MuClip.wrapMode values are
            # misread (commonly as Ping-Pong=4) and keys become garbage.
            try:
                mucurve.wrapMode = (int(wm[0]), int(wm[1]))
            except Exception:
                mucurve.wrapMode = (8, 8)
            mucurve.keys = []
            for key in iter_export_keyframes(action, curve):
                mucurve.keys.append(make_key(key, mult))
            return mucurve
        if curve.data_path not in property_map:
            return None
        property, mult, ctyp = property_map[curve.data_path][curve.array_index]
    elif typ == "arm":
        if "." in curve.data_path:
            bpath, dpath = curve.data_path.rsplit(".", 1)
            bone_path = muobj.bone_paths[bpath]
            bone = mu.object_paths[bone_path]
            # The Animation component's true host (anim_root) can sit one or
            # more BONE-hops below the armature's own path (eg. a "DrillFixed"
            # root bone whose Unity GameObject also owns the MuAnimation).
            # Strip using the deeper of the two so bone paths stay relative
            # to the real host instead of accidentally including the extra
            # bone segment(s) — that duplication corrupted every position/
            # rotation keyframe on TriBitDrill's control armature.
            strip_prefix = muobj.path
            if (anim_root and len(anim_root) > len(strip_prefix)
                    and (anim_root == strip_prefix
                         or anim_root.startswith(strip_prefix + "/"))):
                strip_prefix = anim_root
            bone_path = bone_path[len(strip_prefix):]
            if bone_path[:1] == '/':
                bone_path = bone_path[1:]
            if path and path[-1:] != "/":
                path = path + "/"
            mucurve.path = path + bone_path
            property, mult, ctyp = property_map[dpath][curve.array_index]
            if not hasattr(bone, "curves"):
                bone.curves = {}
            if dpath not in bone.curves:
                bone.curves[dpath] = [None] * len(property_map[dpath])
            bone.curves[dpath][curve.array_index] = mucurve
            muobj.animated_bones.add(bone)
        else:
            dp = curve.data_path
            ai = curve.array_index
            if dp not in property_map:
                return None
            property, mult, ctyp = property_map[dp][ai]
    elif type(typ) == bpy.types.Material:
        dp_full = _mumatprop_data_path(curve.data_path)
        if not dp_full:
            return None
        dp = dp_full.split(".")
        # Prefer exact Unity property name stored at import
        stored = None
        if action is not None:
            try:
                key = "mu_uprop:%s:%d" % (dp_full, curve.array_index)
                if key in action:
                    stored = action[key]
            except Exception:
                stored = None
        if stored:
            property = stored
            mult = 1
            ctyp = 1
        else:
            try:
                prop_rna = typ
                for part in dp[:-1]:
                    if part.endswith("]") and "[" in part:
                        # properties[2]
                        attr, idx = part[:-1].split("[", 1)
                        prop_rna = getattr(prop_rna, attr)[int(idx)]
                    else:
                        prop_rna = getattr(prop_rna, part)
                property = prop_rna.name
            except Exception:
                return None
            mult = 1
            if dp[1] in ["color", "vector"]:
                property += vector_map[dp[1]][curve.array_index]
            elif dp[1] == "texture":
                # data_path: mumatprop.texture.properties[N].offset|scale
                attr = dp[-1]
                suf = _texture_vector_suffix.get((attr, curve.array_index))
                if not suf:
                    return None
                property += suf
            ctyp = 1
    else:
        return None
    mucurve.property = property
    # 0 = transform, 1 = material, 2 = light, 3 = audio source
    mucurve.type = ctyp
    wm = get_mu_curve_wrap(action, curve) if action is not None else (8, 8)
    # MuCurve.wrapMode must be exactly two ints (pre, post) — otherwise
    # the binary stream shifts and later MuClip.wrapMode values are
    # misread (commonly as Ping-Pong=4) and keys become garbage.
    try:
        mucurve.wrapMode = (int(wm[0]), int(wm[1]))
    except Exception:
        mucurve.wrapMode = (8, 8)
    mucurve.keys = []
    for key in iter_export_keyframes(action, curve):
        mucurve.keys.append(make_key(key, mult))
    if not mucurve.keys and curve.keyframe_points:
        for kp in curve.keyframe_points:
            mucurve.keys.append(make_key(kp, mult))
    # Transform/light curves: ``path`` (rel_path from export hierarchy) is
    # authoritative. Overwriting with import-time mu_unity_curve_path broke
    # round-trip when export strips .NNN from GO names but stored paths still
    # had them (ht2 radiator 36→51 clips) or collapsed siblings (strut4 vs
    # strut4.001). Material paths are set via curve_rel in make_animations.
    if (action is not None and typ in {"obj", "lit"} and not path):
        try:
            stored = action.get("mu_unity_curve_path")
            if stored is not None and str(stored).strip():
                # Orphan / authored Unity paths: exact string (no strip_nnn)
                if action.get("mu_orphan_curve"):
                    mucurve.path = str(stored).strip()
                else:
                    mucurve.path = normalize_mu_curve_path(str(stored))
        except Exception:
            pass
    return mucurve

def transform_curves(muarm):
    # Called once per bone-track entry (see make_animations), but
    # `animated_bones` accumulates every bone seen so far for the current
    # clip. Consume (pop) it instead of merely iterating, otherwise a bone
    # added on an early entry gets its location/rotation curves re-derived
    # from rest on every later entry too — each pass adds another copy of
    # the rest offset, compounding into wildly wrong keyframe values (eg.
    # TriBitDrill's ~19x position blowup with ~20 animated control bones).
    bones = list(muarm.animated_bones)
    muarm.animated_bones.clear()
    for bone in bones:
        if "location" in bone.curves:
            location = bone.curves["location"]
            if None in location:
                print("INFO: Skipping incomplete location curve set")
            else:
                n = min(len(location[i].keys) for i in range(3))
                if n == 0:
                    print("INFO: Skipping empty location curve set")
                else:
                    if (len(location[0].keys) != n
                            or len(location[1].keys) != n
                            or len(location[2].keys) != n):
                        print("INFO: Location curve key counts differ — "
                              f"converting first {n} keys")
                    # Inverse of import: blender_loc = rrot @ (unity_loc - lloc)
                    rrot = getattr(bone, "relRotation", None) or Quaternion((1, 0, 0, 0))
                    rrot_inv = rrot.inverted()
                    lloc = Vector(bone.transform.localPosition)
                    for i in range(n):
                        xk = location[0].keys[i].value
                        yk = location[1].keys[i].value
                        zk = location[2].keys[i].value
                        loc = rrot_inv @ Vector((xk, yk, zk)) + lloc
                        location[0].keys[i].value = loc.x
                        location[1].keys[i].value = loc.y
                        location[2].keys[i].value = loc.z
        if "rotation_quaternion" in bone.curves:
            rotation = bone.curves["rotation_quaternion"]
            if None in rotation:
                print("INFO: Skipping incomplete rotation fcurve set")
            elif ((len(rotation[0].keys) != len(rotation[1].keys))
                  or (len(rotation[0].keys) != len(rotation[2].keys))
                  or (len(rotation[0].keys) != len(rotation[3].keys))):
                print("INFO: Skipping mismatched rotation fcurve set")
            else:
                lrot = bone.transform.localRotation
                for i in range(len(rotation[0].keys)):
                    # the keys are already left-handled, but the array
                    # order is wxzy
                    wk = rotation[0].keys[i].value
                    xk = -rotation[1].keys[i].value
                    yk = -rotation[2].keys[i].value
                    zk = -rotation[3].keys[i].value
                    rot = Quaternion((wk, xk, yk, zk))
                    rot = lrot @ rot
                    # the keys are already left-handled, but the array
                    # order is wxzy
                    rotation[0].keys[i].value = rot.w
                    rotation[1].keys[i].value = -rot.x
                    rotation[2].keys[i].value = -rot.y
                    rotation[3].keys[i].value = -rot.z
                    for j in range(2):
                        # the keys are already left-handled, but the array
                        # order is wxzy
                        wk = rotation[0].keys[i].tangent[j]
                        xk = -rotation[1].keys[i].tangent[j]
                        yk = -rotation[2].keys[i].tangent[j]
                        zk = -rotation[3].keys[i].tangent[j]
                        tan = Quaternion((wk, xk, yk, zk))
                        tan = lrot @ tan
                        # the keys are already left-handled, but the array
                        # order is wxzy
                        rotation[0].keys[i].tangent[j] = tan.w
                        rotation[1].keys[i].tangent[j] = -tan.x
                        rotation[2].keys[i].tangent[j] = -tan.y
                        rotation[3].keys[i].tangent[j] = -tan.z

def make_animations_per_host(mu, animations, default_root=""):
    """Build one MuAnimation per distinct host (orange empty / Animation GO).

    Sibling objects that share a clip name (e.g. four ``antenna`` clips) each
    keep their own wrapMode. Returns list of ``(host_key, anim_root, MuAnimation)``.
    Prefer this over a single ``make_animations`` call on the ungrouped dict.
    """
    groups = group_animations_by_host(animations, default_root)
    out = []
    for host_key, host_anims in groups.items():
        if host_key[0] == "path":
            root = host_key[1] or default_root or ""
        else:
            # bobj name → prefer mu_anim_host from any action in the group
            root = default_root or ""
            for entries in host_anims.values():
                for track, path, typ in entries:
                    action = track if isinstance(track, bpy.types.Action) else (
                        track.strips[0].action if getattr(track, "strips", None) else None)
                    if action is None:
                        continue
                    try:
                        tagged = action.get("mu_anim_host") if hasattr(action, "get") else None
                        if not tagged and "mu_anim_host" in action:
                            tagged = action["mu_anim_host"]
                        if tagged:
                            root = str(tagged)
                            break
                    except Exception:
                        pass
                    if path:
                        root = path
                        break
                if root:
                    break
        anim = make_animations(mu, host_anims, root)
        if anim is not None and getattr(anim, "clips", None):
            out.append((host_key, root, anim))
    return out


def _material_for_shader_export(muobj):
    """Best-effort material for mumatprop fcurves on a mesh MuObject."""
    bobj = getattr(muobj, "bobj", None)
    if bobj is None:
        return None
    data = getattr(bobj, "data", None)
    slots = getattr(data, "materials", None) if data else None
    if not slots:
        return None
    for mat in slots:
        if mat is not None:
            return mat
    return None


def make_animations(mu, animations, anim_root):
    # Never write Ping-Pong viewport bake into .mu keys
    restore_all_pingpong_for_export()

    anim = MuAnimation()
    anim.autoPlay = False
    default_clip_name = None
    selected_clip_name = None

    by_clip = _merge_entries_by_clip_name(animations)

    for clip_name, clip_entries in by_clip.items():
        clip = MuClip()
        if default_clip_name is None:
            default_clip_name = clip_name
        clip.name = clip_name
        clip.lbCenter = (0, 0, 0)
        clip.lbSize = (0, 0, 0)
        clip.wrapMode = 1
        # Prefer explicit mu_clip_wrap_mode from any Action on this clip
        # (including those that did not add curves this pass). Majority only
        # as fallback so partial exports cannot force Once over a real Ping-Pong.
        clip_action = None
        wrap_votes = []
        wrap_votes_any = []  # all Actions, even without new curves
        seen_actions = set()
        contributed = False

        for data in clip_entries:
            track, path, typ = data
            # Normalize Blender-only segments (.skin / .bindPose / ∧nnn)
            norm = "/".join(
                strip_nnn(s).removesuffix(".skin").removesuffix(".bindPose")
                for s in path.split("/")
                if s and not strip_nnn(s).startswith("mesh:")
            )
            muobj = mu.object_paths.get(path)
            if muobj is None and norm != path:
                muobj = mu.object_paths.get(norm)
                if muobj:
                    path = norm
            if not muobj:
                # Fallback: suffix / basename match (spaces, bindPose rename)
                base = norm.rsplit("/", 1)[-1]
                matches = [p for p in mu.object_paths if p == norm
                           or p.endswith("/" + norm)
                           or p.rsplit("/", 1)[-1] == base]
                if not matches and base:
                    tail = "/".join(norm.split("/")[-2:]) if "/" in norm else base
                    matches = [p for p in mu.object_paths
                               if p.endswith("/" + tail) or p.endswith("/" + base)]
                if len(matches) == 1:
                    path = matches[0]
                    muobj = mu.object_paths[path]
                elif matches:
                    def score(p):
                        a, b = p.split("/"), norm.split("/")
                        n = 0
                        for x, y in zip(reversed(a), reversed(b)):
                            if x != y:
                                break
                            n += 1
                        return n, len(p)
                    path = max(matches, key=score)
                    muobj = mu.object_paths[path]
                else:
                    path = norm
            if not muobj:
                # Orphan / anim-stub Unity paths are not MuObjects in the
                # exported tree (TriBitDrill shake, ladder garbage targets).
                # Still emit curves on the Animation host with the stored path.
                action_peek = track if isinstance(track, bpy.types.Action) else (
                    track.strips[0].action if getattr(track, "strips", None) else None)
                is_orphan_entry = False
                stored_peek = ""
                if action_peek is not None:
                    try:
                        stored_peek = str(
                            action_peek.get("mu_unity_curve_path") or "").strip()
                        is_orphan_entry = bool(
                            action_peek.get("mu_orphan_curve")
                            or action_peek.get("mu_anim_stub_owner")
                        )
                    except Exception:
                        pass
                if is_orphan_entry or stored_peek:
                    host_mu = None
                    if anim_root and anim_root in mu.object_paths:
                        host_mu = mu.object_paths[anim_root]
                    if host_mu is None and anim_root:
                        leaf = anim_root.rstrip("/").split("/")[-1]
                        hits = [p for p in mu.object_paths
                                if p == anim_root or p.endswith("/" + leaf)]
                        if len(hits) == 1:
                            host_mu = mu.object_paths[hits[0]]
                    if host_mu is not None:
                        muobj = host_mu
                        if stored_peek:
                            path = stored_peek
                    else:
                        print(f"Object path not found: {path}")
                        continue
                else:
                    print(f"Object path not found: {path}")
                    continue

            # Strict host filter: entry must belong to THIS anim_root host.
            # Use orange-empty identity (mu_anim_bobj / mu_nla_owner / path),
            # NOT a loose prefix match that pulls sibling antennas together.
            host_key = _anim_host_of(track, path)
            if anim_root:
                belongs = False
                root_norm = _norm_mu_path(anim_root)
                path_norm = _norm_mu_path(path)
                if host_key[0] == "path" and host_key[1]:
                    # Exact host path, or this entry IS the host object
                    host_norm = _norm_mu_path(host_key[1])
                    belongs = (
                        host_norm == root_norm
                        or path_norm == root_norm
                        or host_key[1] == anim_root
                        or path == anim_root
                    )
                elif host_key[0] == "bobj" and host_key[1]:
                    try:
                        action_tmp = track if isinstance(track, bpy.types.Action) else (
                            track.strips[0].action if getattr(track, "strips", None) else None)
                        tagged = None
                        if action_tmp is not None:
                            tagged = action_tmp.get("mu_anim_host") if hasattr(action_tmp, "get") else None
                            if not tagged and "mu_anim_host" in action_tmp:
                                tagged = action_tmp["mu_anim_host"]
                        if tagged and (
                                str(tagged) == anim_root
                                or _norm_mu_path(tagged) == root_norm):
                            belongs = True
                        # Also accept when anim_root path ends with this bobj name
                        if not belongs and anim_root.rstrip("/").endswith("/" + str(host_key[1])):
                            belongs = True
                        if not belongs and anim_root.rstrip("/").split("/")[-1] == str(host_key[1]):
                            belongs = True
                    except Exception:
                        pass
                if not belongs and (
                        path == anim_root or path_norm == root_norm):
                    belongs = True
                if not belongs:
                    continue

            # Curve paths are relative to the Animation host (anim_root)
            if not anim_root or path == anim_root:
                rel_path = ""
            elif path.startswith(anim_root + "/"):
                rel_path = path[len(anim_root) + 1:]
            elif anim_root.startswith(path + "/"):
                rel_path = ""
            else:
                rel_path = path
            action = track if isinstance(track, bpy.types.Action) else (
                track.strips[0].action if getattr(track, "strips", None) else None)
            if action:
                # Shared material Actions are collected once per mesh user
                ap = action.as_pointer()
                if ap in seen_actions:
                    continue
                seen_actions.add(ap)
                # Always record wrap from every Action on this clip (UI/test set it)
                try:
                    wrap_votes_any.append(read_mu_clip_wrap(action))
                except Exception:
                    pass
                curve_rel = rel_path
                if type(typ) == bpy.types.Material:
                    try:
                        if action is not None and "mu_unity_curve_path" in action:
                            stored = action["mu_unity_curve_path"]
                            if stored is not None and str(stored).strip():
                                curve_rel = str(stored).strip()
                    except Exception:
                        pass
                elif typ in ("obj", "lit") and action is not None:
                    try:
                        stored = str(action.get("mu_unity_curve_path") or "").strip()
                        is_orphan = bool(
                            action.get("mu_orphan_curve")
                            or action.get("mu_anim_stub_owner")
                        )
                        if stored and is_orphan:
                            # Lossless: garbage / missing-GO paths from import
                            curve_rel = stored
                        elif stored:
                            hier_leaf = (rel_path or "").rstrip("/").split("/")[-1]
                            store_leaf = stored.rstrip("/").split("/")[-1]
                            # Unity duplicate-name disambiguator (.001)
                            if (store_leaf and hier_leaf
                                    and store_leaf != hier_leaf
                                    and strip_nnn(store_leaf) == hier_leaf):
                                curve_rel = stored  # keep .001 — do NOT normalize
                    except Exception:
                        pass
                n_before = len(clip.curves)
                for curve in iter_action_fcurves(action):
                    export_typ = typ
                    if export_typ in ("obj", "lit") and (
                            (curve.data_path or "").startswith("mumatprop.")):
                        mat = _material_for_shader_export(muobj)
                        if mat is not None:
                            export_typ = mat
                    curve_data = make_curve(
                        mu, muobj, curve, curve_rel, export_typ, action=action,
                        anim_root=anim_root)
                    if curve_data:
                        clip.curves.append(curve_data)
                if hasattr(muobj, "animated_bones"):
                    transform_curves(muobj)
                # Actions that added curves still preferred for selected clip name
                if len(clip.curves) > n_before:
                    contributed = True
                    if clip_action is None:
                        clip_action = action
                    wrap_votes.append(read_mu_clip_wrap(action))

        # Prefer unanimous / majority from ALL actions on the clip first, then
        # from contributors only. Avoid silent Once when UI set Ping-Pong
        # (light-only Actions often add 0 curves after host filter and used
        # to force Once via an empty wrap_votes list).
        from collections import Counter
        chosen = None
        for pool in (wrap_votes_any, wrap_votes):
            if not pool:
                continue
            counts = Counter(int(m) for m in pool)
            mode, _n = counts.most_common(1)[0]
            non_once = [int(m) for m in pool if int(m) != 1]
            # Unique non-Once mode wins even when Once is the plurality
            # (Once is the code default — treat it as weaker signal).
            if non_once and len(set(non_once)) == 1:
                chosen = non_once[0]
            else:
                chosen = int(mode)
            break
        if chosen is not None:
            clip.wrapMode = int(chosen)
        if clip_action is not None and selected_clip_name is None:
            try:
                value = clip_action.get("mu_animation_clip", "")
                if value:
                    selected_clip_name = str(value)
            except Exception:
                pass
        # Skip empty clips (all entries filtered out as other hosts).
        # Keep metadata-only clips (wrap/autoPlay tags, zero curves) so
        # Combined / LR87 / Viking Propulsion round-trip clip names.
        if not contributed and not clip.curves and not wrap_votes_any:
            continue
        anim.clips.append(clip)

    if selected_clip_name:
        anim.clip = selected_clip_name
    elif default_clip_name:
        anim.clip = default_clip_name
    host_ap = _host_autoplay_from_animations(animations, anim_root)
    if host_ap is not None:
        anim.autoPlay = bool(host_ap)
    #print(f"Created animation: {anim}") # Debug animations
    return anim
