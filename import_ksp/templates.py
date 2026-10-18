# vim:ts=4:et
# <pep8 compliant>
"""Generate read-only KSPedia sample templates for the Mu New menu."""

from __future__ import annotations

import os
import uuid

import bpy

from . import viewport


def _bg_dir():
    """Bundled KSPedia backgrounds live in import_ksp/backgrounds."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "backgrounds")


def _load_bg(name, key):
    path = os.path.join(_bg_dir(), name)
    if not os.path.isfile(path):
        # Explicit second chance across both asset roots
        try:
            from ..export_ksp.prefab_clone import bundled_background_png
            path = bundled_background_png(name) or path
        except Exception:
            pass
    if not os.path.isfile(path):
        return None
    img_name = "ksp_sample_%s_%s" % (key, os.path.splitext(name)[0])
    existing = bpy.data.images.get(img_name)
    if existing is not None:
        return existing
    try:
        img = bpy.data.images.load(path, check_existing=False)
        img.name = img_name
        try:
            img.pack()
        except Exception:
            pass
        return img
    except Exception:
        return None


def _make_empty(collection, name, parent=None, size=0.05):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = size
    collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def _add_page(collection, root, kb, *, name, title, screen, depth, parent_folder,
              bg_img, texts, pixel_scale, page_index):
    page = _make_empty(collection, name, parent_folder or root, size=0.08)
    page["ksp_page_index"] = int(page_index)
    page["ksp_page"] = screen
    page["ksp_display_title"] = title
    try:
        page["ksp_toc_kind"] = "page"
    except Exception:
        pass

    # TitleScreen of a folder is not a TOC list row (one row = one page folder).
    parent_folder_node = None
    if parent_folder is not None:
        for n in kb.toc_nodes:
            try:
                if n.kind in ("category", "subcategory") and n.folder_object == parent_folder:
                    parent_folder_node = n
            except Exception:
                continue
    ts = ""
    if parent_folder_node is not None:
        ts = (parent_folder_node.screen or "").strip()
    if parent_folder_node is not None and ts and ts == (screen or "").strip():
        try:
            parent_folder_node.page_object = page
            parent_folder_node.page_index = page_index
        except Exception:
            pass
        return _finish_page_content(
            collection, kb, page, name, title, screen, bg_img, texts,
            pixel_scale, page_index,
        )

    node = kb.toc_nodes.add()
    node.kind = "page"
    node.depth = depth
    node.name = screen
    node.title = title
    node.screen = screen
    node.page_object = page
    node.page_index = page_index
    node.expanded = True
    _apply_catalog_meta(kb, node, screen)

    return _finish_page_content(
        collection, kb, page, name, title, screen, bg_img, texts,
        pixel_scale, page_index,
    )


def _finish_page_content(collection, kb, page, name, title, screen, bg_img, texts,
                         pixel_scale, page_index):
    sx = float(pixel_scale)
    w, h = 1024.0 * sx, 768.0 * sx
    if bg_img is not None:
        try:
            w = float(bg_img.size[0]) * sx
            h = float(bg_img.size[1]) * sx
        except Exception:
            pass
        mat = viewport.make_unlit_image_material("%s_Mat" % name, bg_img)
        plane = viewport.create_image_plane(collection, "%s_BG" % name, w, h, mat)
        plane.parent = page
        plane.location = (0.0, 0.0, -0.001)
        tex = kb.textures.add()
        tex.name = bg_img.name
        tex.width = int(bg_img.size[0]) if bg_img.size else 0
        tex.height = int(bg_img.size[1]) if bg_img.size else 0
        tex.image = bg_img
        ui = kb.ui_elements.add()
        ui.name = "%s_BG" % name
        ui.kind = "image"
        ui.viewport_object = plane
        ui.page_screen = screen
        try:
            plane.ksp_ui.is_ksp_ui = True
            plane.ksp_ui.kind = "image"
            plane.ksp_ui.element_name = ui.name
        except Exception:
            pass

    y = h * 0.35
    for i, (label, body, fam, size) in enumerate(texts):
        el_name = "%s_T%d" % (name, i)
        empty = _make_empty(collection, el_name, page, size=0.001)
        empty.location = (-w * 0.4, y, 0.002)
        try:
            empty.empty_display_size = 0.001
            empty.hide_viewport = False
        except Exception:
            pass
        try:
            empty.ksp_ui.is_ksp_ui = True
            empty.ksp_ui.kind = "text"
            empty.ksp_ui.element_name = el_name
            empty.ksp_ui.text = body
            empty.ksp_ui.font_size = float(size)
            empty.ksp_ui.font_family = fam
            empty.ksp_ui.size_delta = (600.0, 80.0)
            empty.ksp_ui.pivot = (0.0, 1.0)
        except Exception:
            pass
        try:
            # Distinct FONT name so Blender does not rename the empty root.
            root_txt, _plain = viewport.create_rich_ui_text(
                collection,
                el_name + "_run",
                body,
                float(size),
                base_color=(1.0, 1.0, 1.0, 1.0),
                pixel_scale=sx,
                box_width=600.0,
                box_height=80.0,
                font_family=fam,
            )
            if root_txt is not None:
                root_txt.parent = empty
                root_txt.location = (0.0, 0.0, 0.0)
                try:
                    # Runs must not be independent list rows (heal skips them).
                    if root_txt.ksp_ui.is_ksp_ui:
                        root_txt.ksp_ui.element_name = el_name + "_run"
                except Exception:
                    pass
        except Exception:
            try:
                curve = bpy.data.curves.new(el_name + "_run", "FONT")
                curve.body = body
                curve.size = float(size) * sx
                fo = bpy.data.objects.new(el_name + "_run", curve)
                collection.objects.link(fo)
                fo.parent = empty
            except Exception:
                pass
        # Drop rows heal may have added for this empty before we register one.
        try:
            from .mu_ops import _remove_ui_element_viewport
            _remove_ui_element_viewport(kb, empty)
        except Exception:
            for _i in range(len(kb.ui_elements) - 1, -1, -1):
                try:
                    if kb.ui_elements[_i].viewport_object == empty:
                        kb.ui_elements.remove(_i)
                except Exception:
                    pass
        item = kb.ui_elements.add()
        item.name = el_name
        item.kind = "text"
        item.text = body
        item.font_size = float(size)
        item.font_family = fam
        item.viewport_object = empty
        item.page_screen = screen
        y -= 0.12
    # Final dedupe: one list row per viewport object (heal race).
    try:
        seen = set()
        for _i in range(len(kb.ui_elements) - 1, -1, -1):
            vo = kb.ui_elements[_i].viewport_object
            if vo is None:
                continue
            ptr = vo.as_pointer()
            if ptr in seen:
                kb.ui_elements.remove(_i)
            else:
                seen.add(ptr)
    except Exception:
        pass
    return page


def _add_folder(kb, *, name, title, screen, depth, folder_obj):
    node = kb.toc_nodes.add()
    node.kind = "category" if depth == 0 else "subcategory"
    node.depth = depth
    node.name = name
    node.title = title
    node.screen = screen
    node.folder_object = folder_obj
    node.expanded = True
    _apply_catalog_meta(kb, node, screen)
    try:
        folder_obj["ksp_toc_kind"] = node.kind
        folder_obj["ksp_title_screen"] = screen
        folder_obj["ksp_display_title"] = title
    except Exception:
        pass
    return node


def _init_root(collection, name, kind_label):
    uid = uuid.uuid4().hex[:6]
    root = _make_empty(collection, "%s_%s" % (name, uid), None, size=0.12)
    kb = root.ksp_bundle
    kb.is_ksp_bundle = True
    kb.is_sample_template = True
    kb.bundle_name = name
    kb.bundle_kind = "kspedia_ui"
    kb.pixel_scale = 0.001
    kb.source_path = ""
    # Point Export at the bundled UnityFS shell so sample pages can clone
    # missing prefabs (CareerUI donor in template_kspedia_ui.ksp).
    try:
        from .fonts_util import template_ksp_path
        kb.template_path = template_ksp_path() or ""
    except Exception:
        kb.template_path = ""
    kb.layout_mode = "multipage"
    kb.available_locales = "en-us"
    kb.locale = "en-us"
    try:
        kb["active_locale"] = "en-us"
    except Exception:
        pass
    kb.export_gamedata_path = "GameData/KSPedia/"
    root["ksp_kind"] = "kspedia_ui"
    root["ksp_sample"] = kind_label
    return root, kb



def _apply_catalog_meta(kb, node, screen):
    """Set BundleName + AssetPath so Export / game TOC can resolve the Screen."""
    try:
        from . import kspedia_index as ki
        b = (getattr(node, "bundle_name", None) or "").strip()
        if not b:
            node.bundle_name = ki.default_bundle_name_for_kb(kb)
        a = (getattr(node, "asset_path", None) or "").strip()
        if not a:
            node.asset_path = ki.default_asset_path_for_screen(screen)
    except Exception:
        try:
            if not (getattr(node, "bundle_name", None) or "").strip():
                node.bundle_name = (kb.bundle_name or "kspedia").strip()
            if not (getattr(node, "asset_path", None) or "").strip():
                node.asset_path = "Assets/KSPedia/%s.prefab" % (screen or "Screen")
        except Exception:
            pass


def _ensure_sample_xml(kb):
    """Minimal KSPedia XML TextAsset so sync can write Screen catalog entries."""
    bname = (kb.bundle_name or "sample").strip() or "sample"
    xml_name = "%s_en-us" % bname
    try:
        kb.kspedia_xml_asset = xml_name
    except Exception:
        pass
    target = None
    for ta in kb.text_assets:
        if (ta.name or "") == xml_name:
            target = ta
            break
    if target is None:
        target = kb.text_assets.add()
        target.name = xml_name
    skeleton = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<KSPedia Name="%s">\n  <Categories/>\n  <Screens/>\n</KSPedia>\n'
        % bname
    )
    if not (target.text or "").strip():
        target.text = skeleton
    try:
        from . import kspedia_index as ki
        for node in kb.toc_nodes:
            _apply_catalog_meta(kb, node, getattr(node, "screen", "") or "")
        ki.sync_bundle_toc_xml(kb)
    except Exception:
        pass

def create_kspedia_page_sample(context):
    """Stock-like single KSPedia page: background + a few texts."""
    collection = context.view_layer.active_layer_collection.collection
    root, kb = _init_root(collection, "sample_kspedia", "kspedia")
    kb.layout_mode = "single"
    bg = _load_bg("BackgroundBlue.png", "kspedia") or _load_bg(
        "BackgroundStars.png", "kspedia"
    )
    page = _add_page(
        collection, root, kb,
        name="SampleKSPedia",
        title="Sample KSPedia",
        screen="SampleKSPedia",
        depth=0,
        parent_folder=root,
        bg_img=bg,
        texts=[
            ("Title", "Sample KSPedia Page", "Amaranth SDF", 36),
            ("Body", "Welcome to the KSPedia sample.\nEdit texts live, then Export to a writable folder.", "OpenSans SDF", 18),
            ("Hint", "Use New → PBS / GEP for multi-page trees.", "OpenSans SDF", 14),
        ],
        pixel_scale=kb.pixel_scale,
        page_index=0,
    )
    kb.page_count = 1
    kb.active_page_index = 0
    kb.display_title = "Sample KSPedia"
    context.view_layer.objects.active = root
    root.select_set(True)
    try:
        viewport.setup_ui_view()
    except Exception:
        pass
    _ensure_sample_xml(kb)
    return root


def create_pbs_sample(context):
    """PBS-like: folders, submenus, two locales, backgrounds + texts."""
    collection = context.view_layer.active_layer_collection.collection
    root, kb = _init_root(collection, "sample_pbs", "pbs")
    kb.available_locales = "en-us,de-de"
    kb.locale = "en-us"
    try:
        kb["active_locale"] = "en-us"
    except Exception:
        pass

    bg_ts = _load_bg("BackgroundBlackTS.png", "pbs") or _load_bg(
        "BackgroundBlack.png", "pbs"
    )
    bg_page = _load_bg("BackgroundBlueGrid.png", "pbs") or _load_bg(
        "BackgroundBlue.png", "pbs"
    )
    bg_stars = _load_bg("BackgroundStars.png", "pbs")

    cat = _make_empty(collection, "PlanetaryBase", root, size=0.06)
    _add_folder(
        kb, name="PlanetaryBase", title="Planetary Base Inc",
        screen="PBS_Home", depth=0, folder_obj=cat,
    )
    _add_page(
        collection, root, kb,
        name="PBS_Home", title="Planetary Base Inc", screen="PBS_Home",
        depth=1, parent_folder=cat, bg_img=bg_ts,
        texts=[
            ("Title", "Planetary Base Inc", "Amaranth SDF", 32),
            ("Body", "Modular habitats for Kerbin and beyond.", "OpenSans SDF", 16),
        ],
        pixel_scale=kb.pixel_scale, page_index=0,
    )

    sub = _make_empty(collection, "Habitats", cat, size=0.05)
    _add_folder(
        kb, name="Habitats", title="Habitats",
        screen="PBS_Habitats", depth=1, folder_obj=sub,
    )
    _add_page(
        collection, root, kb,
        name="PBS_Habitats", title="Habitats", screen="PBS_Habitats",
        depth=2, parent_folder=sub, bg_img=bg_page,
        texts=[
            ("Title", "Habitats", "Amaranth SDF", 28),
            ("Body", "Living quarters, corridors and life support.", "OpenSans SDF", 15),
        ],
        pixel_scale=kb.pixel_scale, page_index=1,
    )
    _add_page(
        collection, root, kb,
        name="PBS_Configuration", title="Configuration", screen="PBS_Configuration",
        depth=2, parent_folder=sub, bg_img=bg_page,
        texts=[
            ("Title", "Configuration", "Amaranth SDF", 28),
            ("Body", "Filter for life support and base modules.", "OpenSans SDF", 15),
            ("Note", "Locale: switch en-us / de-de after Export + .lang.", "OpenSans SDF", 13),
        ],
        pixel_scale=kb.pixel_scale, page_index=2,
    )

    sub2 = _make_empty(collection, "Logistics", cat, size=0.05)
    _add_folder(
        kb, name="Logistics", title="Logistics",
        screen="PBS_Logistics", depth=1, folder_obj=sub2,
    )
    _add_page(
        collection, root, kb,
        name="PBS_Logistics", title="Logistics", screen="PBS_Logistics",
        depth=2, parent_folder=sub2, bg_img=bg_stars or bg_page,
        texts=[
            ("Title", "Logistics", "Amaranth SDF", 28),
            ("Body", "Storage, fuel and crew transfer.", "OpenSans SDF", 15),
        ],
        pixel_scale=kb.pixel_scale, page_index=3,
    )

    kb.page_count = 4
    kb.active_page_index = 0
    kb.display_title = "Planetary Base Inc"
    from .import_ksp import show_first_toc_page, _set_hide_tree, iter_page_roots
    show_first_toc_page(root)
    context.view_layer.objects.active = root
    root.select_set(True)
    try:
        viewport.setup_ui_view()
    except Exception:
        pass
    _ensure_sample_xml(kb)
    return root


def create_gep_sample(context):
    """GEP-like: background pages + tree, single locale (no language picker needed)."""
    collection = context.view_layer.active_layer_collection.collection
    root, kb = _init_root(collection, "sample_gep", "gep")
    kb.available_locales = "en-us"

    bg_ksc = _load_bg("BackgroundKSC.png", "gep")
    bg_stars = _load_bg("BackgroundStars.png", "gep")
    bg_blue = _load_bg("BackgroundBlue.png", "gep")

    cat = _make_empty(collection, "GEP", root, size=0.06)
    _add_folder(
        kb, name="GEP", title="Galactic Neighborhood",
        screen="GEP_Home", depth=0, folder_obj=cat,
    )
    _add_page(
        collection, root, kb,
        name="GEP_Home", title="Galactic Neighborhood", screen="GEP_Home",
        depth=1, parent_folder=cat, bg_img=bg_ksc or bg_stars,
        texts=[
            ("Title", "Galactic Neighborhood", "Amaranth SDF", 30),
        ],
        pixel_scale=kb.pixel_scale, page_index=0,
    )
    sub = _make_empty(collection, "Worlds", cat, size=0.05)
    _add_folder(
        kb, name="Worlds", title="Worlds",
        screen="GEP_Worlds", depth=1, folder_obj=sub,
    )
    _add_page(
        collection, root, kb,
        name="GEP_Worlds", title="Worlds", screen="GEP_Worlds",
        depth=2, parent_folder=sub, bg_img=bg_stars or bg_blue,
        texts=[],
        pixel_scale=kb.pixel_scale, page_index=1,
    )
    _add_page(
        collection, root, kb,
        name="GEP_Kerbin", title="Kerbin", screen="GEP_Kerbin",
        depth=2, parent_folder=sub, bg_img=bg_blue or bg_stars,
        texts=[],
        pixel_scale=kb.pixel_scale, page_index=2,
    )

    kb.page_count = 3
    kb.display_title = "Galactic Neighborhood"
    from .import_ksp import show_first_toc_page
    show_first_toc_page(root)
    context.view_layer.objects.active = root
    root.select_set(True)
    try:
        viewport.setup_ui_view()
    except Exception:
        pass
    _ensure_sample_xml(kb)
    return root


def create_kerbin_texture_sample(context):
    """Demo: stock-like Kerbin page whose background was swapped for another texture.

    Use this as the fourth New-menu example: Import Image on a background to
    replace Kerbin/blue with Stars (or any PNG) — same workflow as editing PBS.
    """
    collection = context.view_layer.active_layer_collection.collection
    root, kb = _init_root(collection, "sample_kerbin_tex", "kerbin_tex")
    kb.available_locales = "en-us"

    bg_old = _load_bg("BackgroundBlue.png", "kerbin_old")
    bg_new = _load_bg("BackgroundStars.png", "kerbin_new") or bg_old
    bg_ksc = _load_bg("BackgroundKSC.png", "kerbin_ksc")

    cat = _make_empty(collection, "KSPedia", root, size=0.06)
    _add_folder(
        kb, name="KSPedia", title="KSPedia",
        screen="TitleScreen", depth=0, folder_obj=cat,
    )
    _add_page(
        collection, root, kb,
        name="TitleScreen", title="Kerbin (texture swap demo)", screen="TitleScreen",
        depth=1, parent_folder=cat, bg_img=bg_ksc or bg_new,
        texts=[
            ("Title", "Kerbin", "Amaranth SDF", 32),
            ("Body", "Background replaced via UI Elements → Import Image.", "OpenSans SDF", 15),
            ("Hint", "Select the image row → Import → pick Stars/Blue/your PNG → Export.", "OpenSans SDF", 13),
        ],
        pixel_scale=kb.pixel_scale, page_index=0,
    )
    _add_page(
        collection, root, kb,
        name="Kerbin", title="Kerbin Surface", screen="Kerbin",
        depth=1, parent_folder=cat, bg_img=bg_new,
        texts=[
            ("Title", "Kerbin — swapped texture", "Amaranth SDF", 28),
            ("Body", "Was Blue / stock planet art; now sample Stars (or your file).", "OpenSans SDF", 15),
        ],
        pixel_scale=kb.pixel_scale, page_index=1,
    )

    kb.page_count = 2
    kb.display_title = "Kerbin texture swap"
    from .import_ksp import show_first_toc_page
    show_first_toc_page(root)
    context.view_layer.objects.active = root
    root.select_set(True)
    try:
        viewport.setup_ui_view()
    except Exception:
        pass
    _ensure_sample_xml(kb)
    return root
