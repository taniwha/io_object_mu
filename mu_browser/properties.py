# vim:ts=4:et
# <pep8 compliant>


import unicodedata
import re
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup, WindowManager

# Cache dla kategorii - używamy słownika z timestampem
_CATEGORY_CACHE = {
    'items': None,
    'timestamp': 0,
    'loading': False
}

def _category_items(self, context):
    """Pobiera listę kategorii z cache lub ładuje w tle"""
    import time
    
    # Jeśli już ładujemy, zwróć poprzednią wartość lub domyślną
    if _CATEGORY_CACHE['loading']:
        if _CATEGORY_CACHE['items']:
            return _CATEGORY_CACHE['items']
        return [("Other", "Other", "", 0)]
    
    # Jeśli cache jest świeży (mniej niż 2 sekundy), użyj go
    if _CATEGORY_CACHE['items'] and (time.time() - _CATEGORY_CACHE['timestamp'] < 2.0):
        return _CATEGORY_CACHE['items']
    
    try:
        _CATEGORY_CACHE['loading'] = True
        
        # Spróbuj załadować kategorie
        try:
            from . import catalog
            cats = catalog.categories()
        except Exception as e:
            print(f"[mu_browser] Błąd ładowania katalogów: {e}")
            cats = []
        
        # Jeśli nie ma kategorii, spróbuj pobrać aktualną wartość
        if not cats:
            try:
                current = str(getattr(self, "category", ""))
            except Exception:
                current = ""
            
            # Jeśli current to '0' lub puste, użyj "Other"
            if not current or current == "0":
                cats = ["Other"]
            else:
                cats = [current]
        
        # Unique ids; label shows live part count when available
        items = []
        seen = set()
        for c in cats:
            if c and c not in seen:
                seen.add(c)
                label = c
                try:
                    # Read-only cache lookup — must NOT call parts_in_category()
                    # (that can schedule a scan and steal/break the blue progress bar).
                    n = int(catalog.category_part_count(c))
                    if n > 0:
                        label = "%s (%d)" % (c, n)
                except Exception:
                    pass
                items.append((c, label, "", len(items)))
        
        # Jeśli nadal brak elementów, dodaj "Other"
        if not items:
            items = [("Other", "Other", "", 0)]
        
        # Zapisz w cache z timestampem
        _CATEGORY_CACHE['items'] = items
        _CATEGORY_CACHE['timestamp'] = time.time()
        
        return items
        
    except Exception as e:
        print(f"[mu_browser] Błąd w _category_items: {e}")
        return [("Other", "Other", "", 0)]
    
    finally:
        _CATEGORY_CACHE['loading'] = False

def _reset_part_selection(br):
    """Resetuje wybór części i czyści miniaturkę"""
    if br is None:
        return
    
    # Resetuj indeks
    br.parts_index = 0
    try:
        br.preview_limit = 64
    except Exception:
        pass
    
    # Wyczyść part_preview - to wymusi odświeżenie
    try:
        # Najpierw ustaw na pusty string
        br.part_preview = ""
    except Exception:
        pass
    
    # Jeśli są części, ustaw na pierwszą
    if len(br.parts) > 0:
        try:
            br.part_preview = _enum_cache_string("PART_0")
        except Exception:
            pass

# category name → last parts_index (session memory for 8×8 grid)
_CAT_LAST_INDEX = {}
_LAST_CATEGORY = ""


def _remember_category_index(br):
    try:
        cat = str(getattr(br, "category", "") or "")
        idx = int(getattr(br, "parts_index", 0) or 0)
        if cat:
            _CAT_LAST_INDEX[cat] = idx
    except Exception:
        pass


def _restore_category_index(br):
    """Restore last parts_index for this category (selection; scroll is Blender-limited)."""
    try:
        cat = str(getattr(br, "category", "") or "")
        n = len(br.parts)
        if not cat or n <= 0:
            return
        idx = int(_CAT_LAST_INDEX.get(cat, 0) or 0)
        if idx < 0 or idx >= n:
            idx = 0
        br.parts_index = idx
        try:
            target = _enum_cache_string("PART_%d" % idx)
            br.part_preview = target
        except Exception:
            try:
                br.part_preview = "PART_%d" % idx
            except Exception:
                pass
    except Exception:
        pass


def _update_category(self, context):
    """Aktualizacja kategorii — odświeża listę i przywraca ostatni index w tej kategorii."""
    global _LAST_CATEGORY
    try:
        # Zapamiętaj index poprzedniej kategorii (przed rebuild listy)
        br = getattr(context.window_manager, "ksp_mu_browser", None)
        if br is not None and _LAST_CATEGORY:
            try:
                _CAT_LAST_INDEX[_LAST_CATEGORY] = int(getattr(br, "parts_index", 0) or 0)
            except Exception:
                pass

        _CATEGORY_CACHE['items'] = None
        _CATEGORY_CACHE['timestamp'] = 0

        from . import operators
        operators.refresh_part_list(context)
        from . import thumbnails
        thumbnails.invalidate_ksp_thumbs_index()
        thumbnails.schedule_ksp_thumbs_index_build(force=True)
        try:
            thumbnails.reset_preview_stream(
                getattr(context.window_manager, "ksp_mu_browser", None)
            )
        except Exception:
            pass
        try:
            _PREVIEW_ENUM_CACHE["sig"] = None
            _PREVIEW_ENUM_CACHE["items"] = None
        except Exception:
            pass

        br = getattr(context.window_manager, "ksp_mu_browser", None)
        if br is None:
            return

        cat = str(getattr(br, "category", "") or "")
        _LAST_CATEGORY = cat
        # Przywróć ostatni wybór w tej kategorii (selection). Scroll 8×8
        # template_icon_view nie ma publicznego API — Blender resetuje go sam.
        try:
            _restore_category_index(br)
        except Exception:
            _reset_part_selection(br)

        if context.area:
            context.area.tag_redraw()

    except Exception as e:
        print(f"[mu_browser] Błąd w _update_category: {e}")


def _safe_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""
    value = (
        value
        .replace("\u2018", "'")   # ‘
        .replace("\u2019", "'")   # ’
        .replace("\u201c", '"')   # “
        .replace("\u201d", '"')   # ”
        .replace("\u2013", "-")   # –
        .replace("\u2014", "-")   # —
        .replace("\u2026", "...") # …
        .replace("\xa0", " ")     # non-breaking space
    )
    value = unicodedata.normalize("NFKC", value)
    value = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C" or ch in "\t\n")
    if len(value) > 80:
        value = value[:77] + "..."
    return value.strip()

_ENUM_STRING_CACHE = {}
def _enum_cache_string(value):
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    cached = _ENUM_STRING_CACHE.get(value)
    if cached is None:
        cached = "{}".format(value)
        _ENUM_STRING_CACHE[value] = cached
    return cached


# Cached enum for template_icon_view — rebuild only when parts/icons change.
_PREVIEW_ENUM_CACHE = {
    "sig": None,
    "items": None,
    "icon_rev": 0,
}

# cfg_path → "[B9]" / "[V]" / ""  (cheap head-read, cached)
_VARIANT_TAG_CACHE = {}


def _variant_source_tag(cfg_path: str, mu_path: str = "") -> str:
    """Return [B9] and/or [V] if the part.cfg declares those switch modules.

    Overlay on 8×8 thumbs is not possible without regenerating PNGs, so we
    mark the label under the icon instead (template_icon_view show_labels).
    Falls back to a sibling .cfg next to the .mu when cfg_path is empty.
    """
    import os
    paths = []
    if cfg_path:
        paths.append(cfg_path)
    if mu_path:
        stem, _ = os.path.splitext(mu_path)
        for cand in (
            stem + ".cfg",
            os.path.join(os.path.dirname(mu_path), "part.cfg"),
        ):
            if cand not in paths:
                paths.append(cand)
    if not paths:
        return ""
    # Cache key = first existing path or cfg_path
    cache_key = None
    for p in paths:
        if p in _VARIANT_TAG_CACHE:
            return _VARIANT_TAG_CACHE[p]
        if os.path.isfile(p):
            cache_key = p
            break
    if not cache_key:
        for p in paths:
            _VARIANT_TAG_CACHE[p] = ""
        return ""
    tag = ""
    try:
        # MODULE names — first 128 KiB covers long BDB/ReStock part.cfg files
        with open(cache_key, "r", encoding="utf-8", errors="ignore") as fh:
            head = fh.read(131072)
        low = head.lower()
        has_b9 = (
            "moduleb9partswitch" in low
            or "name = moduleb9partswitch" in low
            or "name=moduleb9partswitch" in low
            or "b9partswitch" in low
        )
        has_v = (
            "modulepartvariants" in low
            or "name = modulepartvariants" in low
            or "name=modulepartvariants" in low
        )
        # Stock often uses baseVariant + VARIANT { without repeating the module
        # type in every snippet; treat as [V] when VARIANT blocks exist.
        if not has_v and "basevariant" in low and "variant" in low:
            has_v = True
        # ReStock / BDB: meshSwitch* / textureSwitch* MODULE blocks are B9 even
        # when the type string is only in a ModuleManager patch outside this file.
        if not has_b9 and "subtype" in low and (
            "meshswitch" in low
            or "textureswitch" in low
            or "meshtoggle" in low
            or "switcherdescription" in low
        ):
            has_b9 = True
        if has_b9 and has_v:
            tag = "[B9][V]"
        elif has_b9:
            tag = "[B9]"
        elif has_v:
            tag = "[V]"
    except Exception:
        tag = ""
    _VARIANT_TAG_CACHE[cache_key] = tag
    for p in paths:
        if p != cache_key:
            _VARIANT_TAG_CACHE.setdefault(p, tag)
    return tag


def bump_preview_enum_icons():
    """Call after warmup loads more icons so the open popup can refresh."""
    _PREVIEW_ENUM_CACHE["icon_rev"] = int(_PREVIEW_ENUM_CACHE.get("icon_rev") or 0) + 1
    _PREVIEW_ENUM_CACHE["sig"] = None  # force rebuild


def _preview_items(self, context):
    """Enum for template_icon_view — full list, heavily cached.

    Blender still has to layout the popup once; we make the *Python* side
    instant by caching the tuple and never touching disk here. Icons come
    from the in-memory preview collection (real or default placeholder).
    """
    try:
        parts = self.parts
        n = len(parts)
    except Exception:
        n = 0
        parts = None

    if not n:
        return [
            (
                _enum_cache_string("NONE"),
                _enum_cache_string("No parts"),
                _enum_cache_string(""),
                0,
                0,
            )
        ]

    rev = int(_PREVIEW_ENUM_CACHE.get("icon_rev") or 0)
    # Signature: length + first/last name + icon revision
    try:
        # Include first/last variant_tag so [B9]/[V] label updates invalidate cache
        t0 = getattr(parts[0], "variant_tag", "") or ""
        t1 = getattr(parts[n - 1], "variant_tag", "") or ""
        sig = (n, parts[0].name, parts[n - 1].name, rev, t0, t1)
    except Exception:
        sig = (n, rev)

    if _PREVIEW_ENUM_CACHE.get("sig") == sig and _PREVIEW_ENUM_CACHE.get("items"):
        return _PREVIEW_ENUM_CACHE["items"]

    try:
        from . import thumbnails
        peek = thumbnails.peek_icon_id
    except Exception:
        peek = None

    items = [None] * n
    for i in range(n):
        item = parts[i]
        identifier = _enum_cache_string("PART_%d" % i)
        # Tag stock ModulePartVariants [V] and B9PartSwitch [B9] in the label
        # (template_icon_view shows this text under the 8×8 thumb — no regen).
        raw_title = _safe_text(item.title) or _safe_text(item.name) or "?"
        # Strip any previous tag then re-apply so cache rebuilds stay clean
        for t in ("[B9][V] ", "[B9] ", "[V] "):
            if raw_title.startswith(t):
                raw_title = raw_title[len(t):]
                break
        tag = (getattr(item, "variant_tag", "") or "").strip()
        if not tag:
            tag = _variant_source_tag(
                getattr(item, "cfg_path", "") or "",
                getattr(item, "mu_path", "") or "",
            )
        if tag:
            raw_title = "%s %s" % (tag, raw_title)
        title = _enum_cache_string(raw_title)
        name = _enum_cache_string(_safe_text(item.name))
        icon_id = 0
        if peek is not None:
            try:
                icon_id = int(peek(item.mu_path, item.name) or 0)
            except Exception:
                icon_id = 0
        # identifier, name(label under icon), description, icon, index
        items[i] = (identifier, title, name, icon_id, i)

    _PREVIEW_ENUM_CACHE["sig"] = sig
    _PREVIEW_ENUM_CACHE["items"] = items
    return items


def _update_preview(self, context):
    """Aktualizacja wybranej części"""
    value = self.part_preview
    if not value:
        return
    if not value.startswith("PART_"):
        return
    try:
        index = int(value[5:])
    except (TypeError, ValueError):
        return
    if index < 0:
        return
    if index >= len(self.parts):
        return
    self.parts_index = index
    try:
        cat = str(getattr(self, "category", "") or "")
        if cat:
            _CAT_LAST_INDEX[cat] = index
            global _LAST_CATEGORY
            _LAST_CATEGORY = cat
    except Exception:
        pass

def _update_include_stock_thumbs(self, context):
    try:
        from . import thumbnails
        enabled = bool(self.include_stock_thumbs)
        thumbnails.set_include_stock_thumbs(enabled)
        thumbnails.invalidate_ksp_thumbs_index()
        # Important: the preview cache may already contain the stock image
        # under the same part key. Drop ALL part preview entries so switching
        # OFF immediately exposes our generated cache (or the default image),
        # and switching ON can restore the KSP @thumbs image.
        thumbnails.invalidate_preview_icons()
        thumbnails.schedule_ksp_thumbs_index_build(force=True)
        _PREVIEW_ENUM_CACHE["sig"] = None
        _PREVIEW_ENUM_CACHE["items"] = None
        try:
            br = getattr(context.window_manager, "ksp_mu_browser", None)
            if br is not None:
                thumbnails.reset_preview_stream(br)
                thumbnails.schedule_preview_warmup(br, chunk_size=16)
                # Re-assert current enum value so template_icon_view rebuilds.
                cur = str(getattr(br, "part_preview", "") or "")
                if cur.startswith("PART_"):
                    br.part_preview = ""
                    br.part_preview = cur
        except Exception:
            pass
        # Also update real viewport attachment markers immediately.
        try:
            from . import operators as _ops
            _ops.update_attach_point_markers(context, bool(getattr(br, "show_attach_points", False)))
        except Exception as e:
            print("[mu_browser] attach-point update failed:", type(e).__name__, e)
        # Redraw every open 3D View, not only the area that owns the checkbox.
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "VIEW_3D":
                        area.tag_redraw()
        except Exception:
            pass
    except Exception as e:
        print("[mu_browser] stock thumb preference update failed:", type(e).__name__, e)


def _update_show_attach_points(self, context):
    try:
        from ..tools.display import _in_undo_redo
        if _in_undo_redo():
            return
    except Exception:
        pass
    try:
        from . import operators as _ops
        _ops.update_attach_point_markers(context, bool(self.show_attach_points))
    except Exception as e:
        print("[mu_browser] attach-point update failed:", type(e).__name__, e)
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


def _load_persistent_thumbnail_prefs(br):
    try:
        from . import thumbnails
        value = bool(thumbnails.include_stock_thumbs())
        if bool(getattr(br, "include_stock_thumbs", True)) != value:
            br.include_stock_thumbs = value
    except Exception:
        pass


class KSPMU_PG_MuPartItem(PropertyGroup):
    name: StringProperty(name="Name")
    title: StringProperty(name="Title")
    category: StringProperty(name="Category")
    mu_path: StringProperty(
        name="Mu Path",
        subtype="FILE_PATH",
    )
    cfg_path: StringProperty(
        name="Cfg Path",
        subtype="FILE_PATH",
    )
    variant_tag: StringProperty(
        name="Variant Tag",
        description="[V] ModulePartVariants / [B9] B9PartSwitch",
        default="",
    )
    attach_rules: StringProperty(
        name="Attach Rules",
        default="",
    )

class KSPMU_PG_MuBrowser(PropertyGroup):
    include_stock_thumbs: BoolProperty(
        name="Include stock thumbs",
        description="Use KSP @thumbs icons when available",
        default=True,
        update=_update_include_stock_thumbs,
    )
    show_attach_points: BoolProperty(
        name="Show attach points",
        description="Show KSP-like translucent green attachment nodes in the viewport and generated thumbnails",
        default=False,
        update=_update_show_attach_points,
    )
    category: EnumProperty(
        name="Category",
        items=_category_items,
        update=_update_category,
    )
    filter: StringProperty(
        name="Filter",
        default="",
        update=_update_category,
    )
    parts: CollectionProperty(
        type=KSPMU_PG_MuPartItem
    )
    parts_index: IntProperty(
        name="Part Index",
        default=0,
    )
    preview_limit: IntProperty(
        name="Preview Limit",
        description="How many part icons are currently exposed in the grid (grows automatically)",
        default=64,
        min=8,
    )
    part_preview: EnumProperty(
        name="Part Preview",
        description="Select KSP part",
        items=_preview_items,
        update=_update_preview,
    )
    thumbs_pending: BoolProperty(
        name="Lazy Thumbnails",
        description=(
            "Load cached preview icons; "
            "use Generate for missing ones"
        ),
        default=True,
    )

# Funkcja do resetowania cache kategorii
def reset_category_cache():
    """Resetuje cache kategorii - wymusza ponowne załadowanie"""
    import time
    _CATEGORY_CACHE['items'] = None
    _CATEGORY_CACHE['timestamp'] = 0
    _CATEGORY_CACHE['loading'] = False

classes_to_register = (
    KSPMU_PG_MuPartItem,
    KSPMU_PG_MuBrowser,
)

custom_properties_to_register = (
    (
        WindowManager,
        "ksp_mu_browser",
        KSPMU_PG_MuBrowser,
    ),
)