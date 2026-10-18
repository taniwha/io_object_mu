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
"""PropertyGroups for KSP .ksp AssetBundle editing."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


# UI / TMP paragraphs can exceed Blender's default StringProperty cap (1024).
_TEXT_MAXLEN = 16384


def _skip_id_mutating_update():
    """Property updates must not create/delete IDs during undo/redo."""
    try:
        from .blend_persist import in_undo_redo
        return bool(in_undo_redo())
    except Exception:
        return False


bundle_kind_items = (
    ('kspedia_ui', "KSPedia UI", "UI page with RectTransforms / TextMeshPro"),
    ('xml_index', "XML Index", "TextAsset-only index / definition bundle"),
    ('shaders', "Shaders", "Shader AssetBundle"),
    ('textures', "Textures", "Texture-only AssetBundle"),
    ('other', "Other", "Unclassified AssetBundle"),
)

ui_kind_items = (
    ('empty', "Empty", ""),
    ('text', "Text", "TextMeshPro / UI text"),
    ('image', "Image", "UI Image / Sprite"),
    ('meta', "Meta", "Button/Toggle/Layout/Canvas/Outline/…"),
)

toc_kind_items = (
    ('category', "Category", "Top-level KSPedia category"),
    ('subcategory', "Subcategory", "Nested KSPedia subcategory"),
    ('page', "Page", "Screen / TitleScreen prefab"),
)


def _select_viewport_object(context, obj):
    if obj is None or context is None:
        return
    if _suppress_ui_element_select:
        return
    prev_active = None
    try:
        prev_active = context.view_layer.objects.active
    except Exception:
        prev_active = None
    try:
        for o in context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        # Highlight this element's own FONT/MESH only — never a nested UI
        # text/image (ConfS3 must not also select ConfT3 under it).
        active = obj

        def _under_nested_ui(ch):
            cur = getattr(ch, "parent", None)
            while cur is not None and cur != obj:
                try:
                    if cur.ksp_ui.is_ksp_ui:
                        return True
                except Exception:
                    pass
                try:
                    cur = cur.parent
                except Exception:
                    break
            return False

        try:
            for ch in list(getattr(obj, "children_recursive", []) or []):
                if _under_nested_ui(ch):
                    continue
                try:
                    # Nested UI root (another list row) — never select it.
                    if ch.ksp_ui.is_ksp_ui and ch != obj:
                        continue
                except Exception:
                    pass
                if getattr(ch, "type", "") == "FONT":
                    ch.select_set(True)
                    active = ch
                    break
            if active is obj:
                for ch in list(getattr(obj, "children_recursive", []) or []):
                    if _under_nested_ui(ch):
                        continue
                    try:
                        if ch.ksp_ui.is_ksp_ui and ch != obj:
                            continue
                    except Exception:
                        pass
                    if getattr(ch, "type", "") == "MESH":
                        ch.select_set(True)
                        active = ch
                        break
        except Exception:
            active = obj
        context.view_layer.objects.active = active
        return
    except Exception:
        pass
    # Never leave the scene with an empty selection after a failed retarget
    # (hidden / excluded page) — that blanked the KSP panel mid-TOC edit.
    if prev_active is not None:
        try:
            prev_active.select_set(True)
            context.view_layer.objects.active = prev_active
        except Exception:
            pass


def _keep_bundle_root_selected(context, root, also_select=None):
    """Keep the bundle root active so the N-panel does not lose context.

    Optionally also select a page/folder (Outliner highlight) without making
    it the active object.
    """
    if root is None or context is None:
        return
    try:
        from .operators import pin_active_bundle
        pin_active_bundle(root, getattr(context, "scene", None))
    except Exception:
        pass
    if _suppress_ui_element_select:
        return
    try:
        for o in context.view_layer.objects:
            o.select_set(False)
        if also_select is not None and also_select != root:
            try:
                also_select.select_set(True)
            except Exception:
                pass
        root.select_set(True)
        context.view_layer.objects.active = root
    except Exception:
        pass


_suppress_ui_element_select = False


class _SuppressUiElementSelect:
    """Keep bundle root selected while operators reshuffle filters / lists."""

    def __enter__(self):
        global _suppress_ui_element_select
        self._prev = _suppress_ui_element_select
        _suppress_ui_element_select = True
        return self

    def __exit__(self, *exc):
        global _suppress_ui_element_select
        _suppress_ui_element_select = self._prev
        return False


def suppress_ui_element_select():
    return _SuppressUiElementSelect()



_ui_list_select_lock = False


def _update_ui_element_list_selected(self, context):
    """Checkbox in UI Elements: keep viewport multi-selection in sync."""
    global _ui_list_select_lock
    if _ui_list_select_lock or _skip_id_mutating_update():
        return
    if _suppress_ui_element_select or context is None:
        return
    try:
        from .operators import _find_bundle_root_from_context
        root = _find_bundle_root_from_context(context)
    except Exception:
        root = None
    if root is None:
        return
    kb = root.ksp_bundle
    objs = []
    try:
        for it in kb.ui_elements:
            if getattr(it, "list_selected", False) and it.viewport_object is not None:
                objs.append(it.viewport_object)
    except Exception:
        return
    if not objs and getattr(self, "viewport_object", None) is not None:
        # Just unchecked last box — leave viewport alone.
        return
    _ui_list_select_lock = True
    try:
        for o in context.view_layer.objects:
            try:
                o.select_set(False)
            except Exception:
                pass
        for o in objs:
            try:
                o.select_set(True)
            except Exception:
                pass
        if objs:
            try:
                context.view_layer.objects.active = objs[-1]
            except Exception:
                pass
    finally:
        _ui_list_select_lock = False


def _update_ui_elements_index(self, context):
    try:
        if _skip_id_mutating_update():
            return
        if _suppress_ui_element_select:
            return
        if not (0 <= self.ui_elements_index < len(self.ui_elements)):
            return
        global _ui_list_select_lock
        if not _ui_list_select_lock:
            _ui_list_select_lock = True
            try:
                idx = int(self.ui_elements_index)
                for i, it in enumerate(self.ui_elements):
                    want = (i == idx)
                    if bool(getattr(it, "list_selected", False)) != want:
                        it.list_selected = want
            finally:
                _ui_list_select_lock = False
        item = self.ui_elements[self.ui_elements_index]
        _select_viewport_object(context, item.viewport_object)
    except Exception:
        pass


_ui_element_rename_lock = False


def _update_ui_element_name(self, context):
    """F2 / inline rename in UI Elements: sync viewport + locale map keys."""
    global _ui_element_rename_lock
    if _skip_id_mutating_update() or _ui_element_rename_lock:
        return
    new_name = (getattr(self, "name", "") or "").strip()
    if not new_name:
        return
    vo = getattr(self, "viewport_object", None)
    old_name = ""
    old_hier = ""
    if vo is not None:
        try:
            old_name = (vo.ksp_ui.element_name or vo.name or "").strip()
        except Exception:
            try:
                old_name = (vo.name or "").strip()
            except Exception:
                old_name = ""
        try:
            old_hier = str(vo.get("ksp_hierarchy") or "").strip()
        except Exception:
            old_hier = ""
    if not old_name:
        old_name = new_name
    user_added = False
    if vo is not None:
        try:
            user_added = bool(vo.get("ksp_user_added"))
        except Exception:
            user_added = False
    new_hier = old_hier
    if user_added or (old_hier.startswith("user/") if old_hier else False):
        new_hier = "user/" + new_name
    _ui_element_rename_lock = True
    try:
        if vo is not None:
            try:
                vo.name = new_name
            except Exception:
                pass
            try:
                vo.ksp_ui.element_name = new_name
            except Exception:
                pass
            if user_added:
                try:
                    from .locale_buffers import encode_shipped_go_name
                    shipped = str(vo.get("ksp_shipped_locales") or "").strip()
                    locs = [x.strip() for x in shipped.split(",") if x.strip()]
                    vo["ksp_export_go_name"] = encode_shipped_go_name(
                        new_name, locs,
                    )
                except Exception:
                    vo["ksp_export_go_name"] = new_name
            if new_hier:
                try:
                    vo["ksp_hierarchy"] = new_hier
                except Exception:
                    pass
        if old_name == new_name and old_hier == new_hier:
            return
        root = _resolve_bundle_root(vo) if vo is not None else None
        if root is None and context is not None:
            scene = getattr(context, "scene", None)
            if scene is not None:
                for obj in scene.objects:
                    try:
                        kb = obj.ksp_bundle
                        if not kb.is_ksp_bundle:
                            continue
                        for it in kb.ui_elements:
                            if it == self:
                                root = obj
                                break
                        if root is not None:
                            break
                    except Exception:
                        continue
        if root is None:
            return
        kb = root.ksp_bundle
        kind = str(getattr(self, "kind", "") or "text")
        text = (getattr(self, "text", "") or "") if kind == "text" else None
        state = None
        if vo is not None:
            try:
                from . import locale_buffers as _lb
                state = _lb.snapshot_object_el_state(
                    vo,
                    pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
                )
            except Exception:
                state = None
        try:
            from . import locale_buffers as _lb
            locales = []
            for tag in (getattr(kb, "available_locales", "") or "").split(","):
                tag = tag.strip().lower()
                if tag and tag not in locales:
                    locales.append(tag)
            active = (getattr(kb, "active_locale", "") or "").lower()
            if active and active not in locales:
                locales.insert(0, active)
            if not locales and active:
                locales = [active]
            for loc in locales:
                try:
                    _lb.forget_element(kb, loc, hier=old_hier, name=old_name)
                except Exception:
                    pass
                try:
                    _lb.remember_element(
                        kb, loc, hier=new_hier, name=new_name,
                        kind=kind, state=state, text=text,
                    )
                except Exception:
                    pass
        except Exception:
            pass
    finally:
        _ui_element_rename_lock = False


def _update_textures_index(self, context):
    try:
        if _skip_id_mutating_update():
            return
        if not (0 <= self.textures_index < len(self.textures)):
            return
        item = self.textures[self.textures_index]
        img = item.image
        if img is None:
            return
        # Prefer object under current page filter
        page = self.filter_page_object
        candidates = []
        root = None
        try:
            # Walk owners: PropertyGroup is on Object.ksp_bundle
            pass
        except Exception:
            pass
        scene = getattr(context, "scene", None)
        if scene is None:
            return
        for obj in scene.objects:
            if obj.type != 'MESH':
                continue
            for slot in getattr(obj, "material_slots", []) or []:
                mat = slot.material
                if mat is None or not mat.use_nodes:
                    continue
                for node in mat.node_tree.nodes:
                    if getattr(node, "image", None) is img:
                        candidates.append(obj)
                        break
        if not candidates:
            return
        if page is not None:
            under = [o for o in candidates if _is_descendant(o, page)]
            if under:
                candidates = under
        _select_viewport_object(context, candidates[0])
    except Exception:
        pass


def _is_descendant(obj, ancestor):
    cur = obj
    while cur is not None:
        if cur == ancestor:
            return True
        cur = cur.parent
    return False


def _resolve_bundle_root(obj):
    cur = obj
    while cur is not None:
        try:
            if cur.ksp_bundle.is_ksp_bundle:
                return cur
        except Exception:
            pass
        cur = cur.parent
    return None


def _locale_enum_items(self, context):
    try:
        from .locale_switch import locale_enum_items
        return locale_enum_items(self, context)
    except Exception:
        loc = getattr(self, "locale", "") or "en-us"
        return [(loc, loc, "", 0)]


_LOCALE_TITLES = {}
_toc_title_lock = False
_locale_update_lock = False


def drop_titles_for_bundle(kb) -> None:
    """Drop all cached TOC titles for this PropertyGroup (delete / remove)."""
    global _LOCALE_TITLES
    try:
        ptr = int(kb.as_pointer())
    except Exception:
        ptr = id(kb)
    for key in [k for k in list(_LOCALE_TITLES.keys()) if k and k[0] == ptr]:
        _LOCALE_TITLES.pop(key, None)


def _titles_key(kb, locale):
    try:
        ptr = int(kb.as_pointer())
    except Exception:
        ptr = id(kb)
    return (ptr, (locale or "").lower())


def _locale_titles(kb, locale):
    """Page titles parsed from a .lang, cached so RAM switches skip the disk."""
    return _LOCALE_TITLES.get(_titles_key(kb, locale))


def _store_locale_titles(kb, locale, titles, *, prefer_existing: bool = False) -> None:
    """Store per-locale TOC titles.

    `prefer_existing=True`: disk/lang titles fill gaps; non-empty RAM edits
    win per screen key (so `New Page_de` survives preload, but a full EN
    snapshot cannot wipe DE titles from .lang).
    """
    key = _titles_key(kb, locale)
    incoming = dict(titles or {})
    if prefer_existing:
        prev = dict(_LOCALE_TITLES.get(key) or {})
        merged = dict(incoming)
        for k, v in prev.items():
            if (v or "").strip():
                merged[k] = v
        incoming = merged
    _LOCALE_TITLES[key] = incoming


def remember_toc_title(kb, locale: str, screen: str, title: str, *,
                       only_if_missing: bool = False) -> None:
    """Record one TOC title for one language (user edit / new page)."""
    loc = (locale or "").lower()
    sid = (screen or "").strip()
    if kb is None or not loc or not sid:
        return
    cur = dict(_locale_titles(kb, loc) or {})
    if only_if_missing and sid in cur and (cur.get(sid) or "").strip():
        return
    cur[sid] = (title or "").strip() or sid
    _store_locale_titles(kb, loc, cur)


def capture_toc_titles(kb, locale: str) -> None:
    """Snapshot live TOC row titles into that language's RAM map."""
    loc = (locale or "").lower()
    if kb is None or not loc:
        return
    cur = dict(_locale_titles(kb, loc) or {})
    try:
        nodes = kb.toc_nodes
    except Exception:
        return
    for node in nodes:
        try:
            sid = (node.screen or node.name or "").strip()
            title = (node.title or "").strip()
        except Exception:
            continue
        if sid and title:
            cur[sid] = title
    _store_locale_titles(kb, loc, cur)


def _stamp_toc_title_objects(node, title: str) -> None:
    """Push locale title onto TOC empties (display prop + Outliner name)."""
    title = (title or "").strip()
    kind = ""
    try:
        kind = str(getattr(node, "kind", "") or "")
    except Exception:
        kind = ""
    try:
        if node.folder_object is not None:
            node.folder_object["ksp_display_title"] = title
            if kind in ("category", "subcategory") and title:
                try:
                    node.folder_object.name = title[:60] or node.folder_object.name
                except Exception:
                    pass
    except Exception:
        pass
    try:
        if node.page_object is not None:
            node.page_object["ksp_display_title"] = title
            if kind == "page" and title:
                try:
                    node.page_object.name = title[:60] or node.page_object.name
                except Exception:
                    pass
    except Exception:
        pass


def apply_locale_toc_titles(kb, locale: str) -> int:
    """Show this language's TOC titles. Missing keys use default-locale / raw.

    User-added pages are per-locale: a ``_de`` suffix must not leak into EN,
    and a DE rename must survive EN→DE. Stock titles still come from the
    .lang XML cache.
    """
    global _toc_title_lock
    loc = (locale or "").lower()
    if kb is None or not loc:
        return 0
    titles = dict(_locale_titles(kb, loc) or {})
    default = (getattr(kb, "locale", "") or "en-us").lower()
    fallback = dict(_locale_titles(kb, default) or {}) if default != loc else {}
    n = 0
    _toc_title_lock = True
    try:
        for node in kb.toc_nodes:
            try:
                sid = (node.screen or node.name or "").strip()
            except Exception:
                continue
            if not sid:
                continue
            want = titles.get(sid) or ""
            if not want:
                want = fallback.get(sid) or ""
            if not want:
                raw = (getattr(node, "title_raw", "") or "").strip()
                if raw and not raw.startswith("#"):
                    want = raw
            if not want:
                # Never keep the previous language's live title on this row.
                want = sid
            try:
                if (node.title or "") != want:
                    node.title = want
                    n += 1
            except Exception:
                continue
            _stamp_toc_title_objects(node, want)
    finally:
        _toc_title_lock = False
    return n


def _update_active_locale(self, context):
    """Live-switch KSPedia texts when the Locale enum changes."""
    global _locale_update_lock
    if _locale_update_lock or _skip_id_mutating_update():
        return
    import os
    try:
        from .locale_switch import (
            apply_text_map_to_viewport,
            locale_maps_from_bundle,
            path_for_locale,
            sync_text_box_overlays,
        )
        from .bundle import load_bundle
        from . import fonts_resolve
    except Exception:
        return
    root = None
    scene = getattr(context, "scene", None) if context else None
    if scene is not None:
        for obj in scene.objects:
            try:
                if obj.ksp_bundle == self:
                    root = obj
                    break
            except Exception:
                continue
    if root is None and context is not None:
        try:
            ao = context.view_layer.objects.active
        except Exception:
            ao = None
        root = _resolve_bundle_root(ao)
        try:
            if root is not None and root.ksp_bundle != self:
                root = None
        except Exception:
            root = None
    if root is None:
        return
    src = getattr(self, "source_path", "") or ""
    loc = getattr(self, "active_locale", "") or ""
    path = path_for_locale(src, loc)
    from . import locale_buffers
    maps = None
    try:
        maps = locale_buffers.get_maps(self, loc)
    except Exception:
        maps = None
    if not maps:
        try:
            maps = locale_buffers.ensure_locale_maps(self, loc, src)
        except Exception:
            maps = None
    # Sibling .lang on disk is optional — Add Locale is RAM-only until Export.
    if not maps and (not path or not os.path.isfile(path)):
        return

    # Park the language we are leaving, then prefer what is already in RAM.
    # Reading the .lang back from disk on every switch is what threw away
    # hand tuning: widths, colours, fonts, moves — all of it, every time.
    _locale_update_lock = True
    n = 0
    bundle = None
    try:
        try:
            # Park the language on screen. prev is empty after import; locale
            # still holds the outgoing tag until we assign it below.
            locale_buffers.set_live_sync_lock(True)
            locale_buffers.park_outgoing_locale(self, root, loc)
        except Exception as exc:
            try:
                print("WARNING: KSP locale park failed: %s" % exc)
            except Exception:
                pass
        try:
            prev = locale_buffers.infer_outgoing_locale(self, root)
            if prev and prev != loc:
                capture_toc_titles(self, prev)
        except Exception:
            pass

        if not maps:
            try:
                maps = locale_buffers.ensure_locale_maps(self, loc, src)
            except Exception:
                maps = None
        # Fonts: only when this language is not already in RAM. Preload + prior
        # switches leave maps hot — re-extracting from every .lang made EN↔DE slow.
        if not maps and path and os.path.isfile(path):
            try:
                fonts_resolve.extract_embedded_fonts_from_path(path)
            except Exception:
                pass
            if src and os.path.isfile(src) and os.path.abspath(src) != os.path.abspath(path):
                try:
                    fonts_resolve.extract_embedded_fonts_from_path(src)
                except Exception:
                    pass
        if not maps and path and os.path.isfile(path):
            try:
                bundle, _env = load_bundle(path)
            except Exception:
                return
            maps = locale_maps_from_bundle(bundle)
            try:
                locale_buffers.store_maps(self, loc, maps)
                maps = locale_buffers.get_maps(self, loc) or maps
            except Exception:
                pass
        if not maps:
            return
        try:
            n = apply_text_map_to_viewport(
                root,
                maps,
                locale=loc,
                pixel_scale=float(getattr(self, "pixel_scale", 0.001) or 0.001),
            )
        except Exception as exc:
            try:
                print("WARNING: KSP locale apply failed: %s" % exc)
            except Exception:
                pass
            n = 0
        # Point live-sync at the language now on screen BEFORE unlocking — otherwise
        # a deferred unlock writes the new viewport into the outgoing .lang maps
        # (EN text leaked into de-de.lang on Export).
        try:
            locale_buffers.set_prev_locale(self, loc)
        except Exception:
            pass
        try:
            self.locale = loc
        except Exception:
            pass
        try:
            title_by_screen = _locale_titles(self, loc)
            if (not title_by_screen) and path and os.path.isfile(path):
                from . import kspedia_index
                if bundle is None:
                    bundle, _env = load_bundle(path)
                idx = kspedia_index.parse_kspedia_from_bundle_text_assets(
                    bundle.text_assets, filepath=path
                )
                title_by_screen = {}
                for e in getattr(idx, "entries", None) or []:
                    if e.kind == "page" and e.screen and e.title:
                        title_by_screen[e.screen] = e.title
                    if e.kind in ("category", "subcategory") and getattr(
                        e, "title_screen", ""
                    ):
                        if e.title:
                            title_by_screen[e.title_screen] = e.title
                _store_locale_titles(
                    self, loc, title_by_screen, prefer_existing=True
                )
            apply_locale_toc_titles(self, loc)
            # Bundle display title = first category title or TitleScreen
            for node in self.toc_nodes:
                if node.kind in {'category', 'subcategory'} and node.title:
                    try:
                        # Skip update callback — must not rewrite the selected TOC row.
                        self["display_title"] = node.title
                    except Exception:
                        pass
                    break
                if (node.screen or "").lower() == "titlescreen" and node.title:
                    try:
                        self["display_title"] = node.title
                    except Exception:
                        pass
                    break
        except Exception:
            pass
        try:
            if getattr(self, "show_text_boxes", False):
                sync_text_box_overlays(
                    root,
                    True,
                    pixel_scale=float(getattr(self, "pixel_scale", 0.001) or 0.001),
                )
        except Exception:
            pass
        try:
            print("INFO: KSP locale → %s (%d texts)" % (loc, n))
        except Exception:
            pass
    finally:
        _locale_update_lock = False
        try:
            locale_buffers.release_live_sync_lock_deferred()
        except Exception:
            pass


def _update_show_text_boxes(self, context):
    """Toggle RectTransform box overlays for all KSPedia text roots."""
    if _skip_id_mutating_update():
        return
    try:
        from .locale_switch import sync_text_box_overlays, _clear_text_box_edit_handles
    except Exception:
        return
    # Edit Text Boxes is disabled — never leave handles / flag on.
    try:
        if bool(getattr(self, "edit_text_boxes", False)):
            try:
                self["edit_text_boxes"] = False
            except Exception:
                pass
        _clear_text_box_edit_handles()
    except Exception:
        pass
    root = None
    scene = getattr(context, "scene", None) if context else None
    if scene is not None:
        for obj in scene.objects:
            try:
                if obj.ksp_bundle == self:
                    root = obj
                    break
            except Exception:
                continue
    if root is None and context is not None:
        try:
            ao = context.view_layer.objects.active
        except Exception:
            ao = None
        root = _resolve_bundle_root(ao)
        try:
            if root is not None and root.ksp_bundle != self:
                root = None
        except Exception:
            root = None
    if root is None:
        return
    try:
        # Whole active bundle — not only the selected TOC row.
        sync_text_box_overlays(
            root,
            bool(getattr(self, "show_text_boxes", False)),
            pixel_scale=float(getattr(self, "pixel_scale", 0.001) or 0.001),
            scope=None,
        )
    except Exception:
        pass


def _update_bundle_display_title(self, context):
    """Bundle-level label only — never write onto the selected TOC row.

    Export / locale refresh used to set ``display_title`` to the root category
    (``Planetary Base Systems``) and this callback copied it onto whichever
    page or subcategory was selected (e.g. Configuration).
    """
    return


def _update_toc_screen(self, context):
    if _skip_id_mutating_update():
        return
    try:
        from . import kspedia_index
        screen = (self.screen or "").strip()
        # Avoid load_catalog_index here — it freezes Add Page / Screen rename.
        idx = None
        # Autofill when catalog has nothing (new blank / sample pages)
        if screen and not (self.bundle_name or "").strip():
            try:
                from .operators import _find_bundle_root_from_context
                root = _find_bundle_root_from_context(context) if context else None
                if root is not None:
                    self.bundle_name = kspedia_index.default_bundle_name_for_kb(
                        root.ksp_bundle
                    )
            except Exception:
                pass
        # Local pack: Screen rename → AssetPath follows Screen id (not Title).
        if screen:
            try:
                from .operators import _find_bundle_root_from_context
                from .unityfs_catalog import host_bundle_stem, is_local_toc_node
                root = _find_bundle_root_from_context(context) if context else None
                host = host_bundle_stem(root.ksp_bundle) if root is not None else ""
                if is_local_toc_node(self, host) or not (self.bundle_name or "").strip():
                    want = kspedia_index.default_asset_path_for_screen(screen)
                    if (self.asset_path or "").strip() != want:
                        self.asset_path = want
                    if host and not (self.bundle_name or "").strip():
                        self.bundle_name = host
            except Exception:
                if screen and not (self.asset_path or "").strip():
                    try:
                        self.asset_path = kspedia_index.default_asset_path_for_screen(screen)
                    except Exception:
                        self.asset_path = "Assets/KSPedia/%s.prefab" % screen
        if screen and not (self.asset_path or "").strip():
            try:
                self.asset_path = kspedia_index.default_asset_path_for_screen(screen)
            except Exception:
                self.asset_path = "Assets/KSPedia/%s.prefab" % screen
        # Override = stock/DLC Screen in a non-official pack (use pack host,
        # not Screen BundleName which is often still "kspedia").
        try:
            own = ""
            try:
                from .operators import _find_bundle_root_from_context
                from .unityfs_catalog import host_bundle_stem
                r = _find_bundle_root_from_context(context) if context else None
                if r is not None:
                    own = host_bundle_stem(r.ksp_bundle) or (
                        getattr(r.ksp_bundle, "bundle_name", "") or ""
                    ).strip()
            except Exception:
                own = ""
            if not own:
                own = (self.bundle_name or "").strip()
            self.overrides_stock = kspedia_index.screen_overrides_base(
                screen, own, title=(self.title or "").strip(),
            )
        except Exception:
            self.overrides_stock = False
    except Exception:
        pass


def _update_toc_title(self, context):
    """Real-time title edit: sync display, per-locale RAM, patch XML."""
    global _toc_title_lock
    if _toc_title_lock or _skip_id_mutating_update():
        return
    try:
        title = (self.title or "").strip()
        kind = str(getattr(self, "kind", "") or "")
        # Folders own the Outliner empty; TitleScreen page_object must keep
        # its GO name or F2 / Title edits rename BackgroundBlack's parent page
        # and leave the TOC folder label pointing at the wrong active object.
        if kind in ("category", "subcategory"):
            if self.folder_object is not None:
                self.folder_object["ksp_display_title"] = title
                try:
                    self.folder_object.name = title[:60] or self.folder_object.name
                except Exception:
                    pass
            if self.page_object is not None:
                try:
                    self.page_object["ksp_display_title"] = title
                except Exception:
                    pass
        elif self.page_object is not None:
            self.page_object["ksp_display_title"] = title
            try:
                self.page_object.name = title[:60] or self.page_object.name
            except Exception:
                pass
        # Title is display-only — override flag follows Screen id (stock/DLC)
        try:
            from . import kspedia_index as _ki
            from .unityfs_catalog import host_bundle_stem
            root = _resolve_bundle_root(self.page_object) or _resolve_bundle_root(
                self.folder_object
            )
            kb = root.ksp_bundle if root is not None else None
            pack_host = ""
            if kb is not None:
                pack_host = (
                    host_bundle_stem(kb)
                    or (getattr(kb, "bundle_name", "") or "").strip()
                )
            if not pack_host:
                pack_host = (self.bundle_name or "").strip()
            self.overrides_stock = _ki.screen_overrides_base(
                (self.screen or "").strip(),
                pack_host,
                title=(self.title or "").strip(),
            )
        except Exception:
            pass
        # Keep the original XML/LOC key. Overwriting title_raw with a DE
        # suffix made that name the fallback on every language.
        raw = (getattr(self, "title_raw", "") or "")
        if not raw:
            self.title_raw = title
        # Sync bundle display_title when this is the active TOC row
        root = _resolve_bundle_root(self.page_object) or _resolve_bundle_root(
            self.folder_object
        )
        if root is None and context is not None:
            for obj in context.scene.objects:
                try:
                    if obj.ksp_bundle.is_ksp_bundle and (
                        0 <= obj.ksp_bundle.toc_nodes_index < len(obj.ksp_bundle.toc_nodes)
                    ):
                        if obj.ksp_bundle.toc_nodes[obj.ksp_bundle.toc_nodes_index] == self:
                            root = obj
                            break
                except Exception:
                    continue
        if root is not None:
            kb = root.ksp_bundle
            try:
                from .operators import pin_active_bundle
                pin_active_bundle(root, getattr(context, "scene", None) if context else None)
            except Exception:
                pass
            # Only the root category owns bundle display_title. Pushing every
            # subcategory edit upward made locale refresh / reselect rewrite
            # Configuration → Planetary Base Systems.
            if self.kind == "category" and int(getattr(self, "depth", 0) or 0) == 0:
                if kb.display_title != title:
                    kb.display_title = title
            loc = (
                getattr(kb, "active_locale", "")
                or getattr(kb, "locale", "")
                or ""
            ).lower()
            screen = (self.screen or self.name or "").strip()
            if loc and screen:
                remember_toc_title(kb, loc, screen, title)
            default = (getattr(kb, "locale", "") or "en-us").lower()
            # Live-patch the imported TextAsset only for the default language.
            # DE/FR titles live in RAM until sibling .lang export.
            try:
                from . import kspedia_index
                if screen and kb.text_assets and (not loc or loc == default):
                    xml_name = kb.kspedia_xml_asset
                    xml_name = kb.kspedia_xml_asset
                    target = None
                    for ta in kb.text_assets:
                        if xml_name and ta.name == xml_name:
                            target = ta
                            break
                    if target is None:
                        for ta in kb.text_assets:
                            if "kspedia" in (ta.name or "").lower() and "bundle" not in (ta.name or "").lower():
                                target = ta
                                break
                    if target is not None:
                        src = ""
                        if target.text_block:
                            src = target.text_block.as_string()
                        src = src or target.text or ""
                        write_title = title
                        if raw.startswith("#"):
                            write_title = raw  # keep LOC key in XML for stock index
                        new_xml = kspedia_index.set_screen_title_in_xml(
                            src, screen, write_title
                        )
                        if self.bundle_name or self.asset_path:
                            new_xml = kspedia_index.set_screen_meta_in_xml(
                                new_xml, screen,
                                bundle_name=(self.bundle_name or None),
                                asset_path=(self.asset_path or None),
                            )
                        target.text = new_xml
                        if target.text_block:
                            target.text_block.clear()
                            target.text_block.write(new_xml)
            except Exception:
                pass
    except Exception:
        pass


def _update_toc_index(self, context):
    """TOC click → show scope immediately + filter asset lists."""
    try:
        if _skip_id_mutating_update():
            return
        if not (0 <= self.toc_nodes_index < len(self.toc_nodes)):
            return
        node = self.toc_nodes[self.toc_nodes_index]
        from .import_ksp import set_active_bundle, show_multipage_scope

        scope = None
        select_obj = None
        if node.kind == 'page':
            scope = node.page_object
            select_obj = scope
        else:
            # Folder row: prefer the category empty — not the TitleScreen page
            # / BackgroundBlack mesh (Outliner F2 was renaming those).
            scope = node.folder_object
            select_obj = node.folder_object or node.page_object
            # Bind hidden Screen child so filter-to-page / Duplicate find it
            # by parent, not TOC visibility.
            if node.page_object is None and node.folder_object is not None:
                try:
                    from .mu_ops import _folder_screen_child, _attach_folder_title_screen
                    po = _folder_screen_child(node.folder_object, node.screen)
                    if po is not None:
                        _attach_folder_title_screen(node, po)
                except Exception:
                    pass

        root = _resolve_bundle_root(scope) or _resolve_bundle_root(
            getattr(context, "active_object", None)
        )
        # Fallback: owner of this PropertyGroup is not available; search scene
        if root is None and context is not None:
            for obj in context.scene.objects:
                try:
                    if obj.ksp_bundle.is_ksp_bundle and obj.ksp_bundle.as_pointer() == self.as_pointer():
                        root = obj
                        break
                except Exception:
                    continue

        if root is not None:
            set_active_bundle(root, context.scene)
            try:
                from .operators import pin_active_bundle
                pin_active_bundle(root, context.scene)
            except Exception:
                pass
            # Multipage unhide / filter updates must not steal the active
            # object via ui_elements / textures index callbacks.
            with suppress_ui_element_select():
                if self.layout_mode == 'multipage':
                    show_multipage_scope(root, scope)
                try:
                    self.filter_scope_object = scope
                    if node.kind == 'page':
                        self.filter_page_object = scope
                    # Folder: keep filter_page_object from show_multipage_scope
                    # (the visible TitleScreen / primary page, not the whole folder).
                except Exception:
                    pass
            # Keep the bundle root active. Selecting only the page/folder used
            # to blank the KSP panel when several KSPedia roots share the scene
            # (failed select after hide, or no parent walk). Highlight the
            # page/folder too so the Outliner still shows what TOC picked.
            _keep_bundle_root_selected(context, root, also_select=select_obj)
    except Exception:
        pass


class KSPMU_PG_KspTextureItem(PropertyGroup):
    name: StringProperty(name="Name")
    path_id: StringProperty(name="Path ID")
    width: IntProperty(name="Width")
    height: IntProperty(name="Height")
    image: PointerProperty(name="Image", type=bpy.types.Image)
    page_screen: StringProperty(
        name="Page Screen",
        description="KSPedia Screen id that uses this texture (if known)",
        default="",
    )
    texture_external: BoolProperty(
        name="External Texture",
        description="Resolved from dependency bundle (not written on export)",
        default=False,
    )
    texture_format: IntProperty(
        name="Texture Format",
        description="Unity TextureFormat enum (e.g. 10=DXT1). Kept on export.",
        default=0,
    )
    content_hash: StringProperty(
        name="Content Hash",
        description="SHA1 of imported PNG bytes; unchanged textures skip rewrite",
        default="",
    )
    dirty: BoolProperty(
        name="Dirty",
        description="Marked when image was edited; forces texture rewrite on export",
        default=False,
    )


class KSPMU_PG_KspTextAssetItem(PropertyGroup):
    name: StringProperty(name="Name")
    path_id: StringProperty(name="Path ID")
    text: StringProperty(
        name="Text",
        description="Inline text (huge assets use the Text datablock)",
        maxlen=_TEXT_MAXLEN,
    )
    text_block: PointerProperty(name="Text Block", type=bpy.types.Text)


class KSPMU_PG_KspShaderItem(PropertyGroup):
    name: StringProperty(name="Name")
    path_id: StringProperty(name="Path ID")


class KSPMU_PG_KspUiElementItem(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="UI element name (F2 / click to rename)",
        update=_update_ui_element_name,
    )
    path_id: StringProperty(name="Path ID")
    go_path_id: StringProperty(name="GameObject Path ID")
    rect_path_id: StringProperty(name="Rect Path ID")
    mb_path_id: StringProperty(name="MonoBehaviour Path ID")
    kind: EnumProperty(name="Kind", items=ui_kind_items, default='empty')
    missing_in_locale: BoolProperty(
        name="Missing In Locale",
        description="The active language file does not contain this element",
        default=False,
    )
    list_selected: BoolProperty(
        name="Selected",
        description="Multi-select in UI Elements (checkbox) / synced from viewport",
        default=False,
        update=_update_ui_element_list_selected,
    )
    text: StringProperty(name="Text", default="", maxlen=_TEXT_MAXLEN)
    font_size: FloatProperty(name="Font Size", default=14.0)
    color: FloatVectorProperty(
        name="Color", size=4, subtype='COLOR_GAMMA',
        default=(1.0, 1.0, 1.0, 1.0), min=0.0, max=1.0,
    )
    anchored_position: FloatVectorProperty(
        name="Anchored Position", size=3, subtype='XYZ'
    )
    size_delta: FloatVectorProperty(
        name="Size Delta", size=3, subtype='XYZ'
    )
    pivot: FloatVectorProperty(name="Pivot", size=2, default=(0.5, 0.5))
    anchor_min: FloatVectorProperty(
        name="Anchor Min", size=2, default=(0.5, 0.5)
    )
    anchor_max: FloatVectorProperty(
        name="Anchor Max", size=2, default=(0.5, 0.5)
    )
    offset_min: FloatVectorProperty(name="Offset Min", size=2, default=(0.0, 0.0))
    offset_max: FloatVectorProperty(name="Offset Max", size=2, default=(0.0, 0.0))
    has_offset_min: BoolProperty(name="Has Offset Min", default=False)
    has_offset_max: BoolProperty(name="Has Offset Max", default=False)
    local_rotation: FloatVectorProperty(
        name="Local Rotation",
        description="Unity RectTransform m_LocalRotation (x,y,z,w)",
        size=4,
        default=(0.0, 0.0, 0.0, 1.0),
    )
    local_scale: FloatVectorProperty(
        name="Local Scale",
        description="Unity RectTransform m_LocalScale",
        size=3,
        default=(1.0, 1.0, 1.0),
    )
    local_position_z: FloatProperty(
        name="Local Position Z",
        description="Unity RectTransform m_LocalPosition.z",
        default=0.0,
    )
    texture_path_id: StringProperty(name="Texture Path ID")
    sprite_path_id: StringProperty(name="Sprite Path ID")
    parent_rect_path_id: StringProperty(name="Parent Rect Path ID")

    text_alignment: IntProperty(name="Text Alignment", default=0)
    font_style: IntProperty(name="Font Style", default=0)
    is_rich_text: BoolProperty(name="Rich Text", default=True)
    enable_word_wrapping: BoolProperty(name="Word Wrapping", default=True)
    line_spacing: FloatProperty(name="Line Spacing", default=0.0)
    margin: FloatVectorProperty(name="Margin", size=4, default=(0.0, 0.0, 0.0, 0.0))
    font_family: StringProperty(name="Font Family", default="")
    texture_external: BoolProperty(name="External Texture", default=False)
    viewport_object: PointerProperty(
        name="Viewport Object", type=bpy.types.Object
    )
    page_screen: StringProperty(
        name="Page Screen",
        description="Owning multipage Screen id (if any)",
        default="",
    )

    font_asset_path_id: StringProperty(name="Font Asset Path ID", default="0")
    font_asset_file_id: StringProperty(name="Font Asset File ID", default="0")
    image_type: IntProperty(name="Image Type", default=0, min=0, max=3,
        description="0 Simple, 1 Sliced, 2 Tiled, 3 Filled")
    preserve_aspect: BoolProperty(name="Preserve Aspect", default=False)
    fill_center: BoolProperty(name="Fill Center", default=True)
    fill_method: IntProperty(name="Fill Method", default=0)
    fill_amount: FloatProperty(name="Fill Amount", default=1.0, min=0.0, max=1.0)
    fill_clock_wise: BoolProperty(name="Fill Clockwise", default=True)
    fill_origin: IntProperty(name="Fill Origin", default=0)
    is_raw_image: BoolProperty(name="Raw Image", default=False)
    horizontal_alignment: IntProperty(name="TMP Horizontal Align", default=0)
    vertical_alignment: IntProperty(name="TMP Vertical Align", default=0)
    outline_width: FloatProperty(name="Outline Width", default=0.0)
    outline_color: FloatVectorProperty(
        name="Outline Color", size=4, subtype='COLOR_GAMMA',
        default=(0.0, 0.0, 0.0, 1.0), min=0.0, max=1.0,
    )
    character_spacing: FloatProperty(name="Character Spacing", default=0.0)
    word_spacing: FloatProperty(name="Word Spacing", default=0.0)
    paragraph_spacing: FloatProperty(name="Paragraph Spacing", default=0.0)
    enable_auto_sizing: BoolProperty(name="Auto Size", default=False)
    font_size_min: FloatProperty(name="Font Size Min", default=0.0)
    font_size_max: FloatProperty(name="Font Size Max", default=0.0)
    overflow_mode: IntProperty(name="Overflow Mode", default=0)
    enable_kerning: BoolProperty(name="Kerning", default=True)
    locale_tag: StringProperty(name="Locale Tag", default="")
    face_color: FloatVectorProperty(
        name="Face Color", size=4, subtype='COLOR_GAMMA',
        default=(1.0, 1.0, 1.0, 1.0), min=0.0, max=1.0,
    )
    enable_vertex_gradient: BoolProperty(name="Vertex Gradient", default=False)
    tint_all_sprites: BoolProperty(name="Tint Sprites", default=False)
    horizontal_mapping: IntProperty(name="Horizontal Mapping", default=0)
    vertical_mapping: IntProperty(name="Vertical Mapping", default=0)
    is_volumetric_text: BoolProperty(name="Volumetric Text", default=False)
    page_to_display: IntProperty(name="Page To Display", default=1, min=0)
    linked_text_path_id: StringProperty(name="Linked Text Path ID", default="0")
    sprite_animator_path_id: StringProperty(
        name="Sprite Animator Path ID", default="0"
    )
    script_class: StringProperty(name="Script Class", default="")
    meta_scripts: StringProperty(name="Meta Scripts", default="")
    effect_distance: FloatVectorProperty(
        name="Effect Distance", size=2, default=(0.0, 0.0)
    )
    has_ui_outline: BoolProperty(name="UI Outline", default=False)
    has_ui_shadow: BoolProperty(name="UI Shadow", default=False)


class KSPMU_PG_KspMaterialItem(PropertyGroup):
    name: StringProperty(name="Name")
    path_id: StringProperty(name="Path ID")


class KSPMU_PG_KspExploreAssetItem(PropertyGroup):
    """One row in Menu Check → Explore Assets."""
    name: StringProperty(name="Name", default="")
    kind: StringProperty(name="Kind", default="")
    detail: StringProperty(name="Detail", default="")


class KSPMU_PG_KspTocNode(PropertyGroup):
    kind: EnumProperty(name="Kind", items=toc_kind_items, default='page')
    depth: IntProperty(name="Depth", default=0, min=0)
    name: StringProperty(name="Internal Name", default="")
    title: StringProperty(
        name="Title",
        description="KSPedia title (edit applies immediately)",
        default="",
        update=_update_toc_title,
    )
    title_raw: StringProperty(
        name="Title Raw",
        description="XML <Title> as stored (#autoLOC_* key or literal)",
        default="",
    )
    screen: StringProperty(name="Screen Id", default="", update=_update_toc_screen)
    bundle_name: StringProperty(
        name="Bundle Name",
        description="Screen catalog BundleName (kspedia_*.ksp stem)",
        default="",
    )
    asset_path: StringProperty(
        name="Asset Path",
        description="Screen catalog AssetPath (prefab path in bundle)",
        default="",
    )
    expanded: BoolProperty(name="Expanded", default=True)
    page_index: IntProperty(name="Page Index", default=-1)
    overrides_stock: BoolProperty(
        name="Overrides Stock/DLC",
        description=(
            "Same Screen id as Squad stock or official DLC KSPedia — game "
            "loads last AssetBundle (GEP/JNSQ style). Shown blue in TOC"
        ),
        default=False,
    )
    page_object: PointerProperty(name="Page Object", type=bpy.types.Object)
    folder_object: PointerProperty(name="Folder Object", type=bpy.types.Object)


class KSPMU_PG_KspFontItem(PropertyGroup):
    """One Font / TMP family persisted from the imported .ksp (no UnityFS)."""
    name: StringProperty(name="Name")
    path_id: StringProperty(name="Path ID", default="0")
    file_id: StringProperty(name="File ID", default="0")


class KSPMU_PG_KspBundle(PropertyGroup):
    is_ksp_bundle: BoolProperty(name="Is KSP Bundle", default=False)
    source_path: StringProperty(name="Source Path", subtype='FILE_PATH')
    source_embedded: BoolProperty(
        name="Source Embedded",
        description=(
            "UnityFS template bytes are stored in the .blend "
            "(export works without the external .ksp on disk)"
        ),
        default=False,
    )
    embedded_source_text: StringProperty(
        name="Embedded Source Text",
        description="Text datablock holding base64 of the source .ksp",
        default="",
    )
    template_path: StringProperty(
        name="Template Path",
        description="Optional template .ksp used when creating/exporting",
        subtype='FILE_PATH',
    )
    bundle_name: StringProperty(name="Bundle Name")
    bundle_kind: EnumProperty(
        name="Kind", items=bundle_kind_items, default='other'
    )
    layout_mode: EnumProperty(
        name="Layout Mode",
        items=(
            ('single', "Single", "One KSPedia page root"),
            ('locale', "Locale", "EN/CJK duplicate roots (one kept)"),
            ('multipage', "Multi-page", "Many tab/prefab roots (JNSQ/GEP wiki)"),
        ),
        default='single',
    )
    page_count: IntProperty(name="Page Count", default=0, min=0)
    active_page_index: IntProperty(
        name="Active Page",
        default=0,
        min=0,
        description="Which multipage tab is visible in the viewport",
    )
    locale: StringProperty(
        name="Locale",
        description="Detected language tag (e.g. en-us) from filename / cfg",
        default="",
    )
    locale_base: StringProperty(
        name="Locale Base Name",
        description="Filename without _locale suffix",
        default="",
    )
    localization_cfg: StringProperty(
        name="Localization Cfg",
        subtype='FILE_PATH',
        default="",
    )
    available_locales: StringProperty(
        name="Available Locales",
        description="Comma-separated locale tags discovered next to the .ksp",
        default="",
    )
    pending_remove_textures: StringProperty(
        name="Pending Remove Textures",
        description=(
            "Comma-separated Texture2D path_ids to delete on export when "
            "unreferenced"
        ),
        default="",
    )
    pending_removed_locales: StringProperty(
        name="Pending Removed Locales",
        description=(
            "Locales removed in the UI; disk .lang files are deleted only on Export"
        ),
        default="",
        options={'HIDDEN'},
    )
    active_locale: StringProperty(
        name="Locale",
        description="Live KSPedia language (sibling .ksp / .lang)",
        default="",
        update=_update_active_locale,
    )
    locale_buffers_text: StringProperty(
        name="Locale Buffers Text",
        description="Text datablock holding the per-language buffers",
        default="",
    )
    locale_buffers_json: StringProperty(
        name="Locale Buffers JSON",
        description="Small mirror of the per-language buffers",
        default="",
    )
    show_missing_elements: BoolProperty(
        name="Show Missing",
        description=(
            "List elements that the active language file does not contain "
            "(shown dimmed instead of hidden)"
        ),
        default=False,
    )
    show_text_boxes: BoolProperty(
        name="Show Text Boxes",
        description="Draw RectTransform sizeDelta boxes for KSPedia texts",
        default=False,
        update=_update_show_text_boxes,
    )
    edit_text_boxes: BoolProperty(
        name="Edit Text Boxes",
        description=(
            "When Show Text Boxes is on, show edge handles to resize the "
            "content box (updates Unity sizeDelta / wrap width)"
        ),
        default=False,
        update=_update_show_text_boxes,
    )
    kspedia_xml_asset: StringProperty(
        name="KSPedia XML Asset",
        description="TextAsset name that holds the Categories XML",
        default="",
    )
    filter_to_page: BoolProperty(
        name="Filter Lists to Page",
        description="When a page is focused, Textures / UI Elements show only that page",
        default=True,
    )
    filter_page_object: PointerProperty(
        name="Filter Page",
        type=bpy.types.Object,
    )
    filter_scope_object: PointerProperty(
        name="Filter Scope",
        description="Page or category folder currently focused in the TOC",
        type=bpy.types.Object,
    )
    display_title: StringProperty(
        name="Title",
        description="KSPedia title",
        default="",
        update=_update_bundle_display_title,
    )
    stock_diff_report: StringProperty(
        name="Stock Diff",
        description="Differences vs stock kspedia.ksp fingerprint / GameData",
        default="",
    )
    is_kspedia_index: BoolProperty(
        name="Is KSPedia Index",
        description="This bundle is the Categories/Screen catalog (kspedia.ksp)",
        default=False,
    )
    coverage_report: StringProperty(
        name="UI Coverage Report",
        description="MonoScript classification summary from last import",
        default="",
    )
    coverage_unknown: IntProperty(
        name="Unknown UI Scripts",
        description="Count of unrecognized MonoBehaviour scripts on import",
        default=0,
        min=0,
    )

    canvas_scale_mode: IntProperty(name="Canvas Scale Mode", default=0)
    canvas_ref_resolution: FloatVectorProperty(
        name="Canvas Ref Resolution", size=2, default=(0.0, 0.0),
    )
    canvas_scale_factor: FloatProperty(name="Canvas Scale Factor", default=1.0)
    materials: CollectionProperty(type=KSPMU_PG_KspMaterialItem)
    materials_index: IntProperty(name="Material Index", default=0)
    materials_expanded: BoolProperty(
        name="Materials Expanded",
        description="Expand the informational Materials list",
        default=False,
    )
    toc_expanded: BoolProperty(
        name="TOC Expanded",
        description="Expand the KSPedia TOC list",
        default=True,
    )
    ui_elements_expanded: BoolProperty(
        name="UI Elements Expanded",
        description="Expand the UI Elements list",
        default=True,
    )
    shaders_expanded: BoolProperty(
        name="Shaders Expanded",
        description="Expand the informational Shaders list",
        default=False,
    )
    is_sample_template: BoolProperty(
        name="Sample Template",
        description="Read-only sample generated by New — export asks for a writable Source folder",
        default=False,
    )
    export_gamedata_path: StringProperty(
        name="GameData Path",
        description="Relative GameData path written into localization.cfg (path = …)",
        default="GameData/KSPedia/",
    )
    pixel_scale: FloatProperty(
        name="Pixel Scale",
        default=0.001,
        min=1e-6,
        description="Unity pixel to Blender unit scale for UI preview",
    )
    textures: CollectionProperty(type=KSPMU_PG_KspTextureItem)
    textures_index: IntProperty(
        name="Texture Index", default=0, update=_update_textures_index,
    )
    text_assets: CollectionProperty(type=KSPMU_PG_KspTextAssetItem)
    text_assets_index: IntProperty(name="Text Asset Index", default=0)
    shaders: CollectionProperty(type=KSPMU_PG_KspShaderItem)
    shaders_index: IntProperty(name="Shader Index", default=0)
    explore_assets: CollectionProperty(type=KSPMU_PG_KspExploreAssetItem)
    explore_assets_index: IntProperty(name="Explore Assets Index", default=0)
    ui_elements: CollectionProperty(type=KSPMU_PG_KspUiElementItem)
    ui_elements_index: IntProperty(
        name="UI Element Index", default=0, update=_update_ui_elements_index,
    )
    font_inventory: CollectionProperty(type=KSPMU_PG_KspFontItem)
    toc_nodes: CollectionProperty(type=KSPMU_PG_KspTocNode)
    toc_nodes_index: IntProperty(
        name="TOC Index", default=0, update=_update_toc_index,
    )


class KSPMU_PG_KspUiObject(PropertyGroup):
    is_ksp_ui: BoolProperty(name="Is KSP UI", default=False)
    element_name: StringProperty(name="Element Name")
    kind: EnumProperty(name="Kind", items=ui_kind_items, default='empty')
    mb_path_id: StringProperty(name="MonoBehaviour Path ID")
    go_path_id: StringProperty(name="GameObject Path ID")
    rect_path_id: StringProperty(name="Rect Path ID")
    parent_rect_path_id: StringProperty(name="Parent Rect Path ID")
    text: StringProperty(name="Text", default="", maxlen=_TEXT_MAXLEN)
    font_size: FloatProperty(name="Font Size", default=14.0)
    color: FloatVectorProperty(
        name="Color", size=4, subtype='COLOR_GAMMA',
        default=(1.0, 1.0, 1.0, 1.0), min=0.0, max=1.0,
    )
    anchored_position: FloatVectorProperty(name="Anchored Position", size=2)
    size_delta: FloatVectorProperty(name="Size Delta", size=2)
    pivot: FloatVectorProperty(name="Pivot", size=2, default=(0.5, 0.5))
    anchor_min: FloatVectorProperty(name="Anchor Min", size=2, default=(0.5, 0.5))
    anchor_max: FloatVectorProperty(name="Anchor Max", size=2, default=(0.5, 0.5))
    local_rotation: FloatVectorProperty(
        name="Local Rotation", size=4, default=(0.0, 0.0, 0.0, 1.0),
    )
    local_scale: FloatVectorProperty(
        name="Local Scale", size=3, default=(1.0, 1.0, 1.0),
    )
    local_position_z: FloatProperty(name="Local Position Z", default=0.0)
    text_alignment: IntProperty(name="Text Alignment", default=0)
    font_style: IntProperty(name="Font Style", default=0)
    enable_word_wrapping: BoolProperty(name="Word Wrapping", default=True)
    line_spacing: FloatProperty(name="Line Spacing", default=0.0)
    margin: FloatVectorProperty(name="Margin", size=4, default=(0.0, 0.0, 0.0, 0.0))
    font_family: StringProperty(name="Font Family", default="")


classes_to_register = (
    KSPMU_PG_KspTextureItem,
    KSPMU_PG_KspTextAssetItem,
    KSPMU_PG_KspShaderItem,
    KSPMU_PG_KspExploreAssetItem,
    KSPMU_PG_KspMaterialItem,
    KSPMU_PG_KspUiElementItem,
    KSPMU_PG_KspFontItem,
    KSPMU_PG_KspTocNode,
    KSPMU_PG_KspBundle,
    KSPMU_PG_KspUiObject,
)

custom_properties_to_register = (
    (bpy.types.Object, "ksp_bundle", KSPMU_PG_KspBundle),
    (bpy.types.Object, "ksp_ui", KSPMU_PG_KspUiObject),
    (bpy.types.Scene, "ksp_active_bundle", bpy.types.Object),
)
