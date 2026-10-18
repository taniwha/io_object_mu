# temporary patch script — delete after use
from pathlib import Path

path = Path(__file__).with_name("locale_switch.py")
text = path.read_text(encoding="utf-8")
start = text.find("def apply_text_map_to_viewport(")
end = text.find("\n# Viewport-only text-box preview")
if start < 0 or end < 0:
    raise SystemExit("markers not found %s %s" % (start, end))

new = r'''def _obj_depth(o) -> int:
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


def _can_inplace_locale_text(obj) -> bool:
    """Single FONT root without legacy rich-run FONT children."""
    try:
        if getattr(obj, "type", "") != "FONT" or obj.data is None:
            return False
    except Exception:
        return False
    try:
        for c in obj.children:
            if getattr(c, "type", "") == "FONT":
                return False
    except Exception:
        return False
    return True


def _try_inplace_locale_text(obj, new_text, *, locale, pixel_scale, kb, loc_el):
    """Update body in place — avoids delete/create (main freeze source)."""
    if not _can_inplace_locale_text(obj):
        return None
    from .tmp_markup import parse_tmp_rich_text
    from . import locale_buffers

    try:
        live_state = locale_buffers.snapshot_object_el_state(
            obj, pixel_scale=pixel_scale
        )
        loc_el = locale_buffers.merge_live_into_loc_el(live_state, loc_el)
    except Exception:
        live_state = {}
    item = _find_element_item(kb, obj)
    props = _snapshot_text_props(obj, item, loc_el=loc_el)
    try:
        parsed = parse_tmp_rich_text(new_text or "")
        display = parsed.plain or ""
    except Exception:
        display = new_text or ""
    try:
        from . import viewport as _vp
        display = _vp._figure_space_indent_lines(display) or display
    except Exception:
        pass
    try:
        obj.data.body = display
    except Exception:
        return None
    try:
        obj["ksp_text_display"] = display
        obj["ksp_locale_applied"] = locale or ""
    except Exception:
        pass
    _apply_ksp_ui(obj, props, new_text)
    try:
        ui = obj.ksp_ui
        ui.size_delta = props["size_delta"][:2]
        ui.anchored_position = props["anchored_position"][:2]
        ui.font_size = props["font_size"]
        ui.font_family = props["font_family"]
        ui.text = new_text or ""
    except Exception:
        pass
    try:
        locale_buffers.apply_viewport_el_state(
            obj, loc_el if loc_el is not None else live_state
        )
    except Exception:
        pass
    if item is not None:
        try:
            item.text = new_text or ""
            item.viewport_object = obj
        except Exception:
            pass
    return obj


def _resolve_locale_text_for_obj(obj, text_by_hier, text_by_name, el_by_hier, element_by_name):
    try:
        ui = obj.ksp_ui
        name = (ui.element_name or obj.name or "").strip()
    except Exception:
        return None, None, "", ""
    base = _element_base_name(name)
    hier = _obj_hierarchy_key(obj)
    text = text_by_hier.get(hier) if hier else None
    loc_el = el_by_hier.get(hier) if hier else None
    if text is None:
        text = text_by_name.get(name)
        if text is None and base:
            text = text_by_name.get(base)
    if loc_el is None and element_by_name:
        loc_el = element_by_name.get(name) or element_by_name.get(base)
    return text, loc_el, name, hier


def _apply_one_locale_text(obj, text, *, locale, pixel_scale, kb, loc_el, name="", hier=""):
    """Orphan / skip / inplace / full rebuild for one text root."""
    if text is None:
        try:
            obj["ksp_locale_orphan"] = True
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
    # Already showing this locale text — only refresh viewport overrides.
    try:
        if (
            str(obj.get("ksp_locale_applied", "") or "") == (locale or "")
            and str(obj.ksp_ui.text or "") == str(text or "")
        ):
            from . import locale_buffers as _lb
            if loc_el is not None:
                _lb.apply_viewport_el_state(obj, loc_el)
            return obj
    except Exception:
        pass
    try:
        rebuilt = _try_inplace_locale_text(
            obj,
            text,
            locale=locale,
            pixel_scale=pixel_scale,
            kb=kb,
            loc_el=loc_el,
        )
        if rebuilt is not None:
            return rebuilt
        return rebuild_text_object(
            obj,
            text,
            locale=locale,
            pixel_scale=pixel_scale,
            kb=kb,
            loc_el=loc_el,
        )
    except Exception as exc:
        try:
            print("WARNING: KSP locale rebuild failed for %s: %s" % (name, exc))
        except Exception:
            pass
        return None


def _finish_locale_apply(root, maps, *, locale, pixel_scale, kb, objs=None):
    """Images, multipage visibility, orphan hide — after all texts applied."""
    n = 0
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
            if loc_el is None and element_by_name:
                loc_el = element_by_name.get(name)
            if loc_el is None:
                continue
            try:
                _lb.apply_viewport_el_state(obj, loc_el)
                n += 1
            except Exception:
                pass
    except Exception:
        pass
    if kb is not None:
        try:
            if getattr(kb, "layout_mode", "") == "multipage":
                from .import_ksp import show_multipage_scope, show_multipage_index
                scope = getattr(kb, "filter_scope_object", None)
                if scope is not None:
                    show_multipage_scope(root, scope)
                else:
                    show_multipage_index(
                        root, int(getattr(kb, "active_page_index", 0) or 0)
                    )
        except Exception:
            pass
    try:
        objs2 = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs2 = [root]
    for obj in objs2:
        try:
            if not obj.get("ksp_locale_orphan"):
                continue
        except Exception:
            continue
        try:
            _hide_tree(obj, True)
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
    maps_n, objs, jobs = collect_locale_apply_jobs(root, maps)
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
    }
    return _LOCALE_JOB


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
            job["done"] = int(job.get("done") or 0) + 1
    job["index"] = i
    if i >= len(jobs):
        try:
            extra = _finish_locale_apply(
                job.get("root"),
                job.get("maps") or {},
                locale=locale,
                pixel_scale=pixel_scale,
                kb=kb,
                objs=job.get("objs"),
            )
            job["done"] = int(job.get("done") or 0) + int(extra or 0)
        except Exception:
            pass
        job["finished"] = True
        _LOCALE_JOB = None
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

    if async_apply:
        job = start_locale_apply_job(
            root, maps, locale=locale, pixel_scale=pixel_scale, kb=kb
        )
        return len(job.get("jobs") or []) if job else 0

    maps_n, objs, jobs = collect_locale_apply_jobs(root, maps, element_by_name)
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
    return n


'''

path.write_text(text[:start] + new + text[end + 1 :], encoding="utf-8")
import ast

ast.parse(path.read_text(encoding="utf-8"))
print("OK", path)
