# vim:ts=4:et
# <pep8 compliant>
"""In-memory per-locale buffers for KSPedia editing.

Keeps .cfg/.ksp/.lang text maps AND live viewport layout (TRS, FONT spacing,
text boxes, image transforms) in RAM while the Blender session is open.

Live sync reads Blender ID state (already on the undo stack). After Ctrl+Z the
depsgraph fires again and the buffer is refreshed from the restored objects —
no separate undo history is needed for the RAM layer.
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

# Survives .ksp reimport: LOCAL Duplicate/Add of a shared image otherwise
# looks like stock (presence_has_element always True for images).
SHIPPED_GO_MARK = "__kS_"
_SHIPPED_TAIL_INDEX_RE = re.compile(r"_\d+$")

# kb.as_pointer() -> { locale: maps_dict }
_BUFFERS: Dict[int, Dict[str, dict]] = {}
# kb.as_pointer() -> last active locale (for switch capture)
_PREV_LOCALE: Dict[int, str] = {}

# Prevent depsgraph re-entry while writing ksp_ui / RAM
_LIVE_SYNC_LOCK = False


def is_live_sync_locked() -> bool:
    return bool(_LIVE_SYNC_LOCK)


def set_live_sync_lock(locked: bool) -> None:
    """Freeze depsgraph→RAM sync during locale apply / capture bursts."""
    global _LIVE_SYNC_LOCK
    _LIVE_SYNC_LOCK = bool(locked)


def release_live_sync_lock_deferred(delay: float = 0.25) -> None:
    """Unlock only once the depsgraph flushed the apply we just performed.

    Objects rebuilt by a locale switch arrive in ``depsgraph_update_post``
    after the job already finished. Unlocking synchronously made every one of
    them look like a user drag, so the whole page was stored as a viewport
    edit and later switches restored those stale positions.
    """
    global _LIVE_SYNC_LOCK
    try:
        import bpy

        def _unlock():
            global _LIVE_SYNC_LOCK
            _LIVE_SYNC_LOCK = False
            return None

        bpy.app.timers.register(_unlock, first_interval=max(float(delay), 0.0))
    except Exception:
        _LIVE_SYNC_LOCK = False


# Unity / KSP UI fields we persist per element
_EL_FIELDS = (
    "kind",
    "name",
    "element_name",
    "font_size",
    "color",
    "anchored_position",
    "size_delta",
    "pivot",
    "anchor_min",
    "anchor_max",
    "local_rotation",
    "local_scale",
    "local_position_z",
    "text_alignment",
    "font_style",
    "is_rich_text",
    "enable_word_wrapping",
    "line_spacing",
    "margin",
    "character_spacing",
    "word_spacing",
    "paragraph_spacing",
    "enable_auto_sizing",
    "font_size_min",
    "font_size_max",
    "overflow_mode",
    "font_family",
    "outline_width",
    "outline_color",
    "effect_distance",
    "has_ui_outline",
    "has_ui_shadow",
    # Exact Blender viewport overrides (survive rebuild / locale switch)
    "has_viewport_edit",
    "location",
    "rotation_euler",
    "scale",
    "curve_size",
    "curve_shear",
    "curve_space_character",
    "curve_space_word",
    "curve_space_line",
    "curve_align_x",
    "curve_align_y",
    "curve_offset_x",
    "curve_offset_y",
    "curve_underline_position",
    "curve_underline_height",
    "curve_small_caps_scale",
    "curve_overflow",
    "text_boxes",
    # Native Blender tweaks (material colour, font datablock, curve size,
    # dragged wrap width) measured against the builder output — see
    # capture_user_overrides().
    "user_overrides",
    "content_size",
    "mb_path_id",
    "rect_path_id",
    "go_path_id",
    "parent_rect_path_id",
    "sibling_index",
)


def _ptr(kb) -> int:
    try:
        return int(kb.as_pointer())
    except ReferenceError:
        return 0
    except Exception:
        try:
            return id(kb)
        except Exception:
            return 0


# Matches import_ksp.properties._TEXT_MAXLEN — RNA StringProperty hard cap.
_RNA_TEXT_MAX = 16384


def _rna_text(value) -> str:
    s = "" if value is None else str(value)
    if len(s) > _RNA_TEXT_MAX:
        return s[:_RNA_TEXT_MAX]
    return s


def clear_bundle(kb) -> None:
    p = _ptr(kb)
    _BUFFERS.pop(p, None)
    _PREV_LOCALE.pop(p, None)


def get_prev_locale(kb) -> str:
    return (_PREV_LOCALE.get(_ptr(kb)) or "").lower()


def set_prev_locale(kb, locale: str) -> None:
    _PREV_LOCALE[_ptr(kb)] = (locale or "").lower()


def infer_outgoing_locale(kb, root=None) -> str:
    """Language currently on screen. ``active_locale`` is already the incoming tag."""
    prev = get_prev_locale(kb)
    if prev:
        return prev
    try:
        loc = str(getattr(kb, "locale", "") or "").lower()
        if loc:
            return loc
    except Exception:
        pass
    if root is not None:
        try:
            objs = [root] + list(getattr(root, "children_recursive", []) or [])
        except Exception:
            objs = [root]
        for obj in objs:
            try:
                applied = str(obj.get("ksp_locale_applied") or "").lower()
                if applied:
                    return applied
            except Exception:
                continue
    return "en-us"


def park_outgoing_locale(kb, root, incoming: str) -> str:
    """Snapshot the language we are leaving before applying ``incoming``.

    After import ``get_prev_locale`` is empty. The RNA update has already
    written the new ``active_locale``, so a naive ``if prev: capture`` skipped
    the first EN→DE park — de→en then rebuilt English from stock maps and
    dropped multimaterial / rotation / scale / the blue-text box.
    """
    incoming = (incoming or "").lower()
    prev = infer_outgoing_locale(kb, root)
    if prev and prev != incoming:
        try:
            from .properties import capture_toc_titles
            capture_toc_titles(kb, prev)
        except Exception:
            pass
        capture_current(kb, root, prev)
    return prev


def _is_locale_orphan(obj) -> bool:
    try:
        return bool(obj.get("ksp_locale_orphan"))
    except Exception:
        return False


def forgotten_locales_of(obj) -> list:
    try:
        if "ksp_forgotten_locales" not in obj.keys():
            return []
        raw = str(obj.get("ksp_forgotten_locales") or "")
    except Exception:
        return []
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def mark_forgotten_locale(obj, locale: str) -> None:
    loc = (locale or "").strip().lower()
    if obj is None or not loc:
        return
    cur = forgotten_locales_of(obj)
    if loc not in cur:
        cur.append(loc)
    try:
        obj["ksp_forgotten_locales"] = ",".join(cur)
    except Exception:
        pass


def is_forgotten_in_locale(obj, locale: str) -> bool:
    loc = (locale or "").strip().lower()
    if not loc or obj is None:
        return False
    return loc in forgotten_locales_of(obj)


def split_shipped_go_name(name: str) -> Tuple[str, Optional[List[str]]]:
    """``(base, locales)`` from a Unity GO name. ``locales`` is None when unmarked."""
    raw = str(name or "").strip()
    mark = SHIPPED_GO_MARK
    idx = raw.find(mark)
    if idx < 0:
        return raw, None
    base = raw[:idx]
    rest = raw[idx + len(mark) :]
    rest = _SHIPPED_TAIL_INDEX_RE.sub("", rest)
    locs = [
        x.strip().lower()
        for x in rest.replace(",", "+").split("+")
        if x.strip()
    ]
    if not locs:
        return base or raw, None
    return base, locs


def join_shipped_go_name(base: str, locales) -> str:
    stem = str(base or "").strip()
    locs = sorted({
        (x or "").strip().lower()
        for x in (locales or [])
        if (x or "").strip()
    })
    if not stem or not locs:
        return stem
    return "%s%s%s" % (stem, SHIPPED_GO_MARK, "+".join(locs))


def encode_shipped_go_name(name: str, locales, all_locales=None) -> str:
    """Mark a LOCAL/PICK GO so reimport can restore ``ksp_shipped_locales``.

    ALL-scope (every detected language) stays unmarked — extra images in the
    base .ksp should remain visible everywhere.
    """
    base, _prev = split_shipped_go_name(name)
    locs = sorted({
        (x or "").strip().lower()
        for x in (locales or [])
        if (x or "").strip()
    })
    if not base:
        return str(name or "").strip()
    if not locs:
        return base
    all_set = {
        (x or "").strip().lower()
        for x in (all_locales or [])
        if (x or "").strip()
    }
    if all_set and set(locs) >= all_set:
        return base
    if not all_set and len(locs) != 1:
        return base
    return join_shipped_go_name(base, locs)


def shipped_go_display_name(name: str) -> str:
    base, _locs = split_shipped_go_name(name)
    return base or str(name or "").strip()


def stamp_shipped_locale_from_name(obj) -> bool:
    """Restore user_added + shipped locales from an encoded Unity GO name."""
    if obj is None:
        return False
    candidates = []
    try:
        gn = str(obj.get("ksp_export_go_name") or "").strip()
        if gn:
            candidates.append(gn)
    except Exception:
        pass
    try:
        ui = obj.ksp_ui
        en = str(getattr(ui, "element_name", "") or "").strip()
        if en:
            candidates.append(en)
    except Exception:
        pass
    try:
        n = str(getattr(obj, "name", "") or "").strip()
        if n:
            candidates.append(n)
    except Exception:
        pass
    locs = None
    base = ""
    encoded = ""
    for cand in candidates:
        b, got = split_shipped_go_name(cand)
        if got:
            base, locs, encoded = b, got, cand
            break
    if not locs:
        return False
    try:
        obj["ksp_user_added"] = True
        obj["ksp_shipped_locales"] = ",".join(locs)
        obj["ksp_export_go_name"] = encoded or join_shipped_go_name(base, locs)
    except Exception:
        return False
    return True


def _plain_value(v):
    """Detach RNA arrays / mathutils vectors into plain Python data.

    A ``bpy_prop_array`` only holds a pointer to its owner ID. Parking one in
    the RAM buffers meant that reading it later — on export, after a locale
    switch had rebuilt (and freed) those text objects — dereferenced freed
    memory and took Blender down inside the array iterator, where no Python
    ``except`` can catch it.

    Sequence-like ID properties (``body_format`` index arrays) must NOT go
    through ``.items()`` — some Blender builds expose that and turn a list of
    material indices into ``{"0": 1, "1": 0, ...}``, which then blows up
    ``SimpleNamespace(**el)`` and greys the whole language as Missing.
    """
    if v is None or isinstance(v, (bool, int, float, str, bytes)):
        return v
    if isinstance(v, dict):
        try:
            return {str(k): _plain_value(x) for k, x in v.items()}
        except Exception:
            return {}
    if isinstance(v, (list, tuple)):
        return tuple(_plain_value(x) for x in v)
    # Mapping (IDPropertyGroup) before sequence: groups have keys/items.
    if callable(getattr(v, "keys", None)) and callable(getattr(v, "items", None)):
        try:
            return {str(k): _plain_value(x) for k, x in v.items()}
        except Exception:
            pass
    # bpy_prop_array / IDPropertyArray
    try:
        return tuple(_plain_value(x) for x in v)
    except TypeError:
        return v
    except Exception:
        return None


def _tup(v, n=None, default=None):
    if v is None:
        return default
    try:
        t = tuple(float(x) for x in v)
        if n is not None:
            if len(t) < n:
                fill = default or ((0.0,) * n)
                t = t + tuple(fill[len(t):n])
            return t[:n]
        return t
    except Exception:
        return default


def _copy_el_dict(el: Any) -> dict:
    """Serialize Unity element / SimpleNamespace / dict to a plain dict."""
    if el is None:
        return {}
    if isinstance(el, dict):
        src = el
    else:
        src = {}
        for k in _EL_FIELDS:
            if hasattr(el, k):
                try:
                    src[k] = getattr(el, k)
                except Exception:
                    pass
        # Common aliases from KspUiElement / ksp_ui
        for k in (
            "name",
            "text",
            "font_size",
            "color",
            "anchored_position",
            "size_delta",
            "pivot",
            "local_rotation",
            "local_scale",
            "local_position_z",
            "text_alignment",
            "font_style",
            "enable_word_wrapping",
            "line_spacing",
            "margin",
            "character_spacing",
            "word_spacing",
            "paragraph_spacing",
            "font_family",
            "overflow_mode",
            "kind",
            "mb_path_id",
            "rect_path_id",
            "go_path_id",
            "parent_rect_path_id",
            "sibling_index",
        ):
            if k not in src and hasattr(el, k):
                try:
                    src[k] = getattr(el, k)
                except Exception:
                    pass
    out: Dict[str, Any] = {}
    for k, v in src.items():
        if k == "user_overrides":
            ov = _plain_value(v)
            out[k] = ov if isinstance(ov, dict) else {}
        elif k == "text_boxes" and v is not None:
            boxes = []
            for b in v:
                try:
                    if isinstance(b, dict):
                        boxes.append(
                            {
                                "width": float(b.get("width", 0.0)),
                                "height": float(b.get("height", 0.0)),
                                "x": float(b.get("x", 0.0)),
                                "y": float(b.get("y", 0.0)),
                            }
                        )
                    else:
                        boxes.append(
                            {
                                "width": float(b[0]),
                                "height": float(b[1]),
                                "x": float(b[2]),
                                "y": float(b[3]),
                            }
                        )
                except Exception:
                    continue
            out[k] = boxes
        elif isinstance(v, (list, tuple)):
            try:
                out[k] = tuple(float(x) for x in v)
            except Exception:
                out[k] = _plain_value(v)
        else:
            out[k] = _plain_value(v)
    return out


def el_as_namespace(el: Any) -> Any:
    """loc_el usable with getattr() in locale_switch._snapshot_text_props."""
    if el is None:
        return None
    if isinstance(el, SimpleNamespace):
        return el
    d = _copy_el_dict(el)
    if not d:
        return el
    clean = {
        k: v for k, v in d.items()
        if isinstance(k, str) and k.isidentifier()
    }
    if not clean:
        return el
    try:
        return SimpleNamespace(**clean)
    except TypeError:
        return el


_PRESENCE_KEYS = (
    "present_hier",
    "present_names",
    "present_names_all",
    "present_kinds",
    "present_mb",
)


def store_maps(kb, locale: str, maps: dict) -> None:
    loc = (locale or "").lower()
    if not loc or not maps:
        return
    p = _ptr(kb)
    if not p:
        return
    bucket = _BUFFERS.setdefault(p, {})
    el_h = {}
    for k, v in (maps.get("el_by_hier") or {}).items():
        try:
            el_h[str(k)] = _copy_el_dict(v)
        except Exception:
            continue
    el_n = {}
    for k, v in (maps.get("el_by_name") or {}).items():
        try:
            el_n[str(k)] = _copy_el_dict(v)
        except Exception:
            continue
    prev = bucket.get(loc) or {}
    entry = {
        "text_by_hier": dict(maps.get("text_by_hier") or {}),
        "text_by_name": dict(maps.get("text_by_name") or {}),
        "el_by_hier": el_h,
        "el_by_name": el_n,
    }
    # Presence describes what the .lang itself contains, so a viewport capture
    # (which also sees the hidden leftovers of other locales) must never
    # widen it — only a fresh bundle read or an explicit edit may.
    # Empty lists from get_maps() must NOT wipe real presence — that greys
    # every row after a multimaterial live-sync / get→store round-trip.
    for key in _PRESENCE_KEYS:
        incoming = maps.get(key)
        if incoming is not None:
            incoming_list = list(incoming)
            if incoming_list:
                entry[key] = sorted(str(x) for x in incoming_list)
            elif key in prev and prev.get(key):
                entry[key] = list(prev.get(key) or ())
            else:
                entry[key] = []
        elif key in prev:
            entry[key] = list(prev.get(key) or ())
    bucket[loc] = entry


def get_maps(kb, locale: str) -> Optional[dict]:
    loc = (locale or "").lower()
    if not loc:
        return None
    raw = (_BUFFERS.get(_ptr(kb)) or {}).get(loc)
    if raw is None:
        return None
    # Return namespaces for el maps so rebuild can getattr()
    el_h = {}
    for k, v in (raw.get("el_by_hier") or {}).items():
        try:
            el_h[k] = el_as_namespace(v)
        except Exception:
            continue
    el_n = {}
    for k, v in (raw.get("el_by_name") or {}).items():
        try:
            el_n[k] = el_as_namespace(v)
        except Exception:
            continue
    out = {
        "text_by_hier": dict(raw.get("text_by_hier") or {}),
        "text_by_name": dict(raw.get("text_by_name") or {}),
        "el_by_hier": el_h,
        "el_by_name": el_n,
    }
    for key in _PRESENCE_KEYS:
        out[key] = list(raw.get(key) or ())
    return out


def has_locale_maps(kb, locale: str) -> bool:
    """True when this language already has a RAM buffer (even an empty shell)."""
    loc = (locale or "").lower()
    if not loc:
        return False
    return (_BUFFERS.get(_ptr(kb)) or {}).get(loc) is not None


def drop_maps(kb, locale: str) -> None:
    """Forget one language's RAM buffer (UI remove; disk untouched until Export)."""
    loc = (locale or "").lower()
    if not loc:
        return
    bucket = _BUFFERS.get(_ptr(kb))
    if not bucket:
        return
    bucket.pop(loc, None)


def has_maps(kb, locale: str) -> bool:
    return get_maps(kb, locale) is not None


def presence_from_maps(maps: Optional[dict]) -> Optional[dict]:
    """Sets of hierarchy keys / names / kinds a locale actually ships.

    ``None`` means the locale was never read from a bundle, so nothing is
    known and every element counts as present.
    """
    if not maps:
        return None
    hier = set(maps.get("present_hier") or ())
    names = set(maps.get("present_names") or ())
    names_all = set(maps.get("present_names_all") or ()) or set(names)
    # Soft: any name that still has text/layout in RAM is present. Incomplete
    # present_names_all alone used to gray whole PBS pages.
    names_all |= set((maps.get("text_by_name") or {}).keys())
    names_all |= set((maps.get("el_by_name") or {}).keys())
    mb = set(str(x) for x in (maps.get("present_mb") or ()) if x)
    if not hier and not names and not names_all and not mb:
        return None
    return {
        "hier": hier,
        "names": names,
        "names_all": names_all,
        "mb": mb,
        "kinds": set(maps.get("present_kinds") or ()),
    }


def presence_has_element(
    presence: Optional[dict],
    hier: str,
    name: str,
    kind: str,
    mb_path_id: str = "",
) -> bool:
    """True when the locale ships this element (or says nothing about it)."""
    if not presence:
        return True
    kinds = presence.get("kinds") or set()
    if kind and kinds and kind not in kinds:
        # This .lang carries no element of that kind at all (text-only
        # translations are common) - it is not a statement about this element.
        return True
    if (kind or "") == "image":
        # Viewport images keep English GO names from the base .ksp; ru/zh
        # .lang files often list localized names, which is not "dropped".
        return True
    # Path ids differ per .lang AssetBundle — only useful within one file.
    mb = str(mb_path_id or "").strip()
    if mb and mb != "0" and mb in (presence.get("mb") or ()):
        return True
    if hier and hier in presence["hier"]:
        return True
    try:
        from .locale_switch import hier_dup_match_key
        want = hier_dup_match_key(hier or "")
        if want:
            for h in presence["hier"]:
                if hier_dup_match_key(h) == want:
                    return True
    except Exception:
        pass
    if name and name in presence["names"]:
        return True
    # Hierarchy keys break after localized GO renames on page folders.
    # Any occurrence of the element name in the .lang keeps the box visible
    # (duplicate Headers stay up rather than graying the whole page).
    if name and name in (presence.get("names_all") or ()):
        return True
    # Blender / list suffixes (.001, #1) must not mark a duplicate sibling
    # missing when the Unity GO name is still in the locale.
    if name:
        base = name
        try:
            from .locale_switch import _element_base_name
            base = _element_base_name(name) or name
        except Exception:
            base = name
        if "#" in base:
            base = base.split("#", 1)[0]
        if base and base != name and base in (presence.get("names_all") or ()):
            return True
    return not (hier or name or (mb and mb != "0"))


def set_element_presence(kb, locale: str, *, hier: str = "", name: str = "",
                         kind: str = "", present: bool = True) -> bool:
    """Add / drop one element in a locale's presence set. True if it changed."""
    loc = (locale or "").lower()
    entry = (_BUFFERS.get(_ptr(kb)) or {}).get(loc)
    if entry is None:
        return False
    changed = False
    for key, val in (("present_hier", hier), ("present_names", name),
                     ("present_kinds", kind)):
        if not val:
            continue
        cur = set(entry.get(key) or ())
        if present:
            if val in cur:
                continue
            cur.add(val)
        else:
            if key == "present_kinds":
                # A kind stays declared even when its last element goes away,
                # otherwise the locale would look like it never had any.
                continue
            if val not in cur:
                continue
            cur.discard(val)
        entry[key] = sorted(cur)
        changed = True
    return changed


def locale_ships_element(kb, locale: str, *, hier: str = "", name: str = "",
                         kind: str = "") -> bool:
    """Does this locale carry the element? Unknown locales answer yes."""
    raw = (_BUFFERS.get(_ptr(kb)) or {}).get((locale or "").lower())
    return presence_has_element(presence_from_maps(raw), hier, name, kind)


def forget_element(kb, locale: str, *, hier: str = "", name: str = "") -> bool:
    """Drop an element from one locale — that .lang no longer carries it."""
    loc = (locale or "").lower()
    entry = (_BUFFERS.get(_ptr(kb)) or {}).get(loc)
    if entry is None:
        return False
    changed = set_element_presence(kb, loc, hier=hier, name=name, present=False)
    for key, val in (("text_by_hier", hier), ("el_by_hier", hier),
                     ("text_by_name", name), ("el_by_name", name)):
        if not val:
            continue
        block = entry.get(key)
        if isinstance(block, dict) and val in block:
            del block[val]
            changed = True
    # Drop the name from present_names_all only when no other map still
    # carries it (duplicate Headers on other pages stay listed).
    if name:
        still = False
        for key in ("el_by_name", "text_by_name"):
            if name in (entry.get(key) or {}):
                still = True
                break
        if not still:
            for key in ("el_by_hier", "text_by_hier"):
                for k in (entry.get(key) or {}):
                    last = str(k).rsplit("/", 1)[-1]
                    base = last.split("#", 1)[0]
                    if last == name or base == name:
                        still = True
                        break
                if still:
                    break
        if not still:
            extra = set(entry.get("present_names_all") or ())
            if name in extra:
                extra.discard(name)
                entry["present_names_all"] = sorted(extra)
                changed = True
    return changed


def remember_element(kb, locale: str, *, hier: str = "", name: str = "",
                     kind: str = "text", state: Optional[dict] = None,
                     text: Optional[str] = None) -> bool:
    """Add an element to one locale's map + presence set."""
    loc = (locale or "").lower()
    entry = (_BUFFERS.get(_ptr(kb)) or {}).get(loc)
    if entry is None:
        return False
    changed = set_element_presence(
        kb, loc, hier=hier, name=name, kind=kind, present=True
    )
    payload = _copy_el_dict(state) if state else {}
    if text is not None:
        payload["text"] = text
    for key, val in (("el_by_hier", hier), ("el_by_name", name)):
        if val and payload:
            entry.setdefault(key, {})[val] = dict(payload)
            changed = True
    if kind == "text" and text is not None:
        for key, val in (("text_by_hier", hier), ("text_by_name", name)):
            if val:
                entry.setdefault(key, {})[val] = text
                changed = True
    return changed


def _linear_to_srgb_channel(c) -> float:
    x = max(0.0, min(1.0, float(c)))
    if x <= 0.0031308:
        return x * 12.92
    return 1.055 * (x ** (1.0 / 2.4)) - 0.055


def _material_color_srgb(obj):
    """sRGB RGBA of the emission material Blender actually renders.

    Recolouring text in the shader / material tab never touches ``ksp_ui``,
    so without reading it back a hand-picked colour died on the next rebuild.
    """
    try:
        mats = list(getattr(getattr(obj, "data", None), "materials", None) or ())
    except Exception:
        return None
    for mat in mats:
        if mat is None or not getattr(mat, "use_nodes", False):
            continue
        try:
            nodes = list(mat.node_tree.nodes)
        except Exception:
            continue
        rgb = None
        alpha = 1.0
        for nd in nodes:
            kind = str(getattr(nd, "type", "") or "")
            if kind == "EMISSION" and rgb is None:
                try:
                    v = nd.inputs["Color"].default_value
                    rgb = (float(v[0]), float(v[1]), float(v[2]))
                except Exception:
                    rgb = None
            elif kind == "MIX_SHADER":
                try:
                    alpha = float(nd.inputs["Fac"].default_value)
                except Exception:
                    pass
        if rgb is not None:
            return (
                _linear_to_srgb_channel(rgb[0]),
                _linear_to_srgb_channel(rgb[1]),
                _linear_to_srgb_channel(rgb[2]),
                max(0.0, min(1.0, alpha)),
            )
    return None


def _font_datablock_name(obj) -> str:
    try:
        return str(obj.data.font.name or "")
    except Exception:
        return ""


def build_state_of(obj) -> dict:
    """What the builder left on this object — the yardstick for user tweaks."""
    st: Dict[str, Any] = {}
    if obj is None:
        return st
    try:
        st["curve_size"] = float(obj.data.size)
    except Exception:
        pass
    try:
        tb = obj.data.text_boxes[0]
        st["box_width"] = float(tb.width)
        st["box_height"] = float(tb.height)
        st["box_x"] = float(tb.x)
        st["box_y"] = float(tb.y)
    except Exception:
        pass
    try:
        st["font"] = _font_datablock_name(obj)
    except Exception:
        pass
    col = _material_color_srgb(obj)
    if col is not None:
        st["color"] = col
    # Never stamp live Blender R/S. A later pin (Refresh / text commit /
    # pin_all_layout_xy) on a user-scaled object would make the yardstick
    # match the tweak, so capture_user_overrides would drop rotation/scale.
    try:
        from .viewport import snapshot_font_materials
        snap = snapshot_font_materials(obj)
        names = []
        for info in snap.get("materials") or []:
            names.append(str(info.get("name") or ""))
        st["material_names"] = names
        st["material_indices"] = list(snap.get("indices") or [])
    except Exception:
        pass
    try:
        ui = obj.ksp_ui
        st["font_size"] = float(ui.font_size or 0.0)
        st["size_delta"] = tuple(float(x) for x in (ui.size_delta or (0.0, 0.0))[:2])
    except Exception:
        pass
    return st


_BOX_PX_EPS = 0.75
# FONT text-box vs Unity sizeDelta at import (ConfS2 is ~18 px). Real Size X
# edits are hundreds of px; this slack must not export that calibration.
_LAYOUT_SLACK_PX = 32.0


def live_font_box_size_delta(obj, *, pixel_scale: float = 0.001, base_sd=None):
    """Unity sizeDelta from the FONT Text Boxes panel when the user resized it.

    Import lays out with ``height=0`` (Blender quirk). A changed Size X or a
    Size Y > 0 vs the post-build stamp is a real resize and must export as
    RectTransform ``m_SizeDelta``. Returns ``(w_px, h_px)`` or ``None``.
    """
    if obj is None:
        return None
    font = obj
    try:
        kind = getattr(obj, "type", "FONT")
        if kind not in ("FONT", "", None):
            font = None
            try:
                for ch in list(getattr(obj, "children", None) or []):
                    if getattr(ch, "type", "") == "FONT" and getattr(ch, "data", None) is not None:
                        font = ch
                        break
            except Exception:
                font = None
            if font is None:
                return None
    except Exception:
        font = obj
    try:
        tb = font.data.text_boxes[0]
    except Exception:
        return None
    try:
        from .viewport import is_artwork_overlay
        src = ""
        try:
            src = str(obj.ksp_ui.text or "")
        except Exception:
            src = ""
        if is_artwork_overlay(src, obj):
            return None
    except Exception:
        pass
    sx = float(pixel_scale) or 0.001
    live_w_bu = abs(float(tb.width))
    live_h_bu = abs(float(tb.height))
    live_w = live_w_bu / sx
    live_h = live_h_bu / sx
    base = _stamped_build_state(obj) or {}
    stamp_w = base.get("box_width")
    stamp_h = base.get("box_height")
    stamp_has_size_delta = base.get("size_delta") is not None
    # Unity hole stamped at import — pin_build_state restamp must not hide
    # Size X 1500 vs 818.5 (USER-OLD-002). Tests grep this call.
    import_cs = import_content_size_of(obj)
    try:
        ui_sd = tuple(
            float(x) for x in (obj.ksp_ui.size_delta or (0.0, 0.0))[:2]
        )
    except Exception:
        ui_sd = (0.0, 0.0)
    if base_sd is None:
        base_sd = ui_sd
    try:
        orig_w = abs(float(base_sd[0] or 0.0))
        orig_h = abs(float(base_sd[1] or 0.0))
    except Exception:
        orig_w, orig_h = abs(float(ui_sd[0])), abs(float(ui_sd[1]))
    try:
        ics_w = abs(float(import_cs[0])) if import_cs is not None else 0.0
        ics_h = abs(float(import_cs[1])) if import_cs is not None else 0.0
    except Exception:
        ics_w, ics_h = 0.0, 0.0
    if ics_w > 1.0:
        orig_w = ics_w if orig_w < 1.0 else orig_w
    if ics_h > 1.0:
        orig_h = ics_h if orig_h < 1.0 else orig_h

    user_added = False
    try:
        user_added = bool(obj.get("ksp_user_added"))
    except Exception:
        user_added = False

    def _wider_than_unity(live_px, unity_px):
        """True for a real Size X grow, not import FONT-box calibration."""
        try:
            lp = abs(float(live_px))
            up = abs(float(unity_px))
        except Exception:
            return False
        if up < 1.0:
            return lp > _BOX_PX_EPS
        # Narrower height=0 boxes are the Blender layout quirk (ConfB overlays).
        if lp + _BOX_PX_EPS < up and live_h <= _BOX_PX_EPS:
            return False
        return (lp - up) > _LAYOUT_SLACK_PX

    # Post-import FONT box (grow_single / wrap bonus). Size X is a move off
    # this yardstick — not "live wider than Unity sizeDelta" (that fired on
    # every TrackEditor one-liner and exported 2×–6× widths).
    import_box = import_font_box_of(obj)
    try:
        imp_w = abs(float(import_box[0])) / sx if import_box is not None else None
        imp_h = abs(float(import_box[1])) / sx if import_box is not None else None
    except Exception:
        imp_w, imp_h = None, None

    w_changed = False
    h_changed = False
    if stamp_w is not None:
        moved_vs_stamp = abs(live_w_bu - float(stamp_w)) / sx > _BOX_PX_EPS
        if stamp_has_size_delta:
            if moved_vs_stamp:
                w_changed = True
            elif imp_w is not None and abs(live_w - float(imp_w)) > _LAYOUT_SLACK_PX:
                # Locale/export restamped ksp_build_state to the live box;
                # frozen import box still holds the post-build width.
                w_changed = True
            elif _wider_than_unity(live_w, ics_w or orig_w):
                # Legacy: stamp carried size_delta and no import_font_box.
                if imp_w is None:
                    w_changed = True
        else:
            # Normal pin: compare to stamp / frozen import box — NEVER to
            # raw Unity sizeDelta (grow_single is often >> Unity + 32 px).
            if moved_vs_stamp:
                w_changed = True
            elif imp_w is not None and abs(live_w - float(imp_w)) > _LAYOUT_SLACK_PX:
                w_changed = True
    elif user_added and abs(live_w - orig_w) > _BOX_PX_EPS:
        w_changed = True
    else:
        if imp_w is not None:
            if abs(live_w - float(imp_w)) > _LAYOUT_SLACK_PX:
                w_changed = True
        elif abs(live_w - orig_w) > _LAYOUT_SLACK_PX:
            try:
                body_txt = str(getattr(getattr(obj, "data", None), "body", None) or "")
            except Exception:
                body_txt = ""
            try:
                ui_txt = str(getattr(getattr(obj, "ksp_ui", None), "text", None) or "")
            except Exception:
                ui_txt = ""
            if body_txt.strip() and ui_txt.strip() and body_txt.strip() == ui_txt.strip():
                w_changed = True
            elif _wider_than_unity(live_w, ics_w or orig_w):
                w_changed = True
    if stamp_h is not None:
        moved_h = abs(live_h_bu - float(stamp_h)) / sx > _BOX_PX_EPS
        if stamp_has_size_delta:
            if moved_h:
                h_changed = True
            elif (
                imp_h is not None
                and live_h > _BOX_PX_EPS
                and abs(live_h - float(imp_h)) > _LAYOUT_SLACK_PX
            ):
                h_changed = True
        else:
            # When stamp has no size_delta, never treat height=0 as a live
            # resize (layout quirk); only mark when live_h is non-zero.
            if moved_h and live_h > _BOX_PX_EPS:
                h_changed = True
            elif (
                imp_h is not None
                and live_h > _BOX_PX_EPS
                and abs(live_h - float(imp_h)) > _LAYOUT_SLACK_PX
            ):
                h_changed = True
    elif live_h > _BOX_PX_EPS and abs(live_h - orig_h) > _BOX_PX_EPS:
        if imp_h is not None:
            if abs(live_h - float(imp_h)) > _LAYOUT_SLACK_PX:
                h_changed = True
        else:
            h_changed = True

    extra_content = False
    nlines = 1
    try:
        body = str(getattr(obj.data, "body", None) or "")
        ui_txt = ""
        try:
            ui_txt = str(obj.ksp_ui.text or "")
        except Exception:
            ui_txt = ""
        body_c = " ".join(body.replace("\u2007", " ").split())
        ui_c = " ".join(ui_txt.replace("\u2007", " ").split())
        if body_c and ui_c and body_c.startswith(ui_c) and len(body_c) > len(ui_c) + 1:
            extra_content = True
        nlines = max(1, body.count("\n") + 1)
    except Exception:
        extra_content = False

    if not w_changed and not h_changed and not extra_content:
        return None

    # Stock: never shrink Unity sizeDelta because the FONT box auto-fit after
    # a glyph edit. That clipped the paragraph on reimport and every language
    # inherited the English box (active-locale-only rule).
    if not user_added:
        if w_changed and (live_w + _BOX_PX_EPS) < orig_w:
            w_changed = False
        stamp_h_px = 0.0
        try:
            if stamp_h is not None:
                stamp_h_px = abs(float(stamp_h)) / sx
        except Exception:
            stamp_h_px = 0.0
        # Import stamps height=0 (Blender quirk). A live Size Y > 0 is a
        # real N-panel edit. Only ignore height when the stamp already had
        # a box and glyph auto-fit made it shorter than Unity.
        if (
            h_changed
            and live_h > _BOX_PX_EPS
            and stamp_h_px > _BOX_PX_EPS
            and (live_h + _BOX_PX_EPS) < orig_h
        ):
            h_changed = False
        if not w_changed and not h_changed and not extra_content:
            return None

    w_px = live_w if w_changed else orig_w
    h_px = orig_h
    if h_changed and live_h > _BOX_PX_EPS:
        h_px = live_h
    if extra_content or (w_changed and nlines > 1):
        fs = 14.0
        try:
            fs = float(obj.ksp_ui.font_size or 14.0)
        except Exception:
            fs = 14.0
        h_px = max(h_px, orig_h, float(fs) * float(max(nlines, 1)) * 1.2)
    if w_px < 1.0 and h_px < 1.0:
        return None
    return (float(w_px), float(h_px))


def persist_live_font_box_size(obj, *, pixel_scale: float = 0.001) -> bool:
    """Write a native Text Boxes resize into ``ksp_ui`` / overrides before pin.

    ``pin_build_state`` restamps the live boxes. Without this, a later text
    commit would treat the new Size X/Y as the builder baseline and drop it.
    """
    live = live_font_box_size_delta(obj, pixel_scale=pixel_scale)
    if live is None:
        return False
    ov = applied_overrides(obj)
    ov["size_delta"] = (float(live[0]), float(live[1]))
    ov["box_width_px"] = abs(float(live[0]))
    remember_applied_overrides(obj, ov)
    try:
        obj.ksp_ui.size_delta = (float(live[0]), float(live[1]))
    except Exception:
        pass
    return True


def font_curve_obj(obj):
    """Return FONT curve-like data (unit-test friendly; no `obj.type` needed)."""
    try:
        if obj is None:
            return None
        d = getattr(obj, "data", None)
        if d is None:
            return None
        # In tests, `obj.type` is often absent; rely on data shape.
        if hasattr(d, "text_boxes") or hasattr(d, "body") or hasattr(d, "size"):
            return d
        return None
    except Exception:
        return None


def pin_build_state(obj) -> None:
    """Stamp the post-build yardstick on the object (locale switch resets it)."""
    if obj is None:
        return
    try:
        obj["ksp_build_state"] = _idprop_safe_dict(build_state_of(obj))
    except Exception:
        pass
    # Freeze Unity sizeDelta from the first pin. Later persist/restamp of
    # ksp_ui.size_delta to 1500 must not become the import yardstick.
    try:
        if import_content_size_of(obj) is None:
            ui = obj.ksp_ui
            sd = tuple(float(x) for x in (ui.size_delta or (0.0, 0.0))[:2])
            if abs(sd[0]) >= 1.0 or abs(sd[1]) >= 1.0:
                stamp_import_content_size(obj, sd[0], sd[1])
    except Exception:
        pass
    # Freeze the post-import FONT box (includes grow_single / wrap bonus).
    # Later pin after Size X must not move this — live_font_box_size_delta
    # uses it so import calibration is not exported as a user widen.
    try:
        if import_font_box_of(obj) is None:
            tb = obj.data.text_boxes[0]
            stamp_import_font_box(obj, float(tb.width), float(tb.height))
    except Exception:
        pass


def stamp_import_font_box(obj, width_bu: float, height_bu: float) -> None:
    if obj is None:
        return
    try:
        obj["ksp_import_font_box"] = (float(width_bu), float(height_bu))
    except Exception:
        pass


def import_font_box_of(obj):
    """Blender text_boxes size stamped on first pin (BU), or None."""
    if obj is None:
        return None
    try:
        raw = obj.get("ksp_import_font_box", None)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        if len(raw) >= 2:
            return (float(raw[0]), float(raw[1]))
    except Exception:
        return None
    return None


def _stamped_build_state(obj):
    try:
        raw = obj.get("ksp_build_state", None)
    except Exception:
        return None
    if raw is None:
        return None
    val = _plain_value(raw)
    return val if isinstance(val, dict) else None


def applied_overrides(obj) -> dict:
    """Overrides the last rebuild of this object already honoured."""
    try:
        raw = obj.get("ksp_user_overrides", None)
    except Exception:
        return {}
    val = _plain_value(raw)
    return dict(val) if isinstance(val, dict) else {}


def remember_applied_overrides(obj, overrides) -> None:
    if obj is None:
        return
    try:
        obj["ksp_user_overrides"] = _idprop_safe_dict(overrides or {})
    except Exception:
        pass


def _idprop_safe_dict(d) -> dict:
    """JSON-roundtrip so Blender ID properties never store RNA / datablocks."""
    if not isinstance(d, dict):
        return {}
    try:
        import json
        return json.loads(json.dumps(_plain_value(d), default=lambda _o: None))
    except Exception:
        out = {}
        for k, v in d.items():
            if isinstance(v, (bool, int, float, str)):
                out[str(k)] = v
        return out


def _unity_trs_baseline(obj):
    """Blender R/S that ``apply_ui_local_trs`` would set from Unity local TRS.

    Reads ``ksp_local_scale`` / ``ksp_local_rotation`` stamped at import or
    locale apply. Missing keys (old objects) fall back to identity — never
    to the poisoned ``ksp_build_state`` pin.
    """
    rot = (0.0, 0.0, 0.0)
    sc = (1.0, 1.0, 1.0)
    q = None
    try:
        q = obj.get("ksp_local_rotation", None)
    except Exception:
        q = None
    if q is not None:
        try:
            from .layout import quat_identity, unity_ui_quat_to_blender_euler
            if not quat_identity(q):
                rot = tuple(
                    float(x) for x in unity_ui_quat_to_blender_euler(q)[:3]
                )
        except Exception:
            pass
    try:
        raw = obj.get("ksp_local_scale", None)
        if raw is not None and len(raw) >= 3:
            sc = tuple(float(x) for x in raw[:3])
            if abs(sc[0]) < 1e-12 and abs(sc[1]) < 1e-12:
                sc = (1.0, 1.0, 1.0)
    except Exception:
        pass
    return rot, sc


def capture_user_overrides(obj, *, pixel_scale: float = 0.001):
    """Hand tweaks Blender-side that ``ksp_ui`` cannot see, vs the build state.

    Every value is absolute, never a factor against the current build: a
    multiplier would be folded into the props of the next rebuild and then
    measured again, so a box nudged 20%% wider grew on every language switch.

    Rotation / scale are measured against Unity ``ksp_local_*`` on the object,
    not the builder stamp. Re-pinning a live transformed object must not
    hide those tweaks from RAM.
    """
    base = _stamped_build_state(obj) or {}
    now = build_state_of(obj)
    ov: Dict[str, Any] = applied_overrides(obj)

    b_size = float(base.get("curve_size") or 0.0)
    n_size = float(now.get("curve_size") or 0.0)
    if b_size > 1e-9 and n_size > 1e-9 and abs(n_size / b_size - 1.0) > 1e-4:
        built_fs = float(now.get("font_size") or base.get("font_size") or 0.0)
        if built_fs > 1e-6:
            ov["font_size"] = built_fs * (n_size / b_size)

    sx = float(pixel_scale) or 0.001
    user_added = False
    try:
        user_added = bool(obj.get("ksp_user_added"))
    except Exception:
        user_added = False
    b_box = base.get("box_width")
    n_box = now.get("box_width")
    b_sd = base.get("size_delta") or (0.0, 0.0)
    n_sd = now.get("size_delta") or (0.0, 0.0)
    live_sd = None
    try:
        base_for_live = None
        try:
            if abs(float(b_sd[0])) >= 1.0 or abs(float(b_sd[1])) >= 1.0:
                base_for_live = b_sd
        except Exception:
            base_for_live = None
        live_sd = live_font_box_size_delta(
            obj, pixel_scale=sx, base_sd=base_for_live,
        )
    except Exception:
        live_sd = None
    if live_sd is not None:
        ov["size_delta"] = (float(live_sd[0]), float(live_sd[1]))
        ov["box_width_px"] = abs(float(live_sd[0]))
        try:
            if abs(float(live_sd[0])) + 0.5 < abs(float(b_sd[0] or 0.0)):
                ov["enable_word_wrapping"] = True
        except Exception:
            pass
    else:
        sd_touched = False
        try:
            sd_touched = abs(float(n_sd[0]) - float(b_sd[0])) > 0.01
        except Exception:
            sd_touched = False
        if sd_touched:
            ov.pop("box_width_px", None)
        elif b_box is not None and n_box is not None:
            dw = (float(n_box) - float(b_box)) / sx
            # Stock: FONT auto-fit after a glyph edit is narrower, not a
            # user Size X. Stashing that clip in overrides rebuilt every
            # language into a tiny box (text vanished on reimport).
            if dw > 0.5 or (user_added and abs(dw) > 0.5):
                try:
                    ov["box_width_px"] = abs(float(n_sd[0])) + dw
                except Exception:
                    pass

    b_font = str(base.get("font") or "")
    n_font = str(now.get("font") or "")
    if b_font and n_font and n_font != b_font:
        ov["font"] = n_font

    b_col = base.get("color")
    n_col = now.get("color")
    if b_col is not None and n_col is not None:
        try:
            if any(abs(float(a) - float(b)) > 1.0 / 512.0
                   for a, b in zip(n_col, b_col)):
                ov["color"] = tuple(float(c) for c in n_col)
        except Exception:
            pass

    # Unity baseline on the object — never the builder stamp.
    b_rot, b_sc = _unity_trs_baseline(obj)
    n_rot = None
    n_sc = None
    try:
        n_rot = tuple(float(x) for x in obj.rotation_euler[:3])
    except Exception:
        n_rot = None
    try:
        n_sc = tuple(float(x) for x in obj.scale[:3])
    except Exception:
        n_sc = None
    if n_rot is not None and len(n_rot) >= 3:
        try:
            if any(abs(float(a) - float(b)) > 0.002 for a, b in zip(n_rot, b_rot)):
                ov["rotation_euler"] = tuple(float(c) for c in n_rot[:3])
        except Exception:
            pass
    if n_sc is not None and len(n_sc) >= 3:
        try:
            if any(abs(float(a) - float(b)) > 0.002 for a, b in zip(n_sc, b_sc)):
                ov["scale"] = tuple(float(c) for c in n_sc[:3])
        except Exception:
            pass

    try:
        from .viewport import snapshot_font_materials
        snap = snapshot_font_materials(obj)
        idxs = list(snap.get("indices") or [])
        mats = list(snap.get("materials") or [])
        multi = len(mats) > 1 or len(set(idxs)) > 1
        b_names = list(base.get("material_names") or [])
        n_names = [str(m.get("name") or "") for m in mats]
        b_idx = list(base.get("material_indices") or [])
        if multi and (n_names != b_names or idxs != b_idx):
            ov["font_materials"] = [
                {"name": m.get("name") or "", "color": m.get("color")}
                for m in mats
            ]
            ov["body_format"] = idxs
            ov["font_body"] = snap.get("body") or ""
            ov.pop("color", None)
    except Exception:
        pass
    return ov


def _merge_override_dicts(base_ov, live_ov) -> dict:
    """Union per-locale tweaks. An empty live capture must not wipe RAM."""
    out = {}
    if isinstance(base_ov, dict):
        out.update(base_ov)
    if isinstance(live_ov, dict) and live_ov:
        out.update(live_ov)
    return out


def merged_override_props(props: dict, overrides) -> dict:
    """Fold user tweaks into the props the text builder is about to use."""
    if not overrides or not isinstance(overrides, dict):
        return props
    try:
        fs = float(overrides.get("font_size") or 0.0)
        if fs > 1e-6:
            props["font_size"] = fs
    except Exception:
        pass
    try:
        want = float(overrides.get("box_width_px") or 0.0)
        if want > 0.5:
            sd = tuple(props.get("size_delta") or (0.0, 0.0))
            w = float(sd[0]) if sd else 0.0
            h = float(sd[1]) if len(sd) > 1 else 0.0
            props["size_delta"] = (want if w >= 0.0 else -want, h)
    except Exception:
        pass
    try:
        sd_ov = overrides.get("size_delta")
        if sd_ov is not None and len(sd_ov) >= 2:
            w = float(sd_ov[0])
            h = float(sd_ov[1])
            if abs(w) >= 1.0 or abs(h) >= 1.0:
                props["size_delta"] = (w, h)
    except Exception:
        pass
    try:
        if overrides.get("enable_word_wrapping") is True:
            props["enable_word_wrapping"] = True
    except Exception:
        pass
    try:
        col = overrides.get("color")
        if col is not None and len(col) >= 3:
            props["color"] = tuple(float(c) for c in col)
    except Exception:
        pass
    try:
        cs = overrides.get("content_size")
        if cs is not None and len(cs) >= 2:
            sd = list(props.get("size_delta") or (0.0, 0.0))
            while len(sd) < 2:
                sd.append(0.0)
            if abs(float(sd[0])) < 1.0 and abs(float(cs[0])) >= 1.0:
                sd[0] = float(cs[0])
            if abs(float(sd[1])) < 1.0 and abs(float(cs[1])) >= 1.0:
                sd[1] = float(cs[1])
            props["size_delta"] = (float(sd[0]), float(sd[1]))
    except Exception:
        pass
    return props


def apply_font_override(obj, overrides) -> None:
    """Swap in the font datablock the user picked (after the rebuild)."""
    if obj is None or not overrides or not isinstance(overrides, dict):
        return
    name = str(overrides.get("font") or "")
    if not name:
        return
    try:
        import bpy

        font = bpy.data.fonts.get(name)
        if font is not None:
            obj.data.font = font
    except Exception:
        pass


def apply_material_override(obj, overrides) -> None:
    """Restore per-letter FONT materials the user painted in Blender.

    Callers must pass THIS locale's ``user_overrides``. Silent viewport
    paint never opens a language dialog, so it lives only in ``active_locale``
    RAM — do not pass the previous language's leftover live materials.

    Body text is rebuilt from this locale's string, so it will not match the
    captured ``font_body`` byte-for-byte (TMP tags, NBSP, leading pad). Still
    apply slots + as many letter indices as fit — requiring an exact body
    dropped the paint on the way back from another language.
    """
    if obj is None or not overrides or not isinstance(overrides, dict):
        return
    mats = overrides.get("font_materials")
    if not mats:
        return
    try:
        from .viewport import restore_font_materials
        restore_font_materials(
            obj,
            {
                "materials": mats,
                "indices": list(overrides.get("body_format") or []),
                "body": str(overrides.get("font_body") or ""),
            },
            require_same_body=False,
        )
    except Exception:
        pass


def apply_blender_trs_override(obj, overrides=None, loc_el=None) -> None:
    """Restore Blender R/S the user set (Unity UI quat cannot round-trip them).

    ``overrides`` / ``loc_el`` must be the incoming locale's maps. Viewport
    G/R/S without a language dialog is active-locale only.
    """
    if obj is None:
        return
    rot = sc = None
    if isinstance(overrides, dict):
        rot = overrides.get("rotation_euler")
        sc = overrides.get("scale")
    user_edit = False
    if loc_el is not None:
        try:
            if isinstance(loc_el, dict):
                user_edit = bool(loc_el.get("has_viewport_edit"))
            else:
                user_edit = bool(getattr(loc_el, "has_viewport_edit", False))
        except Exception:
            user_edit = False
    if user_edit and rot is None and loc_el is not None:
        try:
            rot = loc_el.get("rotation_euler") if isinstance(loc_el, dict) else getattr(loc_el, "rotation_euler", None)
        except Exception:
            rot = None
    if user_edit and sc is None and loc_el is not None:
        try:
            sc = loc_el.get("scale") if isinstance(loc_el, dict) else getattr(loc_el, "scale", None)
        except Exception:
            sc = None
    try:
        if rot is not None and len(rot) >= 3:
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = (float(rot[0]), float(rot[1]), float(rot[2]))
    except Exception:
        pass
    try:
        if sc is not None and len(sc) >= 3:
            obj.scale = (float(sc[0]), float(sc[1]), float(sc[2]))
    except Exception:
        pass


def _user_added_uses_page_space_ap(obj) -> bool:
    """Flattened duplicates sit on the page; ConfT2 overlay pin AP is the wrong parent.

    After Duplicate, ``flatten_user_added_off_text_parent`` keeps Unity AP from
    ConfS2/ConfT2. Export then wrote overlay-space pixels and reimport placed
    clones under BackgroundBlack at the wrong XY (reimport.blend).
    """
    try:
        if not bool(obj.get("ksp_user_added")):
            return False
    except Exception:
        return False
    try:
        p = getattr(obj, "parent", None)
        if p is None:
            return True
        ui = p.ksp_ui
        if ui.is_ksp_ui and str(ui.kind or "") == "text":
            return False
    except Exception:
        return True
    return True


def snapshot_object_el_state(
    obj, *, pixel_scale: float = 0.001, mark_edit: bool = False
) -> dict:
    """Full live state of a KSPedia UI object (text or image) for RAM / rebuild.

    `mark_edit=True` only for interactive depsgraph sync (user G/R/S / N-panel).
    Locale switch capture must NOT mark every element as a viewport edit — that
    forced Blender `location` restores and made text boxes drift by hundreds
    of pixels across languages.
    """
    from .layout import blender_euler_to_unity_ui_quat

    prev_edit = False
    try:
        prev_edit = bool(obj.get("ksp_has_viewport_edit")) if obj is not None else False
    except Exception:
        prev_edit = False
    # Never stamp has_viewport_edit just because depsgraph asked us to look.
    # A nested child's G-move used to redirect onto the parent; mark_edit=True
    # then locked the parent's EN pose and shoved blue/white overlays (the
    # USER-LATEST-006 / 008 cascade). Only a real pin/rot/scale/box delta marks.
    state: Dict[str, Any] = {
        "has_viewport_edit": bool(prev_edit),
    }
    if obj is None:
        return state
    try:
        ui = obj.ksp_ui
    except Exception:
        ui = None

    kind = "empty"
    name = ""
    try:
        kind = str(getattr(ui, "kind", "") or "")
        name = (getattr(ui, "element_name", None) or obj.name or "").strip()
    except Exception:
        try:
            name = (obj.name or "").strip()
        except Exception:
            name = ""
    state["kind"] = kind or "empty"
    state["name"] = name
    state["element_name"] = name

    try:
        state["location"] = tuple(float(x) for x in obj.location)
    except Exception:
        pass
    try:
        state["rotation_euler"] = tuple(float(x) for x in obj.rotation_euler)
        state["local_rotation"] = blender_euler_to_unity_ui_quat(obj.rotation_euler)
    except Exception:
        pass
    try:
        state["scale"] = tuple(float(x) for x in obj.scale)
        state["local_scale"] = tuple(float(x) for x in obj.scale[:3])
    except Exception:
        pass

    # Rotation / scale vs import pin — G/R/S without a translation still counts.
    try:
        pin_rot = obj.get("ksp_layout_rot", None)
        if pin_rot is not None and len(pin_rot) >= 3:
            now = tuple(float(x) for x in obj.rotation_euler[:3])
            if any(abs(now[i] - float(pin_rot[i])) > 1e-4 for i in range(3)):
                state["has_viewport_edit"] = True
        pin_sc = obj.get("ksp_layout_scale", None)
        if pin_sc is not None and len(pin_sc) >= 3:
            now = tuple(float(x) for x in obj.scale[:3])
            if any(abs(now[i] - float(pin_sc[i])) > 2e-3 for i in range(min(3, len(now)))):
                state["has_viewport_edit"] = True
    except Exception:
        pass

    # Copy known ksp_ui fields, then override from live Blender where stronger
    if ui is not None:
        for k in _EL_FIELDS:
            if k in (
                "has_viewport_edit",
                "location",
                "rotation_euler",
                "scale",
                "local_rotation",
                "local_scale",
                "curve_size",
                "curve_shear",
                "curve_space_character",
                "curve_space_word",
                "curve_space_line",
                "curve_align_x",
                "curve_align_y",
                "curve_offset_x",
                "curve_offset_y",
                "curve_underline_position",
                "curve_underline_height",
                "curve_small_caps_scale",
                "curve_overflow",
                "text_boxes",
                "kind",
                "name",
                "element_name",
            ):
                continue
            if hasattr(ui, k):
                try:
                    state[k] = _plain_value(getattr(ui, k))
                except Exception:
                    pass

    # Unity localPosition.z — measured against the importer's draw-order bias.
    # Raw location.z would export a text at z=0.02 as localPosition.z = 20.
    try:
        sx = float(pixel_scale) or 0.001
        base_z = obj.get("ksp_base_z", None)
        if base_z is not None:
            state["local_position_z"] = (float(obj.location.z) - float(base_z)) / sx
        elif "local_position_z" not in state:
            state["local_position_z"] = float(obj.get("ksp_local_position_z", 0.0) or 0.0)
    except Exception:
        pass

    # A move in the viewport must reach Unity as anchoredPosition. Measuring
    # against the layout pin cancels the import calibration nudges that are
    # baked into location, so an untouched object reports its stored value.
    # After Outliner un-nest, location also carries ancestor AP deltas — those
    # are NOT a hand move and must not set has_viewport_edit (that locked the
    # previous language's XY into RAM and wiped Overview edits on switch).
    try:
        sx = float(pixel_scale) or 0.001
        page_ap = False
        if _user_added_uses_page_space_ap(obj):
            xy = None
            try:
                from .locale_switch import page_space_xy
                xy = page_space_xy(obj)
            except Exception:
                xy = None
            if xy is None or len(xy) < 2:
                xy = (float(obj.location.x), float(obj.location.y))
            ax = float(xy[0]) / sx
            ay = float(xy[1]) / sx
            state["anchored_position"] = (ax, ay)
            page_ap = True
            slop = 0.5 * sx
            try:
                old = tuple(obj.ksp_ui.anchored_position or (0.0, 0.0))
                if abs(ax - float(old[0])) > 0.5 or abs(ay - float(old[1])) > 0.5:
                    state["has_viewport_edit"] = True
            except Exception:
                state["has_viewport_edit"] = True
            try:
                pin_xy0 = obj.get("ksp_layout_xy", None)
                if pin_xy0 is not None and len(pin_xy0) >= 2:
                    if (
                        abs(float(xy[0]) - float(pin_xy0[0])) > slop
                        or abs(float(xy[1]) - float(pin_xy0[1])) > slop
                    ):
                        state["has_viewport_edit"] = True
            except Exception:
                pass
        pin_xy = obj.get("ksp_layout_xy", None)
        pin_ap = obj.get("ksp_layout_ap", None)
        font_like = False
        try:
            font_like = str(getattr(obj, "type", "") or "") == "FONT"
        except Exception:
            font_like = False
        # FONT rebuild after a glyph edit nudges location by ~1 px. That is
        # not a G-move; 0.5 px slop used to stamp has_viewport_edit and bake
        # a new AP into the default .ksp (every language shifted on reimport).
        loc_slop_px = 2.0 if (font_like and not page_ap) else 0.5
        if (
            not page_ap
            and pin_xy is not None and pin_ap is not None
            and len(pin_xy) >= 2 and len(pin_ap) >= 2
        ):
            slop = loc_slop_px * sx
            exp = None
            try:
                from .locale_switch import expected_locale_location
                exp = expected_locale_location(obj, pixel_scale)
            except Exception:
                exp = None
            if exp is not None:
                dx = float(obj.location.x) - float(exp[0])
                dy = float(obj.location.y) - float(exp[1])
                # Own AP = pin AP + (location − expected ancestor-composed).
                # expected already includes own locale AP, so a match ⇒ stock.
                if abs(dx) > slop or abs(dy) > slop:
                    # Guard against false positives in unit tests:
                    # if the object is still at the locale pin (stock), do not
                    # mark a viewport edit just because expected_locale_location
                    # differs due to partial stubs / mocked RNA.
                    dx_pin = abs(float(obj.location.x) - float(pin_xy[0]))
                    dy_pin = abs(float(obj.location.y) - float(pin_xy[1]))
                    if not (dx_pin <= slop and dy_pin <= slop):
                        state["has_viewport_edit"] = True
                    anc_dx = anc_dy = 0.0
                    try:
                        from .locale_switch import layout_shift_parts
                        _own_x, _own_y, anc_dx, anc_dy = layout_shift_parts(
                            obj,
                            tuple(obj.ksp_ui.anchored_position or (0.0, 0.0)),
                            pixel_scale,
                        )
                    except Exception:
                        anc_dx = anc_dy = 0.0
                    state["anchored_position"] = (
                        float(pin_ap[0]) + (
                            float(obj.location.x) - float(pin_xy[0]) - anc_dx
                        ) / sx,
                        float(pin_ap[1]) + (
                            float(obj.location.y) - float(pin_xy[1]) - anc_dy
                        ) / sx,
                    )
                else:
                    try:
                        state["anchored_position"] = (
                            float(obj.ksp_ui.anchored_position[0]),
                            float(obj.ksp_ui.anchored_position[1]),
                        )
                    except Exception:
                        state["anchored_position"] = (
                            float(pin_ap[0]), float(pin_ap[1])
                        )
                # USER-ADDED: even if expected_locale_location collapses in a
                # mocked/unit-test environment, a hand move must be treated as
                # a real viewport edit when it diverges from the locale pin.
                try:
                    user_added = bool(obj.get("ksp_user_added"))
                except Exception:
                    user_added = False
                if user_added:
                    dx_pin = abs(float(obj.location.x) - float(pin_xy[0]))
                    dy_pin = abs(float(obj.location.y) - float(pin_xy[1]))
                    if dx_pin > slop or dy_pin > slop:
                        state["has_viewport_edit"] = True
                # Nested stock children: live AP sync makes expected match, so
                # measure against the last stock locale apply — never against
                # a pin stamp from import (that flagged every nested child and
                # skipped apply_locale_layout_xy, stacking headers/bodies).
                try:
                    applied = obj.get("ksp_applied_xy", None)
                except Exception:
                    applied = None
                if applied is not None and len(applied) >= 2:
                    dx_app = abs(float(obj.location.x) - float(applied[0]))
                    dy_app = abs(float(obj.location.y) - float(applied[1]))
                    dx_pin = abs(float(obj.location.x) - float(pin_xy[0]))
                    dy_pin = abs(float(obj.location.y) - float(pin_xy[1]))
                    at_pin = dx_pin <= slop and dy_pin <= slop
                    if (dx_app > slop or dy_app > slop) and not at_pin:
                        state["has_viewport_edit"] = True
            else:
                dx = (float(obj.location.x) - float(pin_xy[0])) / sx
                dy = (float(obj.location.y) - float(pin_xy[1])) / sx
                state["anchored_position"] = (
                    float(pin_ap[0]) + dx,
                    float(pin_ap[1]) + dy,
                )
                if abs(dx) > loc_slop_px or abs(dy) > loc_slop_px:
                    state["has_viewport_edit"] = True
        else:
            # Load Image / Add Image often lacked pins → G-moves never left
            # AP=(0,0) and export stacked everything at the canvas centre.
            user_added = False
            try:
                user_added = bool(obj.get("ksp_user_added"))
            except Exception:
                user_added = False
            if user_added:
                ax = float(obj.location.x) / sx
                ay = float(obj.location.y) / sx
                state["anchored_position"] = (ax, ay)
                try:
                    old = tuple(obj.ksp_ui.anchored_position or (0.0, 0.0))
                    if abs(ax - float(old[0])) > 0.5 or abs(ay - float(old[1])) > 0.5:
                        state["has_viewport_edit"] = True
                except Exception:
                    if abs(ax) > 0.5 or abs(ay) > 0.5:
                        state["has_viewport_edit"] = True
                # Late-stamp so subsequent syncs use the pin path.
                try:
                    if pin_xy is None or pin_ap is None:
                        obj["ksp_layout_xy"] = (
                            float(obj.location.x), float(obj.location.y),
                        )
                        obj["ksp_layout_ap"] = (ax, ay)
                        try:
                            obj.ksp_ui.anchored_position = (ax, ay)
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception:
        pass

    # User-scaled image planes: sizeDelta = visual size in UI pixels
    # (mesh × object scale). Export then uses localScale (1,1,1) so scale is
    # not applied twice.
    try:
        user_added = bool(obj.get("ksp_user_added"))
    except Exception:
        user_added = False
    try:
        kind = str(getattr(obj.ksp_ui, "kind", "") or "")
    except Exception:
        kind = ""
    if user_added and kind == "image":
        try:
            sx = float(pixel_scale) or 0.001
            sc = tuple(float(x) for x in obj.scale[:2])
            if any(abs(c - 1.0) > 0.002 for c in sc):
                w_px = abs(float(obj.dimensions.x)) / sx
                h_px = abs(float(obj.dimensions.y)) / sx
                if w_px >= 1.0 and h_px >= 1.0:
                    state["size_delta"] = (w_px, h_px)
                    state["local_scale"] = (1.0, 1.0, 1.0)
                    state["has_viewport_edit"] = True
        except Exception:
            pass

    # FONT curve → Unity-ish spacing + exact curve overrides
    try:
        if getattr(obj, "type", "") == "FONT" and obj.data is not None:
            curve = obj.data
            try:
                state["curve_size"] = float(curve.size)
            except Exception:
                pass
            try:
                state["curve_shear"] = float(curve.shear)
            except Exception:
                pass
            # TMP spacing is read back as a ratio against the pinned build, not
            # as an absolute inverse: curve.space_* also carries the layout
            # profile multipliers and fit shrink, and exporting those made the
            # next import apply them a second time.
            pin_curve = None
            try:
                pc = obj.get("ksp_layout_curve", None)
                if pc is not None and len(pc) >= 4:
                    pin_curve = tuple(float(v) for v in pc[:4])
            except Exception:
                pin_curve = None

            def _spacing_pct(now, pin_idx, stored_key):
                """Unity %% that reproduces `now` given the pinned build."""
                if pin_curve is None or pin_curve[pin_idx] <= 1e-9:
                    return (now - 1.0) * 100.0
                stored = 0.0
                try:
                    stored = float(state.get(stored_key) or 0.0)
                except Exception:
                    stored = 0.0
                factor = 1.0 + stored / 100.0
                return (factor * now / pin_curve[pin_idx] - 1.0) * 100.0

            try:
                sc = float(curve.space_character)
                state["curve_space_character"] = sc
                state["character_spacing"] = _spacing_pct(sc, 1, "character_spacing")
            except Exception:
                pass
            try:
                sw = float(curve.space_word)
                state["curve_space_word"] = sw
                state["word_spacing"] = _spacing_pct(sw, 2, "word_spacing")
            except Exception:
                pass
            try:
                sl = float(curve.space_line)
                state["curve_space_line"] = sl
                state["line_spacing"] = _spacing_pct(sl, 3, "line_spacing")
            except Exception:
                pass
            for attr, key in (
                ("align_x", "curve_align_x"),
                ("align_y", "curve_align_y"),
                ("overflow", "curve_overflow"),
            ):
                try:
                    state[key] = str(getattr(curve, attr))
                except Exception:
                    pass
            try:
                state["curve_offset_x"] = float(curve.offset_x)
                state["curve_offset_y"] = float(curve.offset_y)
            except Exception:
                pass
            try:
                state["curve_underline_position"] = float(curve.underline_position)
                state["curve_underline_height"] = float(curve.underline_height)
            except Exception:
                pass
            try:
                state["curve_small_caps_scale"] = float(curve.small_caps_scale)
            except Exception:
                pass
            boxes = []
            try:
                for tb in curve.text_boxes:
                    boxes.append(
                        {
                            "width": float(tb.width),
                            "height": float(tb.height),
                            "x": float(tb.x),
                            "y": float(tb.y),
                        }
                    )
            except Exception:
                pass
            if boxes:
                # Blender FONT text_boxes often use height=0 (layout quirk).
                # Do not blindly copy them as Unity sizeDelta — only when the
                # user resized Size X/Y vs the post-build stamp.
                state["text_boxes"] = boxes
                try:
                    live_sd = live_font_box_size_delta(
                        obj,
                        pixel_scale=float(pixel_scale) or 0.001,
                        base_sd=state.get("size_delta"),
                    )
                    if live_sd is not None:
                        state["size_delta"] = (float(live_sd[0]), float(live_sd[1]))
                        state["has_viewport_edit"] = True
                        try:
                            ov = dict(state.get("user_overrides") or {})
                            ov["size_delta"] = (float(live_sd[0]), float(live_sd[1]))
                            ov["box_width_px"] = abs(float(live_sd[0]))
                            state["user_overrides"] = ov
                        except Exception:
                            pass
                except Exception:
                    pass
            # font_size from curve.size if ui missing/zero
            try:
                sx = float(pixel_scale) or 0.001
                fs = float(state.get("font_size") or 0.0)
                if fs < 1.0 and float(curve.size) > 1e-8:
                    state["font_size"] = float(curve.size) / sx
            except Exception:
                pass
    except Exception:
        pass

    try:
        ov = capture_user_overrides(obj, pixel_scale=pixel_scale)
        if ov:
            state["user_overrides"] = ov
    except Exception:
        pass
    try:
        from .viewport import snapshot_font_materials
        snap = snapshot_font_materials(obj)
        idxs = list(snap.get("indices") or [])
        mats = list(snap.get("materials") or [])
        if len(mats) > 1 or len(set(idxs)) > 1:
            ov = dict(state.get("user_overrides") or {})
            ov["font_materials"] = [
                {"name": m.get("name") or "", "color": m.get("color")}
                for m in mats
            ]
            ov["body_format"] = idxs
            ov["font_body"] = snap.get("body") or ""
            ov.pop("color", None)
            state["user_overrides"] = ov
    except Exception:
        pass
    try:
        cs = import_content_size_of(obj) or estimate_live_content_size(
            obj, pixel_scale=pixel_scale,
        )
        if cs is not None:
            state["content_size"] = cs
            ov = dict(state.get("user_overrides") or {})
            if "content_size" not in ov:
                ov["content_size"] = cs
                state["user_overrides"] = ov
            if import_content_size_of(obj) is None:
                stamp_import_content_size(obj, cs[0], cs[1])
    except Exception:
        pass

    try:
        if state.get("has_viewport_edit"):
            obj["ksp_has_viewport_edit"] = True
    except Exception:
        pass

    # RNA StringProperty / FONT body drop trailing ``\\n`` after space pads.
    try:
        src = str(obj.get("ksp_text_source") or "")
        ui_txt = str(state.get("text") or "")
        if src:
            from .viewport import preserve_overlay_newlines, is_space_pad_overlay
            src = preserve_overlay_newlines(src)
            if is_space_pad_overlay(src) or src.strip("\n\r") == ui_txt.strip("\n\r"):
                if len(src) >= len(ui_txt):
                    state["text"] = src
    except Exception:
        pass

    return state


def apply_viewport_el_state(obj, el, *, prefer_curve: bool = True) -> None:
    """Re-apply exact Blender TRS / FONT props from a captured el state.

    Blender `location` / `rotation_euler` / `scale` are restored ONLY when
    `has_viewport_edit` is set. Stray location keys from a locale capture must
    not move stock elements (that caused text-box drift across languages).
    """
    if obj is None or el is None:
        return
    d = _copy_el_dict(el) if not isinstance(el, dict) else el
    user_edit = bool(d.get("has_viewport_edit"))
    if not user_edit:
        # Disk / stock RAM — Unity localRotation/Scale/Z only; keep XY.
        try:
            from . import layout
            sx = 0.001
            try:
                root = obj
                while root.parent is not None:
                    root = root.parent
                if root.ksp_bundle.is_ksp_bundle:
                    sx = float(root.ksp_bundle.pixel_scale or 0.001)
            except Exception:
                pass
            # Keep the draw-order bias the importer gave this object, else
            # the text drops to z=0 and z-fights the page background.
            base_z = None
            try:
                bz = obj.get("ksp_base_z", None)
                base_z = None if bz is None else float(bz)
            except Exception:
                base_z = None
            layout.apply_ui_local_trs(
                obj, el_as_namespace(d), pixel_scale=sx, base_z=base_z
            )
        except Exception:
            pass
        return

    try:
        loc = d.get("location")
        if loc is not None and len(loc) >= 3:
            obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    except Exception:
        pass
    try:
        rot = d.get("rotation_euler")
        if rot is not None and len(rot) >= 3:
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = (float(rot[0]), float(rot[1]), float(rot[2]))
    except Exception:
        pass
    try:
        sc = d.get("scale")
        if sc is not None and len(sc) >= 3:
            obj.scale = (float(sc[0]), float(sc[1]), float(sc[2]))
    except Exception:
        pass

    if not prefer_curve or getattr(obj, "type", "") != "FONT" or obj.data is None:
        return
    curve = obj.data
    for attr, key in (
        ("size", "curve_size"),
        ("shear", "curve_shear"),
        ("space_character", "curve_space_character"),
        ("space_word", "curve_space_word"),
        ("space_line", "curve_space_line"),
        ("offset_x", "curve_offset_x"),
        ("offset_y", "curve_offset_y"),
        ("underline_position", "curve_underline_position"),
        ("underline_height", "curve_underline_height"),
        ("small_caps_scale", "curve_small_caps_scale"),
    ):
        if key not in d or d[key] is None:
            continue
        try:
            setattr(curve, attr, float(d[key]))
        except Exception:
            pass
    for attr, key in (
        ("align_x", "curve_align_x"),
        ("align_y", "curve_align_y"),
        ("overflow", "curve_overflow"),
    ):
        if key not in d or d[key] is None:
            continue
        try:
            setattr(curve, attr, str(d[key]))
        except Exception:
            pass
    boxes = d.get("text_boxes") or []
    # Do not push Blender text_boxes back when they would wipe Unity layout.
    # height≈0 is normal for FONT curves but must not become the content box.
    if boxes and prefer_curve:
        try:
            h0 = float(boxes[0].get("height", 0.0) or 0.0)
            w0 = float(boxes[0].get("width", 0.0) or 0.0)
            # Skip restore if both are near-zero, or height is zero while we
            # still have a real Unity size_delta height on the object.
            skip_boxes = False
            if w0 < 1e-8 and h0 < 1e-8:
                skip_boxes = True
            if h0 < 1e-8:
                try:
                    sd = tuple(obj.ksp_ui.size_delta or (0.0, 0.0))
                    if len(sd) > 1 and abs(float(sd[1])) > 1.0:
                        skip_boxes = True
                except Exception:
                    pass
            if not skip_boxes:
                while len(curve.text_boxes) < len(boxes):
                    curve.text_boxes.add()
                for i, b in enumerate(boxes):
                    tb = curve.text_boxes[i]
                    tb.width = float(b.get("width", 0.0))
                    tb.height = float(b.get("height", 0.0))
                    tb.x = float(b.get("x", 0.0))
                    tb.y = float(b.get("y", 0.0))
        except Exception:
            pass


def _write_state_to_ksp_ui(obj, state: dict) -> None:
    if obj is None or not state:
        return
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui:
            return
    except Exception:
        return
    mapping = (
        ("font_size", "font_size", float),
        ("line_spacing", "line_spacing", float),
        ("character_spacing", None, None),  # may not exist on ksp_ui
        ("local_position_z", "local_position_z", float),
        ("font_family", "font_family", str),
        ("text_alignment", "text_alignment", int),
        ("font_style", "font_style", int),
        ("enable_word_wrapping", "enable_word_wrapping", bool),
    )
    for src, dst, cast in mapping:
        if dst is None or src not in state:
            continue
        if not hasattr(ui, dst):
            continue
        try:
            val = cast(state[src]) if cast else state[src]
            cur = getattr(ui, dst)
            if cur != val:
                setattr(ui, dst, val)
        except Exception:
            pass
    for key, n in (
        ("local_rotation", 4),
        ("local_scale", 3),
        ("anchored_position", 2),
        ("size_delta", 2),
        ("pivot", 2),
        ("color", 4),
        ("margin", 4),
    ):
        if key not in state or not hasattr(ui, key):
            continue
        try:
            val = _tup(state[key], n)
            if val is None:
                continue
            # Guard: never flatten Unity size_delta height with a ~0 capture
            if key == "size_delta" and n >= 2:
                try:
                    cur = tuple(getattr(ui, key))
                    if abs(float(val[1])) < 1e-3 and abs(float(cur[1])) > 1.0:
                        val = (float(val[0]), float(cur[1])) + val[2:]
                except Exception:
                    pass
            cur = tuple(getattr(ui, key))
            if cur[:n] != val[:n]:
                setattr(ui, key, val[:n])
        except Exception:
            pass


def _bake_user_overrides_into_el_state(state: dict) -> dict:
    """Promote ``user_overrides`` into Unity export fields on an el dict.

    Locale capture often keeps R/S/colour only under ``user_overrides`` when
    ``has_viewport_edit`` is false (stock merge). Sibling ``.lang`` export
    reads ``local_rotation`` / ``color`` from the list — without this bake
    DE hand-edits were dropped and the file stayed factory.
    """
    if not state or not isinstance(state, dict):
        return state or {}
    ov = state.get("user_overrides")
    if not isinstance(ov, dict) or not ov:
        return state
    out = dict(state)
    try:
        col = ov.get("color")
        if col is not None and len(col) >= 3:
            out["color"] = tuple(float(c) for c in col[:4])
    except Exception:
        pass
    try:
        rot = ov.get("rotation_euler")
        if rot is not None and len(rot) >= 3:
            from .layout import blender_euler_to_unity_ui_quat
            out["rotation_euler"] = tuple(float(x) for x in rot[:3])
            out["local_rotation"] = tuple(
                float(x) for x in blender_euler_to_unity_ui_quat(rot)[:4]
            )
    except Exception:
        pass
    try:
        sc = ov.get("scale")
        if sc is not None and len(sc) >= 3:
            out["scale"] = tuple(float(x) for x in sc[:3])
            out["local_scale"] = tuple(float(x) for x in sc[:3])
    except Exception:
        pass
    # Multimaterial paint is restored on viewport via font_materials; export
    # text must already carry <color> from capture_text_map. If overrides have
    # a tagged font_body, prefer it when state text is plain.
    try:
        body = str(ov.get("font_body") or "")
        low = body.lower()
        if body and ("<color" in low or "<b>" in low or "<i>" in low):
            cur = str(out.get("text") or "")
            cur_l = cur.lower()
            if ("<color" not in cur_l) and ("<b>" not in cur_l):
                out["text"] = body
    except Exception:
        pass
    try:
        sd_ov = ov.get("size_delta")
        if sd_ov is not None and len(sd_ov) >= 2:
            w = float(sd_ov[0])
            h = float(sd_ov[1])
            if abs(w) >= 1.0 or abs(h) >= 1.0:
                out["size_delta"] = (w, h)
    except Exception:
        pass
    try:
        if ov.get("enable_word_wrapping") is True:
            out["enable_word_wrapping"] = True
    except Exception:
        pass
    return out


def _write_state_to_item(item, state: dict, plain: Optional[str] = None) -> None:
    if item is None:
        return
    # Plain text must apply even when layout state is empty — otherwise a
    # locale apply that only has text_by_hier leaves the previous language
    # sitting in ui_elements and export writes the wrong .lang.
    state = _bake_user_overrides_into_el_state(_copy_el_dict(state) if state else {})
    if plain is None and state.get("text"):
        plain = state.get("text")
    if plain is not None:
        try:
            clipped = _rna_text(plain)
            if item.text != clipped:
                item.text = clipped
        except Exception:
            pass
    if not state:
        return
    def _state_has(key: str) -> bool:
        if isinstance(state, dict):
            return key in state
        return hasattr(state, key)

    def _state_get(key: str):
        if isinstance(state, dict):
            return state.get(key)
        return getattr(state, key, None)

    for key, n in (
        ("local_rotation", 4),
        ("local_scale", 3),
        ("anchored_position", 2),
        ("size_delta", 2),
        ("pivot", 2),
        ("color", 4),
        ("margin", 4),
    ):
        if not _state_has(key) or not hasattr(item, key):
            continue
        try:
            val = _tup(_state_get(key), n)
            if val is None:
                continue
            if key == "size_delta" and n >= 2:
                try:
                    cur = tuple(getattr(item, key))
                    if abs(float(val[1])) < 1e-3 and abs(float(cur[1])) > 1.0:
                        val = (float(val[0]), float(cur[1])) + tuple(val[2:])
                except Exception:
                    pass
            cur = tuple(getattr(item, key))
            if cur[:n] != val[:n]:
                setattr(item, key, val[:n])
        except Exception:
            pass
    for key, cast in (
        ("font_size", float),
        ("line_spacing", float),
        ("character_spacing", float),
        ("word_spacing", float),
        ("paragraph_spacing", float),
        ("local_position_z", float),
        ("text_alignment", int),
        ("font_style", int),
        ("enable_word_wrapping", bool),
        ("font_family", str),
        ("overflow_mode", int),
        ("image_type", int),
        ("preserve_aspect", bool),
        ("fill_center", bool),
        ("fill_method", int),
        ("fill_amount", float),
        ("fill_clock_wise", bool),
        ("fill_origin", int),
        ("is_raw_image", bool),
    ):
        if not _state_has(key) or not hasattr(item, key):
            continue
        try:
            val = cast(_state_get(key))
            if getattr(item, key) != val:
                setattr(item, key, val)
        except Exception:
            pass


def _name_unique_in_kb(kb, name: str, *, kind: str = "") -> bool:
    if not name or kb is None:
        return False
    n = 0
    try:
        for it in kb.ui_elements:
            if kind and str(getattr(it, "kind", "") or "") != kind:
                continue
            if (getattr(it, "name", "") or "").strip() == name:
                n += 1
                if n > 1:
                    return False
    except Exception:
        return False
    return n == 1


def _upsert_el_in_maps(maps: dict, hier: str, name: str, state: dict) -> None:
    if not maps or not state:
        return
    el_h = maps.setdefault("el_by_hier", {})
    el_n = maps.setdefault("el_by_name", {})

    def _put(bucket, key):
        if not key:
            return
        prev = _copy_el_dict(bucket.get(key))
        new = _copy_el_dict(state)
        ov = _merge_override_dicts(prev.get("user_overrides"), new.get("user_overrides"))
        prev.update(new)
        if ov:
            prev["user_overrides"] = ov
        if new.get("content_size") and not prev.get("content_size"):
            prev["content_size"] = new["content_size"]
        elif prev.get("content_size") and not new.get("content_size"):
            pass  # keep
        bucket[key] = prev

    _put(el_h, hier)
    if name:
        _put(el_n, name)
        try:
            from .locale_switch import _element_base_name
            base = _element_base_name(name)
            if base and base not in el_n:
                el_n[base] = dict(el_n.get(name) or {})
        except Exception:
            pass


def sync_object_live(obj, kb=None, root=None, plain: Optional[str] = None) -> bool:
    """Push one object's live viewport state into ksp_ui / list / active locale RAM.

    Invariant: silent viewport ops (G/R/S, colour, material, texture scale)
    never prompt for languages. When more than one language exists they
    write ONLY ``active_locale`` maps (and that locale's parked tree).
    Duplicate / Add / Delete still use the ``_LocaleScopeMixin`` dialog.

    Safe for depsgraph: skips when locked; writes only when values change.
    Blender undo restores Object/Curve IDs; the next sync refreshes RAM to match.
    """
    global _LIVE_SYNC_LOCK
    if _LIVE_SYNC_LOCK or obj is None:
        return False
    try:
        from .blend_persist import in_undo_redo
        if in_undo_redo():
            return False
    except Exception:
        pass
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui:
            return False
        kind = str(ui.kind or "")
        if kind not in ("text", "image"):
            return False
    except Exception:
        return False

    if root is None:
        cur = obj
        while cur is not None:
            try:
                if cur.ksp_bundle.is_ksp_bundle:
                    root = cur
                    break
            except Exception:
                pass
            cur = cur.parent
    if root is None:
        return False
    if kb is None:
        try:
            kb = root.ksp_bundle
        except Exception:
            return False

    pixel_scale = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
    state = snapshot_object_el_state(obj, pixel_scale=pixel_scale, mark_edit=True)
    if plain is not None:
        state["text"] = plain
        try:
            obj["ksp_text_source"] = str(plain)
        except Exception:
            pass
    # Glyph-only sync: do not bake FONT-rebuild AP / size into ksp_ui.
    # Those RectTransform fields are shared across languages after reimport.
    try:
        user_added_sync = bool(obj.get("ksp_user_added"))
    except Exception:
        user_added_sync = False
    if not state.get("has_viewport_edit") and not user_added_sync:
        state.pop("anchored_position", None)
        state.pop("size_delta", None)

    _LIVE_SYNC_LOCK = True
    try:
        _write_state_to_ksp_ui(obj, state)
        # Match ui_elements row
        try:
            from .locale_switch import _obj_hierarchy_key, _find_element_item
            item = _find_element_item(kb, obj)
            if item is not None:
                _write_state_to_item(item, state, plain=plain)
            hier = _obj_hierarchy_key(obj)
            name = state.get("element_name") or state.get("name") or ""
        except Exception:
            hier, name = "", state.get("name") or ""

        loc = (getattr(kb, "active_locale", "") or getattr(kb, "locale", "") or "").lower()
        if not loc:
            loc = get_prev_locale(kb)
        if loc:
            p = _ptr(kb)
            bucket = _BUFFERS.setdefault(p, {})
            maps = bucket.get(loc)
            if maps is None:
                # Empty shell here used to wipe present_* on the next
                # store_maps — every UI Elements row of this language went
                # Missing after painting a multimaterial and switching locale.
                try:
                    hydrate_from_blend(kb, root)
                    maps = bucket.get(loc)
                except Exception:
                    maps = None
            if maps is not None:
                _upsert_el_in_maps(maps, hier, name if _name_unique_in_kb(kb, name) else "", state)
                if plain is not None:
                    if hier:
                        maps.setdefault("text_by_hier", {})[hier] = plain
                    if name and _name_unique_in_kb(kb, name):
                        maps.setdefault("text_by_name", {})[name] = plain
        return True
    finally:
        _LIVE_SYNC_LOCK = False


def viewport_text_of(obj, *, expect_locale: str = "") -> str:
    """Authoritative text for a live UI object.

    Prefer the source string stamped on ``ksp_ui`` / the object over the FONT
    body: the body is what Blender *renders* (figure-spaces, soft wraps, as/each
    splits) and writing it back into the .lang would destroy the original.
    The FONT body is only the last resort when nothing else was stored.

    ``expect_locale``: when capturing language L, skip live strings whose
    ``ksp_locale_applied`` is a different language — otherwise a stale ES
    FONT / ksp_ui after EN→ES→EN poisons the EN RAM map and the .ksp.
    """
    if obj is None:
        return ""
    expect = (expect_locale or "").strip().lower()
    if expect:
        try:
            applied = str(obj.get("ksp_locale_applied") or "").strip().lower()
        except Exception:
            applied = ""
        if applied and applied != expect:
            return ""
    ui_plain = ""
    try:
        ui_plain = str(obj.ksp_ui.text or "")
    except Exception:
        ui_plain = ""
    src_plain = ""
    try:
        src_plain = str(obj.get("ksp_text_source") or "")
    except Exception:
        src_plain = ""
    disp = ""
    try:
        disp = str(obj.get("ksp_text_display", "") or "")
    except Exception:
        disp = ""
    font_plain = ""
    try:
        from .mu_ops import collect_viewport_text_plain

        font_plain = collect_viewport_text_plain(obj) or ""
    except Exception:
        font_plain = ""

    def _chomp_nl(s: str) -> str:
        return (s or "").strip("\n\r")

    def _strip_tags(s: str) -> str:
        try:
            import re
            return re.sub(r"<[^>]+>", "", s or "").strip("\n\r")
        except Exception:
            return (s or "").strip("\n\r")

    # Overlay pads: ID-prop / ksp_ui keep trailing \\n that FONT display drops.
    try:
        from .viewport import (
            is_artwork_overlay,
            is_space_pad_overlay,
            preserve_overlay_newlines,
        )
        cand = src_plain or ui_plain
        if cand:
            try:
                cand = preserve_overlay_newlines(cand)
            except Exception:
                pass
        if cand and (
            is_artwork_overlay(cand, obj) or is_space_pad_overlay(cand)
        ):
            if not font_plain or _chomp_nl(font_plain) == _chomp_nl(cand):
                return cand
            if ui_plain and _chomp_nl(ui_plain) == _chomp_nl(cand):
                return cand if len(cand) >= len(ui_plain) else ui_plain
            return cand
    except Exception:
        pass

    # After a locale apply the FONT curve is updated first; ksp_ui can lag on
    # the previous language. Prefer FONT when tag-stripped plains diverge so
    # capture/export cannot re-poison RAM with the stale PropertyGroup string.
    if ui_plain and font_plain and _strip_tags(ui_plain) != _strip_tags(font_plain):
        return font_plain
    if src_plain and _chomp_nl(src_plain) == _chomp_nl(ui_plain or src_plain):
        if len(src_plain) >= len(ui_plain or ""):
            return src_plain
    if ui_plain:
        return ui_plain
    if disp:
        return disp
    return font_plain or ""


def capture_text_map_from_viewport(root, locale: str = "") -> dict:
    """Snapshot live viewport texts + full el layout into a locale map."""
    from .locale_switch import (
        _is_locale_text_root,
        _obj_hierarchy_key,
        _element_base_name,
        _purge_duplicate_text_roots,
    )

    text_by_hier: Dict[str, str] = {}
    text_by_name: Dict[str, str] = {}
    el_by_hier: Dict[str, dict] = {}
    el_by_name: Dict[str, dict] = {}

    pixel_scale = 0.001
    kb = None
    try:
        kb = root.ksp_bundle
        pixel_scale = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
    except Exception:
        kb = None
    expect_loc = (locale or "").strip().lower()
    if not expect_loc and kb is not None:
        try:
            expect_loc = (
                str(getattr(kb, "active_locale", "") or "")
                or str(getattr(kb, "locale", "") or "")
            ).strip().lower()
        except Exception:
            expect_loc = ""

    objs = []
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    # Boxes this language dropped are still in the scene, hidden, holding the
    # previous language's text - capturing them would write it back.
    objs = [o for o in objs if not _is_locale_orphan(o)]
    texts = [o for o in objs if _is_locale_text_root(o)]
    texts = _purge_duplicate_text_roots(texts, delete=False)
    name_counts: Dict[str, int] = {}
    for obj in texts:
        try:
            nm = (obj.ksp_ui.element_name or obj.name or "").strip()
        except Exception:
            continue
        if nm:
            name_counts[nm] = name_counts.get(nm, 0) + 1

    try:
        from .locale_switch import _set_layout_apply_ctx, _clear_layout_apply_ctx
        _set_layout_apply_ctx(root, None, kb)
    except Exception:
        pass
    try:
        for obj in texts:
            try:
                ui = obj.ksp_ui
                name = (ui.element_name or obj.name or "").strip()
            except Exception:
                continue
            if expect_loc:
                try:
                    applied = str(obj.get("ksp_locale_applied") or "").strip().lower()
                except Exception:
                    applied = ""
                if applied and applied != expect_loc:
                    continue
            try:
                plain = viewport_text_of(obj, expect_locale=expect_loc)
                state = snapshot_object_el_state(obj, pixel_scale=pixel_scale)
                state["text"] = plain
                hier = _obj_hierarchy_key(obj)
                if hier:
                    text_by_hier[hier] = plain
                    el_by_hier[hier] = state
                unique = bool(name) and name_counts.get(name, 0) == 1
                if unique:
                    text_by_name[name] = plain
                    el_by_name[name] = state
                    base = _element_base_name(name)
                    if base and base not in text_by_name:
                        text_by_name[base] = plain
                    if base and base not in el_by_name:
                        el_by_name[base] = state
            except Exception:
                continue

        # Images: layout only (no text map)
        for obj in objs:
            try:
                ui = obj.ksp_ui
                if not ui.is_ksp_ui or ui.kind != "image":
                    continue
                name = (ui.element_name or obj.name or "").strip()
            except Exception:
                continue
            state = snapshot_object_el_state(obj, pixel_scale=pixel_scale)
            hier = _obj_hierarchy_key(obj)
            if hier:
                el_by_hier[hier] = state
            if name:
                el_by_name[name] = state

        # Also pull from ui_elements list (authoritative for export path ids)
        try:
            if kb is None:
                kb = root.ksp_bundle
            for item in kb.ui_elements:
                if item.kind != "text" or item.missing_in_locale:
                    continue
                name = (item.name or "").strip()
                plain = item.text or ""
                vo = item.viewport_object
                if vo is None:
                    # No live stamp — list may still hold the previous language
                    # after capture_current(apply_maps). Skip when capturing L.
                    if expect_loc:
                        continue
                if vo is not None:
                    try:
                        applied = str(vo.get("ksp_locale_applied") or "").strip().lower()
                    except Exception:
                        applied = ""
                    # Require an explicit matching stamp. Empty applied + stale
                    # list text (previous sibling language) must not enter RAM.
                    if expect_loc and applied != expect_loc:
                        continue
                    try:
                        live = viewport_text_of(vo, expect_locale=expect_loc)
                        if live:
                            plain = live
                            # Only write back when the source string itself changed
                            # — never when the FONT body differs from the stamp.
                            clipped = _rna_text(live)
                            if (item.text or "") != clipped:
                                item.text = clipped
                    except Exception:
                        pass
                    hier = _obj_hierarchy_key(vo)
                    if hier:
                        text_by_hier[hier] = plain
                        if hier not in el_by_hier:
                            el_by_hier[hier] = snapshot_object_el_state(
                                vo, pixel_scale=pixel_scale
                            )
                    try:
                        _write_state_to_item(
                            item,
                            el_by_hier.get(hier) or snapshot_object_el_state(
                                vo, pixel_scale=pixel_scale
                            ),
                            plain=plain,
                        )
                    except Exception:
                        pass
                if name and name not in text_by_name:
                    text_by_name[name] = plain
        except Exception:
            pass
    finally:
        try:
            from .locale_switch import _clear_layout_apply_ctx
            _clear_layout_apply_ctx()
        except Exception:
            pass

    return {
        "text_by_hier": text_by_hier,
        "text_by_name": text_by_name,
        "el_by_hier": el_by_hier,
        "el_by_name": el_by_name,
    }


def apply_maps_to_ui_elements(
    kb, maps: dict, *, clear_stale_text: bool = True, touch_viewport: bool = True,
    locale: str = "",
) -> int:
    """Write map texts + layout into kb.ui_elements rows (for export).

    ``clear_stale_text``: when a text row is not found in this locale's maps,
    clear its list text so a previous language (e.g. DE left after
    ``capture_current``) cannot leak into the EN ``.ksp`` on export.
    """
    if kb is None or not maps:
        return 0
    text_by_hier = maps.get("text_by_hier") or {}
    text_by_name = maps.get("text_by_name") or {}
    el_by_hier = maps.get("el_by_hier") or {}
    el_by_name = maps.get("el_by_name") or {}
    n = 0
    for item in kb.ui_elements:
        kind = str(getattr(item, "kind", "") or "")
        if kind not in ("text", "image", "empty"):
            continue
        plain = None
        el = None
        matched = False
        vo = item.viewport_object
        try:
            from .locale_switch import _obj_blocks_active_locale
            loc = (
                (locale or "").strip().lower()
                or (getattr(kb, "active_locale", "") or "").lower()
            )
            if _obj_blocks_active_locale(vo, loc):
                continue
        except Exception:
            pass
        name = (item.name or "").strip()
        hier = ""
        mb = ""
        try:
            mb = str(getattr(item, "mb_path_id", "") or "").strip()
        except Exception:
            mb = ""
        if vo is not None:
            try:
                from .locale_switch import _obj_hierarchy_key, _lookup_el_by_mb
                hier = _obj_hierarchy_key(vo)
                if hier and hier in el_by_hier:
                    el = el_by_hier[hier]
                    matched = True
                if kind == "text" and hier and hier in text_by_hier:
                    plain = text_by_hier[hier]
                    matched = True
                if el is None and mb:
                    el = _lookup_el_by_mb(el_by_hier, mb)
                    if el is not None:
                        matched = True
                        if plain is None and kind == "text":
                            plain = getattr(el, "text", None)
                            if isinstance(el, dict):
                                plain = el.get("text") if plain is None else plain
            except Exception:
                pass
        # Prefer by-name when present — hierarchy keys can stay on a stale
        # stock string after a user edit that updated text_by_name only
        # (sibling .lang export then wrote the wrong language into the file).
        # Duplicate GO names are omitted from unique-name maps: do not stamp
        # one sibling's string onto every row that shares the name.
        name_unique = True
        if name:
            try:
                name_unique = sum(
                    1 for it in kb.ui_elements
                    if str(getattr(it, "kind", "") or "") == kind
                    and (it.name or "").strip() == name
                ) == 1
            except Exception:
                name_unique = False
        # Name layout/color survives hier drift (same as text pins).
        if name and name in el_by_name and (name_unique or el is None):
            el = el_by_name[name]
            matched = True
        # Fall back to name text when hier missed — duplicate names still
        # need a restore after locale switch or DE leaks into the EN .ksp.
        if kind == "text" and name and name in text_by_name and name_unique:
            plain = text_by_name[name]
            matched = True
            if el is None and name in el_by_name:
                el = el_by_name[name]
        if not matched and plain is None and el is None:
            if clear_stale_text and kind == "text":
                # Only wipe when this locale does not ship the element —
                # otherwise a lookup miss would blank a real string.
                missing = False
                try:
                    presence = presence_from_maps(maps)
                    missing = not presence_has_element(
                        presence, hier, name, kind, mb_path_id=mb,
                    )
                except Exception:
                    missing = False
                if missing:
                    try:
                        if item.text:
                            item.text = ""
                            n += 1
                        item.missing_in_locale = True
                    except Exception:
                        pass
            continue
        try:
            _write_state_to_item(item, _copy_el_dict(el) if el else {}, plain=plain)
            n += 1
        except Exception:
            pass
        if touch_viewport and vo is not None and plain is not None and kind == "text":
            try:
                if vo.ksp_ui.is_ksp_ui:
                    vo.ksp_ui.text = _rna_text(plain)
            except Exception:
                pass
    return n


def sync_missing_flags(kb, maps: Optional[dict], locale: str = "") -> int:
    """Flag ui_elements rows the active locale does not ship. Returns count."""
    if kb is None:
        return 0
    presence = presence_from_maps(maps)
    from .locale_switch import _obj_hierarchy_key

    loc = (
        (locale or "").strip().lower()
        or (getattr(kb, "active_locale", "") or "").lower()
    )
    n = 0
    for item in kb.ui_elements:
        hier = ""
        vo = item.viewport_object
        if vo is not None:
            try:
                hier = _obj_hierarchy_key(vo)
            except Exception:
                hier = ""
        name = (item.name or "").strip()
        mb = ""
        try:
            mb = str(getattr(item, "mb_path_id", "") or "").strip()
        except Exception:
            mb = ""
        if not mb and vo is not None:
            try:
                mb = str(getattr(vo.ksp_ui, "mb_path_id", "") or "").strip()
            except Exception:
                mb = ""
        missing = not presence_has_element(
            presence, hier, name, str(item.kind or ""), mb_path_id=mb
        )
        try:
            if vo is not None and is_forgotten_in_locale(vo, loc):
                missing = True
        except Exception:
            pass
        # presence_has_element always returns True for images (stock ru/zh
        # GO renames). User-added Load Image still has to drop other .lang.
        try:
            if vo is not None:
                shipped = str(vo.get("ksp_shipped_locales") or "").strip()
                if shipped and loc:
                    allowed = {
                        x.strip().lower() for x in shipped.split(",") if x.strip()
                    }
                    if loc not in allowed:
                        missing = True
        except Exception:
            pass
        try:
            if item.missing_in_locale != missing:
                item.missing_in_locale = missing
        except Exception:
            continue
        if missing:
            n += 1
    return n


def _store_titles_from_bundle(kb, locale: str, bundle, filepath: str = "") -> None:
    try:
        from . import properties as _props
        from . import kspedia_index
        idx = kspedia_index.parse_kspedia_from_bundle_text_assets(
            getattr(bundle, "text_assets", None) or [],
            filepath=filepath or getattr(bundle, "filepath", "") or "",
        )
        titles = {}
        for e in getattr(idx, "entries", None) or []:
            if e.kind == "page" and e.screen and e.title:
                titles[e.screen] = e.title
            if e.kind in ("category", "subcategory") and getattr(
                e, "title_screen", ""
            ):
                if e.title:
                    titles[e.title_screen] = e.title
        if titles:
            _props._store_locale_titles(
                kb, locale, titles, prefer_existing=True
            )
    except Exception:
        pass


def seed_from_disk(kb, locale: str, filepath: str) -> Optional[dict]:
    """Load locale maps from a .ksp/.lang on disk into RAM.

    Uses the light UI-only parser (no textures / deps / font extract) so
    sibling .lang files can be hydrated in the background without a full
    ``load_bundle``.
    """
    from .bundle import load_locale_ui_bundle
    from .locale_switch import locale_maps_from_bundle

    loc = (locale or "").lower()
    if not loc or not filepath or not os.path.isfile(filepath):
        return None
    try:
        bundle = load_locale_ui_bundle(filepath)
        maps = locale_maps_from_bundle(bundle)
        store_maps(kb, loc, maps)
        _store_titles_from_bundle(kb, loc, bundle, filepath)
        return get_maps(kb, loc)
    except Exception:
        return None


# Background sibling-locale hydration (one UnityPy parse per timer tick).
_PRELOAD_JOBS: Dict[int, dict] = {}
_PRELOAD_TIMER_ON = False


def pending_preload_locales(kb) -> list:
    job = _PRELOAD_JOBS.get(_ptr(kb))
    if not job:
        return []
    return list(job.get("pending") or [])


def process_preload_chunk(kb=None, *, n: int = 1) -> int:
    """Seed up to ``n`` pending sibling locales into RAM. Returns how many ran."""
    jobs = []
    if kb is not None:
        job = _PRELOAD_JOBS.get(_ptr(kb))
        if job:
            jobs = [(_ptr(kb), job)]
    else:
        jobs = list(_PRELOAD_JOBS.items())
    did = 0
    want = max(1, int(n or 1))
    for ptr, job in jobs:
        pending = list(job.get("pending") or [])
        while pending and did < want:
            loc, path = pending.pop(0)
            job["pending"] = pending
            target_kb = job.get("kb")
            if target_kb is None and kb is not None:
                target_kb = kb
            if target_kb is None:
                target_kb = _kb_from_ptr(ptr)
            if target_kb is None:
                continue
            if has_locale_maps(target_kb, loc):
                continue
            try:
                seed_from_disk(target_kb, loc, path)
            except Exception:
                pass
            did += 1
        if not pending:
            _PRELOAD_JOBS.pop(ptr, None)
        else:
            job["pending"] = pending
    return did


def drain_locale_preload(kb=None, *, limit: int = 64) -> int:
    """Synchronously finish sibling preload (tests / scripts)."""
    n = 0
    guard = 0
    while guard < int(limit or 64):
        got = process_preload_chunk(kb, n=1)
        if not got:
            break
        n += got
        guard += 1
    return n


def _kb_from_ptr(ptr: int):
    try:
        import bpy
        for obj in bpy.data.objects:
            try:
                kb = obj.ksp_bundle
                if kb.is_ksp_bundle and int(kb.as_pointer()) == int(ptr):
                    return kb
            except Exception:
                continue
    except Exception:
        pass
    return None


def _preload_timer():
    global _PRELOAD_TIMER_ON
    try:
        got = process_preload_chunk(None, n=1)
    except Exception:
        got = 0
    if _PRELOAD_JOBS and got >= 0 and any(
        (j.get("pending") or []) for j in _PRELOAD_JOBS.values()
    ):
        return 0.05
    _PRELOAD_TIMER_ON = False
    return None


def schedule_preload_sibling_locales(kb, source_path: str, skip_locale: str = "") -> int:
    """Queue every sibling .lang/.ksp into RAM without blocking the viewport.

    Import should call this after the active (usually EN) maps exist. Each
    timer tick parses one file via the light UI loader. Locale switch after
    preload is RAM-only.
    """
    global _PRELOAD_TIMER_ON
    if kb is None or not source_path:
        return 0
    try:
        from .locale_switch import discover_locale_variants
        variants = discover_locale_variants(source_path)
    except Exception:
        variants = []
    skip = (skip_locale or "").lower()
    pending = []
    for loc, path in variants:
        L = (loc or "").lower()
        if not L or L == skip:
            continue
        if has_locale_maps(kb, L):
            continue
        if path and os.path.isfile(path):
            pending.append((L, path))
    csv = ""
    try:
        csv = getattr(kb, "available_locales", "") or ""
    except Exception:
        csv = ""
    have = {L for L, _ in pending}
    have.add(skip)
    for tag in (x.strip().lower() for x in csv.split(",") if x.strip()):
        if tag in have or has_locale_maps(kb, tag):
            continue
        try:
            from .locale_switch import path_for_locale
            path = path_for_locale(source_path, tag)
        except Exception:
            path = ""
        if path and os.path.isfile(path):
            pending.append((tag, path))
            have.add(tag)
    if not pending:
        return 0
    ptr = _ptr(kb)
    prev = _PRELOAD_JOBS.get(ptr) or {}
    old = list(prev.get("pending") or [])
    seen = {(a, b) for a, b in old}
    for item in pending:
        if item not in seen:
            old.append(item)
            seen.add(item)
    _PRELOAD_JOBS[ptr] = {"kb": kb, "pending": old, "source": source_path}
    try:
        import bpy
        if not _PRELOAD_TIMER_ON:
            bpy.app.timers.register(_preload_timer, first_interval=0.05)
            _PRELOAD_TIMER_ON = True
    except Exception:
        pass
    return len(old)



def refresh_el_metrics_from_disk(kb, locale: str, source_path: str) -> bool:
    """Reload Unity/TMP metrics from the locale file; keep RAM texts.

    Stops poisoned curve captures from permanently replacing .lang spacing.
    """
    from .locale_switch import path_for_locale, locale_maps_from_bundle
    from .bundle import load_bundle
    import os

    loc = (locale or "").lower()
    if not loc or not source_path:
        return False
    path = path_for_locale(source_path, loc) if source_path else ""
    if not path or not os.path.isfile(path):
        return False
    try:
        bundle, _env = load_bundle(path)
        disk = locale_maps_from_bundle(bundle)
    except Exception:
        return False
    cur = get_maps(kb, loc)
    if cur is None:
        store_maps(kb, loc, disk)
        return True
    # Preserve edited texts from RAM
    text_h = dict(cur.get("text_by_hier") or {})
    text_n = dict(cur.get("text_by_name") or {})
    # Prefer disk texts only where RAM empty
    for k, v in (disk.get("text_by_hier") or {}).items():
        text_h.setdefault(k, v)
    for k, v in (disk.get("text_by_name") or {}).items():
        text_n.setdefault(k, v)
    merged = {
        "text_by_hier": text_h,
        "text_by_name": text_n,
        "el_by_hier": {
            str(k): _strip_blender_trs_fields(_copy_el_dict(v))
            for k, v in (disk.get("el_by_hier") or {}).items()
        },
        "el_by_name": {
            str(k): _strip_blender_trs_fields(_copy_el_dict(v))
            for k, v in (disk.get("el_by_name") or {}).items()
        },
    }
    # Keep user viewport edits if any (rare)
    for bname in ("el_by_hier", "el_by_name"):
        for k, el in (cur.get(bname) or {}).items():
            d = _copy_el_dict(el)
            if d.get("has_viewport_edit") and k in merged[bname]:
                keep = merged[bname][k]
                keep["has_viewport_edit"] = True
                for fk in ("location", "rotation_euler", "scale"):
                    if fk in d:
                        keep[fk] = d[fk]
                merged[bname][k] = keep
    # #region agent log
    try:
        from .locale_switch import _dbg
        _blk = merged.get("el_by_name") or {}
        _sample = {}
        for _k in sorted(_blk.keys())[:4]:
            _e = _blk[_k] or {}
            _sample[_k] = {
                "font_size": _e.get("font_size"),
                "char_sp": _e.get("character_spacing"),
                "word_sp": _e.get("word_spacing"),
                "line_sp": _e.get("line_spacing"),
                "anchored": _e.get("anchored_position"),
                "size_delta": _e.get("size_delta"),
                "family": _e.get("font_family"),
            }
        _dbg("B,E", "disk .lang metrics", {
            "locale": loc,
            "file": os.path.basename(path),
            "n_el": len(_blk),
            "sample": _sample,
        })
    except Exception:
        pass
    # #endregion
    store_maps(kb, loc, merged)
    return True


def ensure_locale_maps(kb, locale: str, source_path: str) -> Optional[dict]:
    """Return RAM maps for locale, seeding from disk once if needed."""
    from .locale_switch import path_for_locale

    loc = (locale or "").lower()
    raw_entry = (_BUFFERS.get(_ptr(kb)) or {}).get(loc)
    cached = get_maps(kb, loc) if raw_entry is not None else None
    if cached is not None:
        # Synthesize present_names_all in RAM — never re-seed from disk just
        # for that key (disk reload wiped layout / made language switches slow).
        if raw_entry is not None and "present_names_all" not in raw_entry:
            names = set(raw_entry.get("present_names") or ())
            names |= set((raw_entry.get("text_by_name") or {}).keys())
            names |= set((raw_entry.get("el_by_name") or {}).keys())
            raw_entry["present_names_all"] = sorted(names)
            cached = get_maps(kb, loc) or cached
        return cached
    path = path_for_locale(source_path, loc) if source_path else ""
    if path and os.path.isfile(path):
        seeded = seed_from_disk(kb, loc, path)
        if seeded is not None:
            return seeded
    # New locale with no file yet: clone from default/en-us/active if any
    for fallback in (
        (getattr(kb, "locale", "") or "").lower(),
        "en-us",
        (getattr(kb, "active_locale", "") or "").lower(),
    ):
        if not fallback or fallback == loc:
            continue
        src = get_maps(kb, fallback)
        if src is not None:
            # Clone stock texts/layout only. Copying EN user_overrides onto
            # a missing DE file leaked rotation, scale and multimaterial.
            cloned = {
                "text_by_hier": dict(src.get("text_by_hier") or {}),
                "text_by_name": dict(src.get("text_by_name") or {}),
                "el_by_hier": {},
                "el_by_name": {},
            }
            for bname in ("el_by_hier", "el_by_name"):
                for key, el in (src.get(bname) or {}).items():
                    d = _strip_blender_trs_fields(_copy_el_dict(el))
                    d.pop("user_overrides", None)
                    d["has_viewport_edit"] = False
                    cloned[bname][key] = d
            store_maps(kb, loc, cloned)
            return get_maps(kb, loc)
    # Empty shell
    store_maps(
        kb,
        loc,
        {
            "text_by_hier": {},
            "text_by_name": {},
            "el_by_hier": {},
            "el_by_name": {},
            "present_mb": [],
            "present_names_all": [],
        },
    )
    return get_maps(kb, loc)



def update_element_fields(
    kb,
    locale: str,
    *,
    hier: str = "",
    name: str = "",
    font_family: str = "",
) -> None:
    """Update element fields inside a locale RAM buffer (best-effort).

    Used by `KSPMU_OT_SetUiFont` to propagate font family into per-locale
    element maps.
    """
    try:
        loc = (locale or "").lower()
        if not loc or kb is None:
            return
        if not has_locale_maps(kb, loc):
            # Seed empty shell; caller may not have an on-disk .lang yet.
            ensure_locale_maps(kb, loc, source_path="")

        bucket = _BUFFERS.get(_ptr(kb)) or {}
        entry = bucket.get(loc)
        if not isinstance(entry, dict):
            return

        ff = str(font_family or "")
        if not ff:
            return

        if hier:
            el = (entry.get("el_by_hier") or {}).get(str(hier))
            if isinstance(el, dict):
                el["font_family"] = ff

        if name:
            el = (entry.get("el_by_name") or {}).get(str(name))
            if isinstance(el, dict):
                el["font_family"] = ff
    except Exception:
        # Locale buffers are critical path for UI; never crash ops.
        return


_BLENDER_TRS_KEYS = (
    "location",
    "rotation_euler",
    "scale",
    "text_boxes",
    "curve_size",
    "curve_shear",
    "curve_space_character",
    "curve_space_word",
    "curve_space_line",
    "curve_align_x",
    "curve_align_y",
    "curve_offset_x",
    "curve_offset_y",
    "curve_underline_position",
    "curve_underline_height",
    "curve_small_caps_scale",
    "curve_overflow",
)


def _strip_blender_trs_fields(state: dict) -> dict:
    out = dict(state or {})
    out["has_viewport_edit"] = False
    for k in _BLENDER_TRS_KEYS:
        out.pop(k, None)
    return out



def sanitize_locale_spacing(maps: dict) -> int:
    """Zero absurd TMP spacing %% left by bad curve→RAM inverse captures."""
    if not maps:
        return 0
    n = 0
    for bname in ("el_by_hier", "el_by_name"):
        block = maps.get(bname) or {}
        for key, el in list(block.items()):
            d = _copy_el_dict(el)
            changed = False
            for fld, lim in (
                ("character_spacing", 50.0),
                ("word_spacing", 50.0),
                ("line_spacing", 100.0),
            ):
                try:
                    v = float(d.get(fld) or 0.0)
                except Exception:
                    continue
                if abs(v) > lim:
                    d[fld] = 0.0
                    changed = True
            if changed:
                block[key] = d
                n += 1
        maps[bname] = block
    return n


def strip_viewport_edits_in_maps(maps: dict) -> int:
    """Remove has_viewport_edit + Blender TRS from a maps dict (in place)."""
    if not maps:
        return 0
    n = 0
    for bname in ("el_by_hier", "el_by_name"):
        block = maps.get(bname) or {}
        for key in list(block.keys()):
            block[key] = _strip_blender_trs_fields(_copy_el_dict(block[key]))
            n += 1
        maps[bname] = block
    return n


def demote_mass_viewport_edits(kb) -> int:
    """Clear old capture bug: every element marked has_viewport_edit.

    That locked Blender XY from the previous language into RAM and made text
    boxes drift by hundreds of pixels on each locale switch.
    """
    if kb is None:
        return 0
    p = _ptr(kb)
    bucket = _BUFFERS.get(p) or {}
    n = 0
    for loc, maps in list(bucket.items()):
        els = []
        for bname in ("el_by_hier", "el_by_name"):
            for _k, el in (maps.get(bname) or {}).items():
                d = _copy_el_dict(el)
                els.append(d)
        if not els:
            continue
        marked = sum(1 for d in els if d.get("has_viewport_edit"))
        # Only a depsgraph echo flags virtually everything at once; hand edits
        # touch a few elements and must survive the next switch.
        if len(els) < 8 or marked < int(0.9 * len(els)):
            continue
        for bname in ("el_by_hier", "el_by_name"):
            block = maps.get(bname) or {}
            for key in list(block.keys()):
                block[key] = _strip_blender_trs_fields(_copy_el_dict(block[key]))
                n += 1
    return n


def capture_current(kb, root, locale: str) -> dict:
    """Snapshot viewport into locale RAM without poisoning stock layout.

    Text always updates. Blender TRS is kept as a viewport edit only if this
    locale already had `has_viewport_edit` (user moved something earlier via
    live sync). Otherwise Unity fields from the live `ksp_ui` are stored
    without locking XY to the previous language's object positions.
    """
    loc = (locale or "").lower()
    try:
        from .properties import capture_toc_titles
        capture_toc_titles(kb, loc)
    except Exception:
        pass
    prev = None
    try:
        raw = (_BUFFERS.get(_ptr(kb)) or {}).get(loc)
        if raw is not None:
            prev = {
                "el_by_hier": dict(raw.get("el_by_hier") or {}),
                "el_by_name": dict(raw.get("el_by_name") or {}),
                "text_by_hier": dict(raw.get("text_by_hier") or {}),
                "text_by_name": dict(raw.get("text_by_name") or {}),
            }
    except Exception:
        prev = None

    live = capture_text_map_from_viewport(root, locale=loc)

    def _strip_blender_trs(state: dict) -> dict:
        out = dict(state or {})
        out["has_viewport_edit"] = False
        for k in (
            "location",
            "rotation_euler",
            "scale",
            "text_boxes",
            "curve_size",
            "curve_shear",
            "curve_space_character",
            "curve_space_word",
            "curve_space_line",
            "curve_align_x",
            "curve_align_y",
            "curve_offset_x",
            "curve_offset_y",
            "curve_underline_position",
            "curve_underline_height",
            "curve_small_caps_scale",
            "curve_overflow",
        ):
            out.pop(k, None)
        return out

    def _merge_el(key: str, state: dict, bucket: str) -> dict:
        st = _copy_el_dict(state)
        base = {}
        if prev is not None:
            base = _copy_el_dict((prev.get(bucket) or {}).get(key))
        keep_edit = bool(base.get("has_viewport_edit")) or bool(st.get("has_viewport_edit"))
        if keep_edit:
            merged = dict(base)
            merged.update(st)
            merged["has_viewport_edit"] = True
            merged["user_overrides"] = _merge_override_dicts(
                base.get("user_overrides"), st.get("user_overrides"),
            )
            return _bake_user_overrides_into_el_state(merged)
        # Stock: keep disk/.lang metrics. Live curve often carries fit remnants
        # (space_character >> 1) that must NOT overwrite m_characterSpacing etc.
        merged = _strip_blender_trs_fields(dict(base)) if base else {}
        # Allow non-metric live refreshes only when base lacked the field
        clean = _strip_blender_trs(st)
        _METRIC = (
            "font_size",
            "character_spacing",
            "word_spacing",
            "line_spacing",
            "paragraph_spacing",
            "size_delta",
            "anchored_position",
            "pivot",
            "font_family",
            "text_alignment",
            "font_style",
            "local_rotation",
            "local_scale",
            "local_position_z",
            "margin",
            "enable_word_wrapping",
            "overflow_mode",
            "color",
        )
        _LAYOUT = frozenset({
            "size_delta",
            "anchored_position",
            "pivot",
            "anchor_min",
            "anchor_max",
            "offset_min",
            "offset_max",
            "local_rotation",
            "local_scale",
            "local_position_z",
        })
        for k, v in clean.items():
            if k in _LAYOUT and not keep_edit:
                continue
            if k in _METRIC and k in merged and merged[k] is not None:
                continue
            if k == "user_overrides":
                continue
            if v is not None:
                merged[k] = v
        merged["user_overrides"] = _merge_override_dicts(
            merged.get("user_overrides"), clean.get("user_overrides"),
        )
        if clean.get("content_size") and not merged.get("content_size"):
            merged["content_size"] = clean["content_size"]
        merged["has_viewport_edit"] = False
        # Hand colour / R / S live in user_overrides even without viewport_edit.
        return _bake_user_overrides_into_el_state(merged)

    maps = {
        "text_by_hier": {},
        "text_by_name": {},
        "el_by_hier": {},
        "el_by_name": {},
    }
    if prev is not None:
        maps["text_by_hier"] = dict(prev.get("text_by_hier") or {})
        maps["text_by_name"] = dict(prev.get("text_by_name") or {})

    def _prefer_text(old, new):
        """Don't let a plain FONT body wipe TMP/UI markup from RAM."""
        old = old or ""
        new = new or ""
        if not new:
            return old
        if not old:
            return new
        old_l = old.lower()
        new_l = new.lower()
        old_m = ("<color" in old_l) or ("<b>" in old_l) or ("<i>" in old_l)
        new_m = ("<color" in new_l) or ("<b>" in new_l) or ("<i>" in new_l)
        if old_m and not new_m:
            return old
        return new

    for k, tx in (live.get("text_by_hier") or {}).items():
        maps["text_by_hier"][k] = _prefer_text(maps["text_by_hier"].get(k), tx)
    for k, tx in (live.get("text_by_name") or {}).items():
        maps["text_by_name"][k] = _prefer_text(maps["text_by_name"].get(k), tx)
    for k, st in (live.get("el_by_hier") or {}).items():
        maps["el_by_hier"][k] = _merge_el(k, st, "el_by_hier")
    for k, st in (live.get("el_by_name") or {}).items():
        maps["el_by_name"][k] = _merge_el(k, st, "el_by_name")
    # Keep previous els not present in the live viewport (hidden / other page)
    if prev is not None:
        for k, st in (prev.get("el_by_hier") or {}).items():
            if k not in maps["el_by_hier"]:
                maps["el_by_hier"][k] = _copy_el_dict(st)
        for k, st in (prev.get("el_by_name") or {}).items():
            if k not in maps["el_by_name"]:
                maps["el_by_name"][k] = _copy_el_dict(st)
        for k, tx in (prev.get("text_by_hier") or {}).items():
            maps["text_by_hier"].setdefault(k, tx)
        for k, tx in (prev.get("text_by_name") or {}).items():
            maps["text_by_name"].setdefault(k, tx)

    store_maps(kb, locale, maps)
    try:
        apply_maps_to_ui_elements(kb, maps)
    except Exception:
        pass
    # Do NOT call flush here: huge Text rewrites on switch crash Blender.
    # Persistence is save_pre only.
    return maps


def coalesce_size_delta(primary, *fallbacks):
    """Keep locale size_delta unless width or height is degenerate (~0 px).

    Import lays out from the computed Unity rect (``crect``). Locale rebuild
    used to take raw ``m_SizeDelta``, which is often ``(w, 0)`` on stretched
    UI.Text — that dropped the content box and glued glyphs to pivot 0.5.
    """
    sd = [0.0, 0.0]
    try:
        if primary is not None and len(primary) >= 1:
            sd[0] = float(primary[0])
            if len(primary) > 1:
                sd[1] = float(primary[1])
    except Exception:
        pass
    for src in fallbacks:
        if src is None:
            continue
        try:
            w = float(src[0]) if len(src) > 0 else 0.0
            h = float(src[1]) if len(src) > 1 else 0.0
        except Exception:
            continue
        if abs(sd[0]) < 1.0 and abs(w) >= 1.0:
            sd[0] = w
        if abs(sd[1]) < 1.0 and abs(h) >= 1.0:
            sd[1] = h
        if abs(sd[0]) >= 1.0 and abs(sd[1]) >= 1.0:
            break
    return (sd[0], sd[1])


def content_size_of(obj):
    """Import Unity rect (px). Never the last language's rebuilt box."""
    if obj is None:
        return None
    for key in ("ksp_import_content_size", "ksp_content_size"):
        try:
            c = obj.get(key, None)
            if c is not None and len(c) >= 2:
                w, h = float(c[0]), float(c[1])
                if abs(w) >= 1.0 or abs(h) >= 1.0:
                    return (w, h)
        except Exception:
            pass
    return None


def import_content_size_of(obj):
    """Unity hole stamped at import — safe across languages."""
    if obj is None:
        return None
    try:
        c = obj.get("ksp_import_content_size", None)
        if c is not None and len(c) >= 2:
            w, h = float(c[0]), float(c[1])
            if abs(w) >= 1.0 or abs(h) >= 1.0:
                return (w, h)
    except Exception:
        pass
    return None


def stamp_content_size(obj, width_px, height_px) -> None:
    if obj is None:
        return
    try:
        w, h = float(width_px), float(height_px)
        if abs(w) < 1.0 and abs(h) < 1.0:
            return
        obj["ksp_content_size"] = (w, h)
    except Exception:
        pass


def stamp_import_content_size(obj, width_px, height_px) -> None:
    """Pin the computed Unity rect; locale rebuilds must not overwrite it."""
    stamp_content_size(obj, width_px, height_px)
    if obj is None:
        return
    try:
        w, h = float(width_px), float(height_px)
        if abs(w) < 1.0 and abs(h) < 1.0:
            return
        obj["ksp_import_content_size"] = (w, h)
    except Exception:
        pass


def estimate_live_content_size(obj, *, pixel_scale: float = 0.001):
    """Unity hole in px from import stamp, size_delta, or the live FONT box."""
    sz = import_content_size_of(obj)
    if sz is not None:
        return sz
    try:
        sd = tuple(obj.ksp_ui.size_delta or (0.0, 0.0))
        w = abs(float(sd[0])) if sd else 0.0
        h = abs(float(sd[1])) if len(sd) > 1 else 0.0
        if w > 1.0 and h > 1.0:
            return (w, h)
    except Exception:
        pass
    try:
        tb = obj.data.text_boxes[0]
        sx = float(pixel_scale) or 0.001
        w = abs(float(tb.width)) / sx
        pv = (0.5, 0.5)
        try:
            pv = tuple(obj.ksp_ui.pivot or (0.5, 0.5))
        except Exception:
            pass
        py = float(pv[1]) if len(pv) > 1 else 0.5
        denom = (1.0 - py) if (1.0 - py) > 1e-4 else max(py, 1e-4)
        top = float(tb.y)
        h = 0.0
        if abs(top) > 1e-8:
            est = abs(top) / (denom * sx)
            if 1.0 < est < 4000.0:
                h = est
        if w > 1.0 or h > 1.0:
            return (w if w > 1.0 else 0.0, h)
    except Exception:
        pass
    return None


def copy_import_content_size(dst, src) -> None:
    """Carry the import Unity hole onto a rebuilt object (not the live box)."""
    if dst is None or src is None:
        return
    sz = import_content_size_of(src)
    if sz is None:
        return
    try:
        dst["ksp_import_content_size"] = (float(sz[0]), float(sz[1]))
        dst["ksp_content_size"] = (float(sz[0]), float(sz[1]))
    except Exception:
        pass


def repair_flat_size_deltas(root) -> int:
    """Restore size_delta height flattened by bad Blender text_boxes captures.

    Prefers ui_elements row values, then the import ``ksp_content_size`` stamp,
    then refuses to leave height≈0 when the matching list item still has a
    real Unity height.
    """
    if root is None:
        return 0
    kb = None
    try:
        kb = root.ksp_bundle
    except Exception:
        return 0
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
            sd = tuple(ui.size_delta or (0.0, 0.0))
            if len(sd) < 2 or abs(float(sd[1])) > 1e-3:
                continue
        except Exception:
            continue
        # Find list row with same rect / name
        fixed = None
        try:
            rid = str(ui.rect_path_id or "")
            name = (ui.element_name or "").strip()
            for item in kb.ui_elements:
                if item.kind not in ("text", "image"):
                    continue
                try:
                    isd = tuple(item.size_delta or (0.0, 0.0))
                except Exception:
                    continue
                if len(isd) < 2 or abs(float(isd[1])) <= 1.0:
                    continue
                match = False
                if rid and str(item.rect_path_id or "") == rid:
                    match = True
                elif name and (item.name or "") == name:
                    same = 0
                    try:
                        same = sum(
                            1 for it in kb.ui_elements
                            if (it.name or "").strip() == name
                            and it.kind in ("text", "image")
                        )
                    except Exception:
                        same = 2
                    if same == 1:
                        match = True
                try:
                    if item.viewport_object == obj:
                        match = True
                except Exception:
                    pass
                if match:
                    fixed = (float(isd[0]) if abs(float(sd[0])) < 1e-3 else float(sd[0]), float(isd[1]))
                    break
        except Exception:
            fixed = None
        if fixed is None:
            cs = content_size_of(obj)
            if cs is not None and abs(float(cs[1])) > 1.0:
                try:
                    w0 = float(sd[0]) if abs(float(sd[0])) >= 1e-3 else float(cs[0])
                    fixed = (w0, float(cs[1]))
                except Exception:
                    fixed = None
        if fixed is None:
            continue
        try:
            ui.size_delta = fixed[:2]
            n += 1
        except Exception:
            pass
    return n


def merge_live_into_loc_el(live_state: dict, loc_el: Any, *, prefer_live_trs: bool = False) -> Any:
    """Merge disk/RAM loc_el with a live viewport snapshot.

    Default: ``loc_el`` wins for TRS / boxes (per-locale). Use
    ``prefer_live_trs=True`` only for same-locale refresh, never on switch.
    """
    base = _copy_el_dict(loc_el) if loc_el is not None else {}
    live = _copy_el_dict(live_state) if live_state else {}
    merged = dict(base)
    trs_keys = {
        "has_viewport_edit",
        "location",
        "rotation_euler",
        "scale",
        "local_rotation",
        "local_scale",
        "text_boxes",
        "character_spacing",
        "word_spacing",
        "line_spacing",
    }
    for k, v in live.items():
        if v is None:
            continue
        is_trs = k.startswith("curve_") or k in trs_keys
        if is_trs and not prefer_live_trs:
            if k not in merged or merged[k] is None:
                merged[k] = v
            continue
        if is_trs and prefer_live_trs:
            merged[k] = v
            continue
        if k not in merged or merged[k] is None:
            merged[k] = v
    if prefer_live_trs and live.get("has_viewport_edit"):
        merged["has_viewport_edit"] = True
    return el_as_namespace(merged)


# ---------------------------------------------------------------------------
# .blend persistence (survives close / other PC)
# ---------------------------------------------------------------------------

import json

_BLEND_VERSION = 2


def _sanitize_text_name(s: str) -> str:
    s = (s or "bundle").strip() or "bundle"
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:56]


def text_block_name_for(kb, root=None) -> str:
    try:
        if root is not None and getattr(root, "name", ""):
            return "ksp_locale_buffers__%s" % _sanitize_text_name(root.name)
    except Exception:
        pass
    try:
        bn = getattr(kb, "bundle_name", "") or ""
        if bn:
            return "ksp_locale_buffers__%s" % _sanitize_text_name(bn)
    except Exception:
        pass
    try:
        return "ksp_locale_buffers__%x" % (_ptr(kb) & 0xFFFFFFFF)
    except Exception:
        return "ksp_locale_buffers__anon"


def dump_all_maps(kb) -> dict:
    """Serializable snapshot of all locales for this bundle."""
    p = _ptr(kb)
    raw = _BUFFERS.get(p) or {}
    locales = {}
    for loc, maps in raw.items():
        entry = {
            "text_by_hier": dict(maps.get("text_by_hier") or {}),
            "text_by_name": dict(maps.get("text_by_name") or {}),
            "el_by_hier": {
                str(k): _copy_el_dict(v)
                for k, v in (maps.get("el_by_hier") or {}).items()
            },
            "el_by_name": {
                str(k): _copy_el_dict(v)
                for k, v in (maps.get("el_by_name") or {}).items()
            },
        }
        for key in _PRESENCE_KEYS:
            entry[key] = list(maps.get(key) or ())
        locales[str(loc)] = entry
    return {
        "version": _BLEND_VERSION,
        "prev_locale": get_prev_locale(kb),
        "locales": locales,
    }


def load_all_maps(kb, data: dict) -> int:
    """Hydrate RAM from a dump_all_maps() dict. Returns locale count."""
    if not data or not isinstance(data, dict):
        return 0
    locales = data.get("locales") or {}
    ver = int(data.get("version") or 1)
    n = 0
    for loc, maps in locales.items():
        if not loc or not isinstance(maps, dict):
            continue
        if ver < 2:
            # v1 mass-marked every capture as viewport edit → strip Blender TRS
            for bname in ("el_by_hier", "el_by_name"):
                block = dict(maps.get(bname) or {})
                for key, el in list(block.items()):
                    block[key] = _strip_blender_trs_fields(_copy_el_dict(el))
                maps[bname] = block
        store_maps(kb, loc, maps)
        n += 1
    prev = (data.get("prev_locale") or "").lower()
    if prev:
        set_prev_locale(kb, prev)
    return n


def flush_to_blend(kb, root=None, *, allow_new_ids: bool = True) -> bool:
    """Write current RAM buffers into a Text datablock (saved with .blend).

    During save_pre, pass allow_new_ids=False — creating Text IDs mid-save
    can hard-crash Blender. Prefer updating an existing Text or an ID prop.
    """
    import bpy

    if kb is None:
        return False
    try:
        if not getattr(kb, "is_ksp_bundle", False):
            return False
    except Exception:
        return False
    try:
        payload = dump_all_maps(kb)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return False
    tname = text_block_name_for(kb, root)
    wrote = False
    try:
        if tname in bpy.data.texts:
            block = bpy.data.texts[tname]
            block.clear()
            block.write(text)
            wrote = True
        elif allow_new_ids:
            block = bpy.data.texts.new(tname)
            block.write(text)
            wrote = True
    except Exception:
        wrote = False
    if not wrote:
        try:
            if root is not None:
                root["ksp_locale_buffers_json"] = text
                wrote = True
        except Exception:
            return False
    try:
        if wrote and (allow_new_ids or tname in bpy.data.texts):
            kb.locale_buffers_text = tname
        elif root is not None:
            try:
                if "ksp_locale_buffers_json" in root.keys():
                    kb.locale_buffers_text = ""
            except Exception:
                pass
    except Exception:
        pass
    try:
        limit = 100000 if not allow_new_ids else 250000
        kb.locale_buffers_json = text if len(text) < limit else ""
    except Exception:
        pass
    return True


def hydrate_from_blend(kb, root=None) -> int:
    """Restore RAM from Text datablock / JSON property. Returns locale count."""
    import bpy

    if kb is None:
        return 0
    raw = ""
    tname = ""
    try:
        tname = (getattr(kb, "locale_buffers_text", "") or "").strip()
    except Exception:
        tname = ""
    if not tname:
        tname = text_block_name_for(kb, root)
    try:
        if tname and tname in bpy.data.texts:
            raw = bpy.data.texts[tname].as_string()
    except Exception:
        raw = ""
    if not raw:
        try:
            raw = (getattr(kb, "locale_buffers_json", "") or "").strip()
        except Exception:
            raw = ""
    if not raw and root is not None:
        try:
            raw = str(root.get("ksp_locale_buffers_json", "") or "")
        except Exception:
            raw = ""
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except Exception:
        return 0
    return load_all_maps(kb, data)


def flush_all_bundles(scene=None, *, allow_new_ids: bool = True) -> int:
    """Capture active locale + flush every KSPedia root in the scene."""
    import bpy

    objects = list(getattr(bpy.data, "objects", []) or [])
    if not objects and scene is not None:
        objects = list(getattr(scene, "objects", []) or [])
    elif not objects:
        try:
            scene = scene or bpy.context.scene
            objects = list(getattr(scene, "objects", []) or [])
        except Exception:
            objects = []
    n = 0
    for obj in objects:
        try:
            kb = obj.ksp_bundle
            if not kb.is_ksp_bundle:
                continue
        except Exception:
            continue
        try:
            loc = (
                getattr(kb, "active_locale", "")
                or getattr(kb, "locale", "")
                or get_prev_locale(kb)
                or ""
            ).lower()
            if loc:
                capture_current(kb, obj, loc)
        except Exception:
            pass
        try:
            if flush_to_blend(kb, obj, allow_new_ids=allow_new_ids):
                n += 1
        except Exception:
            pass
    return n


def hydrate_all_bundles(scene=None) -> int:
    import bpy

    if scene is None:
        try:
            scene = bpy.context.scene
        except Exception:
            return 0
    n = 0
    for obj in list(getattr(scene, "objects", []) or []):
        try:
            kb = obj.ksp_bundle
            if not kb.is_ksp_bundle:
                continue
        except Exception:
            continue
        try:
            got = hydrate_from_blend(kb, obj)
            n += int(got or 0)
        except Exception:
            pass
        try:
            src = getattr(kb, "source_path", "") or ""
            skip = (
                getattr(kb, "active_locale", "")
                or getattr(kb, "locale", "")
                or ""
            )
            if src:
                schedule_preload_sibling_locales(kb, src, skip_locale=skip)
        except Exception:
            pass
        try:
            demote_mass_viewport_edits(kb)
        except Exception:
            pass
        try:
            repair_flat_size_deltas(obj)
        except Exception:
            pass
    return n