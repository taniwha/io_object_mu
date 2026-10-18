# vim:ts=4:et
# <pep8 compliant>
"""KSPedia Menu Check: sanity + small in-game menu/page preview."""

from __future__ import annotations

import os

from mathutils import Matrix, Vector

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty


_IMAGE_NAME = "KSP_MenuCheck_Page"
# ~360p capture; PreviewCollection icon (no Image Save UI).
_PREVIEW_ICON_SCALE = 40.0
_PREVIEW_H = 640
_PREVIEW_W = 400
_MENU_SPLIT = 0.34
_DIALOG_WIDTH = 420
_LOCALE_ITEMS = [("en-us", "en-us", "", 1)]
_LOCALE_KEY = ()
_LOCK = False

# Last sanity lines (level, message) for the open dialog.
_ISSUES = []
_CAPTURE_ERROR = ""
_CAPTURE_ICON_ID = 0
_CAPTURE_GEN = 0
_PCOLL = None
_MENU_CHECK_LIVE = False
_MENU_CHECK_IDX = -1
_MENU_CHECK_SYNC = False


def register_menu_check_wm_props():
    """Drop stale WM width prop from older builds (save/crash safety)."""
    if hasattr(bpy.types.WindowManager, "ksp_menu_check_width"):
        try:
            del bpy.types.WindowManager.ksp_menu_check_width
        except Exception:
            pass


def unregister_menu_check_wm_props():
    register_menu_check_wm_props()


def _find_root(context):
    from .operators import _find_bundle_root_from_context
    return _find_bundle_root_from_context(context)


def _locale_items(self, context):
    global _LOCALE_ITEMS, _LOCALE_KEY
    root = _find_root(context) if context else None
    kb = root.ksp_bundle if root is not None else None
    raw = []
    try:
        raw = [
            x.strip().lower()
            for x in (getattr(kb, "available_locales", "") or "").split(",")
            if x.strip()
        ]
    except Exception:
        raw = []
    if not raw:
        raw = ["en-us"]
    key = tuple(raw)
    if key != _LOCALE_KEY:
        _LOCALE_ITEMS = [
            (tag, tag, "Preview this language", i + 1)
            for i, tag in enumerate(raw)
        ]
        _LOCALE_KEY = key
    return _LOCALE_ITEMS


def _toc_has_children(nodes, index):
    try:
        n = len(nodes)
        node = nodes[index]
        if node.kind not in {"category", "subcategory"}:
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
        try:
            if nodes[j].kind == "page":
                parent = nodes[index]
                if (nodes[j].screen or "") == (parent.screen or "") and parent.screen:
                    continue
        except Exception:
            pass
        return True
    return False


def _looks_like_official_kspedia_pack(kb, src=""):
    """True for Squad / DLC / ``kspedia_*`` hosts (stock-style, not third-party).

    Used to soften Check Sanity false alarms (no multipage XML, shared
    ``localization.cfg``). Does not affect override / blue-tint logic.
    """
    official = {
        "squad",
        "kspedia",
        "makinghistory",
        "serenity",
        "breakingground",
        "expansion",
    }
    names = []
    for attr in ("bundle_name", "locale_base"):
        try:
            v = str(getattr(kb, attr, None) or "").strip().lower()
            if v:
                names.append(v)
        except Exception:
            pass
    try:
        from .unityfs_catalog import host_bundle_stem

        h = (host_bundle_stem(kb) or "").strip().lower()
        if h:
            names.append(h)
    except Exception:
        pass
    try:
        for node in getattr(kb, "toc_nodes", None) or []:
            try:
                b = str(getattr(node, "bundle_name", None) or "").strip().lower()
                if b:
                    names.append(b)
            except Exception:
                pass
            try:
                ap = (
                    str(getattr(node, "asset_path", None) or "")
                    .replace("\\", "/")
                    .lower()
                )
            except Exception:
                ap = ""
            if ap.startswith("assets/squad/kspedia/") or "/squad/kspedia/" in ap:
                return True
    except Exception:
        pass
    for n in names:
        if n in official or n.startswith("kspedia"):
            return True

    path = (src or "").strip()
    if not path:
        try:
            path = str(getattr(kb, "source_path", None) or "").strip()
        except Exception:
            path = ""
    norm = path.replace("\\", "/").lower()
    markers = (
        "/squad/kspedia/",
        "/makinghistory/kspedia/",
        "/serenity/kspedia/",
        "/squadexpansion/makinghistory/kspedia/",
        "/squadexpansion/serenity/kspedia/",
    )
    for m in markers:
        if m in norm:
            return True
    return False


def sanity_check_menu(root, kb):
    """Return ``[(level, message), ...]`` - level is OK / WARN / ERROR / INFO."""
    issues = []
    if kb is None:
        return [("ERROR", "No KSP bundle selected")]

    from .unityfs_catalog import (
        asset_path_in_pack,
        heal_pack_identity,
        host_bundle_stem,
        inspect_ksp_unityfs,
        is_local_toc_node,
        node_asset_path,
        node_bundle_name,
        node_screen_id,
    )

    nodes = list(getattr(kb, "toc_nodes", None) or [])
    src = (getattr(kb, "source_path", "") or "").strip()
    # Heal stale blends where locale_base/filename was used as pack stem
    try:
        heal_pack_identity(kb, filepath=src)
    except Exception:
        pass
    host = host_bundle_stem(kb)
    file_stem = ""
    try:
        file_stem = str(getattr(kb, "locale_base", "") or "").strip()
    except Exception:
        file_stem = ""
    unity = inspect_ksp_unityfs(src) if src else None

    screens = {}
    missing_prefabs = []
    bundle_mismatch = []
    foreign_pages = []

    for i, node in enumerate(nodes):
        title = (getattr(node, "title", "") or "").strip() or "?"
        sid = node_screen_id(node)
        kind = getattr(node, "kind", "") or ""
        if sid:
            screens.setdefault(sid.lower(), []).append(node)
        if title.startswith("#"):
            issues.append(("WARN", "Unresolved LOC key: %s" % title[:48]))
        if kind == "page":
            if getattr(node, "page_object", None) is None:
                issues.append(("WARN", "Page '%s' has no viewport object" % title[:40]))
            bname = node_bundle_name(node)
            apath = node_asset_path(node)
            if not bname:
                issues.append(("WARN", "Page '%s' missing BundleName" % title[:40]))
            if not apath:
                issues.append(("WARN", "Page '%s' missing AssetPath" % title[:40]))
            under_kspedia = (apath or "").replace("\\", "/").lower().startswith(
                "assets/kspedia/"
            )
            local = is_local_toc_node(node, host) or under_kspedia
            if under_kspedia and host and bname and bname.lower() != host.lower():
                bundle_mismatch.append(sid or title)
            if local and apath and unity is not None:
                if not asset_path_in_pack(apath, unity):
                    missing_prefabs.append(sid or title)
            elif (not local) and apath and unity is not None:
                if not asset_path_in_pack(apath, unity):
                    foreign_pages.append(sid or title)
            elif (not local) and bname and host and bname.lower() != host.lower():
                foreign_pages.append(sid or title)
        elif kind in {"category", "subcategory"}:
            if not sid and not _toc_has_children(nodes, i):
                issues.append(
                    ("WARN", "Empty folder '%s' (no TitleScreen / pages)" % title[:40])
                )
            apath = node_asset_path(node)
            if sid and is_local_toc_node(node, host) and apath and unity is not None:
                if not asset_path_in_pack(apath, unity):
                    missing_prefabs.append(sid)

    if missing_prefabs:
        uniq = []
        for s in missing_prefabs:
            if s not in uniq:
                uniq.append(s)
        issues.append(
            (
                "ERROR",
                "Missing prefab in .ksp (%d): %s - Export to clone"
                % (len(uniq), ", ".join(uniq[:4]) + ("..." if len(uniq) > 4 else "")),
            )
        )
    if bundle_mismatch:
        uniq = []
        for s in bundle_mismatch:
            if s not in uniq:
                uniq.append(s)
        issues.append(
            (
                "ERROR",
                "BundleName != UrlName '%s' (%d screens) - Export auto-fixes"
                % (host or "?", len(uniq)),
            )
        )
    if foreign_pages:
        uniq = []
        for s in foreign_pages:
            if s not in uniq:
                uniq.append(s)
        # Without Adopt / clone these Screens point at missing bundles →
        # KSPediaController: Asset load failed. Treat as ERROR.
        issues.append(
            (
                "ERROR",
                "Foreign BundleName/AssetPath not resolvable (%d): %s — "
                "Adopt into pack or Export will fail in-game"
                % (
                    len(uniq),
                    ", ".join(uniq[:4]) + ("..." if len(uniq) > 4 else ""),
                ),
            )
        )
    if unity is not None:
        url = (unity.get("url_name") or unity.get("ab_name") or "").strip()
        if url and host and url.lower() != host.lower():
            issues.append(
                (
                    "ERROR",
                    "UrlName/AssetBundle '%s' != pack identity '%s'"
                    % (url[:24], host[:24]),
                )
            )
        elif file_stem and url and file_stem.lower() != url.lower():
            issues.append(
                (
                    "INFO",
                    "Filename stem '%s' != UrlName '%s' (OK — localization name)"
                    % (file_stem[:24], url[:24]),
                )
            )

    for sid, group in screens.items():
        pages = [n for n in group if getattr(n, "kind", "") == "page"]
        if len(pages) > 1:
            issues.append(
                (
                    "ERROR",
                    "Duplicate Screen '%s' (%d pages) - KSP keeps one" % (sid, len(pages)),
                )
            )

    locs = [
        x.strip().lower()
        for x in (getattr(kb, "available_locales", "") or "").split(",")
        if x.strip()
    ]
    default = (getattr(kb, "locale", "") or "").strip().lower()
    if default and locs and default not in locs:
        issues.append(("WARN", "Default %s is not in available locales" % default))

    if src:
        try:
            from .kspedia_index import find_localization_near_ksp
            cfg = find_localization_near_ksp(src)
        except Exception:
            cfg = None
        if cfg is None:
            # Shared folder cfg (e.g. filename=kspedia) is listed in Explore
            # but rejected by find_localization_near_ksp for other stems.
            shared_cfg = False
            try:
                folder = os.path.dirname(os.path.abspath(src))
                for name in ("localization.cfg", "KSPediaLocalization.cfg"):
                    if os.path.isfile(os.path.join(folder, name)):
                        shared_cfg = True
                        break
            except Exception:
                shared_cfg = False
            official = _looks_like_official_kspedia_pack(kb, src)
            if shared_cfg:
                issues.append(
                    (
                        "INFO",
                        "Shared localization.cfg beside source (filename locale)",
                    )
                )
            elif not official:
                issues.append(
                    (
                        "INFO",
                        "No localization.cfg beside source (filename locale used)",
                    )
                )
            # Official stock-style packs without a cfg: skip (not alarming).
        else:
            cfg_def = (getattr(cfg, "default", "") or "").strip().lower()
            cfg_filename = (getattr(cfg, "filename", "") or "").strip()
            if cfg_def and default and cfg_def != default:
                issues.append(
                    (
                        "WARN",
                        "localization.cfg default=%s vs bundle %s" % (cfg_def, default),
                    )
                )
            # cfg filename tracks locale_base / .ksp name, not UrlName
            cmp_stem = file_stem or host
            if cfg_filename and cmp_stem and cfg_filename.lower() != cmp_stem.lower():
                issues.append(
                    (
                        "WARN",
                        "localization.cfg filename=%s vs file stem %s"
                        % (cfg_filename, cmp_stem),
                    )
                )
    else:
        issues.append(("INFO", "No source .ksp - prefab check skipped"))

    pending = (getattr(kb, "pending_removed_locales", "") or "").strip()
    if pending:
        issues.append(
            ("INFO", "Locales pending delete on Export: %s" % pending[:48])
        )

    try:
        n_toc = len(nodes)
    except Exception:
        n_toc = 0
    try:
        n_ui = len(getattr(kb, "ui_elements", None) or [])
    except Exception:
        n_ui = 0
    try:
        n_tex = len(getattr(kb, "textures", None) or [])
    except Exception:
        n_tex = 0
    try:
        n_ta = len(getattr(kb, "text_assets", None) or [])
    except Exception:
        n_ta = 0
    try:
        n_sh = len(getattr(kb, "shaders", None) or [])
    except Exception:
        n_sh = 0
    issues.append(
        (
            "INFO",
            "Export payload: TOC=%d UI=%d Tex=%d Text=%d Shaders=%d"
            % (n_toc, n_ui, n_tex, n_ta, n_sh),
        )
    )
    if n_toc == 0 and n_ui == 0 and n_tex == 0 and n_ta == 0:
        issues.append(
            ("WARN", "Nothing to export (empty TOC / UI / textures / text)")
        )

    xml_src = ""
    xml_name = (getattr(kb, "kspedia_xml_asset", "") or "").strip()
    try:
        for ta in getattr(kb, "text_assets", None) or []:
            if xml_name and (ta.name or "") == xml_name:
                xml_src = ta.text or ""
                if ta.text_block:
                    try:
                        xml_src = ta.text_block.as_string() or xml_src
                    except Exception:
                        pass
                break
            if not xml_src:
                lname = (ta.name or "").lower()
                if "kspedia" in lname and "bundle" not in lname:
                    xml_src = ta.text or ""
                    if ta.text_block:
                        try:
                            xml_src = ta.text_block.as_string() or xml_src
                        except Exception:
                            pass
    except Exception:
        xml_src = ""
    if xml_src.strip():
        try:
            import xml.etree.ElementTree as ET
            root_xml = ET.fromstring(xml_src)
            n_screens = sum(1 for el in root_xml.iter("Screen") if el.get("Name"))
            issues.append(("INFO", "KSPedia XML OK (%d Screen entries)" % n_screens))
            if n_toc == 0 and n_screens == 0:
                issues.append(("WARN", "XML has 0 Screens and TOC is empty"))
        except Exception as ex:
            issues.append(("ERROR", "KSPedia XML parse failed: %s" % str(ex)[:40]))
    elif n_toc > 0:
        # Squad single-page kspedia_* packs often have no Categories XML;
        # TOC is page/UI-only — WARN is only useful for third-party packs.
        if _looks_like_official_kspedia_pack(kb, src):
            issues.append(
                ("INFO", "Stock-style pack (no multipage XML TextAsset)")
            )
        else:
            issues.append(
                ("WARN", "No KSPedia XML TextAsset (TOC may not export)")
            )

    try:
        kb["_menu_check_missing_prefabs"] = ",".join(missing_prefabs[:64])
    except Exception:
        pass

    errors = [x for x in issues if x[0] == "ERROR"]
    warns = [x for x in issues if x[0] == "WARN"]
    infos = [x for x in issues if x[0] == "INFO"]
    out = errors[:6] + warns[:6] + infos[:4]
    if not errors and not warns:
        out.insert(
            0,
            ("OK", "Menu looks export-ready (.ksp / .lang / .cfg)"),
        )
    return out[:14]


def _page_bounds(page):
    coords = []
    try:
        objs = [page] + list(getattr(page, "children_recursive", []) or [])
    except Exception:
        objs = [page]
    for obj in objs:
        try:
            if obj.hide_get() or obj.hide_viewport:
                continue
        except Exception:
            continue
        try:
            for corner in obj.bound_box:
                coords.append(obj.matrix_world @ Vector(corner))
        except Exception:
            try:
                coords.append(obj.matrix_world.translation.copy())
            except Exception:
                continue
    if not coords:
        return None
    mn = Vector((
        min(v.x for v in coords),
        min(v.y for v in coords),
        min(v.z for v in coords),
    ))
    mx = Vector((
        max(v.x for v in coords),
        max(v.y for v in coords),
        max(v.z for v in coords),
    ))
    return mn, mx


def _ortho_matrices(mn, mx, width, height):
    center = (mn + mx) * 0.5
    span_x = max(float(mx.x - mn.x), 0.02)
    span_y = max(float(mx.y - mn.y), 0.02)
    pad = 1.08
    span_x *= pad
    span_y *= pad
    aspect = float(width) / float(max(height, 1))
    world_aspect = span_x / span_y
    if world_aspect > aspect:
        span_y = span_x / aspect
    else:
        span_x = span_y * aspect
    z = float(mx.z) + max(span_x, span_y) * 0.35 + 1.0
    view = Matrix.Translation(Vector((center.x, center.y, z))).inverted()
    # OpenGL ortho: left, right, bottom, top, near, far
    l, r = -span_x * 0.5, span_x * 0.5
    b, t = -span_y * 0.5, span_y * 0.5
    n, f = 0.01, max(z + 8.0, 20.0)
    proj = Matrix((
        (2.0 / (r - l), 0.0, 0.0, -(r + l) / (r - l)),
        (0.0, 2.0 / (t - b), 0.0, -(t + b) / (t - b)),
        (0.0, 0.0, -2.0 / (f - n), -(f + n) / (f - n)),
        (0.0, 0.0, 0.0, 1.0),
    ))
    return view, proj


def _get_pcoll():
    global _PCOLL
    import bpy.utils.previews
    if _PCOLL is None:
        _PCOLL = bpy.utils.previews.new()
    return _PCOLL


def _clear_pcoll():
    if _PCOLL is None:
        return
    for key in list(_PCOLL):
        try:
            del _PCOLL[key]
        except Exception:
            pass


def _store_capture_icon(img):
    """Save capture PNG and load a fresh icon (avoids Image Save UI)."""
    global _CAPTURE_ICON_ID, _CAPTURE_GEN
    _CAPTURE_ICON_ID = 0
    if img is None:
        return 0
    import os
    import tempfile
    _CAPTURE_GEN += 1
    path = os.path.join(
        tempfile.gettempdir(), "ksp_menu_check_%d.png" % _CAPTURE_GEN
    )
    try:
        img.file_format = "PNG"
        try:
            img.save(filepath=path)
        except TypeError:
            img.filepath_raw = path
            img.save()
    except Exception as e:
        print("WARNING: Menu Check save preview PNG failed: %s" % e)
        return 0
    if not os.path.isfile(path):
        return 0
    try:
        pcoll = _get_pcoll()
        _clear_pcoll()
        key = "cap_%d" % _CAPTURE_GEN
        try:
            pcoll.load(key, path, "IMAGE", True)
        except TypeError:
            pcoll.load(key, path, "IMAGE")
        _CAPTURE_ICON_ID = int(pcoll[key].icon_id)
    except Exception as e:
        print("WARNING: Menu Check preview icon failed: %s" % e)
        _CAPTURE_ICON_ID = 0
    return _CAPTURE_ICON_ID


def _pixels_to_image(name, width, height, pixels_float):
    # Always recreate so the dialog cannot keep a stale GPU/preview cache.
    old = bpy.data.images.get(name)
    if old is not None:
        try:
            bpy.data.images.remove(old)
        except Exception:
            pass
    try:
        tex = bpy.data.textures.get("KSP_MenuCheck_Tex")
        if tex is not None:
            bpy.data.textures.remove(tex)
    except Exception:
        pass
    img = bpy.data.images.new(name, width, height, alpha=True)
    try:
        img.pixels.foreach_set(pixels_float)
    except Exception:
        try:
            img.pixels[:] = pixels_float
        except Exception:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass
            return None
    try:
        img.update()
    except Exception:
        pass
    _store_capture_icon(img)
    _ensure_preview_texture(img)
    return img


def _resolve_capture_page(kb):

    """Menu Check follows the TOC radio — not a stale filter_page_object."""
    if kb is None:
        return None
    try:
        idx = int(kb.toc_nodes_index)
        if 0 <= idx < len(kb.toc_nodes):
            node = kb.toc_nodes[idx]
            page = node.page_object or node.folder_object
            if page is not None:
                return page
    except Exception:
        pass
    return getattr(kb, "filter_page_object", None)


def _flatten_pixel_seq(buf, width, height):
    """GPU Buffer → flat float RGBA (len = w*h*4). Nested to_list() is OK."""
    n = int(width) * int(height) * 4
    if buf is None or n <= 0:
        return None
    try:
        buf.dimensions = n
    except Exception:
        pass
    seq = None
    try:
        if hasattr(buf, "to_list"):
            seq = buf.to_list()
    except Exception:
        seq = None
    if seq is None:
        try:
            seq = list(buf)
        except Exception:
            return None
    flat = []

    def _walk(x):
        if isinstance(x, (list, tuple)):
            for y in x:
                _walk(y)
        else:
            try:
                flat.append(float(x))
            except Exception:
                pass

    _walk(seq)
    if len(flat) < n:
        return None
    sample = [flat[i] for i in range(0, min(32, n), 4)]
    scale = 255.0 if (sample and max(sample) > 1.01) else 1.0
    if scale == 1.0:
        return flat[:n]
    return [v / scale for v in flat[:n]]


def _read_offscreen_pixels(offscreen, width, height):
    buf = None
    try:
        tex = getattr(offscreen, "texture_color", None)
        if tex is not None:
            buf = tex.read()
    except Exception:
        buf = None
    pix = _flatten_pixel_seq(buf, width, height) if buf is not None else None
    if pix:
        return pix
    try:
        import gpu
        offscreen.bind()
        try:
            fb = gpu.state.active_framebuffer_get()
            buf = fb.read_color(0, 0, width, height, 4, 0, "FLOAT")
            try:
                buf.dimensions = width * height * 4
            except Exception:
                pass
            return _flatten_pixel_seq(buf, width, height)
        finally:
            try:
                offscreen.unbind()
            except Exception:
                pass
    except Exception:
        return None


def _gpu_offscreen(width, height):
    """Create an offscreen; ``gpu.init()`` is required in some 5.2 contexts."""
    import gpu
    try:
        return gpu.types.GPUOffScreen(width, height)
    except SystemError:
        try:
            gpu.init()
        except Exception:
            pass
        return gpu.types.GPUOffScreen(width, height)


def _iter_wm_windows(context):
    windows = []
    try:
        wm = getattr(context, "window_manager", None) or bpy.context.window_manager
        windows = list(getattr(wm, "windows", []) or [])
    except Exception:
        windows = []
    if not windows:
        win = getattr(context, "window", None)
        if win is not None:
            windows = [win]
    return windows


def _view3d_from_area(area):
    if area is None:
        return None, None
    space = getattr(area, "spaces", None)
    space = space.active if space is not None else None
    region = None
    try:
        for reg in area.regions:
            if reg.type == "WINDOW" and int(getattr(reg, "width", 0) or 0) > 8:
                region = reg
                break
        if region is None:
            for reg in area.regions:
                if reg.type == "WINDOW":
                    region = reg
                    break
    except Exception:
        region = None
    return space, region


def _find_view3d(context):
    """Any live 3D View across all windows (not only the dialog's screen)."""
    for win in _iter_wm_windows(context):
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in getattr(screen, "areas", []) or []:
            try:
                if area.type != "VIEW_3D":
                    continue
            except Exception:
                continue
            space, region = _view3d_from_area(area)
            if space is not None and region is not None:
                return win, area, space, region
    return None, None, None, None


def _pick_area_to_convert(screen):
    areas = list(getattr(screen, "areas", []) or [])
    if not areas:
        return None
    prefer = (
        "IMAGE_EDITOR", "NODE_EDITOR", "OUTLINER", "TEXT_EDITOR",
        "DOPESHEET_EDITOR", "GRAPH_EDITOR", "SEQUENCE_EDITOR",
    )
    for kind in prefer:
        for area in areas:
            try:
                if area.type == kind:
                    return area
            except Exception:
                continue
    try:
        return max(areas, key=lambda a: int(a.width) * int(a.height))
    except Exception:
        return areas[0]


def _open_view3d(context):
    """Turn an existing editor into VIEW_3D. Returns (win, area, space, region, restore_type)."""
    win = None
    try:
        win = getattr(context, "window", None) or _iter_wm_windows(context)[0]
    except Exception:
        win = None
    if win is None:
        return None, None, None, None, None
    screen = getattr(win, "screen", None)
    area = _pick_area_to_convert(screen)
    if area is None:
        return None, None, None, None, None
    prev = None
    try:
        prev = area.type
        area.type = "VIEW_3D"
    except Exception:
        return None, None, None, None, None
    space, region = _view3d_from_area(area)
    try:
        from .viewport import setup_ui_view
        setup_ui_view(context)
    except Exception:
        try:
            if space is not None:
                space.shading.type = "MATERIAL"
                if space.region_3d is not None:
                    space.region_3d.view_perspective = "ORTHO"
        except Exception:
            pass
    return win, area, space, region, prev


def _ensure_view3d(context):
    """Return (win, area, space, region, restore_type or None)."""
    win, area, space, region = _find_view3d(context)
    if space is not None and region is not None:
        return win, area, space, region, None
    return _open_view3d(context)


def _set_capture_error(msg):
    global _CAPTURE_ERROR
    _CAPTURE_ERROR = (msg or "")[:96]


def capture_page_preview(context, root, page, width=_PREVIEW_W, height=_PREVIEW_H):
    """Ortho snapshot of the visible page as it will look in-game (no overlays).

    Opens a 3D View itself when the current workspace has none.
    """
    if context is None or page is None:
        _set_capture_error("No page selected")
        return None
    bounds = _page_bounds(page)
    if bounds is None:
        _set_capture_error("Page has no visible geometry")
        return None
    mn, mx = bounds
    view, proj = _ortho_matrices(mn, mx, width, height)

    win, area, space, region, restore_type = _ensure_view3d(context)
    if space is None or region is None:
        if restore_type and area is not None:
            try:
                area.type = restore_type
            except Exception:
                pass
        _set_capture_error("No 3D View to capture")
        return None
    scene = getattr(win, "scene", None) or getattr(context, "scene", None)
    view_layer = getattr(win, "view_layer", None) or getattr(context, "view_layer", None)
    if scene is None or view_layer is None:
        if restore_type and area is not None:
            try:
                area.type = restore_type
            except Exception:
                pass
        _set_capture_error("No scene / view layer")
        return None

    overlay_prev = None
    show_text = None
    try:
        overlay_prev = bool(space.overlay.show_overlays)
        space.overlay.show_overlays = False
    except Exception:
        overlay_prev = None
    try:
        kb = root.ksp_bundle if root is not None else None
        if kb is not None and getattr(kb, "show_text_boxes", False):
            from .locale_switch import sync_text_box_overlays
            show_text = True
            sync_text_box_overlays(root, False)
    except Exception:
        show_text = None

    img = None
    pix = None
    try:
        offscreen = _gpu_offscreen(width, height)
        try:
            try:
                offscreen.draw_view3d(
                    scene,
                    view_layer,
                    space,
                    region,
                    view,
                    proj,
                    do_color_management=True,
                    draw_background=True,
                )
            except TypeError:
                offscreen.draw_view3d(
                    scene,
                    view_layer,
                    space,
                    region,
                    view,
                    proj,
                )
            pix = _read_offscreen_pixels(offscreen, width, height)
        finally:
            try:
                offscreen.free()
            except Exception:
                pass
        if pix:
            img = _pixels_to_image(_IMAGE_NAME, width, height, pix)
            if img is None:
                _set_capture_error("Could not store preview image")
        else:
            _set_capture_error("Could not read page pixels")
            stale = bpy.data.images.get(_IMAGE_NAME)
            if stale is not None:
                try:
                    bpy.data.images.remove(stale)
                except Exception:
                    pass
    except Exception as e:
        img = None
        _set_capture_error("%s: %s" % (type(e).__name__, e))
        print("WARNING: Menu Check preview failed: %s" % e)
    finally:
        if overlay_prev is not None:
            try:
                space.overlay.show_overlays = overlay_prev
            except Exception:
                pass
        if show_text and root is not None:
            try:
                from .locale_switch import sync_text_box_overlays
                kb = root.ksp_bundle
                sync_text_box_overlays(
                    root,
                    True,
                    pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
                    scope=page,
                )
            except Exception:
                pass
        if restore_type and area is not None:
            try:
                area.type = restore_type
            except Exception:
                pass
    return img


def _drain_locale():
    try:
        from .locale_switch import get_locale_apply_job, process_locale_apply_chunk
        g = 0
        while get_locale_apply_job() is not None and g < 4000:
            process_locale_apply_chunk(48)
            g += 1
    except Exception:
        pass



def fill_explore_assets(kb) -> int:
    """Rebuild ``kb.explore_assets`` from what Export would write."""
    if kb is None:
        return 0
    try:
        kb.explore_assets.clear()
    except Exception:
        return 0

    def _add(kind, name, detail=""):
        try:
            row = kb.explore_assets.add()
            row.kind = kind
            row.name = name or "?"
            row.detail = detail or ""
        except Exception:
            pass

    # Textures → .ksp Texture2D
    try:
        for tex in kb.textures:
            w = int(getattr(tex, "width", 0) or 0)
            h = int(getattr(tex, "height", 0) or 0)
            pid = (getattr(tex, "path_id", None) or "").strip()
            ext = "external" if getattr(tex, "texture_external", False) else "embed"
            detail = "%dx%d · %s" % (w, h, ext)
            if pid:
                detail += " · id=%s" % pid
            _add("texture", tex.name or "(texture)", detail)
    except Exception:
        pass

    # TextAssets → .ksp (XML etc.)
    try:
        for ta in kb.text_assets:
            body = ta.text or ""
            if ta.text_block:
                try:
                    body = ta.text_block.as_string() or body
                except Exception:
                    pass
            n = len(body or "")
            mark = ""
            lname = (ta.name or "").lower()
            xml_name = (getattr(kb, "kspedia_xml_asset", "") or "").strip().lower()
            if xml_name and lname == xml_name:
                mark = " · KSPedia XML"
            elif "kspedia" in lname and "bundle" not in lname:
                mark = " · KSPedia XML?"
            _add("text", ta.name or "(text)", "%d chars%s" % (n, mark))
    except Exception:
        pass

    # Shaders / materials (passthrough in .ksp)
    try:
        for sh in kb.shaders:
            _add("shader", sh.name or "(shader)", "path_id=%s" % (sh.path_id or ""))
    except Exception:
        pass
    try:
        for mat in kb.materials:
            _add("material", mat.name or "(material)", "")
    except Exception:
        pass

    # UI Elements summary (live objects written into prefabs)
    try:
        n_text = n_img = n_other = 0
        for el in kb.ui_elements:
            k = str(getattr(el, "kind", "") or "")
            if k == "text":
                n_text += 1
            elif k == "image":
                n_img += 1
            else:
                n_other += 1
        if n_text or n_img or n_other:
            _add(
                "ui",
                "UI Elements",
                "text=%d image=%d other=%d" % (n_text, n_img, n_other),
            )
    except Exception:
        pass

    # TOC
    try:
        n_toc = len(kb.toc_nodes)
        if n_toc:
            _add("toc", "TOC rows", "%d" % n_toc)
    except Exception:
        pass

    # Locales / .lang on disk beside Source
    locs = [
        x.strip().lower()
        for x in (getattr(kb, "available_locales", "") or "").split(",")
        if x.strip()
    ]
    src = (getattr(kb, "source_path", "") or "").strip()
    import os
    for loc in locs or ["en-us"]:
        detail = "in memory"
        if src and os.path.isfile(src):
            folder = os.path.dirname(src)
            base = os.path.splitext(os.path.basename(src))[0]
            # strip locale suffix from base if present
            cand = [
                os.path.join(folder, "%s.lang" % loc),
                os.path.join(folder, "%s_%s.lang" % (base, loc)),
            ]
            # common pattern: name_en-us.ksp + name.lang / Localization
            stem = base
            for suf in ("_en-us", "_de-de", "_fr-fr", "_es-es", "_pt-br", "_ru", "_zh-cn"):
                if stem.lower().endswith(suf):
                    stem = stem[: -len(suf)]
                    break
            cand.append(os.path.join(folder, "%s.lang" % stem))
            cand.append(os.path.join(folder, "%s_%s.lang" % (stem, loc)))
            found = next((p for p in cand if os.path.isfile(p)), None)
            if found:
                try:
                    sz = os.path.getsize(found)
                except Exception:
                    sz = 0
                detail = "%s (%d B)" % (os.path.basename(found), sz)
            else:
                detail = "no .lang on disk yet"
        _add("lang", loc, detail)

    if src and os.path.isfile(src):
        try:
            sz = os.path.getsize(src)
        except Exception:
            sz = 0
        _add("ksp", os.path.basename(src), "source · %d B" % sz)
        folder = os.path.dirname(src)
        cfg = os.path.join(folder, "localization.cfg")
        if os.path.isfile(cfg):
            _add("cfg", "localization.cfg", folder)

    try:
        return len(kb.explore_assets)
    except Exception:
        return 0


def _draw_explore_assets(layout, kb):
    box = layout.box()
    try:
        box.label(text="Explore Assets", icon="FILEBROWSER")
    except Exception:
        box.label(text="Explore Assets", icon="FILE")
    try:
        n = len(kb.explore_assets)
    except Exception:
        n = 0
    if n == 0:
        box.label(text="(nothing queued for export)", icon="INFO")
        return
    # Compact list — invoke_popup clips tall content below the Menu TOC.
    rows = min(6, max(3, min(n, 6)))
    box.template_list(
        "KSPMU_UL_MenuCheckExplore",
        "ksp_menu_explore",
        kb,
        "explore_assets",
        kb,
        "explore_assets_index",
        rows=rows,
        maxrows=rows,
    )


class KSPMU_UL_MenuCheckExplore(bpy.types.UIList):
    """Export payload browser inside Menu Check."""

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index,
    ):
        kind = (getattr(item, "kind", "") or "").lower()
        ic = {
            "texture": "IMAGE_DATA",
            "text": "TEXT",
            "shader": "NODE_MATERIAL",
            "material": "MATERIAL",
            "ui": "FONT_DATA",
            "toc": "BOOKMARKS",
            "lang": "WORLD",
            "ksp": "FILE_BLEND",
            "cfg": "SETTINGS",
        }.get(kind, "DOT")
        row = layout.row(align=True)
        row.label(text=item.name or "?", icon=ic)
        det = (getattr(item, "detail", "") or "").strip()
        if det:
            sub = row.row(align=True)
            sub.alignment = "RIGHT"
            sub.label(text=det[:42])


def _refresh_state(context):
    global _ISSUES, _CAPTURE_ERROR, _CAPTURE_ICON_ID
    _CAPTURE_ERROR = ""
    _CAPTURE_ICON_ID = 0
    root = _find_root(context)
    if root is None:
        _ISSUES = [("ERROR", "Select a KSP bundle")]
        _set_capture_error("Select a KSP bundle")
        return None
    kb = root.ksp_bundle
    _ISSUES = sanity_check_menu(root, kb)
    try:
        fill_explore_assets(kb)
    except Exception:
        pass
    page = _resolve_capture_page(kb)
    if page is not None:
        try:
            from .import_ksp import show_multipage_scope
            show_multipage_scope(root, page)
        except Exception:
            pass
    capture_page_preview(context, root, page)
    return root


def _on_menu_check_locale(self, context):
    global _LOCK
    if _LOCK:
        return
    loc = (self.locale or "").strip().lower()
    if not loc:
        return
    root = _find_root(context)
    if root is None:
        return
    kb = root.ksp_bundle
    cur = (getattr(kb, "active_locale", "") or "").strip().lower()
    if loc == cur:
        return
    _LOCK = True
    try:
        try:
            kb.active_locale = loc
        except Exception:
            try:
                kb["active_locale"] = loc
            except Exception:
                pass
        _drain_locale()
        _refresh_state(context)
        try:
            for area in context.screen.areas:
                area.tag_redraw()
        except Exception:
            pass
    except Exception:
        pass
    finally:
        _LOCK = False


def _schedule_menu_check_capture():
    """Recapture after TOC click without doing GPU work inside draw()."""
    global _MENU_CHECK_SYNC
    if _MENU_CHECK_SYNC or not _MENU_CHECK_LIVE:
        return

    def _run():
        global _MENU_CHECK_SYNC, _MENU_CHECK_IDX
        if not _MENU_CHECK_LIVE:
            return None
        _MENU_CHECK_SYNC = True
        try:
            root = _find_root(bpy.context)
            if root is None:
                return None
            kb = root.ksp_bundle
            idx = int(getattr(kb, "toc_nodes_index", 0) or 0)
            if idx == _MENU_CHECK_IDX:
                return None
            _MENU_CHECK_IDX = idx
            _refresh_state(bpy.context)
            try:
                screen = getattr(bpy.context, "screen", None)
                if screen is not None:
                    for area in screen.areas:
                        area.tag_redraw()
            except Exception:
                pass
        except Exception as e:
            print("WARNING: Menu Check recapture failed: %s" % e)
        finally:
            _MENU_CHECK_SYNC = False
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.02)
    except Exception:
        _run()


def _draw_menu_preview(layout, kb):
    """Scrollable TOC (UIList) — vertical bar when items exceed the pane."""
    nodes = getattr(kb, "toc_nodes", None)
    if not nodes or len(nodes) == 0:
        layout.label(text="(no TOC)", icon="INFO")
        return
    # Shorter TOC so Explore Assets under Menu stays visible in invoke_popup.
    rows = 8
    layout.template_list(
        "KSPMU_UL_MenuCheckToc",
        "ksp_menu_check",
        kb,
        "toc_nodes",
        kb,
        "toc_nodes_index",
        rows=rows,
        maxrows=rows,
    )


class KSPMU_UL_MenuCheckToc(bpy.types.UIList):
    """Menu Check TOC rows with indent + radio affordance."""

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index,
    ):
        row = layout.row(align=True)
        try:
            depth = int(item.depth)
        except Exception:
            depth = 0
        for _ in range(max(0, min(depth, 6))):
            row.label(text="", icon="BLANK1")
        kind = getattr(item, "kind", "") or ""
        ic = "FILE_FOLDER" if kind in {"category", "subcategory"} else "DOCUMENTS"
        try:
            sel = int(getattr(active_data, active_propname))
        except Exception:
            sel = -1
        on = index == sel
        row.label(text="", icon="RADIOBUT_ON" if on else "RADIOBUT_OFF")
        title = (getattr(item, "title", "") or getattr(item, "screen", "") or "?").strip()
        miss = ""
        try:
            if hasattr(data, "keys") and "_menu_check_missing_prefabs" in data.keys():
                miss = str(data["_menu_check_missing_prefabs"] or "")
        except Exception:
            miss = ""
        sid = (getattr(item, "screen", "") or "").strip()
        if sid and miss and sid in miss.split(","):
            title = "%s (missing prefab)" % title
        elif getattr(item, "overrides_stock", False):
            title = "%s (replaced)" % title
        row.label(text=title, icon=ic)


class KSPMU_OT_MenuCheckSelect(bpy.types.Operator):
    """Pick a TOC row in the Menu Check dialog and recapture its page."""

    bl_idname = "object.ksp_menu_check_select"
    bl_label = "Select Menu Item"
    bl_description = "Show this KSPedia menu entry and recapture its page thumbnail"
    bl_options = {"INTERNAL"}

    index: IntProperty(name="TOC index", default=0, min=0)

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        idx = int(self.index)
        try:
            n = len(kb.toc_nodes)
        except Exception:
            n = 0
        if not (0 <= idx < n):
            return {"CANCELLED"}
        try:
            if int(kb.toc_nodes_index) != idx:
                kb.toc_nodes_index = idx
        except Exception:
            try:
                kb["toc_nodes_index"] = idx
            except Exception:
                pass
        _refresh_state(context)
        try:
            for area in context.screen.areas:
                area.tag_redraw()
        except Exception:
            pass
        return {"FINISHED"}


class KSPMU_OT_MenuCheck(bpy.types.Operator):
    """Sanity-check the KSPedia menu, then preview in-game menu + page."""

    bl_idname = "object.ksp_menu_check"
    bl_label = "Menu Check"
    bl_description = (
        "Check the TOC for export problems, then show a small preview of how "
        "the menu and the current page will look in-game (.ksp / .lang / .cfg)"
    )
    bl_options = {"REGISTER"}

    locale: EnumProperty(
        name="Language",
        description="Switch language to preview menu titles and page texts",
        items=_locale_items,
        update=_on_menu_check_locale,
    )

    @classmethod
    def poll(cls, context):
        return _find_root(context) is not None

    def invoke(self, context, event):
        global _LOCK
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        _LOCK = True
        try:
            cur = (
                getattr(kb, "active_locale", "")
                or getattr(kb, "locale", "")
                or "en-us"
            ).strip().lower()
            try:
                self.locale = cur
            except Exception:
                pass
        finally:
            _LOCK = False
        global _MENU_CHECK_LIVE, _MENU_CHECK_IDX
        _MENU_CHECK_LIVE = True
        _MENU_CHECK_IDX = -1
        _refresh_state(context)
        try:
            _MENU_CHECK_IDX = int(kb.toc_nodes_index)
        except Exception:
            _MENU_CHECK_IDX = 0
        return context.window_manager.invoke_popup(self, width=int(_DIALOG_WIDTH))

    def draw(self, context):
        layout = self.layout
        root = _find_root(context)
        kb = root.ksp_bundle if root is not None else None

        issues = _ISSUES or [("INFO", "No check run")]
        box = layout.box()
        worst = "OK"
        for level, _msg in issues:
            if level == "ERROR":
                worst = "ERROR"
                break
            if level == "WARN" and worst == "OK":
                worst = "WARN"
        head_icon = (
            "CHECKMARK" if worst == "OK" else (
                "ERROR" if worst == "ERROR" else "ERROR"
            )
        )
        box.label(text="Sanity", icon=head_icon)
        for level, msg in issues:
            icon = {
                "OK": "CHECKMARK",
                "ERROR": "CANCEL",
                "WARN": "ERROR",
                "INFO": "INFO",
            }.get(level, "DOT")
            box.label(text=msg[:88], icon=icon)

        layout.prop(self, "locale", text="Language")
        if kb is not None:
            src = (getattr(kb, "source_path", "") or "").strip()
            loc = (self.locale or "").strip().lower()
            hint = ".ksp + .lang + localization.cfg"
            if src:
                import os
                base = os.path.splitext(os.path.basename(src))[0]
                hint = "%s.ksp  |  %s.lang  |  localization.cfg" % (base, loc or "xx-xx")
            layout.label(text=hint, icon="EXPORT")

        layout.label(text="Menu", icon="OUTLINER")
        if kb is not None:
            _draw_menu_preview(layout, kb)
            try:
                if not len(getattr(kb, "explore_assets", []) or []):
                    fill_explore_assets(kb)
            except Exception:
                try:
                    fill_explore_assets(kb)
                except Exception:
                    pass
            _draw_explore_assets(layout, kb)

    def execute(self, context):
        global _MENU_CHECK_LIVE
        _MENU_CHECK_LIVE = False
        _refresh_state(context)
        return {"FINISHED"}

    def cancel(self, context):
        global _MENU_CHECK_LIVE
        _MENU_CHECK_LIVE = False

