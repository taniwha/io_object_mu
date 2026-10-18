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
"""Import KSP .ksp Unity AssetBundles into Blender."""

from __future__ import annotations

import os

import bpy
from mathutils import Vector

from .bundle import KspBundleError, load_bundle
from . import kspedia_index
from . import layout
from . import viewport


def _link_object(collection, obj, parent=None):
    if obj.name not in collection.objects:
        try:
            collection.objects.link(obj)
        except RuntimeError:
            pass
    if parent is not None:
        obj.parent = parent
    return obj


def _make_empty(collection, name, parent=None, size=0.05):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = float(size)
    _link_object(collection, obj, parent)
    return obj


def _locale_hide_locked(obj) -> bool:
    """Artwork overlay stamp. Not used to skip TOC page hide (USER-LATEST-009)."""
    try:
        if obj.get("ksp_artwork_overlay"):
            return True
    except Exception:
        pass
    return False


def _safe_hide_set(obj, hide) -> None:
    """Viewport hide without crashing on objects outside this view layer.

    ``Object.hide_set`` is view-layer local. Calling it on a newly copied
    object that is not yet evaluated, or while walking a parent cycle, can
    take Blender down in C where Python ``except`` cannot catch it.
    """
    if obj is None:
        return
    try:
        obj.hide_viewport = hide
    except Exception:
        pass
    try:
        obj.hide_render = hide
    except Exception:
        pass
    try:
        import bpy
        vl = bpy.context.view_layer
        found = vl.objects.get(obj.name) if vl is not None else None
        if found is obj:
            obj.hide_set(hide)
    except Exception:
        pass


def _set_hide_tree(obj, hide):
    """Hide/show object and all descendants (viewport + render).

    When unhiding, do not reveal ``ksp_locale_parked`` nodes (instant locale
    cache) and do not walk their children — TOC folder clicks used to unhide
    cloned ConfT2/ConfB copies parked under the EN Header.

    Page hide must hide overlays too. Skipping ``ksp_artwork_overlay`` left
    nested children visible on every TOC page (USER-LATEST-009): a hidden
    parent does not hide a child with hide_viewport=False.
    """
    if obj is None:
        return
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
        if not hide:
            try:
                if cur.get("ksp_locale_parked"):
                    continue
            except Exception:
                pass
        _safe_hide_set(cur, hide)
        try:
            stack.extend(list(cur.children))
        except Exception:
            pass


def iter_page_roots(root):
    """Yield multipage page-root empties under bundle root."""
    pages = []
    for obj in [root] + list(getattr(root, "children_recursive", []) or []):
        try:
            if "ksp_page_index" in obj.keys():
                pages.append(obj)
        except Exception:
            continue
    pages.sort(key=lambda o: int(o.get("ksp_page_index", 0)))
    return pages


def _is_under(obj, ancestor):
    cur = obj
    while cur is not None:
        if cur == ancestor:
            return True
        cur = cur.parent
    return False


def show_multipage_index(root, page_index):
    """Show one page hierarchy; hide sibling pages. Returns page object."""
    pages = iter_page_roots(root)
    if not pages:
        return None
    n = len(pages)
    idx = max(0, min(int(page_index), n - 1))
    try:
        root.ksp_bundle.active_page_index = idx
        root.ksp_bundle.page_count = n
    except Exception:
        pass
    active = pages[idx]
    return show_multipage_scope(root, active)


def show_first_toc_page(root):
    """Show the first TOC landing page (TitleScreen / first category).

    Multipage imports used to call ``show_multipage_index(root, 0)``, which is
    the first page by ``ksp_page_index`` — often alphabetically earlier than
    the category TitleScreen (PBS). Prefer the first TOC folder's TitleScreen,
    then a page named TitleScreen, else page 0.
    """
    pages = iter_page_roots(root)
    if not pages:
        return None
    try:
        kb = root.ksp_bundle
    except Exception:
        return show_multipage_index(root, 0)

    target = None
    # 1) First category/subcategory TitleScreen from TOC
    try:
        for node in kb.toc_nodes:
            if node.kind not in {'category', 'subcategory'}:
                continue
            sid = (node.screen or "").strip()
            if not sid:
                continue
            for page in pages:
                if str(page.get("ksp_page", "") or "") == sid:
                    target = page
                    break
            if target is None and node.page_object is not None:
                target = node.page_object
            if target is not None:
                break
    except Exception:
        target = None

    # 2) Explicit TitleScreen page id / name
    if target is None:
        for page in pages:
            sid = str(page.get("ksp_page", "") or page.name or "")
            if sid.lower() == "titlescreen" or sid.lower().endswith("titlescreen"):
                target = page
                break

    # 3) First TOC page row with a viewport object
    if target is None:
        try:
            for node in kb.toc_nodes:
                if node.kind == 'page' and node.page_object is not None:
                    target = node.page_object
                    break
        except Exception:
            pass

    if target is None:
        return show_multipage_index(root, 0)

    try:
        idx = pages.index(target)
        kb.active_page_index = idx
        kb.page_count = len(pages)
    except Exception:
        pass
    return show_multipage_scope(root, target)


def resolve_ksp_import_path(filepath):
    """Map a user-picked .lang (or locale file) to the editable base .ksp.

    Language packs are UnityFS siblings; importing only a .lang often lacks
    fonts/backgrounds. Prefer the matching base / en-us .ksp next to it.
    Returns (path_to_load, preferred_locale).
    """
    import os
    from . import locale_switch

    path = os.path.abspath(filepath or "")
    if not path or not os.path.isfile(path):
        return filepath, ""
    base_name = os.path.basename(path)
    folder = os.path.dirname(path)
    m = locale_switch._LOCALE_FILE_RE.match(base_name)
    locale = (m.group("locale") or "").lower() if m else ""
    base = m.group("base") if m else os.path.splitext(base_name)[0]

    # Non-locale pick: load as-is (still report locale if filename has one)
    if not path.lower().endswith(".lang"):
        return path, locale

    # .lang → sibling .ksp (base, en-us, then any matching base_*.ksp)
    candidates = [
        os.path.join(folder, "%s.ksp" % base),
        os.path.join(folder, "%s_en-us.ksp" % base),
    ]
    try:
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".ksp"):
                continue
            mm = locale_switch._LOCALE_FILE_RE.match(name)
            stem = mm.group("base") if mm else os.path.splitext(name)[0]
            if stem.lower() != base.lower():
                continue
            candidates.append(os.path.join(folder, name))
    except Exception:
        pass
    seen = set()
    for cand in candidates:
        ap = os.path.abspath(cand)
        if ap in seen or not os.path.isfile(ap):
            continue
        seen.add(ap)
        return ap, locale
    raise KspBundleError(
        "Cannot import .lang without a sibling .ksp in the same folder "
        "(e.g. %s_en-us.ksp). Open the .ksp, then switch language."
        % (base or "pack")
    )


def show_multipage_scope(root, scope_obj):
    """Show page(s) under scope (page empty or category folder).

    - page: only that page
    - folder: all pages nested under that folder
    - None / bundle root: first page only (safe default)
    Returns the primary visible page (or None).
    """
    pages = iter_page_roots(root)
    if not pages:
        return None
    try:
        root.ksp_bundle.page_count = len(pages)
    except Exception:
        pass

    under = []
    exact_page = None
    folder_scope = False
    if scope_obj is None:
        under = [pages[0]]
        exact_page = pages[0]
    else:
        for page in pages:
            if page == scope_obj:
                exact_page = page
                under = [page]
                break
        if exact_page is None:
            folder_scope = True
            # Category/subcategory: prefer TitleScreen page (KSP TOC behaviour)
            ts = ""
            try:
                ts = str(scope_obj.get("ksp_title_screen", "") or "")
            except Exception:
                ts = ""
            if ts:
                for page in pages:
                    if str(page.get("ksp_page", "") or "") == ts:
                        exact_page = page
                        under = [page]
                        break
            if exact_page is None:
                for page in pages:
                    if _is_under(page, scope_obj):
                        under.append(page)
                # Prefer direct-child page whose title matches folder title
                if under and len(under) > 1:
                    folder_title = ""
                    try:
                        folder_title = str(
                            scope_obj.get("ksp_display_title", "") or scope_obj.name
                        )
                    except Exception:
                        folder_title = scope_obj.name
                    for page in under:
                        pt = str(page.get("ksp_display_title", "") or page.name)
                        if pt == folder_title or page.name == folder_title:
                            exact_page = page
                            under = [page]
                            break
        if not under:
            try:
                if scope_obj.ksp_bundle.is_ksp_bundle:
                    under = [pages[0]]
                    exact_page = pages[0]
            except Exception:
                pass
            if not under:
                under = [pages[0]]
                exact_page = pages[0]

    # One page in viewport. Do NOT keep previous active_page_index when
    # switching to a category folder (that left a child page visible).
    primary = exact_page or under[0]

    for page in pages:
        _set_hide_tree(page, page != primary)

    try:
        kb = root.ksp_bundle
        kb.filter_scope_object = scope_obj if scope_obj is not None else primary
        # Always the visible page so Filter Assets matches the viewport
        # (a category folder would otherwise list every nested page).
        kb.filter_page_object = primary
        # Store LIST POSITION (not raw ksp_page_index prop) — the prop can be
        # sparse / non-contiguous and show_multipage_index treats the value as
        # an index into iter_page_roots().
        try:
            kb.active_page_index = int(pages.index(primary))
        except Exception:
            kb.active_page_index = int(primary.get("ksp_page_index", 0))
        kb.page_count = len(pages)
    except Exception:
        pass
    # Unhiding a page tree must not resurrect boxes dropped for this language
    # (KSP Delete / locale orphan). Keyboard-deleted objects are already gone.
    try:
        _hide_locale_orphans(root)
    except Exception:
        pass
    # Hide/show walks the page tree; GPU text-box entries still pointed at
    # the previous page, so boxes vanished until the next locale switch.
    try:
        kb = root.ksp_bundle
        if getattr(kb, "show_text_boxes", False):
            from .locale_switch import sync_text_box_overlays
            sync_text_box_overlays(
                root,
                True,
                pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
                scope=primary,
            )
    except Exception:
        pass
    return primary


def _hide_locale_orphans(root):
    """Re-hide ksp_locale_orphan objects after a page/folder show.

    Clear stale orphan marks when the object is live for the active locale
    (presence soft-match / wake can leave the flag set while the box is valid).
    """
    if root is None:
        return
    active = ""
    try:
        active = str(getattr(root.ksp_bundle, "active_locale", "") or "").lower()
    except Exception:
        active = ""
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    for obj in objs:
        try:
            if not obj.get("ksp_locale_orphan"):
                continue
        except Exception:
            continue
        try:
            if obj.get("ksp_locale_parked"):
                _set_hide_tree(obj, True)
                continue
        except Exception:
            pass
        if active:
            try:
                applied = str(obj.get("ksp_locale_applied") or "").lower()
                if applied == active and not obj.get("ksp_locale_hidden"):
                    del obj["ksp_locale_orphan"]
                    continue
                # Nested overlay with empty stamp under a live parent of this locale
                if not applied and not obj.get("ksp_locale_hidden"):
                    par = obj.parent
                    while par is not None:
                        try:
                            if str(par.get("ksp_locale_applied") or "").lower() == active:
                                if not par.get("ksp_locale_orphan") and not par.get("ksp_locale_parked"):
                                    del obj["ksp_locale_orphan"]
                                    break
                        except Exception:
                            pass
                        try:
                            par = par.parent
                        except Exception:
                            par = None
                    else:
                        pass
                    if "ksp_locale_orphan" not in obj.keys():
                        continue
            except Exception:
                pass
        _set_hide_tree(obj, True)


def _hide_bundle_content(root, hide):
    """Hide/show bundle *contents* but keep the root empty selectable.

    Blender rejects `select_set` / Outliner activation on `hide_set`
    objects — hiding the whole tree made Select Bundle fail when trying
    to reveal another bundle from the Outliner.
    """
    if root is None:
        return
    try:
        root.hide_set(False)
        root.hide_render = False
    except Exception:
        pass
    for child in list(root.children):
        _set_hide_tree(child, hide)


def set_active_bundle(root, scene=None):
    """Show active bundle content; hide other bundles' content (roots stay)."""
    import bpy as _bpy
    scene = scene or _bpy.context.scene
    roots = []
    for obj in scene.objects:
        try:
            if obj.ksp_bundle.is_ksp_bundle:
                roots.append(obj)
        except Exception:
            continue
    for other in roots:
        _hide_bundle_content(other, other != root)
    try:
        from .operators import pin_active_bundle
        pin_active_bundle(root, scene)
    except Exception:
        pass
    return root


def _cleanup_legacy_pages_collections(bundle_name):
    """Remove old <bundle>_Pages collection trees from earlier addon versions."""
    if not bundle_name:
        return
    target = "%s_Pages" % bundle_name
    col = bpy.data.collections.get(target)
    if col is None:
        return
    for child in list(col.children):
        for obj in list(child.objects):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
        try:
            bpy.data.collections.remove(child)
        except Exception:
            pass
    for obj in list(col.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.data.collections.remove(col)
    except Exception:
        pass


def _import_scope_id(root, bundle=None) -> str:
    """Blender-unique id for this import (root empty name, incl. .001)."""
    try:
        if root is not None and getattr(root, "name", ""):
            return str(root.name)
    except Exception:
        pass
    try:
        if bundle is not None and getattr(bundle, "name", ""):
            return str(bundle.name)
    except Exception:
        pass
    return "ksp"


def _fill_bundle_props(kb, bundle, filepath, *, scope: str = ""):
    kb.is_ksp_bundle = True
    kb.source_path = filepath
    kb.bundle_name = bundle.name
    kb.bundle_kind = bundle.kind
    # Per-import datablock prefix — second open of the same .ksp must not
    # share images / Text assets / materials with the first.
    scope_id = (scope or "").strip() or (bundle.name or "ksp")
    try:
        kb["import_scope"] = scope_id
    except Exception:
        pass
    base, locale = kspedia_index.detect_locale_from_filename(filepath)
    loc = kspedia_index.find_localization_near_ksp(filepath)
    kb.locale_base = base or bundle.name
    kb.locale = (loc.locale if loc and loc.locale else locale) or ""
    kb.localization_cfg = (loc.cfg_path if loc else "") or ""
    # Pack identity = UrlName (may differ from filename stem, e.g. gep vs jnsq)
    try:
        from .unityfs_catalog import heal_pack_identity
        heal_pack_identity(kb, filepath=filepath)
    except Exception:
        pass
    try:
        from . import locale_switch
        # Prefer filename locale, then localization.cfg default, then en-us.
        want = (kb.locale or "").lower()
        if not want and loc is not None:
            want = (getattr(loc, "default", "") or "").lower()
        if not want:
            want = "en-us"
            kb.locale = want
        kb.available_locales = locale_switch.locales_csv(filepath, preferred=want)
        locs = [x.strip() for x in (kb.available_locales or "").split(",") if x.strip()]
        # Always expose at least the detected language (solo .ksp / no siblings).
        if want and want not in locs:
            locs = sorted(set(locs + [want]))
            kb.available_locales = ",".join(locs)
        if not locs:
            kb.available_locales = want
            locs = [want]
        if want not in locs:
            want = locs[0]
            kb.locale = want
        # Seed enum without firing update (stable alpha order in items).
        kb["active_locale"] = want
        # Fonts are extracted once from the already-loaded UnityPy env in
        # import_ksp() — do not UnityPy.load the same .ksp again here.
    except Exception:
        pass
    xml_name, _xml = kspedia_index.find_kspedia_xml_text(bundle.text_assets)
    kb.kspedia_xml_asset = xml_name or ""
    try:
        kb.coverage_report = getattr(bundle, "coverage_report", "") or ""
        kb.coverage_unknown = int(getattr(bundle, "coverage_unknown", 0) or 0)
        kb.canvas_scale_mode = int(getattr(bundle, "canvas_scale_mode", 0) or 0)
        cref = getattr(bundle, "canvas_ref_resolution", (0.0, 0.0)) or (0.0, 0.0)
        kb.canvas_ref_resolution = (float(cref[0]), float(cref[1]))
        kb.canvas_scale_factor = float(getattr(bundle, "canvas_scale_factor", 1.0) or 1.0)
        kb.materials.clear()
        for name, pid in getattr(bundle, "materials", None) or []:
            m = kb.materials.add()
            m.name = name
            m.path_id = str(pid)
        try:
            kb.font_inventory.clear()
            inv = getattr(bundle, "font_inventory", None) or {}
            for fam in sorted(inv.keys(), key=lambda s: str(s).lower()):
                if not fam or str(fam).startswith("("):
                    continue
                it = kb.font_inventory.add()
                it.name = str(fam)
                try:
                    it.path_id = str(int(inv.get(fam) or 0))
                except Exception:
                    it.path_id = "0"
                it.file_id = "0"
        except Exception:
            pass
    except Exception:
        pass
    kb.toc_nodes.clear()
    kb.filter_page_object = None
    kb.textures.clear()
    n_tex = len(bundle.textures or [])
    for i, tex in enumerate(bundle.textures):
        try:
            from .progress_util import tick_items
            tick_items(i, n_tex, 25, 48, text="Loading textures…")
        except Exception:
            pass
        item = kb.textures.add()
        item.name = tex.name
        item.path_id = str(tex.path_id)
        item.width = tex.width
        item.height = tex.height
        try:
            item.texture_external = bool(getattr(tex, "external", False))
        except Exception:
            pass
        try:
            item.texture_format = int(getattr(tex, "texture_format", 0) or 0)
            item.content_hash = str(getattr(tex, "content_hash", "") or "")
            item.dirty = False
        except Exception:
            pass
        img_name = "ksp_%s_%s_%s" % (scope_id, tex.name, tex.path_id)
        img = viewport.image_from_png_bytes(img_name, tex.png_bytes)
        if img is not None:
            item.image = img
            # Hash AFTER Blender round-trip so export passthrough matches
            try:
                item.content_hash = viewport.image_content_hash(img)
            except Exception:
                pass
    try:
        from .progress_util import tick
        tick(50, text="Loading UI properties…")
    except Exception:
        pass
    kb.text_assets.clear()
    for ta in bundle.text_assets:
        item = kb.text_assets.add()
        item.name = ta.name
        item.path_id = str(ta.path_id)
        item.text = ta.text
        # Never reuse/clear another import's Text datablock.
        tbase = "ksp_text_%s_%s" % (scope_id, ta.name)
        tname = tbase
        if tname in bpy.data.texts:
            n = 1
            while ("%s.%03d" % (tbase, n)) in bpy.data.texts:
                n += 1
            tname = "%s.%03d" % (tbase, n)
        txt = bpy.data.texts.new(tname)
        txt.clear()
        txt.write(ta.text or "")
        item.text_block = txt
    kb.shaders.clear()
    for sh in bundle.shaders:
        item = kb.shaders.add()
        item.name = sh.name
        item.path_id = str(sh.path_id)
    kb.ui_elements.clear()
    for el in bundle.ui_elements:
        item = kb.ui_elements.add()
        item.name = el.name
        item.path_id = str(el.path_id)
        item.go_path_id = str(el.go_path_id)
        item.rect_path_id = str(el.rect_path_id)
        item.mb_path_id = str(el.mb_path_id)
        item.kind = el.kind
        item.text = el.text  # raw TMP markup (export source)
        item.font_size = el.font_size
        item.color = el.color
        item.anchored_position = el.anchored_position + (0.0,)
        item.size_delta = el.size_delta + (0.0,)
        item.pivot = el.pivot
        item.anchor_min = el.anchor_min
        item.anchor_max = el.anchor_max
        if el.offset_min is not None:
            item.offset_min = el.offset_min
            item.has_offset_min = True
        if el.offset_max is not None:
            item.offset_max = el.offset_max
            item.has_offset_max = True
        try:
            item.local_rotation = tuple(
                getattr(el, "local_rotation", (0.0, 0.0, 0.0, 1.0))
            )
            item.local_scale = tuple(getattr(el, "local_scale", (1.0, 1.0, 1.0)))
            item.local_position_z = float(
                getattr(el, "local_position_z", 0.0) or 0.0
            )
        except Exception:
            pass
        item.texture_path_id = str(el.texture_path_id)
        item.sprite_path_id = str(el.sprite_path_id)
        item.parent_rect_path_id = str(el.parent_rect_path_id)
        item.text_alignment = int(getattr(el, "text_alignment", 0) or 0)
        item.font_style = int(getattr(el, "font_style", 0) or 0)
        item.is_rich_text = bool(getattr(el, "is_rich_text", True))
        item.enable_word_wrapping = bool(getattr(el, "enable_word_wrapping", True))
        item.line_spacing = float(getattr(el, "line_spacing", 0.0) or 0.0)
        item.margin = tuple(getattr(el, "margin", (0.0, 0.0, 0.0, 0.0)))
        item.font_family = str(getattr(el, "font_family", "") or "")
        item.texture_external = bool(getattr(el, "texture_external", False))
        try:
            item.font_asset_path_id = str(int(getattr(el, "font_asset_path_id", 0) or 0))
            item.font_asset_file_id = str(int(getattr(el, "font_asset_file_id", 0) or 0))
            item.image_type = int(getattr(el, "image_type", 0) or 0)
            item.preserve_aspect = bool(getattr(el, "preserve_aspect", False))
            item.fill_center = bool(getattr(el, "fill_center", True))
            item.fill_method = int(getattr(el, "fill_method", 0) or 0)
            item.fill_amount = float(getattr(el, "fill_amount", 1.0) or 1.0)
            item.fill_clock_wise = bool(getattr(el, "fill_clock_wise", True))
            item.fill_origin = int(getattr(el, "fill_origin", 0) or 0)
            item.is_raw_image = bool(getattr(el, "is_raw_image", False))
            item.horizontal_alignment = int(getattr(el, "horizontal_alignment", 0) or 0)
            item.vertical_alignment = int(getattr(el, "vertical_alignment", 0) or 0)
            item.outline_width = float(getattr(el, "outline_width", 0.0) or 0.0)
            item.outline_color = tuple(getattr(el, "outline_color", (0.0, 0.0, 0.0, 1.0)))
            item.character_spacing = float(getattr(el, "character_spacing", 0.0) or 0.0)
            item.word_spacing = float(getattr(el, "word_spacing", 0.0) or 0.0)
            item.paragraph_spacing = float(getattr(el, "paragraph_spacing", 0.0) or 0.0)
            item.enable_auto_sizing = bool(getattr(el, "enable_auto_sizing", False))
            item.font_size_min = float(getattr(el, "font_size_min", 0.0) or 0.0)
            item.font_size_max = float(getattr(el, "font_size_max", 0.0) or 0.0)
            item.overflow_mode = int(getattr(el, "overflow_mode", 0) or 0)
            item.enable_kerning = bool(getattr(el, "enable_kerning", True))
            item.locale_tag = str(getattr(el, "locale_tag", "") or "")
            item.face_color = tuple(getattr(el, "face_color", (1, 1, 1, 1)))
            item.enable_vertex_gradient = bool(
                getattr(el, "enable_vertex_gradient", False)
            )
            item.tint_all_sprites = bool(getattr(el, "tint_all_sprites", False))
            item.horizontal_mapping = int(getattr(el, "horizontal_mapping", 0) or 0)
            item.vertical_mapping = int(getattr(el, "vertical_mapping", 0) or 0)
            item.is_volumetric_text = bool(getattr(el, "is_volumetric_text", False))
            item.page_to_display = int(getattr(el, "page_to_display", 1) or 1)
            item.linked_text_path_id = str(
                int(getattr(el, "linked_text_path_id", 0) or 0)
            )
            item.sprite_animator_path_id = str(
                int(getattr(el, "sprite_animator_path_id", 0) or 0)
            )
            item.script_class = str(getattr(el, "script_class", "") or "")
            item.meta_scripts = str(getattr(el, "meta_scripts", "") or "")
            item.effect_distance = tuple(
                getattr(el, "effect_distance", (0.0, 0.0))
            )
            item.has_ui_outline = bool(getattr(el, "has_ui_outline", False))
            item.has_ui_shadow = bool(getattr(el, "has_ui_shadow", False))
        except Exception:
            pass


def _fallback_canvas_size(bundle):
    """Prefer page art (typ. 2048x1536), not font SDF atlases (4096 etc.)."""
    textures = list(getattr(bundle, "textures", None) or [])
    if not textures:
        return 1920.0, 1080.0
    scored = []
    for t in textures:
        w = float(getattr(t, "width", 0) or 0)
        h = float(getattr(t, "height", 0) or 0)
        name = (getattr(t, "name", "") or "").lower()
        if w < 64 or h < 64:
            continue
        if "sdf" in name or "atlas" in name or "font" in name:
            continue
        if "background" in name and w <= 1024 and h <= 768:
            continue
        aspect = w / max(h, 1.0)
        page_bonus = 0
        if 1.2 <= aspect <= 1.5 and 1500 <= w <= 2200 and 1100 <= h <= 1700:
            page_bonus = 100
        scored.append((page_bonus, w * h, w, h))
    if scored:
        scored.sort(reverse=True)
        return float(scored[0][2]), float(scored[0][3])
    t = textures[0]
    return float(t.width), float(t.height)


def _texture_name_for_id(bundle, path_id):
    try:
        tid = int(path_id or 0)
    except Exception:
        return ""
    for tex in getattr(bundle, "textures", None) or []:
        if int(getattr(tex, "path_id", 0) or 0) == tid:
            return str(getattr(tex, "name", "") or "")
    return ""


def _tag_ui_page(kb, el, screen_id):
    for item in kb.ui_elements:
        if item.rect_path_id == str(el.rect_path_id):
            try:
                item.page_screen = screen_id or ""
            except Exception:
                pass
            break
    if el.kind == "image":
        tid = str(getattr(el, "texture_path_id", "") or "")
        for tex in kb.textures:
            if tex.path_id == tid or (
                tid and tex.path_id == str(int(tid) if tid.lstrip("-").isdigit() else -1)
            ):
                try:
                    if not tex.page_screen:
                        tex.page_screen = screen_id or ""
                except Exception:
                    pass
                break


def _build_toc_folders(collection, ui_root, index):
    """Create category/subcategory empties; return path->folder map."""
    folders = {(): ui_root}
    for entry in index.entries:
        if entry.kind == "page":
            continue
        path = entry.parent_path + (entry.name,)
        if path in folders:
            continue
        parent = folders.get(entry.parent_path, ui_root)
        # Prefer KSPedia display title as object name.
        folder = _make_empty(
            collection, entry.title or entry.name, parent, size=0.04
        )
        try:
            folder["ksp_toc_kind"] = entry.kind
            folder["ksp_toc_name"] = entry.name
            folder["ksp_display_title"] = entry.title or entry.name
            ts = getattr(entry, "title_screen", "") or ""
            if ts:
                folder["ksp_title_screen"] = ts
        except Exception:
            pass
        folders[path] = folder
    return folders



def _resolve_toc_display_titles(kb, filepath: str = ""):
    """Resolve #autoLOC display titles from GameData dictionaries.

    Keeps ``title_raw`` as the LOC key so language switches still work.
    Uses addon GameData preference when the .ksp is outside GameData.
    """
    try:
        from . import ksp_loc
    except Exception:
        return
    src = (filepath or getattr(kb, "source_path", "") or "").strip()
    try:
        dictionary = ksp_loc.load_merged_dictionary(src)
    except Exception:
        dictionary = {}
    if not dictionary:
        return
    for node in list(getattr(kb, "toc_nodes", []) or []):
        try:
            raw = (getattr(node, "title_raw", "") or "").strip()
            title = (getattr(node, "title", "") or "").strip()
            if not raw and ksp_loc.is_loc_key(title):
                node.title_raw = title
                raw = title
            if ksp_loc.is_loc_key(raw):
                resolved = ksp_loc.resolve_loc(raw, dictionary, filepath=src)
                if resolved and resolved != raw:
                    node.title = resolved
            elif ksp_loc.is_loc_key(title):
                resolved = ksp_loc.resolve_loc(title, dictionary, filepath=src)
                if resolved and resolved != title:
                    if not raw:
                        node.title_raw = title
                    node.title = resolved
        except Exception:
            continue


def _populate_toc_props(kb, index, page_by_screen, folders, overrides):
    kb.toc_nodes.clear()
    listed = set()
    # TitleScreen pages are opened by clicking the parent category in KSP —
    # do not list them as duplicate TOC rows under the same title.
    title_screens = {
        getattr(e, "title_screen", "")
        for e in index.entries
        if e.kind in ("category", "subcategory") and getattr(e, "title_screen", "")
    }
    for entry in index.entries:
        if entry.kind == "page" and entry.screen and entry.screen in title_screens:
            listed.add(entry.screen)
            continue
        node = kb.toc_nodes.add()
        node.kind = entry.kind if entry.kind in {
            'category', 'subcategory', 'page'
        } else 'page'
        node.depth = int(entry.depth)
        node.name = entry.name
        node.title = entry.title or entry.name
        try:
            node.title_raw = getattr(entry, "title_raw", "") or entry.title or ""
        except Exception:
            pass
        # Pages: Screen id. Folders: Category/Subcategory <TitleScreen>
        # (hidden as a duplicate page row — still editable on the folder).
        if entry.kind == "page":
            node.screen = entry.screen or ""
        else:
            node.screen = getattr(entry, "title_screen", "") or ""
        try:
            sid = (node.screen or "").strip()
            if sid:
                node.bundle_name = (index.screen_bundles or {}).get(sid, "") or (
                    getattr(kb, "bundle_name", "") or ""
                )
                node.asset_path = (
                    getattr(index, "screen_assets", None) or {}
                ).get(sid, "")
            elif not (node.bundle_name or "").strip():
                node.bundle_name = getattr(kb, "bundle_name", "") or ""
        except Exception:
            pass
        node.expanded = True
        try:
            from .unityfs_catalog import host_bundle_stem
            host = (
                host_bundle_stem(kb)
                or (getattr(kb, "bundle_name", "") or "").strip()
            )
            # Pack host only — Screen BundleName may still be "kspedia".
            node.overrides_stock = kspedia_index.screen_overrides_base(
                (node.screen or "").strip(),
                host,
                title=(node.title or "").strip(),
            )
        except Exception:
            node.overrides_stock = bool(
                node.screen and node.screen in overrides
            )
        if entry.kind == "page":
            page = page_by_screen.get(entry.screen)
            node.page_object = page
            listed.add(entry.screen)
            if page is not None:
                try:
                    node.page_index = int(page.get("ksp_page_index", -1))
                except Exception:
                    node.page_index = -1
        else:
            path = entry.parent_path + (entry.name,)
            node.folder_object = folders.get(path)
            # Prefer TitleScreen page object when present in the viewport.
            ts = (node.screen or "").strip()
            if ts and ts in page_by_screen:
                node.page_object = page_by_screen.get(ts)
                try:
                    node.page_index = int(
                        page_by_screen[ts].get("ksp_page_index", -1)
                    )
                except Exception:
                    node.page_index = -1
    for screen, page in sorted(
        page_by_screen.items(),
        key=lambda kv: int(kv[1].get("ksp_page_index", 0)),
    ):
        if screen in listed:
            continue
        try:
            if kspedia_index.is_deleted_toc_screen(screen, index):
                continue
        except Exception:
            pass
        node = kb.toc_nodes.add()
        node.kind = 'page'
        node.depth = 0
        node.name = screen
        node.title = page.get("ksp_display_title", screen) or screen
        node.screen = screen
        node.page_object = page
        node.page_index = int(page.get("ksp_page_index", -1))
        try:
            node.bundle_name = (index.screen_bundles or {}).get(screen, "") or (
                getattr(kb, "bundle_name", "") or ""
            )
            node.asset_path = (
                getattr(index, "screen_assets", None) or {}
            ).get(screen, "")
        except Exception:
            try:
                if not (node.bundle_name or "").strip():
                    node.bundle_name = getattr(kb, "bundle_name", "") or ""
            except Exception:
                pass
        try:
            from .unityfs_catalog import host_bundle_stem
            host = (
                host_bundle_stem(kb)
                or (getattr(kb, "bundle_name", "") or "").strip()
            )
            node.overrides_stock = kspedia_index.screen_overrides_base(
                screen,
                host,
                title=(node.title or "").strip(),
            )
        except Exception:
            node.overrides_stock = screen in overrides


    try:
        kspedia_index.apply_toc_folder_override_inherit(kb.toc_nodes)
    except Exception:
        pass

def _build_one_ui_element(
    collection, el, parent_obj, crect, elements, rects, bundle, kb,
    tex_images, pixel_scale, sx, *, local_origin=False, page_screen="",
):
    """Create one UI object; return (obj, display_text)."""
    if local_origin:
        loc_x = loc_y = 0.0
    else:
        loc_x = crect.pivot_x * sx
        loc_y = crect.pivot_y * sx

    w = max(abs(crect.width), 1e-3) * sx
    h = max(abs(crect.height), 1e-3) * sx
    display_text = ""
    try:
        scope = str(kb.get("import_scope", "") or "")
    except Exception:
        scope = ""

    def _scoped_obj_name(base):
        raw = (base or "ui").strip() or "ui"
        if scope:
            return "%s__%s" % (scope, raw)
        return raw

    if el.kind == "image":
        img = tex_images.get(el.texture_path_id)
        if img is None and bundle.textures:
            img = tex_images.get(bundle.textures[0].path_id)
        tex_name = _texture_name_for_id(bundle, el.texture_path_id)
        plane_name = _scoped_obj_name(tex_name or el.name)
        mat_name = (
            "%s__%s_Mat" % (scope, (tex_name or el.name)) if scope else ((tex_name or el.name) + "_Mat")
        )
        if img is not None:
            mat = viewport.make_unlit_image_material(
                mat_name, img, el.color
            )
        else:
            mat = viewport.make_unlit_color_material(
                mat_name, el.color
            )
        obj = viewport.create_image_plane(
            collection, plane_name, w, h, mat, pivot=el.pivot
        )
        z = -0.002 if (
            (el.name or "").lower().startswith("background")
            or bool(getattr(el, "texture_external", False))
        ) else 0.0
        obj.location = Vector((loc_x, loc_y, z))
        obj.parent = parent_obj
        layout.apply_ui_local_trs(obj, el, pixel_scale=pixel_scale, base_z=z)
    elif el.kind == "text":
        row_pitch_px = None
        content_h = abs(crect.height)
        fs = float(getattr(el, "font_size", 14.0) or 14.0)
        if content_h > fs * 1.45:
            row_pitch_px = layout.estimate_sibling_row_pitch_px(
                el, crect, elements, rects
            )
        fam = str(getattr(el, "font_family", "") or "")
        if getattr(el, "is_ui_text", False) and not fam:
            # Last resort only — PBS resolves OpenSans/Amaranth from m_Font
            # during load_bundle inventory / re-resolve. Never prefer Arial
            # when the bundle already carried a Font asset name.
            fam = "Arial"
        wrap = bool(getattr(el, "enable_word_wrapping", True))
        talign = int(getattr(el, "text_alignment", 0) or 0)
        raw = el.text or ""
        # Leading \\n/spaces are converted to offsets in create_ui_text. Long
        # leftover overlays (ConfB2 quote) must soft-wrap like Unity on-screen.
        rem = raw.lstrip(" \t\n\r")
        if raw[:1].isspace() and len(rem) >= 28:
            wrap = True
        if getattr(el, "is_ui_text", False):
            # Unity TextAnchor 0..8 → TMP legacy slots used by tmp_text_align
            _anchor = {
                0: 0, 1: 1, 2: 2,
                3: 4, 4: 5, 5: 6,  # middle → center vertical in legacy map
                6: 8, 7: 9, 8: 10,
            }
            talign = _anchor.get(talign, 0)
        obj, display_text = viewport.create_rich_ui_text(
            collection,
            _scoped_obj_name(el.name),
            el.text,
            el.font_size,
            base_color=el.color,
            pixel_scale=pixel_scale,
            pivot=el.pivot,
            box_width=abs(crect.width),
            box_height=abs(crect.height),
            font_style=getattr(el, "font_style", 0),
            is_rich_text=getattr(el, "is_rich_text", True),
            text_alignment=talign,
            line_spacing=getattr(el, "line_spacing", 0.0),
            enable_word_wrapping=wrap,
            margin=getattr(el, "margin", (0.0, 0.0, 0.0, 0.0)),
            font_family=fam,
            locale=(getattr(kb, "active_locale", "") or getattr(kb, "locale", "") or ""),
            character_spacing=getattr(el, "character_spacing", 0.0),
            word_spacing=getattr(el, "word_spacing", 0.0),
            paragraph_spacing=getattr(el, "paragraph_spacing", 0.0),
            enable_auto_sizing=getattr(el, "enable_auto_sizing", False),
            font_size_min=getattr(el, "font_size_min", 0.0),
            font_size_max=getattr(el, "font_size_max", 0.0),
            overflow_mode=getattr(el, "overflow_mode", 0),
            row_pitch_px=row_pitch_px,
        )
        obj.location = Vector((loc_x, loc_y, 0.02))
        obj.parent = parent_obj
        layout.apply_ui_local_trs(
            obj, el, pixel_scale=pixel_scale, base_z=0.02
        )
        # TMP / UI Outline/Shadow preview (offset ghost copies)
        try:
            ow = float(getattr(el, "outline_width", 0.0) or 0.0)
            if ow > 0.05 or getattr(el, "has_ui_outline", False) or getattr(el, "has_ui_shadow", False):
                viewport.attach_text_outline_preview(
                    obj,
                    outline_width_px=max(ow, 1.0),
                    outline_color=getattr(el, "outline_color", (0, 0, 0, 1)),
                    pixel_scale=pixel_scale,
                    effect_distance=getattr(el, "effect_distance", (1.0, -1.0)),
                )
        except Exception:
            pass
    elif el.kind == "meta":
        obj = bpy.data.objects.new(_scoped_obj_name(el.name or "meta"), None)
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.015
        _link_object(collection, obj, parent_obj)
        obj.location = Vector((loc_x, loc_y, 0.01))
        layout.apply_ui_local_trs(obj, el, pixel_scale=pixel_scale, base_z=0.01)
        try:
            obj["ksp_meta_script"] = str(getattr(el, "script_class", "") or "")
            obj["ksp_meta_scripts"] = str(getattr(el, "meta_scripts", "") or "")
        except Exception:
            pass
    else:
        obj = bpy.data.objects.new(_scoped_obj_name(el.name), None)
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.02
        _link_object(collection, obj, parent_obj)
        obj.location = Vector((loc_x, loc_y, 0.0))
        layout.apply_ui_local_trs(obj, el, pixel_scale=pixel_scale, base_z=0.0)

    try:
        ui = obj.ksp_ui
        ui.is_ksp_ui = True
        ui.element_name = el.name
        ui.kind = el.kind
        try:
            obj["ksp_export_go_name"] = el.name
        except Exception:
            pass
        try:
            from .locale_buffers import stamp_shipped_locale_from_name
            stamp_shipped_locale_from_name(obj)
        except Exception:
            pass
        ui.mb_path_id = str(el.mb_path_id)
        ui.go_path_id = str(el.go_path_id)
        ui.rect_path_id = str(el.rect_path_id)
        try:
            ui.parent_rect_path_id = str(el.parent_rect_path_id or "")
            obj["ksp_parent_rect"] = str(el.parent_rect_path_id or "")
        except Exception:
            pass
        ui.text = el.text
        ui.font_size = el.font_size
        ui.color = el.color
        ui.anchored_position = el.anchored_position
        ui.size_delta = el.size_delta
        ui.pivot = el.pivot
        ui.anchor_min = el.anchor_min
        ui.anchor_max = el.anchor_max
        try:
            ui.local_rotation = tuple(getattr(el, "local_rotation", (0, 0, 0, 1)))
            ui.local_scale = tuple(getattr(el, "local_scale", (1, 1, 1)))
            ui.local_position_z = float(getattr(el, "local_position_z", 0.0) or 0.0)
        except Exception:
            pass
        ui.text_alignment = int(getattr(el, "text_alignment", 0) or 0)
        ui.font_style = int(getattr(el, "font_style", 0) or 0)
        ui.enable_word_wrapping = bool(getattr(el, "enable_word_wrapping", True))
        ui.line_spacing = float(getattr(el, "line_spacing", 0.0) or 0.0)
        ui.margin = tuple(getattr(el, "margin", (0.0, 0.0, 0.0, 0.0)))
        ui.font_family = str(getattr(el, "font_family", "") or "")
    except Exception:
        pass
    try:
        from . import locale_buffers as _lb
        _lb.stamp_import_content_size(obj, abs(crect.width), abs(crect.height))
    except Exception:
        pass
    try:
        if el.kind == "text":
            # Stamp Unity face at import — .lang often has empty font_family
            # and must not wipe OpenSans/Amaranth on locale rebuild.
            try:
                fam0 = str(getattr(el, "font_family", "") or "")
                if not fam0.strip():
                    fam0 = str(getattr(ui, "font_family", "") or "")
                if fam0.strip():
                    obj["ksp_import_font_family"] = fam0
            except Exception:
                pass
                obj["ksp_text_display"] = display_text
            try:
                from .viewport import preserve_overlay_newlines
                src_txt = preserve_overlay_newlines(str(el.text or ""))
            except Exception:
                src_txt = str(el.text or "")
            try:
                obj["ksp_text_source"] = src_txt
            except Exception:
                pass
            try:
                from .viewport import is_artwork_overlay
                if is_artwork_overlay(el.text or "", obj):
                    obj["ksp_artwork_overlay"] = True
            except Exception:
                pass
            try:
                from .locale_switch import hierarchy_key_for_element
                hier = hierarchy_key_for_element(bundle, el)
                if hier:
                    obj["ksp_hierarchy"] = hier
            except Exception:
                pass
    except Exception:
        pass
    for item in kb.ui_elements:
        if item.rect_path_id == str(el.rect_path_id):
            try:
                item.viewport_object = obj
                if page_screen:
                    item.page_screen = page_screen
            except Exception:
                pass
            break
    if page_screen:
        _tag_ui_page(kb, el, page_screen)
    return obj


def _build_ui_viewport(collection, root, bundle, kb, pixel_scale):
    from .progress_util import tick, tick_items

    tex_images = {}
    for i, tex in enumerate(bundle.textures):
        if i < len(kb.textures) and kb.textures[i].image:
            tex_images[tex.path_id] = kb.textures[i].image

    sx = float(pixel_scale)
    fb = _fallback_canvas_size(bundle)
    all_els = list(bundle.ui_elements or [])
    mode = layout.classify_ui_layout_mode(all_els)
    # Locale: build only preferred tree in viewport; export still has all in kb
    if mode == "locale":
        pref = set(int(x) for x in (getattr(bundle, "preferred_locale_rect_ids", None) or []))
        if pref:
            all_els = [el for el in all_els if int(getattr(el, "rect_path_id", 0) or 0) in pref]
    try:
        kb.layout_mode = mode
    except Exception:
        pass

    # --- Multi-page wiki (JNSQ/GEP): object tree under one bundle root ---
    if mode == "multipage":
        tick(55, text="Building multipage TOC…")
        ui_root = _make_empty(
            collection, "%s_UI" % (bundle.name or "KSP"), root, size=0.06
        )
        src = (getattr(kb, "source_path", "") or getattr(bundle, "filepath", None) or "")
        index = kspedia_index.parse_kspedia_from_bundle_text_assets(
            bundle.text_assets, filepath=src
        )
        folders = _build_toc_folders(collection, ui_root, index)
        uncategorized = None
        groups = layout.group_ui_elements_by_root(all_els)
        try:
            kb.page_count = len(groups)
        except Exception:
            pass
        page_names = [((r.name or "").strip()) for r, _ in groups]
        overrides = kspedia_index.mark_overrides_against_stock(
            page_names + kspedia_index.screens_in_index(index),
            filepath=src,
            pack_bundle=(getattr(kb, 'bundle_name', '') or ''),
        )
        page_by_screen = {}
        n_pages = max(len(groups), 1)
        built_i = 0
        for page_i, (root_el, subtree) in enumerate(groups):
            tab_name = (root_el.name or ("Page_%d" % page_i)).strip() or (
                "Page_%d" % page_i
            )
            # Prefab leftover after Del Page: still in UnityFS / catalog, gone
            # from <Categories>. Skip any Screen id, not a specific page name.
            try:
                if kspedia_index.is_deleted_toc_screen(tab_name, index):
                    continue
            except Exception:
                pass
            tick_items(
                built_i, n_pages, 58, 90,
                text="Building page %d/%d…" % (page_i + 1, n_pages),
                every=1,
            )
            built_i += 1
            display_title = index.screen_titles.get(tab_name, tab_name)
            parent_path = index.screen_paths.get(tab_name)
            if parent_path is not None and parent_path in folders:
                parent_obj = folders[parent_path]
            else:
                if uncategorized is None:
                    uncategorized = _make_empty(
                        collection, "Uncategorized", ui_root, size=0.04
                    )
                    try:
                        uncategorized["ksp_toc_kind"] = "category"
                        uncategorized["ksp_display_title"] = "Uncategorized"
                    except Exception:
                        pass
                parent_obj = uncategorized

            # Avoid Blender ".001" clash with category folder of the same title
            page_name = tab_name
            try:
                if parent_obj is not None and parent_obj.name == tab_name:
                    page_name = "%s_page" % tab_name
            except Exception:
                pass
            page_root = _make_empty(collection, page_name, parent_obj, size=0.05)
            try:
                page_root["ksp_page"] = tab_name
                page_root["ksp_page_index"] = page_i
                page_root["ksp_display_title"] = display_title
                page_root["ksp_toc_kind"] = "page"
                page_root["ksp_overrides_stock"] = tab_name in overrides
            except Exception:
                pass
            page_by_screen[tab_name] = page_root

            rects = layout.compute_all_rects(subtree, root_fallback_size=fb)
            ordered = layout.topological_ui_elements(subtree)
            rect_objs = {}
            for el in ordered:
                is_page_root = (
                    int(getattr(el, "rect_path_id", 0) or 0)
                    == int(getattr(root_el, "rect_path_id", 0) or 0)
                )
                if is_page_root:
                    parent_el_obj = page_root
                elif el.parent_rect_path_id and el.parent_rect_path_id in rect_objs:
                    parent_el_obj = rect_objs[el.parent_rect_path_id]
                else:
                    parent_el_obj = page_root

                crect = rects.get(int(el.rect_path_id))
                if crect is None:
                    crect = layout.compute_rect(
                        el.anchored_position,
                        el.size_delta,
                        el.anchor_min,
                        el.anchor_max,
                        el.pivot,
                        fb[0],
                        fb[1],
                        (0.5, 0.5),
                        offset_min=getattr(el, "offset_min", None),
                        offset_max=getattr(el, "offset_max", None),
                    )
                obj = _build_one_ui_element(
                    collection, el, parent_el_obj, crect, ordered, rects,
                    bundle, kb, tex_images, pixel_scale, sx,
                    local_origin=is_page_root,
                    page_screen=tab_name,
                )
                rect_objs[el.rect_path_id] = obj

        _populate_toc_props(kb, index, page_by_screen, folders, overrides)
        _resolve_toc_display_titles(kb, filepath=src)
        try:
            from .mu_ops import sync_outliner_order_to_toc
            sync_outliner_order_to_toc(root)
        except Exception:
            pass
        try:
            kb.display_title = index.name or (bundle.name or root.name)
            if index.entries:
                for e in index.entries:
                    if e.kind == "category" and e.title:
                        kb.display_title = e.title
                        break
        except Exception:
            pass
        show_first_toc_page(root)
        viewport.setup_ui_view()
        try:
            from .locale_switch import finalize_imported_layout
            finalize_imported_layout(root)
        except Exception:
            pass
        return ui_root

    # --- Single-page / locale (original path) ---
    tick(55, text="Building UI elements…")
    canvas = _make_empty(collection, bundle.name + "_UI", root, size=0.1)

    rects = layout.compute_all_rects(all_els, root_fallback_size=fb)
    elements = layout.topological_ui_elements(all_els)

    rect_objs = {}
    n_el = max(len(elements), 1)
    for i, el in enumerate(elements):
        tick_items(i, n_el, 58, 90, text="Building UI elements…")
        parent_obj = canvas
        if el.parent_rect_path_id and el.parent_rect_path_id in rect_objs:
            parent_obj = rect_objs[el.parent_rect_path_id]

        crect = rects.get(int(el.rect_path_id))
        if crect is None:
            crect = layout.compute_rect(
                el.anchored_position,
                el.size_delta,
                el.anchor_min,
                el.anchor_max,
                el.pivot,
                fb[0],
                fb[1],
                (0.5, 0.5),
                offset_min=getattr(el, "offset_min", None),
                offset_max=getattr(el, "offset_max", None),
            )
        obj = _build_one_ui_element(
            collection, el, parent_obj, crect, elements, rects,
            bundle, kb, tex_images, pixel_scale, sx,
            local_origin=False,
        )
        rect_objs[el.rect_path_id] = obj

    viewport.setup_ui_view()
    _populate_single_page_toc(kb, bundle, canvas, root)
    try:
        from .locale_switch import finalize_imported_layout
        finalize_imported_layout(root)
    except Exception:
        pass
    return canvas


def _populate_single_page_toc(kb, bundle, canvas, root):
    """Minimal TOC + display title for single/locale pages."""
    try:
        kb.toc_nodes.clear()
    except Exception:
        return
    src = getattr(bundle, "filepath", None) or getattr(kb, "source_path", "") or ""
    index = kspedia_index.parse_kspedia_from_bundle_text_assets(
        bundle.text_assets, filepath=src
    )
    title = ""
    screen = ""
    if index.entries:
        for e in index.entries:
            if e.kind == "page" and e.screen:
                title = e.title or e.screen
                screen = e.screen
                break
        if not title:
            for e in index.entries:
                if e.title:
                    title = e.title
                    break
    # Stock / DLC single-page .ksp has no Categories XML — titles live in
    # Squad/KSPedia/kspedia.ksp or DLC master indexes (makinghistory / serenity).
    if not title or title == (bundle.name or ""):
        catalog = kspedia_index.load_catalog_index(src)
        stem = os.path.splitext(os.path.basename(src or ""))[0] or (
            bundle.name or ""
        )
        sid, stitle = kspedia_index.lookup_screen_for_bundle(catalog, stem)
        if not sid and bundle.name:
            sid, stitle = kspedia_index.lookup_screen_for_bundle(
                catalog, bundle.name
            )
        if sid:
            screen = screen or sid
            title = stitle or title
    if not title:
        title = (bundle.name or root.name or "Page").replace("_", " ")
    try:
        kb.display_title = title
        root["ksp_display_title"] = title
        if canvas is not None:
            canvas["ksp_display_title"] = title
            canvas["ksp_page"] = screen or canvas.get("ksp_page", "")
    except Exception:
        pass
    # Fill BundleName / AssetPath / title_raw from stock + DLC Screen catalogs
    catalog = None
    try:
        catalog = kspedia_index.load_catalog_index(src)
    except Exception:
        catalog = None
    bname = ""
    apath = ""
    traw = ""
    if catalog is not None and screen:
        bname = (catalog.screen_bundles or {}).get(screen, "")
        apath = (getattr(catalog, "screen_assets", None) or {}).get(screen, "")
        traw = (catalog.screen_titles_raw or {}).get(screen, "")
    if not bname and catalog is not None:
        sid2, _ = kspedia_index.lookup_screen_for_bundle(
            catalog, os.path.splitext(os.path.basename(src or ""))[0]
        )
        if sid2:
            screen = screen or sid2
            bname = (catalog.screen_bundles or {}).get(sid2, "")
            apath = (getattr(catalog, "screen_assets", None) or {}).get(sid2, "")
            traw = (catalog.screen_titles_raw or {}).get(sid2, "") or traw
            if not title or title == (bundle.name or ""):
                title = (catalog.screen_titles or {}).get(sid2, "") or title

    node = kb.toc_nodes.add()
    node.kind = 'page'
    node.depth = 0
    node.name = screen or (bundle.name or root.name)
    node.title = title
    node.title_raw = traw or title
    node.screen = screen or node.name
    node.bundle_name = bname
    node.asset_path = apath
    node.page_object = canvas
    node.page_index = 0
    node.expanded = True
    try:
        # Official DLC/stock page is not an "override" of itself.
        stock_hits = kspedia_index.mark_overrides_against_stock(
            [screen] if screen else [],
            filepath=src,
            pack_bundle=(getattr(kb, 'bundle_name', '') or bname or ''),
        )
        node.overrides_stock = bool(screen and screen in stock_hits)
    except Exception:
        pass


def import_ksp(collection, filepath, pixel_scale=None, build_viewport=True):
    """Import a .ksp AssetBundle into collection.

    Returns the root empty object.
    """
    from .progress_util import tick

    if pixel_scale is None:
        pixel_scale = viewport.DEFAULT_PIXEL_SCALE

    tick(2, text="Resolving path…")
    orig_path = os.path.abspath(filepath or "")
    load_path, prefer_locale = resolve_ksp_import_path(filepath)
    tick(5, text="Loading UnityFS…", force=True)
    bundle, env = load_bundle(load_path)
    tick(22, text="Extracting fonts…")
    try:
        from . import fonts_resolve
        fonts_resolve.extract_embedded_fonts_from_env(env, load_path)
    except Exception:
        pass

    # Drop legacy collection-based multipage trees from older addon builds.
    try:
        _cleanup_legacy_pages_collections(bundle.name)
    except Exception:
        pass

    tick(25, text="Creating bundle root…")
    root = _make_empty(collection, bundle.name, None, size=0.05)

    kb = root.ksp_bundle
    scope = _import_scope_id(root, bundle)
    _fill_bundle_props(
        kb, bundle, os.path.abspath(load_path), scope=scope,
    )
    try:
        root["ksp_import_scope"] = scope
    except Exception:
        pass
    kb.pixel_scale = float(pixel_scale)
    if prefer_locale:
        try:
            kb.locale = prefer_locale
            kb["active_locale"] = prefer_locale
        except Exception:
            pass

    if build_viewport:
        tick(52, text="Building viewport…", force=True)
        if bundle.kind == "kspedia_ui":
            _build_ui_viewport(collection, root, bundle, kb, pixel_scale)
            viewport.setup_ui_view()
        elif bundle.kind == "xml_index":
            _build_kspedia_index_viewport(collection, root, bundle, kb)
        else:
            y = 0.0
            n_tex = len(bundle.textures)
            for i, tex in enumerate(bundle.textures):
                from .progress_util import tick_items
                tick_items(i, n_tex, 52, 90, text="Building texture planes…")
                img = kb.textures[i].image if i < len(kb.textures) else None
                if img is None:
                    continue
                w = tex.width * pixel_scale
                h = tex.height * pixel_scale
                mat = viewport.make_unlit_image_material(
                    "%s__%s_Mat" % (_import_scope_id(root, bundle), tex.name),
                    img,
                )
                plane = viewport.create_image_plane(
                    collection, tex.name, w, h, mat
                )
                plane.parent = root
                plane.location = (0.0, y, 0.0)
                y -= h * 1.05
        # If user opened a .lang (or non-default locale), apply its texts now.
        # Seed maps from the picked .lang — never stamp the English UnityFS
        # under es-es / de-de (that showed English strings in every language).
        if prefer_locale:
            tick(92, text="Applying locale texts…")
            try:
                from .locale_switch import apply_text_map_to_viewport, path_for_locale
                from . import locale_buffers
                seed_path = orig_path
                if not str(seed_path).lower().endswith(".lang"):
                    seed_path = path_for_locale(
                        os.path.abspath(load_path), prefer_locale
                    ) or os.path.abspath(load_path)
                maps = locale_buffers.ensure_locale_maps(
                    kb, prefer_locale, seed_path
                )
                if maps:
                    apply_text_map_to_viewport(
                        root, maps, locale=prefer_locale, pixel_scale=float(pixel_scale),
                    )
            except Exception as exc:
                print("WARNING: KSP apply locale texts failed: %s" % exc)

    tick(95, text="Caching locale maps…")
    try:
        from .locale_switch import locale_maps_from_bundle
        from . import locale_buffers
        loc = (
            (prefer_locale or getattr(kb, "active_locale", "") or getattr(kb, "locale", "") or "en-us")
        ).lower()
        if not locale_buffers.has_locale_maps(kb, loc):
            # Never store the English viewport bundle as a non-English locale.
            en_like = loc in ("en-us", "en", "en-gb") or not prefer_locale
            if en_like:
                locale_buffers.store_maps(kb, loc, locale_maps_from_bundle(bundle))
            else:
                try:
                    from .locale_switch import path_for_locale
                    lang_path = orig_path if str(orig_path).lower().endswith(".lang") else path_for_locale(
                        os.path.abspath(load_path), loc
                    )
                    if lang_path:
                        locale_buffers.seed_from_disk(kb, loc, lang_path)
                except Exception as exc:
                    print("WARNING: KSP seed locale maps failed: %s" % exc)
        locale_buffers.set_prev_locale(kb, loc)
        try:
            from . import properties as _props
            if getattr(kb, "toc_nodes", None) and len(kb.toc_nodes):
                _props.capture_toc_titles(kb, loc)
        except Exception:
            pass
        locale_buffers.schedule_preload_sibling_locales(
            kb, os.path.abspath(load_path), skip_locale=loc,
        )
    except Exception:
        pass

    root["ksp_kind"] = bundle.kind
    root["ksp_source"] = os.path.abspath(load_path)
    # Do not auto-embed on import: multi-MB Text writes freeze the UI.
    # User embeds explicitly via the Source-row PACKAGE icon.
    tick(100, text="Import complete", force=True)
    return root


def _build_kspedia_index_viewport(collection, root, bundle, kb):
    """Nest full Categories / Screen catalog from kspedia.ksp into TOC + empties."""
    src = getattr(kb, "source_path", "") or getattr(bundle, "filepath", "") or ""
    index = kspedia_index.parse_kspedia_from_bundle_text_assets(
        bundle.text_assets, filepath=src
    )
    try:
        kb.is_kspedia_index = True
        kb.layout_mode = "multipage"
        kb.page_count = sum(1 for e in index.entries if e.kind == "page")
        kb.display_title = index.name or "KSPedia"
    except Exception:
        pass
    ui_root = _make_empty(
        collection, "%s_TOC" % (bundle.name or "KSPedia"), root, size=0.06
    )
    folders = _build_toc_folders(collection, ui_root, index)
    page_by_screen = {}
    for entry in index.entries:
        if entry.kind != "page" or not entry.screen:
            continue
        parent_path = entry.parent_path
        parent_obj = folders.get(parent_path, ui_root)
        page = _make_empty(
            collection, entry.title or entry.screen, parent_obj, size=0.04
        )
        try:
            page["ksp_page"] = entry.screen
            page["ksp_display_title"] = entry.title
            page["ksp_title_raw"] = entry.title_raw or entry.title
            page["ksp_toc_kind"] = "page"
            bname = (index.screen_bundles or {}).get(entry.screen, "")
            if bname:
                page["ksp_bundle_name"] = bname
        except Exception:
            pass
        page_by_screen[entry.screen] = page
    overrides = kspedia_index.mark_overrides_against_stock(
        list(page_by_screen.keys()),
        filepath=src,
        pack_bundle=(getattr(kb, 'bundle_name', '') or ''),
    )
    _populate_toc_props(kb, index, page_by_screen, folders, overrides)
    _resolve_toc_display_titles(kb, filepath=src)
    try:
        from .mu_ops import sync_outliner_order_to_toc
        sync_outliner_order_to_toc(root)
    except Exception:
        pass
    # Stock integrity / GameData drift
    try:
        diffs = kspedia_index.diff_against_gamedata_stock(src, index)
        if not diffs and src:
            # Compare against shipped fingerprint when importing live stock
            diffs = kspedia_index.diff_against_stock_fingerprint(index)
        # When identical to fingerprint, keep empty; when importing stock file
        # that matches fingerprint, report OK line
        if not diffs:
            kb.stock_diff_report = "OK: matches stock fingerprint"
        else:
            kb.stock_diff_report = "\n".join(diffs[:80])
            print("INFO: KSPedia stock diff (%d):" % len(diffs))
            for line in diffs[:20]:
                print("  ", line)
    except Exception as e:
        try:
            kb.stock_diff_report = "diff error: %s" % e
        except Exception:
            pass
