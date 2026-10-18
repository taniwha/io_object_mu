# vim:ts=4:et
# <pep8 compliant>
"""Persist KSPedia locale RAM buffers into the .blend file.

save_pre  → capture active locale + write Text datablock
load_post → hydrate RAM so other PCs / reopen keep all languages
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

_HANDLERS_OK = False

# Nested undo/redo depth + a short cooldown after undo_post so RNA updates
# that fire at the tail of restore cannot recreate/delete IDs mid-undo.
_UNDO_REDO = 0
_UNDO_COOLDOWN = False


def in_undo_redo() -> bool:
    """True while Blender is restoring an undo/redo step (or just after).

    Property updates and depsgraph live-sync must not create/delete IDs or
    start a locale apply here — that is what crashed Ctrl+Z after Remove Locale.
    """
    return bool(_UNDO_REDO > 0 or _UNDO_COOLDOWN)


def _cancel_locale_work():
    try:
        from .locale_switch import cancel_locale_apply_job
        cancel_locale_apply_job()
    except Exception:
        pass
    try:
        from . import locale_buffers
        locale_buffers.set_live_sync_lock(True)
    except Exception:
        pass


@persistent
def _ksp_undo_redo_pre(_dummy):
    global _UNDO_REDO, _UNDO_COOLDOWN
    _UNDO_REDO += 1
    _UNDO_COOLDOWN = True
    _cancel_locale_work()




def _id_alive(obj) -> bool:
    """False for None or deleted ID pointers (common after merge/delete)."""
    if obj is None:
        return False
    try:
        return bool(obj.name is not None)
    except ReferenceError:
        return False
    except Exception:
        return False


def _clear_dead_pointer(owner, attr: str) -> bool:
    try:
        obj = getattr(owner, attr, None)
    except ReferenceError:
        obj = None
    except Exception:
        return False
    if obj is None:
        return False
    if _id_alive(obj):
        return False
    try:
        setattr(owner, attr, None)
        return True
    except Exception:
        return False


def sanitize_ksp_bundle_pointers(kb, root=None) -> int:
    """Clear dangling PointerProperties so .blend save does not crash."""
    n = 0
    if kb is None:
        return 0
    for attr in ("filter_page_object", "filter_scope_object"):
        if _clear_dead_pointer(kb, attr):
            n += 1
    try:
        for node in list(getattr(kb, "toc_nodes", []) or []):
            for attr in ("page_object", "folder_object"):
                if _clear_dead_pointer(node, attr):
                    n += 1
    except Exception:
        pass
    try:
        for it in list(getattr(kb, "ui_elements", []) or []):
            for attr in ("viewport_object", "image", "text_block"):
                if _clear_dead_pointer(it, attr):
                    n += 1
    except Exception:
        pass
    try:
        for it in list(getattr(kb, "textures", []) or []):
            if _clear_dead_pointer(it, "image"):
                n += 1
    except Exception:
        pass
    try:
        for it in list(getattr(kb, "text_assets", []) or []):
            if _clear_dead_pointer(it, "text_block"):
                n += 1
    except Exception:
        pass
    return n


def _blend_has_ksp_data():
    """True when this .blend actually holds a KSP bundle or locale buffer."""
    try:
        import bpy
    except Exception:
        return False
    try:
        for text in list(getattr(bpy.data, "texts", []) or []):
            if (getattr(text, "name", "") or "").startswith("ksp_locale_buffers"):
                return True
    except Exception:
        pass
    try:
        objects = list(getattr(bpy.data, "objects", []) or [])
    except Exception:
        objects = []
    for obj in objects:
        try:
            if obj.get("ksp_locale_buffers_json"):
                return True
        except Exception:
            pass
        try:
            kb = obj.ksp_bundle
            if getattr(kb, "is_ksp_bundle", False):
                return True
        except Exception:
            continue
    return False


@persistent
def _ksp_locale_save_pre(_dummy):
    if not _blend_has_ksp_data():
        return
    try:
        import bpy
        from . import locale_buffers
        # Dead PointerProperties after merge/delete crash Blender on write.
        for obj in list(getattr(bpy.data, "objects", []) or []):
            try:
                kb = obj.ksp_bundle
                if not getattr(kb, "is_ksp_bundle", False):
                    continue
            except Exception:
                continue
            try:
                sanitize_ksp_bundle_pointers(kb, obj)
            except Exception:
                pass
        n = locale_buffers.flush_all_bundles(allow_new_ids=False)
        if n:
            print("INFO: KSP locale buffers → .blend (%d bundle(s))" % n)
    except Exception as exc:
        try:
            print("WARNING: KSP locale save_pre failed: %s" % exc)
        except Exception:
            pass


@persistent
def _ksp_locale_load_post(_dummy):
    if not _blend_has_ksp_data():
        return
    try:
        from . import locale_buffers
        n = locale_buffers.hydrate_all_bundles()
        if n:
            print("INFO: KSP locale buffers ← .blend (%d locale map(s))" % n)
    except Exception as exc:
        try:
            print("WARNING: KSP locale load_post failed: %s" % exc)
        except Exception:
            pass


@persistent
def _ksp_undo_redo_post(_dummy):
    """Undo restores FONT objects but not the GPU Show Text Boxes cache."""
    global _UNDO_REDO, _UNDO_COOLDOWN
    _UNDO_REDO = max(0, _UNDO_REDO - 1)
    _UNDO_COOLDOWN = True

    def _finish():
        global _UNDO_COOLDOWN
        _UNDO_COOLDOWN = False
        try:
            from . import locale_buffers
            locale_buffers.release_live_sync_lock_deferred(0.15)
        except Exception:
            pass
        try:
            from .locale_switch import resync_text_box_overlays_all
            resync_text_box_overlays_all()
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_finish, first_interval=0.05)
    except Exception:
        _finish()


def ensure_blend_handlers():
    global _HANDLERS_OK
    if _HANDLERS_OK:
        return
    if _ksp_locale_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_ksp_locale_save_pre)
    if _ksp_locale_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_ksp_locale_load_post)
    for hlist, fn in (
        (bpy.app.handlers.undo_pre, _ksp_undo_redo_pre),
        (bpy.app.handlers.redo_pre, _ksp_undo_redo_pre),
        (bpy.app.handlers.undo_post, _ksp_undo_redo_post),
        (bpy.app.handlers.redo_post, _ksp_undo_redo_post),
    ):
        if fn not in hlist:
            hlist.append(fn)
    _HANDLERS_OK = True
    try:
        def _hydrate_after_register():
            if not _blend_has_ksp_data():
                return None
            try:
                from . import locale_buffers
                locale_buffers.hydrate_all_bundles()
            except Exception:
                pass
            return None
        bpy.app.timers.register(_hydrate_after_register, first_interval=0.05)
    except Exception:
        pass


def remove_blend_handlers():
    global _HANDLERS_OK
    pairs = (
        (bpy.app.handlers.save_pre, _ksp_locale_save_pre),
        (bpy.app.handlers.load_post, _ksp_locale_load_post),
        (bpy.app.handlers.undo_pre, _ksp_undo_redo_pre),
        (bpy.app.handlers.redo_pre, _ksp_undo_redo_pre),
        (bpy.app.handlers.undo_post, _ksp_undo_redo_post),
        (bpy.app.handlers.redo_post, _ksp_undo_redo_post),
    )
    for hlist, fn in pairs:
        try:
            if fn in hlist:
                hlist.remove(fn)
        except Exception:
            pass
    _HANDLERS_OK = False