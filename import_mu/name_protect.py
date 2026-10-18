# vim:ts=4:et
# <pep8 compliant>
"""Keep imported Unity names intact: do not let F2 strip ``∧`` or ``.NNN``.

``create_protected_data_object`` appends ``∧`` so Blender's ``.001`` uniquifier
does not rewrite the Unity transform name. Export ``strip_nnn`` already drops
both ``∧…`` and ``.NNN`` when writing .mu — but deleting ``∧`` in the outliner
collides two objects onto the same Unity name. This handler puts the marks back.
"""
from __future__ import annotations

import re

import bpy
from bpy.app.handlers import persistent

from ..utils.rename_parse import (
    blender_name_has_nnn,
    merge_blender_protected_rename,
)

_WEDGE = "\u2227"
_NNN_RE = re.compile(r"^(.*)(\.\d{3})$")
_protecting = False
_handler = None


def _nnn_suffix(name):
    m = _NNN_RE.match(name or "")
    return m.group(2) if m else ""


def mark_protected_name(obj):
    """Call right after an imported object is created (name already uniquified)."""
    if obj is None:
        return
    try:
        n = obj.name or ""
    except Exception:
        return
    if _WEDGE in n:
        try:
            obj["mu_protect_wedge"] = 1
        except Exception:
            pass
    nnn = _nnn_suffix(n)
    if nnn:
        try:
            obj["mu_protect_nnn"] = nnn
        except Exception:
            pass
    try:
        obj["mu_import_name"] = n
    except Exception:
        pass


def _refresh_protect_flags(obj):
    """Pick up ``∧`` / ``.NNN`` Blender added after the original mark."""
    try:
        n = obj.name or ""
    except Exception:
        return
    if _WEDGE in n:
        try:
            obj["mu_protect_wedge"] = 1
        except Exception:
            pass
    nnn = _nnn_suffix(n)
    if nnn:
        try:
            if not obj.get("mu_protect_nnn"):
                obj["mu_protect_nnn"] = nnn
        except Exception:
            pass


def _restore_name(obj, new_name):
    global _protecting
    if new_name == obj.name:
        return
    _protecting = True
    try:
        obj.name = new_name
    except Exception:
        pass
    finally:
        _protecting = False


def _desired_name(obj):
    """Return corrected name, or None if the current name is already valid."""
    try:
        n = obj.name or ""
    except Exception:
        return None
    changed = False
    if obj.get("mu_protect_wedge") and _WEDGE not in n:
        m = _NNN_RE.match(n)
        if m:
            n = m.group(1) + _WEDGE + m.group(2)
        else:
            n = n + _WEDGE
        changed = True
    nnn = ""
    try:
        nnn = str(obj.get("mu_protect_nnn") or "")
    except Exception:
        nnn = ""
    if nnn and not blender_name_has_nnn(n):
        n = n + nnn
        changed = True
    return n if changed else None


def retarget_anim_object_name(old_name, new_name):
    """Keep MuAnimation tags / Action names pointing at the renamed object."""
    from ..utils.rename_parse import (
        rewrite_action_datablock_name,
        rewrite_path_segments,
    )
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name or old_name == new_name:
        return
    try:
        actions = list(bpy.data.actions)
    except Exception:
        return
    for action in actions:
        try:
            if str(action.get("mu_anim_bobj") or "") == old_name:
                action["mu_anim_bobj"] = new_name
            if str(action.get("mu_nla_owner") or "") == old_name:
                action["mu_nla_owner"] = new_name
            host = str(action.get("mu_anim_host") or "")
            rewritten = rewrite_path_segments(host, old_name, new_name)
            if rewritten != host:
                action["mu_anim_host"] = rewritten
        except Exception:
            pass
        try:
            nxt = rewrite_action_datablock_name(action.name or "", old_name, new_name)
            if nxt and nxt != action.name:
                action.name = nxt
        except Exception:
            pass
    try:
        objects = list(bpy.data.objects)
    except Exception:
        objects = []
    for obj in objects:
        try:
            tagged = str(obj.get("mu_animation_host") or "")
        except Exception:
            continue
        if not tagged:
            continue
        rewritten = rewrite_path_segments(tagged, old_name, new_name)
        if rewritten != tagged:
            try:
                obj["mu_animation_host"] = rewritten
            except Exception:
                pass
    try:
        from ..mu_browser import panels as _anim_panels
        _anim_panels._anim_tree_sig = ""
    except Exception:
        pass


def apply_protected_object_rename(obj, requested):
    """Rename ``obj`` then put ``∧`` / ``.NNN`` back. Returns (actual, flags).

    flags contains ``wedge`` and/or ``nnn`` when those marks were restored
    so the UI can snap the field to ``actual`` immediately.
    """
    global _protecting
    requested = (requested or "").strip()
    if obj is None:
        return "", []
    try:
        old_name = obj.name or ""
    except Exception:
        old_name = ""
    if not requested:
        return old_name, []
    requested = merge_blender_protected_rename(old_name, requested)
    _refresh_protect_flags(obj)
    flags = []
    try:
        if obj.get("mu_protect_wedge") and _WEDGE not in requested:
            flags.append("wedge")
    except Exception:
        pass
    nnn = ""
    try:
        nnn = str(obj.get("mu_protect_nnn") or "")
    except Exception:
        nnn = ""
    if nnn and not blender_name_has_nnn(requested):
        flags.append("nnn")
    _protecting = True
    try:
        obj.name = requested
    except Exception:
        pass
    finally:
        _protecting = False
    desired = _desired_name(obj)
    if desired:
        _restore_name(obj, desired)
    try:
        actual = obj.name or requested
    except Exception:
        actual = requested
    try:
        obj["mu_import_name"] = actual
    except Exception:
        pass
    if old_name and actual and old_name != actual:
        retarget_anim_object_name(old_name, actual)
    return actual, flags


@persistent
def _on_name_protect(scene, depsgraph):
    global _protecting
    if _protecting:
        return
    try:
        updates = depsgraph.updates
    except Exception:
        return
    for upd in updates:
        id_data = getattr(upd, "id", None)
        if id_data is None:
            continue
        try:
            if not isinstance(id_data, bpy.types.Object):
                continue
        except Exception:
            continue
        try:
            obj = bpy.data.objects.get(id_data.name)
        except Exception:
            obj = None
        if obj is None:
            continue
        if "mu_import_id" in obj:
            try:
                n = obj.name or ""
            except Exception:
                n = ""
            if "mu_protect_wedge" not in obj and "mu_protect_nnn" not in obj:
                if _WEDGE in n or _nnn_suffix(n):
                    mark_protected_name(obj)
            else:
                _refresh_protect_flags(obj)
        if not obj.get("mu_protect_wedge") and not obj.get("mu_protect_nnn"):
            continue
        try:
            before = str(obj.get("mu_import_name") or obj.name or "")
        except Exception:
            before = ""
        desired = _desired_name(obj)
        if desired:
            _restore_name(obj, desired)
        try:
            after = obj.name or ""
        except Exception:
            after = ""
        if after:
            try:
                obj["mu_import_name"] = after
            except Exception:
                pass
        if before and after and before != after:
            retarget_anim_object_name(before, after)


def ensure_name_protect_handler():
    global _handler
    if _on_name_protect not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_name_protect)
    _handler = _on_name_protect


def remove_name_protect_handler():
    global _handler
    try:
        if _on_name_protect in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_on_name_protect)
    except Exception:
        pass
    _handler = None
