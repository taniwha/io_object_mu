# vim:ts=4:et
# <pep8 compliant>

import os
import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup, WindowManager

from . import thumbnails
from .anim_scope import (
    import_id_from_object_chain as _import_id_from_object_chain,
    resolve_mu_import_id as _resolve_mu_import_id,
)
from ..utils import strip_nnn
from .rename_parse import (
    merge_blender_protected_rename,
    parse_f2_identity as _parse_f2_identity,
)
from ..import_mu.name_protect import apply_protected_object_rename
import importlib
from ..utils import action_compat as _action_compat_mod
importlib.reload(_action_compat_mod)
from ..utils.action_compat import (
    iter_action_fcurves,
    apply_mu_clip_wrap_to_action,
    apply_mu_curve_wrap,
    get_mu_curve_wrap,
    mu_wrap_name,
    actions_clip_length,
)

_THUMB_SCALE = 7.5 # Main thumb (7.5X20px)
_THUMB_SCALE_POPUP = 5.0 # Menu thumbs (5x20px)

# Module-level collapse state (like shader property sets)
_anim_section_expanded = True
_preview_section_expanded = {
    "lights": False,
    "fx": False,
    "robotics": False,
}
_anim_tree_sig = ""
_panel_import_id_cache = object()  # sentinel — bust UI tree when scope changes
_anim_ui_guard = False

_WRAP_BTNS = (
    (1, "Once"),
    (2, "Loop"),
    (4, "Ping-Pong"),
    (8, "Clamp"),
)
# UIList default / hard cap (same idea as import_ksp panels)
_ANIM_LIST_DEFAULT_ROWS = 2
_ANIM_LIST_MAX_ROWS = 10

# Force MU panel redraw when only the active layer collection changes
# (Outliner collection click does not always refresh View3D UI by itself).
_alc_redraw_handler = None
_last_alc_ptr = None


def _tag_mu_view3d_redraw():
    try:
        wm = bpy.context.window_manager
    except Exception:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _on_alc_depsgraph(_scene, _depsgraph=None):
    global _last_alc_ptr
    try:
        alc = bpy.context.view_layer.active_layer_collection
        ptr = alc.as_pointer() if alc is not None else 0
    except Exception:
        return
    if ptr == _last_alc_ptr:
        return
    _last_alc_ptr = ptr
    _tag_mu_view3d_redraw()


def ensure_alc_redraw_handler():
    global _alc_redraw_handler
    if _alc_redraw_handler is not None:
        return
    try:
        from .anim_scope import reset_scope_drive_state
        reset_scope_drive_state()
    except Exception:
        pass
    if _on_alc_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_alc_depsgraph)
    _alc_redraw_handler = _on_alc_depsgraph


def remove_alc_redraw_handler():
    global _alc_redraw_handler, _last_alc_ptr
    try:
        if _on_alc_depsgraph in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_on_alc_depsgraph)
    except Exception:
        pass
    _alc_redraw_handler = None
    _last_alc_ptr = None


def _mu_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default


def _normalize_wrap(mode):
    """Unity Default(0) → Once(1) for button highlight."""
    mode = _mu_int(mode, 1)
    return 1 if mode == 0 else mode


def _find_nla_owner(action):
    """Return Blender object name that owns this Action on an NLA track."""
    if action is None:
        return ""
    try:
        stored = action.get("mu_nla_owner")
        if stored:
            return str(stored)
    except Exception:
        pass
    try:
        stored = action.get("mu_anim_bobj")
        if stored and stored in bpy.data.objects:
            return str(stored)
    except Exception:
        pass
    # Walk scene — prefer exact Action pointer match on NLA strips
    for obj in bpy.data.objects:
        ad = getattr(obj, "animation_data", None)
        if not ad:
            continue
        for track in ad.nla_tracks:
            for strip in track.strips:
                if strip.action == action:
                    return obj.name
    return ""


def _mu_import_id_of_object(obj):
    """Return the unique import ID assigned to a .mu object."""
    if obj is None:
        return ""
    try:
        value = obj.get("mu_import_id")
        if value:
            return str(value)
    except Exception:
        pass
    return ""


def _scene_uses_mu_import_ids(context):
    """True when the .blend has mu_import_id tags (imports after the upgrade)."""
    for obj in bpy.data.objects:
        try:
            if obj.get("mu_import_id"):
                return True
        except Exception:
            pass
    try:
        for mat in bpy.data.materials:
            try:
                if mat.get("mu_import_id"):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _bobj_name_from_host_key(host_key):
    """Extract Blender object name from a host_key ('bobj:Name', etc.)."""
    key = (host_key or "").strip()
    if key.startswith("bobj:"):
        return key[5:]
    if key.startswith("nla:"):
        return key[4:]
    return ""


def _object_by_name(name):
    """Find a scene object by Blender name, ∧-stripped name, or .001 uniquifier."""
    if not name:
        return None
    name = str(name)
    hit = bpy.data.objects.get(name)
    if hit is not None:
        return hit
    try:
        base = strip_nnn(name)
    except Exception:
        base = name
    matches = []
    for obj in bpy.data.objects:
        on = obj.name or ""
        if on == name or on.startswith(name + "."):
            matches.append(obj)
            continue
        try:
            if strip_nnn(on) == base:
                matches.append(obj)
        except Exception:
            pass
    if matches:
        return matches[0]
    return None


def _host_path_from_key(host_key):
    key = (host_key or "").strip()
    if key.startswith("path:"):
        return key[5:]
    return ""


def _objects_for_host_key(host_key):
    """Animation GO(s) for a tree host_key (bobj / nla / path)."""
    host_key = (host_key or "").strip()
    found = []
    seen = set()

    def _add(obj):
        if obj is None:
            return
        try:
            ptr = obj.as_pointer()
        except Exception:
            ptr = id(obj)
        if ptr in seen:
            return
        seen.add(ptr)
        found.append(obj)

    _add(_object_by_name(_bobj_name_from_host_key(host_key)))
    path = _host_path_from_key(host_key)
    for action in bpy.data.actions:
        try:
            if _host_key_of_action(action, "") != host_key:
                continue
        except Exception:
            continue
        try:
            _add(_object_by_name(action.get("mu_anim_bobj")))
        except Exception:
            pass
        try:
            tagged = str(action.get("mu_anim_host") or "")
            if tagged and not path:
                path = tagged
        except Exception:
            pass
    if path:
        for obj in bpy.data.objects:
            try:
                if str(obj.get("mu_animation_host") or "") == path:
                    _add(obj)
            except Exception:
                pass
        if not found:
            leaf = path.rstrip("/").split("/")[-1]
            _add(_object_by_name(leaf))
    return found


def _read_host_autoplay(host_key):
    """Host Auto Play: object flag first, then any Action of this host."""
    for obj in _objects_for_host_key(host_key):
        try:
            if "mu_animation_autoplay" in obj:
                return bool(_mu_int(obj.get("mu_animation_autoplay", 0), 0))
        except Exception:
            pass
    for action in bpy.data.actions:
        try:
            if _host_key_of_action(action, "") != host_key:
                continue
        except Exception:
            continue
        ap = _host_autoplay_from_action(action)
        if ap is not None:
            return bool(ap)
        try:
            if _mu_int(action.get("mu_auto_play", 0), 0):
                return True
        except Exception:
            pass
    return False


def _host_autoplay_from_action(action):
    """Read MuAnimation.autoPlay from the Animation GO custom property."""
    if action is None:
        return None
    try:
        bname = action.get("mu_anim_bobj")
        if not bname:
            return None
        bobj = _object_by_name(str(bname))
        if bobj is None:
            return None
        if "mu_animation_autoplay" not in bobj:
            return None
        return bool(_mu_int(bobj.get("mu_animation_autoplay", 0), 0))
    except Exception:
        return None


def _set_host_autoplay(host_key, value):
    """Sync autoPlay on every Action and the Animation GO for one host."""
    value = int(bool(value))
    host_key = (host_key or "").strip()
    matched = 0
    for action in bpy.data.actions:
        try:
            oh = _host_key_of_action(action, "")
            if host_key and oh == host_key:
                action["mu_auto_play"] = value
                matched += 1
        except Exception:
            continue
    objs = _objects_for_host_key(host_key)
    for bobj in objs:
        try:
            bobj["mu_animation_autoplay"] = value
        except Exception:
            pass
    return matched


def _is_preview_action(action):
    """Viewport-only FX / ColorChanger / robotics Actions are not MU clips."""
    if action is None:
        return True
    try:
        if (action.get("mu_fx_preview")
                or action.get("mu_color_changer_preview")
                or action.get("mu_robotic_preview")):
            return True
    except Exception:
        pass
    try:
        name = getattr(action, "name", "") or ""
        if name.startswith("ColorChanger") or name.endswith(".fx_preview"):
            return True
        if name.startswith("mu_fx_"):
            return True
    except Exception:
        pass
    return False


def _preview_section_of(ent):
    """Which viewport ribbon a preview Action belongs to."""
    act = ent.get("action") if ent else None
    cname = str((ent or {}).get("clip_name") or "")
    aname = ""
    try:
        if act is not None:
            aname = act.name or ""
            if act.get("mu_color_changer_preview"):
                return "lights"
            if act.get("mu_robotic_preview"):
                return "robotics"
    except Exception:
        pass
    blob = ("%s %s" % (cname, aname)).lower()
    if aname.startswith("ColorChanger") or "colorchanger" in blob:
        return "lights"
    if "robot" in blob or "servo" in blob or "hinge" in blob:
        return "robotics"
    return "fx"


def _entry_owner_name(ent):
    """Blender object that owns the NLA strip (curve target)."""
    owner = str((ent or {}).get("owner") or "")
    if owner:
        return owner
    act = (ent or {}).get("action")
    if act is None:
        return ""
    try:
        stored = str(act.get("mu_nla_owner") or "")
        if stored:
            return stored
    except Exception:
        pass
    return _find_nla_owner(act)


def _unity_clip_siblings(action):
    """Actions that are the same Unity MuClip on the same Animation GO.

    MuClip.wrapMode is one value per (host, clip name). Two hosts may each
    own a clip named ``idle`` with different wrap — those are two definitions.
    """
    if action is None:
        return []
    hk = _host_key_of_action(action, "")
    try:
        clip = str(action.get("mu_clip_name") or "")
    except Exception:
        clip = ""
    out = [action]
    if not hk or not clip:
        return out
    seen = {id(action)}
    for other in bpy.data.actions:
        if id(other) in seen:
            continue
        try:
            if _host_key_of_action(other, "") != hk:
                continue
            if str(other.get("mu_clip_name") or "") != clip:
                continue
        except Exception:
            continue
        seen.add(id(other))
        out.append(other)
    return out


def _on_row_autoplay(self, context):
    if _anim_ui_guard or getattr(self, "kind", "") != "host":
        return
    _set_host_autoplay(self.host_key, self.autoplay)


def _objects_of_mu_import(import_id):
    """Return ALL Blender objects belonging to one .mu import."""
    if not import_id:
        return []
    result = []
    seen = set()
    for obj in bpy.data.objects:
        try:
            if str(obj.get("mu_import_id", "")) != import_id:
                continue
        except Exception:
            continue
        try:
            ptr = obj.as_pointer()
        except Exception:
            ptr = id(obj)
        if ptr in seen:
            continue
        seen.add(ptr)
        result.append(obj)
    return result


def _count_import_roots(import_id):
    """Top-level Blender objects belonging to one mu_import_id (panel Roots).

    Animation-only stubs (``mu_anim_stub``) created for missing curve paths
    are never counted — they exist only to host NLA and must not inflate
    Roots after reimport (Beacon1 1→6 regression).
    """
    if not import_id:
        return 0
    roots = 0
    seen = set()
    for obj in bpy.data.objects:
        try:
            if str(obj.get("mu_import_id", "")) != str(import_id):
                continue
        except Exception:
            continue
        try:
            if obj.get("mu_anim_stub"):
                continue
        except Exception:
            pass
        try:
            ptr = obj.as_pointer()
        except Exception:
            ptr = id(obj)
        if ptr in seen:
            continue
        parent = getattr(obj, "parent", None)
        parent_iid = ""
        if parent is not None:
            try:
                parent_iid = str(parent.get("mu_import_id") or "")
            except Exception:
                parent_iid = ""
        if parent is not None and parent_iid == str(import_id):
            continue
        seen.add(ptr)
        roots += 1
    return roots


def _scan_objects_for_import_id(import_id):
    """All Blender objects (+ descendants) tagged with one mu_import_id."""
    scan_objects = []
    scan_seen = set()
    for candidate in bpy.data.objects:
        try:
            candidate_import_id = str(candidate.get("mu_import_id") or "")
        except Exception:
            candidate_import_id = ""
        if candidate_import_id != str(import_id):
            continue
        try:
            ptr = candidate.as_pointer()
        except Exception:
            ptr = id(candidate)
        if ptr in scan_seen:
            continue
        scan_seen.add(ptr)
        scan_objects.append(candidate)

    def add_object_recursive(o):
        if o is None:
            return
        try:
            ptr = o.as_pointer()
        except Exception:
            ptr = id(o)
        if ptr in scan_seen:
            return
        scan_seen.add(ptr)
        scan_objects.append(o)
        try:
            children = list(o.children)
        except Exception:
            children = []
        for child in children:
            add_object_recursive(child)

    for root_object in list(scan_objects):
        try:
            children = list(root_object.children)
        except Exception:
            children = []
        for child in children:
            add_object_recursive(child)
    return scan_objects


def _collect_animation_entries_from_scan(scan_objects, import_id="", preview=False):
    """NLA Action rows for scanned objects/materials (one row = one UI clip line)."""
    entries = []
    seen_actions = set()

    def _add_from_id(id_data, owner_hint=""):
        ad = getattr(id_data, "animation_data", None)
        if not ad:
            return
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
                action = getattr(strip, "action", None)
                if action is None:
                    continue
                if _is_preview_action(action):
                    if not preview:
                        continue
                else:
                    if preview:
                        continue
                try:
                    ptr = action.as_pointer()
                except Exception:
                    ptr = id(action)
                if ptr in seen_actions:
                    continue
                has_mu = False
                try:
                    has_mu = (
                        "mu_clip_name" in action
                        or "mu_clip_wrap_mode" in action
                        or "mu_anim_host" in action
                        or "mu_anim_bobj" in action
                        or "mu_nla_owner" in action
                        or "mu_auto_play" in action
                        or "mu_import_gen" in action
                        or "mu_import_id" in action
                    )
                except Exception:
                    has_mu = False
                if not has_mu:
                    try:
                        if not track.name:
                            continue
                    except Exception:
                        continue
                if import_id:
                    try:
                        action_import_id = str(action.get("mu_import_id") or "")
                    except Exception:
                        action_import_id = ""
                    if action_import_id and action_import_id != str(import_id):
                        continue
                seen_actions.add(ptr)
                try:
                    clip_name = (action.get("mu_clip_name") or track.name or action.name)
                except Exception:
                    clip_name = track.name or action.name
                owner = (
                    owner_hint
                    or getattr(id_data, "name", "")
                    or _find_nla_owner(action)
                )
                if not owner:
                    try:
                        owner = str(action.get("mu_nla_owner") or "")
                    except Exception:
                        owner = ""
                try:
                    wrap = _normalize_wrap(action.get("mu_clip_wrap_mode", 1))
                except Exception:
                    wrap = 1
                autoplay = _host_autoplay_from_action(action)
                if autoplay is None:
                    try:
                        autoplay = bool(_mu_int(action.get("mu_auto_play", 0), 0))
                    except Exception:
                        autoplay = False
                try:
                    anim_host = str(action.get("mu_anim_host") or "")
                except Exception:
                    anim_host = ""
                try:
                    anim_bobj = str(action.get("mu_anim_bobj") or "")
                except Exception:
                    anim_bobj = ""
                entries.append({
                    "action": action,
                    "clip_name": str(clip_name),
                    "owner": str(owner),
                    "wrap": wrap,
                    "autoplay": autoplay,
                    "anim_host": anim_host,
                    "anim_bobj": anim_bobj,
                })

    for model_obj in scan_objects:
        _add_from_id(model_obj, getattr(model_obj, "name", ""))
    scanned_materials = set()
    for model_obj in scan_objects:
        try:
            slots = getattr(model_obj, "material_slots", []) or []
        except Exception:
            slots = []
        for slot in slots:
            try:
                mat = slot.material
            except Exception:
                mat = None
            if mat is None:
                continue
            try:
                ptr = mat.as_pointer()
            except Exception:
                ptr = id(mat)
            if ptr in scanned_materials:
                continue
            scanned_materials.add(ptr)
            _add_from_id(mat, getattr(model_obj, "name", ""))
    if import_id:
        for mat in bpy.data.materials:
            try:
                if str(mat.get("mu_import_id", "")) != str(import_id):
                    continue
            except Exception:
                continue
            try:
                ptr = mat.as_pointer()
            except Exception:
                ptr = id(mat)
            if ptr in scanned_materials:
                continue
            scanned_materials.add(ptr)
            _add_from_id(mat, "")
    return entries


def collect_mu_animation_entries_by_import_id(import_id):
    """All Animation panel rows for one imported .mu (by mu_import_id)."""
    if not import_id:
        return []
    scan_objects = _scan_objects_for_import_id(import_id)
    if not scan_objects:
        return []
    return _collect_animation_entries_from_scan(scan_objects, import_id)


def collect_mu_preview_entries_by_import_id(import_id):
    """Viewport-only FX / ColorChanger / robotics NLA (not MuAnimation)."""
    if not import_id:
        return []
    scan_objects = _scan_objects_for_import_id(import_id)
    if not scan_objects:
        return []
    return _collect_animation_entries_from_scan(
        scan_objects, import_id, preview=True)


def _mu_animation_entries(context):
    """Collect ALL MU animation clips belonging to one imported .mu import.
    The important rule is:
        selected object -> find its mu_import_id
        mu_import_id -> find ALL objects from that import
        ALL import objects -> recursively scan their complete hierarchy
    This prevents the animation list from changing when the user selects
    different hosts / empties / meshes inside the same imported .mu model.
    It also correctly supports a single .mu file creating multiple Blender roots.
    Each imported .mu is treated as one logical animation scope.
    """
    global _anim_tree_sig, _panel_import_id_cache
    import_id = _resolve_mu_import_id(context)
    if import_id != _panel_import_id_cache:
        _anim_tree_sig = ""
        _panel_import_id_cache = import_id
    if import_id:
        return collect_mu_animation_entries_by_import_id(import_id)
    # Tagged .blend but no unambiguous scope (empty col / Scene Collection) → hide list.
    if _scene_uses_mu_import_ids(context):
        return []
    return _legacy_mu_animation_entries(context)


def _object_hidden_by_variant(name):
    """True when this object or an ancestor is hidden by the active variant."""
    if not name:
        return False
    obj = bpy.data.objects.get(str(name))
    if obj is None:
        return False
    cur = obj
    while cur is not None:
        try:
            if cur.get("mu_variant_hidden"):
                return True
        except Exception:
            pass
        cur = getattr(cur, "parent", None)
    return False


def _active_variant_disabled_clips(context):
    """Clip names disabled by the active ModulePartVariants entry."""
    import json
    disabled = set()
    try:
        import_id = _resolve_mu_import_id(context) or ""
    except Exception:
        import_id = ""
    for obj in bpy.data.objects:
        try:
            if import_id and str(obj.get("mu_import_id") or "") != str(import_id):
                continue
            raw = obj.get("mu_variants")
        except Exception:
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        active = data.get("active") or data.get("base")
        for variant in data.get("variants") or []:
            if variant.get("name") != active:
                continue
            for name in variant.get("disabledAnimations") or []:
                if name:
                    disabled.add(str(name).strip().lower())
            break
        break
    return disabled


def _filter_variant_anim_entries(context, entries):
    """Keep clips that belong to the active variant.

    Hidden variant objects drop out. Clips named in disabledAnimations drop out.
    With the filter off, the list is unchanged.
    """
    try:
        enabled = bool(getattr(context.scene, "mu_anim_variant_filter", False))
    except Exception:
        enabled = False
    if not enabled:
        return entries
    disabled = _active_variant_disabled_clips(context)
    out = []
    for ent in entries or []:
        clip = str(ent.get("clip_name") or "").strip().lower()
        if clip and disabled and any(
            clip == name or name in clip or clip in name for name in disabled
        ):
            continue
        owner = str(ent.get("owner") or ent.get("anim_bobj") or "")
        nla = ""
        act = ent.get("action")
        if act is not None:
            try:
                nla = str(act.get("mu_nla_owner") or "")
            except Exception:
                nla = ""
        if owner and _object_hidden_by_variant(owner):
            continue
        if nla and nla != owner and _object_hidden_by_variant(nla):
            continue
        out.append(ent)
    return out


def _legacy_mu_animation_entries(context):
    # Legacy fallback for .blend files imported before mu_import_id existed.
    obj = getattr(context, "object", None)
    roots = []

    def top_parent(o):
        if o is None:
            return None
        seen = set()
        current = o
        while current is not None:
            try:
                ptr = current.as_pointer()
            except Exception:
                ptr = id(current)
            if ptr in seen:
                break
            seen.add(ptr)
            parent = getattr(current, "parent", None)
            if parent is None:
                break
            current = parent
        return current

    if obj is not None:
        root = top_parent(obj)
        if root is not None:
            roots.append(root)
    try:
        for selected in context.selected_objects:
            root = top_parent(selected)
            if root is not None and root not in roots:
                roots.append(root)
    except Exception:
        pass
    if not roots:
        try:
            collection = context.view_layer.active_layer_collection.collection
            for candidate in collection.objects:
                parent = getattr(candidate, "parent", None)
                if parent is None:
                    root = candidate
                    if root not in roots:
                        roots.append(root)
            if not roots:
                for candidate in collection.objects:
                    root = top_parent(candidate)
                    if root is not None and root not in roots:
                        roots.append(root)
        except Exception:
            pass
    if not roots:
        return []
    mu_paths = set()
    for root in roots:
        try:
            src = root.get("ksp_mu_path") or root.get("mu_import_path")
            if src:
                mu_paths.add(str(src))
        except Exception:
            pass
    if mu_paths:
        for candidate in bpy.data.objects:
            if getattr(candidate, "parent", None) is not None:
                continue
            try:
                src = candidate.get("ksp_mu_path") or candidate.get("mu_import_path")
                if src and str(src) in mu_paths and candidate not in roots:
                    roots.append(candidate)
            except Exception:
                pass
    scan_objects = []
    scan_seen = set()

    def add_object_recursive(o):
        if o is None:
            return
        try:
            ptr = o.as_pointer()
        except Exception:
            ptr = id(o)
        if ptr in scan_seen:
            return
        scan_seen.add(ptr)
        scan_objects.append(o)
        try:
            children = list(o.children)
        except Exception:
            children = []
        for child in children:
            add_object_recursive(child)

    for root in roots:
        add_object_recursive(root)
    if not scan_objects:
        return []
    return _collect_animation_entries_from_scan(scan_objects, "")


def _wrap_short(mode):
    """Compact wrap label for the UIList status column."""
    try:
        mode = int(mode)
    except Exception:
        mode = 1
    return {0: "?", 1: "Once", 2: "Loop", 4: "PP", 8: "Clamp"}.get(mode, "?")


def _host_key_of_action(action, owner=""):
    """Stable host id for grouping clips under one Animation component.

    Never use the NLA target mesh as a host — that turned window covers
    into fake Auto Play rows.
    """
    if action is not None:
        try:
            bobj = action.get("mu_anim_bobj")
            if bobj:
                return "bobj:" + str(bobj)
            host = action.get("mu_anim_host")
            if host:
                return "path:" + str(host)
        except Exception:
            pass
    return "owner:" + str(owner or "_default")


def _curve_wrap_of_action(action):
    """Dominant curve wrap mode (0 = mixed/unknown)."""
    if action is None:
        return 8
    try:
        wraps = []
        for fc in iter_action_fcurves(action):
            try:
                pre, post = get_mu_curve_wrap(action, fc)
                wraps.append((int(pre), int(post)))
            except Exception:
                pass
        if wraps and len(set(wraps)) == 1 and wraps[0][0] == wraps[0][1]:
            return int(wraps[0][0])
        if wraps:
            return 0
    except Exception:
        pass
    return 8


def _group_entries_by_host(entries):
    """Ordered list of (host_key, display_name, owner, autoplay, [clip dicts])."""
    from collections import OrderedDict
    groups = OrderedDict()
    for ent in entries:
        act = ent.get("action")
        owner = ent.get("owner") or ""
        hk = _host_key_of_action(act, owner)
        if hk not in groups:
            # Display: prefer bobj/owner name; show path host in paren if different
            disp = owner or hk
            try:
                if act is not None:
                    bobj = act.get("mu_anim_bobj") or ""
                    path = act.get("mu_anim_host") or ""
                    if bobj:
                        disp = str(bobj)
                        if path and str(path) != str(bobj) and "/" in str(path):
                            # keep short — owner empty name is enough
                            pass
                    elif path:
                        disp = str(path).rstrip("/").split("/")[-1] or str(path)
            except Exception:
                pass
            ap = _read_host_autoplay(hk)
            groups[hk] = {
                "host_key": hk,
                "name": str(disp),
                "owner": str(owner),
                "autoplay": ap,
                "clips": [],
            }
        g = groups[hk]
        g["clips"].append(ent)
    return list(groups.values())


def _group_entries_by_clip_name(ents):
    """Preserve first-seen order of Unity MuClip names under one host."""
    from collections import OrderedDict
    grouped = OrderedDict()
    for ent in ents:
        name = str(ent.get("clip_name") or "?")
        grouped.setdefault(name, []).append(ent)
    return list(grouped.items())


def mu_animation_entry_stats(entries, import_id=""):
    """Counts aligned with the Animation panel header.

    Returns (roots, hosts, clips, curves):
    - Roots: top-level Blender objects with this mu_import_id
    - Hosts: distinct Animation hosts (_host_key_of_action + owner)
    - Clips: len(entries) — one UI row per NLA Action (panel \"clip\")
    - Curves: total F-Curves across those Actions
    """
    from ..utils.action_compat import count_action_fcurves
    n_clips = len(entries)
    host_keys = set()
    curve_count = 0
    for ent in entries:
        act = ent.get("action")
        owner = ent.get("owner") or ""
        host_keys.add(_host_key_of_action(act, owner))
        if act is not None:
            try:
                curve_count += int(count_action_fcurves(act))
            except Exception:
                pass
    n_hosts = len(host_keys)
    n_roots = _count_import_roots(import_id) if import_id else 0
    if n_roots == 0 and n_hosts:
        n_roots = 1
    return n_roots, n_hosts, n_clips, curve_count


def _unhide_object_chain(obj):
    """Unhide ``obj`` and its parents so Scene Collection can show the selection."""
    seen = set()
    o = obj
    while o is not None:
        try:
            ptr = o.as_pointer()
        except Exception:
            ptr = id(o)
        if ptr in seen:
            break
        seen.add(ptr)
        for attr, val in (
            ("hide_select", False),
            ("hide_viewport", False),
        ):
            try:
                setattr(o, attr, val)
            except Exception:
                pass
        try:
            o.hide_set(False)
        except Exception:
            pass
        o = getattr(o, "parent", None)


def _show_active_in_outliner(context):
    """Scroll/expand Outliner (Scene Collection) to the active object."""
    try:
        windows = list(context.window_manager.windows)
    except Exception:
        return
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "OUTLINER":
                continue
            region = None
            for reg in area.regions:
                if reg.type == "WINDOW":
                    region = reg
                    break
            if region is None:
                continue
            try:
                with context.temp_override(
                        window=window, screen=screen,
                        area=area, region=region):
                    bpy.ops.outliner.show_active()
            except Exception:
                pass


def _select_scene_object(context, obj):
    """Make ``obj`` the active selection so F2 / outliner match the anim list."""
    if obj is None:
        return
    _reveal_in_view_layer(context, obj)
    _unhide_object_chain(obj)
    try:
        in_vl = obj.name in context.view_layer.objects
    except Exception:
        in_vl = False
    if not in_vl:
        try:
            context.view_layer.update()
        except Exception:
            pass
    try:
        for o in context.view_layer.objects:
            try:
                o.select_set(False)
            except Exception:
                pass
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except Exception:
        try:
            obj.select_set(True)
            context.view_layer.objects.active = obj
        except Exception:
            pass
    _show_active_in_outliner(context)


def _reveal_in_view_layer(context, obj):
    """Un-exclude nested collections so a child like AntennaCap can be selected."""
    if obj is None:
        return
    try:
        root = context.view_layer.layer_collection
    except Exception:
        return
    wanted = set()
    o = obj
    seen = set()
    while o is not None:
        try:
            ptr = o.as_pointer()
        except Exception:
            ptr = id(o)
        if ptr in seen:
            break
        seen.add(ptr)
        try:
            for col in o.users_collection:
                wanted.add(col)
        except Exception:
            pass
        o = getattr(o, "parent", None)

    def _walk(lc):
        found = False
        col = getattr(lc, "collection", None)
        if col is not None:
            if col in wanted:
                found = True
            else:
                try:
                    if obj in col.objects:
                        found = True
                except Exception:
                    pass
        for child in getattr(lc, "children", []) or []:
            if _walk(child):
                found = True
        if found:
            try:
                lc.exclude = False
            except Exception:
                pass
            try:
                lc.hide_viewport = False
            except Exception:
                pass
        return found

    try:
        _walk(root)
    except Exception:
        pass


def _object_owning_action(action):
    """Object whose NLA actually holds this Action (nested GO, stale names)."""
    if action is None:
        return None
    for obj in bpy.data.objects:
        ad = getattr(obj, "animation_data", None)
        if not ad:
            continue
        for track in ad.nla_tracks:
            for strip in track.strips:
                if getattr(strip, "action", None) is action:
                    return obj
    return None


def _row_clip_name(item):
    return (getattr(item, "clip_name", "") or getattr(item, "name", "") or "")


def _paren_title(name, owner):
    """``clip (Rescalar.obj.007)`` — always wrap the bare Action name."""
    name = name or "?"
    owner = _parse_f2_identity(owner or "", name, owner or "")
    if owner and owner != name:
        return "%s (%s)" % (name, owner)
    return name


def _repair_nested_action_name(action, clip_name):
    """Undo ``dish (dish (Rescalar) a) b`` Action names from a nested F2 wrap."""
    if action is None:
        return
    try:
        old = action.name or ""
    except Exception:
        return
    clip = (clip_name or "").strip()
    if not clip:
        try:
            clip = str(action.get("mu_clip_name") or "")
        except Exception:
            clip = ""
    peeled = _parse_f2_identity(old, clip, old)
    if not peeled or peeled == old:
        return
    try:
        action.name = peeled
    except Exception:
        pass


def _repair_all_nested_action_names():
    """Fix Action datablocks already saved with ``clip (name)`` wrappers."""
    try:
        actions = list(bpy.data.actions)
    except Exception:
        return
    for action in actions:
        try:
            if not (action.get("mu_clip_name")
                    or action.get("mu_anim_bobj")
                    or action.get("mu_nla_owner")):
                continue
        except Exception:
            continue
        try:
            clip = str(action.get("mu_clip_name") or "")
        except Exception:
            clip = ""
        _repair_nested_action_name(action, clip)


def _row_curve_label(item):
    """Unique NLA Action name (``Rescalar.obj.007``), else the object name."""
    an = getattr(item, "action_name", "") or ""
    if an:
        return an
    return _row_owner(item)


def _action_object_prefix(action_name):
    """``AntennaCap∧.obj.001`` → ``AntennaCap∧`` (keep ∧; do not strip_nnn first)."""
    an = (action_name or "").strip()
    if not an:
        return ""
    if len(an) > 4 and an[-4] == "." and an[-3:].isdigit():
        an = an[:-4]
    for suffix in (".obj", ".pose", ".data"):
        if an.endswith(suffix):
            return an[:-len(suffix)]
    return an


def _iter_hierarchy(root):
    if root is None:
        return
    stack = [root]
    seen = set()
    while stack:
        obj = stack.pop()
        try:
            ptr = obj.as_pointer()
        except Exception:
            ptr = id(obj)
        if ptr in seen:
            continue
        seen.add(ptr)
        yield obj
        try:
            children = list(obj.children)
        except Exception:
            children = []
        if children:
            stack.extend(reversed(children))


def _named_in_hierarchy(root, prefix):
    """Find ``prefix`` under ``root`` (exact, then ∧/.NNN variants)."""
    if root is None or not prefix:
        return None
    prefix = str(prefix)
    try:
        base = strip_nnn(prefix)
    except Exception:
        base = prefix
    base_hit = None
    prefix_hit = None
    for obj in _iter_hierarchy(root):
        on = obj.name or ""
        if on == prefix:
            return obj
        if base_hit is None:
            try:
                if strip_nnn(on) == base:
                    base_hit = obj
            except Exception:
                pass
        if prefix_hit is None and (
                on.startswith(prefix + ".") or on.startswith(prefix + "∧")):
            prefix_hit = obj
    return base_hit or prefix_hit


def _object_from_action_name(action_name):
    """``AntennaCap∧.obj`` / ``Rescalar.obj.007`` → scene object, not the NLA host."""
    an = (action_name or "").strip()
    if not an:
        return None
    prefix = _action_object_prefix(an)
    for cand in (an, prefix):
        if not cand:
            continue
        obj = _object_by_name(cand)
        if obj is not None:
            return obj
        if "^" in cand:
            obj = _object_by_name(cand.replace("^", "∧"))
            if obj is not None:
                return obj
    return None


def _import_root_of(obj):
    """Top of the imported .mu hierarchy (Animation GO is often a sibling)."""
    if obj is None:
        return None
    want = _mu_import_id_of_object(obj) or _import_id_from_object_chain(obj)
    top = obj
    seen = set()
    p = getattr(obj, "parent", None)
    while p is not None:
        try:
            ptr = p.as_pointer()
        except Exception:
            ptr = id(p)
        if ptr in seen:
            break
        seen.add(ptr)
        pid = _mu_import_id_of_object(p) or _import_id_from_object_chain(p)
        if want and pid and pid != want:
            break
        top = p
        p = getattr(p, "parent", None)
    return top


def _named_in_import_id(prefix, import_id):
    if not prefix or not import_id:
        return None
    try:
        base = strip_nnn(prefix)
    except Exception:
        base = prefix
    base_hit = None
    for obj in bpy.data.objects:
        oid = _mu_import_id_of_object(obj)
        if oid and oid != import_id:
            continue
        if not oid:
            if _import_id_from_object_chain(obj) != import_id:
                continue
        on = obj.name or ""
        if on == prefix:
            return obj
        if base_hit is None:
            try:
                if strip_nnn(on) == base:
                    base_hit = obj
            except Exception:
                pass
    return base_hit


def _resolve_curve_object(action_name, nla_obj, host_key):
    """Object named by the Action — search the whole import, not only the host."""
    prefix = _action_object_prefix(action_name)
    roots = []
    seen = set()
    import_id = ""

    def _add_root(obj):
        nonlocal import_id
        if obj is None:
            return
        try:
            ptr = obj.as_pointer()
        except Exception:
            ptr = id(obj)
        if ptr in seen:
            return
        seen.add(ptr)
        roots.append(obj)
        if not import_id:
            import_id = (
                _mu_import_id_of_object(obj)
                or _import_id_from_object_chain(obj)
            )
        root = _import_root_of(obj)
        if root is not None:
            try:
                rptr = root.as_pointer()
            except Exception:
                rptr = id(root)
            if rptr not in seen:
                seen.add(rptr)
                roots.append(root)

    _add_root(nla_obj)
    for obj in _objects_for_host_key(host_key):
        _add_root(obj)
    for root in roots:
        hit = _named_in_hierarchy(root, prefix)
        if hit is not None:
            return hit
        if action_name and action_name != prefix:
            hit = _named_in_hierarchy(root, action_name)
            if hit is not None:
                return hit
    if import_id:
        hit = _named_in_import_id(prefix, import_id)
        if hit is not None:
            return hit
    return _object_from_action_name(action_name)


def _bind_row_target(row, action, host_key, display, tip_kind="Curve"):
    """Fill label (tree text) and target_name (Scene Collection object)."""
    an = ""
    if action is not None:
        try:
            an = action.name or ""
        except Exception:
            an = ""
    nla = _object_owning_action(action) if action is not None else None
    obj = _resolve_curve_object(an, nla, host_key)
    if obj is not None:
        row.target_name = obj.name
    else:
        row.target_name = _action_object_prefix(an)
    inner = display or an
    if tip_kind in ("Action", "Curve"):
        inner = _parse_f2_identity(
            inner, getattr(row, "clip_name", "") or "", an or inner)
        try:
            row.name = inner or row.name
        except Exception:
            pass
    _set_row_tip_fields(row, tip_kind, inner)


def _select_nla_action(obj, action):
    """Highlight the NLA track/strip for this Action (Outliner NLA list)."""
    if action is None:
        return
    targets = []
    if obj is not None:
        targets.append(obj)
    try:
        owner_name = _find_nla_owner(action)
    except Exception:
        owner_name = ""
    extra = _object_by_name(owner_name)
    if extra is not None and extra not in targets:
        targets.append(extra)
    owned = _object_owning_action(action)
    if owned is not None and owned not in targets:
        targets.insert(0, owned)
    for id_data in targets:
        ad = getattr(id_data, "animation_data", None)
        if not ad:
            continue
        for track in ad.nla_tracks:
            hit = False
            for strip in track.strips:
                is_hit = getattr(strip, "action", None) == action
                try:
                    strip.select = bool(is_hit)
                except Exception:
                    pass
                if is_hit:
                    hit = True
            try:
                track.select = hit
            except Exception:
                pass


def _row_owner(item):
    owner = getattr(item, "owner", "") or ""
    if owner:
        return owner
    aname = getattr(item, "action_name", "") or ""
    if not aname:
        return ""
    act = bpy.data.actions.get(aname)
    if act is None:
        return ""
    try:
        stored = str(act.get("mu_nla_owner") or "")
        if stored:
            return stored
    except Exception:
        pass
    return _find_nla_owner(act)


def _on_anim_rows_index(self, context):
    if _anim_ui_guard:
        return
    try:
        idx = int(self.rows_index)
        item = self.rows[idx]
    except Exception:
        return
    obj = None
    action = None
    aname = getattr(item, "action_name", "") or ""
    if aname:
        action = bpy.data.actions.get(aname)
    kind = getattr(item, "kind", "")
    tname = getattr(item, "target_name", "") or ""
    if tname:
        obj = _object_by_name(tname)
    if kind == "host":
        if obj is None:
            objs = _objects_for_host_key(item.host_key)
            obj = objs[0] if objs else None
    elif kind in ("clip", "target"):
        # Prefer the animated GO (AntennaCap∧), not the parent that holds NLA.
        nla_obj = _object_owning_action(action) if action is not None else None
        if obj is None:
            obj = _resolve_curve_object(aname, nla_obj, item.host_key)
        if obj is None:
            owner = _row_owner(item)
            if owner:
                obj = _object_by_name(owner)
        if obj is None:
            obj = nla_obj
        if obj is None and kind == "clip":
            objs = _objects_for_host_key(item.host_key)
            obj = objs[0] if objs else None
    _select_scene_object(context, obj)
    _select_nla_action(obj, action)


def _rename_action_datablock(old_name, new_name):
    """Rename a Blender Action; return the actual new name (may uniquify)."""
    if not old_name or not new_name or old_name == new_name:
        return old_name
    act = bpy.data.actions.get(old_name)
    if act is None:
        return old_name
    try:
        act.name = new_name
    except Exception:
        return old_name
    return act.name or new_name


def _rename_unity_clip(host_key, old_clip, new_clip):
    if not host_key or not old_clip or not new_clip or old_clip == new_clip:
        return
    sibs = []
    for action in bpy.data.actions:
        try:
            if _host_key_of_action(action, "") != host_key:
                continue
            if str(action.get("mu_clip_name") or "") != old_clip:
                continue
        except Exception:
            continue
        sibs.append(action)
        try:
            action["mu_clip_name"] = new_clip
        except Exception:
            pass
    if not sibs:
        return
    sib_ids = set(id(a) for a in sibs)
    for obj in bpy.data.objects:
        ad = getattr(obj, "animation_data", None)
        if not ad:
            continue
        for track in ad.nla_tracks:
            try:
                if track.name != old_clip:
                    continue
            except Exception:
                continue
            hit = False
            for strip in track.strips:
                if id(getattr(strip, "action", None)) in sib_ids:
                    hit = True
                    break
            if hit:
                try:
                    track.name = new_clip
                except Exception:
                    pass


_TIP_PROP = {
    "Root": "tip_root",
    "Host": "tip_host",
    "Clip": "tip_clip",
    "Action": "tip_action",
    "Curve": "tip_curve",
}


def _row_display_text(row):
    """Value stored in the editable tip_* field — never the ``clip (…)`` wrap."""
    tip = getattr(row, "tip_kind", "") or ""
    if tip in ("Host", "Root"):
        return getattr(row, "name", "") or ""
    if tip == "Clip":
        return _row_clip_name(row) or getattr(row, "name", "") or ""
    return _parse_f2_identity(
        getattr(row, "action_name", "") or getattr(row, "name", "") or "",
        _row_clip_name(row),
        getattr(row, "action_name", "") or getattr(row, "name", "") or "")


def _set_row_tip_fields(row, tip_kind, display):
    row.tip_kind = tip_kind or ""
    if tip_kind in ("Action", "Curve"):
        display = _parse_f2_identity(
            display or "",
            getattr(row, "clip_name", "") or "",
            display or "")
    row.label = display or ""
    for kind, prop in _TIP_PROP.items():
        try:
            setattr(row, prop, display if kind == tip_kind else "")
        except Exception:
            pass


def _on_row_rename(self, context):
    """F2 on the UIList edits ``name`` — map that to the Object / Action / clip."""
    global _anim_ui_guard
    if _anim_ui_guard:
        return
    new = (getattr(self, "name", "") or "").strip()
    if not new:
        return
    kind = getattr(self, "kind", "")
    if kind == "host":
        obj = _object_by_name(getattr(self, "target_name", "") or "")
        if obj is None:
            objs = _objects_for_host_key(self.host_key)
            obj = objs[0] if objs else None
        if obj is None:
            return
        actual, flags = apply_protected_object_rename(
            obj, merge_blender_protected_rename(obj.name or "", new))
        _anim_ui_guard = True
        try:
            self.name = actual or new
            self.target_name = actual or self.target_name
            if actual:
                self.host_key = "bobj:" + actual
            tip = getattr(self, "tip_kind", "") or "Host"
            _set_row_tip_fields(self, tip, self.name)
            self.name_corrected = bool(flags)
        finally:
            _anim_ui_guard = False
        return
    if kind == "target" or (kind == "clip" and (self.owner or "")):
        parsed = _parse_f2_identity(new, self.clip_name, self.action_name)
        new = merge_blender_protected_rename(
            self.action_name or self.name or "", parsed)
        actual = _rename_action_datablock(self.action_name, new)
        _anim_ui_guard = True
        try:
            self.action_name = actual
            self.name = actual
            tip = getattr(self, "tip_kind", "") or (
                "Action" if kind == "clip" else "Curve")
            _set_row_tip_fields(self, tip, actual)
        finally:
            _anim_ui_guard = False
        return
    if kind == "clip":
        old_clip = self.clip_name or ""
        _rename_unity_clip(self.host_key, old_clip, new)
        _anim_ui_guard = True
        try:
            self.clip_name = new
            self.name = new
            _set_row_tip_fields(self, getattr(self, "tip_kind", "") or "Clip", new)
            self.name_corrected = False
        finally:
            _anim_ui_guard = False


def _on_tip_rename(self, context):
    """In-place / F2 edit of the visible Host/Clip/Action/Curve field."""
    global _anim_ui_guard
    if _anim_ui_guard:
        return
    tip = getattr(self, "tip_kind", "") or ""
    prop = _TIP_PROP.get(tip)
    new_disp = (getattr(self, prop, "") or "").strip() if prop else ""
    if not new_disp:
        _anim_ui_guard = True
        try:
            _set_row_tip_fields(self, tip, _row_display_text(self))
        finally:
            _anim_ui_guard = False
        return
    if tip in ("Host", "Root", "Clip"):
        if tip in ("Host", "Root"):
            obj = _object_by_name(getattr(self, "target_name", "") or "")
            if obj is None:
                objs = _objects_for_host_key(self.host_key)
                obj = objs[0] if objs else None
            old = (obj.name if obj is not None else self.name) or ""
            ident = merge_blender_protected_rename(old, new_disp)
        else:
            ident = new_disp
    else:
        parsed = _parse_f2_identity(
            new_disp, self.clip_name, self.action_name)
        ident = merge_blender_protected_rename(
            self.action_name or self.name or "", parsed)
    if ident != (self.name or ""):
        self.name = ident
    display = _row_display_text(self)
    _anim_ui_guard = True
    try:
        _set_row_tip_fields(self, tip, display)
        if tip in ("Host", "Root"):
            self.name_corrected = bool(
                self.name_corrected or new_disp != display)
        else:
            self.name_corrected = bool(new_disp != display)
    finally:
        _anim_ui_guard = False


def _anim_row_tip_text(item, has_kids):
    """Tooltip: Root / Host / Clip / Action / Curve."""
    kind = getattr(item, "kind", "") or ""
    if kind == "host":
        objs = _objects_for_host_key(getattr(item, "host_key", "") or "")
        obj = objs[0] if objs else None
        if obj is not None and getattr(obj, "parent", None) is None:
            return "Root"
        return "Host"
    if kind == "clip":
        return "Clip" if has_kids else "Action"
    if kind == "target":
        return "Curve"
    return ""


def _anim_list_name_fit(context, display, depth, show_tri, is_host, wrap_txt):
    """Left-aligned label; ellipsis only when text would pass ~10px before Clamp."""
    display = display or ""
    try:
        scale = float(context.preferences.system.ui_scale)
    except Exception:
        scale = 1.0
    try:
        region_w = float(context.region.width)
    except Exception:
        region_w = 280.0
    # ui_units_x on the right column (see draw_item) → approx px
    right_u = 4.4 if is_host else (4.5 if "/" in (wrap_txt or "") else 2.8)
    right_px = right_u * 20.0 * scale
    chrome_px = (
        max(0, int(depth)) * 18.0
        + (16.0 if show_tri else 0.0)
        + 20.0  # row icon
        + 28.0  # list padding / scrollbar
    ) * scale
    gap_px = 10.0 * scale
    avail_px = region_w - right_px - chrome_px - gap_px
    char_w = 7.2 * scale
    max_chars = max(4, int(avail_px / char_w))
    if len(display) <= max_chars:
        return display
    return display[: max(1, max_chars - 1)] + "…"


class KSPMU_PG_AnimRowItem(PropertyGroup):
    """One row in the MU Animation list."""
    kind: StringProperty(name="Kind", default="clip")  # "host" | "clip" | "target"
    host_key: StringProperty(name="Host Key", default="")
    name: StringProperty(name="Name", default="", update=_on_row_rename)
    clip_name: StringProperty(name="Clip", default="")
    owner: StringProperty(name="Owner", default="")
    action_name: StringProperty(name="Action", default="")
    target_name: StringProperty(name="Target", default="")
    label: StringProperty(name="Label", description="Display name", default="")
    tip_kind: StringProperty(name="", description="", default="")
    tip_root: StringProperty(
        name="Root", description="", default="", update=_on_tip_rename)
    tip_host: StringProperty(
        name="Host", description="", default="", update=_on_tip_rename)
    tip_clip: StringProperty(
        name="Clip", description="", default="", update=_on_tip_rename)
    tip_action: StringProperty(
        name="Action", description="", default="", update=_on_tip_rename)
    tip_curve: StringProperty(
        name="Curve", description="", default="", update=_on_tip_rename)
    name_corrected: BoolProperty(
        name="Name corrected",
        description="Shown when ∧ / .NNN or a nested clip wrap was snapped back",
        default=False)
    wrap: IntProperty(name="Wrap", default=1)
    curve_wrap: IntProperty(name="Curve Wrap", default=8)
    autoplay: BoolProperty(
        name="Auto Play",
        description="MuAnimation.autoPlay for this host",
        default=False, update=_on_row_autoplay)
    expanded: BoolProperty(
        name="Expanded",
        description="Expand or collapse this row",
        default=True)
    depth: IntProperty(name="Depth", default=0)


class KSPMU_PG_AnimClipsHost(PropertyGroup):
    """Host for the scrollable MU animation tree (on WindowManager)."""
    rows: CollectionProperty(
        type=KSPMU_PG_AnimRowItem,
        name="",
        description="")
    rows_index: IntProperty(
        name="",
        description="",
        default=0, update=_on_anim_rows_index)


_OB_TYPE_ICON = {
    "MESH": "OUTLINER_OB_MESH",
    "EMPTY": "OUTLINER_OB_EMPTY",
    "ARMATURE": "OUTLINER_OB_ARMATURE",
    "LIGHT": "OUTLINER_OB_LIGHT",
    "CAMERA": "OUTLINER_OB_CAMERA",
    "CURVE": "OUTLINER_OB_CURVE",
    "FONT": "OUTLINER_OB_FONT",
    "LATTICE": "OUTLINER_OB_LATTICE",
    "SURFACE": "OUTLINER_OB_SURFACE",
    "META": "OUTLINER_OB_META",
    "VOLUME": "OUTLINER_OB_VOLUME",
    "GPENCIL": "OUTLINER_OB_GREASEPENCIL",
    "GREASEPENCIL": "OUTLINER_OB_GREASEPENCIL",
    "SPEAKER": "OUTLINER_OB_SPEAKER",
}


def _row_scene_object(item):
    tname = getattr(item, "target_name", "") or ""
    obj = _object_by_name(tname) if tname else None
    if obj is None and getattr(item, "kind", "") == "host":
        objs = _objects_for_host_key(getattr(item, "host_key", "") or "")
        obj = objs[0] if objs else None
    return obj


def _prop_icon_kwargs(layout, item, fallback):
    """Outliner-style icon for the row's scene object, else ``fallback``."""
    obj = _row_scene_object(item)
    if obj is not None:
        try:
            ic = layout.icon(obj)
            if ic:
                return {"icon_value": int(ic)}
        except Exception:
            pass
        try:
            named = _OB_TYPE_ICON.get(obj.type)
            if named:
                return {"icon": named}
        except Exception:
            pass
    return {"icon": fallback}


class KSPMU_UL_AnimClipList(bpy.types.UIList):
    """Collapsible host → Unity clip → target tree."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if self.layout_type not in {'DEFAULT', 'COMPACT'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='ACTION')
            return
        has_kids = False
        depth = int(item.depth)
        try:
            nxt = data.rows[index + 1]
            has_kids = int(nxt.depth) > depth
        except Exception:
            has_kids = False
        layout.use_property_split = False
        layout.use_property_decorate = False
        row_tip = (
            _anim_row_tip_text(item, has_kids)
            or getattr(item, "tip_kind", "")
            or "")
        if row_tip and (getattr(item, "tip_kind", "") or "") != row_tip:
            try:
                item.tip_kind = row_tip
            except Exception:
                pass
        is_host = item.kind == "host"
        if is_host:
            fallback_icon = 'OUTLINER_OB_EMPTY'
            wrap_txt = ""
        elif item.kind == "clip" and has_kids:
            fallback_icon = 'NLA'
            wrap_txt = _wrap_short(item.wrap)
        elif item.kind == "clip":
            fallback_icon = 'ACTION'
            wrap_txt = "%s/%s" % (
                _wrap_short(item.wrap), _wrap_short(item.curve_wrap))
        else:
            fallback_icon = 'ACTION'
            wrap_txt = _wrap_short(item.curve_wrap)
        # KSPedia-style left column: BLANK1 + prop(emboss=False) left-aligns
        # and ellipsizes at the widget's right edge. Fixed ui_units_x sibling
        # keeps Auto Play / Clamp (~10px gap). Row tooltip text comes from
        # template_list item_dyntip_propname="tip_kind" (not editable here).
        row = layout.row(align=True)
        for _ in range(max(0, depth)):
            row.label(text="", icon='BLANK1')
        show_tri = is_host or (item.kind == "clip" and has_kids)
        if show_tri:
            icon_tri = 'TRIA_DOWN' if item.expanded else 'TRIA_RIGHT'
            tri = row.row(align=True)
            tri.scale_x = 0.85
            tri.prop(item, "expanded", text="", icon=icon_tri, emboss=False)
        propname = _TIP_PROP.get(row_tip, "") or "name"
        icon_kw = (
            _prop_icon_kwargs(row, item, fallback_icon)
            if is_host else {"icon": fallback_icon})
        try:
            row.alert = bool(item.name_corrected)
        except Exception:
            pass
        row.prop(item, propname, text="", emboss=False, **icon_kw)
        st = row.row(align=False)
        st.alignment = 'RIGHT'
        if is_host:
            st.ui_units_x = 4.4
            col = st.column(align=False)
            col.separator(factor=0.08)
            btn = col.row()
            btn.scale_x = 0.65
            btn.scale_y = 0.80
            btn.prop(item, "autoplay", text="Auto Play", toggle=True)
            col.separator(factor=0.30)
        else:
            st.ui_units_x = 4.5 if "/" in wrap_txt else 2.8
            op = st.operator(
                "object.ksp_mu_anim_row_tip",
                text=wrap_txt,
                emboss=False)
            op.index = index
            op.tip = row_tip

    def filter_items(self, context, data, propname):
        """Hide children under collapsed hosts / Unity clips."""
        try:
            self.use_filter_show = False
        except Exception:
            pass
        nodes = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(nodes)
        flt_neworder = list(range(len(nodes)))
        collapse_depth = None
        for i, node in enumerate(nodes):
            depth = int(node.depth)
            if collapse_depth is not None:
                if depth > collapse_depth:
                    flt_flags[i] = 0
                    continue
                collapse_depth = None
            if node.kind in ("host", "clip") and not node.expanded:
                collapse_depth = depth
        return flt_flags, flt_neworder


def _anim_clips_host(context):
    wm = context.window_manager
    return getattr(wm, "ksp_mu_anim_ui", None)


def _entries_signature(entries):
    """Stable signature for the complete MU animation tree.

    Wrap / autoplay are omitted so toggling them does not rebuild (and
    un-depress) the list.
    """
    parts = []
    for ent in entries:
        act = ent.get("action")
        an = act.name if act is not None else ""
        host = ent.get("anim_host") or ""
        bobj = ent.get("anim_bobj") or ""
        parts.append(
            "%s\x00%s\x00%s\x00%s\x00%s"
            % (
                ent.get("clip_name") or "",
                ent.get("owner") or "",
                host,
                bobj,
                an,
            )
        )
    return "\n".join(parts)


def _sync_anim_clip_collection(context, entries):
    """Rebuild tree rows only when clip/host data actually changed."""
    global _anim_tree_sig, _anim_ui_guard
    ui = _anim_clips_host(context)
    if ui is None:
        return None
    coll = ui.rows
    _repair_all_nested_action_names()
    for ent in entries:
        try:
            _repair_nested_action_name(
                ent.get("action"), ent.get("clip_name") or "")
        except Exception:
            pass
    sig = _entries_signature(entries)

    def _cw_int(act):
        cw = _curve_wrap_of_action(act)
        if cw in (1, 2, 4, 8):
            return int(cw)
        return 8

    # Lightweight refresh of autoplay / wrap flags without clearing selection
    if sig == _anim_tree_sig and len(coll) > 0:
        by_action = {}
        for ent in entries:
            act = ent.get("action")
            if act is not None:
                by_action[act.name] = ent
        _anim_ui_guard = True
        try:
            for r in coll:
                if r.kind in ("clip", "target") and r.action_name in by_action:
                    ent = by_action[r.action_name]
                    r.wrap = int(ent.get("wrap") or 1)
                    r.curve_wrap = _cw_int(ent.get("action"))
                elif r.kind == "host":
                    r.autoplay = _read_host_autoplay(r.host_key)
        finally:
            _anim_ui_guard = False
        return ui

    # Full rebuild: host → Unity MuClip → (targets if the clip splits)
    expand_map = {}
    prev_key = ""
    try:
        for r in coll:
            if r.kind == "host":
                expand_map[("host", r.host_key)] = bool(r.expanded)
            elif r.kind == "clip":
                expand_map[("clip", r.host_key, _row_clip_name(r))] = bool(r.expanded)
        idx = int(ui.rows_index)
        if 0 <= idx < len(coll):
            prev_key = "%s|%s|%s|%s" % (
                coll[idx].kind, coll[idx].host_key,
                _row_clip_name(coll[idx]), coll[idx].action_name)
    except Exception:
        pass

    _anim_ui_guard = True
    try:
        coll.clear()
        groups = _group_entries_by_host(entries)
        for g in groups:
            hk = g["host_key"]
            hrow = coll.add()
            hrow.kind = "host"
            hrow.host_key = hk
            hrow.name = g["name"]
            hrow.owner = g["owner"]
            hrow.autoplay = _read_host_autoplay(hk)
            hrow.depth = 0
            hrow.expanded = expand_map.get(("host", hk), True)
            hrow.wrap = 1
            hrow.curve_wrap = 8
            hrow.label = g["name"]
            hobjs = _objects_for_host_key(hk)
            hrow.target_name = hobjs[0].name if hobjs else (g["name"] or "")
            htip = "Host"
            if hobjs and getattr(hobjs[0], "parent", None) is None:
                htip = "Root"
            _set_row_tip_fields(hrow, htip, g["name"])
            if g["clips"]:
                act0 = g["clips"][0].get("action")
                hrow.action_name = act0.name if act0 is not None else ""
            for cname, ents in _group_entries_by_clip_name(g["clips"]):
                act0 = ents[0].get("action") if ents else None
                crow = coll.add()
                crow.kind = "clip"
                crow.host_key = hk
                crow.clip_name = cname
                crow.action_name = act0.name if act0 is not None else ""
                crow.wrap = int(ents[0].get("wrap") or 1) if ents else 1
                crow.curve_wrap = _cw_int(act0)
                crow.autoplay = bool(ents[0].get("autoplay")) if ents else False
                crow.depth = 1
                crow.expanded = expand_map.get(("clip", hk, cname), True)
                if len(ents) == 1:
                    _repair_nested_action_name(act0, cname)
                    if act0 is not None:
                        try:
                            crow.action_name = act0.name or crow.action_name
                        except Exception:
                            pass
                    crow.owner = _entry_owner_name(ents[0])
                    crow.name = (
                        act0.name if act0 is not None else cname)
                    _bind_row_target(
                        crow, act0, hk,
                        act0.name if act0 is not None else "",
                        "Action")
                else:
                    crow.name = cname
                    crow.owner = ""
                    _bind_row_target(crow, act0, hk, cname, "Clip")
                    for ent in ents:
                        act = ent.get("action")
                        _repair_nested_action_name(act, cname)
                        trow = coll.add()
                        trow.kind = "target"
                        trow.host_key = hk
                        trow.clip_name = cname
                        trow.name = act.name if act is not None else cname
                        trow.owner = _entry_owner_name(ent)
                        trow.action_name = act.name if act is not None else ""
                        trow.wrap = int(ent.get("wrap") or 1)
                        trow.curve_wrap = _cw_int(act)
                        trow.autoplay = bool(ent.get("autoplay"))
                        trow.depth = 2
                        trow.expanded = True
                        _bind_row_target(
                            trow, act, hk,
                            act.name if act is not None else cname,
                            "Curve")
    finally:
        _anim_ui_guard = False

    new_idx = 0
    if prev_key:
        for i, r in enumerate(coll):
            key = "%s|%s|%s|%s" % (
                r.kind, r.host_key, _row_clip_name(r), r.action_name)
            if key == prev_key:
                new_idx = i
                break
    _anim_ui_guard = True
    try:
        ui.rows_index = min(new_idx, max(0, len(coll) - 1))
    except Exception:
        pass
    finally:
        _anim_ui_guard = False
    _anim_tree_sig = sig
    return ui


def _ensure_parts_populated(context, br):
    """Fill br.parts for the current category when the list is still empty.

    First open of the MU tab often has category enum set but parts never
    scanned — category change triggers refresh, plain tab open does not.
    """
    if br is None:
        return
    try:
        if len(br.parts) > 0:
            return
    except Exception:
        return
    try:
        from . import operators
        operators.refresh_part_list(context)
    except Exception:
        pass


def _ensure_first_part_preview(br):
    """Force first category part into the icon view (parts_index + part_preview).

    template_icon_view binds to ``part_preview`` EnumProperty; setting only
    ``parts_index`` leaves the thumbnail blank until the user changes category.
    Always re-assert PART_<index> via the enum string cache used by properties.
    """
    if br is None:
        return
    try:
        n = len(br.parts)
    except Exception:
        return
    if n <= 0:
        return
    try:
        idx = int(br.parts_index)
    except Exception:
        idx = -1
    if idx < 0 or idx >= n:
        idx = 0
        try:
            br.parts_index = 0
        except Exception:
            pass
    # Always sync part_preview → PART_<idx> (enum identity must match cache)
    try:
        from .properties import _enum_cache_string
        target = _enum_cache_string("PART_%d" % idx)
    except Exception:
        target = "PART_%d" % idx
    try:
        cur = str(br.part_preview or "")
    except Exception:
        cur = ""
    if cur != target and cur != ("PART_%d" % idx):
        try:
            br.part_preview = target
        except Exception:
            try:
                from .properties import _reset_part_selection
                _reset_part_selection(br)
            except Exception:
                try:
                    br.part_preview = "PART_%d" % idx
                except Exception:
                    pass
    # If still empty/invalid after assign, hard reset to first item
    try:
        cur2 = str(br.part_preview or "")
        if not cur2.startswith("PART_"):
            br.parts_index = 0
            try:
                from .properties import _reset_part_selection
                _reset_part_selection(br)
            except Exception:
                try:
                    from .properties import _enum_cache_string
                    br.part_preview = _enum_cache_string("PART_0")
                except Exception:
                    br.part_preview = "PART_0"
    except Exception:
        pass


_last_anim_row_click = {}


class KSPMU_OT_anim_row_tip(bpy.types.Operator):
    bl_idname = "object.ksp_mu_anim_row_tip"
    bl_label = "Rename"
    bl_description = ""
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0)
    kind: StringProperty(default="")
    has_kids: BoolProperty(default=False)
    tip: StringProperty(default="")
    allow_rename: BoolProperty(default=False)
    rename: StringProperty(name="Name", default="")

    @classmethod
    def description(cls, context, properties):
        return getattr(properties, "tip", "") or ""

    def draw(self, context):
        self.layout.prop(self, "rename", text="")

    def invoke(self, context, event):
        import time
        ui = _anim_clips_host(context)
        if ui is None:
            return {'CANCELLED'}
        try:
            idx = int(self.index)
            ui.rows_index = idx
        except Exception:
            return {'CANCELLED'}
        if not bool(self.allow_rename):
            return {'FINISHED'}
        now = time.monotonic()
        prev = _last_anim_row_click.get(idx, 0.0)
        _last_anim_row_click[idx] = now
        is_double = (
            getattr(event, "value", "") == 'DOUBLE_CLICK'
            or (now - prev) < 0.4
        )
        if not is_double:
            return {'FINISHED'}
        try:
            item = ui.rows[idx]
        except Exception:
            return {'CANCELLED'}
        tip = getattr(item, "tip_kind", "") or ""
        prop = _TIP_PROP.get(tip, "") or "name"
        self.rename = (
            getattr(item, prop, "") or getattr(item, "name", "") or "")
        return context.window_manager.invoke_props_dialog(self, width=240)

    def execute(self, context):
        ui = _anim_clips_host(context)
        if ui is None:
            return {'CANCELLED'}
        try:
            idx = int(self.index)
            ui.rows_index = idx
        except Exception:
            return {'CANCELLED'}
        new = (self.rename or "").strip()
        if new and bool(self.allow_rename):
            try:
                item = ui.rows[idx]
            except Exception:
                return {'CANCELLED'}
            tip = getattr(item, "tip_kind", "") or ""
            prop = _TIP_PROP.get(tip, "") or "name"
            try:
                setattr(item, prop, new)
            except Exception:
                return {'CANCELLED'}
        return {'FINISHED'}


class KSPMU_OT_toggle_anim_section(bpy.types.Operator):
    bl_idname = "object.ksp_mu_toggle_anim_section"
    bl_label = "Toggle Animation Section"
    bl_description = "Expand or collapse the MU Animation clip list"
    bl_options = {'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        global _anim_section_expanded
        _anim_section_expanded = not _anim_section_expanded
        return {'FINISHED'}


class KSPMU_OT_toggle_fx_section(bpy.types.Operator):
    bl_idname = "object.ksp_mu_toggle_fx_section"
    bl_label = "Toggle FX Section"
    bl_description = "Expand or collapse a viewport preview ribbon"
    bl_options = {'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    section: StringProperty(name="Section", default="fx")

    def execute(self, context):
        global _preview_section_expanded
        key = self.section or "fx"
        _preview_section_expanded[key] = not _preview_section_expanded.get(
            key, False)
        return {'FINISHED'}


def _selected_anim_row(context, kinds=None):
    ui = _anim_clips_host(context)
    if ui is None:
        return None, None
    try:
        item = ui.rows[int(ui.rows_index)]
    except Exception:
        return ui, None
    if kinds is not None and getattr(item, "kind", "") not in kinds:
        return ui, None
    return ui, item


def _selected_clip_row(context):
    """Unity MuClip row (kind=clip), not a per-target Action."""
    return _selected_anim_row(context, kinds=("clip",))


def _clip_row_has_targets(ui, item, index):
    try:
        nxt = ui.rows[int(index) + 1]
        return (
            getattr(nxt, "kind", "") == "target"
            and nxt.host_key == item.host_key
            and _row_clip_name(nxt) == _row_clip_name(item)
        )
    except Exception:
        return False


def _finish_clip_wrap(ui, item, mode, curve=False):
    """Clip wrap updates every row of that Unity MuClip; curve wrap is per row."""
    global _anim_ui_guard
    _anim_ui_guard = True
    try:
        if curve:
            item.curve_wrap = int(mode)
            return
        clip_name = _row_clip_name(item)
        hk = item.host_key
        for row in ui.rows:
            if (row.kind in ("clip", "target")
                    and row.host_key == hk
                    and _row_clip_name(row) == clip_name):
                row.wrap = int(mode)
    finally:
        _anim_ui_guard = False


def _exec_clip_wrap(context, mode):
    ui, item = _selected_clip_row(context)
    if item is None:
        return {'CANCELLED'}
    action = bpy.data.actions.get(item.action_name)
    if action is None:
        return {'CANCELLED'}
    sibs = list(_unity_clip_siblings(action))
    clip_len = 0.0
    for act in sibs:
        try:
            if act.get("mu_pp_baked"):
                clip_len = max(clip_len, float(act.get("mu_clip_length") or 0))
        except Exception:
            pass
    if clip_len <= 0:
        try:
            clip_len = float(actions_clip_length(sibs) or 0)
        except Exception:
            clip_len = 0.0
    for act in sibs:
        try:
            act["mu_clip_wrap_mode"] = int(mode)
            if clip_len > 0 and not act.get("mu_pp_baked"):
                act["mu_clip_length"] = clip_len
        except Exception:
            continue
        apply_mu_clip_wrap_to_action(act, mode)
    _finish_clip_wrap(ui, item, mode, curve=False)
    return {'FINISHED'}


class KSPMU_OT_clip_wrap_once(bpy.types.Operator):
    bl_idname = "object.ksp_mu_clip_wrap_once"
    bl_label = "Once"
    bl_description = "Clip wrap: Once (this Unity MuClip on this host)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_clip_wrap(context, 1)


class KSPMU_OT_clip_wrap_loop(bpy.types.Operator):
    bl_idname = "object.ksp_mu_clip_wrap_loop"
    bl_label = "Loop"
    bl_description = "Clip wrap: Loop (this Unity MuClip on this host)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_clip_wrap(context, 2)


class KSPMU_OT_clip_wrap_pp(bpy.types.Operator):
    bl_idname = "object.ksp_mu_clip_wrap_pp"
    bl_label = "Ping-Pong"
    bl_description = "Clip wrap: Ping-Pong (this Unity MuClip on this host)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_clip_wrap(context, 4)


class KSPMU_OT_clip_wrap_clamp(bpy.types.Operator):
    bl_idname = "object.ksp_mu_clip_wrap_clamp"
    bl_label = "Clamp"
    bl_description = "Clip wrap: Clamp (this Unity MuClip on this host)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_clip_wrap(context, 8)


class KSPMU_OT_curve_wrap_once(bpy.types.Operator):
    bl_idname = "object.ksp_mu_curve_wrap_once"
    bl_label = "Once"
    bl_description = "Curve wrap: Once (this target's curves only)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_curve_wrap(context, 1)


class KSPMU_OT_curve_wrap_loop(bpy.types.Operator):
    bl_idname = "object.ksp_mu_curve_wrap_loop"
    bl_label = "Loop"
    bl_description = "Curve wrap: Loop (this target's curves only)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_curve_wrap(context, 2)


class KSPMU_OT_curve_wrap_pp(bpy.types.Operator):
    bl_idname = "object.ksp_mu_curve_wrap_pp"
    bl_label = "Ping-Pong"
    bl_description = "Curve wrap: Ping-Pong (this target's curves only)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_curve_wrap(context, 4)


class KSPMU_OT_curve_wrap_clamp(bpy.types.Operator):
    bl_idname = "object.ksp_mu_curve_wrap_clamp"
    bl_label = "Clamp"
    bl_description = "Curve wrap: Clamp (this target's curves only)"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    def execute(self, context):
        return _exec_curve_wrap(context, 8)


def _exec_curve_wrap(context, mode):
    ui, item = _selected_anim_row(context, kinds=("clip", "target"))
    if item is None:
        return {'CANCELLED'}
    aidx = 0
    try:
        aidx = int(ui.rows_index)
    except Exception:
        pass
    if item.kind == "clip" and _clip_row_has_targets(ui, item, aidx):
        return {'CANCELLED'}
    action = bpy.data.actions.get(item.action_name)
    if action is None:
        return {'CANCELLED'}
    ok = 0
    for fcurve in iter_action_fcurves(action):
        try:
            if fcurve is None:
                continue
            apply_mu_curve_wrap(action, fcurve, mode, mode)
            ok += 1
        except Exception:
            continue
    if ok == 0:
        return {'CANCELLED'}
    _finish_clip_wrap(ui, item, mode, curve=True)
    return {'FINISHED'}


class KSPMU_OT_set_animation_autoplay(bpy.types.Operator):
    bl_idname = "object.ksp_mu_set_animation_autoplay"
    bl_label = "Set MU Auto Play"
    bl_description = "Toggle MuAnimation.autoPlay for this Animation host only (Unity: one flag per host)"
    bl_options = {'UNDO'}

    @classmethod
    def description(cls, context, properties):
        return cls.bl_description

    host_key: StringProperty(name="Host Key", default="")
    action_name: StringProperty(name="Action", default="")
    value: BoolProperty(name="Auto Play", default=False)

    def execute(self, context):
        value = int(bool(self.value))
        host_key = (self.host_key or "").strip()
        # Resolve host from explicit key or from the representative action
        if not host_key and self.action_name:
            act = bpy.data.actions.get(self.action_name)
            if act is not None:
                host_key = _host_key_of_action(act, "")
        if not host_key and self.action_name:
            # Fallback: only the named action
            act = bpy.data.actions.get(self.action_name)
            if act is not None:
                try:
                    act["mu_auto_play"] = value
                except Exception:
                    pass
            return {'FINISHED'}

        matched = _set_host_autoplay(host_key, value)
        if matched == 0 and self.action_name:
            act = bpy.data.actions.get(self.action_name)
            if act is not None:
                try:
                    act["mu_auto_play"] = value
                except Exception:
                    pass
        return {'FINISHED'}


def _draw_preview_ribbon(layout, key, title, icon, entries):
    """Collapsible viewport-only NLA ribbon (FX / lights / robotics)."""
    if not entries:
        return
    expanded = bool(_preview_section_expanded.get(key, False))
    box = layout.box()
    header = box.row(align=True)
    op = header.operator(
        "object.ksp_mu_toggle_fx_section", text="", emboss=False,
        icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT')
    op.section = key
    if expanded:
        header.label(text=title, icon=icon)
        box.label(
            text="NLA preview — not MuAnimation, skipped on export",
            icon="INFO")
        for ent in entries:
            cname = ent.get("clip_name") or "?"
            box.label(
                text=_paren_title(cname, _entry_owner_name(ent)),
                icon=icon)
    else:
        header.label(text="%s (%d)" % (title, len(entries)), icon=icon)


class VIEW3D_PT_mu_part_browser(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MU"
    bl_label = "Parts (.mu)"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        try:
            from ..import_mu.progress_util import draw_mu_panel_progress
            draw_mu_panel_progress(layout)
        except Exception:
            pass
        wm = context.window_manager
        br = getattr(wm, "ksp_mu_browser", None)

        if br is None:
            layout.label(text="Browser not registered", icon="ERROR")
            return
        try:
            from ..preferences.preferences import Preferences
            gd = (Preferences().GameData or "").strip()
        except Exception:
            gd = ""
        if not gd:
            layout.label(text="Set GameData in Tool > Options", icon="ERROR")
        else:
            layout.label(text=(os.path.basename(gd.rstrip("/\\")) or gd), icon="FILE_FOLDER")

        # Settings stay visible even while a job runs.
        settings_row = layout.row(align=True)
        settings_row.prop(br, "include_stock_thumbs", text="Include stock thumbs")
        settings_row.prop(br, "show_attach_points", text="Show attach points")

        # ---- Loading / exclusive job overlay ----
        # When GameData path is valid and catalog is scanning (or thumbs/regen
        # is running), hide Refresh/Thumbs/Regen, category, search, thumbnails,
        # Import and the part info labels. Only Cancel (+ progress) remains.
        from . import operators as _ops
        from . import catalog as _cat
        job_kind, job_title, job_cur, job_tot = _ops.job_progress()
        catalog_loading = bool(gd) and (
            _cat.catalog_scan_running() or job_kind == "catalog"
        )
        thumbs_busy = job_kind in ("thumbs", "regen")
        hide_browser_controls = bool(gd) and (catalog_loading or thumbs_busy)

        if hide_browser_controls:
            # Blue MU progress bar is drawn above via draw_mu_panel_progress.
            # Only show a cancel control here; hide the rest of the browser UI.
            if thumbs_busy:
                cancel_row = layout.row(align=True)
                if job_kind == "thumbs":
                    cancel_row.operator(
                        "object.ksp_mu_browser_gen_thumbs",
                        text="Cancel Thumbs",
                        icon="CANCEL",
                    )
                else:
                    cancel_row.operator(
                        "object.ksp_mu_browser_regen_thumbs",
                        text="Cancel Regen",
                        icon="CANCEL",
                    )
            elif catalog_loading:
                cancel_row = layout.row(align=True)
                cancel_row.operator(
                    "object.ksp_mu_browser_refresh",
                    text="Scanning… (click to dismiss)",
                    icon="CANCEL",
                )
            # Fallback text if progress_util bar is unavailable
            try:
                from ..import_mu.progress_util import draw_mu_panel_progress as _dpp
            except Exception:
                box = layout.box()
                # job_title already carries "Name N/M (P.P%)" for thumb jobs
                box.label(text=job_title or "Loading…", icon="TIME")
            _ensure_parts_populated(context, br)
        else:
            row = layout.row(align=True)
            row.operator("object.ksp_mu_browser_refresh", text="Refresh", icon="FILE_REFRESH")
            row.operator("object.ksp_mu_browser_gen_thumbs", text="Thumbs", icon="IMAGE_DATA")
            row.operator("object.ksp_mu_browser_regen_thumbs", text="Regen", icon="FILE_REFRESH")
            layout.prop(br, "category", text="")
            layout.prop(br, "filter", text="", icon="VIEWZOOM")
            # First MU-tab open: category may be set while parts are still empty.
            _ensure_parts_populated(context, br)
            _ensure_first_part_preview(br)
            parts = br.parts
            if not parts:
                layout.label(text="No parts in category", icon="INFO")
            else:
                preview_box = layout.box()
                preview_box.template_icon_view(
                    br, "part_preview", show_labels=True,
                    scale=_THUMB_SCALE, scale_popup=_THUMB_SCALE_POPUP)
                try:
                    from . import thumbnails as _th
                    _th.schedule_preview_warmup(br, chunk_size=16)
                except Exception:
                    pass

            row = layout.row(align=True)
            try:
                from .operators import ZIP_BUTTON as _zip_mode
            except Exception:
                _zip_mode = 0
            if int(_zip_mode) > 0:
                # 7/8 Import + 1/8 ZIP
                split = row.split(factor=0.875, align=True)
                left = split.row(align=True)
                right = split.row(align=True)
                op = left.operator(
                    "object.ksp_mu_browser_import_part", text="Import", icon="IMPORT"
                )
                zop = right.operator(
                    "object.ksp_mu_browser_zip_part", text="ZIP", icon="FILE_ARCHIVE"
                )
                if 0 <= br.parts_index < len(br.parts):
                    op.part_name = br.parts[br.parts_index].name
                    zop.part_name = br.parts[br.parts_index].name
            else:
                op = row.operator(
                    "object.ksp_mu_browser_import_part", text="Import", icon="IMPORT"
                )
                if 0 <= br.parts_index < len(br.parts):
                    op.part_name = br.parts[br.parts_index].name
            if 0 <= br.parts_index < len(br.parts):
                item = br.parts[br.parts_index]
                box = layout.box()
                box.label(text="Selected part", icon="IMAGE_DATA")
                row = box.row(align=True)
                row.label(text="Part title: %s" % item.title)
                row = box.row(align=True)
                row.label(text="File name: %s" % item.name)
                if item.attach_rules:
                    row = box.row(align=True)
                    row.label(text="Attach rules: %s" % item.attach_rules)

        # ---- MU Animation (host → clips tree) + viewport FX ----
        entries = _filter_variant_anim_entries(
            context, _mu_animation_entries(context))
        import_id = ""
        try:
            import_id = _resolve_mu_import_id(context) or ""
        except Exception:
            import_id = ""
        previews = []
        if import_id:
            try:
                previews = collect_mu_preview_entries_by_import_id(import_id)
            except Exception:
                previews = []
        lights, fx_ents, robotics = [], [], []
        for ent in previews:
            kind = _preview_section_of(ent)
            if kind == "lights":
                lights.append(ent)
            elif kind == "robotics":
                robotics.append(ent)
            else:
                fx_ents.append(ent)

        if entries:
            box = layout.box()
            header = box.row(align=True)
            header.operator(
                "object.ksp_mu_toggle_anim_section", text="", emboss=False,
                icon='TRIA_DOWN' if _anim_section_expanded else 'TRIA_RIGHT')
            n_hosts = len(_group_entries_by_host(entries))
            n_clips = len(entries)
            if _anim_section_expanded:
                header.label(text="Animation", icon="ANIM")
            else:
                header.label(
                    text="Animation (%d host / %d clip)" % (n_hosts, n_clips),
                    icon="ANIM")
            if hasattr(context.scene, "mu_anim_variant_filter"):
                header.prop(
                    context.scene,
                    "mu_anim_variant_filter",
                    text="All / variant",
                    toggle=True,
                )
            if _anim_section_expanded:
                ui = _sync_anim_clip_collection(context, entries)
                if ui is not None and len(ui.rows) > 0:
                    vis = 0
                    collapse = None
                    for r in ui.rows:
                        d = int(r.depth)
                        if collapse is not None:
                            if d > collapse:
                                continue
                            collapse = None
                        vis += 1
                        if r.kind == "host" and not r.expanded:
                            collapse = d
                        elif r.kind == "clip" and not r.expanded:
                            collapse = d
                    rows = min(max(_ANIM_LIST_DEFAULT_ROWS, 1), _ANIM_LIST_MAX_ROWS)
                    rows = min(rows, max(1, vis))
                    box.template_list(
                        "KSPMU_UL_AnimClipList", "",
                        ui, "rows",
                        ui, "rows_index",
                        rows=rows,
                        maxrows=_ANIM_LIST_MAX_ROWS,
                        # TODO after fixing the mirrored-Y bug in item_dyntip (after Blender fix this)
                        #item_dyntip_propname="tip_kind",
                    )
                    try:
                        aidx = int(ui.rows_index)
                    except Exception:
                        aidx = 0
                    if 0 <= aidx < len(ui.rows):
                        item = ui.rows[aidx]
                        if item.kind == "clip" and item.action_name:
                            action = bpy.data.actions.get(item.action_name)
                            if action is not None:
                                has_targets = _clip_row_has_targets(ui, item, aidx)
                                n_sib = 0
                                try:
                                    n_sib = len(_unity_clip_siblings(action))
                                except Exception:
                                    n_sib = 0
                                detail_name = _paren_title(
                                    _row_clip_name(item) or action.name,
                                    _row_curve_label(item) if not has_targets else "")
                                clip_box = box.box()
                                clip_box.label(
                                    text=detail_name,
                                    icon="NLA" if has_targets else "ACTION")
                                if getattr(item, "name_corrected", False):
                                    clip_box.label(
                                        text="Name snapped (∧ / .NNN kept; clip wrap not nested)",
                                        icon="CHECKMARK")
                                if n_sib > 1:
                                    clip_box.label(
                                        text="Clip Wrap shared by %d targets on this host"
                                        % n_sib,
                                        icon="INFO")
                                clip_wrap = _normalize_wrap(item.wrap)
                                row = clip_box.row(align=True)
                                row.label(text="Clip Wrap")
                                for mode, label, opid in (
                                    (1, "Once", "object.ksp_mu_clip_wrap_once"),
                                    (2, "Loop", "object.ksp_mu_clip_wrap_loop"),
                                    (4, "Ping-Pong", "object.ksp_mu_clip_wrap_pp"),
                                    (8, "Clamp", "object.ksp_mu_clip_wrap_clamp"),
                                ):
                                    row.operator(opid, text=label, depress=(clip_wrap == mode))
                                if not has_targets:
                                    cw = int(item.curve_wrap or 0)
                                    row = clip_box.row(align=True)
                                    row.label(text="Curve Wrap")
                                    for mode, label, opid in (
                                        (1, "Once", "object.ksp_mu_curve_wrap_once"),
                                        (2, "Loop", "object.ksp_mu_curve_wrap_loop"),
                                        (4, "Ping-Pong", "object.ksp_mu_curve_wrap_pp"),
                                        (8, "Clamp", "object.ksp_mu_curve_wrap_clamp"),
                                    ):
                                        row.operator(
                                            opid, text=label, depress=(cw == mode))
                        elif item.kind == "target" and item.action_name:
                            action = bpy.data.actions.get(item.action_name)
                            if action is not None:
                                detail_name = _paren_title(
                                    _row_clip_name(item) or action.name,
                                    _row_curve_label(item))
                                clip_box = box.box()
                                clip_box.label(text=detail_name, icon="ACTION")
                                if getattr(item, "name_corrected", False):
                                    clip_box.label(
                                        text="Name snapped (∧ / .NNN kept; clip wrap not nested)",
                                        icon="CHECKMARK")
                                clip_box.label(
                                    text="Clip Wrap is on the parent clip (%s)"
                                    % (_row_clip_name(item) or "?"),
                                    icon="INFO")
                                cw = int(item.curve_wrap or 0)
                                row = clip_box.row(align=True)
                                row.label(text="Curve Wrap")
                                for mode, label, opid in (
                                    (1, "Once", "object.ksp_mu_curve_wrap_once"),
                                    (2, "Loop", "object.ksp_mu_curve_wrap_loop"),
                                    (4, "Ping-Pong", "object.ksp_mu_curve_wrap_pp"),
                                    (8, "Clamp", "object.ksp_mu_curve_wrap_clamp"),
                                ):
                                    row.operator(opid, text=label, depress=(cw == mode))
                        elif item.kind == "host":
                            if getattr(item, "name_corrected", False):
                                box.label(
                                    text="Name snapped: ∧ / .NNN restored for Unity export",
                                    icon="CHECKMARK")
                            box.label(
                                text="Select a clip to edit Clip Wrap, or a target for Curve Wrap",
                                icon="INFO")
                else:
                    box.label(
                        text="Reload addon to enable animation list",
                        icon="INFO")

        _draw_preview_ribbon(
            layout, "lights", "Lights (viewport)", "LIGHT", lights)
        _draw_preview_ribbon(
            layout, "fx", "FX (viewport)", "SHADERFX", fx_ents)
        _draw_preview_ribbon(
            layout, "robotics", "Robotics (viewport)", "DRIVER", robotics)


classes_to_register = (
    KSPMU_PG_AnimRowItem,
    KSPMU_PG_AnimClipsHost,
    KSPMU_UL_AnimClipList,
    KSPMU_OT_anim_row_tip,
    KSPMU_OT_toggle_anim_section,
    KSPMU_OT_toggle_fx_section,
    KSPMU_OT_clip_wrap_once,
    KSPMU_OT_clip_wrap_loop,
    KSPMU_OT_clip_wrap_pp,
    KSPMU_OT_clip_wrap_clamp,
    KSPMU_OT_curve_wrap_once,
    KSPMU_OT_curve_wrap_loop,
    KSPMU_OT_curve_wrap_pp,
    KSPMU_OT_curve_wrap_clamp,
    KSPMU_OT_set_animation_autoplay,
    VIEW3D_PT_mu_part_browser,
)

# Registered by main __init__ via:
#   setattr(prop[0], prop[1], PointerProperty(type=prop[2]))
custom_properties_to_register = (
    (WindowManager, "ksp_mu_anim_ui", KSPMU_PG_AnimClipsHost),
)
