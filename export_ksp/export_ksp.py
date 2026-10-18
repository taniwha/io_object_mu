# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>
"""Export edited KSP .ksp Unity AssetBundles."""

from __future__ import annotations

import io
import json
import os
import shutil
import time

import bpy

from ..import_ksp.bundle import (
    KspBundleError,
    apply_rect_transform,
    apply_text_asset,
    apply_texture_png,
    apply_ui_image,
    apply_ui_style,
    apply_ui_text,
    clear_image_mb_sprite_refs,
    collect_orphan_texture_candidates,
    detect_bundle_compression,
    load_env_for_export,
    purge_unreferenced_texture_assets,
    save_bundle,
    texture_pids_kept_by_blender,
)
from ..import_ksp import ui_roundtrip
from ..import_ksp.deps import ensure_unitypy, last_error
from ..import_ksp.layout import (
    blender_euler_to_unity_ui_quat,
)


def find_bundle_root(obj):
    """Walk parents to find an object with ksp_bundle.is_ksp_bundle.

    Only the selected/active hierarchy is considered - never another
    unrelated bundle root in the scene.
    """
    if obj is None:
        return None
    cur = obj
    while cur is not None:
        try:
            if cur.ksp_bundle.is_ksp_bundle:
                return cur
        except Exception:
            pass
        cur = cur.parent
    return None


def _kb_export_locale(kb, explicit=None) -> str:
    """Language this export_ksp call is writing (sibling .lang ≠ viewport)."""
    if explicit:
        return str(explicit).strip().lower()
    try:
        v = kb.get("_ksp_export_locale")
        if v:
            return str(v).strip().lower()
    except Exception:
        pass
    return (
        str(getattr(kb, "active_locale", "") or "")
        or str(getattr(kb, "locale", "") or "")
    ).strip().lower()


def _vo_skipped_for_locale(vo, loc: str) -> bool:
    """True when a user-added element must not ship in ``loc``."""
    if not loc or vo is None:
        return False
    try:
        from ..import_ksp.locale_buffers import is_forgotten_in_locale
        if is_forgotten_in_locale(vo, loc):
            return True
    except Exception:
        pass
    try:
        shipped = str(vo.get("ksp_shipped_locales") or "").strip()
    except Exception:
        shipped = ""
    if shipped:
        allowed = {x.strip().lower() for x in shipped.split(",") if x.strip()}
        if loc not in allowed:
            return True
    return False


def _deactivate_el_in_env(env, el) -> bool:
    """Turn off a scoped-out GO by MonoBehaviour id, then by export name."""
    did = False
    mid = 0
    try:
        mid = int(getattr(el, "mb_path_id", 0) or 0)
    except Exception:
        mid = 0
    if mid:
        try:
            if ui_roundtrip.set_game_object_active(env, mid, False):
                did = True
        except Exception:
            pass
    names = []
    try:
        vo = getattr(el, "viewport_object", None)
        if vo is not None:
            n = str(vo.get("ksp_export_go_name") or "").strip()
            if n:
                names.append(n)
    except Exception:
        pass
    try:
        n = str(getattr(el, "name", "") or "").strip()
        if n and n not in names:
            names.append(n)
    except Exception:
        pass
    skip_names = {"image", "text", ""}
    for name in names:
        if name.lower() in skip_names:
            continue
        try:
            if ui_roundtrip.set_game_object_active_by_name(env, name, False):
                did = True
        except Exception:
            pass
    return did


def _rect_local_rotation(el, ui_obj, *, prefer_list=False, locale_has_edit=None):
    """Unity quat for this export locale.

    Live euler is only for the viewport-locale ``.ksp``. Sibling ``.lang``
    must use list/maps / import pin — the shared stock object still holds
    the default language's G/R/S.

    ``locale_has_edit=False``: EN export may have baked live R into
    ``el.local_rotation``. Ignore the list row and use the import pin.
    """
    try:
        user_added = bool(ui_obj is not None and ui_obj.get("ksp_user_added"))
    except Exception:
        user_added = False
    pin_first = bool(prefer_list) and (not user_added) and (locale_has_edit is False)
    if pin_first and ui_obj is not None:
        try:
            q = ui_obj.get("ksp_local_rotation", None)
            if q is not None and len(q) >= 4:
                return tuple(float(x) for x in q[:4])
        except Exception:
            pass
    if prefer_list:
        try:
            q = tuple(getattr(el, "local_rotation", (0.0, 0.0, 0.0, 1.0)))
            if len(q) >= 4:
                return (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
        except Exception:
            pass
        if ui_obj is not None:
            try:
                q = ui_obj.get("ksp_local_rotation", None)
                if q is not None and len(q) >= 4:
                    return tuple(float(x) for x in q[:4])
            except Exception:
                pass
    if ui_obj is not None:
        try:
            # Always use live euler - identity early-out previously preferred
            # stale el.local_rotation and skipped real R=0 / small edits.
            return tuple(blender_euler_to_unity_ui_quat(ui_obj.rotation_euler))
        except Exception:
            pass
    try:
        q = tuple(getattr(el, "local_rotation", (0.0, 0.0, 0.0, 1.0)))
        if len(q) >= 4:
            return (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    except Exception:
        pass
    return (0.0, 0.0, 0.0, 1.0)


def _rect_local_scale(el, ui_obj, *, prefer_list=False, locale_has_edit=None):
    # User-added images may bake Blender scale into sizeDelta and leave
    # el.local_scale at identity — prefer that over raw object.scale.
    try:
        user_added = bool(ui_obj is not None and ui_obj.get("ksp_user_added"))
    except Exception:
        user_added = False
    pin_first = bool(prefer_list) and (not user_added) and (locale_has_edit is False)
    if pin_first and ui_obj is not None:
        try:
            raw = ui_obj.get("ksp_local_scale", None)
            if raw is not None and len(raw) >= 3:
                return tuple(float(x) for x in raw[:3])
        except Exception:
            pass
    if prefer_list or user_added:
        try:
            s = tuple(getattr(el, "local_scale", (1.0, 1.0, 1.0)))
            if len(s) >= 3:
                return (float(s[0]), float(s[1]), float(s[2]))
        except Exception:
            pass
        if prefer_list and ui_obj is not None:
            try:
                raw = ui_obj.get("ksp_local_scale", None)
                if raw is not None and len(raw) >= 3:
                    return tuple(float(x) for x in raw[:3])
            except Exception:
                pass
    if ui_obj is not None:
        try:
            return (
                float(ui_obj.scale.x),
                float(ui_obj.scale.y),
                float(ui_obj.scale.z),
            )
        except Exception:
            pass
    try:
        s = tuple(getattr(el, "local_scale", (1.0, 1.0, 1.0)))
        if len(s) >= 3:
            return (float(s[0]), float(s[1]), float(s[2]))
    except Exception:
        pass
    return (1.0, 1.0, 1.0)


def _rect_local_position_z(el, ui_obj):
    try:
        return float(getattr(el, "local_position_z", 0.0) or 0.0)
    except Exception:
        return 0.0


def _image_png_bytes(image):
    if image is None:
        return None
    try:
        if image.packed_file is not None:
            data = image.packed_file.data
            if data:
                return bytes(data)
    except Exception:
        pass
    try:
        from PIL import Image
        w, h = image.size
        pixels = list(image.pixels)
        raw = bytearray(w * h * 4)
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 4
                o = ((h - 1 - y) * w + x) * 4
                raw[o] = int(max(0, min(255, pixels[i] * 255)))
                raw[o + 1] = int(max(0, min(255, pixels[i + 1] * 255)))
                raw[o + 2] = int(max(0, min(255, pixels[i + 2] * 255)))
                raw[o + 3] = int(max(0, min(255, pixels[i + 3] * 255)))
        img = Image.frombytes("RGBA", (w, h), bytes(raw))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _plain_ui_text(s: str) -> str:
    """Tag-stripped body for locale / markup comparisons."""
    import re
    try:
        return re.sub(r"<[^>]+>", "", s or "").strip()
    except Exception:
        return (s or "").strip()


def _collapse_ws(s: str) -> str:
    try:
        return " ".join((s or "").replace("\u2007", " ").split())
    except Exception:
        return (s or "").strip()


def _viewport_text_for_element(root, el, *, expect_locale: str = ""):
    """Find matching viewport UI object text for a list element.

    Prefer ``ksp_ui.text`` (source / TMP markup) over FONT ``body`` (may contain
    soft-wrap figure-spaces). Callers must flush Edit Text / list edits into
    ``ksp_ui`` before export.

    Skip objects whose ``ksp_locale_applied`` disagrees with ``expect_locale``
    so a stale sibling-language FONT cannot poison the main .ksp.
    """
    mb = el.mb_path_id or ""
    name = el.name or ""
    expect = (expect_locale or "").strip().lower()
    if not expect:
        try:
            kb = root.ksp_bundle
            expect = (
                str(getattr(kb, "active_locale", "") or "")
                or str(getattr(kb, "locale", "") or "")
            ).strip().lower()
        except Exception:
            expect = ""
    for obj in [root] + list(root.children_recursive):
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui or ui.kind != "text":
                continue
        except Exception:
            continue
        try:
            if obj.get("ksp_locale_parked"):
                continue
        except Exception:
            pass
        if expect:
            try:
                applied = str(obj.get("ksp_locale_applied") or "").strip().lower()
            except Exception:
                applied = ""
            if applied and applied != expect:
                continue
        if mb and ui.mb_path_id == mb:
            pass
        elif (not mb) and name and ui.element_name == name:
            pass
        else:
            continue
        # ALT / showModCategory pads live in ksp_ui - FONT may have collapsed
        # leading spaces after a locale rebuild.
        try:
            from ..import_ksp.viewport import is_artwork_overlay, preserve_overlay_newlines
            src = str(obj.get("ksp_text_source") or "") or str(ui.text or "")
            if src:
                src = preserve_overlay_newlines(src)
            if src and is_artwork_overlay(src, obj):
                return src
        except Exception:
            pass
        # Prefer live FONT multimaterial / bold markup over stale ksp_ui.text
        # (style edits often leave a plain string in the PropertyGroup).
        try:
            from ..import_ksp.mu_ops import collect_viewport_text_plain
            live = collect_viewport_text_plain(obj) or ""
            low = live.lower()
            if live and ("<color" in low or "<b>" in low or "<i>" in low):
                return live
        except Exception:
            live = ""
        if live:
            live_plain = _plain_ui_text(live)
            ui_plain = _plain_ui_text(ui.text or "")
            live_c = _collapse_ws(live_plain)
            ui_c = _collapse_ws(ui_plain)
            # User appended in the FONT body (Edit Text / extra line). ksp_ui
            # still holds the imported string — keep the extra words.
            if live_c and ui_c and live_c.startswith(ui_c) and len(live_c) > len(ui_c):
                extra = live_plain[len(ui_plain):] if live_plain.startswith(ui_plain) else (
                    live_c[len(ui_c):]
                )
                if extra and not extra[:1] in ("\n", "\r") and "\n" in (live or ""):
                    extra = "\n" + extra.lstrip()
                return (ui.text or "") + extra
        if ui.text:
            return ui.text
        if live:
            return live
        if obj.type == "FONT":
            return obj.data.body
        return ""
    return None


def _normalize_unity_ui_color_tags(text: str) -> str:
    """Normalize ``<color=#…>`` tags (TMP-safe). Prefer ``sanitize_ui_text_for_ksp``.
    """
    if not text or "<color" not in text.lower():
        return text or ""
    try:
        import re
        def _shrink(m):
            hx = (m.group(1) or "").strip()
            if len(hx) >= 6 and all(c in "0123456789abcdefABCDEF" for c in hx[:6]):
                return "<color=#%s>" % hx[:6].upper()
            return m.group(0)
        return re.sub(
            r"<color=#([0-9A-Fa-f]{6,8})(?![0-9A-Fa-f])>",
            _shrink,
            text,
            flags=re.IGNORECASE,
        )
    except Exception:
        return text


def sanitize_ui_text_for_ksp(
    text: str,
    *,
    is_ui_text: bool = False,
    local_rotation=None,
    local_scale=None,
):
    """Prepare text for UnityFS write.

    Keep ``<color>`` / ``<b>`` / ``<i>`` (stock de-de .lang uses them).
    Convert Blender figure-spaces (U+2007/U+2008) back to ASCII spaces so
    Unity UI.Text overlays (ALT / showModCategory pads) keep their indent -
    U+2007 in m_Text collapses and the label jumps to the rect origin.
    Only normalize ``#RRGGBBAA`` → ``#RRGGBB``. Returns ``(text, None)``.
    ``is_ui_text`` / TRS args kept for call-site compatibility.
    """
    del is_ui_text, local_rotation, local_scale  # API compat; no strip
    raw = text if text is not None else ""
    try:
        raw = (
            str(raw)
            .replace(chr(0x2007), " ")
            .replace(chr(0x2008), " ")
            .replace(chr(0x00A0), " ")
        )
    except Exception:
        pass
    return _normalize_unity_ui_color_tags(raw), None


def _resolve_ui_text(root, el, *, prefer_list=False):
    """Resolve export text from viewport and/or ``ui_elements`` list row.

    Default prefers live ``ksp_ui.text``. After ``apply_maps_to_ui_elements``
    for a *non-visible* sibling locale, pass ``prefer_list=True``.

    ``prefer_list=True`` is strict: the list row alone is the source of truth
    (sibling ``.lang`` export). Never fall back to the viewport - it still
    holds the on-screen language (usually EN with ``<b>``) and used to bake
    English into KSPedia XML while MonoBehaviour kept the locale string.
    """
    # Prefer list when requested - INCLUDING empty string (user cleared
    # Configuration body / deleted sentence). ``if list_text`` skipped clears
    # and fell through to stale viewport "By default KPBS…".
    list_text = el.text if el.text is not None else ""
    if prefer_list:
        cleaned, _ = sanitize_ui_text_for_ksp(list_text)
        return cleaned
    expect = ""
    try:
        kb = root.ksp_bundle
        expect = (
            str(getattr(kb, "active_locale", "") or "")
            or str(getattr(kb, "locale", "") or "")
        ).strip().lower()
    except Exception:
        expect = ""
    view_text = _viewport_text_for_element(root, el, expect_locale=expect)
    list_low = list_text.lower()
    list_has_markup = ("<color" in list_low) or ("<b>" in list_low) or ("<i>" in list_low)
    view_low = (view_text or "").lower()
    view_has_markup = ("<color" in view_low) or ("<b>" in view_low) or ("<i>" in view_low)
    list_plain = _plain_ui_text(list_text)
    view_plain = _plain_ui_text(view_text or "")
    # Stale DE/IT list rows often keep <color> while the viewport already shows
    # EN - never prefer other-locale markup over the on-screen string.
    if list_has_markup and not view_has_markup:
        if not view_text or list_plain == view_plain:
            return _normalize_unity_ui_color_tags(list_text)
    if view_text is not None:
        # User-added Add→Text rows often keep the default FONT body while the
        # list / ksp_ui already holds the edit - Prefer list for those.
        try:
            vo = getattr(el, "viewport_object", None)
            view_c = _collapse_ws(view_plain)
            list_c = _collapse_ws(list_plain)
            appended = bool(
                view_c and list_c
                and view_c.startswith(list_c)
                and len(view_c) > len(list_c)
            )
            if (
                vo is not None
                and bool(vo.get("ksp_user_added"))
                and list_text
                and list_text != view_text
                and not appended
            ):
                return _normalize_unity_ui_color_tags(list_text)
        except Exception:
            pass
        # Prefer longer list only when it still has markup the viewport lost
        # *and* the plain body still matches (same language).
        if (
            list_text
            and list_text != view_text
            and len(list_text) > len(view_text) + 3
            and list_has_markup
            and list_plain == view_plain
        ):
            return _normalize_unity_ui_color_tags(list_text)
        # Shorter list = user deleted / shortened text in the UI list.
        # Only when plains share a prefix - otherwise list is another locale.
        # Do NOT prefer list when the viewport is a prefix-extension (user
        # appended in FONT) — that used to drop extra lines in-game.
        if list_text != view_text and len(list_text) < len(view_text or ""):
            view_c = _collapse_ws(view_plain)
            list_c = _collapse_ws(list_plain)
            if view_c and list_c and view_c.startswith(list_c) and len(view_c) > len(list_c):
                pass
            elif (
                not list_plain
                or not view_plain
                or list_plain == view_plain
                or list_c == view_c
                or list_plain.startswith(view_plain[: max(8, len(list_plain) // 2)])
            ):
                return _normalize_unity_ui_color_tags(list_text)
        return _normalize_unity_ui_color_tags(view_text)
    return _normalize_unity_ui_color_tags(list_text)


def _flush_text_edits_for_export(root, kb, context=None) -> int:
    """Push panel / Edit Text edits into ``ksp_ui`` + list rows before patching.

    Does **not** commit every FONT body (that would bake soft-wrap figure-spaces).
    Commits:
    - active Edit Text (leave → OBJECT)
    - any UI text marked ``ksp_text_dirty`` while typing
    - list row text that is ahead of ``ksp_ui.text``
    """
    n = 0
    expect_loc = ""
    try:
        expect_loc = (
            str(getattr(kb, "active_locale", "") or "")
            or str(getattr(kb, "locale", "") or "")
        ).strip().lower()
    except Exception:
        expect_loc = ""
    try:
        import bpy
        from ..import_ksp.mu_ops import (
            _sync_font_obj_to_ui_list,
            clear_text_dirty,
            is_text_dirty,
        )
    except Exception:
        bpy = None
        _sync_font_obj_to_ui_list = None
        is_text_dirty = None
        clear_text_dirty = None
    if context is not None and bpy is not None:
        try:
            if getattr(context, "mode", "") == "EDIT_TEXT":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    try:
                        bpy.ops.object.editmode_toggle()
                    except Exception:
                        pass
                ao = getattr(context.view_layer, "objects", None)
                ao = getattr(ao, "active", None) if ao is not None else None
                if ao is not None and _sync_font_obj_to_ui_list is not None:
                    try:
                        if _sync_font_obj_to_ui_list(ao, commit_body=True):
                            n += 1
                    except Exception:
                        pass
                    try:
                        if ao.parent is not None and _sync_font_obj_to_ui_list(
                            ao.parent, commit_body=True
                        ):
                            n += 1
                    except Exception:
                        pass
        except Exception:
            pass
    # Dirty FONT bodies (Edit Text → Export without a clean mode transition).
    if _sync_font_obj_to_ui_list is not None and is_text_dirty is not None:
        for el in kb.ui_elements:
            if getattr(el, "kind", "") != "text":
                continue
            vo = getattr(el, "viewport_object", None)
            if vo is None:
                continue
            try:
                if vo.get("ksp_locale_parked"):
                    continue
            except Exception:
                pass
            if not is_text_dirty(vo):
                continue
            if expect_loc:
                try:
                    applied = str(vo.get("ksp_locale_applied") or "").strip().lower()
                except Exception:
                    applied = ""
                if applied != expect_loc:
                    continue
            try:
                if _sync_font_obj_to_ui_list(vo, commit_body=True):
                    n += 1
            except Exception:
                pass
            # Also try FONT children (active object may have been the curve).
            try:
                for child in list(getattr(vo, "children_recursive", []) or []):
                    if getattr(child, "type", "") != "FONT":
                        continue
                    if _sync_font_obj_to_ui_list(child, commit_body=True):
                        n += 1
            except Exception:
                pass
            if clear_text_dirty is not None:
                try:
                    clear_text_dirty(vo)
                except Exception:
                    pass
    # Multimaterial / bold FONT markup must reach ui_elements.text even when
    # ksp_text_dirty was never set (paint materials → Export).
    # Never commit a FONT whose ksp_locale_applied disagrees with the active
    # locale - after EN→DE edits the DE body still has <color> tags and would
    # otherwise overwrite the EN list row right before prefer_list export.
    try:
        from ..import_ksp.mu_ops import collect_viewport_text_plain
    except Exception:
        collect_viewport_text_plain = None
    if collect_viewport_text_plain is not None:
        for el in kb.ui_elements:
            if getattr(el, "kind", "") != "text":
                continue
            vo = getattr(el, "viewport_object", None)
            if vo is None:
                continue
            try:
                if vo.get("ksp_locale_parked"):
                    continue
            except Exception:
                pass
            if expect_loc:
                try:
                    applied = str(vo.get("ksp_locale_applied") or "").strip().lower()
                except Exception:
                    applied = ""
                if applied != expect_loc:
                    continue
            try:
                live = collect_viewport_text_plain(vo) or ""
            except Exception:
                live = ""
            if not live:
                continue
            low = live.lower()
            has_markup = (
                "<color" in low or "<b>" in low or "<i>" in low
            )
            src = ""
            try:
                src = str(vo.ksp_ui.text or "") or str(el.text or "")
            except Exception:
                src = str(el.text or "")
            # Adopt live when it has markup the list/ksp_ui lost, OR when the
            # plain body changed in Edit Text (do not require plains to match -
            # that blocked "I changed the text" exports).
            adopt = False
            if has_markup:
                adopt = True
                if src:
                    try:
                        import re as _re
                        def _plain(s):
                            return _re.sub(r"<[^>]+>", "", s or "").strip()
                        # FontStyle Bold → whole-string <b>…</b> is not real
                        # markup; do not overwrite plain locale / list text.
                        if _is_whole_string_style_wrap(live, src):
                            adopt = False
                        # Locale poison guard: DE FONT vs EN list (or any
                        # other-language leftover). Only adopt divergent
                        # plains when Edit Text marked the object dirty.
                        elif _plain(live) != _plain(src):
                            dirty = False
                            try:
                                dirty = bool(is_text_dirty(vo)) if is_text_dirty else False
                            except Exception:
                                dirty = False
                            if not dirty:
                                adopt = False
                    except Exception:
                        pass
            if adopt and str(el.text or "") != live:
                try:
                    el.text = live
                    n += 1
                except Exception:
                    pass
            if adopt:
                ui = _viewport_ui_for_element(root, el)
                if ui is not None:
                    try:
                        if str(ui.text or "") != live:
                            ui.text = live
                            n += 1
                    except Exception:
                        pass
            # Whole-block recolor (single material, no <color> tags): push
            # Blender material colour onto the list row → m_Color on export.
            try:
                raw_ov = vo.get("ksp_user_overrides") or {}
                ov = raw_ov if isinstance(raw_ov, dict) else {}
                user_recolor = (
                    ("color" in ov)
                    or bool(vo.get("ksp_user_added"))
                    or bool(vo.get("ksp_has_viewport_edit"))
                )
            except Exception:
                user_recolor = False
            if user_recolor:
                try:
                    from ..import_ksp.mu_ops import (
                        _material_slot_color as _mat_col,
                    )
                    fonts = []
                    scan = [vo] + list(getattr(vo, "children_recursive", []) or [])
                    for o in scan:
                        if getattr(o, "type", "") == "FONT" and o.data is not None:
                            fonts.append(o)
                    if fonts:
                        col = _mat_col(fonts[0], 0)
                        if col is not None and len(col) >= 3:
                            def _lin_srgb(c):
                                x = max(0.0, min(1.0, float(c)))
                                if x <= 0.0031308:
                                    return x * 12.92
                                return 1.055 * (x ** (1.0 / 2.4)) - 0.055
                            rgb = (
                                _lin_srgb(col[0]),
                                _lin_srgb(col[1]),
                                _lin_srgb(col[2]),
                                float(col[3]) if len(col) > 3 else 1.0,
                            )
                            cur = tuple(float(x) for x in (tuple(el.color)[:4] if el.color is not None else (1,1,1,1)))
                            if any(abs(a - b) > 0.02 for a, b in zip(rgb, cur)):
                                el.color = rgb
                                n += 1
                                if vo.ksp_ui.is_ksp_ui:
                                    vo.ksp_ui.color = rgb
                except Exception:
                    pass
    # Panel list edits: ui_elements.text may be ahead of ksp_ui.text
    for el in kb.ui_elements:
        if getattr(el, "kind", "") != "text":
            continue
        list_text = el.text or ""
        if not list_text:
            continue
        ui = _viewport_ui_for_element(root, el)
        if ui is None:
            continue
        try:
            if str(ui.text or "") != list_text:
                ui.text = list_text
                n += 1
        except Exception:
            pass
        try:
            vo = el.viewport_object
            if vo is not None and not vo.get("ksp_locale_parked"):
                vo["ksp_text_display"] = list_text
                if clear_text_dirty is not None:
                    clear_text_dirty(vo)
        except Exception:
            pass
    return n


def _viewport_ui_for_element(root, el):
    """Return the matching KSP UI property group, if its object survives."""
    mb = el.mb_path_id or ""
    for obj in [root] + list(root.children_recursive):
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
            if obj.get("ksp_locale_parked"):
                continue
            if mb and ui.mb_path_id == mb:
                return ui
            if not mb and ui.element_name == el.name:
                return ui
        except Exception:
            continue
    return None


def _text_asset_unchanged(env, path_id: int, text: str) -> bool:
    for obj in env.objects:
        if obj.type.name != "TextAsset" or int(obj.path_id) != int(path_id):
            continue
        data = obj.read()
        script = getattr(data, "m_Script", b"")
        if isinstance(script, bytes):
            cur = script.decode("utf-8", errors="replace")
        else:
            cur = str(script or "")
        return cur == (text or "")
    # Missing path id (en-us ids vs sibling .lang) is not "already matches".
    return False


def _tree_color(tree: dict):
    """Read Unity UI / TMP fill colour from a MonoBehaviour typetree."""
    from ..import_ksp.ui_roundtrip import _color

    if not isinstance(tree, dict):
        return None
    for key in ("m_Color", "m_faceColor", "m_fontColor"):
        if key in tree:
            return _color(tree.get(key))
    return None


def _colors_close(a, b, eps=1.0 / 512.0) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return all(abs(float(a[i]) - float(b[i])) <= eps for i in range(4))
    except Exception:
        return False


def _ui_style_unchanged(env, path_id: int, text: str, kind: str, *, color, font_size) -> bool:
    """True when bundle MonoBehaviour already matches what we would write."""
    if not path_id:
        return True
    found = False
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour" or int(obj.path_id) != int(path_id):
            continue
        found = True
        try:
            tree = obj.read_typetree()
        except Exception:
            return False
        if not isinstance(tree, dict):
            return False
        cur = tree.get("m_text")
        if cur is None:
            cur = tree.get("m_Text")
        if cur is not None and str(cur) != str(text or ""):
            return False
        want_col = tuple(color) if color is not None else None
        if want_col is not None and not _colors_close(_tree_color(tree), want_col):
            return False
        try:
            want_fs = float(font_size or 0.0)
        except Exception:
            want_fs = 0.0
        if want_fs > 0.5:
            cur_fs = None
            fd = tree.get("m_FontData")
            if isinstance(fd, dict) and "m_FontSize" in fd:
                cur_fs = float(fd.get("m_FontSize") or 0.0)
            elif "m_fontSize" in tree:
                cur_fs = float(tree.get("m_fontSize") or 0.0)
            if cur_fs is not None and abs(cur_fs - want_fs) > 0.05:
                return False
        return True
    # Missing path id in this UnityFS (typical: en-us ids vs sibling .lang) -
    # not "already matches". Caller should remap by element name.
    return False


def _path_id_in_env(env, path_id: int, *, type_name: str = None) -> bool:
    """True when ``path_id`` exists in ``env`` (optionally filtered by type)."""
    try:
        want = int(path_id or 0)
    except Exception:
        return False
    if not want or env is None:
        return False
    for obj in getattr(env, "objects", None) or []:
        try:
            if int(obj.path_id) != want:
                continue
            if type_name and getattr(obj.type, "name", None) != type_name:
                continue
            return True
        except Exception:
            continue
    return False


def _unique_path_id_remap_from_env(env) -> dict:
    """Map uniquely-named UI elements → path ids inside an already-open UnityFS.

    Sibling ``.lang`` AssetBundles renumber MonoBehaviour / RectTransform
    fileIDs. Viewport rows keep the base ``.ksp`` ids, so export must remap
    before patching or every write misses and the .lang is byte-copied.

    Must use the open ``env`` (not re-open the file) - a second load keeps a
    Windows handle and ``save_bundle`` then fails with Access Denied.
    """
    if env is None:
        return {}
    try:
        from ..import_ksp.bundle import _collect_ui
        elements, _report = _collect_ui(env, {})
    except Exception:
        return {}
    counts = {}
    for el in elements or []:
        name = (getattr(el, "name", "") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    out = {}
    for el in elements or []:
        name = (getattr(el, "name", "") or "").strip()
        if not name or counts.get(name, 0) != 1:
            continue
        try:
            mb = int(getattr(el, "mb_path_id", 0) or 0)
        except Exception:
            mb = 0
        try:
            rid = int(getattr(el, "rect_path_id", 0) or 0)
        except Exception:
            rid = 0
        try:
            gid = int(getattr(el, "go_path_id", 0) or 0)
        except Exception:
            gid = 0
        if mb or rid:
            out[name] = {"mb": mb, "rect": rid, "go": gid}
    return out


def _remap_ui_ids_for_env(env, path_remap: dict, el_name: str, mid: int, rid: int):
    """Resolve ``.lang`` renumbered ids; keep grafted mid/rid that already exist.

    Stock pages (STHeader, …) keep en-us path ids on the list row. Sibling
    ``.lang`` files renumber those ids - without remap, XML sync (by name)
    updates ``<Text>`` while ``apply_ui_style`` misses ``m_Text`` → verify
    fails on tags like ``<b>`` that only landed in XML.
    """
    if not el_name or not path_remap or el_name not in path_remap:
        return mid, rid
    rem = path_remap[el_name]
    try:
        rem_mb = int(rem.get("mb") or 0)
    except Exception:
        rem_mb = 0
    try:
        rem_rid = int(rem.get("rect") or 0)
    except Exception:
        rem_rid = 0
    # Keep mid/rid only when they resolve inside this UnityFS (grafted page
    # prefabs). Otherwise always take the unique-name remap from the template.
    if rem_mb and not _path_id_in_env(env, mid, type_name="MonoBehaviour"):
        mid = rem_mb
    if rem_rid and not _path_id_in_env(env, rid):
        rid = rem_rid
    return mid, rid


def _is_whole_string_style_wrap(tagged: str, plain: str) -> bool:
    """True when ``tagged`` is only ``<b>``/``<i>`` around the same plain body.

    PBS / stock UI.Text headers use ``m_FontStyle`` Bold with plain ``m_Text``.
    Blender FONT ``use_bold`` used to invent ``<b>…</b>`` and bake it into XML
    while MonoBehaviour stayed plain (or the reverse after a missed MB write).
    """
    import re
    t = tagged if tagged is not None else ""
    p = plain if plain is not None else ""
    if not t or t == p:
        return False
    core = t.strip()
    for _ in range(2):
        m = re.fullmatch(r"(?is)<(b|i)>(.*)</\1>", core)
        if not m:
            break
        core = m.group(2)
    try:
        def _strip(s):
            return re.sub(r"<[^>]+>", "", s or "").strip()
        return _strip(core) == _strip(p) and core == p
    except Exception:
        return core == p


def _text_asset_ids_by_name(env) -> dict:
    """Unique TextAsset ``m_Name`` → path_id in this UnityFS.

    Sibling ``.lang`` files renumber TextAssets the same way they renumber UI.
    Without this remap, KSPedia XML (user page titles) is never patched into
    the locale file and DE reimport falls back to the EN title.
    """
    counts = {}
    first = {}
    if env is None:
        return {}
    for obj in env.objects:
        try:
            if obj.type.name != "TextAsset":
                continue
            pid = int(obj.path_id)
            data = obj.read()
            name = (getattr(data, "m_Name", None) or "").strip()
        except Exception:
            continue
        if not name:
            continue
        key = name.lower()
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, pid)
    return {k: pid for k, pid in first.items() if counts.get(k, 0) == 1}


def _find_kspedia_xml_path_id(env) -> int:
    """Path id of the unique KSPedia XML TextAsset in ``env``, else 0."""
    hits = []
    if env is None:
        return 0
    for obj in env.objects:
        try:
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            script = getattr(data, "m_Script", b"")
            if isinstance(script, bytes):
                script = script.decode("utf-8", errors="replace")
            name = (getattr(data, "m_Name", None) or "").lower()
            text = str(script or "")
        except Exception:
            continue
        if "<KSPedia" in text[:800] or (
            "kspedia" in name and "bundle" not in name
        ):
            hits.append(int(obj.path_id))
    return hits[0] if len(hits) == 1 else 0


def _viewport_object_for_element(root, el):
    """Live (non-parked) viewport object for a UI list row."""
    vo = getattr(el, "viewport_object", None)
    if vo is not None:
        try:
            if vo.get("ksp_locale_parked"):
                vo = None
            else:
                # Other TOC pages are hide_viewport during export; they still
                # hold the live FONT Size X / G-move (USER-OLD-002 ConfS2).
                return vo
        except Exception:
            return vo
    mb = str(getattr(el, "mb_path_id", "") or "")
    name = (getattr(el, "name", "") or "").strip()
    for obj in [root] + list(getattr(root, "children_recursive", []) or []):
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
            if obj.get("ksp_locale_parked"):
                continue
            if _vo_hidden(obj):
                continue
            if mb and str(ui.mb_path_id or "") == mb:
                return obj
            if (not mb) and name and (ui.element_name or "") == name:
                return obj
        except Exception:
            continue
    return None


def _vo_hidden(obj) -> bool:
    """True for locale leftovers / outliner-hidden copies that must not export."""
    if obj is None:
        return False
    try:
        if obj.get("ksp_locale_parked"):
            return True
    except Exception:
        pass
    try:
        if bool(getattr(obj, "hide_viewport", False)):
            return True
    except Exception:
        pass
    try:
        if obj.hide_get():
            return True
    except Exception:
        pass
    return False


_LAYOUT_OV_KEYS = (
    "size_delta",
    "anchored_position",
    "pivot",
    "anchor_min",
    "anchor_max",
    "offset_min",
    "offset_max",
    "box_width_px",
)
_POS_OV_KEYS = (
    "anchored_position",
    "pivot",
    "anchor_min",
    "anchor_max",
    "offset_min",
    "offset_max",
)


def _vo_user_overrides(vo) -> dict:
    """Plain dict of ``ksp_user_overrides`` (Blender IDPropertyGroup ≠ dict)."""
    if vo is None:
        return {}
    try:
        from ..import_ksp.locale_buffers import applied_overrides
        ov = applied_overrides(vo)
        if isinstance(ov, dict) and ov:
            return ov
    except Exception:
        pass
    try:
        raw = vo.get("ksp_user_overrides") or {}
        if not raw:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        return {str(k): raw[k] for k in list(raw.keys())}
    except Exception:
        return {}


def _vo_viewport_edit(vo) -> bool:
    try:
        return bool(vo is not None and vo.get("ksp_has_viewport_edit"))
    except Exception:
        return False


def _el_locale_has_viewport_edit(kb, el, vo, export_loc) -> bool:
    """G/R/S recorded for THIS export language — not the shared live object.

    Stock images are one Blender object. ``ksp_has_viewport_edit`` is the
    language currently on screen; writing it into every ``.lang`` leaked
    default-locale scale/rotation to all languages on reimport.
    """
    loc = (export_loc or "").strip().lower()
    if not loc:
        return _vo_viewport_edit(vo)
    try:
        from ..import_ksp import locale_buffers
        maps = locale_buffers.get_maps(kb, loc)
    except Exception:
        maps = None
    if not maps:
        return False
    el_by_hier = maps.get("el_by_hier") or {}
    el_by_name = maps.get("el_by_name") or {}
    st = None
    try:
        if vo is not None:
            from ..import_ksp.locale_switch import _obj_hierarchy_key
            hier = _obj_hierarchy_key(vo)
            if hier and hier in el_by_hier:
                st = el_by_hier[hier]
    except Exception:
        st = None
    if st is None:
        name = (getattr(el, "name", "") or "").strip()
        if name and name in el_by_name:
            st = el_by_name[name]
    if isinstance(st, dict):
        return bool(st.get("has_viewport_edit"))
    return False


def _export_layout_allowed(vo, ov, user_added, *, overlay_lock=False, locale_has_edit=None):
    """True when Unity RectTransform layout may diverge from disk template.

    Stock PBS must not export import-calibration drift (locale switch nudges,
    FONT box vs Unity sizeDelta) — only real user edits / overrides.
    A stock overlay G-move (ConfT2 red pad) stamps ``ksp_has_viewport_edit``
    and MUST export; overlay_lock only blocks untouched calibration drift.

    ``locale_has_edit=False``: sibling ``.lang`` — the shared live object still
    carries the default language's G/R/S flag. Do not treat that as a write.
    """
    if user_added:
        return True
    if locale_has_edit is False:
        return False
    if locale_has_edit is True:
        return True
    if _vo_viewport_edit(vo):
        return True
    if isinstance(ov, dict) and any(k in ov for k in _POS_OV_KEYS):
        return True
    if overlay_lock:
        return False
    return False


def _texture_row_is_user_added(kb, item) -> bool:
    """True when this Texture2D is bound to a user-added Image (Load/Add)."""
    try:
        pid = int(getattr(item, "path_id", 0) or 0)
    except Exception:
        pid = 0
    tname = (getattr(item, "name", "") or "").strip().lower()
    img = getattr(item, "image", None)
    for el in list(getattr(kb, "ui_elements", []) or []):
        vo = getattr(el, "viewport_object", None)
        userish = False
        try:
            userish = bool(vo is not None and vo.get("ksp_user_added"))
        except Exception:
            userish = False
        if not userish:
            continue
        try:
            if pid and int(getattr(el, "texture_path_id", 0) or 0) == pid:
                return True
        except Exception:
            pass
        try:
            if img is not None and getattr(el, "image", None) is img:
                return True
        except Exception:
            pass
        en = (getattr(el, "name", "") or "").strip().lower()
        if tname and en and (tname == en or tname.endswith("_" + en) or en in tname):
            return True
    return False


def _texture_item_is_user_art(kb, item) -> bool:
    """Legacy name kept for regression tests (user-added logo/art)."""
    return _texture_row_is_user_added(kb, item)


def _unity_texture_size(env, path_id: int):
    try:
        want = int(path_id or 0)
    except Exception:
        return (0, 0)
    if not want or env is None:
        return (0, 0)
    for obj in getattr(env, "objects", []) or []:
        try:
            if obj.type.name != "Texture2D" or int(obj.path_id) != want:
                continue
            data = obj.read()
            return (
                int(getattr(data, "m_Width", 0) or 0),
                int(getattr(data, "m_Height", 0) or 0),
            )
        except Exception:
            return (0, 0)
    return (0, 0)


def _sync_el_from_viewport(root, el) -> None:
    """Push live ksp_ui style + moved layout onto the export list row.

    Hand moves (G) update ``ksp_ui.anchored_position`` via live sync but used
    to skip export unless the key was already in ``ksp_user_overrides`` -
    duplicates / ALT / showModCategory then kept stock RectTransform coords.
    """
    ui = _viewport_ui_for_element(root, el)
    vo = _viewport_object_for_element(root, el)
    ov = _vo_user_overrides(vo)
    user_added = False
    try:
        user_added = bool(vo is not None and vo.get("ksp_user_added"))
    except Exception:
        user_added = False
    overlay_lock = False
    if vo is not None:
        try:
            from ..import_ksp.viewport import is_artwork_overlay as _is_art_sync
            raw_txt = str(getattr(el, "text", "") or "")
            try:
                raw_txt = raw_txt or str(vo.ksp_ui.text or "")
            except Exception:
                pass
            overlay_lock = bool(_is_art_sync(raw_txt, vo))
        except Exception:
            overlay_lock = False
    layout_allowed = _export_layout_allowed(
        vo, ov, user_added, overlay_lock=overlay_lock,
    )
    # Recompute AP from layout pin when the object was moved in the viewport.
    live_ap = None
    live_sd = None
    live_ls = None
    if vo is not None:
        try:
            kb = root.ksp_bundle
            sx = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
            from ..import_ksp.locale_buffers import snapshot_object_el_state
            st = snapshot_object_el_state(vo, pixel_scale=sx, mark_edit=False)
            # FONT rebuild after a glyph edit nudges location by <1 px and
            # used to look like a G-move, so every language inherited a new
            # AP. Real G/R/S stamps ksp_has_viewport_edit.
            moved = bool(_vo_viewport_edit(vo) or user_added)
            if st.get("anchored_position") is not None:
                cand = tuple(float(x) for x in st["anchored_position"][:2])
                if moved and layout_allowed:
                    live_ap = cand
            if st.get("size_delta") is not None and layout_allowed and (
                moved
                or user_added
                or "size_delta" in ov
                or "box_width_px" in ov
            ):
                live_sd = tuple(float(x) for x in st["size_delta"][:2])
            if live_sd is None:
                try:
                    from ..import_ksp.locale_buffers import live_font_box_size_delta
                    box = live_font_box_size_delta(vo, pixel_scale=sx)
                    if box is not None:
                        # Do not bake the live English box into a sibling locale.
                        allow_live_sd = True
                        try:
                            applied = str(vo.get("ksp_locale_applied") or "").strip().lower()
                            exp = ""
                            try:
                                exp = str(root.ksp_bundle.get("_ksp_export_locale") or "").strip().lower()
                            except Exception:
                                exp = str(getattr(root.ksp_bundle, "active_locale", "") or "").strip().lower()
                            if exp and applied and exp != applied:
                                allow_live_sd = False
                        except Exception:
                            allow_live_sd = True
                        if allow_live_sd and layout_allowed:
                            live_sd = tuple(float(x) for x in box[:2])
                            ov = dict(ov)
                            ov["size_delta"] = live_sd
                            ov["box_width_px"] = abs(float(live_sd[0]))
                except Exception:
                    pass
            if st.get("local_scale") is not None and (moved or user_added):
                try:
                    live_ls = tuple(float(x) for x in st["local_scale"][:3])
                except Exception:
                    live_ls = None
            if moved or user_added:
                ov = dict(ov)
                if live_ap is not None:
                    ov["anchored_position"] = live_ap
                if live_sd is not None:
                    ov["size_delta"] = live_sd
                try:
                    from ..import_ksp.locale_buffers import remember_applied_overrides
                    remember_applied_overrides(vo, ov)
                except Exception:
                    pass
                # Keep ksp_ui in sync so inject (runs before this in some
                # paths) and later writes see the live AP / size.
                try:
                    ui_live = getattr(vo, "ksp_ui", None)
                    if ui_live is not None:
                        if live_ap is not None and hasattr(ui_live, "anchored_position"):
                            ui_live.anchored_position = (live_ap[0], live_ap[1])
                        if live_sd is not None and hasattr(ui_live, "size_delta"):
                            ui_live.size_delta = (live_sd[0], live_sd[1])
                except Exception:
                    pass
        except Exception:
            pass
    if ui is not None:
        for key in ("font_size", "font_family"):
            if not hasattr(el, key) or not hasattr(ui, key):
                continue
            try:
                val = getattr(ui, key)
                if val is not None:
                    setattr(el, key, val)
            except Exception:
                pass
        # Do not copy ksp_ui.color every export — COLOR subtype values can
        # drift vs Unity sRGB and darken in-game. Only when the user overrode.
        for key in ("size_delta", "anchored_position"):
            take = key in ov or user_added
            if key == "anchored_position" and live_ap is not None:
                take = True
            if key == "size_delta" and live_sd is not None and (
                key in ov or user_added or "box_width_px" in ov
            ):
                take = True
            if not take:
                try:
                    if (
                        key == "anchored_position"
                        and layout_allowed
                        and not overlay_lock
                        and hasattr(ui, key)
                        and hasattr(el, key)
                    ):
                        uap = tuple(float(x) for x in (ui.anchored_position or (0, 0))[:2])
                        eap = tuple(float(x) for x in (el.anchored_position or (0, 0))[:2])
                        if any(abs(a - b) > 0.05 for a, b in zip(uap, eap)):
                            take = True
                except Exception:
                    pass
            if not take or not hasattr(el, key):
                continue
            try:
                if key == "anchored_position" and live_ap is not None:
                    el.anchored_position = (live_ap[0], live_ap[1], 0.0)
                elif key == "size_delta" and live_sd is not None and (
                    key in ov or user_added or "box_width_px" in ov
                ):
                    cur = tuple(getattr(el, "size_delta", (0.0, 0.0)) or (0.0, 0.0))
                    if len(cur) > 2:
                        el.size_delta = (live_sd[0], live_sd[1]) + tuple(cur[2:])
                    else:
                        el.size_delta = (live_sd[0], live_sd[1])
                elif hasattr(ui, key):
                    val = getattr(ui, key)
                    if val is not None:
                        setattr(el, key, val)
            except Exception:
                pass
    try:
        if ov.get("enable_word_wrapping") is True and hasattr(el, "enable_word_wrapping"):
            el.enable_word_wrapping = True
            if ui is not None and hasattr(ui, "enable_word_wrapping"):
                ui.enable_word_wrapping = True
    except Exception:
        pass
    if vo is None:
        return
    try:
        col = ov.get("color")
        if col is not None and len(col) >= 3 and hasattr(el, "color"):
            el.color = tuple(float(c) for c in col[:4])
    except Exception:
        pass
    # Stock ConfT2 recolour lives on the FONT material, not ksp_ui.color.
    # Mouse paint without Duplicate used to skip m_Color (reimport.blend).
    if getattr(el, "kind", "") == "text" and hasattr(el, "color"):
        try:
            take_col = ("color" in ov) or user_added or _vo_viewport_edit(vo)
        except Exception:
            take_col = False
        if take_col:
            try:
                from ..import_ksp.locale_buffers import _material_color_srgb
                live = _material_color_srgb(vo)
                if live is not None and len(live) >= 3:
                    rgb = tuple(float(c) for c in live[:4])
                    if len(rgb) < 4:
                        rgb = (rgb[0], rgb[1], rgb[2], 1.0)
                    cur = tuple(
                        float(x)
                        for x in (
                            tuple(el.color)[:4]
                            if el.color is not None
                            else (1, 1, 1, 1)
                        )
                    )
                    if any(abs(a - b) > 0.02 for a, b in zip(rgb, cur)):
                        el.color = rgb
                        ov = dict(ov)
                        ov["color"] = rgb
                        try:
                            from ..import_ksp.locale_buffers import (
                                remember_applied_overrides,
                            )
                            remember_applied_overrides(vo, ov)
                        except Exception:
                            pass
                        try:
                            if vo.ksp_ui.is_ksp_ui:
                                vo.ksp_ui.color = rgb
                        except Exception:
                            pass
            except Exception:
                pass
    # Image tint: prefer ksp_ui / custom-prop alpha. Material Emission RGB is
    # wired to the texture (A forced to 1.0), so `_material_slot_color` was
    # wiping Unity m_Color.a and backgrounds lost soft transparency on export.
    if getattr(el, "kind", "") == "image" and hasattr(el, "color"):
        try:
            col = None
            if "color" in ov and ov.get("color") is not None:
                col = tuple(float(c) for c in ov.get("color")[:4])
            if col is None and ui is not None:
                try:
                    uc = tuple(float(c) for c in ui.color)
                    if len(uc) >= 3:
                        col = uc if len(uc) >= 4 else (uc[0], uc[1], uc[2], 1.0)
                except Exception:
                    col = None
            if col is None:
                try:
                    mats = list(getattr(getattr(vo, "data", None), "materials", None) or ())
                    mat = mats[0] if mats else None
                    if mat is not None:
                        a = mat.get("ksp_ui_color_a", None)
                        if a is not None:
                            base = tuple(float(c) for c in (el.color or (1, 1, 1, 1))[:3])
                            col = (base[0], base[1], base[2], float(a))
                except Exception:
                    col = None
            if col is not None and len(col) >= 3:
                if len(col) < 4:
                    col = (col[0], col[1], col[2], 1.0)
                el.color = col[:4]
            elif user_added:
                # Opaque Image tint — letterbox transparency is in the texture.
                try:
                    cur = tuple(float(c) for c in (el.color or (1.0, 1.0, 1.0, 1.0))[:3])
                    el.color = (cur[0], cur[1], cur[2], 1.0)
                except Exception:
                    try:
                        el.color = (1.0, 1.0, 1.0, 1.0)
                    except Exception:
                        pass
        except Exception:
            pass
    try:
        fs = float(ov.get("font_size") or 0.0)
        if fs > 0.5 and hasattr(el, "font_size"):
            el.font_size = fs
    except Exception:
        pass
    # Bake live Blender R/S into Unity fields so export (and .lang prefer_list)
    # sees the edit even when the ksp_ui PropertyGroup has no euler/scale.
    try:
        from ..import_ksp.layout import blender_euler_to_unity_ui_quat
        q = blender_euler_to_unity_ui_quat(vo.rotation_euler)
        el.local_rotation = tuple(float(x) for x in q[:4])
    except Exception:
        pass
    try:
        # When sizeDelta already includes object scale, ship identity localScale.
        if live_ls is not None:
            el.local_scale = (
                float(live_ls[0]), float(live_ls[1]), float(live_ls[2]),
            )
        else:
            el.local_scale = (
                float(vo.scale.x),
                float(vo.scale.y),
                float(vo.scale.z),
            )
    except Exception:
        pass



def export_ksp(
    root,
    filepath,
    template_path=None,
    *,
    prefer_list_text=False,
    sync_from_viewport=True,
    set_source_path=True,
    progress_start=None,
    progress_end=None,
    export_locale=None,
):
    """Patch source/template UnityFS with edits from root.ksp_bundle.

    Returns the output filepath.

    ``prefer_list_text`` / ``sync_from_viewport=False``: use ``ui_elements``
    rows already filled by locale maps (sibling ``.lang`` export) instead of
    live FONT bodies - avoids rewriting the viewport during multi-lang save.
    """
    from ..import_ksp.progress_util import tick, tick_items

    def _p(value, text=None, force=False):
        if progress_start is None or progress_end is None:
            return
        lo = int(progress_start)
        hi = int(progress_end)
        if hi < lo:
            hi = lo
        # value is 0..100 within this export_ksp call
        mapped = lo + int(round((hi - lo) * (float(value) / 100.0)))
        tick(mapped, text=text, force=force)

    if not ensure_unitypy(False):
        from ..import_ksp.deps import ensure_unitypy_or_prompt
        if not ensure_unitypy_or_prompt():
            raise KspBundleError(
                "UnityPy is not available: %s" % (last_error() or "unknown")
            )
    if root is None or not root.ksp_bundle.is_ksp_bundle:
        raise KspBundleError("Object is not a KSP bundle root")

    kb = root.ksp_bundle
    export_loc = _kb_export_locale(kb, export_locale)
    try:
        kb["_ksp_export_locale"] = export_loc
    except Exception:
        pass

    # Safety net: operators flush before export_ksp, but direct callers /
    # scripts may not - multimaterial FONT markup must hit the list first.
    if sync_from_viewport:
        try:
            import bpy as _bpy
            _flush_text_edits_for_export(
                root, kb, getattr(_bpy, "context", None),
            )
        except Exception:
            pass

    from ..import_ksp import source_embed

    src, embed_tmp, _from_embed = source_embed.resolve_export_source(
        kb, template_path=template_path
    )
    if not src or not os.path.isfile(src):
        raise KspBundleError(
            "No source/template .ksp found to patch (set Source via Export, "
            "import a real .ksp, or Embed source .ksp)"
        )

    def _drop_embed_tmp():
        nonlocal embed_tmp
        if not embed_tmp:
            return
        try:
            if os.path.isfile(embed_tmp):
                os.remove(embed_tmp)
        except Exception:
            pass
        embed_tmp = None

    _p(5, text="Loading export template…", force=True)
    try:
        src, env = load_env_for_export(src)
    except Exception:
        _drop_embed_tmp()
        raise

    # Auto-fix: keep UnityFS UrlName identity; locale_base is file naming only.
    # gep.ksp + UrlName=jnsq -> sync Screens to jnsq, do NOT rewrite UrlName to gep.
    n_prefab_clone = 0
    did_pack_autofix = False
    file_stem = ""
    try:
        file_stem = (
            str(getattr(kb, "locale_base", "") or "").strip()
            or str(getattr(kb, "bundle_name", "") or "").strip()
        )
    except Exception:
        file_stem = ""
    previous_stem = ""
    try:
        from ..import_ksp.unityfs_catalog import inspect_ksp_unityfs
        _uinfo = inspect_ksp_unityfs(src)
        if _uinfo:
            previous_stem = (
                str(_uinfo.get("url_name") or "").strip()
                or str(_uinfo.get("ab_name") or "").strip()
            )
    except Exception:
        previous_stem = ""
    # Pack identity = UrlName; fall back to kb.bundle_name then file stem.
    # Sample / New-menu templates only use previous_stem as the *donor shell*
    # (prev_for_sync) - never as the user's pack UrlName (else every sample
    # exports as kspedia_careerui from template_kspedia_ui.ksp).
    try:
        if getattr(kb, "is_sample_template", False):
            identity = (
                str(getattr(kb, "bundle_name", "") or "").strip()
                or file_stem
                or previous_stem
            )
        else:
            identity = (
                previous_stem
                or str(getattr(kb, "bundle_name", "") or "").strip()
                or file_stem
            )
    except Exception:
        identity = previous_stem or file_stem
    new_stem = identity
    if previous_stem and new_stem and previous_stem.lower() == new_stem.lower():
        prev_for_sync = ""
    else:
        prev_for_sync = previous_stem
    # Stale .lang UrlName (kpbs_zh) stamped onto TOC breaks is_local → NewPage
    # never cloned into the main .ksp (byte-identical gray page). Heal here.
    if new_stem:
        try:
            kb.bundle_name = new_stem
        except Exception:
            pass
        try:
            for node in list(getattr(kb, "toc_nodes", []) or []):
                bn = str(getattr(node, "bundle_name", "") or "").strip()
                if not bn:
                    node.bundle_name = new_stem
                    continue
                # Replace wrong locale pack ids / stale UrlNames (kpbs_zh).
                low = bn.lower()
                stem_l = new_stem.lower()
                if low == stem_l or low.startswith(stem_l + "_"):
                    continue
                sid = str(getattr(node, "screen", "") or "").strip().lower().replace(" ", "")
                ap = str(getattr(node, "asset_path", "") or "").replace("\\", "/").lower()
                foreign_stock = (
                    "/squad/" in ap
                    or "/makinghistory/" in ap
                    or "/serenity/" in ap
                )
                user = grafted = False
                try:
                    for obj in (
                        getattr(node, "page_object", None),
                        getattr(node, "folder_object", None),
                    ):
                        if obj is None:
                            continue
                        if obj.get("ksp_user_added"):
                            user = True
                        if obj.get("ksp_grafted") or obj.get("ksp_graft_source_ksp"):
                            grafted = True
                except Exception:
                    pass
                if (
                    user
                    or grafted
                    or sid.startswith("newpage")
                    or low.startswith("kpbs")
                    or (ap.startswith("assets/kspedia/") and not foreign_stock)
                ):
                    try:
                        node.bundle_name = new_stem
                    except Exception:
                        pass
        except Exception:
            pass
    if new_stem:
        # Do NOT force UnityPy repack just because a stem exists - GEP/JNSQ
        # streamed textures collapse from ~200MB to a few MB on full save.
        try:
            if file_stem and file_stem.lower() != new_stem.lower():
                try:
                    kb.locale_base = file_stem
                except Exception:
                    pass
            from ..import_ksp.unityfs_catalog import sync_local_nodes_to_stem
            sync_local_nodes_to_stem(
                kb, new_stem, previous_stem=prev_for_sync,
                update_locale_base=False,
            )
        except Exception as ex:
            print("WARNING: BundleName sync failed: %s" % ex)
        try:
            from .prefab_clone import ensure_local_page_prefabs
            n_prefab_clone, clone_errs, env_dirty = ensure_local_page_prefabs(
                env, kb, new_stem, previous_stem=prev_for_sync,
            )
            if clone_errs:
                _drop_embed_tmp()
                raise KspBundleError(
                    "Could not clone page prefabs into UnityFS: %s"
                    % ", ".join(clone_errs[:8])
                )
            if n_prefab_clone or env_dirty:
                did_pack_autofix = True
            if n_prefab_clone:
                print(
                    "INFO: KSP export: cloned %d missing page prefab(s)"
                    % n_prefab_clone
                )
        except KspBundleError:
            _drop_embed_tmp()
            raise
        except Exception as ex:
            _drop_embed_tmp()
            raise KspBundleError("Prefab clone failed: %s" % ex)
        if did_pack_autofix:
            try:
                from ..import_ksp import kspedia_index as _kidx
                _kidx.sync_bundle_toc_xml(kb)
            except Exception as ex:
                print("WARNING: TOC XML sync after prefab clone failed: %s" % ex)

    # Sibling .lang files use different fileIDs than the base .ksp the viewport
    # was imported from - remap uniquely-named elements to this template's ids.
    path_remap = {}
    try:
        path_remap = _unique_path_id_remap_from_env(env)
    except Exception:
        path_remap = {}
    # Add/Load/Duplicate first - inject NEW Unity GOs before name-bind, else
    # fuzzy bind steals stock Configuration Image mids and Load Image overwrites
    # the wrong page content / proportions.
    # Sync layout from Blender first so inject reads live AP / size (not 0,0).
    if sync_from_viewport:
        try:
            for _el in list(kb.ui_elements):
                try:
                    if str(getattr(_el, "kind", "") or "") not in ("text", "image"):
                        continue
                except Exception:
                    continue
                try:
                    _sync_el_from_viewport(root, _el)
                except Exception:
                    pass
        except Exception as syn_ex:
            print("WARNING: pre-inject viewport sync failed: %s" % syn_ex)
    # Restore nulled page-root sprites before cloning — GEP Antenna donors
    # otherwise have m_Sprite=0 and Load Image abort.
    try:
        from .prefab_clone import heal_null_image_sprites as _heal_pre
        n_pre = _heal_pre(env)
        if n_pre:
            print(
                "INFO: KSP export: pre-inject healed %d Image/Rect link(s)"
                % n_pre
            )
    except Exception as ex:
        print("WARNING: KSP export: pre-inject Image heal failed: %s" % ex)
    try:
        from .prefab_clone import inject_user_ui_elements
        n_inj = inject_user_ui_elements(env, kb, export_locale=export_loc)
        if n_inj:
            print(
                "INFO: KSP export: injected %d new UI element(s) into page prefabs"
                % n_inj
            )
            did_pack_autofix = True
    except Exception as inj_ex:
        print("WARNING: UI inject into prefab failed: %s" % inj_ex)

    # Prefer per-page prefab ids for grafted screens (global remap collapses
    # once Configuration was cloned under multiple AssetPaths).
    try:
        from .prefab_clone import bind_ui_elements_to_page_prefabs
        n_bind = bind_ui_elements_to_page_prefabs(env, kb)
        if n_bind:
            print(
                "INFO: KSP export: bound %d UI element(s) to page prefabs"
                % n_bind
            )
    except Exception as bind_ex:
        print("WARNING: page prefab UI bind failed: %s" % bind_ex)


    # Clear / deactivate UI texts deleted in Blender.
    # Track separately: ``n_ui_write`` is reset later before the main UI loop.
    n_deleted_ui = 0
    try:
        from ..import_ksp.ui_roundtrip import set_game_object_active
        raw_clear = str(root.get("ksp_pending_clear_mbs") or "")
        clear_mids = []
        for part in raw_clear.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                clear_mids.append(int(part))
            except Exception:
                pass
        for mid in clear_mids:
            try:
                if apply_ui_style(env, mid, text=""):
                    n_deleted_ui += 1
            except Exception:
                try:
                    if apply_ui_text(env, mid, ""):
                        n_deleted_ui += 1
                except Exception:
                    pass
            try:
                clear_image_mb_sprite_refs(env, [mid])
            except Exception:
                pass
            try:
                if set_game_object_active(env, mid, False):
                    n_deleted_ui += 1
            except Exception:
                pass
        if clear_mids:
            try:
                root["ksp_pending_clear_mbs"] = ""
            except Exception:
                pass
    except Exception as ex:
        print("WARNING: KSP export: clear deleted texts failed: %s" % ex)

    # Durable delete: even if pending-clear was empty (native X, lost props),
    # deactivate prefab text/image GOs no longer listed in ui_elements.
    try:
        from .prefab_clone import prune_deleted_prefab_ui
        n_prune = prune_deleted_prefab_ui(env, kb)
        if n_prune:
            n_deleted_ui += int(n_prune)
            print(
                "INFO: KSP export: pruned %d deleted UI object(s) from prefabs"
                % n_prune
            )
            did_pack_autofix = True
    except Exception as ex:
        print("WARNING: KSP export: prune deleted UI failed: %s" % ex)

    # Heal page-root Images that already have m_Sprite=0 (prior prune bug) and
    # one-way RectTransform parenting left by inject without reader rebind.
    try:
        from .prefab_clone import heal_null_image_sprites
        n_heal = heal_null_image_sprites(env)
        if n_heal:
            did_pack_autofix = True
            print("INFO: KSP export: healed %d broken Image/Rect link(s)" % n_heal)
    except Exception as ex:
        print("WARNING: KSP export: Image/Rect heal failed: %s" % ex)

    # Textures: skip unchanged (passthrough keeps m_StreamData / size).
    # Dirty or empty content_hash always rewrite; hash match alone may skip.
    import hashlib
    n_tex_write = 0
    n_tex_skip = 0
    n_tex_fail = 0

    def _resolve_export_texture_pid(tex_item):
        """path_id on the row, or from linked ui_elements / materials."""
        try:
            pid = int(getattr(tex_item, "path_id", 0) or 0)
        except Exception:
            pid = 0
        if pid:
            return pid
        img = getattr(tex_item, "image", None)
        tname = (getattr(tex_item, "name", "") or "").strip()
        try:
            for el in kb.ui_elements:
                try:
                    tpid = int(getattr(el, "texture_path_id", 0) or 0)
                except Exception:
                    tpid = 0
                if not tpid:
                    continue
                linked = False
                if img is not None:
                    try:
                        vo = getattr(el, "viewport_object", None)
                        if vo is not None:
                            for slot in getattr(vo, "material_slots", []) or []:
                                mat = getattr(slot, "material", None)
                                if mat is None or not getattr(mat, "use_nodes", False):
                                    continue
                                for node in mat.node_tree.nodes:
                                    if getattr(node, "image", None) is img:
                                        linked = True
                                        break
                                if linked:
                                    break
                    except Exception:
                        pass
                if not linked and tname:
                    try:
                        ename = (getattr(el, "name", "") or "").strip()
                        if ename and (tname == ename or tname in ename or ename in tname):
                            linked = True
                    except Exception:
                        pass
                if linked:
                    return tpid
        except Exception:
            pass
        return 0

    tex_items = list(kb.textures)
    n_tex = max(len(tex_items), 1)
    for i, item in enumerate(tex_items):
        if progress_start is not None:
            tick_items(
                i, n_tex,
                int(progress_start) + int(0.08 * (int(progress_end) - int(progress_start))),
                int(progress_start) + int(0.35 * (int(progress_end) - int(progress_start))),
                text="Exporting textures…",
            )
        try:
            if getattr(item, "texture_external", False):
                continue
        except Exception:
            pass
        dirty = False
        try:
            dirty = bool(getattr(item, "dirty", False))
        except Exception:
            dirty = False
        pid = _resolve_export_texture_pid(item)
        if not pid:
            if dirty:
                # Orphan dirty row (e.g. BackgroundBlueGrid.png.001 after user
                # deleted Background / inject never got a Unity path_id). Drop
                # it quietly when nothing in ui_elements still points at it.
                tname = (getattr(item, "name", "") or "").strip()
                img = getattr(item, "image", None)
                still_used = False
                try:
                    for el in kb.ui_elements:
                        try:
                            if bool(getattr(el, "missing_in_locale", False)):
                                continue
                        except Exception:
                            pass
                        linked = False
                        if img is not None:
                            try:
                                if getattr(el, "image", None) is img:
                                    linked = True
                            except Exception:
                                pass
                        if not linked and tname:
                            try:
                                en = (getattr(el, "name", "") or "").strip()
                                if en and (
                                    en.lower() == tname.lower()
                                    or tname.lower().startswith(en.lower() + ".")
                                ):
                                    linked = True
                            except Exception:
                                pass
                        if linked:
                            still_used = True
                            break
                except Exception:
                    still_used = False
                if still_used:
                    print(
                        "WARNING: KSP texture export: dirty texture %r has no "
                        "path_id — inject may have failed (UI still references it)"
                        % (tname or "?")
                    )
                    n_tex_fail += 1
                else:
                    print(
                        "INFO: KSP texture export: dropping unreferenced dirty "
                        "texture row %r (no path_id)"
                        % (tname or "?")
                    )
                    try:
                        # Clear dirty so later passes stay quiet; remove row.
                        item.dirty = False
                    except Exception:
                        pass
                    try:
                        for _i in range(len(kb.textures) - 1, -1, -1):
                            if kb.textures[_i] is item:
                                kb.textures.remove(_i)
                                break
                    except Exception:
                        pass
            continue
        # Persist resolved id back onto the row for later passes / reimport.
        try:
            if not str(getattr(item, "path_id", "") or "").strip():
                item.path_id = str(pid)
        except Exception:
            pass
        png = _image_png_bytes(item.image)
        if not png:
            if dirty:
                print(
                    "WARNING: KSP texture export: dirty texture %r (path_id=%s) "
                    "has no PNG bytes"
                    % (getattr(item, "name", "") or "?", pid)
                )
                n_tex_fail += 1
            continue
        try:
            from ..import_ksp import viewport as _ksp_viewport
            cur_hash = _ksp_viewport.image_content_hash(item.image) or hashlib.sha1(png).hexdigest()
        except Exception:
            cur_hash = hashlib.sha1(png).hexdigest()
        orig_hash = ""
        fmt = 0
        try:
            orig_hash = str(getattr(item, "content_hash", "") or "")
            fmt = int(getattr(item, "texture_format", 0) or 0)
        except Exception:
            pass
        # dirty → always write; empty content_hash → treat as changed;
        # otherwise skip only when hash still matches.
        if not dirty and orig_hash and cur_hash == orig_hash:
            # Still rewrite when Unity Texture2D has no pixels (empty inject
            # clones / prior apply wiped by obj.read()). Otherwise hash skip
            # leaves stock Antenna stubs forever.
            force = False
            try:
                from ..import_ksp.bundle import texture_has_embedded_or_streamed_pixels
                for _obj in env.objects:
                    if _obj.type.name != "Texture2D" or int(_obj.path_id) != int(pid):
                        continue
                    force = not texture_has_embedded_or_streamed_pixels(_obj.read())
                    break
            except Exception:
                force = False
            if not force:
                try:
                    from PIL import Image as _PILImage
                    _png_wh = _PILImage.open(io.BytesIO(png)).size
                    _uwh = _unity_texture_size(env, pid)
                    if (
                        _png_wh
                        and _uwh[0] > 0
                        and _uwh[1] > 0
                        and _png_wh != _uwh
                    ):
                        force = True
                except Exception:
                    force = False
            if not force:
                n_tex_skip += 1
                continue
            print(
                "INFO: KSP texture export: forcing rewrite of empty Unity "
                "Texture2D %r path_id=%s"
                % (getattr(item, "name", "") or "?", pid)
            )
        keep_unity = True
        try:
            from PIL import Image as _PILImage
            _png_wh = _PILImage.open(io.BytesIO(png)).size
            _uwh = _unity_texture_size(env, pid)
            user_tex = _texture_item_is_user_art(kb, item)
            if user_tex:
                keep_unity = False
            elif (
                _png_wh
                and _uwh[0] > 0
                and _uwh[1] > 0
                and _png_wh != _uwh
            ):
                sa = float(_png_wh[0]) / float(max(1, _png_wh[1]))
                da = float(_uwh[0]) / float(max(1, _uwh[1]))
                if abs(sa - da) > 0.03:
                    keep_unity = False
        except Exception:
            keep_unity = True
        if apply_texture_png(
            env, pid, png, texture_format=fmt,
            keep_unity_size=keep_unity,
        ):
            n_tex_write += 1
            try:
                item.content_hash = cur_hash
                item.dirty = False
                item.path_id = str(pid)
            except Exception:
                pass
            try:
                uw, uh = _unity_texture_size(env, pid)
                if uw >= 4 and uh >= 4:
                    item.width = int(uw)
                    item.height = int(uh)
            except Exception:
                pass
            # Persist alpha format when letterboxing so re-export stays DXT5.
            try:
                from PIL import Image as _PILImage
                from ..import_ksp.bundle import (
                    _rgba_needs_alpha_format,
                    _format_with_alpha,
                )
                _im = _PILImage.open(io.BytesIO(png)).convert("RGBA")
                _tw = int(getattr(item, "width", 0) or 0)
                _th = int(getattr(item, "height", 0) or 0)
                _need = (_tw > 0 and _th > 0 and _im.size != (_tw, _th)) or (
                    _rgba_needs_alpha_format(_im)
                )
                if _need:
                    item.texture_format = int(
                        _format_with_alpha(int(getattr(item, "texture_format", 0) or 0))
                    )
            except Exception:
                pass
        else:
            print(
                "WARNING: KSP texture export: apply_texture_png failed for "
                "%r path_id=%s"
                % (getattr(item, "name", "") or "?", pid)
            )
            n_tex_fail += 1
    print(
        "INFO: KSP texture export: wrote=%d skipped=%d failed=%d"
        % (n_tex_write, n_tex_skip, n_tex_fail)
    )

    # Drop Texture2D / Sprite assets removed from the Blender list (or never
    # kept) when nothing in the bundle still references them.
    n_orphan_tex = 0
    n_orphan_spr = 0
    try:
        keep_tex = texture_pids_kept_by_blender(kb)
        candidates = collect_orphan_texture_candidates(env, kb, root)
        if candidates:
            n_orphan_tex, n_orphan_spr = purge_unreferenced_texture_assets(
                env, candidates, keep_tex_ids=keep_tex,
            )
        if n_orphan_tex or n_orphan_spr:
            did_pack_autofix = True
            print(
                "INFO: KSP export: purged unreferenced assets "
                "tex=%d sprite=%d (candidates=%d)"
                % (n_orphan_tex, n_orphan_spr, len(candidates))
            )
            try:
                kb.pending_remove_textures = ""
            except Exception:
                pass
            try:
                root["ksp_pending_remove_textures"] = ""
            except Exception:
                pass
        elif candidates:
            print(
                "INFO: KSP export: %d texture candidate(s) still referenced "
                "- kept"
                % len(candidates)
            )
    except Exception as ex:
        print("WARNING: KSP export: orphan texture purge failed: %s" % ex)

    n_text_write = 0
    n_ui_write = 0

    # Push Blender UI texts into KSPedia XML TextAsset BEFORE writing TextAssets,
    # so planetarybaseinc_kspedia <Text Name> nodes match MonoBehaviour m_Text.
    try:
        from ..import_ksp import kspedia_index as _kidx_txt
        _xml_entries = []
        for _el in list(kb.ui_elements):
            try:
                if str(getattr(_el, "kind", "") or "") != "text":
                    continue
            except Exception:
                continue
            _nm = (getattr(_el, "name", "") or "").strip()
            if not _nm:
                continue
            if sync_from_viewport:
                try:
                    _sync_el_from_viewport(root, _el)
                except Exception:
                    pass
            try:
                _tx = _resolve_ui_text(
                    root, _el, prefer_list=prefer_list_text,
                )
            except Exception:
                _tx = getattr(_el, "text", None) or ""
            try:
                _tx, _ = sanitize_ui_text_for_ksp(_tx, is_ui_text=True)
            except Exception:
                pass
            _alive = True
            try:
                if bool(getattr(_el, "missing_in_locale", False)):
                    _alive = False
            except Exception:
                pass
            # Keep list row identical to what we bake into MB + XML.
            try:
                if _alive and getattr(_el, "text", None) != _tx:
                    _el.text = _tx
            except Exception:
                pass
            _xml_entries.append({
                "page_screen": (getattr(_el, "page_screen", "") or "").strip(),
                "name": _nm,
                "text": _tx if _alive else "",
                "alive": _alive,
            })
        _n_xml_txt = _kidx_txt.sync_ui_texts_into_kspedia_xml(kb, _xml_entries)
        if _n_xml_txt:
            print(
                "INFO: KSP export: synced %d KSPedia XML text node change(s)"
                % _n_xml_txt
            )
            did_pack_autofix = True
    except Exception as _xml_sync_ex:
        print("WARNING: KSPedia XML text sync failed: %s" % _xml_sync_ex)

    # Text assets from text blocks / inline text
    _p(40, text="Exporting text assets…")
    ta_by_name = {}
    try:
        ta_by_name = _text_asset_ids_by_name(env)
    except Exception:
        ta_by_name = {}
    for item in kb.text_assets:
        try:
            pid = int(item.path_id)
        except Exception:
            continue
        name = (getattr(item, "name", "") or "").strip()
        lname = name.lower()
        # *_bundle.xml is owned by ensure_local_page_prefabs /
        # update_bundle_definition_xml. Rewriting it from the Blender list
        # wiped Asset rows for blank NewPage → game error
        # "Cannot find asset definition … NewPage.prefab".
        if lname.endswith("_bundle"):
            continue
        if lname and lname in ta_by_name:
            pid = int(ta_by_name[lname])
        else:
            xml_name = (getattr(kb, "kspedia_xml_asset", "") or "").strip().lower()
            is_kspedia = (xml_name and lname == xml_name) or (
                "kspedia" in lname and "bundle" not in lname
            )
            if is_kspedia:
                alt = _find_kspedia_xml_path_id(env)
                if alt:
                    pid = alt
        text = item.text or ""
        if item.text_block is not None:
            try:
                text = item.text_block.as_string()
            except Exception:
                text = "\n".join(line.body for line in item.text_block.lines)
        if _text_asset_unchanged(env, pid, text):
            continue
        if apply_text_asset(env, pid, text):
            n_text_write += 1

    # UI MonoBehaviours and RectTransforms.  The bundle-list properties are
    # authoritative; matching viewport properties fill gaps for scripted UI.
    ui_items = list(kb.ui_elements)
    n_ui = max(len(ui_items), 1)
    for i, el in enumerate(ui_items):
        if progress_start is not None:
            tick_items(
                i, n_ui,
                int(progress_start) + int(0.42 * (int(progress_end) - int(progress_start))),
                int(progress_start) + int(0.85 * (int(progress_end) - int(progress_start))),
                text="Exporting UI elements…",
            )
        if sync_from_viewport:
            _sync_el_from_viewport(root, el)
            ui = _viewport_ui_for_element(root, el)
            vo = _viewport_object_for_element(root, el)
        else:
            # Pointer only — do not name-search (copy vs original). Live
            # G/R/S still belong to the viewport language.
            ui = None
            vo = getattr(el, "viewport_object", None)
        loc_edit = None
        if not sync_from_viewport:
            loc_edit = _el_locale_has_viewport_edit(kb, el, vo, export_loc)
        try:
            mid = int(el.mb_path_id)
        except Exception:
            mid = 0
        try:
            rid = int(el.rect_path_id)
        except Exception:
            rid = 0
        el_name = (getattr(el, "name", "") or "").strip()
        # Sibling .lang renumbers fileIDs; keep grafted mid/rid only if present.
        mid, rid = _remap_ui_ids_for_env(env, path_remap, el_name, mid, rid)
        skip_missing = bool(getattr(el, "missing_in_locale", False))
        try:
            vo_ship = getattr(el, "viewport_object", None)
            if _vo_skipped_for_locale(vo_ship, export_loc):
                skip_missing = True
        except Exception:
            pass
        if skip_missing and sync_from_viewport:
            # Live main-.ksp export: stale missing flags from a sibling-locale
            # preview must not leave stock UnityFS text in the default file.
            # User-added "this language only" keeps skip_missing.
            try:
                vo_chk = getattr(el, "viewport_object", None)
                userish = bool(vo_chk.get("ksp_user_added")) if vo_chk is not None else False
                if userish or _vo_skipped_for_locale(vo_chk, export_loc):
                    pass
                elif _viewport_ui_for_element(root, el) is not None:
                    skip_missing = False
            except Exception:
                pass
        hide_after_write = False
        if skip_missing:
            # Not part of this language: never write our text over it.
            # Only deactivate user-added LOCAL clones — stock originals
            # flagged missing (incomplete .lang maps) must stay in Unity.
            # User images still write sprite/rect into the shared .ksp, then
            # go inactive — otherwise Add Image on DE vanished on reimport.
            userish = False
            kind_now = str(getattr(el, "kind", "") or "")
            try:
                vo_chk = getattr(el, "viewport_object", None)
                userish = bool(
                    vo_chk is not None and vo_chk.get("ksp_user_added")
                )
            except Exception:
                userish = False
            if userish and kind_now == "image":
                hide_after_write = True
            else:
                if userish:
                    if _deactivate_el_in_env(env, el):
                        n_ui_write += 1
                continue
        if el.kind == 'text' and mid:
            try:
                from ..import_ksp.ui_roundtrip import set_game_object_active
                set_game_object_active(env, mid, True)
            except Exception:
                pass
            color = tuple(el.color)
            font_size = float(el.font_size)
            if (
                sync_from_viewport
                and ui is not None
                and not el.text
                and ui.text
            ):
                text = ui.text
            else:
                text = _resolve_ui_text(root, el, prefer_list=prefer_list_text)
            # UI.Text + <color> is stock-ok (de-de .lang). Strip only when
            # RectTransform has non-identity R/S (crash combo on Reentry).
            is_ui = False
            try:
                is_ui = bool(getattr(el, "is_ui_text", False))
                if not is_ui and ui is not None:
                    is_ui = bool(getattr(ui, "is_ui_text", False))
                if not is_ui:
                    scn = str(getattr(el, "script_class", "") or "")
                    fam = str(getattr(el, "font_family", "") or "").lower()
                    if "uitext" in scn.lower() or "unityengine.ui.text" in scn.lower():
                        is_ui = True
                    if "opensans" in fam or ("amaranth" in fam and "sdf" not in fam):
                        is_ui = True
            except Exception:
                is_ui = False
            try:
                _vo = _viewport_ui_for_element(root, el) if sync_from_viewport else None
            except Exception:
                _vo = None
            text, dom_col = sanitize_ui_text_for_ksp(
                text,
                is_ui_text=is_ui,
                local_rotation=_rect_local_rotation(
                    el, _vo, prefer_list=not sync_from_viewport,
                    locale_has_edit=(
                        None if sync_from_viewport
                        else _el_locale_has_viewport_edit(
                            kb, el, _vo, export_loc,
                        )
                    ),
                ),
                local_scale=_rect_local_scale(
                    el, _vo, prefer_list=not sync_from_viewport,
                    locale_has_edit=(
                        None if sync_from_viewport
                        else _el_locale_has_viewport_edit(
                            kb, el, _vo, export_loc,
                        )
                    ),
                ),
            )
            color_kw = color
            vo_col = None
            ov_col = {}
            try:
                vo_col = getattr(el, "viewport_object", None)
                if vo_col is None and sync_from_viewport:
                    vo_col = _viewport_object_for_element(root, el)
                ov_col = _vo_user_overrides(vo_col)
                if (
                    "color" not in ov_col
                    and not bool(vo_col.get("ksp_user_added") if vo_col else False)
                    and not _vo_viewport_edit(vo_col)
                ):
                    color_kw = None
            except Exception:
                pass
            if dom_col is not None and is_ui:
                try:
                    color_kw = tuple(dom_col)
                except Exception:
                    pass
            # Skip full style write only when text *and* colour/size match disk.
            text_only_same = _ui_style_unchanged(
                env, mid, text, el.kind,
                color=color_kw, font_size=font_size,
            )
            # Resolve font only when missing - never wipe external squadcore
            # FontAsset PPtrs (that caused white tofu squares in-game).
            fpid = int(getattr(el, "font_asset_path_id", 0) or 0)
            ffid = int(getattr(el, "font_asset_file_id", 0) or 0)
            fam = (getattr(el, "font_family", "") or "").strip()
            if not fam:
                try:
                    if ui is not None:
                        fam = (getattr(ui, "font_family", "") or "").strip()
                except Exception:
                    pass
            if not fam and vo is not None:
                try:
                    if getattr(vo, "type", "") == "FONT" and vo.data and vo.data.font:
                        fam = str(vo.data.font.name or "").strip()
                except Exception:
                    pass
            # Stale OpenSans path_id + a new family (NotoSans-Bold stand-in)
            # used to rewrite the old PPtr and the face reverted on reimport.
            font_dirty = False
            try:
                from ..import_ksp.ui_roundtrip import (
                    resolve_font_path_id_from_kb,
                    resolve_font_path_id_by_name,
                    _font_name_key,
                )
                want_key = _font_name_key(fam)
                cur_key = ""
                if fpid:
                    try:
                        for _fo in env.objects:
                            if int(_fo.path_id) != int(fpid):
                                continue
                            if _fo.type.name == "Font":
                                cur_key = _font_name_key(
                                    str(getattr(_fo.read(), "m_Name", "") or "")
                                )
                            else:
                                cur_key = _font_name_key(
                                    str(_fo.read_typetree().get("m_Name") or "")
                                )
                            break
                    except Exception:
                        cur_key = ""
                need_resolve = bool(fam) and (
                    not fpid
                    or not want_key
                    or not cur_key
                    or want_key != cur_key
                )
                if need_resolve:
                    rf, rp = resolve_font_path_id_from_kb(kb, fam)
                    if not rp:
                        rf, rp = resolve_font_path_id_by_name(env, fam)
                    if not rp:
                        try:
                            from .prefab_clone import ensure_named_font_asset
                            rf, rp = ensure_named_font_asset(
                                env, fam, kb=kb,
                            )
                        except Exception:
                            rf, rp = 0, 0
                    if rp:
                        fpid, ffid = int(rp), int(rf or 0)
                        font_dirty = True
                        try:
                            el.font_asset_path_id = str(int(fpid))
                            el.font_asset_file_id = str(int(ffid))
                        except Exception:
                            pass
            except Exception:
                pass
            if font_dirty:
                text_only_same = False
            # Only rewrite FontAsset when we have a real path id.
            font_kw = {}
            if fpid:
                font_kw["font_asset_path_id"] = fpid
                font_kw["font_asset_file_id"] = ffid
            if not text_only_same:
                n_ui_write += 1
                apply_ui_style(
                    env, mid, text=text, color=color_kw, font_size=font_size,
                    text_alignment=int(getattr(el, "text_alignment", 0) or 0),
                    font_style=int(getattr(el, "font_style", 0) or 0),
                    enable_word_wrapping=bool(getattr(el, "enable_word_wrapping", True)),
                    line_spacing=float(getattr(el, "line_spacing", 0.0) or 0.0),
                    margin=tuple(getattr(el, "margin", (0.0, 0.0, 0.0, 0.0))),
                    is_rich_text=bool(getattr(el, "is_rich_text", True)),
                    character_spacing=float(getattr(el, "character_spacing", 0.0) or 0.0),
                    word_spacing=float(getattr(el, "word_spacing", 0.0) or 0.0),
                    paragraph_spacing=float(getattr(el, "paragraph_spacing", 0.0) or 0.0),
                    enable_auto_sizing=bool(getattr(el, "enable_auto_sizing", False)),
                    font_size_min=float(getattr(el, "font_size_min", 0.0) or 0.0),
                    font_size_max=float(getattr(el, "font_size_max", 0.0) or 0.0),
                    overflow_mode=int(getattr(el, "overflow_mode", 0) or 0),
                    enable_kerning=bool(getattr(el, "enable_kerning", True)),
                    horizontal_alignment=int(getattr(el, "horizontal_alignment", 0) or 0),
                    vertical_alignment=int(getattr(el, "vertical_alignment", 0) or 0),
                    **font_kw,
                    tint_all_sprites=bool(getattr(el, "tint_all_sprites", False)),
                    horizontal_mapping=int(getattr(el, "horizontal_mapping", 0) or 0),
                    vertical_mapping=int(getattr(el, "vertical_mapping", 0) or 0),
                    is_volumetric_text=bool(getattr(el, "is_volumetric_text", False)),
                    page_to_display=int(getattr(el, "page_to_display", 1) or 1),
                    linked_text_path_id=int(
                        getattr(el, "linked_text_path_id", 0) or 0
                    ) or None,
                    **(
                        dict(
                            outline_width=float(getattr(el, "outline_width", 0.0) or 0.0),
                            outline_color=tuple(getattr(el, "outline_color", (0.0, 0.0, 0.0, 1.0))),
                            face_color=tuple(getattr(el, "face_color", (1.0, 1.0, 1.0, 1.0))),
                            enable_vertex_gradient=bool(
                                getattr(el, "enable_vertex_gradient", False)
                            ),
                            gradient_top_left=tuple(
                                getattr(el, "gradient_top_left", (1, 1, 1, 1))
                            ),
                            gradient_top_right=tuple(
                                getattr(el, "gradient_top_right", (1, 1, 1, 1))
                            ),
                            gradient_bottom_left=tuple(
                                getattr(el, "gradient_bottom_left", (1, 1, 1, 1))
                            ),
                            gradient_bottom_right=tuple(
                                getattr(el, "gradient_bottom_right", (1, 1, 1, 1))
                            ),
                        )
                        if (
                            ("color" in ov_col)
                            or bool(vo_col.get("ksp_user_added") if vo_col else False)
                        )
                        else {}
                    ),
                )
        elif el.kind == 'image' and mid:
            # Only rewrite when this image differs from disk - never cascade
            # from a sibling text edit (that forced UnityPy repacks).
            try:
                spid = int(el.sprite_path_id or 0)
            except Exception:
                spid = 0
            try:
                tpid = int(el.texture_path_id or 0)
            except Exception:
                tpid = 0
            img_kwargs = dict(
                image_type=int(getattr(el, "image_type", 0) or 0),
                preserve_aspect=bool(getattr(el, "preserve_aspect", False)),
                fill_center=bool(getattr(el, "fill_center", True)),
                fill_method=int(getattr(el, "fill_method", 0) or 0),
                fill_amount=float(getattr(el, "fill_amount", 1.0) or 1.0),
                fill_clock_wise=bool(getattr(el, "fill_clock_wise", True)),
                fill_origin=int(getattr(el, "fill_origin", 0) or 0),
                # Never pass sprite_path_id=0 — that would null m_Sprite and
                # crash InstantiateScreen. Missing id → leave Unity sprite.
                sprite_path_id=(spid if spid else None),
                texture_path_id=(
                    tpid if getattr(el, "is_raw_image", False) else None
                ),
            )
            try:
                vo_img = getattr(el, "viewport_object", None)
                ov_img = {}
                if vo_img is not None:
                    raw_ov = vo_img.get("ksp_user_overrides") or {}
                    ov_img = raw_ov if isinstance(raw_ov, dict) else {}
                user_img = bool(vo_img.get("ksp_user_added")) if vo_img is not None else False
                if user_img or "color" in ov_img:
                    img_kwargs["color"] = tuple(el.color)
            except Exception:
                pass
            img_same = False
            try:
                img_same = bool(
                    ui_roundtrip.ui_image_unchanged(env, mid, **img_kwargs)
                )
            except Exception:
                img_same = False
            if not img_same:
                if apply_ui_image(env, mid, **img_kwargs):
                    n_ui_write += 1
        rot = _rect_local_rotation(
            el, vo, prefer_list=not sync_from_viewport,
            locale_has_edit=loc_edit,
        )
        sc = _rect_local_scale(
            el, vo, prefer_list=not sync_from_viewport,
            locale_has_edit=loc_edit,
        )
        zpos = _rect_local_position_z(el, vo)

        def _close4(a, b, eps=1e-5):
            try:
                return all(abs(float(a[i]) - float(b[i])) <= eps for i in range(4))
            except Exception:
                return False

        def _close3(a, b, eps=1e-5):
            try:
                return all(abs(float(a[i]) - float(b[i])) <= eps for i in range(3))
            except Exception:
                return False

        def _disk_rt_trs(rect_id):
            """UnityFS RectTransform R/S/Z - ground truth for dirty checks."""
            if not rect_id:
                return None
            try:
                from ..import_ksp.bundle import _vec3, _quat
            except Exception:
                _vec3 = _quat = None
            for obj in env.objects:
                try:
                    if obj.type.name != "RectTransform":
                        continue
                    if int(obj.path_id) != int(rect_id):
                        continue
                    tree = obj.read_typetree()
                except Exception:
                    continue
                try:
                    if _quat is not None:
                        q = _quat(tree.get("m_LocalRotation"))
                        s = _vec3(tree.get("m_LocalScale"))
                    else:
                        rq = tree.get("m_LocalRotation") or {}
                        rs = tree.get("m_LocalScale") or {}
                        q = (
                            float(rq.get("x", 0)), float(rq.get("y", 0)),
                            float(rq.get("z", 0)), float(rq.get("w", 1)),
                        )
                        s = (
                            float(rs.get("x", 1)), float(rs.get("y", 1)),
                            float(rs.get("z", 1)),
                        )
                    z = 0.0
                    if "m_LocalPosition" in tree:
                        rp = tree.get("m_LocalPosition") or {}
                        z = float(rp.get("z", 0) if isinstance(rp, dict) else 0)
                    return q, s, z
                except Exception:
                    return None
            return None

        # Compare live export values to the UnityFS template - stamps on the
        # viewport can already match a captured edit after locale apply, and
        # el after _sync always matches live (old trs_dirty was always False).
        trs_dirty = False
        disk = _disk_rt_trs(rid) if rid else None
        if disk is not None:
            dq, ds, dz = disk
            trs_dirty = (
                (not _close4(rot, dq))
                or (not _close3(sc, ds))
                or (abs(float(zpos) - float(dz)) > 1e-6)
            )
        elif vo is not None:
            # Fallback: import stamps / user overrides
            try:
                stamp_q = vo.get("ksp_local_rotation", None)
                stamp_s = vo.get("ksp_local_scale", None)
                raw_ov = vo.get("ksp_user_overrides") or {}
            except Exception:
                stamp_q, stamp_s, raw_ov = None, None, {}
            if stamp_q is not None and len(stamp_q) >= 4:
                trs_dirty = trs_dirty or (not _close4(rot, stamp_q))
            if stamp_s is not None and len(stamp_s) >= 3:
                trs_dirty = trs_dirty or (not _close3(sc, stamp_s))
            if isinstance(raw_ov, dict) and (
                "rotation_euler" in raw_ov
                or "scale" in raw_ov
                or "local_rotation" in raw_ov
                or "local_scale" in raw_ov
            ):
                trs_dirty = True

        # Layout fields: write when the user moved/resized the element.
        # ``ksp_user_overrides`` alone is not enough - G-moves update
        # ``ksp_ui.anchored_position`` via live sync but never stamped the
        # override dict, so ALT / showModCategory / duplicates kept stock XY.
        ov = _vo_user_overrides(vo)
        layout_dirty = any(
            k in ov
            for k in (
                "size_delta",
                "anchored_position",
                "pivot",
                "anchor_min",
                "anchor_max",
                "offset_min",
                "offset_max",
                "box_width_px",
            )
        )
        try:
            if vo is not None and bool(vo.get("ksp_user_added")):
                layout_dirty = True
        except Exception:
            pass
        try:
            if sync_from_viewport and _vo_viewport_edit(vo):
                layout_dirty = True
            elif (not sync_from_viewport) and _el_locale_has_viewport_edit(
                kb, el, vo, export_loc,
            ):
                layout_dirty = True
        except Exception:
            pass
        overlay_lock = False
        try:
            from ..import_ksp.viewport import is_artwork_overlay as _is_art
            raw_txt = str(getattr(el, "text", "") or "")
            overlay_lock = bool(_is_art(raw_txt, vo))
        except Exception:
            overlay_lock = False
        user_added_el = False
        try:
            user_added_el = bool(vo is not None and vo.get("ksp_user_added"))
        except Exception:
            user_added_el = False
        layout_allowed = _export_layout_allowed(
            vo, ov, user_added_el, overlay_lock=overlay_lock,
            locale_has_edit=loc_edit,
        )
        if not layout_dirty and rid and not overlay_lock and layout_allowed:
            try:
                want_ap = tuple(float(x) for x in (el.anchored_position or (0, 0))[:2])
            except Exception:
                want_ap = None
            disk_ap = None
            try:
                from ..import_ksp.bundle import _vec2
                for obj in env.objects:
                    try:
                        if obj.type.name != "RectTransform":
                            continue
                        if int(obj.path_id) != int(rid):
                            continue
                        tree = obj.read_typetree()
                        disk_ap = _vec2(tree.get("m_AnchoredPosition"))
                        break
                    except Exception:
                        continue
            except Exception:
                disk_ap = None
            if (
                want_ap is not None
                and disk_ap is not None
                and len(disk_ap) >= 2
                and any(abs(float(want_ap[i]) - float(disk_ap[i])) > 0.05 for i in range(2))
            ):
                layout_dirty = True

        # Only the viewport-locale export may treat list size_delta vs disk
        # as dirty. Sibling .lang keeps leftover EN Size X on the same rows.
        if (
            not layout_dirty
            and rid
            and not overlay_lock
            and sync_from_viewport
            and layout_allowed
        ):
            try:
                want_sd = tuple(float(x) for x in (el.size_delta or (0, 0))[:2])
            except Exception:
                want_sd = None
            disk_sd = None
            try:
                from ..import_ksp.bundle import _vec2
                for obj in env.objects:
                    try:
                        if obj.type.name != "RectTransform":
                            continue
                        if int(obj.path_id) != int(rid):
                            continue
                        tree = obj.read_typetree()
                        disk_sd = _vec2(tree.get("m_SizeDelta"))
                        break
                    except Exception:
                        continue
            except Exception:
                disk_sd = None
            if (
                want_sd is not None
                and disk_sd is not None
                and len(disk_sd) >= 2
                and any(abs(float(want_sd[i]) - float(disk_sd[i])) > 0.5 for i in range(2))
            ):
                layout_dirty = True

        # Native FONT Text Boxes Size X/Y (ConfS2 818→1457) even when the
        # pin restamped ksp_ui and ov still holds the stock Unity size.
        # Sibling .lang export keeps the English viewport (update_viewport=
        # False). Live Size X must NOT be copied onto other languages.
        live_box_for_this_locale = True
        try:
            exp_loc = str(export_loc or "").strip().lower()
            applied = ""
            if vo is not None:
                applied = str(vo.get("ksp_locale_applied") or "").strip().lower()
            if exp_loc and applied and exp_loc != applied:
                live_box_for_this_locale = False
            elif exp_loc and not applied:
                view_loc = str(getattr(kb, "active_locale", "") or "").strip().lower()
                if view_loc and exp_loc != view_loc:
                    live_box_for_this_locale = False
        except Exception:
            live_box_for_this_locale = True
        if not overlay_lock and vo is not None and live_box_for_this_locale:
            try:
                from ..import_ksp.locale_buffers import persist_live_font_box_size
                sx = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
                from ..import_ksp.locale_buffers import live_font_box_size_delta
                live_box = live_font_box_size_delta(vo, pixel_scale=sx)
                # live_font_box_size_delta already requires real box resize vs stamp;
                # do not also require layout_allowed (that blocked USER-OLD-002 Size X).
                # Text Boxes Size X/Y must hit ksp_user_overrides before pin restamp.
                if live_box is not None:
                    persist_live_font_box_size(vo, pixel_scale=sx)
                    ov = dict(_vo_user_overrides(vo))
                    nw, nh = float(live_box[0]), float(live_box[1])
                    el.size_delta = (nw, nh)
                    layout_dirty = True
                    ov = dict(ov or {})
                    ov["size_delta"] = (nw, nh)
                    ov["box_width_px"] = abs(nw)
                else:
                    from ..import_ksp.locale_buffers import font_curve_obj
                    fo = font_curve_obj(vo)
                    curve = getattr(fo, "data", None) or fo
                    tb = None
                    try:
                        tb = curve.text_boxes[0]
                    except Exception:
                        tb = None
                    if tb is not None:
                        tbw = abs(float(tb.width)) / sx
                        tbh = abs(float(tb.height)) / sx
                        unity_w = None
                        try:
                            from ..import_ksp.locale_buffers import import_content_size_of
                            ics = import_content_size_of(vo)
                            if ics is not None:
                                unity_w = abs(float(ics[0]))
                        except Exception:
                            unity_w = None
                        if unity_w is None or unity_w < 1.0:
                            try:
                                unity_w = abs(float((vo.ksp_ui.size_delta or (0.0, 0.0))[0]))
                            except Exception:
                                unity_w = 0.0
                        nw, nh = unity_w, None
                        try:
                            nh = abs(float((el.size_delta or (0.0, 0.0))[1]))
                        except Exception:
                            nh = 0.0
                        changed = False
                        # Only bake FONT box growth when it moved off the
                        # frozen import box (real Size X) — not grow_single.
                        try:
                            from ..import_ksp.locale_buffers import import_font_box_of
                            ib = import_font_box_of(vo)
                            imp_w = abs(float(ib[0])) / sx if ib is not None else None
                        except Exception:
                            imp_w = None
                        # Same slack as live_font_box_size_delta — do not bake
                        # import FONT-box calibration (~18 px) into Unity.
                        if (
                            tbw > 1.0
                            and (tbw - float(unity_w or 0.0)) > 32.0
                            and (
                                imp_w is None
                                or abs(tbw - float(imp_w)) > 32.0
                            )
                        ):
                            nw = tbw
                            changed = True
                        # Grow-only. Glyph auto-fit can leave a short height=N
                        # box; shipping that clipped every language.
                        if tbh > 0.75 and (tbh - float(nh or 0.0)) > 32.0:
                            nh = tbh
                            changed = True
                        if changed:
                            el.size_delta = (nw, nh)
                            layout_dirty = True
                            ov = dict(ov or {})
                            ov["size_delta"] = (nw, nh)
                            ov["box_width_px"] = abs(nw)
            except Exception:
                pass
            if layout_allowed:
                try:
                    usd = tuple(
                        float(x) for x in (vo.ksp_ui.size_delta or (0.0, 0.0))[:2]
                    )
                    cur = tuple(
                        float(x) for x in (el.size_delta or (0.0, 0.0))[:2]
                    )
                    if (
                        abs(usd[0] - cur[0]) > 0.75
                        or abs(usd[1] - cur[1]) > 0.75
                    ):
                        el.size_delta = (usd[0], usd[1])
                        layout_dirty = True
                        ov = dict(ov or {})
                        ov["size_delta"] = usd
                        ov["box_width_px"] = abs(usd[0])
                except Exception:
                    pass
        # Unedited sibling .lang: keep the language template. Live ov /
        # ksp_has_viewport_edit / EN-baked el.local_* belong to default.
        if (
            (not sync_from_viewport)
            and (not user_added_el)
            and (loc_edit is not True)
        ):
            layout_dirty = False
            trs_dirty = False
        if (trs_dirty or layout_dirty) and rid:
            ap = sd = pv = amin = amax = omin = omax = None
            if layout_dirty:
                write_ap = False
                try:
                    if user_added_el:
                        write_ap = True
                    elif sync_from_viewport and (
                        any(k in ov for k in _POS_OV_KEYS)
                        or _vo_viewport_edit(vo)
                    ):
                        write_ap = True
                    elif (not sync_from_viewport) and loc_edit:
                        write_ap = True
                except Exception:
                    write_ap = False
                try:
                    if (
                        overlay_lock
                        and not bool(vo.get("ksp_user_added") if vo is not None else False)
                        and not (
                            (sync_from_viewport and _vo_viewport_edit(vo))
                            or ((not sync_from_viewport) and loc_edit)
                        )
                        and "anchored_position" not in ov
                    ):
                        write_ap = False
                except Exception:
                    pass
                if write_ap:
                    try:
                        ap = tuple(el.anchored_position[:2])
                    except Exception:
                        ap = None
                else:
                    ap = None
                # Stock overlay texts (ConfB*/ConfSubheader2): AP-only dirty
                # must not ship Blender FONT box width as Unity sizeDelta.
                write_sd = False
                try:
                    if vo is not None and bool(vo.get("ksp_user_added")):
                        write_sd = True
                except Exception:
                    write_sd = False
                if not write_sd:
                    try:
                        write_sd = "size_delta" in ov or "box_width_px" in ov
                    except Exception:
                        write_sd = False
                    # English viewport Size X lives on the object overrides.
                    # Sibling .lang must not inherit it (USER-OLD-002).
                    if write_sd and not live_box_for_this_locale:
                        write_sd = False
                if not write_sd and rid and not overlay_lock and live_box_for_this_locale:
                    try:
                        want_sd = tuple(float(x) for x in (el.size_delta or (0, 0))[:2])
                    except Exception:
                        want_sd = None
                    disk_sd = None
                    try:
                        from ..import_ksp.bundle import _vec2
                        for obj in env.objects:
                            try:
                                if obj.type.name != "RectTransform":
                                    continue
                                if int(obj.path_id) != int(rid):
                                    continue
                                tree = obj.read_typetree()
                                disk_sd = _vec2(tree.get("m_SizeDelta"))
                                break
                            except Exception:
                                continue
                    except Exception:
                        disk_sd = None
                    if (
                        want_sd is not None
                        and disk_sd is not None
                        and len(disk_sd) >= 2
                        and any(
                            abs(float(want_sd[i]) - float(disk_sd[i])) > 0.5
                            for i in range(2)
                        )
                    ):
                        write_sd = True
                if write_sd:
                    sd = None
                    try:
                        ov_sd = ov.get("size_delta") if isinstance(ov, dict) else None
                        if ov_sd is not None and len(ov_sd) >= 2:
                            sd = (float(ov_sd[0]), float(ov_sd[1]))
                    except Exception:
                        sd = None
                    if sd is None and vo is not None:
                        try:
                            usd = tuple(float(x) for x in (vo.ksp_ui.size_delta or (0, 0))[:2])
                            if abs(usd[0]) > 1.0 or abs(usd[1]) > 1.0:
                                sd = usd
                        except Exception:
                            sd = None
                    if sd is None:
                        try:
                            sd = tuple(el.size_delta[:2])
                        except Exception:
                            sd = None
                # Never ship Image sizeDelta 0×0 for *point-anchored* clones —
                # donor shells / failed sync leave Load Image invisible.
                # Stretch + 0×0 is intentional fill-parent (do not write WH).
                try:
                    amin_chk = tuple(el.anchor_min)
                    amax_chk = tuple(el.anchor_max)
                    stretch_img = (
                        abs(float(amax_chk[0]) - float(amin_chk[0])) > 1e-4
                        or abs(float(amax_chk[1]) - float(amin_chk[1])) > 1e-4
                    )
                except Exception:
                    stretch_img = False
                # Prior bad export: stretch Image with sizeDelta = texture/page
                # size → crect 2× parent. Normalize back to fill-parent 0×0.
                if (
                    getattr(el, "kind", "") == "image"
                    and stretch_img
                    and sd is not None
                ):
                    try:
                        from .prefab_clone import _sprite_wh, _texture_wh
                        af = None
                        for _o in env.objects:
                            af = _o.assets_file
                            break
                        tw = th = 0.0
                        spid = int(getattr(el, "sprite_path_id", 0) or 0)
                        tpid = int(getattr(el, "texture_path_id", 0) or 0)
                        if af is not None and spid:
                            tw, th = _sprite_wh(af, spid)
                        if (tw < 1.0 or th < 1.0) and af is not None and tpid:
                            tw, th = _texture_wh(af, tpid)
                        sdx, sdy = float(sd[0]), float(sd[1])
                        if (
                            tw >= 1.0
                            and th >= 1.0
                            and abs(sdx - tw) < 1.5
                            and abs(sdy - th) < 1.5
                        ):
                            sd = (0.0, 0.0)
                            try:
                                el.size_delta = (0.0, 0.0, 0.0)
                            except Exception:
                                try:
                                    el.size_delta = (0.0, 0.0)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if (
                    getattr(el, "kind", "") == "image"
                    and sd is not None
                    and not stretch_img
                    and (abs(float(sd[0])) < 1.0 or abs(float(sd[1])) < 1.0)
                ):
                    w = h = 0.0
                    try:
                        if ui is not None:
                            usd = tuple(ui.size_delta or (0.0, 0.0))
                            w, h = float(usd[0]), float(usd[1])
                    except Exception:
                        w = h = 0.0
                    if w < 1.0 or h < 1.0:
                        try:
                            if vo is not None and vo.data and getattr(
                                vo.data, "materials", None
                            ):
                                mat = vo.data.materials[0] if vo.data.materials else None
                                if mat and mat.use_nodes:
                                    for node in mat.node_tree.nodes:
                                        img = getattr(node, "image", None)
                                        if img is not None and img.size[0] and img.size[1]:
                                            w, h = float(img.size[0]), float(img.size[1])
                                            break
                        except Exception:
                            pass
                    if w < 1.0 or h < 1.0:
                        try:
                            from .prefab_clone import _sprite_wh, _texture_wh
                            af = None
                            for _o in env.objects:
                                af = _o.assets_file
                                break
                            spid = int(getattr(el, "sprite_path_id", 0) or 0)
                            tpid = int(getattr(el, "texture_path_id", 0) or 0)
                            if af is not None and spid:
                                w, h = _sprite_wh(af, spid)
                            if (w < 1.0 or h < 1.0) and af is not None and tpid:
                                w, h = _texture_wh(af, tpid)
                        except Exception:
                            pass
                    if w >= 1.0 and h >= 1.0:
                        sd = (w, h)
                        try:
                            el.size_delta = (w, h, 0.0)
                        except Exception:
                            pass
                    else:
                        # Skip writing zeros — keep whatever heal/inject set.
                        sd = None
                try:
                    pv = tuple(el.pivot)
                except Exception:
                    pv = None
                try:
                    amin = tuple(el.anchor_min)
                    amax = tuple(el.anchor_max)
                except Exception:
                    amin = amax = None
                omin = tuple(el.offset_min) if el.has_offset_min else None
                omax = tuple(el.offset_max) if el.has_offset_max else None
            apply_rect_transform(
                env, rid,
                anchored_position=ap,
                size_delta=sd,
                pivot=pv,
                anchor_min=amin,
                anchor_max=amax,
                offset_min=omin,
                offset_max=omax,
                local_rotation=rot if trs_dirty else None,
                local_scale=sc if trs_dirty else None,
                local_position_z=zpos if trs_dirty else None,
            )
            n_ui_write += 1
            # Stock ksp_local_* is the import Unity baseline used to restore
            # unedited languages. Never overwrite it with the live G/R/S.
            if vo is not None and trs_dirty:
                try:
                    if bool(vo.get("ksp_user_added")):
                        vo["ksp_local_rotation"] = tuple(float(x) for x in rot[:4])
                        vo["ksp_local_scale"] = tuple(float(x) for x in sc[:3])
                        vo["ksp_local_position_z"] = float(zpos)
                except Exception:
                    pass
        if hide_after_write:
            if _deactivate_el_in_env(env, el):
                n_ui_write += 1

    # Re-heal after UI writes: user_added layout sync can still push 0×0
    # sizeDelta / broken fathers; catch anything left invisible.
    try:
        from .prefab_clone import heal_null_image_sprites
        n_heal2 = heal_null_image_sprites(env)
        if n_heal2:
            did_pack_autofix = True
            print(
                "INFO: KSP export: post-UI healed %d Image/Rect issue(s)"
                % n_heal2
            )
    except Exception as ex:
        print("WARNING: KSP export: post-UI Image/Rect heal failed: %s" % ex)

    filepath = os.path.abspath(filepath)
    # UnityPy BundleFile.save always repacks (~1.47x on GEP) even with no
    # edits. When nothing actually changed, copy the source bytes instead.
    out_bytes = None
    if (
        n_tex_write == 0
        and n_text_write == 0
        and n_ui_write == 0
        and n_prefab_clone == 0
        and n_deleted_ui == 0
        and not did_pack_autofix
        and os.path.isfile(src)
    ):
        _p(88, text="Preparing unchanged bytes…", force=True)
        with open(src, "rb") as _bf:
            out_bytes = _bf.read()
        print(
            "INFO: KSP export: byte-identical payload (no asset changes); "
            "textures passthrough=%d"
            % n_tex_skip
        )
    else:
        _p(88, text="Repacking UnityFS in RAM…", force=True)
        comp = detect_bundle_compression(src)
        try:
            out_bytes = env.file.save(packer="original")
        except Exception as _pack_ex:
            print(
                "WARNING: KSP export: packer original failed (%s), using lz4"
                % _pack_ex
            )
            out_bytes = env.file.save(
                packer=comp if comp in ("lzma", "lz4") else "lz4"
            )
        if not isinstance(out_bytes, (bytes, bytearray)):
            out_bytes = bytes(out_bytes)
        print(
            "INFO: KSP export: UnityPy RAM pack wrote=%d tex, %d text, %d ui, "
            "%d prefab clones (source compression=%s)"
            % (
                n_tex_write, n_text_write, n_ui_write, n_prefab_clone,
                comp or "unknown",
            )
        )

    # Verify in RAM (unpacker) before touching the destination on disk.
    # Never CRITICAL-block the write: sync should have aligned XML←MB; remaining
    # whitespace / rich-text / locale cosmetic diffs are warnings only.
    _p(93, text="Verifying export snapshot…", force=True)
    try:
        from ..import_ksp import ksp_unpack as _kun
        _snap = _kun.unpack_bytes(bytes(out_bytes), source=filepath)
        _mis = _snap.get("xml_vs_mb_mismatches") or []
        if _mis:
            cosmetic = []
            content = []
            for row in _mis:
                try:
                    kind = _kun.classify_xml_mb_mismatch(row)
                except Exception:
                    kind = "content"
                if kind == "cosmetic":
                    cosmetic.append(row)
                else:
                    content.append(row)
            if content:
                detail = json.dumps(content[:5], ensure_ascii=False, indent=2)
                print(
                    "WARNING: KSP export: %d XML↔MB content mismatch(es) "
                    "remain after sync (writing destination anyway).\n%s"
                    % (len(content), detail)
                )
            if cosmetic:
                print(
                    "WARNING: KSP export: %d XML↔MB cosmetic mismatch(es) "
                    "(whitespace / rich-text / orphan XML) — ignored."
                    % len(cosmetic)
                )
            # Soft only — Destination MUST be written.
    except Exception as _ver_ex:
        print("WARNING: KSP export RAM verify skipped: %s" % _ver_ex)

    _p(96, text="Writing bundle to disk…", force=True)
    try:
        for obj in (
            getattr(env, "file", None),
            getattr(getattr(env, "file", None), "stream", None),
        ):
            if obj is None:
                continue
            close = getattr(obj, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    except Exception:
        pass
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    tmp = filepath + ".ksp_export_tmp"
    try:
        with open(tmp, "wb") as _wf:
            _wf.write(out_bytes)
        os.replace(tmp, filepath)
    finally:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass

    _p(100, text="Bundle written", force=True)
    if set_source_path:
        try:
            kb.source_path = filepath
        except Exception:
            pass
    # Refresh existing embed only (never create multi-MB Text during export —
    # that freezes the UI; user embeds via the Source-row icon).
    try:
        if out_bytes and source_embed.has_embedded_source(kb):
            source_embed.embed_source_bytes(
                kb,
                bytes(out_bytes),
                root=root,
                original_name=os.path.basename(filepath),
            )
    except Exception:
        pass
    _drop_embed_tmp()
    return filepath
