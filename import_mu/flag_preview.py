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

"""Viewport FlagDecal preview.

Bundled ``flags/default.webp`` plus any image dropped in ``flags/``.
The rest is read from GameData ``Flags*`` folders (png, dds, tga).
DDS is copied to an unpacked image. Blender already stores those pixels
right-side up, so the shader must not flip them again.
"""

from __future__ import annotations

import json
import os
import re
import shutil

import bpy
from bpy.utils import previews

MU_FLAG_KEY = "mu_flag_decal"
MU_FLAG_PREVIEW = "mu_flag_preview"
# Viewport-only: FlagDecal quad hidden for "No Flag" (not written to .mu).
MU_FLAG_NO_FLAG_HIDDEN = "mu_flag_no_flag_hidden"
MU_FLAG_PREV_HIDE_VP = "mu_flag_prev_hide_viewport"
MU_FLAG_PREV_HIDE_RENDER = "mu_flag_prev_hide_render"
NO_FLAG = "NONE"

# bpy.utils.previews collection for Flag Decal enum thumbnails.
_flag_previews = None
# Blender keeps references to enum callback strings — cache the last items list.
_flag_enum_items_cache = []


def addon_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def flags_dir():
    return os.path.join(addon_root(), "flags")


def _ensure_flag_previews():
    """Return the PreviewCollection used for Flag Decal enum icons."""
    global _flag_previews
    if _flag_previews is None:
        _flag_previews = previews.new()
    return _flag_previews


def clear_flag_previews():
    """Remove loaded flag thumbnails (call after sync / on unregister)."""
    global _flag_previews, _flag_enum_items_cache
    if _flag_previews is not None:
        try:
            previews.remove(_flag_previews)
        except Exception:
            pass
        _flag_previews = None
    _flag_enum_items_cache = []


def register_flag_previews():
    """Create an empty preview collection (images load on demand)."""
    _ensure_flag_previews()


def unregister_flag_previews():
    clear_flag_previews()


def _flag_preview_image_path(stem, path=None):
    """Resolve a flag file. ``path`` from the live list wins."""
    if path and os.path.isfile(path):
        return path
    want = (stem or "").lower()
    if not want:
        return None
    for name, candidate in list_flag_files():
        if name.lower() == want and os.path.isfile(candidate):
            return candidate
    return None


_DDS_ICON_QUEUE = []
_DDS_ICON_PENDING = set()
_DDS_ICON_TIMER = False
_DDS_PIXEL_REV = 2


def _flag_icon_cache_dir():
    path = os.path.join(addon_root(), "cache", "flag_icons")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return None
    return path


def _flag_icon_cache_png(stem):
    folder = _flag_icon_cache_dir()
    if not folder:
        return None
    path = os.path.join(folder, "%s.v%d.png" % (stem, _DDS_PIXEL_REV))
    if os.path.isfile(path) and os.path.getsize(path) > 32:
        return path
    return None


def _queue_dds_icon(src_path, stem):
    """Decode DDS thumbs off the enum draw so the menu stays instant."""
    global _DDS_ICON_TIMER
    key = stem.lower()
    if key in _DDS_ICON_PENDING or _flag_icon_cache_png(stem):
        return
    _DDS_ICON_PENDING.add(key)
    _DDS_ICON_QUEUE.append((src_path, stem))
    if _DDS_ICON_TIMER:
        return
    try:
        bpy.app.timers.register(_dds_icon_timer, first_interval=0.05)
        _DDS_ICON_TIMER = True
    except Exception:
        _DDS_ICON_TIMER = False


def _dds_icon_timer():
    """One DDS per tick: flip, write PNG, drop the DDS datablock."""
    global _DDS_ICON_TIMER, _flag_enum_items_cache
    if not _DDS_ICON_QUEUE:
        _DDS_ICON_TIMER = False
        return None
    src_path, stem = _DDS_ICON_QUEUE.pop(0)
    _write_dds_icon_png(src_path, stem)
    _DDS_ICON_PENDING.discard(stem.lower())
    _flag_enum_items_cache = []
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass
    if not _DDS_ICON_QUEUE:
        _DDS_ICON_TIMER = False
        return None
    return 0.02


def _write_dds_icon_png(src_path, stem):
    dst = None
    folder = _flag_icon_cache_dir()
    if folder:
        dst = os.path.join(folder, "%s.v%d.png" % (stem, _DDS_PIXEL_REV))
    raw = None
    try:
        raw = bpy.data.images.load(src_path, check_existing=False)
        _flip_image_vertical(raw)
        if dst:
            raw.filepath_raw = dst
            raw.file_format = "PNG"
            raw.save()
    except Exception:
        return None
    finally:
        if raw is not None:
            try:
                bpy.data.images.remove(raw)
            except Exception:
                pass
    if dst and os.path.isfile(dst):
        return dst
    return None


def _flag_preview_icon_id(stem, path=None):
    """Load (or reuse) a small preview; return icon_id, or 0 on failure."""
    key = "flag_" + (stem or "").lower()
    if not key or key == "flag_":
        return 0
    pcoll = _ensure_flag_previews()
    if key in pcoll:
        return pcoll[key].icon_id
    img_path = _flag_preview_image_path(stem, path)
    if not img_path:
        return 0
    low = img_path.lower()
    if low.endswith(".dds"):
        cached = _flag_icon_cache_png(stem)
        if not cached:
            _queue_dds_icon(img_path, stem)
            return 0
        img_path = cached
    try:
        pcoll.load(key, img_path, "IMAGE")
        return pcoll[key].icon_id
    except Exception:
        return 0


def flags_manifest_path():
    return os.path.join(flags_dir(), "manifest.json")


def _gamedata_relative_source(src):
    """Return ``Squad/Flags/foo.png`` — never an absolute machine path."""
    if not src:
        return ""
    norm = str(src).replace("\\", "/")
    low = norm.lower()
    marker = "/gamedata/"
    idx = low.rfind(marker)
    if idx >= 0:
        return norm[idx + len(marker):]
    if ":" not in norm and not norm.startswith("/"):
        return norm.lstrip("./")
    return os.path.basename(norm)


def _walk_gamedata_roots(mudir=None):
    roots = []
    try:
        prefs = bpy.context.preferences.addons
        for mod in prefs:
            if not mod or not getattr(mod, "preferences", None):
                continue
            gd = getattr(mod.preferences, "GameData", None)
            if gd and os.path.isdir(gd) and gd not in roots:
                roots.append(gd)
    except Exception:
        pass
    if mudir:
        cur = os.path.abspath(mudir)
        for _ in range(12):
            if os.path.basename(cur).lower() == "gamedata":
                if cur not in roots:
                    roots.append(cur)
                break
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    test_gd = os.path.join(addon_root(), "test tools v2", "GameData")
    if os.path.isdir(test_gd) and test_gd not in roots:
        roots.append(test_gd)
    return roots


def _flag_source_dirs(mudir=None):
    """Flag folders one or two levels under GameData.

    Stock is ``Squad/Flags``, ``FlagsAgency``, ``FlagsOrganization``.
    Mods use ``<Mod>/Flags*`` or ``<Mod>/Assets/Flags*``. No full tree walk.
    """
    out = []
    seen = set()

    def _add(path):
        if not path or not os.path.isdir(path):
            return
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    def _take_flags(parent):
        try:
            names = os.listdir(parent)
        except Exception:
            return
        for name in names:
            if not name.lower().startswith("flags"):
                continue
            _add(os.path.join(parent, name))

    for gd in _walk_gamedata_roots(mudir):
        if not os.path.isdir(gd):
            continue
        _take_flags(gd)
        try:
            mods = os.listdir(gd)
        except Exception:
            continue
        for mod in mods:
            mod_path = os.path.join(gd, mod)
            if not os.path.isdir(mod_path):
                continue
            if mod.lower() == "parts":
                continue
            _take_flags(mod_path)
            assets = os.path.join(mod_path, "Assets")
            if os.path.isdir(assets):
                _take_flags(assets)
    return out


_FLAG_EXTS = {".webp", ".png", ".tga", ".dds"}
_FLAG_RANK = {".webp": 0, ".png": 1, ".tga": 2, ".dds": 3}
_FLAG_LIST_CACHE = {"key": None, "items": []}


def _consider_flag(by_stem, stem, path, local):
    ext = os.path.splitext(path)[1].lower()
    rank = _FLAG_RANK.get(ext, 9)
    # Files dropped into addon flags/ win over the same stem in GameData.
    score = (0 if local else 1, rank)
    key = stem.lower()
    prev = by_stem.get(key)
    if prev is None or score < prev[0]:
        by_stem[key] = (score, stem, path)


def _scan_flag_folder(folder, by_stem, local):
    try:
        names = os.listdir(folder)
    except Exception:
        return
    for fn in names:
        ext = os.path.splitext(fn)[1].lower()
        if ext not in _FLAG_EXTS:
            continue
        stem = os.path.splitext(fn)[0]
        if not stem or stem.lower() == "manifest":
            continue
        _consider_flag(by_stem, stem, os.path.join(folder, fn), local)


def list_flag_files():
    """Bundled ``flags/`` plus GameData ``Flags*`` folders.

    Listing only reads directory names. DDS files stay on disk and are
    flipped when the image is shown.
    """
    dest = flags_dir()
    roots = tuple(_walk_gamedata_roots(None))
    try:
        local_m = os.path.getmtime(dest) if os.path.isdir(dest) else 0
    except Exception:
        local_m = 0
    key = (roots, local_m)
    cached = _FLAG_LIST_CACHE.get("key")
    if cached == key:
        return list(_FLAG_LIST_CACHE.get("items") or [])
    by_stem = {}
    if os.path.isdir(dest):
        _scan_flag_folder(dest, by_stem, True)
    for folder in _flag_source_dirs():
        _scan_flag_folder(folder, by_stem, False)
    out = [(stem, path) for _score, stem, path in sorted(
        by_stem.values(), key=lambda t: t[1].lower())]
    _FLAG_LIST_CACHE["key"] = key
    _FLAG_LIST_CACHE["items"] = out
    return list(out)


def sync_flags_from_gamedata(mudir=None, force=False):
    """Kept for callers. Flags are read in place; nothing is copied."""
    _FLAG_LIST_CACHE["key"] = None
    return 0


def _flip_image_vertical(img):
    """Reflect across the X axis (top row becomes the bottom row)."""
    try:
        w, h = int(img.size[0]), int(img.size[1])
    except Exception:
        return
    if w < 1 or h < 1:
        return
    try:
        px = list(img.pixels)
    except Exception:
        return
    row = w * 4
    if len(px) < row * h:
        return
    flipped = []
    for y in range(h - 1, -1, -1):
        start = y * row
        flipped.extend(px[start:start + row])
    try:
        img.pixels = flipped
    except Exception:
        pass


def _save_image_webp(img, dst_path, quality=90):
    scene = bpy.context.scene
    settings = scene.render.image_settings
    old_fmt = settings.file_format
    old_q = settings.quality
    try:
        settings.file_format = "WEBP"
        settings.quality = int(quality)
        try:
            img.file_format = "WEBP"
        except Exception:
            pass
        img.save_render(dst_path)
    finally:
        try:
            settings.file_format = old_fmt
            settings.quality = old_q
        except Exception:
            pass


def store_flag_as_webp(src_path, dest_dir, stem, quality=90):
    """Write ``stem.webp``. DDS is stored upside down, so flip it first."""
    os.makedirs(dest_dir, exist_ok=True)
    dst = os.path.join(dest_dir, stem + ".webp")
    low = (src_path or "").lower()
    if low.endswith(".webp"):
        if os.path.abspath(src_path) != os.path.abspath(dst):
            shutil.copy2(src_path, dst)
        return dst
    img = bpy.data.images.load(src_path, check_existing=False)
    try:
        if low.endswith(".dds"):
            _flip_image_vertical(img)
        _save_image_webp(img, dst, quality=quality)
    finally:
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass
    return dst


def convert_bundled_flags_to_webp():
    """Replace PNG/DDS/TGA already in ``flags/`` with quality-90 WebP."""
    dest = flags_dir()
    if not os.path.isdir(dest):
        return 0
    converted = 0
    for fn in list(os.listdir(dest)):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in (".png", ".dds", ".tga"):
            continue
        stem = os.path.splitext(fn)[0]
        src = os.path.join(dest, fn)
        try:
            store_flag_as_webp(src, dest, stem)
        except Exception as exc:
            print("WARNING: flag webp %s: %s" % (fn, exc))
            continue
        if os.path.isfile(os.path.join(dest, stem + ".webp")):
            try:
                os.remove(src)
            except Exception:
                pass
            converted += 1
    manifest_path = flags_manifest_path()
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        manifest = {"flags": []}
    flags = []
    seen = set()
    for entry in manifest.get("flags") or []:
        stem = str(entry.get("name") or "")
        if not stem or stem.lower() in seen:
            continue
        webp = stem + ".webp"
        if not os.path.isfile(os.path.join(dest, webp)):
            continue
        seen.add(stem.lower())
        flags.append({
            "name": stem,
            "file": webp,
            "source": entry.get("source") or "",
        })
    flags.sort(key=lambda e: e["name"].lower())
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"flags": flags}, f, indent=2)
    except Exception:
        pass
    clear_flag_previews()
    return converted


def parse_flag_decal(cfg_text):
    """Return first FlagDecal {textureQuadName} or None."""
    if not cfg_text or "FlagDecal" not in cfg_text:
        return None
    for block in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = block.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "FlagDecal":
            continue
        tq = re.search(r"^\s*textureQuadName\s*=\s*(.+)$", body, re.M | re.I)
        if not tq:
            continue
        return {
            "textureQuadName": tq.group(1).strip().strip('"').split("//")[0].strip(),
        }
    return None


def _object_stem(name):
    n = (name or "").split("\u2227")[0]
    if "." in n:
        b, s = n.rsplit(".", 1)
        if s.isdigit():
            n = b
    return n


def _find_named(root, want):
    want_l = (want or "").lower()
    if not want_l or root is None:
        return None
    stack = [root]
    while stack:
        o = stack.pop()
        if _object_stem(o.name).lower() == want_l:
            return o
        stack.extend(list(o.children))
    return None


def find_flag_quad(root, texture_quad_name=None):
    """Locate FlagDecal mesh/empty under root."""
    if root is None:
        return None
    if texture_quad_name:
        hit = _find_named(root, texture_quad_name)
        if hit is not None:
            return hit
    # Heuristic: flag / flagTransform / FLAG / flagMat host
    stack = [root]
    prefer = []
    while stack:
        o = stack.pop()
        stem = _object_stem(o.name).lower()
        if stem in ("flag", "flagtransform", "texturequad", "flagdecal"):
            prefer.append(o)
        elif "flag" in stem and o.type == "MESH":
            prefer.append(o)
        stack.extend(list(o.children))
    for o in prefer:
        if o.type == "MESH":
            return o
    for o in prefer:
        for ch in o.children:
            if ch.type == "MESH":
                return ch
        return o
    # Material name heuristic
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.data:
            continue
        # Must be under root
        cur = o
        under = False
        while cur:
            if cur == root:
                under = True
                break
            cur = cur.parent
        if not under:
            continue
        for mat in o.data.materials:
            if not mat:
                continue
            mn = (mat.name or "").lower()
            if "flag" in mn:
                return o
    return None


def _configure_flag_image(img):
    try:
        img.alpha_mode = "STRAIGHT"
    except Exception:
        pass
    try:
        img.colorspace_settings.is_data = False
    except Exception:
        pass
    try:
        img.muimageprop.invertY = False
    except Exception:
        pass


def _unpack_loaded_image(src_img, stem, flip=False):
    """Copy pixels into a generated image with no source filepath."""
    try:
        w, h = int(src_img.size[0]), int(src_img.size[1])
    except Exception:
        return None
    if w < 1 or h < 1:
        return None
    name = ("mu_flag_%s" % stem)[:60]
    img = bpy.data.images.get(name)
    if img is not None:
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass
    img = bpy.data.images.new(name, width=w, height=h, alpha=True)
    try:
        img.pixels = list(src_img.pixels)
    except Exception:
        return None
    if flip:
        _flip_image_vertical(img)
    try:
        img.pack()
    except Exception:
        pass
    try:
        img["mu_flag_px"] = _DDS_PIXEL_REV if flip else 1
    except Exception:
        pass
    _configure_flag_image(img)
    return img


def load_flag_image(stem_or_path):
    """Load flag image by stem (from flags/) or absolute path."""
    path = stem_or_path
    stem = os.path.splitext(os.path.basename(stem_or_path))[0]
    if not os.path.isfile(path):
        for s, p in list_flag_files():
            if s.lower() == stem.lower() or s.lower() == str(stem_or_path).lower():
                path = p
                stem = s
                break
        else:
            return None
    img_name = f"mu_flag_{stem}"[:60]
    if str(path).lower().endswith(".dds"):
        existing = bpy.data.images.get(img_name)
        try:
            ready = (
                existing is not None
                and not (existing.filepath or "")
                and int(existing.get("mu_flag_px") or 0) == _DDS_PIXEL_REV
            )
        except Exception:
            ready = False
        if ready:
            _configure_flag_image(existing)
            return existing
        raw = None
        try:
            raw = bpy.data.images.load(path, check_existing=False)
            img = _unpack_loaded_image(raw, stem, flip=True)
        except Exception:
            img = None
        finally:
            if raw is not None:
                try:
                    bpy.data.images.remove(raw)
                except Exception:
                    pass
        return img
    if img_name in bpy.data.images:
        img = bpy.data.images[img_name]
        try:
            if os.path.normpath(img.filepath_from_user() or "") != os.path.normpath(path):
                img.filepath = path
                img.reload()
        except Exception:
            pass
        _configure_flag_image(img)
        return img
    try:
        img = bpy.data.images.load(path)
        img.name = img_name
        _configure_flag_image(img)
        return img
    except Exception:
        return None


def _set_maintex_image(mat, img):
    """Viewport-only: swap Image Texture node; leave mumatprop.tex for .mu export."""
    if mat is None or img is None:
        return False
    nt = getattr(mat, "node_tree", None)
    if not nt:
        return False
    node = nt.nodes.get("_MainTex")
    if node is None:
        for n in nt.nodes:
            if n.type == "TEX_IMAGE":
                node = n
                break
    if node is None:
        return False
    node.image = img
    try:
        scale = node.texture_mapping.scale
        if scale.y < 0:
            scale.y = abs(float(scale.y))
    except Exception:
        pass
    return True


def _resolve_flag_mesh(quad):
    """Return FlagDecal MESH object from quad empty/mesh, or None."""
    if quad is None:
        return None
    if quad.type == "MESH" and quad.data:
        return quad
    for ch in quad.children:
        if ch.type == "MESH" and ch.data:
            return ch
    return None


def _flag_targets(mesh_obj):
    """Objects to hide for No Flag (mesh + empty parent when parent is Flag*)."""
    if mesh_obj is None:
        return []
    out = [mesh_obj]
    parent = mesh_obj.parent
    if parent is not None and parent.type == "EMPTY":
        stem = _object_stem(parent.name).lower()
        if "flag" in stem:
            out.append(parent)
    return out


def _set_no_flag_hidden(mesh_obj, hide):
    """Hide/show FlagDecal for No Flag preview (viewport-only, export-safe).

    Uses ``hide_viewport`` so the quad disappears in the 3D View. Does **not**
    rely on ``hide_render`` alone: ``export_mu.empty.export_collection`` skips
    ``hide_render`` roots, which would drop the flag mesh from .mu. We keep
    ``hide_render`` False while No Flag is active; ``prepare_flag_for_export``
    also forces a temporary unhide before export as a safety net.
    """
    for obj in _flag_targets(mesh_obj):
        try:
            if hide:
                if not obj.get(MU_FLAG_NO_FLAG_HIDDEN):
                    obj[MU_FLAG_PREV_HIDE_VP] = int(bool(obj.hide_viewport))
                    obj[MU_FLAG_PREV_HIDE_RENDER] = int(bool(obj.hide_render))
                    obj[MU_FLAG_NO_FLAG_HIDDEN] = 1
                obj.hide_viewport = True
                # Keep exportable: do not leave hide_render True for No Flag.
                obj.hide_render = False
            else:
                if obj.get(MU_FLAG_NO_FLAG_HIDDEN):
                    prev_vp = bool(obj.get(MU_FLAG_PREV_HIDE_VP, 0))
                    prev_r = bool(obj.get(MU_FLAG_PREV_HIDE_RENDER, 0))
                    obj.hide_viewport = prev_vp
                    obj.hide_render = prev_r
                    for key in (
                        MU_FLAG_NO_FLAG_HIDDEN,
                        MU_FLAG_PREV_HIDE_VP,
                        MU_FLAG_PREV_HIDE_RENDER,
                    ):
                        if key in obj:
                            del obj[key]
                else:
                    obj.hide_viewport = False
                    obj.hide_render = False
        except Exception:
            pass


def prepare_flag_for_export(root):
    """Temporarily unhide No Flag preview so .mu keeps the FlagDecal mesh.

    Returns a restore token for ``finish_flag_export`` (list of objects that
    were unhidden), or None.
    """
    if root is None:
        return None
    restored = []
    stack = [root]
    while stack:
        o = stack.pop()
        if o.get(MU_FLAG_NO_FLAG_HIDDEN):
            try:
                o.hide_viewport = False
                o.hide_render = False
                restored.append(o)
            except Exception:
                pass
        stack.extend(list(o.children))
    return restored or None


def finish_flag_export(restore_token):
    """Re-hide FlagDecal objects after export if No Flag was active."""
    if not restore_token:
        return
    for o in restore_token:
        try:
            if o.get(MU_FLAG_NO_FLAG_HIDDEN):
                o.hide_viewport = True
                o.hide_render = False
        except Exception:
            pass


def apply_flag_texture(root, flag_stem, info=None):
    """Swap _MainTex on FlagDecal quad (viewport only; never mumatprop.tex).

    ``flag_stem`` NONE / No Flag hides the quad in the viewport (reversible).
    Real flag stems unhide and apply the preview image.
    """
    if root is None:
        return False
    info = info or {}
    try:
        raw = root.get(MU_FLAG_KEY)
        if raw and not info:
            info = json.loads(raw)
    except Exception:
        pass
    quad_name = (info or {}).get("textureQuadName")
    quad = find_flag_quad(root, quad_name)
    if quad is None:
        return False
    mesh_obj = _resolve_flag_mesh(quad)
    if mesh_obj is None:
        return False
    if not flag_stem or flag_stem == NO_FLAG:
        _set_no_flag_hidden(mesh_obj, True)
        try:
            root["mu_active_flag"] = NO_FLAG
            root[MU_FLAG_KEY] = json.dumps({
                "textureQuadName": quad_name or _object_stem(quad.name),
                "active": NO_FLAG,
            })
        except Exception:
            pass
        return True
    # Real flag: show again, then swap viewport image (not mumatprop).
    _set_no_flag_hidden(mesh_obj, False)
    img = load_flag_image(flag_stem)
    if img is None:
        return False
    ok = False
    for mat in mesh_obj.data.materials:
        if mat is None:
            continue
        if _set_maintex_image(mat, img):
            try:
                mat[MU_FLAG_PREVIEW] = 1
            except Exception:
                pass
            ok = True
    if ok:
        try:
            mesh_obj[MU_FLAG_PREVIEW] = 1
            root["mu_active_flag"] = flag_stem
            root[MU_FLAG_KEY] = json.dumps({
                "textureQuadName": quad_name or _object_stem(quad.name),
                "active": flag_stem,
            })
        except Exception:
            pass
    return ok


def attach_flag_preview(root, cfg_text, mudir=None):
    """Parse FlagDecal, sync flags, apply default.png (or first available)."""
    info = parse_flag_decal(cfg_text)
    if not info:
        return 0
    try:
        sync_flags_from_gamedata(mudir)
    except Exception:
        pass
    try:
        root[MU_FLAG_KEY] = json.dumps(info)
    except Exception:
        pass
    default = "default"
    stems = {s.lower(): s for s, _p in list_flag_files()}
    if default not in stems:
        default = next(iter(stems.values()), None) if stems else None
    else:
        default = stems[default]
    if default:
        apply_flag_texture(root, default, info)
        try:
            scene = bpy.context.scene
            if hasattr(scene, "mu_active_flag"):
                scene.mu_active_flag = default
        except Exception:
            pass
        return 1
    return 0


def find_flag_root(obj=None, context=None):
    """Walk up / search scene for object with mu_flag_decal."""
    if obj is None and context is not None:
        obj = getattr(context, "active_object", None)
    cur = obj
    while cur is not None:
        if cur.get(MU_FLAG_KEY):
            return cur
        cur = cur.parent
    for o in bpy.data.objects:
        if o.get(MU_FLAG_KEY):
            return o
    return None


def get_flag_enum_items(self, context):
    """Enum items for Scene.mu_active_flag with flag PNG thumbnails.

    Returns 5-tuples ``(id, name, desc, icon, index)`` so Blender shows
    ``preview.icon_id`` beside each name. ``No Flag`` uses built-in ``BLANK1``.
    """
    global _flag_enum_items_cache
    # Built-in icon name (string) for No Flag; custom icon_id (int) for flags.
    items = [
        (NO_FLAG, "No Flag", "No FlagDecal / clear preview", "BLANK1", 0),
    ]
    root = find_flag_root(
        getattr(context, "active_object", None) if context else None,
        context=context,
    )
    if root is None or not root.get(MU_FLAG_KEY):
        _flag_enum_items_cache = items
        return _flag_enum_items_cache
    idx = 1
    for stem, path in list_flag_files():
        icon = _flag_preview_icon_id(stem, path)
        if not icon:
            icon = "BLANK1"
        items.append((stem, stem, f"Flag texture {stem}", icon, idx))
        idx += 1
    if len(items) == 1:
        items.append(("default", "default", "Default flag", "BLANK1", 1))
    _flag_enum_items_cache = items
    return _flag_enum_items_cache
