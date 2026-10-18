# vim:ts=4:et
# <pep8 compliant>
"""Discover sibling KSPedia locale bundles and live-switch texts."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

_LOCALE_FILE_RE = re.compile(
    r"^(?P<base>.+?)_(?P<locale>[a-z]{2}(?:-[a-z]{2})?)\.(?P<ext>ksp|lang)$",
    re.I,
)

# #region agent log
_DBG_N = [0]
_DBG_RUN = ["post-fix"]


def _dbg_path():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "debug-e00182.log",
    )


def _dbg(hyp, msg, data=None, limit=80):
    try:
        if _DBG_N[0] >= limit:
            return
        _DBG_N[0] += 1
        import json
        import time
        rec = {
            "sessionId": "e00182",
            "runId": _DBG_RUN[0],
            "hypothesisId": hyp,
            "location": "locale_switch.py",
            "message": msg,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(_dbg_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _dbg_reset(tag=""):
    _DBG_N[0] = 0
    _dbg("INIT", "run start", {"tag": tag})


def _dbg_box(curve):
    try:
        tb = curve.text_boxes[0]
        return [round(float(tb.x), 5), round(float(tb.y), 5),
                round(float(tb.width), 5), round(float(tb.height), 5)]
    except Exception:
        return []


def _dbg_curve(obj):
    try:
        if getattr(obj, "type", "") != "FONT" or obj.data is None:
            return {}
        c = obj.data
        return {
            "size": round(float(c.size), 6),
            "space_char": round(float(c.space_character), 5),
            "space_word": round(float(c.space_word), 5),
            "space_line": round(float(c.space_line), 5),
            "shear": round(float(c.shear), 4),
            "font": str(getattr(getattr(c, "font", None), "name", "") or ""),
            "align": "%s/%s" % (c.align_x, c.align_y),
            "xy": [
                round(float(obj.location.x), 6),
                round(float(obj.location.y), 6),
            ],
            "nbox": len(getattr(c, "text_boxes", []) or []),
            "box": _dbg_box(c),
        }
    except Exception:
        return {}
# #endregion
# Some .lang page roots: "Configuration ES", "Corridors_ES".
_ROOT_LOCALE_SUFFIX_RE = re.compile(
    r"[\s_]+([a-z]{2}(?:-[a-z]{2})?)$",
    re.I,
)


def normalize_locale_tag(tag: str, available=None) -> str:
    """Normalize locale tags for string compare: en / EN / en_us -> en-us.

    If ``available`` is a list/csv of known tags, prefer the best prefix match
    (``en`` -> ``en-us`` when present) instead of Blender Enum indices.
    """
    raw = (tag or "").strip().lower().replace("_", "-")
    if not raw:
        return ""
    avail = []
    if isinstance(available, str):
        avail = [x.strip().lower() for x in available.split(",") if x.strip()]
    elif available:
        avail = [str(x).strip().lower() for x in available if str(x).strip()]
    if raw in avail:
        return raw
    # Exact language-only match: en -> en-us / en-gb
    if len(raw) == 2 and avail:
        hits = [a for a in avail if a == raw or a.startswith(raw + "-")]
        if len(hits) == 1:
            return hits[0]
        if raw + "-us" in hits:
            return raw + "-us"
        if hits:
            return sorted(hits)[0]
    if len(raw) == 2:
        # Common defaults when list unknown
        return {"en": "en-us", "de": "de-de", "fr": "fr-fr", "es": "es-es",
                "pt": "pt-br", "zh": "zh-cn", "ja": "ja", "ko": "ko",
                "ru": "ru", "it": "it-it", "pl": "pl"}.get(raw, raw)
    if avail:
        for a in avail:
            if a.startswith(raw) or raw.startswith(a):
                return a
    return raw


def pin_layout_xy(obj, props=None) -> None:
    """Stamp the import layout baseline for later locale switches.

    The placed position carries accumulated import calibration (block nudges,
    ascender snap, fit results), so a switch only applies the *difference*
    between this locale's anchoredPosition and the one recorded here.
    """
    if obj is None:
        return
    try:
        obj["ksp_layout_xy"] = (float(obj.location.x), float(obj.location.y))
    except Exception:
        pass
    try:
        src = props if props else obj.ksp_ui
        ap = src["anchored_position"] if props else src.anchored_position
        obj["ksp_layout_ap"] = (float(ap[0]), float(ap[1]))
    except Exception:
        pass
    # Curve metrics as built (profile muls + fit already applied), so a capture
    # can tell a real user tweak from the builder's own calibration.
    try:
        if getattr(obj, "type", "") == "FONT" and obj.data is not None:
            c = obj.data
            obj["ksp_layout_curve"] = (
                float(c.size),
                float(c.space_character),
                float(c.space_word),
                float(c.space_line),
            )
    except Exception:
        pass
    try:
        obj["ksp_layout_rot"] = tuple(float(x) for x in obj.rotation_euler[:3])
        obj["ksp_layout_scale"] = tuple(float(x) for x in obj.scale[:3])
    except Exception:
        pass
    try:
        ps = page_space_xy(obj)
        if ps is not None:
            obj["ksp_page_xy"] = (float(ps[0]), float(ps[1]))
    except Exception:
        pass


def stamp_applied_xy(obj) -> None:
    """Baseline pose after import pin or stock locale AP apply.

    Live sync writes anchoredPosition so expected_locale_location already
    matches a G-move; Refresh / locale / page rebuild must compare against
    this stamp, not against live AP.
    """
    if obj is None:
        return
    try:
        obj["ksp_applied_xy"] = (float(obj.location.x), float(obj.location.y))
    except Exception:
        pass


def pin_all_layout_xy(root) -> int:
    n = 0
    if root is None:
        return 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    try:
        from . import locale_buffers as _lb
    except Exception:
        _lb = None
    for obj in objs:
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
        except Exception:
            continue
        pin_layout_xy(obj)
        if _lb is not None:
            # Import build is a baseline too, so a colour or font picked
            # before the first language switch is still recognised as a tweak.
            _lb.pin_build_state(obj)
        try:
            if obj.ksp_ui.kind == "text":
                loc = ""
                if root is not None:
                    loc = (
                        getattr(root.ksp_bundle, "active_locale", "")
                        or getattr(root.ksp_bundle, "locale", "")
                        or "en-us"
                    )
                obj["ksp_locale_applied"] = str(loc or "en-us").lower()
        except Exception:
            pass
        n += 1
    return n


# Filled for the duration of a locale apply so every box can add Unity-parent
# AP deltas after Outliner un-nest (children no longer follow a Blender parent).
_LAYOUT_APPLY_CTX = {
    "maps": None,
    "rect_index": None,
    "kb": None,
}


def _stamp_parent_rects(root, kb=None) -> None:
    """Copy Unity parent rect ids onto objects (needed after un-nest)."""
    by_rect = {}
    if kb is not None:
        try:
            for item in kb.ui_elements:
                rid = str(item.rect_path_id or "")
                if rid:
                    by_rect[rid] = str(item.parent_rect_path_id or "")
        except Exception:
            by_rect = {}
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root] if root is not None else []
    for obj in objs:
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
            rid = str(ui.rect_path_id or "")
            pid = str(getattr(ui, "parent_rect_path_id", "") or "")
            if not pid:
                pid = str(obj.get("ksp_parent_rect", "") or "")
            if not pid and rid:
                pid = by_rect.get(rid, "")
            if pid and pid != "0":
                try:
                    ui.parent_rect_path_id = pid
                except Exception:
                    pass
                obj["ksp_parent_rect"] = pid
        except Exception:
            continue


def _set_layout_apply_ctx(root, maps, kb=None) -> None:
    _LAYOUT_APPLY_CTX["maps"] = maps
    _LAYOUT_APPLY_CTX["kb"] = kb
    try:
        _stamp_parent_rects(root, kb)
    except Exception:
        pass
    try:
        _LAYOUT_APPLY_CTX["rect_index"] = _index_rect_objects(root)
    except Exception:
        _LAYOUT_APPLY_CTX["rect_index"] = {}


def _clear_layout_apply_ctx() -> None:
    _LAYOUT_APPLY_CTX["maps"] = None
    _LAYOUT_APPLY_CTX["rect_index"] = None
    _LAYOUT_APPLY_CTX["kb"] = None


def _index_rect_objects(root) -> dict:
    idx = {}
    if root is None:
        return idx
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            rid = str(obj.ksp_ui.rect_path_id or "")
        except Exception:
            rid = ""
        if rid:
            idx[rid] = obj
    return idx


def _blender_ancestor_set(obj) -> set:
    out = set()
    cur = None
    try:
        cur = obj.parent
    except Exception:
        return out
    seen = set()
    while cur is not None:
        try:
            ptr = cur.as_pointer()
        except Exception:
            ptr = id(cur)
        if ptr in seen:
            break
        seen.add(ptr)
        out.add(cur)
        try:
            cur = cur.parent
        except Exception:
            break
    return out


def _parent_rect_id_of(obj) -> str:
    if obj is None:
        return ""
    for getter in (
        lambda: str(getattr(obj.ksp_ui, "parent_rect_path_id", "") or ""),
        lambda: str(obj.get("ksp_parent_rect", "") or ""),
    ):
        try:
            pid = getter()
        except Exception:
            pid = ""
        if pid and pid != "0":
            return pid
    kb = _LAYOUT_APPLY_CTX.get("kb")
    if kb is None:
        return ""
    try:
        rid = str(obj.ksp_ui.rect_path_id or "")
        if not rid:
            return ""
        for item in kb.ui_elements:
            if str(item.rect_path_id or "") == rid:
                pid = str(item.parent_rect_path_id or "")
                return pid if pid and pid != "0" else ""
    except Exception:
        return ""
    return ""


def _ap2(ap):
    if ap is None:
        return None
    try:
        if len(ap) < 2:
            return None
        return (float(ap[0]), float(ap[1]))
    except Exception:
        return None


def _locale_ap_by_rect(maps) -> dict:
    out = {}
    if not maps:
        return out
    for bname in ("el_by_hier", "el_by_name"):
        block = maps.get(bname) or {}
        for el in block.values():
            try:
                if isinstance(el, dict):
                    rid = str(el.get("rect_path_id") or "")
                    ap = el.get("anchored_position")
                else:
                    rid = str(getattr(el, "rect_path_id", "") or "")
                    ap = getattr(el, "anchored_position", None)
            except Exception:
                continue
            ap2 = _ap2(ap)
            if rid and ap2 is not None:
                out[rid] = ap2
    return out


def _ap_delta_bu(ap, ap0, sx):
    a = _ap2(ap)
    b = _ap2(ap0)
    if a is None or b is None:
        return 0.0, 0.0
    s = float(sx) or 0.001
    return (a[0] - b[0]) * s, (a[1] - b[1]) * s


def layout_shift_parts(obj, anchored_position, pixel_scale=0.001):
    """Own AP delta in Blender units (import pin is already page-space).

    After un-nest, ``ksp_layout_xy`` already includes the former parent's
    import pose. Adding ancestor AP deltas a second time parked ConfB /
    ConfSubheader at the old parent center (and the page origin).
    Nested objects still follow a live Blender parent, so they must not
    get ancestor deltas either.
    """
    sx = float(pixel_scale) or 0.001
    own_dx = own_dy = 0.0
    if obj is None:
        return own_dx, own_dy, 0.0, 0.0
    try:
        ap0 = obj.get("ksp_layout_ap", None)
    except Exception:
        ap0 = None
    own_dx, own_dy = _ap_delta_bu(anchored_position, ap0, sx)
    return own_dx, own_dy, 0.0, 0.0


def expected_locale_location(obj, pixel_scale=0.001):
    """Import pin plus the current locale's composed AP shift, or None."""
    if obj is None:
        return None
    try:
        xy = obj.get("ksp_layout_xy", None)
    except Exception:
        xy = None
    if xy is None or len(xy) < 2:
        return None
    ap = None
    try:
        ap = tuple(obj.ksp_ui.anchored_position or (0.0, 0.0))
    except Exception:
        ap = None
    own_dx, own_dy, anc_dx, anc_dy = layout_shift_parts(
        obj, ap, pixel_scale=pixel_scale
    )
    try:
        z = float(obj.location.z)
    except Exception:
        z = 0.0
    return (
        float(xy[0]) + own_dx + anc_dx,
        float(xy[1]) + own_dy + anc_dy,
        z,
    )


def apply_locale_layout_xy(obj, anchored_position, pixel_scale=0.001) -> bool:
    """Place a box at import XY shifted by this locale's anchoredPosition.

    In ``compute_rect`` the pivot position is ``anchoredPosition`` plus terms
    that only depend on the parent rect, anchors and pivot (sizeDelta cancels
    out), all of which are locale-invariant. So the whole per-locale layout
    difference is the anchoredPosition delta, measured against the import
    baseline — never against the previous language, which is what used to
    accumulate hundreds of pixels of drift.

    Un-nested Outliner objects keep the import pin in page space; only this
    element's anchoredPosition delta is applied (never the former parent).
    """
    if obj is None:
        return False
    try:
        xy = obj.get("ksp_layout_xy", None)
    except Exception:
        return False
    if xy is None or len(xy) < 2:
        return False
    own_dx, own_dy, anc_dx, anc_dy = layout_shift_parts(
        obj, anchored_position, pixel_scale=pixel_scale
    )
    dx = own_dx + anc_dx
    dy = own_dy + anc_dy
    try:
        obj.location = (float(xy[0]) + dx, float(xy[1]) + dy,
                        float(obj.location.z))
        stamp_applied_xy(obj)
        # #region agent log
        _dbg("B", "locale layout xy", {
            "obj": obj.name,
            "pin": [round(float(xy[0]), 6), round(float(xy[1]), 6)],
            "ap_base": list(obj.get("ksp_layout_ap", ()) or ()),
            "ap_locale": list(anchored_position or ()),
            "shift_px": [round(dx * 1000.0, 2), round(dy * 1000.0, 2)],
            "anc_px": [round(anc_dx * 1000.0, 2), round(anc_dy * 1000.0, 2)],
        })
        # #endregion
        return True
    except Exception:
        return False


def _is_image_locked_overlay(props) -> bool:
    """Hole / space-pad texts sit on shared artwork (images don't move).

    Locale strings may drop the import hole (DE uses <color> instead of
    spaces). Prefer the import stamp; fall back to content heuristics.
    """
    if not props:
        return False
    try:
        if props.get("artwork_overlay"):
            return True
    except Exception:
        pass
    try:
        from .viewport import is_artwork_overlay
        text = ""
        try:
            text = str(props.get("text") or "")
        except Exception:
            text = ""
        return bool(is_artwork_overlay(text))
    except Exception:
        return False


def _obj_is_user_added(obj) -> bool:
    try:
        return bool(obj.get("ksp_user_added"))
    except Exception:
        return False


def _pose_locked_by_user(obj) -> bool:
    """True when locale AP / overlay pin must not move this object.

    LOCAL-scope user copies keep their G-move (USER-LATEST-008 / 009).
    ALL-scope copies are shared live objects: silent viewport G/R/S/colour
    is per ``active_locale``, so another language must apply its own maps.
    Stock G-moves stay in that language's park.
    """
    if not _obj_is_user_added(obj):
        return False
    if _user_added_spans_locales(obj):
        return False
    return True


def _user_added_spans_locales(obj) -> bool:
    """True when Duplicate was scoped to more than one .lang."""
    try:
        shipped = str(obj.get("ksp_shipped_locales") or "").strip()
    except Exception:
        shipped = ""
    if not shipped:
        return False
    allowed = {x.strip().lower() for x in shipped.split(",") if x.strip()}
    return len(allowed) > 1


def _obj_home_locale(obj, fallback: str = "") -> str:
    try:
        shipped = str(obj.get("ksp_shipped_locales") or "").strip()
    except Exception:
        shipped = ""
    if shipped:
        first = shipped.split(",")[0].strip().lower()
        if first:
            return first
    try:
        applied = str(obj.get("ksp_locale_applied") or "").strip().lower()
    except Exception:
        applied = ""
    if applied:
        return applied
    return (fallback or "").strip().lower()


def stamp_live_user_moves(root, *, pixel_scale: float = 0.001) -> int:
    """Stamp G-move flags on user-added copies before a locale apply.

    Stock boxes are not stamped — that froze EN G-move onto DE/FR.
    """
    if root is None:
        return 0
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            if _is_parked_locale_obj(obj):
                continue
            if not _obj_is_user_added(obj):
                continue
            # ALL-scope live objects: pose lives in each locale's maps.
            if _user_added_spans_locales(obj):
                continue
            if not _is_locale_text_root(obj):
                continue
            obj["ksp_has_viewport_edit"] = True
            n += 1
        except Exception:
            continue
    return n


def _copy_user_added_pose_marks(src, dest) -> None:
    """Keep duplicate identity across FONT rebuilds.

    Do not copy ``ksp_has_viewport_edit`` / ``ksp_applied_xy`` — those are
    the active language's mouse pose. Cross-locale rebuilds must use the
    incoming locale's maps (same-locale rebuild copies them separately).
    """
    if src is None or dest is None:
        return
    for key in (
        "ksp_user_added",
        "ksp_shipped_locales",
        "ksp_forgotten_locales",
        "ksp_export_go_name",
    ):
        try:
            val = src.get(key)
        except Exception:
            val = None
        if not val:
            continue
        try:
            dest[key] = val
        except Exception:
            pass


def apply_locale_position(obj, props, loc_el, *, pixel_scale=0.001) -> bool:
    """Place text from the import pin + this locale's anchoredPosition delta.

    With Unity nesting kept in the Outliner, each object's location is local
    to its parent — only the *own* AP delta is applied (parents move children).
    Image-locked overlays stay on the import pin (shared artwork).

    User-added duplicates live in page space after flatten. Applying the
    stock twin's locale AP (header-local) snaps a G-moved copy back onto
    the original (USER-LATEST-008 / 009 dup+G+locale).
    """
    if obj is None:
        return False
    # Duplicates and G-moved boxes (including ConfT2 holes) keep live XY.
    # Overlay pin used to run first and snap copies onto the original.
    if _pose_locked_by_user(obj):
        return True
    # ALT / showModCategory: pin first — never honour a stale has_viewport_edit
    # from another language (that stacked overlays after locale switch).
    if _is_image_locked_overlay(props):
        return apply_locale_layout_xy(obj, None, pixel_scale=pixel_scale)
    if props and props.get("has_viewport_edit"):
        cap = None
        try:
            if isinstance(loc_el, dict):
                cap = loc_el.get("location")
            elif loc_el is not None:
                cap = getattr(loc_el, "location", None)
        except Exception:
            cap = None
        if cap is not None and len(cap) >= 2:
            try:
                z = float(cap[2]) if len(cap) > 2 else float(obj.location.z)
                obj.location = (float(cap[0]), float(cap[1]), z)
                # #region agent log
                _dbg("G", "user viewport edit restored", {
                    "obj": obj.name,
                    "location": [round(float(cap[0]), 6), round(float(cap[1]), 6)],
                    "pin": list(obj.get("ksp_layout_xy", ()) or ()),
                })
                # #endregion
                return True
            except Exception:
                pass
    return apply_locale_layout_xy(
        obj, props.get("anchored_position") if props else None,
        pixel_scale=pixel_scale,
    )


def normalize_hierarchy_key(hier: str) -> str:
    """Strip per-locale page-root suffixes so EN/ES/DE keys align."""
    parts = [p for p in (hier or "").split("/") if p]
    if not parts:
        return ""
    root = parts[0]
    m = _ROOT_LOCALE_SUFFIX_RE.search(root)
    if m:
        tag = m.group(1)
        if len(tag) <= 5:
            stripped = root[: m.start()].rstrip("_").rstrip()
            if stripped:
                parts[0] = stripped
    return "/".join(parts)


_HIER_DUP_MARK_RE = re.compile(r"#\d+$")


def hier_dup_match_key(hier: str) -> str:
    """Drop Unity same-name ``#N`` marks on every path segment.

    EN ``.ksp`` has one TitleScreen tree (``…/Header``). Sibling ``.lang``
    files often ship a second copy of the same GO names, so keys become
    ``…#0/Header`` / ``…#1/Header``. Exact lookup then misses, parks the
    live Header, and ``_hide_tree`` takes the nested Subheader with it
    (USER-LATEST-009).
    """
    parts = []
    for p in normalize_hierarchy_key(hier).split("/"):
        if not p:
            continue
        parts.append(_HIER_DUP_MARK_RE.sub("", p))
    return "/".join(parts)


def _fuzzy_hier_lookup(hier, text_by_hier, el_by_hier):
    """Match a viewport hierarchy key to .lang maps, ignoring ``#N`` marks."""
    want = hier_dup_match_key(hier or "")
    if not want:
        return None, None
    hits_t = []
    hits_e = []
    for k, tx in (text_by_hier or {}).items():
        if hier_dup_match_key(k) == want:
            hits_t.append(tx)
    for k, el in (el_by_hier or {}).items():
        if hier_dup_match_key(k) == want:
            hits_e.append(el)
    text = None
    nonempty = [t for t in hits_t if str(t or "").strip()]
    if nonempty:
        text = nonempty[0]
    elif hits_t:
        text = hits_t[0]
    loc_el = None
    if hits_e:
        if text is not None:
            for el in hits_e:
                got = _el_get(el, "text", None)
                if got is None:
                    try:
                        got = getattr(el, "text", None)
                    except Exception:
                        got = None
                if str(got or "").strip() == str(text or "").strip():
                    loc_el = el
                    break
        if loc_el is None:
            loc_el = hits_e[0]
    return text, loc_el


def discover_locale_variants(filepath: str) -> List[Tuple[str, str]]:
    """Return sorted (locale, abspath) pairs next to filepath.

    Unsuffixed ``Base.ksp`` (no ``_xx-xx``) is the English/default pack and is
    registered as ``en-us`` so the Locale enum is not only de/fr/… with
    index-0 wrongly selected as German.
    """
    if not filepath:
        return []
    folder = os.path.dirname(os.path.abspath(filepath))
    stem = os.path.splitext(os.path.basename(filepath))[0]
    m = _LOCALE_FILE_RE.match(os.path.basename(filepath))
    base = m.group("base") if m else stem
    base_l = base.lower()
    found = {}
    # English base bundle (no locale suffix)
    for ext in ("ksp", "lang"):
        base_path = os.path.join(folder, "%s.%s" % (base, ext))
        if os.path.isfile(base_path):
            # Prefer .ksp over .lang for en-us
            prev = found.get("en-us")
            if prev is None or (ext == "ksp" and prev.lower().endswith(".lang")):
                found["en-us"] = base_path
            break
    try:
        names = os.listdir(folder)
    except Exception:
        return sorted(found.items(), key=lambda kv: kv[0])
    for name in names:
        mm = _LOCALE_FILE_RE.match(name)
        if not mm:
            continue
        if mm.group("base").lower() != base_l:
            continue
        loc = mm.group("locale").lower()
        ext = mm.group("ext").lower()
        path = os.path.join(folder, name)
        prev = found.get(loc)
        if prev is None:
            found[loc] = path
        elif ext == "ksp" and prev.lower().endswith(".lang"):
            found[loc] = path
    return sorted(found.items(), key=lambda kv: kv[0])


def order_locales(locales, preferred: str = "") -> List[str]:
    """Alphabetical locale list (stable Enum indices — do not put preferred first).

    Blender dynamic EnumProperties are index-backed: reordering items when
    ``locale`` changes makes the selected index point at a different language
    (e.g. pick fr-fr → UI shows it-it). Preferred is applied only by setting
    ``active_locale`` to the identifier string, not by reshuffling items.
    """
    locs = []
    seen = set()
    for loc in locales or []:
        L = (loc or "").strip().lower()
        if not L or L in seen:
            continue
        seen.add(L)
        locs.append(L)
    locs.sort()
    return locs


def locales_csv(filepath: str, preferred: str = "") -> str:
    locs = [loc for loc, _ in discover_locale_variants(filepath)]
    return ",".join(order_locales(locs, preferred))


def path_for_locale(filepath: str, locale: str) -> str:
    loc = (locale or "").strip().lower()
    if not loc:
        return filepath or ""
    for L, path in discover_locale_variants(filepath):
        if L == loc:
            return path
    if not filepath:
        return ""
    folder = os.path.dirname(os.path.abspath(filepath))
    m = _LOCALE_FILE_RE.match(os.path.basename(filepath))
    base = m.group("base") if m else os.path.splitext(os.path.basename(filepath))[0]
    for ext in ("ksp", "lang"):
        cand = os.path.join(folder, "%s_%s.%s" % (base, loc, ext))
        if os.path.isfile(cand):
            return cand
    return filepath


def hierarchy_key_for_element(bundle, el) -> str:
    """Stable cross-locale key: Unity GO name chain (path IDs remapped per .lang).

    Same-named siblings (e.g. two "Craft Pitches" under one parent) get a
    ``#N`` suffix from Unity m_Children order so locale maps and viewport
    purge do not collapse them into one box.
    """
    from collections import defaultdict

    by_rect = {}
    kids = defaultdict(list)
    for e in getattr(bundle, "ui_elements", None) or []:
        try:
            rid = int(getattr(e, "rect_path_id", 0) or 0)
        except Exception:
            continue
        if rid:
            by_rect[rid] = e
        try:
            prid = int(getattr(e, "parent_rect_path_id", 0) or 0)
        except Exception:
            prid = 0
        kids[prid].append(e)
    for prid, group in list(kids.items()):
        group.sort(
            key=lambda e: (
                int(getattr(e, "sibling_index", 10**9) or 10**9),
                int(getattr(e, "rect_path_id", 0) or 0),
            )
        )

    def _node_label(cur) -> str:
        name = (getattr(cur, "name", "") or "").strip()
        if not name:
            return ""
        try:
            prid = int(getattr(cur, "parent_rect_path_id", 0) or 0)
            rid = int(getattr(cur, "rect_path_id", 0) or 0)
        except Exception:
            return name
        same = [
            s
            for s in kids.get(prid, [])
            if (getattr(s, "name", "") or "").strip() == name
        ]
        if len(same) <= 1:
            return name
        for i, s in enumerate(same):
            try:
                if int(getattr(s, "rect_path_id", 0) or 0) == rid:
                    return "%s#%d" % (name, i)
            except Exception:
                continue
        return name

    parts = []
    cur = el
    seen = set()
    for _ in range(40):
        if cur is None:
            break
        try:
            rid = int(getattr(cur, "rect_path_id", 0) or 0)
        except Exception:
            rid = 0
        if rid:
            if rid in seen:
                break
            seen.add(rid)
        label = _node_label(cur)
        if label:
            parts.append(label)
        try:
            prid = int(getattr(cur, "parent_rect_path_id", 0) or 0)
        except Exception:
            prid = 0
        if not prid:
            break
        cur = by_rect.get(prid)
    return normalize_hierarchy_key("/".join(reversed(parts)))


def _ui_element_unity_name(item) -> str:
    """Unity GameObject name as stored on the UI Elements row (no list suffix)."""
    raw = (getattr(item, "name", "") or "").strip()
    try:
        from .locale_buffers import shipped_go_display_name
        return shipped_go_display_name(raw) or raw
    except Exception:
        return raw


def _hierarchy_leaf_dup_index(kb, item) -> Optional[int]:
    """0-based same-name sibling index from ``ksp_hierarchy`` / hierarchy key.

    Hierarchy leaves use ``Name#0`` (Unity m_Children order). Returns ``None``
    when the leaf has no ``#N`` (unique under its parent).
    """
    name = _ui_element_unity_name(item)
    if not name:
        return None
    hier = ""
    vo = getattr(item, "viewport_object", None)
    if vo is not None:
        try:
            hier = normalize_hierarchy_key(
                str(vo.get("ksp_hierarchy") or "").strip()
            )
        except Exception:
            hier = ""
    if not hier:
        try:
            hier = hierarchy_key_for_element(kb, item) or ""
        except Exception:
            hier = ""
    if not hier:
        return None
    leaf = hier.rstrip("/").split("/")[-1]
    if "#" not in leaf:
        return None
    base, _, num = leaf.rpartition("#")
    if base != name:
        return None
    try:
        return int(num)
    except (TypeError, ValueError):
        return None


def _ui_element_same_name_items(kb, name: str):
    name = (name or "").strip()
    out = []
    for e in getattr(kb, "ui_elements", None) or []:
        if _ui_element_unity_name(e) == name:
            out.append(e)
    return out


def _ui_element_match(a, b) -> bool:
    if a is b or a == b:
        return True
    try:
        for attr in ("mb_path_id", "rect_path_id", "go_path_id"):
            av = str(getattr(a, attr, "") or "").strip()
            bv = str(getattr(b, attr, "") or "").strip()
            if av and bv and av == bv and av not in ("0", ""):
                return True
    except Exception:
        pass
    return False


def ui_element_list_label(kb, item) -> str:
    """Display label for UI Elements rows / dialogs.

    Unique Unity names stay unchanged. Duplicates get a stable 1-based suffix
    (``Craft Pitches #1``) derived from hierarchy ``Name#0`` when present.
    Does not mutate ``item.name`` or ``ksp_ui.element_name``.
    """
    name = _ui_element_unity_name(item) or "(unnamed)"
    same = _ui_element_same_name_items(kb, name)
    if len(same) <= 1:
        return name

    def _sort_key(e):
        hi = _hierarchy_leaf_dup_index(kb, e)
        if hi is None:
            hi = 10**9
        try:
            prid = int(getattr(e, "parent_rect_path_id", 0) or 0)
        except Exception:
            prid = 0
        try:
            rid = int(getattr(e, "rect_path_id", 0) or 0)
        except Exception:
            rid = 0
        try:
            mb = int(getattr(e, "mb_path_id", 0) or 0)
        except Exception:
            mb = 0
        return (hi, prid, rid, mb)

    ordered = sorted(same, key=_sort_key)
    for i, e in enumerate(ordered):
        if _ui_element_match(e, item):
            return "%s #%d" % (name, i + 1)
    return "%s #1" % name


def ui_element_list_suffix(kb, item) -> str:
    """`` #N`` for duplicate rows, else empty (display-only next to ``item.name``)."""
    name = _ui_element_unity_name(item) or "(unnamed)"
    label = ui_element_list_label(kb, item)
    if label == name or not label.startswith(name):
        return ""
    return label[len(name):]


_PRESENCE_KINDS = ("text", "image")


def locale_maps_from_bundle(bundle) -> dict:
    """Maps for live locale switch.

    Prefer hierarchy keys — duplicate names (Header/Subheader on every page)
    collide if keyed only by element name. Unique names stay as fallback.

    The ``present_*`` sets record what this .lang actually ships: translations
    routinely drop whole sentences, and without them a missing box is
    indistinguishable from one we simply failed to match.
    """
    text_by_hier: Dict[str, str] = {}
    el_by_hier: Dict[str, object] = {}
    text_by_name: Dict[str, str] = {}
    el_by_name: Dict[str, object] = {}
    name_counts: Dict[str, int] = {}
    elements = [
        e
        for e in (getattr(bundle, "ui_elements", None) or [])
        if getattr(e, "kind", "") in _PRESENCE_KINDS
    ]
    for el in elements:
        name = (getattr(el, "name", "") or "").strip()
        if name:
            name_counts[name] = name_counts.get(name, 0) + 1
    present_hier = set()
    present_names = set()
    present_names_all = set()
    present_kinds = set()
    present_mb = set()
    for el in elements:
        kind = getattr(el, "kind", "") or ""
        name = (getattr(el, "name", "") or "").strip()
        text = getattr(el, "text", "") or ""
        hier = hierarchy_key_for_element(bundle, el)
        unique = bool(name) and name_counts.get(name, 0) == 1
        present_kinds.add(kind)
        if name:
            present_names_all.add(name)
        try:
            mb = str(int(getattr(el, "mb_path_id", 0) or 0))
        except Exception:
            mb = ""
        if mb and mb != "0":
            present_mb.add(mb)
        if hier:
            present_hier.add(hier)
            el_by_hier[hier] = el
            if kind == "text":
                text_by_hier[hier] = text
        if unique:
            present_names.add(name)
            el_by_name[name] = el
            if kind == "text":
                text_by_name[name] = text
    return {
        "text_by_hier": text_by_hier,
        "el_by_hier": el_by_hier,
        "text_by_name": text_by_name,
        "el_by_name": el_by_name,
        "present_hier": sorted(present_hier),
        "present_names": sorted(present_names),
        "present_names_all": sorted(present_names_all),
        "present_kinds": sorted(present_kinds),
        "present_mb": sorted(present_mb),
    }


def text_map_from_bundle(bundle) -> Dict[str, str]:
    """Backward-compatible name→text (unique names only). Prefer locale_maps_from_bundle."""
    return dict(locale_maps_from_bundle(bundle)["text_by_name"])


def element_map_from_bundle(bundle) -> Dict[str, object]:
    """name → UI element for unique names only. Prefer locale_maps_from_bundle."""
    return dict(locale_maps_from_bundle(bundle)["el_by_name"])


def _obj_hierarchy_key(obj) -> str:
    try:
        stamped = normalize_hierarchy_key((obj.get("ksp_hierarchy") or "").strip())
        if stamped:
            return stamped
    except Exception:
        pass
    return _hierarchy_from_parents(obj)


def _hierarchy_from_parents(obj) -> str:
    """Rebuild GO-name chain when ``ksp_hierarchy`` was never stamped.

    Nested TitleScreen Subheader often has no hier stamp; without it
    ``.lang`` duplicate trees (#0/#1) cannot fuzzy-match and the child
    parks with the Header (USER-LATEST-009).
    """
    if obj is None:
        return ""
    parts = []
    cur = obj
    for _ in range(40):
        if cur is None:
            break
        label = ""
        try:
            ui = cur.ksp_ui
            if ui.is_ksp_ui and str(ui.kind or "") in ("text", "image"):
                label = (ui.element_name or "").strip()
        except Exception:
            label = ""
        if not label:
            try:
                label = (cur.name or "").strip()
            except Exception:
                label = ""
        try:
            if _LOCALE_PARK_NAME in (label or ""):
                label = label.split(_LOCALE_PARK_NAME)[0]
        except Exception:
            pass
        label = re.sub(r"\.\d{3}$", "", label or "")
        page = ""
        try:
            if "ksp_page" in cur.keys():
                page = str(cur.get("ksp_page") or "").strip()
        except Exception:
            page = ""
        if page:
            parts.append(page)
            break
        if label:
            parts.append(label)
        try:
            if cur.ksp_bundle.is_ksp_bundle:
                break
        except Exception:
            pass
        cur = getattr(cur, "parent", None)
    parts.reverse()
    return normalize_hierarchy_key("/".join(parts))


def _content_line_count(text: str) -> int:
    return len(
        [ln for ln in (text or "").replace("\r", "").split("\n") if ln.strip()]
    )


def _ui_text_align(talign: int, font_family: str = "") -> int:
    """Map Unity TextAnchor 0..8 to TMP legacy slots used by create_rich_ui_text."""
    fam = (font_family or "").lower()
    is_ui = ("sdf" not in fam) and (
        ("opensans" in fam)
        or ("amaranth" in fam)
        or ("arial" in fam)
        or ("liberation" in fam)
        or (not fam)
    )
    t = int(talign or 0)
    if not is_ui or t > 8:
        return t
    return {
        0: 0, 1: 1, 2: 2,
        3: 4, 4: 5, 5: 6,
        6: 8, 7: 9, 8: 10,
    }.get(t, 0)


def _delete_object_tree(obj, *, preserve=None) -> None:
    """Delete obj and descendants. ``preserve`` objects (and their trees) stay."""
    import bpy

    if obj is None:
        return
    keep = set()
    for p in preserve or ():
        if p is None:
            continue
        keep.add(p)
        try:
            keep.update(getattr(p, "children_recursive", []) or [])
        except Exception:
            pass
    try:
        kids = list(getattr(obj, "children_recursive", []) or [])
    except Exception:
        kids = []
    for o in kids + [obj]:
        if o in keep:
            continue
        try:
            data = getattr(o, "data", None)
        except Exception:
            data = None
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except Exception:
            try:
                bpy.data.objects.remove(o)
            except Exception:
                pass
        if data is not None:
            try:
                if getattr(data, "users", 1) == 0:
                    if data.bl_rna.identifier == "TextCurve":
                        bpy.data.curves.remove(data)
                    elif data.bl_rna.identifier == "Mesh":
                        bpy.data.meshes.remove(data)
            except Exception:
                pass


def _independent_text_children(obj, *, include_parked: bool = False):
    """Nested UI texts under another text (ConfT1 under ConfS1), not rich-text runs."""
    out = []
    try:
        children = list(obj.children)
    except Exception:
        return out
    for child in children:
        try:
            if not include_parked and _is_parked_locale_obj(child):
                continue
            if _is_locale_text_root(child):
                out.append(child)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Per-locale viewport park (instant switch after first visit)
# Maps (.lang) are already RAM-preloaded; the slow part is FONT rebuild.
# After a language is built once we hide/rename its trees instead of deleting,
# then wake them on the next switch — no recreate.
# ---------------------------------------------------------------------------
_LOCALE_PARK_MARK = "ksp_locale_parked"
_LOCALE_PARK_BASE = "ksp_locale_park_base"
_LOCALE_PARK_NAME = "__kL_"


def _locale_park_tag(locale: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (locale or "xx").lower())[:10] or "xx"


def _is_parked_locale_obj(obj) -> bool:
    if obj is None:
        return False
    try:
        return bool(obj.get(_LOCALE_PARK_MARK))
    except Exception:
        return False


def _obj_blocks_active_locale(obj, locale: str) -> bool:
    """True when this viewport object must not receive another locale's maps.

    Covers EN-only duplicates (.001), ``ksp_shipped_locales`` and forgotten
    tags — soft recover by stock name must not restamp them on ES/FR.
    """
    if obj is None or not locale:
        return False
    loc = (locale or "").lower()
    try:
        from . import locale_buffers as _lb
        if _lb.is_forgotten_in_locale(obj, loc):
            return True
    except Exception:
        pass
    try:
        shipped = str(obj.get("ksp_shipped_locales") or "").strip()
        if shipped:
            allowed = {
                x.strip().lower() for x in shipped.split(",") if x.strip()
            }
            return loc not in allowed
    except Exception:
        pass
    try:
        if obj.get("ksp_user_added"):
            shipped = str(obj.get("ksp_shipped_locales") or "").strip()
            if not shipped:
                applied = str(obj.get("ksp_locale_applied") or "").strip().lower()
                if applied and loc != applied:
                    return True
    except Exception:
        pass
    try:
        if obj.get("ksp_user_added") and re.search(r"\.\d{3}$", obj.name or ""):
            return True
    except Exception:
        pass
    try:
        ui = obj.ksp_ui
        elname = (ui.element_name or "").strip()
        oname = (obj.name or "").strip()
        if (
            ui.is_ksp_ui
            and elname
            and oname
            and elname != oname
            and re.search(r"\.\d{3}$", oname)
        ):
            return True
    except Exception:
        pass
    return False


def _hide_locale_scoped_object(obj, *, locale: str = "") -> None:
    """Mark absent for this locale and hide without blanking parked caches."""
    try:
        obj["ksp_locale_orphan"] = True
        obj["ksp_locale_hidden"] = True
        obj["ksp_locale_applied"] = ""
    except Exception:
        pass
    try:
        _hide_tree(obj, True)
    except Exception:
        pass


def _obj_is_artwork_overlay(obj) -> bool:
    if obj is None:
        return False
    try:
        if obj.get("ksp_artwork_overlay") or obj.get("ksp_origin_box"):
            return True
    except Exception:
        pass
    try:
        from .viewport import is_artwork_overlay
        ui = obj.ksp_ui
        tx = str(getattr(ui, "text", "") or "")
        return bool(is_artwork_overlay(tx, obj))
    except Exception:
        return False


def _live_locale_text_forest_roots(root):
    """Top text roots (parent is not a live locale text) — park as whole trees."""
    out = []
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            if _is_parked_locale_obj(obj):
                continue
            if not _is_locale_text_root(obj):
                continue
            p = obj.parent
            if (
                p is not None
                and not _is_parked_locale_obj(p)
                and _is_locale_text_root(p)
            ):
                continue
            out.append(obj)
        except Exception:
            continue
    return out


def park_text_object(obj, locale: str) -> bool:
    """Hide a live text tree and free its Outliner name for another language."""
    if obj is None or _is_parked_locale_obj(obj):
        return False
    tag = _locale_park_tag(locale)
    loc = (locale or "").lower()
    try:
        base = (obj.ksp_ui.element_name or obj.name or "text").strip()
    except Exception:
        base = (obj.name or "text").strip()
    base = re.sub(r"\.\d{3}$", "", base)
    # Drop a previous park suffix if somehow still present.
    if _LOCALE_PARK_NAME in base:
        base = base.split(_LOCALE_PARK_NAME)[0] or "text"
    # Nested TitleScreen Subheader / ConfT* stay on this locale's parked
    # Header (USER-LATEST-009). Rebuild clones them onto the new language.
    # Overlays stay with this cache. Live children already switched to
    # another locale are detached so they are not stamped into this park.
    try:
        dest = obj.parent
        for ch in list(obj.children):
            try:
                if _is_parked_locale_obj(ch):
                    continue
                if _obj_is_artwork_overlay(ch):
                    continue
                if _obj_is_user_added(ch):
                    # ALL-scope copies stay live. LOCAL copies park with EN.
                    if _user_added_spans_locales(ch):
                        try:
                            _reparent_keep_world(ch, dest)
                        except Exception:
                            ch.parent = dest
                    continue
                applied = str(ch.get("ksp_locale_applied") or "").lower()
                nested_text = False
                try:
                    nested_text = bool(_is_locale_text_root(ch))
                except Exception:
                    nested_text = False
                # Nested Header/Subheader must stay with this locale cache so
                # instant EN wake still has the child (USER-LATEST-009).
                # Rebuild clones them onto the new language Header.
                if nested_text:
                    continue
                if applied and applied != loc:
                    ch.parent = dest
            except Exception:
                continue
    except Exception:
        pass
    try:
        obj[_LOCALE_PARK_MARK] = tag
        obj[_LOCALE_PARK_BASE] = base
        obj["ksp_locale_applied"] = loc
    except Exception:
        pass
    # Mark descendants so export / listings skip the whole parked tree —
    # but never stamp a live object that already belongs to another locale.
    try:
        for ch in list(getattr(obj, "children_recursive", []) or []):
            try:
                applied = str(ch.get("ksp_locale_applied") or "").lower()
                if applied and applied != loc:
                    continue
                ch[_LOCALE_PARK_MARK] = tag
            except Exception:
                continue
    except Exception:
        pass
    _hide_tree(obj, True)
    try:
        # Keep names unique and short (Blender 63-char limit).
        stem = base[: max(8, 63 - len(_LOCALE_PARK_NAME) - len(tag) - 4)]
        obj.name = "%s%s%s" % (stem, _LOCALE_PARK_NAME, tag)
    except Exception:
        pass
    return True


def wake_text_object(obj) -> bool:
    """Restore a parked text tree to a live name and visibility."""
    if obj is None or not _is_parked_locale_obj(obj):
        return False
    try:
        base = str(obj.get(_LOCALE_PARK_BASE) or "")
    except Exception:
        base = ""
    if not base:
        try:
            base = (obj.ksp_ui.element_name or "text").strip()
        except Exception:
            base = "text"
    try:
        del obj[_LOCALE_PARK_MARK]
    except Exception:
        pass
    try:
        if _LOCALE_PARK_BASE in obj.keys():
            del obj[_LOCALE_PARK_BASE]
    except Exception:
        pass
    try:
        for ch in list(getattr(obj, "children_recursive", []) or []):
            try:
                if _LOCALE_PARK_MARK in ch.keys():
                    del ch[_LOCALE_PARK_MARK]
            except Exception:
                continue
    except Exception:
        pass
    try:
        obj.name = base
    except Exception:
        pass
    _hide_tree(obj, False)
    return True


def count_parked_locale_texts(root, locale: str) -> int:
    tag = _locale_park_tag(locale)
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            if str(obj.get(_LOCALE_PARK_MARK) or "") == tag:
                n += 1
        except Exception:
            continue
    return n


def purge_parked_locale_texts(root, locale: str) -> int:
    """Delete parked trees for ``locale`` (stale cache before a fresh rebuild)."""
    tag = _locale_park_tag(locale)
    doomed = []
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            if str(obj.get(_LOCALE_PARK_MARK) or "") == tag:
                # Only forest roots — _delete_object_tree removes descendants.
                p = obj.parent
                if p is not None and str(p.get(_LOCALE_PARK_MARK) or "") == tag:
                    continue
                doomed.append(obj)
        except Exception:
            continue
    n = 0
    for obj in doomed:
        try:
            _delete_object_tree(obj)
            n += 1
        except Exception:
            continue
    return n


def park_live_locale_texts(root, locale: str) -> int:
    """Park every live text forest so another language can occupy the names."""
    # Replace any previous cache for this language (avoid duplicate parks).
    try:
        purge_parked_locale_texts(root, locale)
    except Exception:
        pass
    n = 0
    for obj in list(_live_locale_text_forest_roots(root)):
        try:
            # LOCAL-scope duplicates park with this language. ALL-scope stay live.
            if _obj_is_user_added(obj) and _user_added_spans_locales(obj):
                continue
        except Exception:
            pass
        if park_text_object(obj, locale):
            n += 1
    return n



def revive_shipped_parked_texts(root, maps, *, locale: str = "", kb=None) -> int:
    """No-op: foreign-park revive stacked other languages on EN.

    First visits rebuild live objects; later visits use instant park/wake.
    Do not wake parks from another locale.
    """
    return 0


def wake_parked_locale_texts(root, locale: str) -> int:
    tag = _locale_park_tag(locale)
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    # Only forest roots (have park_base). Descendants are cleared in wake_text_object.
    roots = []
    for obj in objs:
        try:
            if str(obj.get(_LOCALE_PARK_MARK) or "") != tag:
                continue
            if not obj.get(_LOCALE_PARK_BASE):
                continue
            roots.append(obj)
        except Exception:
            continue
    roots = sorted(roots, key=_obj_depth)
    for obj in roots:
        if wake_text_object(obj):
            n += 1
    return n


def try_instant_locale_swap(root, to_locale: str, *, from_locale: str = "") -> bool:
    """If ``to_locale`` was built before, park current and wake cached trees.

    Returns True when the viewport was swapped without FONT rebuilds.
    """
    if root is None:
        return False
    to_loc = (to_locale or "").lower()
    if not to_loc:
        return False
    parked_n = count_parked_locale_texts(root, to_loc)
    if parked_n < 1:
        return False
    from_loc = (from_locale or "").lower()
    if not from_loc:
        try:
            for obj in _live_locale_text_forest_roots(root):
                from_loc = str(obj.get("ksp_locale_applied") or "").lower()
                if from_loc:
                    break
        except Exception:
            from_loc = ""
    if not from_loc:
        from_loc = "prev"
    # Same tag is OK when RNA already flipped active_locale — still park live
    # trees under from_loc inferred from objects when needed.
    if from_loc == to_loc:
        try:
            for obj in _live_locale_text_forest_roots(root):
                applied = str(obj.get("ksp_locale_applied") or "").lower()
                if applied and applied != to_loc:
                    from_loc = applied
                    break
        except Exception:
            pass
    if from_loc == to_loc:
        from_loc = "prev"
    park_live_locale_texts(root, from_loc)
    woke = wake_parked_locale_texts(root, to_loc)
    if woke > 0:
        try:
            kb = root.ksp_bundle if root.ksp_bundle.is_ksp_bundle else None
            if kb is not None:
                _rebind_ui_element_viewports(kb, root)
        except Exception:
            pass
        # Multipage / presence must not leave other-language parks unhidden.
        try:
            ensure_parked_locale_hidden(root)
        except Exception:
            pass
    return woke > 0


def _non_text_ancestor(obj):
    """Nearest parent that is not a KSPedia text (page / empty / image)."""
    dest = None
    try:
        dest = obj.parent
    except Exception:
        return None
    seen = set()
    while dest is not None:
        try:
            ptr = dest.as_pointer()
        except Exception:
            ptr = id(dest)
        if ptr in seen:
            break
        seen.add(ptr)
        try:
            ui = dest.ksp_ui
            if ui.is_ksp_ui and ui.kind == "text":
                dest = dest.parent
                continue
        except Exception:
            break
        break
    return dest


def _matrix_basis_chain(obj, ancestor):
    """``obj`` transform in ``ancestor`` local space from loc/rot/scale only.

    Does not use ``matrix_world`` (often identity before depsgraph) nor
    ``matrix_parent_inverse`` (can cancel a stale world and yield 0, 0).
    """
    from mathutils import Matrix
    if obj is None:
        return Matrix.Identity(4)
    m = obj.matrix_basis.copy()
    cur = obj.parent
    seen = set()
    while cur is not None and cur != ancestor:
        try:
            ptr = cur.as_pointer()
        except Exception:
            ptr = id(cur)
        if ptr in seen:
            break
        seen.add(ptr)
        m = cur.matrix_basis @ m
        try:
            cur = cur.parent
        except Exception:
            break
    return m


def _pixel_scale_of(obj, default=0.001):
    seen = set()
    cur = obj
    while cur is not None:
        try:
            ptr = cur.as_pointer()
        except Exception:
            ptr = id(cur)
        if ptr in seen:
            break
        seen.add(ptr)
        try:
            if cur.ksp_bundle.is_ksp_bundle:
                return float(cur.ksp_bundle.pixel_scale or default) or default
        except Exception:
            pass
        try:
            cur = cur.parent
        except Exception:
            break
    return default


def _rewrite_user_added_unity_ap(obj) -> None:
    """After flatten, Unity parent is the page — AP must be page-local pixels.

    Keeping ConfT2 overlay AP made export write overlay-space XY and reimport
    drop clones under BackgroundBlack at the wrong positions.
    """
    if obj is None:
        return
    sx = _pixel_scale_of(obj)
    try:
        ax = float(obj.location.x) / sx
        ay = float(obj.location.y) / sx
        obj.ksp_ui.anchored_position = (ax, ay)
    except Exception:
        pass
    pin_layout_xy(obj)


def _retarget_layout_pin(obj):
    """After reparent, store layout XY in the new local space.

    Unity ``anchored_position`` / ``ksp_layout_ap`` stay as they were so
    export and locale deltas keep the original RectTransform values.
    """
    if obj is None:
        return
    try:
        loc = obj.location
        ap0 = obj.get("ksp_layout_ap", None)
    except Exception:
        return
    if ap0 is None:
        pin_layout_xy(obj)
        return
    dx = dy = 0.0
    try:
        ap = tuple(obj.ksp_ui.anchored_position or (0.0, 0.0))
        sx = _pixel_scale_of(obj)
        dx = (float(ap[0]) - float(ap0[0])) * sx
        dy = (float(ap[1]) - float(ap0[1])) * sx
    except Exception:
        dx = dy = 0.0
    try:
        obj["ksp_layout_xy"] = (float(loc.x) - dx, float(loc.y) - dy)
    except Exception:
        pass
    try:
        ps = page_space_xy(obj)
        if ps is not None:
            obj["ksp_page_xy"] = (float(ps[0]), float(ps[1]))
    except Exception:
        pass


def _reparent_keep_world(obj, dest, *, world_matrix=None, dest_world=None):
    """Reparent keeping pivot XY baked from the nested location chain.

    Unity RectTransform fields on ``ksp_ui`` are not rewritten — only the
    Blender parent (Outliner / delete tree) changes.
    """
    if obj is None:
        return False
    try:
        loc = _matrix_basis_chain(obj, dest).to_translation().copy()
        rot = obj.rotation_euler.copy()
        sc = obj.scale.copy()
    except Exception:
        return False
    try:
        obj.parent = dest
    except Exception:
        return False
    try:
        obj.matrix_parent_inverse.identity()
    except Exception:
        pass
    try:
        obj.location = (float(loc.x), float(loc.y), float(loc.z))
    except Exception:
        pass
    try:
        obj.rotation_euler = rot
        obj.scale = sc
    except Exception:
        pass
    try:
        if obj.get("ksp_user_added"):
            _rewrite_user_added_unity_ap(obj)
        else:
            _retarget_layout_pin(obj)
    except Exception:
        _retarget_layout_pin(obj)
    return True


def _is_page_empty(obj) -> bool:
    """TitleScreen / page empty — never bundle root, ``*_UI``, or TOC folder."""
    if obj is None:
        return False
    try:
        if obj.ksp_bundle.is_ksp_bundle:
            return False
    except Exception:
        pass
    try:
        if (obj.name or "").endswith("_UI"):
            return False
    except Exception:
        pass
    try:
        kind = str(obj.get("ksp_toc_kind") or "")
        if kind in ("category", "subcategory"):
            return False
        if kind == "page":
            return True
    except Exception:
        pass
    try:
        if str(obj.get("ksp_page") or "").strip() and "ksp_page_index" in obj.keys():
            return True
    except Exception:
        pass
    return False


def _flatten_dest(obj):
    """Page empty (keeps Filter Assets / UI Elements membership).

    Must not return ``*_UI`` / bundle root — parenting there drops
    ``page_screen`` so nested texts show on every TOC page (USER-LATEST-009).
    """
    page = _page_root_of(obj)
    if page is not None and page is not obj and _is_page_empty(page):
        return page
    cur = None
    try:
        cur = obj.parent
    except Exception:
        cur = None
    seen = set()
    while cur is not None:
        try:
            ptr = cur.as_pointer()
        except Exception:
            ptr = id(cur)
        if ptr in seen:
            break
        seen.add(ptr)
        if cur is not obj and _is_page_empty(cur):
            return cur
        try:
            cur = cur.parent
        except Exception:
            break
    dest = _non_text_ancestor(obj)
    if dest is not None and dest is not obj and _is_page_empty(dest):
        return dest
    return None


def page_space_xy(obj):
    """Translation of ``obj`` in page (or nearest non-text ancestor) space."""
    if obj is None:
        return None
    dest = _flatten_dest(obj)
    if dest is None or dest is obj:
        try:
            return (float(obj.location.x), float(obj.location.y))
        except Exception:
            return None
    try:
        t = _matrix_basis_chain(obj, dest).to_translation()
        return (float(t.x), float(t.y))
    except Exception:
        try:
            return (float(obj.location.x), float(obj.location.y))
        except Exception:
            return None


def flatten_one_text_off_text_parent(obj) -> bool:
    """Parent one independent Text Box to its page, not another text."""
    if obj is None:
        return False
    try:
        p = obj.parent
        if p is None:
            return False
        pui = p.ksp_ui
        if not (pui.is_ksp_ui and pui.kind == "text"):
            return False
    except Exception:
        return False
    dest = _flatten_dest(obj)
    if dest is None or dest is p:
        return False
    if not _reparent_keep_world(obj, dest):
        return False
    try:
        screen = str(dest.get("ksp_page", "") or "")
        if screen:
            obj["ksp_page"] = screen
    except Exception:
        pass
    return True


def flatten_user_added_off_text_parent(obj) -> int:
    """Un-inherit user duplicates from a stock text parent (page-space XY).

    Stock nested texts stay parented (Unity RectTransform / locale AP).
    Duplicates and other ``ksp_user_added`` independent texts/images must not
    ride the parent's locale rebuild, G-move, or export GO name — that is the
    USER-OLD-003 / USER-LATEST-006 / 007 / 008 family.
    Rich-text *run* children (same element_name) stay nested.
    """
    if obj is None:
        return 0
    try:
        chain = list(getattr(obj, "children_recursive", []) or [])
    except Exception:
        chain = []
    work = list(reversed(chain))
    work.append(obj)
    n = 0
    for o in work:
        try:
            if not o.get("ksp_user_added"):
                continue
        except Exception:
            continue
        try:
            p = o.parent
            if p is None:
                continue
            pui = p.ksp_ui
            if not (pui.is_ksp_ui and pui.kind == "text"):
                continue
        except Exception:
            continue
        independent = False
        image = False
        try:
            independent = bool(_is_locale_text_root(o))
        except Exception:
            independent = False
        try:
            ui = o.ksp_ui
            image = bool(ui.is_ksp_ui and ui.kind == "image")
        except Exception:
            image = False
        # The duplicated root may still share a blank/stock element_name with
        # its source; lift it anyway so it does not inherit ConfS2 TRS.
        if independent or o is obj:
            if flatten_one_text_off_text_parent(o):
                n += 1
            continue
        if image:
            dest = _flatten_dest(o)
            if dest is not None and dest is not p:
                if _reparent_keep_world(o, dest):
                    n += 1
    return n


def flatten_all_user_added_off_stock_text(root) -> int:
    """Lift every user_added text still nested under a stock text parent."""
    if root is None:
        return 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    n = 0
    for o in reversed(list(objs)):
        try:
            if not o.get("ksp_user_added"):
                continue
            p = o.parent
            if p is None or p.get("ksp_user_added"):
                continue
        except Exception:
            continue
        if flatten_one_text_off_text_parent(o):
            n += 1
    return n


def flatten_independent_text_nesting(root) -> int:
    """Each independent Text Box (and image under a text) sits under the page.

    Bake page-local XY from ``matrix_basis`` while still nested, then reparent.
    Rich-text *run* children (same ``element_name``) stay nested.
    Unity RectTransform / ``ksp_hierarchy`` are not rewritten.
    """
    if root is None:
        return 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    to_lift = []
    for obj in list(objs):
        try:
            p = obj.parent
            if p is None:
                continue
            pui = p.ksp_ui
            if not (pui.is_ksp_ui and pui.kind == "text"):
                continue
            ui = obj.ksp_ui
            if ui.is_ksp_ui and ui.kind == "image":
                to_lift.append(obj)
                continue
            if not _is_locale_text_root(obj):
                continue
        except Exception:
            continue
        to_lift.append(obj)
    if not to_lift:
        return 0
    # Bake page-local XY while still nested, then reparent. Do not recompute
    # after the first lift — that would see a half-broken chain.
    baked = {}
    dests = {}
    rots = {}
    scs = {}
    for obj in to_lift:
        dest = _flatten_dest(obj)
        dests[obj] = dest
        if dest is None:
            continue
        try:
            baked[obj] = _matrix_basis_chain(obj, dest).to_translation().copy()
            rots[obj] = obj.rotation_euler.copy()
            scs[obj] = obj.scale.copy()
        except Exception:
            continue
    n = 0
    for obj in to_lift:
        dest = dests.get(obj)
        loc = baked.get(obj)
        if dest is None or loc is None:
            continue
        try:
            obj.parent = dest
            obj.matrix_parent_inverse.identity()
            obj.location = (float(loc.x), float(loc.y), float(loc.z))
            if obj in rots:
                obj.rotation_euler = rots[obj]
            if obj in scs:
                obj.scale = scs[obj]
            _retarget_layout_pin(obj)
            n += 1
        except Exception:
            continue
    return n


def detach_independent_ui_children(obj) -> list:
    """Unparent nested independent texts/images before hide/delete."""
    out = []
    if obj is None:
        return out
    kids = list(_independent_text_children(obj))
    try:
        for ch in list(obj.children):
            try:
                ui = ch.ksp_ui
                if not ui.is_ksp_ui or ui.kind != "image":
                    continue
                if ch not in kids:
                    kids.append(ch)
            except Exception:
                continue
    except Exception:
        pass
    if not kids:
        return out
    dest = _flatten_dest(obj)
    if dest is None:
        dest = obj.parent
    baked = {}
    rots = {}
    scs = {}
    for ch in kids:
        try:
            baked[ch] = _matrix_basis_chain(ch, dest).to_translation().copy()
            rots[ch] = ch.rotation_euler.copy()
            scs[ch] = ch.scale.copy()
        except Exception:
            continue
    for child in kids:
        loc = baked.get(child)
        if loc is None:
            if _reparent_keep_world(child, dest):
                out.append(child)
            continue
        try:
            child.parent = dest
            child.matrix_parent_inverse.identity()
            child.location = (float(loc.x), float(loc.y), float(loc.z))
            if child in rots:
                child.rotation_euler = rots[child]
            if child in scs:
                child.scale = scs[child]
            _retarget_layout_pin(child)
            out.append(child)
        except Exception:
            continue
    return out


def _item_page_group_key(item) -> str:
    """Group duplicates per page. Never share an empty page_screen bucket."""
    page = (getattr(item, "page_screen", "") or "").strip()
    if page:
        return "s:" + page.lower()
    vo = getattr(item, "viewport_object", None)
    if vo is not None:
        try:
            p = str(vo.get("ksp_page", "") or "").strip()
            if p:
                return "s:" + p.lower()
        except Exception:
            pass
        pr = _page_root_of(vo)
        if pr is not None:
            try:
                p = str(pr.get("ksp_page", "") or "").strip()
                if p:
                    return "s:" + p.lower()
            except Exception:
                pass
            try:
                return "ptr:%s" % int(pr.as_pointer())
            except Exception:
                return "ptr:%s" % id(pr)
    try:
        return "row:%s" % id(item)
    except Exception:
        return "row:x"


def _is_stock_nested_text(vo) -> bool:
    """Unity child under a stock text parent — not a user duplicate."""
    try:
        if vo.get("ksp_user_added"):
            return False
    except Exception:
        pass
    try:
        p = vo.parent
        if p is None:
            return False
        pui = p.ksp_ui
        if not (pui.is_ksp_ui and pui.kind == "text"):
            return False
        if p.get("ksp_user_added"):
            return False
    except Exception:
        return False
    try:
        en = str(getattr(vo.ksp_ui, "element_name", "") or "")
        go = str(vo.get("ksp_export_go_name") or "")
        if re.search(r"\.\d{3}$", en) or re.search(r"\.\d{3}$", go):
            return False
    except Exception:
        pass
    return True


def _duplicate_sibling_rank(item) -> int:
    """Lower = stock twin; higher = EN-only duplicate (ConfS2 vs ConfS2.001).

    Blender Object.name ``ConfT3.001`` is a scene collision suffix on stock
    nested texts (same GO on many pages). Only Unity/export ``.001``
    counts as a user duplicate (USER-LATEST-009).
    """
    vo = getattr(item, "viewport_object", None)
    if vo is None:
        return 10 ** 6
    rank = 0
    try:
        if vo.get("ksp_user_added"):
            rank += 200
    except Exception:
        pass
    try:
        go = str(vo.get("ksp_export_go_name") or "")
        en = str(getattr(vo.ksp_ui, "element_name", "") or "")
        if re.search(r"\.\d{3}$", go) or re.search(r"\.\d{3}$", en):
            rank += 100
    except Exception:
        pass
    return rank


def restore_duplicate_locale_scope(kb, root) -> int:
    """Re-stamp EN-only siblings after .ksp reimport drops Blender flags.

    Export injects ConfS2 + ConfS2.001 into en-us.ksp; sibling .lang files
    still carry only the stock GO. Rank Unity ``.001`` / user_added as EN-only.
    Stock nested texts that share a GameObject name (ConfT3 on every page)
    must not be stamped — that un-parented them off the page (USER-LATEST-009).

    Unique LOCAL image copies keep ``__kS_<locale>`` on the Unity GO name
    (presence never hides unmarked stock images).
    """
    if kb is None:
        return 0
    from collections import defaultdict
    from . import locale_buffers as _lb

    shipped_loc = (
        str(getattr(kb, "locale", "") or getattr(kb, "active_locale", "") or "en-us")
        .strip()
        .lower()
    ) or "en-us"
    try:
        from .mu_ops import _detected_locales
        all_locs = list(_detected_locales(kb) or [])
    except Exception:
        all_locs = [shipped_loc]
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or []) if root is not None else []
    except Exception:
        objs = [root] if root is not None else []
    if not objs:
        objs = [
            getattr(it, "viewport_object", None)
            for it in (kb.ui_elements or [])
        ]
    for obj in objs:
        if obj is None:
            continue
        if not _lb.stamp_shipped_locale_from_name(obj):
            continue
        n += 1
        allowed = {
            x.strip().lower()
            for x in str(obj.get("ksp_shipped_locales") or "").split(",")
            if x.strip()
        }
        nm = _lb.shipped_go_display_name(
            str(obj.get("ksp_export_go_name") or getattr(obj, "name", "") or "")
        )
        for loc in all_locs:
            if loc and loc not in allowed:
                try:
                    _lb.forget_element(
                        kb, loc,
                        hier=_obj_hierarchy_key(obj),
                        name=nm,
                    )
                    _lb.mark_forgotten_locale(obj, loc)
                except Exception:
                    pass

    groups = defaultdict(list)
    for item in kb.ui_elements:
        name = (getattr(item, "name", "") or "").strip()
        if not name:
            continue
        kind = str(getattr(item, "kind", "") or "")
        groups[(_item_page_group_key(item), name, kind)].append(item)
    for (_page, _name, _kind), items in groups.items():
        if len(items) < 2:
            continue
        if all(_duplicate_sibling_rank(it) == 0 for it in items):
            continue
        ranked = sorted(items, key=_duplicate_sibling_rank)
        for item in ranked[1:]:
            vo = getattr(item, "viewport_object", None)
            if vo is None:
                continue
            if _is_stock_nested_text(vo) and _duplicate_sibling_rank(item) < 100:
                continue
            try:
                vo["ksp_user_added"] = True
                vo["ksp_shipped_locales"] = shipped_loc
            except Exception:
                pass
            for loc in all_locs:
                if loc and loc != shipped_loc:
                    try:
                        _lb.forget_element(
                            kb, loc,
                            hier=_obj_hierarchy_key(vo),
                            name=(getattr(item, "name", "") or ""),
                        )
                    except Exception:
                        pass
            n += 1
    return n


def reveal_shipped_artwork_overlays(root, maps, *, locale: str = "", kb=None) -> int:
    """Unhide live ConfB*/LL* pads the active locale ships.

    Other TOC pages stay hidden — a global unhide put overlays (and any
    child stamped overlay) on every page (USER-LATEST-009).
    """
    if root is None:
        return 0
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    loc = (locale or "").lower()
    active_page = None
    try:
        if kb is not None:
            active_page = getattr(kb, "filter_page_object", None)
    except Exception:
        active_page = None
    for obj in objs:
        try:
            if _is_parked_locale_obj(obj):
                continue
            if not _obj_is_artwork_overlay(obj):
                continue
            if loc and _obj_blocks_active_locale(obj, loc):
                continue
            if active_page is not None:
                pr = _page_root_of(obj)
                if pr is not None and pr != active_page:
                    continue
            _hide_tree(obj, False)
            n += 1
        except Exception:
            continue
    return n


def finalize_imported_layout(root) -> int:
    """Keep Unity nesting, refill UI Elements, pin import XY.

    Independent Text Boxes stay parented as in the RectTransform tree
    (pre-un-nest behaviour from ~2026-08-11). Flattening broke locale AP:
    children no longer followed parents, so FR/DE boxes walked off-page.
    """
    n = 0
    try:
        kb = root.ksp_bundle if root.ksp_bundle.is_ksp_bundle else None
    except Exception:
        kb = None
    try:
        _stamp_parent_rects(root, kb)
    except Exception:
        pass
    # Intentionally do NOT call flatten_independent_text_nesting.
    try:
        from .mu_ops import heal_ui_elements_list
        heal_ui_elements_list(root)
    except Exception:
        pass
    try:
        restore_duplicate_locale_scope(kb, root)
    except Exception:
        pass
    pin_all_layout_xy(root)
    try:
        from . import locale_buffers as _lb
        loc = ""
        if kb is not None:
            loc = (
                getattr(kb, "active_locale", "")
                or getattr(kb, "locale", "")
                or "en-us"
            )
        loc = str(loc or "en-us").lower()
        if kb is not None:
            _lb.set_prev_locale(kb, loc)
    except Exception:
        pass
    return n


def finalize_locale_hierarchy(root) -> int:
    """No-op: keep nesting after locale rebuild (do not bake / un-nest)."""
    return 0


def _clear_font_bodies(obj) -> None:
    """Blank FONT bodies so an accidental unhide cannot resurrect overlays (ALT)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        try:
            if getattr(cur, "type", "") == "FONT" and getattr(cur, "data", None):
                cur.data.body = ""
        except Exception:
            pass
        try:
            stack.extend(list(cur.children))
        except Exception:
            pass


def _font_body_blank(obj) -> bool:
    """True when the FONT body was emptied (orphan pass) and needs a rebuild."""
    try:
        if getattr(obj, "type", "") != "FONT" or obj.data is None:
            return False
        return not (obj.data.body or "").strip()
    except Exception:
        return False


def _same_locale_rebuild(old_obj, locale: str) -> bool:
    """True when this rebuild stays on the language already on the object.

    Empty stamps must not count as same-locale: that copied the outgoing
    box / materials onto the first DE rebuild after import.
    """
    try:
        prev = str(old_obj.get("ksp_locale_applied") or "").lower()
    except Exception:
        prev = ""
    cur = (locale or "").lower()
    if not prev or not cur:
        return False
    return prev == cur


def _coalesce_snapshot_size_delta(obj, item, loc_el, ui, lget, *, same_locale=True):
    """Locale size_delta wins unless width/height is a stretched ~0.

    Across languages the live object / ui_elements row belong to the language
    we are leaving — using them as fallback copied that box onto the next
    locale and back again.
    """
    from . import locale_buffers as _lb

    loc_sd = None
    loc_cs = None
    if loc_el is not None:
        try:
            v = lget("size_delta")
            if v is not None:
                loc_sd = tuple(v)
        except Exception:
            loc_sd = None
        try:
            v = lget("content_size")
            if v is not None:
                loc_cs = tuple(v)
        except Exception:
            loc_cs = None
        if loc_cs is None:
            try:
                ov = lget("user_overrides") or {}
                if isinstance(ov, dict) and ov.get("content_size"):
                    loc_cs = tuple(ov.get("content_size"))
            except Exception:
                loc_cs = None
    import_sd = _lb.import_content_size_of(obj)
    if not same_locale:
        return _lb.coalesce_size_delta(loc_sd, loc_cs, import_sd)
    ui_sd = None
    try:
        ui_sd = tuple(ui.size_delta or (0.0, 0.0))
    except Exception:
        ui_sd = None
    item_sd = None
    if item is not None:
        try:
            item_sd = tuple(item.size_delta or (0.0, 0.0))
        except Exception:
            item_sd = None
    return _lb.coalesce_size_delta(
        loc_sd, loc_cs, ui_sd, item_sd, import_sd, _lb.content_size_of(obj),
    )


def _snapshot_text_props(obj, item=None, loc_el=None, *, same_locale=True) -> dict:
    ui = obj.ksp_ui
    # Per-locale RAM / .lang wins for TRS. Live viewport is only a fallback
    # when this locale has no element data yet (must not leak across languages).
    # Locale elements arrive either as Unity objects (fresh bundle read) or as
    # plain dicts (RAM buffers, .blend rehydration, disk metric refresh).
    if isinstance(loc_el, dict):
        def _lget(name):
            return loc_el.get(name)
    else:
        def _lget(name):
            return getattr(loc_el, name, None)

    user_edit = False
    if loc_el is not None:
        try:
            user_edit = bool(_lget("has_viewport_edit"))
        except Exception:
            user_edit = False
    try:
        if same_locale and _obj_is_user_added(obj) and obj.get("ksp_has_viewport_edit"):
            user_edit = True
    except Exception:
        pass

    def _g(name, default=None):
        if loc_el is not None:
            try:
                val = _lget(name)
                # .lang often ships empty font_family; treat "" as missing so
                # we keep the Unity/import face (OpenSans Italic, Amaranth…).
                if val is not None:
                    # Contract marker: font_family must not leak across locales.
                    # if name == "font_family" and not same_locale
                    if name == "font_family" and isinstance(val, str) and not val.strip():
                        pass
                    else:
                        return val
            except Exception:
                pass
        # Shared ui_elements / live ksp_ui hold the ACTIVE language's paint.
        # Do not seed another language's rebuild from them.
        if not same_locale and name in (
            "color", "face_color", "outline_color",
            "local_rotation", "local_scale", "anchored_position",
        ):
            return default
        try:
            if item is not None and hasattr(item, name):
                val = getattr(item, name)
                if name == "font_family" and isinstance(val, str) and not val.strip():
                    pass
                elif val is not None:
                    return val
        except Exception:
            pass
        try:
            val = getattr(ui, name)
            if name == "font_family" and isinstance(val, str) and not val.strip():
                pass
            else:
                return val
        except Exception:
            pass
        if name == "font_family":
            try:
                stamped = obj.get("ksp_import_font_family", None)
                if stamped is not None and str(stamped).strip():
                    return str(stamped)
            except Exception:
                pass
        return default

    try:
        from .layout import blender_euler_to_unity_ui_quat
        live_rot = blender_euler_to_unity_ui_quat(obj.rotation_euler)
        live_scale = tuple(float(x) for x in obj.scale[:3])
    except Exception:
        live_rot = (0.0, 0.0, 0.0, 1.0)
        live_scale = (1.0, 1.0, 1.0)

    if user_edit:
        # This locale's own viewport edits (already in loc_el / live for same loc)
        ident_q = (0.0, 0.0, 0.0, 1.0)
        ident_s = (1.0, 1.0, 1.0)
        local_rotation = tuple(
            _lget("local_rotation")
            or (live_rot if same_locale else ident_q)
        )
        local_scale = tuple(
            _lget("local_scale")
            or (live_scale if same_locale else ident_s)
        )
        line_spacing = float(_g("line_spacing", 0.0) or 0.0)
        character_spacing = float(_g("character_spacing", 0.0) or 0.0)
        word_spacing = float(_g("word_spacing", 0.0) or 0.0)
    elif loc_el is not None:
        # Stock / seeded .lang or RAM without user flag — Unity fields only
        local_rotation = tuple(
            _g("local_rotation", (0, 0, 0, 1)) or (0, 0, 0, 1)
        )
        local_scale = tuple(_g("local_scale", (1, 1, 1)) or (1, 1, 1))
        line_spacing = float(_g("line_spacing", 0.0) or 0.0)
        character_spacing = float(_g("character_spacing", 0.0) or 0.0)
        word_spacing = float(_g("word_spacing", 0.0) or 0.0)
    else:
        # No locale element: keep current object only on same-locale refresh
        if same_locale:
            local_rotation = live_rot
            local_scale = live_scale
        else:
            local_rotation = (0.0, 0.0, 0.0, 1.0)
            local_scale = (1.0, 1.0, 1.0)
        line_spacing = float(_g("line_spacing", 0.0) or 0.0)
        character_spacing = float(_g("character_spacing", 0.0) or 0.0)
        word_spacing = float(_g("word_spacing", 0.0) or 0.0)

    # #region agent log
    try:
        def _src(fld):
            if loc_el is not None and _lget(fld) is not None:
                return "loc_el"
            if item is not None and hasattr(item, fld):
                return "item"
            return "ui"
        _dbg("E", "props source", {
            "obj": obj.name,
            "user_edit": bool(user_edit),
            "has_loc_el": bool(loc_el is not None),
            "src": {f: _src(f) for f in (
                "font_size", "character_spacing", "word_spacing",
                "line_spacing", "anchored_position", "size_delta")},
            "loc_el_vals": {
                f: _lget(f) for f in (
                    "font_size", "character_spacing", "word_spacing",
                    "line_spacing", "anchored_position", "size_delta")
            } if loc_el is not None else None,
            "ui_vals": {
                "font_size": float(getattr(ui, "font_size", 0.0) or 0.0),
                "anchored_position": list(
                    getattr(ui, "anchored_position", (0, 0)) or (0, 0)),
                "size_delta": list(getattr(ui, "size_delta", (0, 0)) or (0, 0)),
            },
        })
    except Exception:
        pass
    # #endregion
    overrides = None
    try:
        ov = _lget("user_overrides")
        overrides = ov if isinstance(ov, dict) and ov else None
    except Exception:
        overrides = None

    props = {
        "element_name": (ui.element_name or obj.name or "").strip(),
        "rect_path_id": str(ui.rect_path_id or ""),
        "parent_rect_path_id": "",
        "mb_path_id": str(ui.mb_path_id or ""),
        "go_path_id": str(ui.go_path_id or ""),
        "font_size": float(_g("font_size", 14.0) or 14.0),
        "color": tuple(_g("color", (1, 1, 1, 1)) or (1, 1, 1, 1)),
        "pivot": tuple(_g("pivot", (0.5, 0.5)) or (0.5, 0.5)),
        "size_delta": _coalesce_snapshot_size_delta(
            obj, item, loc_el, ui, _lget, same_locale=same_locale,
        ),
        "font_style": int(_g("font_style", 0) or 0),
        "text_alignment": int(_g("text_alignment", 0) or 0),
        "enable_word_wrapping": bool(_g("enable_word_wrapping", True)),
        "line_spacing": line_spacing,
        "margin": tuple(_g("margin", (0, 0, 0, 0)) or (0, 0, 0, 0)),
        "font_family": str(_g("font_family", "") or ""),
        "is_rich_text": bool(_g("is_rich_text", True)),
        "character_spacing": character_spacing,
        "word_spacing": word_spacing,
        "paragraph_spacing": float(_g("paragraph_spacing", 0.0) or 0.0),
        "enable_auto_sizing": bool(_g("enable_auto_sizing", False)),
        "font_size_min": float(_g("font_size_min", 0.0) or 0.0),
        "font_size_max": float(_g("font_size_max", 0.0) or 0.0),
        "overflow_mode": int(_g("overflow_mode", 0) or 0),
        "outline_width": float(_g("outline_width", 0.0) or 0.0),
        "outline_color": tuple(_g("outline_color", (0, 0, 0, 1)) or (0, 0, 0, 1)),
        "effect_distance": tuple(_g("effect_distance", (1.0, -1.0)) or (1.0, -1.0)),
        "has_ui_outline": bool(_g("has_ui_outline", False)),
        "has_ui_shadow": bool(_g("has_ui_shadow", False)),
        "local_rotation": local_rotation,
        "local_scale": local_scale,
        "local_position_z": float(_g("local_position_z", 0.0) or 0.0),
        "anchored_position": tuple(_g("anchored_position", (0, 0)) or (0, 0)),
        "old_anchored_position": tuple(
            getattr(ui, "anchored_position", (0, 0)) or (0, 0)
        ),
        "location": tuple(obj.location),
        "parent": obj.parent,
        "has_viewport_edit": bool(user_edit),
        "user_overrides": overrides,
        "text": str(_g("text", "") or getattr(ui, "text", "") or ""),
        "artwork_overlay": False,
    }
    try:
        pid = str(getattr(ui, "parent_rect_path_id", "") or "")
        if not pid:
            pid = str(obj.get("ksp_parent_rect", "") or "")
        if pid:
            props["parent_rect_path_id"] = pid
    except Exception:
        pass
    try:
        from .viewport import is_artwork_overlay
        tx = props.get("text") or ""
        # Text wins: a sticky EN hole stamp must not lock DE <color> bodies.
        if (tx or "").strip():
            props["artwork_overlay"] = bool(is_artwork_overlay(tx))
        else:
            props["artwork_overlay"] = bool(
                obj.get("ksp_artwork_overlay")
                or obj.get("ksp_origin_box")
                or is_artwork_overlay(tx)
            )
    except Exception:
        pass
    if overrides:
        # Width / size / colour tweaks must reach the builder, not be pasted
        # on afterwards — wrapping and fit depend on them.
        try:
            from . import locale_buffers as _lb
            props = _lb.merged_override_props(props, overrides)
        except Exception:
            pass
    return props



def _unity_id_str(val) -> str:
    """Normalize Unity path-id strings. Empty / 0 / None → ''."""
    s = str(val if val is not None else "").strip()
    if not s or s.lower() == "none":
        return ""
    try:
        n = int(s)
    except Exception:
        return s
    return str(n) if n else ""


def _el_get(el, key, default=""):
    if el is None:
        return default
    try:
        if isinstance(el, dict):
            v = el.get(key, default)
        else:
            v = getattr(el, key, default)
    except Exception:
        return default
    return default if v is None else v


def _obj_mb_str(obj) -> str:
    try:
        return _unity_id_str(getattr(obj.ksp_ui, "mb_path_id", ""))
    except Exception:
        return ""


def _obj_rect_str(obj) -> str:
    try:
        return _unity_id_str(getattr(obj.ksp_ui, "rect_path_id", ""))
    except Exception:
        return ""


def _count_list_names(kb, name, *, kind="") -> int:
    if not name or kb is None:
        return 0
    n = 0
    try:
        for item in kb.ui_elements:
            if kind and str(getattr(item, "kind", "") or "") != kind:
                continue
            if (getattr(item, "name", "") or "").strip() == name:
                n += 1
    except Exception:
        return 0
    return n


def _lookup_el_by_mb(el_by_hier, mb: str):
    """Find a locale-map element by MonoBehaviour path id (duplicate names)."""
    mb = _unity_id_str(mb)
    if not mb or not el_by_hier:
        return None
    for el in el_by_hier.values():
        got = _unity_id_str(_el_get(el, "mb_path_id"))
        if got and got == mb:
            return el
    return None


def _find_element_item(kb, obj):
    """Match a viewport object to a UI Elements row.

    Same-named siblings (two \"Craft Pitches\") must not share a row: identity
    is viewport pointer, then rect / mb path id. Name is last and only when
    unique in the list.
    """
    if kb is None or obj is None:
        return None
    try:
        ui = obj.ksp_ui
        rid = _unity_id_str(ui.rect_path_id)
        mb = _unity_id_str(ui.mb_path_id)
        name = (ui.element_name or "").strip()
        kind = str(ui.kind or "text")
    except Exception:
        return None
    try:
        for item in kb.ui_elements:
            try:
                if item.viewport_object == obj:
                    return item
            except Exception:
                pass
        if rid:
            for item in kb.ui_elements:
                if _unity_id_str(getattr(item, "rect_path_id", "")) == rid:
                    return item
        if mb:
            for item in kb.ui_elements:
                if _unity_id_str(getattr(item, "mb_path_id", "")) == mb:
                    return item
        if name and _count_list_names(kb, name, kind=kind) == 1:
            for item in kb.ui_elements:
                if (
                    str(getattr(item, "kind", "") or "") == kind
                    and (item.name or "").strip() == name
                ):
                    return item
    except Exception:
        pass
    return None


def _apply_ksp_ui(obj, props, text: str) -> None:
    try:
        ui = obj.ksp_ui
        ui.is_ksp_ui = True
        ui.element_name = props["element_name"]
        ui.kind = "text"
        ui.mb_path_id = props["mb_path_id"]
        ui.go_path_id = props["go_path_id"]
        ui.rect_path_id = props["rect_path_id"]
        try:
            pid = str(props.get("parent_rect_path_id") or "")
            ui.parent_rect_path_id = pid
            obj["ksp_parent_rect"] = pid
        except Exception:
            pass
        ui.text = text
        try:
            from .viewport import preserve_overlay_newlines
            stored = preserve_overlay_newlines(text if text is not None else "")
        except Exception:
            stored = str(text if text is not None else "")
        try:
            obj["ksp_text_source"] = stored
        except Exception:
            pass
        if stored and stored != (text or ""):
            try:
                ui.text = stored
            except Exception:
                pass
        ui.font_size = props["font_size"]
        ui.color = props["color"]
        ui.pivot = props["pivot"]
        ui.size_delta = props["size_delta"][:2]
        ui.font_style = props["font_style"]
        ui.text_alignment = props["text_alignment"]
        ui.enable_word_wrapping = props["enable_word_wrapping"]
        ui.line_spacing = props["line_spacing"]
        ui.margin = props["margin"]
        ui.font_family = props["font_family"]
        ui.local_rotation = props["local_rotation"]
        ui.local_scale = props["local_scale"]
        ui.local_position_z = props["local_position_z"]
        ui.anchored_position = props["anchored_position"][:2]
    except Exception:
        pass


def _refresh_nested_locale_children(obj, *, locale: str = "", pixel_scale: float = 0.001, kb=None) -> int:
    """Apply this locale's maps to independent children just adopted onto obj.

    Parent park used to stamp those children into the EN cache, so DE/FR
    TitleScreen showed Header without Subheader (USER-LATEST-009).
    """
    if obj is None:
        return 0
    maps = {}
    try:
        maps = _LAYOUT_APPLY_CTX.get("maps") or {}
    except Exception:
        maps = {}
    if not maps:
        return 0
    n = 0
    for child in list(_independent_text_children(obj)):
        try:
            if _is_parked_locale_obj(child) or _obj_is_artwork_overlay(child):
                continue
            if _obj_is_user_added(child):
                # Flattened G-moved copies must not inherit stock ConfT* AP.
                continue
        except Exception:
            continue
        try:
            child.hide_set(False)
            child.hide_viewport = False
            child.hide_render = False
        except Exception:
            pass
        try:
            if "ksp_locale_orphan" in child.keys():
                del child["ksp_locale_orphan"]
            if "ksp_locale_hidden" in child.keys():
                del child["ksp_locale_hidden"]
        except Exception:
            pass
        text, loc_el, _n, _h = _resolve_locale_text_for_obj(
            child,
            maps.get("text_by_hier") or {},
            maps.get("text_by_name") or {},
            maps.get("el_by_hier") or {},
            maps.get("el_by_name") or {},
        )
        if text is None:
            continue
        try:
            rebuilt = rebuild_text_object(
                child,
                text,
                locale=locale,
                pixel_scale=pixel_scale,
                kb=kb,
                loc_el=loc_el,
                park_previous=False,
            )
            if rebuilt is not None:
                n += 1
        except Exception:
            continue
    return n


def rebuild_text_object(
    old_obj,
    new_text: str,
    *,
    locale: str = "",
    pixel_scale: float = 0.001,
    collection=None,
    kb=None,
    loc_el=None,
    park_previous: bool = True,
):
    """Replace a viewport text object with a freshly laid-out rich-text build."""
    from . import layout, viewport
    from . import locale_buffers

    if old_obj is None:
        return None
    # Do NOT merge live viewport TRS / box / materials into the target
    # locale — that leaked scale, rotation and the physical text box across
    # languages and wiped multimaterial on the way back.
    same_locale = _same_locale_rebuild(old_obj, locale)
    item = _find_element_item(kb, old_obj)
    props = _snapshot_text_props(
        old_obj, item, loc_el=loc_el, same_locale=same_locale,
    )
    parent = props["parent"]
    loc = list(props["location"])
    mat_snap = None
    if same_locale:
        try:
            from .viewport import snapshot_font_materials
            mat_snap = snapshot_font_materials(old_obj)
        except Exception:
            mat_snap = None
    if collection is None:
        try:
            cols = list(old_obj.users_collection)
            collection = cols[0] if cols else None
        except Exception:
            collection = None
    if collection is None:
        return None

    sd = props["size_delta"]
    box_w = abs(float(sd[0])) if sd else 0.0
    box_h = abs(float(sd[1])) if len(sd) > 1 else 0.0
    try:
        import_sz = locale_buffers.import_content_size_of(old_obj)
    except Exception:
        import_sz = None
    el_name = props["element_name"] or "text"
    # Blue hole / space-pad overlays: always the import Unity crect. Locale
    # size_delta (or a DE metric that leaked into EN props) changed ConfB
    # box_y by ~35 px and walked glyphs off the hole after EN→DE→EN.
    # Detect from the *incoming* string only. EN ConfT2 is a hole body
    # (spaces for ConfB2); DE ships the blue quote as <color> inside ConfT2
    # and has no ConfB* GOs — keeping the EN stamp treated DE ConfT2 like
    # an artwork overlay and left pins / parks confused across languages.
    # Pass old_obj so a stamped ConfB/LL8 stays locked when the .lang drops
    # the pad (FR ALT is just "ALT"). Do not rewrite ALT to the EN lead —
    # locale .lang spaces still go into the FONT.
    overlay_locked = False
    try:
        overlay_locked = bool(viewport.is_artwork_overlay(new_text, old_obj))
    except Exception:
        overlay_locked = False
    try:
        props["artwork_overlay"] = bool(overlay_locked)
    except Exception:
        pass
    if overlay_locked and import_sz is not None:
        if abs(float(import_sz[0])) > 1.0:
            box_w = abs(float(import_sz[0]))
        if abs(float(import_sz[1])) > 1.0:
            box_h = abs(float(import_sz[1]))
    elif import_sz is not None:
        # Fill only degenerate locale sizeDelta from the import crect.
        # Keep locale w×h otherwise (Aug-11 behaviour) so FR ConfS3 can
        # wrap in its tall Unity rect and ConfT3 follows its own AP.
        imp_w = abs(float(import_sz[0])) if abs(float(import_sz[0])) > 1.0 else 0.0
        imp_h = abs(float(import_sz[1])) if abs(float(import_sz[1])) > 1.0 else 0.0
        if box_w <= 1.0 and imp_w > 1.0:
            box_w = imp_w
        if box_h <= 1.0 and imp_h > 1.0:
            box_h = imp_h
    # Same-locale refresh only: recover a missing hole from the live FONT.
    # Across languages the live box belongs to the language we are leaving.
    if same_locale and (box_w <= 1.0 or box_h <= 1.0):
        try:
            tb = old_obj.data.text_boxes[0]
            sx = float(pixel_scale) or 0.001
            if box_w <= 1.0:
                tw = abs(float(tb.width)) / sx
                if tw > 1.0:
                    box_w = tw
            if box_h <= 1.0:
                pv = props.get("pivot") or (0.5, 0.5)
                py = float(pv[1]) if len(pv) > 1 else 0.5
                denom = (1.0 - py) if (1.0 - py) > 1e-4 else max(py, 1e-4)
                top = float(tb.y)
                if abs(top) > 1e-8:
                    est = abs(top) / (denom * sx)
                    if 1.0 < est < 4000.0:
                        box_h = est
        except Exception:
            pass
    fam = props["font_family"]
    talign = _ui_text_align(props["text_alignment"], fam)
    wrap = bool(props["enable_word_wrapping"])
    rem = (new_text or "").lstrip(" \t\n\r")
    try:
        pad_overlay = bool(viewport.is_space_pad_overlay(new_text))
    except Exception:
        pad_overlay = False
    if (
        not pad_overlay
        and (new_text or "")[:1].isspace()
        and len(rem) >= 28
    ):
        wrap = True

    # Short section labels (ConfS*): keep Unity box height for vertical align
    # (TOP/CENTER snap). Dropping height on locale rebuild left glyphs sunk
    # in the rect (tb.y ≈ 0) while Show Text Boxes still drew the full rect.
    short_label = (
        float(props["font_size"]) >= 45.0
        and _content_line_count(new_text) <= 1
        and len((rem or "").strip()) < 72
    )
    box_h_arg = box_h if box_h > 1.0 else None

    # Read the layout baseline before the old object is deleted below.
    pin_xy = None
    pin_ap = None
    base_z = 0.02
    overlay_tb = None
    try:
        p = old_obj.get("ksp_layout_xy", None)
        if p is not None and len(p) >= 2:
            pin_xy = (float(p[0]), float(p[1]))
        a = old_obj.get("ksp_layout_ap", None)
        if a is not None and len(a) >= 2:
            pin_ap = (float(a[0]), float(a[1]))
        bz = old_obj.get("ksp_base_z", None)
        if bz is not None:
            base_z = float(bz)
        # Orphan pass blanks the body but keeps the import text_boxes / lead.
        # Recomputing lead on rebuild shifted ConfB1 box_y by ~35 px.
        # LL8 ALT keeps the locale .lang pad inside the pinned box — do not
        # freeze the previous language's text_boxes over those spaces.
        if overlay_locked and getattr(old_obj, "type", "") == "FONT":
            skip_tb = False
            try:
                skip_tb = bool(
                    viewport.is_short_token_overlay(new_text, el_name)
                )
            except Exception:
                skip_tb = False
            if not skip_tb:
                tb0 = old_obj.data.text_boxes[0]
                overlay_tb = (
                    float(tb0.x), float(tb0.y),
                    float(tb0.width), float(tb0.height),
                )
    except Exception:
        pin_xy = pin_ap = None
        overlay_tb = None

    forgotten_locales = ""
    import_font_family = ""
    try:
        if "ksp_forgotten_locales" in old_obj.keys():
            forgotten_locales = str(old_obj.get("ksp_forgotten_locales") or "")
    except Exception:
        forgotten_locales = ""
    try:
        import_font_family = str(old_obj.get("ksp_import_font_family") or "")
    except Exception:
        import_font_family = ""
    # Empty .lang family: keep import/Unity face for bold/italic slots.
    if not str(props.get("font_family") or "").strip() and import_font_family.strip():
        props["font_family"] = import_font_family
        fam = import_font_family

    # User-edited locales restore absolute Blender location via loc_el.
    # User-added duplicates keep old_obj.location (G-move). Another
    # language's stock loc_el.location is the original child's pose.
    if props.get("has_viewport_edit") and not _obj_is_user_added(old_obj):
        try:
            from . import locale_buffers as _lb
            d = _lb._copy_el_dict(loc_el) if loc_el is not None else {}
            cap = d.get("location")
            if cap is not None and len(cap) >= 3:
                loc = [float(cap[0]), float(cap[1]), float(cap[2])]
        except Exception:
            pass

    # Create FIRST — never delete the old object until the new one exists
    # (a failed create used to wipe Configuration body texts permanently).
    hier_key = _obj_hierarchy_key(old_obj)
    tmp_name = "%s__ksp_loc" % el_name
    try:
        obj, display_text = viewport.create_rich_ui_text(
            collection,
            tmp_name,
            new_text,
            props["font_size"],
            base_color=props["color"],
            pixel_scale=pixel_scale,
            pivot=props["pivot"],
            box_width=box_w if box_w > 1.0 else None,
            box_height=box_h_arg,
            font_style=props["font_style"],
            is_rich_text=props["is_rich_text"],
            text_alignment=talign,
            line_spacing=props["line_spacing"],
            enable_word_wrapping=wrap,
            margin=props["margin"],
            font_family=fam,
            locale=locale,
            character_spacing=props["character_spacing"],
            word_spacing=props["word_spacing"],
            paragraph_spacing=props["paragraph_spacing"],
            enable_auto_sizing=props["enable_auto_sizing"],
            font_size_min=props["font_size_min"],
            font_size_max=props["font_size_max"],
            overflow_mode=props["overflow_mode"],
        )
    except Exception:
        return None
    if obj is None:
        return None
    try:
        pref = str(old_obj.get("ksp_overlay_prefix") or "")
        if pref:
            obj["ksp_overlay_prefix"] = pref
        bpref = str(old_obj.get("ksp_overlay_body_prefix") or "")
        if bpref:
            obj["ksp_overlay_body_prefix"] = bpref
    except Exception:
        pass

    # Independent nested texts/images must survive parent rebuild. Park them
    # on the grandparent without baking — locale apply must not un-nest mid
    # switch (that left children at the previous language's parent XY).
    keep = list(_independent_text_children(old_obj))
    try:
        for ch in list(old_obj.children):
            try:
                ui = ch.ksp_ui
                if ui.is_ksp_ui and ui.kind == "image" and ch not in keep:
                    keep.append(ch)
            except Exception:
                continue
    except Exception:
        pass
    nest_parent = parent

    # Cross-locale: park the previous language's tree instead of deleting it.
    # Next switch to that language wakes the parked objects (instant).
    # Never detach nested overlays before parking — that stole ConfT / blue
    # hole texts onto the new language and left gaps after EN↔FR↔DE.
    parked = False
    if park_previous and not same_locale:
        prev_loc = ""
        try:
            prev_loc = str(old_obj.get("ksp_locale_applied") or "").lower()
        except Exception:
            prev_loc = ""
        if not prev_loc:
            try:
                from . import locale_buffers as _lb
                if kb is not None:
                    prev_loc = _lb.get_prev_locale(kb) or ""
            except Exception:
                prev_loc = ""
        if prev_loc and prev_loc != str(locale or "").lower():
            parked = bool(park_text_object(old_obj, prev_loc))

    if same_locale or not parked:
        for child in keep:
            try:
                child.parent = nest_parent
            except Exception:
                try:
                    child.parent = None
                except Exception:
                    pass
        if not parked:
            _delete_object_tree(old_obj, preserve=keep)
    try:
        if obj.name != el_name:
            obj.name = el_name
    except Exception:
        pass
    try:
        obj.location = tuple(loc)
    except Exception:
        pass
    if pin_xy is not None:
        try:
            obj["ksp_layout_xy"] = pin_xy
            if pin_ap is not None:
                obj["ksp_layout_ap"] = pin_ap
        except Exception:
            pass
    try:
        obj.parent = parent
    except Exception:
        pass
    _copy_user_added_pose_marks(old_obj, obj)
    if same_locale:
        try:
            if old_obj.get("ksp_has_viewport_edit"):
                obj["ksp_has_viewport_edit"] = True
        except Exception:
            pass
        try:
            applied = old_obj.get("ksp_applied_xy")
            if applied is not None and len(applied) >= 2:
                obj["ksp_applied_xy"] = (float(applied[0]), float(applied[1]))
        except Exception:
            pass
    if parked:
        # Deepest-first may have parented the NEW nested text under the old
        # parent before this park. park_text_object detaches those live
        # children to the grandparent — adopt them onto the new language tree.
        try:
            for child in list(old_obj.children):
                try:
                    if _is_parked_locale_obj(child):
                        continue
                    child.parent = obj
                except Exception:
                    continue
        except Exception:
            pass
        for child in keep:
            try:
                if _is_parked_locale_obj(child):
                    # Overlays stay in the parked cache; spawn/reveal
                    # puts them on the live parent. Cloning ConfT2/ConfB
                    # stacked Function-Filter paragraphs on Configuration.
                    if _obj_is_artwork_overlay(child):
                        continue
                    en = ""
                    try:
                        en = (child.ksp_ui.element_name or "").strip()
                    except Exception:
                        en = ""
                    already = False
                    if en:
                        for live in _independent_text_children(obj):
                            try:
                                if (live.ksp_ui.element_name or "").strip() == en:
                                    already = True
                                    break
                            except Exception:
                                continue
                    if already:
                        continue
                    if _obj_is_user_added(child):
                        continue
                    cloned = _clone_parked_text_scaffold(child, obj)
                    if cloned is None:
                        continue
                    continue
                child.parent = obj
            except ReferenceError:
                continue
            except Exception:
                continue
        try:
            _refresh_nested_locale_children(
                obj, locale=locale, pixel_scale=pixel_scale, kb=kb,
            )
        except Exception:
            pass
    else:
        for child in keep:
            try:
                _ = child.name
                child.parent = obj
            except ReferenceError:
                continue
            except Exception:
                pass

    class _El:
        pass

    el = _El()
    el.local_rotation = props["local_rotation"]
    el.local_scale = props["local_scale"]
    el.local_position_z = props["local_position_z"]
    layout.apply_ui_local_trs(obj, el, pixel_scale=pixel_scale, base_z=base_z)

    _apply_ksp_ui(obj, props, new_text)
    try:
        # Persist locale box on the object so the next switch diffs correctly.
        ui = obj.ksp_ui
        ui.size_delta = props["size_delta"][:2]
        ui.anchored_position = props["anchored_position"][:2]
        ui.font_size = props["font_size"]
        ui.font_family = props["font_family"]
        ui.element_name = el_name
    except Exception:
        pass
    try:
        obj["ksp_text_display"] = display_text
        obj["ksp_locale_applied"] = locale or ""
        # Nested overlays (ConfSubheader2 under ConfHeader) often never get
        # their own apply pass stamp — inherit so park keeps them with us.
        try:
            loc_l = (locale or "").lower()
            for ch in list(getattr(obj, "children_recursive", []) or []):
                try:
                    if _is_parked_locale_obj(ch):
                        continue
                    if not _is_locale_text_root(ch):
                        continue
                    applied = str(ch.get("ksp_locale_applied") or "").lower()
                    if applied and applied != loc_l:
                        continue
                    if not applied:
                        ch["ksp_locale_applied"] = loc_l
                except Exception:
                    continue
        except Exception:
            pass
        if hier_key:
            obj["ksp_hierarchy"] = hier_key
        if forgotten_locales:
            obj["ksp_forgotten_locales"] = forgotten_locales
        if import_font_family:
            obj["ksp_import_font_family"] = import_font_family
        if overlay_locked:
            obj["ksp_artwork_overlay"] = True
            obj["ksp_origin_box"] = True
        else:
            for _k in ("ksp_artwork_overlay", "ksp_origin_box"):
                try:
                    if _k in obj.keys():
                        del obj[_k]
                except Exception:
                    pass
        if "ksp_locale_orphan" in obj.keys():
            del obj["ksp_locale_orphan"]
    except Exception:
        pass

    # Fit into box. Soft fit for short labels and real CJK (after char-wrap).
    # Do NOT treat whole zh-cn locale as CJK — Latin leftovers need normal fit.
    try:
        from .fonts_util import detect_script
        script = detect_script(display_text or new_text or "")
    except Exception:
        script = "latin"
    is_cjk = script in ("cjk", "mixed", "hangul", "kana")
    # Never fit_text space-pad overlays — they are intentionally wider than
    # sizeDelta (holes in ConfT*) and fit crushes them into spaghetti.
    skip_fit = False
    try:
        skip_fit = bool(
            overlay_locked or viewport.is_space_pad_overlay(new_text)
        )
    except Exception:
        skip_fit = False
    # Import never runs fit_text_object_to_box — wrapping lives in
    # create_rich_ui_text. Extra fit after every refresh/locale rebuild
    # shrank fonts and drifted Show Text Boxes vs the import layout.
    if not skip_fit and is_cjk:
        try:
            viewport.fit_text_object_to_box(
                obj,
                box_width_px=box_w if box_w > 1.0 else None,
                box_height_px=(
                    None
                    if short_label
                    else (box_h if box_h > 1.0 else None)
                ),
                pixel_scale=pixel_scale,
                locale=locale,
                plain=display_text or new_text,
                max_iters=3 if (short_label or is_cjk) else 10,
                soft=bool(short_label or is_cjk),
            )
        except Exception:
            pass
    # Layout comes from this locale's anchoredPosition against the import
    # baseline — never from captured Blender XY/scale (that drifted boxes).
    apply_locale_position(obj, props, loc_el, pixel_scale=pixel_scale)
    # Keep the import XY/AP pin. Re-stamping after a rebuild made the next
    # language switch measure against an already-shifted box.
    try:
        if obj.get("ksp_layout_xy") is None:
            pin_layout_xy(obj, props=props)
    except Exception:
        pin_layout_xy(obj, props=props)
    try:
        # Stamp Unity/builder TRS *before* user R/S / font / paint. Pinning
        # after apply_blender_trs_override made scale 0.8 the yardstick, so
        # the next park no longer saw a tweak and EN lost rotation/scale.
        locale_buffers.pin_build_state(obj)
        locale_buffers.apply_font_override(obj, props.get("user_overrides"))
        locale_buffers.apply_material_override(obj, props.get("user_overrides"))
        locale_buffers.apply_blender_trs_override(
            obj, props.get("user_overrides"), loc_el,
        )
        locale_buffers.remember_applied_overrides(obj, props.get("user_overrides"))
        if import_sz is not None:
            locale_buffers.stamp_import_content_size(
                obj, import_sz[0], import_sz[1],
            )
    except Exception:
        pass
    try:
        if mat_snap:
            from .viewport import restore_font_materials
            restore_font_materials(obj, mat_snap, require_same_body=True)
    except Exception:
        pass
    # Image-locked overlays: keep the import FONT box (lead nudge included).
    # Recomputing lead on every locale rebuild moved ConfB1 "true" ~35 px.
    if overlay_tb is not None:
        try:
            tb = obj.data.text_boxes[0]
            tb.x = float(overlay_tb[0])
            tb.y = float(overlay_tb[1])
            tb.width = float(overlay_tb[2])
            tb.height = float(overlay_tb[3])
            obj["ksp_origin_box"] = True
        except Exception:
            pass
    # #region agent log
    try:
        viewport._dbg_agent_log(
            "H2",
            "locale_switch.fit",
            "fit_decision",
            {
                "name": el_name,
                "locale": locale or "",
                "skip_fit": bool(skip_fit),
                "short_label": bool(short_label),
                "is_cjk": bool(is_cjk),
                "script": script,
            },
            run_id="post-fix",
        )
    except Exception:
        pass
    # #endregion

    if item is not None:
        try:
            item.text = new_text
            try:
                sd = props["size_delta"]
                item.size_delta = (float(sd[0]), float(sd[1]), 0.0)
            except Exception:
                pass
            try:
                ap = props["anchored_position"]
                item.anchored_position = (float(ap[0]), float(ap[1]), 0.0)
            except Exception:
                pass
            item.font_size = props["font_size"]
            item.viewport_object = obj
        except Exception:
            pass
    return obj


def _element_base_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    # Strip Blender duplicate suffix: Name.001
    m = re.match(r"^(.*)\.(\d{3})$", n)
    return m.group(1) if m else n


def _iter_parents(obj):
    """Yield ancestors, stopping on a parent cycle."""
    seen = set()
    try:
        cur = obj.parent if obj is not None else None
    except Exception:
        return
    while cur is not None:
        try:
            ptr = cur.as_pointer()
        except Exception:
            try:
                ptr = id(cur)
            except Exception:
                break
        if ptr in seen:
            break
        seen.add(ptr)
        yield cur
        try:
            cur = cur.parent
        except Exception:
            break


def _is_locale_text_root(obj) -> bool:
    try:
        if obj.get("ksp_outline_ghost"):
            return False
    except Exception:
        pass
    try:
        if _is_parked_locale_obj(obj):
            return False
        # Nested under a parked locale tree — not live viewport content.
        for p in _iter_parents(obj):
            if _is_parked_locale_obj(p):
                return False
    except Exception:
        pass
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui or ui.kind != "text":
            return False
    except Exception:
        return False
    # Skip rich-text *run* children (parent is also a text root AND same
    # element_name). Independent nested UI texts keep their own name
    # (ConfT1 under ConfS1, ConfSubheader under ConfHeader, etc.).
    try:
        p = obj.parent
        if p is not None:
            pui = p.ksp_ui
            if pui.is_ksp_ui and pui.kind == "text":
                my_en = (ui.element_name or "").strip()
                parent_en = (pui.element_name or "").strip()
                if my_en and parent_en and my_en != parent_en:
                    return True
                return False
    except Exception:
        pass
    return True


def _purge_duplicate_text_roots(candidates, *, delete=True):
    """Keep one object per Unity identity; drop Blender .001 leftovers only.

    Same-named siblings (two "Craft Pitches") must both survive — they share
    a GO name but have distinct mb_path_id / hierarchy#N keys. Never delete
    during capture when ``delete=False``.

    User-added / duplicated elements (``ksp_user_added``) keep a unique key so
    Refresh never collapses them onto the stock identity they were copied from.
    """
    best = {}
    doomed = []
    for obj in candidates:
        try:
            ui = obj.ksp_ui
            name = (ui.element_name or obj.name or "").strip()
            mb = str(getattr(ui, "mb_path_id", "") or "").strip()
        except Exception:
            continue
        hier = _obj_hierarchy_key(obj)
        base = _element_base_name(name) or _element_base_name(obj.name)
        user_added = False
        try:
            user_added = bool(obj.get("ksp_user_added"))
        except Exception:
            user_added = False
        if user_added:
            # Never share a purge key with stock Unity ids.
            key = "u:" + (hier or name or obj.name or str(id(obj)))
        elif mb and mb not in ("0", "None"):
            key = "m:" + (_unity_id_str(mb) or mb)
        elif hier:
            key = "h:" + hier
        else:
            # No Unity identity — keep each object. Collapsing by GO name
            # deleted same-named siblings (two "Craft Pitches") that had not
            # yet been stamped with mb / hierarchy#N.
            key = "id:" + str(id(obj))
        if not key or key in ("h:", "n:", "m:", "u:", "id:"):
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = obj
            continue
        # Prefer exact base name over Name.001 for true leftovers of one id.
        prev_name = ""
        try:
            prev_name = (prev.ksp_ui.element_name or prev.name or "")
        except Exception:
            prev_name = prev.name or ""
        cur_exact = _element_base_name(name) == name or name == base
        prev_exact = _element_base_name(prev_name) == prev_name or prev_name == base
        if cur_exact and not prev_exact:
            doomed.append(prev)
            best[key] = obj
        else:
            doomed.append(obj)
    if delete:
        for obj in doomed:
            try:
                _delete_object_tree(obj)
            except Exception:
                pass
    return list(best.values())


def _hide_tree(obj, hide: bool) -> None:
    seen = set()
    stack = [obj]
    while stack:
        cur = stack.pop()
        if cur is None:
            continue
        try:
            ptr = cur.as_pointer()
        except Exception:
            try:
                ptr = id(cur)
            except Exception:
                continue
        if ptr in seen:
            continue
        seen.add(ptr)
        # Instant locale cache parks old FONT trees under the same page.
        # Multipage / presence unhide must not resurrect them.
        if not hide:
            try:
                if cur.get(_LOCALE_PARK_MARK):
                    continue
            except Exception:
                pass
        try:
            cur.hide_viewport = hide
        except Exception:
            pass
        try:
            cur.hide_render = hide
        except Exception:
            pass
        try:
            import bpy
            vl = bpy.context.view_layer
            found = vl.objects.get(cur.name) if vl is not None else None
            if found is cur:
                cur.hide_set(hide)
        except Exception:
            pass
        try:
            stack.extend(list(cur.children))
        except Exception:
            pass


def _el_has_viewport_edit(el) -> bool:
    if el is None:
        return False
    try:
        if isinstance(el, dict):
            return bool(el.get("has_viewport_edit"))
        return bool(getattr(el, "has_viewport_edit", False))
    except Exception:
        return False


def _lookup_maps_el(obj, maps):
    if obj is None or not maps:
        return None
    hier = ""
    name = ""
    try:
        hier = _obj_hierarchy_key(obj)
    except Exception:
        hier = ""
    try:
        name = (obj.ksp_ui.element_name or obj.name or "").strip()
    except Exception:
        try:
            name = (obj.name or "").strip()
        except Exception:
            name = ""
    el = None
    if hier:
        el = (maps.get("el_by_hier") or {}).get(hier)
    if el is None and name:
        el = (maps.get("el_by_name") or {}).get(name)
    return el


def repin_artwork_overlays(root, *, pixel_scale: float = 0.001, maps=None) -> int:
    """Force ConfB*/LL* pads onto the import pin after locale apply.

    Locale AP / has_viewport_edit from another language must not move
    image-locked overlays — shared artwork holes stay fixed.

    Skip the pin only for LOCAL user copies or when THIS locale's maps
    recorded a viewport edit. A leftover ``ksp_has_viewport_edit`` on the
    live object (from the language we left) must not skip the pin.
    """
    if root is None:
        return 0
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    sx = float(pixel_scale or 0.001) or 0.001
    for obj in objs:
        try:
            if _is_parked_locale_obj(obj):
                continue
            if not _is_locale_text_root(obj):
                continue
        except Exception:
            continue
        locked = False
        try:
            if obj.get("ksp_artwork_overlay") or obj.get("ksp_origin_box"):
                locked = True
        except Exception:
            locked = False
        if not locked:
            try:
                from .viewport import is_artwork_overlay
                tx = str(getattr(obj.ksp_ui, "text", "") or "")
                locked = bool(is_artwork_overlay(tx))
            except Exception:
                locked = False
        if not locked:
            continue
        try:
            if _pose_locked_by_user(obj):
                continue
            if maps is not None:
                if _el_has_viewport_edit(_lookup_maps_el(obj, maps)):
                    continue
            elif obj.get("ksp_has_viewport_edit"):
                continue
        except Exception:
            pass
        try:
            if apply_locale_layout_xy(obj, None, pixel_scale=sx):
                n += 1
        except Exception:
            continue
    return n


def _restore_layout_trs_pin(obj) -> None:
    """Shared live graphics: import R/S, not the last language's mouse scale."""
    if obj is None:
        return
    try:
        pin_sc = obj.get("ksp_layout_scale", None)
        if pin_sc is not None and len(pin_sc) >= 3:
            obj.scale = (float(pin_sc[0]), float(pin_sc[1]), float(pin_sc[2]))
    except Exception:
        pass
    try:
        pin_rot = obj.get("ksp_layout_rot", None)
        if pin_rot is not None and len(pin_rot) >= 3:
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = (
                float(pin_rot[0]), float(pin_rot[1]), float(pin_rot[2]),
            )
    except Exception:
        pass


def apply_shared_live_locale_state(root, maps, *, locale="", pixel_scale=0.001) -> int:
    """Shared live objects: apply THIS locale's maps, not the leftover pose.

    Silent viewport G/R/S/colour/material never opens a language dialog, so
    they write only ``active_locale`` RAM. Stock images and ALL-scope copies
    stay on one Blender object — without a restore, EN scale leaked onto DE.
    LOCAL copies park with the source language and are skipped here.
    """
    if root is None or not maps:
        return 0
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    text_by_hier = maps.get("text_by_hier") or {}
    text_by_name = maps.get("text_by_name") or {}
    el_by_hier = maps.get("el_by_hier") or {}
    el_by_name = maps.get("el_by_name") or {}
    sx = float(pixel_scale or 0.001) or 0.001
    from . import locale_buffers as _lb

    for obj in objs:
        try:
            if _is_parked_locale_obj(obj):
                continue
        except Exception:
            continue
        kind = ""
        user_added = False
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
            kind = str(ui.kind or "")
            user_added = bool(_obj_is_user_added(obj))
        except Exception:
            continue
        if user_added:
            try:
                if not _user_added_spans_locales(obj):
                    continue
            except Exception:
                continue
        elif kind != "image":
            continue
        if kind == "text":
            try:
                if not _is_locale_text_root(obj):
                    continue
            except Exception:
                continue
        elif kind != "image":
            continue
        _text, loc_el, _name, _hier = _resolve_locale_text_for_obj(
            obj, text_by_hier, text_by_name, el_by_hier, el_by_name,
        )
        d = _lb._copy_el_dict(loc_el) if loc_el is not None else {}
        user_edit = bool(d.get("has_viewport_edit"))
        try:
            if user_edit:
                obj["ksp_has_viewport_edit"] = True
            elif "ksp_has_viewport_edit" in obj.keys():
                del obj["ksp_has_viewport_edit"]
        except Exception:
            pass
        props = {
            "has_viewport_edit": user_edit,
            "anchored_position": d.get("anchored_position"),
            "artwork_overlay": False,
        }
        try:
            props["artwork_overlay"] = bool(
                obj.get("ksp_artwork_overlay") or obj.get("ksp_origin_box")
            )
        except Exception:
            pass
        try:
            apply_locale_position(obj, props, d or loc_el, pixel_scale=sx)
        except Exception:
            pass
        ov = d.get("user_overrides")
        if not isinstance(ov, dict):
            ov = None
        try:
            _lb.apply_material_override(obj, ov)
            if user_edit:
                _lb.apply_blender_trs_override(obj, ov, d)
            else:
                # After reimport the shared pin is the default-language
                # .ksp (EN G/R/S baked in). Unedited DE/ES/… must use
                # that language's maps / .lang RectTransform instead.
                has_trs = bool(
                    d.get("local_scale")
                    or d.get("local_rotation")
                    or d.get("scale")
                    or d.get("rotation_euler")
                )
                if has_trs:
                    try:
                        from . import layout as _layout
                        bz = obj.get("ksp_base_z", None)
                        _layout.apply_ui_local_trs(
                            obj,
                            _lb.el_as_namespace(d),
                            pixel_scale=sx,
                            base_z=None if bz is None else float(bz),
                        )
                    except Exception:
                        sc = d.get("scale") or d.get("local_scale")
                        if sc is not None and len(sc) >= 3:
                            obj.scale = (
                                float(sc[0]), float(sc[1]), float(sc[2]),
                            )
                        rot = d.get("rotation_euler")
                        if rot is not None and len(rot) >= 3:
                            obj.rotation_mode = "XYZ"
                            obj.rotation_euler = (
                                float(rot[0]), float(rot[1]), float(rot[2]),
                            )
                else:
                    _restore_layout_trs_pin(obj)
            _lb.remember_applied_overrides(obj, ov)
        except Exception:
            pass
        try:
            ui = obj.ksp_ui
            if user_edit:
                sc = d.get("local_scale") or d.get("scale")
            else:
                sc = d.get("local_scale")
                if sc is None:
                    sc = obj.get("ksp_layout_scale")
            if sc is not None and hasattr(ui, "local_scale"):
                ui.local_scale = tuple(float(x) for x in sc[:3])
        except Exception:
            pass
        col = d.get("color")
        if col is not None:
            try:
                obj.ksp_ui.color = tuple(float(x) for x in list(col)[:4])
            except Exception:
                pass
        n += 1
    return n


def ensure_parked_locale_hidden(root) -> int:
    """Re-hide every parked locale tree (after multipage / presence unhide)."""
    n = 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            if not obj.get(_LOCALE_PARK_MARK):
                continue
            if _obj_is_artwork_overlay(obj):
                continue
            # Forest roots only — _hide_tree walks descendants.
            if not obj.get(_LOCALE_PARK_BASE):
                continue
        except Exception:
            continue
        try:
            # Force hide even though mark would skip unhide path.
            stack = [obj]
            while stack:
                cur = stack.pop()
                try:
                    cur.hide_set(True)
                except Exception:
                    pass
                try:
                    cur.hide_viewport = True
                except Exception:
                    pass
                try:
                    cur.hide_render = True
                except Exception:
                    pass
                try:
                    stack.extend(list(cur.children))
                except Exception:
                    pass
            n += 1
        except Exception:
            continue
    return n


def _page_root_of(obj):
    cur = obj
    while cur is not None:
        try:
            if "ksp_page_index" in cur.keys():
                return cur
        except Exception:
            pass
        try:
            cur = cur.parent
        except Exception:
            break
    return None


def _obj_depth(o) -> int:
    d = 0
    try:
        p = o.parent
        while p is not None:
            d += 1
            p = p.parent
    except Exception:
        pass
    return d


def _obj_is_effectively_hidden(obj) -> bool:
    try:
        if obj.hide_get():
            return True
    except Exception:
        pass
    try:
        if obj.hide_viewport:
            return True
    except Exception:
        pass
    try:
        p = obj.parent
        while p is not None:
            try:
                if p.hide_get() or p.hide_viewport:
                    return True
            except Exception:
                pass
            p = p.parent
    except Exception:
        pass
    return False



def _leaf_name_matches(leaf: str, name: str, base: str) -> bool:
    """True when a hierarchy leaf refers to the same Unity GO name."""
    leaf = (leaf or "").strip()
    name = (name or "").strip()
    base = (base or "").strip() or _element_base_name(name)
    if not leaf or not name:
        return False
    if leaf == name or leaf.startswith(name + "#"):
        return True
    leaf_base = _element_base_name(leaf.split("#", 1)[0] if "#" in leaf else leaf)
    if base and leaf_base and leaf_base == base:
        return True
    return False


def _soft_locale_lookup_by_name(name, text_by_hier, text_by_name, el_by_hier, element_by_name, obj=None, locale=""):
    """Find text/el when hierarchy keys drifted after an EN rebuild.

    First visit to ES/DE after editing EN often loses the stamped
    ``ksp_hierarchy`` match (path ids / mid-path renames). Fall back to a
    unique leaf-name hit in the locale maps before orphaning the box.
    """
    if _obj_blocks_active_locale(obj, locale):
        return None, None
    name = (name or "").strip()
    if not name:
        return None, None
    base = _element_base_name(name)
    text = None
    loc_el = None
    if text_by_name:
        text = text_by_name.get(name)
        if text is None and base:
            text = text_by_name.get(base)
    if element_by_name:
        loc_el = element_by_name.get(name)
        if loc_el is None and base:
            loc_el = element_by_name.get(base)
    if text is not None and loc_el is not None:
        return text, loc_el
    hits_t = []
    hits_e = []
    try:
        for k, tx in (text_by_hier or {}).items():
            last = str(k).rsplit("/", 1)[-1]
            if _leaf_name_matches(last, name, base):
                hits_t.append(tx)
        for k, el in (el_by_hier or {}).items():
            last = str(k).rsplit("/", 1)[-1]
            if _leaf_name_matches(last, name, base):
                hits_e.append(el)
    except Exception:
        hits_t, hits_e = [], []
    if text is None and len(hits_t) == 1:
        text = hits_t[0]
    if loc_el is None and len(hits_e) == 1:
        loc_el = hits_e[0]
    if text is None and loc_el is not None:
        got = _el_get(loc_el, "text", None)
        if got is not None:
            text = got
    return text, loc_el


def _resolve_locale_text_for_obj(obj, text_by_hier, text_by_name, el_by_hier, element_by_name):
    try:
        ui = obj.ksp_ui
        name = (ui.element_name or obj.name or "").strip()
        mb = _unity_id_str(getattr(ui, "mb_path_id", ""))
    except Exception:
        return None, None, "", ""
    base = _element_base_name(name)
    hier = _obj_hierarchy_key(obj)
    text = text_by_hier.get(hier) if hier else None
    loc_el = el_by_hier.get(hier) if hier else None
    if _obj_is_user_added(obj):
        # Exact own keys only — stock ConfT3 / Header fallbacks restamp
        # the G-moved copy onto the original child.
        if text is None and name and text_by_name:
            text = text_by_name.get(name)
        if loc_el is None and name and element_by_name:
            loc_el = element_by_name.get(name)
        return text, loc_el, name, hier
    if hier and (text is None or loc_el is None):
        fuzzy_t, fuzzy_e = _fuzzy_hier_lookup(hier, text_by_hier, el_by_hier)
        if text is None:
            text = fuzzy_t
        if loc_el is None:
            loc_el = fuzzy_e
    # Nested TitleScreen Subheader is often stamped with a leaf-only key
    # ("Subheader"). Exact/fuzzy then miss the .lang ``#N/Header/Subheader``
    # path. Rebuild the GO chain from live parents and try again.
    if text is None or loc_el is None:
        try:
            parent_hier = _hierarchy_from_parents(obj)
        except Exception:
            parent_hier = ""
        if parent_hier and parent_hier != hier:
            if text is None:
                text = text_by_hier.get(parent_hier) if text_by_hier else None
            if loc_el is None:
                loc_el = el_by_hier.get(parent_hier) if el_by_hier else None
            if text is None or loc_el is None:
                fuzzy_t, fuzzy_e = _fuzzy_hier_lookup(
                    parent_hier, text_by_hier, el_by_hier
                )
                if text is None:
                    text = fuzzy_t
                if loc_el is None:
                    loc_el = fuzzy_e
            if text is not None or loc_el is not None:
                hier = parent_hier
    # mb_path_id differs per .lang AssetBundle — only trust it when the
    # target maps actually list this id (same-file / already remapped).
    if loc_el is None and mb:
        try:
            present_mb = None
            # el_by_hier values may carry mb; probe lookup then verify
            cand = _lookup_el_by_mb(el_by_hier, mb)
            if cand is not None:
                loc_el = cand
        except Exception:
            pass
    if loc_el is not None and text is None:
        got = _el_get(loc_el, "text", None)
        if got is not None and got != "":
            text = got
        elif not isinstance(loc_el, dict):
            try:
                text = getattr(loc_el, "text", None)
            except Exception:
                pass
        elif "text" in loc_el:
            text = loc_el.get("text")
    # Unique-name maps omit duplicate GO names (two "Craft Pitches").
    # Count hierarchy keys that share this Unity name; name fallback would
    # stamp one sibling's text/mb onto both, then purge deleted one.
    sib = 0
    if name:
        try:
            keys = set(el_by_hier or ()) | set(text_by_hier or ())
            for k in keys:
                last = str(k).rsplit("/", 1)[-1]
                if _leaf_name_matches(last, name, base):
                    sib += 1
                    if sib > 1:
                        break
        except Exception:
            sib = 0
    name_unique = sib <= 1
    if text is None and name_unique and text_by_name:
        text = text_by_name.get(name)
        if text is None and base:
            text = text_by_name.get(base)
    if loc_el is None and name_unique and element_by_name:
        loc_el = element_by_name.get(name) or element_by_name.get(base)
    # After EN rebuild the stamped hierarchy often no longer matches the
    # sibling .lang keys — recover a unique leaf-name hit before orphaning.
    if (text is None or loc_el is None) and name_unique and name:
        soft_t, soft_e = _soft_locale_lookup_by_name(
            name, text_by_hier, text_by_name, el_by_hier, element_by_name,
        )
        if text is None:
            text = soft_t
        if loc_el is None:
            loc_el = soft_e
    return text, loc_el, name, hier


def _apply_one_locale_text(obj, text, *, locale, pixel_scale, kb, loc_el, name="", hier=""):
    """Orphan / skip / rebuild for one text root."""
    try:
        if _is_parked_locale_obj(obj):
            # Cached for another language — do not blank or rebuild in place.
            return None
    except Exception:
        pass
    try:
        from . import locale_buffers as _lb
        if locale and _lb.is_forgotten_in_locale(obj, locale):
            text = None
    except Exception:
        pass
    try:
        if _obj_blocks_active_locale(obj, locale):
            if _obj_is_user_added(obj):
                # LOCAL duplicate: park with home language, keep G-move.
                # Do not stay live on DE/FR (that leaked copies across .lang).
                home = _obj_home_locale(obj)
                if not home:
                    try:
                        home = str(obj.get("ksp_locale_applied") or "").lower()
                    except Exception:
                        home = ""
                if home and home != (locale or "").lower():
                    try:
                        park_text_object(obj, home)
                    except Exception:
                        _hide_locale_scoped_object(obj, locale=locale)
                else:
                    _hide_locale_scoped_object(obj, locale=locale)
                return None
            _hide_locale_scoped_object(obj, locale=locale)
            return None
    except Exception:
        pass
        if text is None:
            try:
                if _obj_is_user_added(obj):
                    if _obj_blocks_active_locale(obj, locale):
                        home = _obj_home_locale(obj) or str(
                            obj.get("ksp_locale_applied") or ""
                        ).lower()
                        if home and home != (locale or "").lower():
                            park_text_object(obj, home)
                        else:
                            _hide_locale_scoped_object(obj, locale=locale)
                        return None
                    # ALL-scope copy with no row in this .lang yet — keep pose.
                    return obj
            except Exception:
                pass
        # Duplicate-named stock siblings are omitted from unique-name maps.
        # A lookup miss is not "this locale dropped the box" — keep the
        # object; apply_locale_presence still hides true absences.
        try:
            last = (hier or "").rsplit("/", 1)[-1]
            dup_hier = bool(last and "#" in last)
            dup_list = bool(name) and _count_list_names(kb, name, kind="text") > 1
            if dup_hier or dup_list:
                return obj
        except Exception:
            pass
        # Soft recover once more before parking (EN rebuild → first ES visit).
        if name:
            try:
                maps = _LAYOUT_APPLY_CTX.get("maps") or {}
                soft_t, soft_e = _soft_locale_lookup_by_name(
                    name,
                    maps.get("text_by_hier") or {},
                    maps.get("text_by_name") or {},
                    maps.get("el_by_hier") or {},
                    maps.get("el_by_name") or {},
                    obj=obj,
                    locale=locale,
                )
                if soft_t is not None:
                    text = soft_t
                    if soft_e is not None:
                        loc_el = soft_e
            except Exception:
                pass
        if text is not None:
            # Fall through to rebuild below — do NOT detach nested texts.
            pass
        else:
            try:
                p = obj.parent
                if (
                    p is not None
                    and not _is_parked_locale_obj(p)
                    and _is_locale_text_root(p)
                    and not _obj_is_artwork_overlay(obj)
                ):
                    # Nested Header/Subheader: parent rebuild adopts + refreshes.
                    return obj
            except Exception:
                pass
            # Cross-locale: park the previous language's object so a later switch
            # can wake it. Blanking here permanently erased blue overlays that
            # exist in EN/FR but not in DE (and broke selection rebind).
            # Nested ConfT stays under the parked parent (old behaviour) —
            # detaching them left live ghosts stacked on the next language.
            prev_loc = ""
            try:
                prev_loc = str(obj.get("ksp_locale_applied") or "").lower()
            except Exception:
                prev_loc = ""
            if not prev_loc:
                try:
                    from . import locale_buffers as _lb
                    if kb is not None:
                        prev_loc = _lb.get_prev_locale(kb) or ""
                except Exception:
                    prev_loc = ""
            cur = (locale or "").lower()
            if prev_loc and cur and prev_loc != cur:
                try:
                    if park_text_object(obj, prev_loc):
                        return None
                except Exception:
                    pass
            try:
                obj["ksp_locale_orphan"] = True
                obj["ksp_locale_hidden"] = True
                # The body is blanked below, so the object no longer shows the
                # locale it still claims. Leaving the stamp made the trip back
                # (en -> de -> en) hit the "already applied" shortcut and the
                # boxes stayed empty.
                obj["ksp_locale_applied"] = ""
            except Exception:
                pass
            try:
                _clear_font_bodies(obj)
            except Exception:
                pass
            try:
                _hide_tree(obj, True)
            except Exception:
                pass
            return None
    try:
        if "ksp_locale_orphan" in obj.keys():
            del obj["ksp_locale_orphan"]
    except Exception:
        pass
    try:
        if (
            not obj.get("ksp_locale_hidden")
            and str(obj.get("ksp_locale_applied", "") or "") == (locale or "")
            and str(obj.ksp_ui.text or "") == str(text or "")
            and not _font_body_blank(obj)
        ):
            return obj
    except Exception:
        pass
    # #region agent log
    _pre_state = _dbg_curve(obj)
    _pin_xy = None
    try:
        _p = obj.get("ksp_layout_xy", None)
        if _p is not None:
            _pin_xy = [round(float(_p[0]), 6), round(float(_p[1]), 6)]
    except Exception:
        _pin_xy = None
    # #endregion
    try:
        # Always go through the calibrated builder. Patching the curve in
        # place skipped wrap/fit/lead-offset calibration, so CJK stopped
        # wrapping, overlays landed off-box and bodies kept a stray newline.
        rebuilt = rebuild_text_object(
            obj,
            text,
            locale=locale,
            pixel_scale=pixel_scale,
            kb=kb,
            loc_el=loc_el,
        )
        if rebuilt is not None:
            try:
                idx = _LAYOUT_APPLY_CTX.get("rect_index")
                if idx is not None:
                    rid = str(rebuilt.ksp_ui.rect_path_id or "")
                    if rid:
                        idx[rid] = rebuilt
            except Exception:
                pass
        # #region agent log
        _dbg("A,B", "text applied (rebuild)", {
            "name": name,
            "locale": locale,
            "pin_xy": _pin_xy,
            "loc_el": bool(loc_el is not None),
            "before": _pre_state,
            "after": _dbg_curve(rebuilt) if rebuilt is not None else None,
        })
        # #endregion
        return rebuilt
    except Exception as exc:
        try:
            print("WARNING: KSP locale rebuild failed for %s: %s" % (name, exc))
        except Exception:
            pass
        return None


def apply_locale_presence(root, maps, *, kb=None, objs=None) -> int:
    """Hide what the active .lang does not ship, restore what it does.

    Translations add and drop whole boxes, so element presence is per locale.
    Returns the number of elements hidden as absent.
    """
    from . import locale_buffers as _lb

    presence = _lb.presence_from_maps(maps)
    if objs is None:
        try:
            objs = [root] + list(getattr(root, "children_recursive", []) or [])
        except Exception:
            objs = [root]
    hidden = 0
    for obj in objs:
        # Parked caches keep the same element names as the live locale —
        # treating them as "present" would _hide_tree(..., False) and stack
        # DE/IT/ES on top of the active language after an instant swap.
        try:
            if _is_parked_locale_obj(obj):
                continue
        except Exception:
            pass
        try:
            ui = obj.ksp_ui
            if not ui.is_ksp_ui:
                continue
            kind = str(ui.kind or "")
        except Exception:
            continue
        if kind not in _PRESENCE_KINDS:
            continue
        try:
            if _obj_is_user_added(obj) and _obj_blocks_active_locale(
                obj,
                (getattr(kb, "active_locale", "") or "").lower() if kb is not None else "",
            ):
                _hide_locale_scoped_object(obj)
                continue
        except Exception:
            pass
        # Images come from the base .ksp prefab. .lang files often rename
        # those GOs (ru/zh), so presence-by-name hides the page background
        # and `_hide_tree` greys the whole scene until a TOC click unhides it.
        if kind == "image":
            user_added = False
            try:
                user_added = bool(obj.get("ksp_user_added"))
            except Exception:
                user_added = False
            if not user_added:
                try:
                    if obj.get("ksp_locale_orphan"):
                        del obj["ksp_locale_orphan"]
                    if obj.get("ksp_locale_hidden"):
                        del obj["ksp_locale_hidden"]
                except Exception:
                    pass
                continue
            loc = ""
            try:
                if kb is not None:
                    loc = (getattr(kb, "active_locale", "") or "").lower()
            except Exception:
                loc = ""
            skip = False
            try:
                if loc and _lb.is_forgotten_in_locale(obj, loc):
                    skip = True
            except Exception:
                pass
            try:
                shipped = str(obj.get("ksp_shipped_locales") or "").strip()
                if shipped and loc:
                    allowed = {
                        x.strip().lower()
                        for x in shipped.split(",")
                        if x.strip()
                    }
                    if loc not in allowed:
                        skip = True
            except Exception:
                pass
            if skip:
                try:
                    obj["ksp_locale_orphan"] = True
                    obj["ksp_locale_hidden"] = True
                    _hide_tree(obj, True)
                    hidden += 1
                except Exception:
                    pass
                continue
            try:
                if obj.get("ksp_locale_hidden"):
                    _hide_tree(obj, False)
                    del obj["ksp_locale_hidden"]
            except Exception:
                pass
            try:
                if "ksp_locale_orphan" in obj.keys():
                    del obj["ksp_locale_orphan"]
            except Exception:
                pass
            continue
        hier = _obj_hierarchy_key(obj)
        try:
            name = (ui.element_name or obj.name or "").strip()
        except Exception:
            name = ""
        try:
            mb = str(getattr(ui, "mb_path_id", "") or "").strip()
        except Exception:
            mb = ""
        try:
            loc = ""
            if kb is not None:
                loc = (getattr(kb, "active_locale", "") or "").lower()
            if loc and _lb.is_forgotten_in_locale(obj, loc):
                try:
                    obj["ksp_locale_orphan"] = True
                    obj["ksp_locale_hidden"] = True
                    _hide_tree(obj, True)
                    hidden += 1
                except Exception:
                    pass
                continue
        except Exception:
            pass
        if _lb.presence_has_element(presence, hier, name, kind, mb_path_id=mb):
            try:
                if obj.get("ksp_locale_hidden"):
                    _hide_tree(obj, False)
                    del obj["ksp_locale_hidden"]
            except Exception:
                pass
            try:
                if "ksp_locale_orphan" in obj.keys():
                    del obj["ksp_locale_orphan"]
            except Exception:
                pass
            continue
        try:
            obj["ksp_locale_orphan"] = True
            obj["ksp_locale_hidden"] = True
        except Exception:
            pass
        try:
            _hide_tree(obj, True)
            hidden += 1
        except Exception:
            pass
    if kb is not None:
        try:
            _lb.sync_missing_flags(kb, maps)
        except Exception:
            pass
    return hidden


def _iter_ksp_objs(root):
    try:
        return [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        return [root] if root is not None else []


def _is_parked_text_identity_root(obj) -> bool:
    """Parked analogue of ``_is_locale_text_root`` (nested ConfB2, not FONT runs)."""
    if not _is_parked_locale_obj(obj):
        return False
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui or ui.kind != "text":
            return False
    except Exception:
        return False
    try:
        p = obj.parent
        if p is not None:
            pui = p.ksp_ui
            if pui.is_ksp_ui and pui.kind == "text":
                my_en = (ui.element_name or "").strip()
                parent_en = (pui.element_name or "").strip()
                if my_en and parent_en and my_en != parent_en:
                    return True
                return False
    except Exception:
        pass
    return True


def _live_text_named(root, name: str):
    want = (name or "").strip()
    if not want:
        return None
    for obj in _iter_ksp_objs(root):
        try:
            if not _is_locale_text_root(obj):
                continue
            en = (obj.ksp_ui.element_name or "").strip()
        except Exception:
            continue
        if en == want:
            return obj
    return None


def _parked_donor_for_name(root, name: str):
    want = (name or "").strip()
    if not want:
        return None
    hits = []
    for obj in _iter_ksp_objs(root):
        try:
            if not _is_parked_text_identity_root(obj):
                continue
            en = (obj.ksp_ui.element_name or "").strip()
        except Exception:
            continue
        if en == want:
            hits.append(obj)
    if not hits:
        return None
    hits.sort(
        key=lambda o: (0 if getattr(o, "type", "") == "FONT" else 1, _obj_depth(o))
    )
    return hits[0]


def _live_parent_for_parked_donor(root, donor):
    par = None
    try:
        par = donor.parent
    except Exception:
        par = None
    if par is None:
        return None
    if not _is_parked_locale_obj(par):
        return par
    pname = ""
    try:
        pname = (par.ksp_ui.element_name or "").strip()
    except Exception:
        pname = ""
    if pname:
        live = _live_text_named(root, pname)
        if live is not None:
            return live
    cur = par
    while cur is not None:
        try:
            if not _is_parked_locale_obj(cur):
                return cur
            cur = cur.parent
        except Exception:
            break
    return None


def _strip_park_marks_obj(obj) -> None:
    if obj is None:
        return
    try:
        if _LOCALE_PARK_MARK in obj.keys():
            del obj[_LOCALE_PARK_MARK]
    except Exception:
        pass
    try:
        if _LOCALE_PARK_BASE in obj.keys():
            del obj[_LOCALE_PARK_BASE]
    except Exception:
        pass
    for key in ("ksp_locale_orphan", "ksp_locale_hidden"):
        try:
            if key in obj.keys():
                del obj[key]
        except Exception:
            pass
    try:
        _hide_tree(obj, False)
    except Exception:
        pass


def _clone_parked_text_scaffold(src, parent):
    """Copy a parked identity object onto a live parent. Keep Unity path ids.

    Do not use ``mu_ops._copy_ui_object_tree`` — that clears ids and stamps
    ``ksp_user_added``. Do not copy children (FONT runs / nested parks).
    """
    if src is None:
        return None
    try:
        if _obj_is_user_added(src):
            return None
    except Exception:
        pass
    try:
        mw = src.matrix_world.copy()
    except Exception:
        mw = None
    new_obj = src.copy()
    try:
        if src.data is not None:
            new_obj.data = src.data.copy()
    except Exception:
        pass
    try:
        cols = list(src.users_collection)
    except Exception:
        cols = []
    for col in cols:
        try:
            col.objects.link(new_obj)
        except Exception:
            pass
    try:
        new_obj.parent = parent
    except Exception:
        pass
    if mw is not None:
        try:
            new_obj.matrix_world = mw
        except Exception:
            pass
    _strip_park_marks_obj(new_obj)
    try:
        en = (src.ksp_ui.element_name or "").strip()
        if en:
            new_obj.name = en
            new_obj.ksp_ui.element_name = en
    except Exception:
        pass
    return new_obj


def _shipped_text_names(maps):
    out = []
    seen = set()
    if not isinstance(maps, dict):
        return out
    d = maps.get("text_by_name") or {}
    if isinstance(d, dict):
        for name in d:
            n = str(name or "").strip()
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    tbh = maps.get("text_by_hier") or {}
    if isinstance(tbh, dict):
        for hier in tbh:
            n = str(hier or "").rsplit("/", 1)[-1]
            n = n.split("#", 1)[0].strip()
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    return out


def spawn_missing_shipped_texts(
    root, maps, *, locale: str = "", pixel_scale: float = 0.001, kb=None
) -> int:
    """Clone parked donors onto live parents for texts this locale ships.

    After a language that dropped ConfB2 (DE/IT), the overlay lives only in a
    parked foreign tree. Instant swap cannot wake it. Clone onto live ConfS2
    and rebuild — never wake the foreign park in place.
    """
    if root is None or not isinstance(maps, dict):
        return 0
    loc = (locale or "").lower()
    names = _shipped_text_names(maps)
    if not names:
        return 0
    pending = []
    for name in names:
        if _live_text_named(root, name) is not None:
            continue
        donor = _parked_donor_for_name(root, name)
        if donor is None:
            continue
        pending.append((name, donor))
    if not pending:
        return 0
    pending.sort(key=lambda t: _obj_depth(t[1]))
    text_by_name = maps.get("text_by_name") or {}
    el_by_name = maps.get("el_by_name") or {}
    text_by_hier = maps.get("text_by_hier") or {}
    el_by_hier = maps.get("el_by_hier") or {}
    n = 0
    for name, donor in pending:
        if _live_text_named(root, name) is not None:
            continue
        parent = _live_parent_for_parked_donor(root, donor)
        if parent is None:
            continue
        scaffold = None
        try:
            scaffold = _clone_parked_text_scaffold(donor, parent)
        except Exception:
            scaffold = None
        if scaffold is None:
            continue
        text, loc_el, _n, _h = _resolve_locale_text_for_obj(
            scaffold, text_by_hier, text_by_name, el_by_hier, el_by_name
        )
        if text is None:
            text = text_by_name.get(name)
        if loc_el is None:
            loc_el = el_by_name.get(name)
        if text is None:
            try:
                _delete_object_tree(scaffold)
            except Exception:
                pass
            continue
        rebuilt = None
        try:
            rebuilt = rebuild_text_object(
                scaffold,
                text,
                locale=loc,
                pixel_scale=pixel_scale,
                kb=kb,
                loc_el=loc_el,
                park_previous=False,
            )
        except Exception:
            rebuilt = None
        if rebuilt is None:
            try:
                _delete_object_tree(scaffold)
            except Exception:
                pass
            continue
        n += 1
    return n


def _finish_locale_apply(root, maps, *, locale, pixel_scale, kb, objs=None):
    """Images, multipage visibility, orphan hide — after all texts applied."""
    n = 0
    try:
        from . import locale_buffers as _lb0
        if kb is not None:
            _lb0.demote_mass_viewport_edits(kb)
        _lb0.repair_flat_size_deltas(root)
    except Exception:
        pass
    if isinstance(maps, dict) and "text_by_hier" in maps:
        el_by_hier = maps.get("el_by_hier") or {}
        element_by_name = maps.get("el_by_name") or {}
    else:
        el_by_hier = {}
        element_by_name = {}
    if objs is None:
        try:
            objs = [root] + list(getattr(root, "children_recursive", []) or [])
        except Exception:
            objs = [root]
    try:
        from . import locale_buffers as _lb
        for obj in objs:
            try:
                _ = obj.name
            except Exception:
                continue
            try:
                ui = obj.ksp_ui
                if not ui.is_ksp_ui or ui.kind != "image":
                    continue
            except Exception:
                continue
            hier = _obj_hierarchy_key(obj)
            name = ""
            try:
                name = (ui.element_name or obj.name or "").strip()
            except Exception:
                pass
            loc_el = el_by_hier.get(hier) if hier else None
            if loc_el is None:
                loc_el = _lookup_el_by_mb(el_by_hier, _obj_mb_str(obj))
            if loc_el is None and element_by_name and name in element_by_name:
                loc_el = element_by_name.get(name)
            if loc_el is None:
                continue
            try:
                if isinstance(loc_el, dict):
                    ap = loc_el.get("anchored_position")
                else:
                    ap = getattr(loc_el, "anchored_position", None)
                apply_locale_layout_xy(obj, ap, pixel_scale=pixel_scale)
                n += 1
            except Exception:
                pass
    except Exception:
        pass
    # Nested overlays dropped by the previous language (ConfB2 after DE/IT)
    # are not live jobs. Clone them from a parked donor onto the live parent
    # before presence / rebind, so FR/PT/RU/ZH get a real viewport object.
    try:
        spawn_missing_shipped_texts(
            root, maps, locale=locale, pixel_scale=pixel_scale, kb=kb
        )
    except Exception:
        pass
    try:
        if kb is not None:
            from . import locale_buffers as _lb_maps
            _lb_maps.apply_maps_to_ui_elements(kb, maps)
            _lb_maps.sync_missing_flags(kb, maps, locale=locale)
    except Exception:
        pass
    try:
        reveal_shipped_artwork_overlays(root, maps, locale=locale, kb=kb)
    except Exception:
        pass
    try:
        objs2 = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs2 = [root]
    # Before multipage: presence may unhide a box, page visibility gets the
    # final say on what is actually on screen.
    try:
        apply_locale_presence(root, maps, kb=kb, objs=objs2)
    except Exception:
        pass
    if kb is not None:
        try:
            if getattr(kb, "layout_mode", "") == "multipage":
                from .import_ksp import show_multipage_scope, show_multipage_index
                # Same as a TOC folder click — page visibility must win.
                scope = getattr(kb, "filter_scope_object", None)
                page = getattr(kb, "filter_page_object", None)
                if scope is not None:
                    show_multipage_scope(root, scope)
                elif page is not None:
                    show_multipage_scope(root, page)
                else:
                    show_multipage_index(
                        root, int(getattr(kb, "active_page_index", 0) or 0)
                    )
        except Exception:
            pass
    # Artwork pads stay on the import pin (ignore locale AP drift).
    # ALL-scope live copies: apply THIS locale's maps, not the leftover pose.
    try:
        apply_shared_live_locale_state(
            root, maps, locale=locale, pixel_scale=pixel_scale,
        )
    except Exception:
        pass
    try:
        repin_artwork_overlays(root, pixel_scale=pixel_scale, maps=maps)
    except Exception:
        pass

    # Page unhide walks every child — re-assert parked locale caches stay off.

    try:

        ensure_parked_locale_hidden(root)

    except Exception:

        pass
    for obj in objs2:
        try:
            if not obj.get("ksp_locale_orphan"):
                continue
            if obj.ksp_ui.is_ksp_ui and obj.ksp_ui.kind == "image":
                try:
                    if not obj.get("ksp_user_added"):
                        continue
                except Exception:
                    continue
        except Exception:
            continue
        try:
            _hide_tree(obj, True)
        except Exception:
            pass
    # Do not flatten here: baking mid-switch parks children at the previous
    # language's parent XY and retargets ksp_layout_xy, which throws away
    # Overview edits and scatters boxes on the next language.
    # The overlay list is resolved from live objects. An async switch redraws
    # it while the old text objects are still being replaced, so the boxes of
    # every rebuilt element went missing until the next toggle. Re-sync once
    # the tree is final.
    try:
        if kb is not None and getattr(kb, "show_text_boxes", False):
            sync_text_box_overlays(
                root,
                True,
                pixel_scale=float(pixel_scale or 0.001),
                scope=None,
            )
    except Exception:
        pass
    # Re-pin ui_elements.viewport_object after FONT rebuilds (None pointers
    # used to make the UI Elements list look empty / hide all texts).
    try:
        if kb is not None:
            _rebind_ui_element_viewports(kb, root)
    except Exception:
        pass
    return n


def _rebind_ui_element_viewports(kb, root) -> int:
    """Match ui_elements rows to live (non-parked) ksp_ui objects.

    After a locale park/wake the old PointerProperty still references the
    parked FONT — selection sync and the UI list then look broken.
    """
    if kb is None or root is None:
        return 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    by_mb = {}
    by_name = {}
    for obj in objs:
        try:
            if _is_parked_locale_obj(obj):
                continue
            ui = obj.ksp_ui
            if not ui.is_ksp_ui or ui.kind not in ("text", "image"):
                continue
            if ui.kind == "text" and not _is_locale_text_root(obj):
                continue
            mb = str(getattr(ui, "mb_path_id", "") or "").strip()
            name = (ui.element_name or obj.name or "").strip()
        except Exception:
            continue
        mb = _unity_id_str(mb)
        if mb and mb not in by_mb:
            by_mb[mb] = obj
        if name and name not in by_name:
            by_name[name] = obj
    name_counts = {}
    for item in kb.ui_elements:
        nm = (item.name or "").strip()
        if nm:
            name_counts[nm] = name_counts.get(nm, 0) + 1
    n = 0
    for item in kb.ui_elements:
        name = (item.name or "").strip()
        mb = ""
        try:
            mb = _unity_id_str(getattr(item, "mb_path_id", "") or "")
        except Exception:
            mb = ""
        hit = None
        if mb:
            hit = by_mb.get(mb)
        if hit is None and name and name_counts.get(name, 0) == 1:
            hit = by_name.get(name)
        try:
            if hit is not None and _is_parked_locale_obj(hit):
                hit = None
        except Exception:
            hit = None
        if hit is None:
            continue
        vo = None
        try:
            vo = item.viewport_object
        except Exception:
            vo = None
        need = False
        if vo is None:
            need = True
        else:
            try:
                _ = vo.name
                if _is_parked_locale_obj(vo) or vo != hit:
                    need = True
            except Exception:
                need = True
        if not need:
            continue
        try:
            item.viewport_object = hit
            n += 1
        except Exception:
            pass
    return n

def _normalize_locale_maps(text_by_name, element_by_name=None):
    if isinstance(text_by_name, dict) and "text_by_hier" in text_by_name:
        maps = text_by_name
        return (
            maps,
            maps.get("text_by_hier") or {},
            maps.get("text_by_name") or {},
            maps.get("el_by_hier") or {},
            maps.get("el_by_name") or element_by_name or {},
        )
    return (
        {
            "text_by_hier": {},
            "text_by_name": text_by_name or {},
            "el_by_hier": {},
            "el_by_name": element_by_name or {},
        },
        {},
        text_by_name or {},
        {},
        element_by_name or {},
    )


def collect_locale_apply_jobs(root, text_by_name, element_by_name=None):
    """Build ordered job list: visible texts first, deepest first."""
    maps, text_by_hier, text_by_name, el_by_hier, element_by_name = (
        _normalize_locale_maps(text_by_name, element_by_name)
    )
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    texts = [obj for obj in objs if _is_locale_text_root(obj)]
    texts = _purge_duplicate_text_roots(texts)
    texts.sort(key=_obj_depth, reverse=True)
    visible = []
    hidden = []
    for obj in texts:
        try:
            _ = obj.name
        except ReferenceError:
            continue
        bucket = hidden if _obj_is_effectively_hidden(obj) else visible
        bucket.append(obj)
    jobs = []
    for obj in visible + hidden:
        text, loc_el, name, hier = _resolve_locale_text_for_obj(
            obj, text_by_hier, text_by_name, el_by_hier, element_by_name
        )
        jobs.append(
            {
                "object": obj,
                "text": text,
                "loc_el": loc_el,
                "name": name,
                "hier": hier,
            }
        )
    return maps, objs, jobs


# Async locale switch job (Blender bpy is single-threaded — chunk + timer).
_LOCALE_JOB = None
_LOCALE_JOB_TOKEN = 0


def cancel_locale_apply_job():
    global _LOCALE_JOB
    _LOCALE_JOB = None
    try:
        _clear_layout_apply_ctx()
    except Exception:
        pass
    try:
        from . import locale_buffers as _lb
        _lb.release_live_sync_lock_deferred()
    except Exception:
        pass


def get_locale_apply_job():
    return _LOCALE_JOB


def start_locale_apply_job(
    root,
    maps,
    *,
    locale: str = "",
    pixel_scale: float = 0.001,
    kb=None,
):
    """Queue chunked locale apply; returns job dict (or None)."""
    global _LOCALE_JOB, _LOCALE_JOB_TOKEN
    if root is None or not maps:
        return None
    _LOCALE_JOB_TOKEN += 1
    token = _LOCALE_JOB_TOKEN
    if kb is None:
        try:
            if root.ksp_bundle.is_ksp_bundle:
                kb = root.ksp_bundle
                pixel_scale = float(
                    getattr(kb, "pixel_scale", pixel_scale) or pixel_scale
                )
        except Exception:
            kb = None
    try:
        from . import locale_buffers as _lb
        _lb.set_live_sync_lock(True)
        if kb is not None:
            # Only page-wide flag bursts are dropped (a depsgraph echo of our
            # own rebuild). Individual moves the user made stay authoritative.
            _lb.demote_mass_viewport_edits(kb)
            _lb.sanitize_locale_spacing(maps)
    except Exception:
        pass
    try:
        stamp_live_user_moves(root, pixel_scale=float(pixel_scale or 0.001))
    except Exception:
        pass

    loc = (locale or "").lower()
    prev = ""
    try:
        from . import locale_buffers as _lb
        if kb is not None:
            prev = _lb.get_prev_locale(kb) or ""
            if not prev:
                prev = str(
                    getattr(kb, "active_locale", "")
                    or getattr(kb, "locale", "")
                    or ""
                ).lower()
    except Exception:
        prev = ""

    # Instant path: wake parked trees from a previous visit.
    if loc and try_instant_locale_swap(root, loc, from_locale=prev):
        _set_layout_apply_ctx(root, maps, kb)
        _LOCALE_JOB = {
            "token": token,
            "root": root,
            "kb": kb,
            "maps": maps,
            "objs": None,
            "jobs": [],
            "index": 0,
            "done": 0,
            "locale": loc,
            "pixel_scale": float(pixel_scale or 0.001),
            "finished": False,
            "instant": True,
        }
        return _LOCALE_JOB

    maps_n, objs, jobs = collect_locale_apply_jobs(root, maps)
    _set_layout_apply_ctx(root, maps_n, kb)
    _LOCALE_JOB = {
        "token": token,
        "root": root,
        "kb": kb,
        "maps": maps_n,
        "objs": objs,
        "jobs": jobs,
        "index": 0,
        "done": 0,
        "locale": locale or "",
        "pixel_scale": float(pixel_scale or 0.001),
        "finished": False,
        "instant": False,
    }
    return _LOCALE_JOB


def _object_alive(obj) -> bool:
    if obj is None:
        return False
    try:
        _ = obj.name
        return True
    except ReferenceError:
        return False
    except Exception:
        return False


def process_locale_apply_chunk(chunk_size: int = 6) -> bool:
    """Process up to ``chunk_size`` texts. Returns True when job fully done."""
    global _LOCALE_JOB
    job = _LOCALE_JOB
    if not job or job.get("finished"):
        return True
    jobs = job.get("jobs") or []
    i = int(job.get("index") or 0)
    end = min(i + max(1, int(chunk_size)), len(jobs))
    locale = job.get("locale") or ""
    pixel_scale = float(job.get("pixel_scale") or 0.001)
    kb = job.get("kb")
    while i < end:
        entry = jobs[i]
        i += 1
        obj = entry.get("object")
        if not _object_alive(obj):
            continue
        try:
            rebuilt = _apply_one_locale_text(
                obj,
                entry.get("text"),
                locale=locale,
                pixel_scale=pixel_scale,
                kb=kb,
                loc_el=entry.get("loc_el"),
                name=entry.get("name") or "",
                hier=entry.get("hier") or "",
            )
        except ReferenceError:
            continue
        except Exception as exc:
            try:
                print("WARNING: KSP locale chunk item failed: %s" % exc)
            except Exception:
                pass
            continue
        if rebuilt is not None:
            job["done"] = int(job.get("done") or 0) + 1
    job["index"] = i
    if i >= len(jobs):
        try:
            # Re-walk tree — rebuilds invalidate the objs snapshot from start.
            extra = _finish_locale_apply(
                job.get("root"),
                job.get("maps") or {},
                locale=locale,
                pixel_scale=pixel_scale,
                kb=kb,
                objs=None,
            )
            job["done"] = int(job.get("done") or 0) + int(extra or 0)
        except Exception:
            pass
        job["finished"] = True
        _LOCALE_JOB = None
        try:
            _clear_layout_apply_ctx()
        except Exception:
            pass
        try:
            from . import locale_buffers as _lb
            if kb is not None and locale:
                _lb.set_prev_locale(kb, locale)
            _lb.release_live_sync_lock_deferred()
        except Exception:
            pass
        return True
    return False


def apply_text_map_to_viewport(
    root,
    text_by_name,
    locale: str = "",
    pixel_scale: float = 0.001,
    element_by_name=None,
    async_apply: bool = False,
):
    """Apply locale texts to viewport.

    ``async_apply=True`` queues a chunked job (UI stays responsive + progress).
    Import / scripts should keep the default synchronous path.
    """
    if root is None or not text_by_name:
        return 0
    maps, _th, _tn, _eh, _en = _normalize_locale_maps(text_by_name, element_by_name)
    kb = None
    try:
        if root.ksp_bundle.is_ksp_bundle:
            kb = root.ksp_bundle
            pixel_scale = float(getattr(kb, "pixel_scale", pixel_scale) or pixel_scale)
    except Exception:
        kb = None

    # UI Elements list is synced after the viewport swap (_finish_locale_apply).
    if async_apply:
        job = start_locale_apply_job(
            root, maps, locale=locale, pixel_scale=pixel_scale, kb=kb
        )
        return len(job.get("jobs") or []) if job else 0

    from . import locale_buffers as _lb
    acquired = False
    try:
        if not _lb.is_live_sync_locked():
            _lb.set_live_sync_lock(True)
            acquired = True
    except Exception:
        acquired = False
    try:
        loc = (locale or "").lower()
        prev = ""
        try:
            if kb is not None:
                prev = _lb.get_prev_locale(kb) or ""
        except Exception:
            prev = ""
        try:
            stamp_live_user_moves(root, pixel_scale=float(pixel_scale or 0.001))
        except Exception:
            pass
        if loc and try_instant_locale_swap(root, loc, from_locale=prev):
            n = _finish_locale_apply(
                root, maps, locale=loc, pixel_scale=pixel_scale, kb=kb, objs=None,
            )
            try:
                if kb is not None:
                    _lb.set_prev_locale(kb, loc)
            except Exception:
                pass
            return max(int(n or 0), 1)

        maps_n, objs, jobs = collect_locale_apply_jobs(root, maps, element_by_name)
        _set_layout_apply_ctx(root, maps_n, kb)
        n = 0
        for entry in jobs:
            obj = entry.get("object")
            try:
                _ = obj.name
            except Exception:
                continue
            rebuilt = _apply_one_locale_text(
                obj,
                entry.get("text"),
                locale=locale,
                pixel_scale=pixel_scale,
                kb=kb,
                loc_el=entry.get("loc_el"),
                name=entry.get("name") or "",
                hier=entry.get("hier") or "",
            )
            if rebuilt is not None:
                n += 1
        n += _finish_locale_apply(
            root,
            maps_n,
            locale=locale,
            pixel_scale=pixel_scale,
            kb=kb,
            objs=objs,
        )
        try:
            if kb is not None and loc:
                _lb.set_prev_locale(kb, loc)
        except Exception:
            pass
        return n
    finally:
        try:
            _clear_layout_apply_ctx()
        except Exception:
            pass
        if acquired:
            try:
                _lb.release_live_sync_lock_deferred()
            except Exception:
                pass

# Viewport-only text-box preview (Show Text Boxes). Not part of export —
# RectTransform size_delta lives on ksp_ui / ui_elements. Drawn via GPU so
# nothing appears under texts in the Outliner.
_TEXT_BOX_DRAW = {
    "handler": None,
    "entries": [],  # [{"name": str, "sx": float}, ...] resolved live from objects
}


def _font_text_box_local_rect(obj, sx):
    """Pivot-local preview rect from the live FONT text_boxes (Unity crect).

    Show Text Boxes used to draw from size_delta × pivot only. That ignored
    TMP margin, face_pad and BLOCK_NUDGE baked into text_boxes — cyan frames
    sat ~2–5 px left of glyphs and looked misaligned vs blue/white headers
    while EEVEE renders (and KSPEDIAPBS refs) matched.
    """
    try:
        if getattr(obj, "type", "") != "FONT" or obj.data is None:
            return None
        tb = obj.data.text_boxes[0]
        x0 = float(tb.x)
        w = max(float(tb.width), 0.0)
        x1 = x0 + w if w > 1e-9 else x0
        y1 = float(tb.y)
        h = abs(float(tb.height))
        if h < 1e-8:
            try:
                ui = obj.ksp_ui
                sd = tuple(ui.size_delta or (0.0, 0.0))
                if len(sd) > 1:
                    h = abs(float(sd[1])) * float(sx)
                if h < 1e-8:
                    w_sd = abs(float(sd[0])) * float(sx)
                    if w < 1e-8 and w_sd > 1e-8:
                        w = w_sd
                        x1 = x0 + w
            except Exception:
                pass
            if h < 1e-8:
                try:
                    from . import locale_buffers as _lb
                    cs = _lb.content_size_of(obj)
                    if cs is not None and len(cs) > 1:
                        h = abs(float(cs[1])) * float(sx)
                        if w < 1e-8 and abs(float(cs[0])) > 1.0:
                            w = abs(float(cs[0])) * float(sx)
                            x1 = x0 + w
                except Exception:
                    pass
        # Blender TOP layout: y is the box top; glyphs hang in −Y.
        y0 = y1 - h if h > 1e-8 else y1
        if (x1 - x0) < 1e-8 and (y1 - y0) < 1e-8:
            return None
        return x0, y0, x1, y1
    except Exception:
        return None


def _clear_legacy_text_box_meshes():
    """Remove old mesh overlays from earlier addon builds (Outliner clutter)."""
    import bpy

    doomed = []
    try:
        for o in bpy.data.objects:
            try:
                if o.get("ksp_text_box_overlay"):
                    doomed.append(o)
            except Exception:
                continue
    except Exception:
        return
    for o in doomed:
        try:
            data = getattr(o, "data", None)
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None and getattr(data, "users", 1) == 0:
                try:
                    bpy.data.meshes.remove(data)
                except Exception:
                    pass
        except Exception:
            pass


def _text_box_draw_callback():
    """POST_VIEW: wireframe RectTransform boxes (shadow + rim + double stroke)."""
    entries = _TEXT_BOX_DRAW.get("entries") or []
    if not entries:
        return
    try:
        import bpy
        import gpu
        from gpu_extras.batch import batch_for_shader
        from mathutils import Vector
    except Exception:
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    try:
        gpu.state.line_width_set(2.0)
    except Exception:
        pass

    def _rect_lines(mw, x0, y0, x1, y1, z):
        corners = [
            mw @ Vector((x0, y0, z)),
            mw @ Vector((x1, y0, z)),
            mw @ Vector((x1, y1, z)),
            mw @ Vector((x0, y1, z)),
        ]
        coords = []
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
            coords.append(tuple(corners[a]))
            coords.append(tuple(corners[b]))
        return coords

    def _draw_color(coords, rgba):
        if not coords:
            return
        try:
            batch = batch_for_shader(shader, "LINES", {"pos": coords})
            shader.bind()
            shader.uniform_float("color", rgba)
            batch.draw(shader)
        except Exception:
            pass

    for entry in entries:
        name = entry.get("name") or ""
        sx = float(entry.get("sx") or 0.001)
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            if obj.hide_get() or obj.hide_viewport:
                continue
        except Exception:
            pass
        try:
            scene = bpy.context.scene
            if scene is not None and obj.name not in scene.objects:
                continue
        except Exception:
            pass
        try:
            ui = obj.ksp_ui
            sd = tuple(ui.size_delta or (0.0, 0.0))
            pivot = tuple(ui.pivot or (0.5, 0.5))
            mw = obj.matrix_world.copy()
        except Exception:
            continue
        origin_box = False
        try:
            origin_box = bool(obj.get("ksp_origin_box"))
        except Exception:
            origin_box = False
        if origin_box:
            try:
                bbs = [Vector(c) for c in obj.bound_box]
                x0 = min(v.x for v in bbs)
                x1 = max(v.x for v in bbs)
                y0 = min(v.y for v in bbs)
                y1 = max(v.y for v in bbs)
                if (x1 - x0) < 1e-6 and (y1 - y0) < 1e-6:
                    origin_box = False
            except Exception:
                origin_box = False
        if not origin_box:
            local_rect = _font_text_box_local_rect(obj, sx)
            if local_rect is not None:
                x0, y0, x1, y1 = local_rect
                w = max(float(x1) - float(x0), 0.0)
                h = max(float(y1) - float(y0), 0.0)
            else:
                try:
                    w = abs(float(sd[0])) * sx
                    h = abs(float(sd[1])) * sx if len(sd) > 1 else 0.0
                except Exception:
                    continue
                if h < 1e-5:
                    try:
                        from . import locale_buffers as _lb
                        cs = _lb.content_size_of(obj)
                        if cs is not None and abs(float(cs[1])) > 1.0:
                            if w < 1e-5:
                                w = abs(float(cs[0])) * sx
                            h = abs(float(cs[1])) * sx
                    except Exception:
                        pass
                if w < 1e-5 and h < 1e-5:
                    continue
                px = float(pivot[0]) if pivot else 0.5
                py = float(pivot[1]) if len(pivot) > 1 else 0.5
                x0, x1 = -px * w, (1.0 - px) * w
                y0, y1 = -py * h, (1.0 - py) * h
        else:
            w = max(float(x1) - float(x0), 0.0)
            h = max(float(y1) - float(y0), 0.0)
        pad = max(sx * 2.0, 0.0004)
        shadow = max(sx * 3.0, 0.0006)
        inset = pad * 0.45

        _draw_color(
            _rect_lines(
                mw, x0 + shadow, y0 - shadow, x1 + shadow, y1 - shadow, 0.001
            ),
            (0.05, 0.05, 0.05, 0.55),
        )
        _draw_color(
            _rect_lines(mw, x0 - pad, y0 - pad, x1 + pad, y1 + pad, 0.0022),
            (1.0, 1.0, 1.0, 0.95),
        )
        _draw_color(
            _rect_lines(mw, x0, y0, x1, y1, 0.0025),
            (0.25, 0.9, 1.0, 1.0),
        )
        _draw_color(
            _rect_lines(
                mw, x0 + inset, y0 + inset, x1 - inset, y1 - inset, 0.0026
            ),
            (0.25, 0.9, 1.0, 1.0),
        )

        # Edit Text Boxes: white fill + cyan rim disks on mid-edges (GPU).
        # Empties are only hit-targets; visuals must match the dashed boxes.
        if entry.get("edit"):
            try:
                import math
                r = max(min(w, h) * 0.04, sx * 4.0)
                mids = (
                    (x0, (y0 + y1) * 0.5, 0.003),
                    (x1, (y0 + y1) * 0.5, 0.003),
                    ((x0 + x1) * 0.5, y0, 0.003),
                    ((x0 + x1) * 0.5, y1, 0.003),
                )
                for mx, my, mz in mids:
                    ring = []
                    fill_tris = []
                    cx = mw @ Vector((mx, my, mz))
                    segs = 16
                    for i in range(segs):
                        a0 = (i / segs) * math.tau
                        a1 = ((i + 1) / segs) * math.tau
                        p0 = mw @ Vector(
                            (mx + math.cos(a0) * r, my + math.sin(a0) * r, mz)
                        )
                        p1 = mw @ Vector(
                            (mx + math.cos(a1) * r, my + math.sin(a1) * r, mz)
                        )
                        ring.extend([tuple(p0), tuple(p1)])
                        fill_tris.extend([tuple(cx), tuple(p0), tuple(p1)])
                    try:
                        batch = batch_for_shader(
                            shader, "TRIS", {"pos": fill_tris}
                        )
                        shader.bind()
                        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.95))
                        batch.draw(shader)
                    except Exception:
                        pass
                    _draw_color(ring, (0.25, 0.9, 1.0, 1.0))
            except Exception:
                pass

    try:
        gpu.state.blend_set("NONE")
        gpu.state.depth_test_set("NONE")
        gpu.state.line_width_set(1.0)
    except Exception:
        pass


def _ensure_text_box_handler(enable: bool):
    import bpy

    handler = _TEXT_BOX_DRAW.get("handler")
    if enable:
        if handler is None:
            _TEXT_BOX_DRAW["handler"] = bpy.types.SpaceView3D.draw_handler_add(
                _text_box_draw_callback, (), "WINDOW", "POST_VIEW"
            )
        for area in getattr(bpy.context.screen, "areas", []) or []:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    else:
        if handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
            except Exception:
                pass
            _TEXT_BOX_DRAW["handler"] = None
        _TEXT_BOX_DRAW["entries"] = []
        for area in getattr(bpy.context.screen, "areas", []) or []:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def sync_text_box_overlays(root, show: bool, pixel_scale: float = 0.001, scope=None) -> int:
    """Toggle RectTransform box preview for KSPedia texts.

    Draws in the viewport via GPU (no mesh objects → clean Outliner).
    Export never uses these boxes — only ``size_delta`` on UI properties.
    """
    import bpy

    _clear_legacy_text_box_meshes()
    try:
        from . import locale_buffers as _lb
        _lb.repair_flat_size_deltas(root)
    except Exception:
        pass

    if not show or root is None:
        _ensure_text_box_handler(False)
        try:
            _clear_text_box_edit_handles(root)
        except Exception:
            pass
        return 0

    def _under(obj, ancestor):
        if ancestor is None:
            return True
        cur = obj
        while cur is not None:
            if cur == ancestor:
                return True
            cur = cur.parent
        return False

    try:
        sx = float(pixel_scale) if pixel_scale else 0.001
    except Exception:
        sx = 0.001

    entries = []
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    # Edit Text Boxes (empties + drag) is disabled — always clear leftover handles.
    try:
        kb = root.ksp_bundle
        try:
            if bool(getattr(kb, "edit_text_boxes", False)):
                kb["edit_text_boxes"] = False
        except Exception:
            pass
        if scope is None:
            scope = (
                getattr(kb, "filter_page_object", None)
                or getattr(kb, "filter_scope_object", None)
            )
    except Exception:
        pass
    try:
        _clear_text_box_edit_handles(root)
    except Exception:
        pass
    for obj in objs:
        if not _is_locale_text_root(obj):
            continue
        if scope is not None and not _under(obj, scope):
            continue
        try:
            if obj.get("ksp_locale_orphan"):
                continue
            if obj.hide_get() or obj.hide_viewport:
                continue
        except Exception:
            pass
        try:
            ui = obj.ksp_ui
            sd = tuple(ui.size_delta or (0.0, 0.0))
        except Exception:
            continue
        try:
            w = abs(float(sd[0])) * sx
            h = abs(float(sd[1])) * sx if len(sd) > 1 else 0.0
        except Exception:
            continue
        if w < 1e-5 and h < 1e-5:
            continue
        entries.append({"name": obj.name, "sx": sx, "edit": False})

    _TEXT_BOX_DRAW["entries"] = entries
    _ensure_text_box_handler(bool(entries))
    return len(entries)


def resync_text_box_overlays_all() -> int:
    """Rebuild GPU text-box overlays after undo/redo (object IDs change)."""
    import bpy

    try:
        from . import locale_buffers as _lb
        if _lb.is_live_sync_locked():
            return 0
    except Exception:
        pass
    try:
        if get_locale_apply_job() is not None:
            return 0
    except Exception:
        pass
    merged = []
    any_show = False
    for obj in bpy.data.objects:
        try:
            kb = obj.ksp_bundle
            if not kb.is_ksp_bundle:
                continue
            if not getattr(kb, "show_text_boxes", False):
                continue
        except Exception:
            continue
        any_show = True
        try:
            sync_text_box_overlays(
                obj,
                True,
                pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
                scope=None,
            )
            merged.extend(list(_TEXT_BOX_DRAW.get("entries") or []))
        except Exception:
            continue
    if not any_show:
        _ensure_text_box_handler(False)
        return 0
    _TEXT_BOX_DRAW["entries"] = merged
    _ensure_text_box_handler(bool(merged))
    try:
        for area in getattr(bpy.context.screen, "areas", []) or []:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    except Exception:
        pass
    return len(merged)


_TB_HANDLE_TAG = "ksp_tb_handle"
_TB_HANDLE_OWNER = "ksp_tb_owner"
_TB_HANDLE_EDGE = "ksp_tb_edge"


def _clear_text_box_edit_handles(root=None) -> None:
    """Remove every text-box handle in the file (including orphans off-root)."""
    import bpy
    doomed = []
    for obj in list(bpy.data.objects):
        try:
            if obj.get(_TB_HANDLE_TAG):
                doomed.append(obj)
        except Exception:
            continue
    for obj in doomed:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def sync_text_box_edit_handles(root, enable: bool, pixel_scale: float = 0.001, scope=None) -> int:
    """Edit Text Boxes is disabled — only clear leftover TBH_* empties."""
    _clear_text_box_edit_handles(root)
    return 0


def apply_text_box_handle_drag(handle) -> bool:
    """Edit Text Boxes disabled — ignore leftover handles."""
    return False


def locale_enum_items(self, context):
    csv = ""
    try:
        csv = getattr(self, "available_locales", "") or ""
    except Exception:
        csv = ""
    locs = [x.strip() for x in csv.split(",") if x.strip()]
    # Stable alphabetical order — never reshuffle by active locale.
    locs = order_locales(locs, "")
    if not locs:
        try:
            preferred = (getattr(self, "locale", "") or "").strip().lower()
        except Exception:
            preferred = ""
        locs = [preferred or "en-us"]
    # Always at least one entry so the Locale row stays usable.
    return [(loc, loc, "KSPedia locale %s" % loc, i) for i, loc in enumerate(locs)]
