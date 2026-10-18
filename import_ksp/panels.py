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

import bpy


_OVERRIDE_PCOLL = None
_OVERRIDE_BLUE = (0x06, 0x89, 0xD2)


def _png_rgba_icon(pixels, w=32, h=32):
    """Build a small RGBA PNG from flat [r,g,b,a] * w * h list."""
    import struct
    import zlib

    raw = b""
    for y in range(h):
        raw += b"\x00"
        row = y * w * 4
        raw += bytes(pixels[row : row + w * 4])

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _draw_folder_pixels(rgb, w=32, h=32):
    r, g, b = rgb
    px = [0, 0, 0, 0] * (w * h)

    def put(x, y, a=255):
        if 0 <= x < w and 0 <= y < h:
            i = (y * w + x) * 4
            px[i : i + 4] = [r, g, b, a]

    # Tab
    for y in range(6, 11):
        for x in range(4, 14):
            put(x, y)
    # Body
    for y in range(10, 26):
        for x in range(4, 28):
            put(x, y)
    return px


def _draw_image_pixels(rgb, w=32, h=32):
    """IMAGE_DATA-like: thick frame + filled mountain + sun (readable at 16px)."""
    r, g, b = rgb
    px = [0, 0, 0, 0] * (w * h)

    def put(x, y, a=255):
        if 0 <= x < w and 0 <= y < h:
            i = (y * w + x) * 4
            px[i : i + 4] = [r, g, b, a]

    # Thick frame (2px)
    for x in range(4, 28):
        for t in (4, 5, 26, 27):
            put(x, t)
    for y in range(4, 28):
        for t in (4, 5, 26, 27):
            put(t, y)
    # Sun
    for y in range(7, 14):
        for x in range(17, 24):
            if (x - 20) ** 2 + (y - 10) ** 2 <= 10:
                put(x, y)
    # Filled mountains
    for y in range(14, 27):
        for x in range(6, 26):
            if (abs(x - 12) + (27 - y) < 12 and y > 15) or (
                abs(x - 19) + (27 - y) < 10 and y > 17
            ):
                put(x, y)
    return px


def _override_blue_icon_id(kind="folder"):
    """Blue (#0689D2) folder or screen icon for override rows (not a solid square)."""
    global _OVERRIDE_PCOLL
    key = "override_blue_folder_v2" if kind == "folder" else "override_blue_screen_v2"
    try:
        import bpy.utils.previews
    except Exception:
        return 0
    if _OVERRIDE_PCOLL is None:
        _OVERRIDE_PCOLL = bpy.utils.previews.new()
    if key not in _OVERRIDE_PCOLL:
        import os
        import tempfile

        rgb = _OVERRIDE_BLUE
        pixels = (
            _draw_folder_pixels(rgb)
            if kind == "folder"
            else _draw_image_pixels(rgb)
        )
        path = os.path.join(tempfile.gettempdir(), "ksp_%s.png" % key)
        try:
            with open(path, "wb") as f:
                f.write(_png_rgba_icon(pixels))
            _OVERRIDE_PCOLL.load(key, path, "IMAGE")
        except Exception:
            return 0
    try:
        return int(_OVERRIDE_PCOLL[key].icon_id)
    except Exception:
        return 0


def _bundle_root(context):
    """Active/selected KSP bundle, including Outliner-selected hidden roots."""
    from .operators import _find_bundle_root_from_context
    return _find_bundle_root_from_context(context)


def _is_under(obj, ancestor):
    cur = obj
    while cur is not None:
        if cur == ancestor:
            return True
        cur = cur.parent
    return False


def _page_scope(context, kb):
    """Object that asset lists filter under (the visible page)."""
    if not kb.filter_to_page:
        return None
    # Prefer the visible page over a category folder — otherwise the first
    # TOC row (main category / TitleScreen) lists every nested page.
    scope = kb.filter_page_object or kb.filter_scope_object
    if scope is None:
        try:
            if 0 <= kb.toc_nodes_index < len(kb.toc_nodes):
                node = kb.toc_nodes[kb.toc_nodes_index]
                scope = node.page_object or node.folder_object
        except Exception:
            scope = None
    if scope is not None:
        try:
            if "ksp_page_index" not in scope.keys():
                page = kb.filter_page_object
                if page is None:
                    try:
                        if 0 <= kb.toc_nodes_index < len(kb.toc_nodes):
                            page = kb.toc_nodes[kb.toc_nodes_index].page_object
                    except Exception:
                        page = None
                if page is not None:
                    return page
        except Exception:
            pass
        return scope
    obj = context.active_object
    while obj is not None:
        try:
            if "ksp_page_index" in obj.keys():
                return obj
        except Exception:
            pass
        try:
            if "ksp_toc_kind" in obj.keys():
                # Category empty: prefer its TitleScreen page when known.
                try:
                    if 0 <= kb.toc_nodes_index < len(kb.toc_nodes):
                        page = kb.toc_nodes[kb.toc_nodes_index].page_object
                        if page is not None:
                            return page
                except Exception:
                    pass
                return obj
        except Exception:
            pass
        try:
            if obj.ksp_bundle.is_ksp_bundle:
                try:
                    if kb.toc_nodes:
                        n0 = kb.toc_nodes[0]
                        return n0.page_object or n0.folder_object
                except Exception:
                    pass
                return None
        except Exception:
            pass
        obj = obj.parent
    return None


def _screen_id(page):
    if page is None:
        return ""
    try:
        return str(page.get("ksp_page", "") or page.name or "")
    except Exception:
        return page.name or ""


def _screens_under(scope):
    """Screen ids for pages under a folder scope (or one page)."""
    if scope is None:
        return None
    try:
        if "ksp_page_index" in scope.keys():
            return {_screen_id(scope)}
    except Exception:
        pass
    out = set()
    for obj in [scope] + list(getattr(scope, "children_recursive", []) or []):
        try:
            if "ksp_page_index" in obj.keys():
                out.add(_screen_id(obj))
        except Exception:
            continue
    return out


_KIND_SORT = {
    "image": 0,
    "text": 1,
    "meta": 2,
    "empty": 3,
}


def _ui_element_live_preview(item, *, max_chars=240):
    """Plain text for list preview — prefer live FONT body over stale item.text."""
    raw = ""
    vo = getattr(item, "viewport_object", None)
    if vo is not None:
        try:
            from .mu_ops import collect_viewport_text_plain
            raw = collect_viewport_text_plain(vo) or ""
        except Exception:
            raw = ""
        if not raw:
            try:
                raw = str(vo.get("ksp_text_display", "") or "")
            except Exception:
                raw = ""
            if not raw:
                try:
                    raw = str(vo.ksp_ui.text or "")
                except Exception:
                    raw = ""
    if not raw:
        raw = item.text or ""
    # One line for the list; keep quotes/spaces, just flatten newlines
    flat = " ".join((raw or "").replace("\r", "\n").split("\n"))
    flat = " ".join(flat.split())
    if max_chars and len(flat) > max_chars:
        return flat[: max_chars - 1] + "…"
    return flat


class KSPMU_UL_KspTextureList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        icon_id = 0
        try:
            img = item.image
            if img is not None and getattr(img, "preview", None) is not None:
                icon_id = int(img.preview.icon_id or 0)
        except Exception:
            icon_id = 0
        label = item.name or "(tex)"
        try:
            if int(item.width or 0) > 0 and int(item.height or 0) > 0:
                label = "%s  %dx%d" % (label, int(item.width), int(item.height))
        except Exception:
            pass
        if icon_id:
            row.label(text=label, icon_value=icon_id)
        else:
            row.label(text=label, icon="IMAGE_DATA")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items)))
        scope = _page_scope(context, data)
        if scope is None:
            return flt_flags, flt_neworder
        screens = _screens_under(scope)
        for i, item in enumerate(items):
            ok = False
            if item.page_screen and screens is not None:
                ok = item.page_screen in screens
            if not ok:
                img = item.image
                if img is not None:
                    for obj in context.scene.objects:
                        if obj.type != 'MESH' or not _is_under(obj, scope):
                            continue
                        for slot in obj.material_slots:
                            mat = slot.material
                            if mat is None or not mat.use_nodes:
                                continue
                            for node in mat.node_tree.nodes:
                                if getattr(node, "image", None) is img:
                                    ok = True
                                    break
                            if ok:
                                break
                        if ok:
                            break
            flt_flags[i] = self.bitflag_filter_item if ok else 0
        return flt_flags, flt_neworder


class KSPMU_UL_KspTextAssetList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        layout.label(text=item.name or "(text)", icon='TEXT')


def _draw_ui_element_name(layout, kb, item, icon_id):
    """Name + optional `` #N`` as one label filling the name column.

    Does not mutate Unity ``item.name``. A ``prop(item, "name")`` widget used
    to expand past its column and starve the preview; a shrink-wrapped LEFT
    label let long preview text paint over the name.
    """
    try:
        from .locale_switch import ui_element_list_label
        text = ui_element_list_label(kb, item)
    except Exception:
        text = getattr(item, "name", None) or "(unnamed)"
    layout.label(text=text or "(unnamed)", icon=icon_id)


class KSPMU_UL_KspUiElementList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        icon_id = 'FONT_DATA' if item.kind == 'text' else (
            'IMAGE_DATA' if item.kind == 'image' else (
                'MODIFIER' if item.kind == 'meta' else 'EMPTY_DATA'
            )
        )
        try:
            if item.missing_in_locale:
                layout.active = False
                icon_id = 'HIDE_ON'
        except Exception:
            pass
        extra = ""
        if item.kind == 'text':
            extra = _ui_element_live_preview(item) or ""
        elif item.kind == 'image':
            w = h = 0
            try:
                w = int(getattr(item, "width", 0) or 0)
                h = int(getattr(item, "height", 0) or 0)
            except Exception:
                pass
            if (not w or not h) and item.viewport_object is not None:
                try:
                    for slot in item.viewport_object.material_slots:
                        mat = slot.material
                        if mat is None or not mat.use_nodes:
                            continue
                        for node in mat.node_tree.nodes:
                            img = getattr(node, "image", None)
                            if img is not None and img.size:
                                w, h = int(img.size[0]), int(img.size[1])
                                break
                        if w and h:
                            break
                except Exception:
                    pass
            if not w or not h:
                try:
                    for tex in data.textures:
                        if tex.name and item.name and tex.name in item.name:
                            w, h = int(tex.width), int(tex.height)
                            break
                        if item.texture_path_id and str(tex.path_id) == str(item.texture_path_id):
                            w, h = int(tex.width), int(tex.height)
                            break
                except Exception:
                    pass
            if w and h:
                extra = "%dx%d" % (w, h)
        # Checkbox (~fixed width) then name — only a few px gap, not a % column
        row = layout.row(align=True)
        chk = row.row(align=True)
        chk.ui_units_x = 0.8
        try:
            chk.prop(item, "list_selected", text="")
        except Exception:
            pass
        name_col = row.row(align=True)
        name_col.scale_x = 1.0
        _draw_ui_element_name(name_col, data, item, icon_id)
        prev_col = row.row(align=True)
        prev_col.scale_x = 1.0
        if extra:
            prev_col.label(text=extra)

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        n = len(items)
        flt_flags = [self.bitflag_filter_item] * n
        flt_neworder = list(range(n))
        if n == 0:
            return flt_flags, flt_neworder
        scope = _page_scope(context, data)
        screens = _screens_under(scope) or set() if scope is not None else set()
        hide_missing = _hides_missing_elements(data)
        visible = []
        hidden = []
        for i, item in enumerate(items):
            ok = _ui_element_row_visible(item, scope, screens, hide_missing)
            if ok:
                visible.append(i)
                flt_flags[i] = self.bitflag_filter_item
            else:
                hidden.append(i)
                flt_flags[i] = 0
        # Keep empty when page filter matches nothing (0/N). Showing all rows
        # here made Scope "0/52" look filtered while the list stayed full.
        visible.sort(
            key=lambda i: (_KIND_SORT.get(items[i].kind, 9), items[i].name or ""),
        )
        # Pack visible rows first. Filter+reorder otherwise fills the widget
        # with hidden image rows and the list looks empty.
        packed = visible + hidden
        flt_neworder = [0] * n
        for new_i, old_i in enumerate(packed):
            flt_neworder[old_i] = new_i
        return flt_flags, flt_neworder


def _is_toc_title_screen_row(nodes, index):
    """True if this page row is the Screen child of a parent page folder.

    TitleScreen of a category/subcategory is not a TOC list row (one row =
    one page folder). Same rule for imported PBS and user-created pages.
    """
    try:
        node = nodes[index]
        if str(node.kind or "") != "page":
            return False
        screen = (node.screen or node.name or "").strip()
        depth = int(node.depth)
    except Exception:
        return False
    for j in range(index - 1, -1, -1):
        try:
            parent = nodes[j]
            pd = int(parent.depth)
        except Exception:
            break
        if pd >= depth:
            continue
        try:
            if str(parent.kind or "") not in {"category", "subcategory"}:
                break
        except Exception:
            break
        ts = (parent.screen or parent.name or "").strip()
        if ts and screen and ts == screen:
            return True
        try:
            ppo = parent.page_object
            npo = node.page_object
            if ppo is not None and npo is not None and ppo == npo:
                return True
        except Exception:
            pass
        if pd == depth - 1 and screen:
            pname = (parent.name or "").strip()
            ptitle = (parent.title or "").strip()
            ntitle = (node.title or "").strip()
            if pname == screen or (ptitle and ntitle and ptitle == ntitle):
                return True
        break
    return False


def _toc_list_visible_count(kb):
    """TOC rows actually drawn (collapse + hidden TitleScreen children)."""
    try:
        nodes = kb.toc_nodes
    except Exception:
        return 0
    n = 0
    collapse_depth = None
    for i, node in enumerate(nodes):
        try:
            depth = int(node.depth)
        except Exception:
            depth = 0
        if collapse_depth is not None:
            if depth > collapse_depth:
                continue
            collapse_depth = None
        if _is_toc_title_screen_row(nodes, i):
            continue
        n += 1
        try:
            if node.kind in {'category', 'subcategory'} and not node.expanded:
                collapse_depth = depth
        except Exception:
            pass
    return n


def _toc_node_has_children(nodes, index):
    """True if the next flat-TOC rows nest under this category/subcategory."""
    try:
        n = len(nodes)
    except Exception:
        return False
    if index < 0 or index >= n:
        return False
    try:
        node = nodes[index]
        if node.kind not in {'category', 'subcategory'}:
            return False
        depth = int(node.depth)
    except Exception:
        return False
    for j in range(index + 1, n):
        try:
            d = int(nodes[j].depth)
        except Exception:
            break
        if d <= depth:
            break
        if _is_toc_title_screen_row(nodes, j):
            continue
        return True
    return False


def _toc_folder_page_nodes(nodes, index):
    """Page nodes nested under a category/subcategory row (flat TOC)."""
    out = []
    try:
        n = len(nodes)
    except Exception:
        return out
    if index < 0 or index >= n:
        return out
    try:
        node = nodes[index]
        if node.kind not in {'category', 'subcategory'}:
            return out
        depth = int(node.depth)
    except Exception:
        return out
    for j in range(index + 1, n):
        try:
            child = nodes[j]
            d = int(child.depth)
        except Exception:
            break
        if d <= depth:
            break
        try:
            if child.kind == 'page':
                out.append(child)
        except Exception:
            pass
    return out


def _draw_toc_screen_meta(box, node, kb, *, screen_label="Screen"):
    """Screen + BundleName + AssetPath (+ stock override hint)."""
    box.prop(node, "screen", text=screen_label)
    # Always show for pages/folders — filled from stock + DLC Screen catalogs.
    box.prop(node, "bundle_name", text="BundleName")
    row = box.row(align=True)
    row.prop(node, "asset_path", text="AssetPath")
    op = row.operator(
        "object.ksp_toc_ensure_prefab",
        text="",
        icon="FILE_REFRESH",
    )
    op.index = -1
    if node.overrides_stock:
        box.label(
            text="Override: replaces stock/DLC Screen (game loads last bundle)",
            icon='INFO',
        )


# TOC / UI Elements: auto height min 3 … max 10. Hard ceiling = 10
# (Blender may jump to maxrows on filter refresh — never set maxrows > 10).
_LIST_AUTO_MAX_ROWS = 10
_LIST_HARD_MAX_ROWS = 10


def _list_auto_rows(count):
    """Default visible rows: min 3, hard-cap 10."""
    try:
        n = int(count or 0)
    except Exception:
        n = 0
    return max(3, min(_LIST_AUTO_MAX_ROWS, n if n > 0 else 3))


def _hides_missing_elements(kb):
    """True when rows absent from the active .lang are filtered out."""
    try:
        return not bool(kb.show_missing_elements)
    except Exception:
        return True


def _ui_element_row_visible(item, scope, screens, hide_missing):
    if hide_missing:
        try:
            if item.missing_in_locale:
                return False
        except Exception:
            pass
    if scope is None:
        return True
    try:
        if item.page_screen and item.page_screen in screens:
            return True
    except Exception:
        pass
    try:
        obj = item.viewport_object
        if obj is None:
            return False
        if _is_under(obj, scope):
            return True
        cur = obj
        while cur is not None:
            sid = ""
            try:
                sid = str(cur.get("ksp_page", "") or "")
            except Exception:
                sid = ""
            if sid and screens and sid in screens:
                return True
            try:
                cur = cur.parent
            except Exception:
                break
    except Exception:
        pass
    return False


def _ui_elements_visible_count(context, kb):
    """Count UI elements actually shown under current TOC filter/scope."""
    try:
        items = list(kb.ui_elements)
    except Exception:
        return 0
    scope = _page_scope(context, kb)
    screens = _screens_under(scope) or set() if scope is not None else set()
    hide_missing = _hides_missing_elements(kb)
    return sum(
        1 for item in items
        if _ui_element_row_visible(item, scope, screens, hide_missing)
    )


class KSPMU_UL_KspShaderList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        layout.label(text=item.name or "(shader)", icon='NODE_MATERIAL')


class KSPMU_UL_KspTocList(bpy.types.UIList):
    """Collapsible KSPedia category / page tree (scrollable via UIList)."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        for _ in range(max(0, int(item.depth))):
            row.label(text="", icon='BLANK1')
        # Flags from import/heal only — no UnityFS, no prop writes, no theme
        # mutation (those hung Blender on GEP-sized TOCs).
        ov = bool(getattr(item, "overrides_stock", False))
        if item.kind in {'category', 'subcategory'}:
            nodes = getattr(data, "toc_nodes", None)
            has_kids = _toc_node_has_children(nodes, index)
            if has_kids:
                icon_tri = 'TRIA_DOWN' if item.expanded else 'TRIA_RIGHT'
                tri = row.row(align=True)
                tri.scale_x = 0.85
                tri.prop(item, "expanded", text="", icon=icon_tri, emboss=False)
            ic = _override_blue_icon_id("folder") if ov else 0
            if ic:
                row.label(text="", icon_value=ic)
                row.prop(item, "title", text="", emboss=False)
            else:
                row.prop(item, "title", text="", emboss=False, icon='FILE_FOLDER')
        else:
            ic = _override_blue_icon_id("screen") if ov else 0
            if ic:
                row.label(text="", icon_value=ic)
                row.prop(item, "title", text="", emboss=False)
            else:
                row.prop(item, "title", text="", emboss=False, icon='IMAGE_DATA')

    def filter_items(self, context, data, propname):
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
            if _is_toc_title_screen_row(nodes, i):
                flt_flags[i] = 0
                continue
            if node.kind in {'category', 'subcategory'} and not node.expanded:
                collapse_depth = depth
        return flt_flags, flt_neworder


class VIEW3D_PT_ksp_bundle(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "KSP"
    bl_label = "KSP Bundle (.ksp)"
    bl_order = 20

    def draw(self, context):
        layout = self.layout
        try:
            from .progress_util import draw_panel_progress
            draw_panel_progress(layout)
        except Exception:
            pass
        root = _bundle_root(context)

        row = layout.row(align=True)
        row.operator("import_object.ksp_bundle", text="Import", icon='IMPORT')
        row.operator("export_object.ksp_bundle", text="Export", icon='EXPORT')
        row.menu("KSPMU_MT_ksp_bundle_new", text="New", icon='ADD')

        # Four equal actions
        row = layout.row(align=True)
        row.operator("object.ksp_select_bundle", text="Select Bundle", icon='PACKAGE')
        row.operator("object.ksp_deselect_bundle", text="Deselect Bundle", icon='RADIOBUT_OFF')
        row.operator("object.ksp_select_next_bundle", text="Select Next", icon='FORWARD')
        row.operator("object.ksp_delete_bundle", text="Delete", icon='TRASH')

        if root is None:
            layout.label(text="Select a KSP bundle root", icon='INFO')
            return

        kb = root.ksp_bundle
        layout.separator()
        row = layout.row(align=True)
        row.label(text=kb.bundle_name or root.name, icon='PACKAGE')
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        sub.operator(
            "object.ksp_menu_check",
            text="Menu Check",
            icon='VIEWZOOM',
        )
        sub.operator(
            "object.ksp_refresh_viewport_preview",
            text="Refresh",
            icon='FILE_REFRESH',
        )
        if getattr(kb, "is_sample_template", False):
            layout.label(
                text="Sample (read-only) — Export to set Source",
                icon='INFO',
            )
        try:
            from . import source_embed
            row = layout.row(align=True)
            if source_embed.source_is_internal(kb):
                row.label(
                    text="Source: Internal (embedded)",
                    icon='PACKAGE',
                )
            else:
                row.prop(kb, "source_path", text="Source")
                # Icon next to the FILE_PATH folder browse control.
                emb = source_embed.has_embedded_source(kb)
                row.operator(
                    "object.ksp_embed_source",
                    text="",
                    icon='FILE_TICK' if emb else 'PACKAGE',
                )
        except Exception:
            layout.prop(kb, "source_path", text="Source")

        # Locale dropdown — picks by string tag, not by Enum index
        cur = (getattr(kb, "active_locale", "") or "").strip().lower()
        row = layout.row(align=True)
        row.label(text="Locale", icon='WORLD')
        row.menu("KSPMU_MT_ksp_locale_select", text=cur or "en-us")
        row.operator("object.ksp_add_locale", text="", icon='ADD')
        n_locs = 0
        try:
            n_locs = len(
                [x for x in (kb.available_locales or "").split(",") if x.strip()]
            )
        except Exception:
            n_locs = 0
        # Compact remove — only when a non-default sibling language exists
        if n_locs > 1:
            sub = row.row(align=True)
            sub.alignment = 'RIGHT'
            op = sub.operator(
                "object.ksp_remove_locale",
                text="",
                icon='X',
            )
            op.locale = cur or ""

        if getattr(kb, "is_kspedia_index", False):
            layout.label(text="KSPedia index (Categories + Screens)", icon='BOOKMARKS')
        diff = getattr(kb, "stock_diff_report", "") or ""
        if diff and not diff.startswith("OK"):
            box = layout.box()
            box.label(text="Stock kspedia.ksp check", icon='ERROR')
            for line in diff.splitlines()[:10]:
                box.label(text=line[:80])
        if kb.canvas_ref_resolution[0] > 0 or kb.canvas_scale_mode:
            box = layout.box()
            box.label(text="CanvasScaler", icon='FULLSCREEN_ENTER')
            box.prop(kb, "canvas_scale_mode", text="Mode")
            box.prop(kb, "canvas_ref_resolution", text="Ref Res")
            box.prop(kb, "canvas_scale_factor", text="Factor")

        cov = kb.coverage_report or ""
        show_cov = False
        if cov:
            import re as _re
            m = _re.search(
                r"skip=(\d+).*unknown=(\d+).*fallback=(\d+)", cov.replace("\n", " ")
            )
            if not m:
                m = _re.search(r"skip=(\d+)", cov)
            if kb.coverage_unknown:
                show_cov = True
            elif m:
                nums = [int(x) for x in m.groups()]
                show_cov = any(n > 0 for n in nums)
            if "UNKNOWN" in cov:
                show_cov = True
        if show_cov:
            box = layout.box()
            box.label(text="UI Coverage", icon='ERROR')
            for line in cov.splitlines()[:8]:
                box.label(text=line)

        if kb.toc_nodes:
            box = layout.box()
            head = box.row(align=True)
            if kb.layout_mode == 'multipage':
                toc_title = "KSPedia TOC: %d pages" % int(kb.page_count or 0)
            else:
                toc_title = "KSPedia Page — Add ▾ → multi-page bundle"
            head.prop(
                kb, "toc_expanded",
                text=toc_title,
                icon='TRIA_DOWN' if kb.toc_expanded else 'TRIA_RIGHT',
                emboss=False,
            )
            if kb.toc_expanded:
                if kb.layout_mode == 'multipage':
                    box.prop(
                        kb, "filter_to_page",
                        text="Filter assets to selected page/folder",
                    )
                # Same controls as PBS multipage (Add converts single → multipage)
                row = box.row(align=True)
                half = row.row(align=True)
                half.menu("KSPMU_MT_toc_add", text="Add", icon="ADD")
                half.operator(
                    "object.ksp_toc_duplicate_page", text="Duplicate", icon='DUPLICATE',
                )
                op = row.operator("object.ksp_toc_indent", text="", icon='TRIA_LEFT')
                op.direction = 'OUT'
                op = row.operator("object.ksp_toc_indent", text="", icon='TRIA_RIGHT')
                op.direction = 'IN'
                row.operator("object.ksp_toc_delete_page", text="Del Page", icon='TRASH')
                list_row = box.row()
                list_row.template_list(
                    "KSPMU_UL_KspTocList", "ksp_toc_cap10",
                    kb, "toc_nodes", kb, "toc_nodes_index",
                    rows=_list_auto_rows(_toc_list_visible_count(kb)),
                    maxrows=_LIST_HARD_MAX_ROWS,
                )
                col = list_row.column(align=True)
                op = col.operator("object.ksp_toc_move", text="", icon='TRIA_UP')
                op.direction = 'UP'
                op.index = -1
                op = col.operator("object.ksp_toc_move", text="", icon='TRIA_DOWN')
                op.direction = 'DOWN'
                op.index = -1
                if 0 <= kb.toc_nodes_index < len(kb.toc_nodes):
                    node = kb.toc_nodes[kb.toc_nodes_index]
                    box.prop(node, "title", text="Title")
                    if node.kind == 'page':
                        _draw_toc_screen_meta(box, node, kb, screen_label="Screen")
                    elif node.kind in {'category', 'subcategory'}:
                        _draw_toc_screen_meta(
                            box, node, kb, screen_label="TitleScreen",
                        )
                        pages = _toc_folder_page_nodes(
                            kb.toc_nodes, kb.toc_nodes_index
                        )
                        ts = (node.screen or "").strip()
                        extras = [
                            p for p in pages
                            if (p.screen or p.name or "").strip() != ts
                        ]
                        show = extras if ts else pages
                        if show:
                            # One line only — listing dozens of screens blew the panel
                            # past the viewport when a fat folder was selected.
                            box.label(
                                text="Contained screens: %d" % len(show),
                                icon='OUTLINER',
                            )
                        elif not ts:
                            box.label(
                                text="No TitleScreen / nested Screens in XML",
                                icon='INFO',
                            )

        scope = _page_scope(context, kb)
        scope_txt = (
            "Scope: %s" % scope.name if scope is not None
            else "Scope: whole bundle"
        )

        # UI Elements only (textures / text assets / KSP UI Element panel removed)
        box = layout.box()
        head = box.row(align=True)
        head.prop(
            kb, "ui_elements_expanded",
            text="UI Elements",
            icon='TRIA_DOWN' if kb.ui_elements_expanded else 'TRIA_RIGHT',
            emboss=False,
        )
        if kb.ui_elements_expanded:
            row = box.row(align=True)
            n_vis = _ui_elements_visible_count(context, kb)
            n_all = 0
            try:
                n_all = len(kb.ui_elements)
            except Exception:
                n_all = 0
            row.label(text="%s  (%d/%d)" % (scope_txt, n_vis, n_all))
            sub = row.row(align=True)
            sub.alignment = 'RIGHT'
            n_missing = 0
            try:
                n_missing = sum(1 for it in kb.ui_elements if it.missing_in_locale)
            except Exception:
                n_missing = 0
            sub.prop(
                kb, "show_missing_elements",
                text="Missing: %d" % n_missing if n_missing else "Missing",
                icon='HIDE_OFF' if kb.show_missing_elements else 'HIDE_ON',
                toggle=True,
            )
            box.template_list(
                "KSPMU_UL_KspUiElementList", "ksp_ui_el_cap10",
                kb, "ui_elements", kb, "ui_elements_index",
                rows=_list_auto_rows(_ui_elements_visible_count(context, kb)),
                maxrows=_LIST_HARD_MAX_ROWS,
            )
            # Equal dynamic columns: Add | Duplicate | Delete
            # On image: third column keeps the same width and splits 3-ways.
            is_image = False
            try:
                if 0 <= kb.ui_elements_index < len(kb.ui_elements):
                    is_image = kb.ui_elements[kb.ui_elements_index].kind == 'image'
            except Exception:
                is_image = False
            split = box.split(factor=0.0, align=True)
            c_add = split.column(align=True)
            c_add.menu("KSPMU_MT_ui_element_add", text="Add", icon='ADD')
            c_dup = split.column(align=True)
            c_dup.operator(
                "object.ksp_ui_element_duplicate", text="Duplicate", icon='DUPLICATE',
            )
            c_del = split.column(align=True)
            if is_image:
                # Same width as Delete — three equal dynamic thirds
                sub = c_del.split(factor=0.0, align=True)
                sub.column(align=True).operator(
                    "object.ksp_ui_element_import_image", text="", icon='IMPORT',
                )
                sub.column(align=True).operator(
                    "object.ksp_ui_element_export_image", text="", icon='EXPORT',
                )
                sub.column(align=True).operator(
                    "object.ksp_ui_element_delete", text="", icon='TRASH',
                )
            else:
                c_del.operator(
                    "object.ksp_ui_element_delete", text="Delete", icon='TRASH',
                )

            text_roots = []
            try:
                from .mu_ops import selected_ksp_text_roots
                text_roots = selected_ksp_text_roots(context)
            except Exception:
                text_roots = []
            cur_font = ""
            try:
                if text_roots:
                    cur_font = str(
                        text_roots[0].ksp_ui.font_family or ""
                    ).strip()
            except Exception:
                cur_font = ""
            row = box.split(factor=0.5, align=True)
            row.prop(
                kb, "show_text_boxes",
                text="Show Text Boxes",
                icon='MESH_GRID',
            )
            font_row = row.row(align=True)
            font_row.enabled = bool(text_roots)
            font_row.operator_menu_enum(
                "object.ksp_set_ui_font",
                "font",
                text=cur_font or "Font",
                icon='FILE_FONT',
            )

        # Materials / Shaders sit under UI Elements; both collapsed by default
        if getattr(kb, "materials", None):
            try:
                nmat = len(kb.materials)
            except Exception:
                nmat = 0
            if nmat:
                box = layout.box()
                row = box.row(align=True)
                row.prop(
                    kb, "materials_expanded",
                    text="Materials (%d)" % nmat,
                    icon='TRIA_DOWN' if kb.materials_expanded else 'TRIA_RIGHT',
                    emboss=False,
                )
                if kb.materials_expanded:
                    box.template_list(
                        "KSPMU_UL_KspShaderList", "mats",
                        kb, "materials", kb, "materials_index", rows=2,
                    )

        if kb.shaders:
            try:
                nsh = len(kb.shaders)
            except Exception:
                nsh = 0
            box = layout.box()
            row = box.row(align=True)
            row.prop(
                kb, "shaders_expanded",
                text="Shaders (%d)" % nsh,
                icon='TRIA_DOWN' if kb.shaders_expanded else 'TRIA_RIGHT',
                emboss=False,
            )
            if kb.shaders_expanded:
                box.template_list(
                    "KSPMU_UL_KspShaderList", "",
                    kb, "shaders", kb, "shaders_index", rows=2,
                )


classes_to_register = (
    KSPMU_UL_KspTextureList,
    KSPMU_UL_KspTextAssetList,
    KSPMU_UL_KspUiElementList,
    KSPMU_UL_KspShaderList,
    KSPMU_UL_KspTocList,
    VIEW3D_PT_ksp_bundle,
)
