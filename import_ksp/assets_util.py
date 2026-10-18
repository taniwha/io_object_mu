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
"""Bundled KSPedia assets (backgrounds + fonts), same idea as addon ``flags/``.

Background PNGs live in ``import_ksp/backgrounds/`` with ``manifest.json``
mapping squadcore sprite/texture path_ids to files.  Outline fonts live in
``import_ksp/fonts/``.  Resolution prefers these bundled files so users can
create/edit ``.ksp`` pages without a GameData install.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple


def addon_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def backgrounds_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "backgrounds")


def fonts_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def backgrounds_manifest_path():
    return os.path.join(backgrounds_dir(), "manifest.json")


def fonts_manifest_path():
    return os.path.join(fonts_dir(), "manifest.json")


_BG_MANIFEST = None
_BG_BY_SPRITE = None
_BG_BY_TEX = None
_BG_BY_NAME = None


def _load_bg_manifest():
    global _BG_MANIFEST, _BG_BY_SPRITE, _BG_BY_TEX, _BG_BY_NAME
    if _BG_MANIFEST is not None:
        return _BG_MANIFEST
    path = backgrounds_manifest_path()
    data = {"textures": [], "sprites": []}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    _BG_MANIFEST = data
    _BG_BY_SPRITE = {}
    _BG_BY_TEX = {}
    _BG_BY_NAME = {}
    # First pass: count how many sprites share each texture_path_id
    tid_counts = {}
    sprite_rows = []
    for s in data.get("sprites") or []:
        try:
            sid = int(s.get("sprite_path_id") or 0)
            tid = int(s.get("texture_path_id") or 0)
        except Exception:
            continue
        entry = {
            "name": s.get("name") or "",
            "file": s.get("file") or "",
            "sprite_path_id": sid,
            "texture_path_id": tid,
        }
        sprite_rows.append(entry)
        if tid:
            tid_counts[tid] = tid_counts.get(tid, 0) + 1
    for entry in sprite_rows:
        sid = int(entry["sprite_path_id"] or 0)
        tid = int(entry["texture_path_id"] or 0)
        if sid:
            _BG_BY_SPRITE[sid] = entry
        # Atlas-backed Black/White share one Texture2D — never map by tid
        if tid and tid_counts.get(tid, 0) == 1:
            _BG_BY_TEX[tid] = entry
        if entry["name"]:
            _BG_BY_NAME[entry["name"].lower()] = entry
    for t in data.get("textures") or []:
        name = (t.get("name") or "").lower()
        # Skip full atlas catalog entries — not a page background
        if "spriteatlas" in name:
            continue
        if name and name not in _BG_BY_NAME:
            try:
                tid = int(t.get("path_id") or 0)
            except Exception:
                tid = 0
            _BG_BY_NAME[name] = {
                "name": t.get("name") or "",
                "file": t.get("file") or "",
                "sprite_path_id": 0,
                "texture_path_id": tid,
            }
            if tid and tid not in _BG_BY_TEX and tid_counts.get(tid, 0) <= 1:
                if name not in ("backgroundblack", "backgroundwhite"):
                    _BG_BY_TEX.setdefault(tid, _BG_BY_NAME[name])
    return _BG_MANIFEST


def list_background_names() -> List[str]:
    _load_bg_manifest()
    return sorted({e["name"] for e in (_BG_BY_NAME or {}).values() if e.get("name")})


def resolve_background_file(
    *,
    sprite_path_id: int = 0,
    texture_path_id: int = 0,
    name: str = "",
) -> Optional[str]:
    """Return absolute PNG path for a squadcore Background* asset, or None."""
    _load_bg_manifest()
    entry = None
    if sprite_path_id and _BG_BY_SPRITE:
        entry = _BG_BY_SPRITE.get(int(sprite_path_id))
    if entry is None and texture_path_id and _BG_BY_TEX:
        entry = _BG_BY_TEX.get(int(texture_path_id))
    if entry is None and name and _BG_BY_NAME:
        entry = _BG_BY_NAME.get(str(name).lower())
    if not entry:
        return None
    fname = entry.get("file") or ""
    if not fname:
        return None
    path = os.path.join(backgrounds_dir(), fname)
    return path if os.path.isfile(path) else None


def load_background_png_bytes(
    *,
    sprite_path_id: int = 0,
    texture_path_id: int = 0,
    name: str = "",
) -> Tuple[Optional[bytes], str, int, int]:
    """Load bundled background PNG bytes.

    Returns ``(png_bytes_or_None, name, width_hint, height_hint)``.
    """
    path = resolve_background_file(
        sprite_path_id=sprite_path_id,
        texture_path_id=texture_path_id,
        name=name,
    )
    if not path:
        return None, "", 0, 0
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return None, "", 0, 0
    base = os.path.splitext(os.path.basename(path))[0]
    # Size hints from manifest
    _load_bg_manifest()
    w = h = 0
    for t in (_BG_MANIFEST or {}).get("textures") or []:
        if (t.get("file") or "") == os.path.basename(path):
            w = int(t.get("width") or 0)
            h = int(t.get("height") or 0)
            base = t.get("name") or base
            break
    return data, base, w, h


def bundled_sprite_tex_map() -> Dict[int, int]:
    """sprite_path_id → texture_path_id from the bundled backgrounds manifest."""
    _load_bg_manifest()
    out = {}
    for sid, entry in (_BG_BY_SPRITE or {}).items():
        tid = int(entry.get("texture_path_id") or 0)
        if sid and tid:
            out[int(sid)] = tid
    return out


def sync_backgrounds_from_squadcore(squadcore_path: str) -> int:
    """Optional re-extract of Background* PNGs from a squadcore.ksp path.

    Returns number of PNGs written.  Requires UnityPy + Pillow (same as import).
    Atlas-backed sprites (BackgroundBlack / BackgroundWhite) are cropped from
    the KSPedia sprite atlas when present instead of solid stand-ins.
    """
    if not squadcore_path or not os.path.isfile(squadcore_path):
        return 0
    try:
        from .deps import ensure_unitypy
        if not ensure_unitypy(False):
            return 0
        import UnityPy
        from PIL import Image
    except Exception:
        return 0
    dest = backgrounds_dir()
    os.makedirs(dest, exist_ok=True)
    env = UnityPy.load(squadcore_path)
    written = 0
    textures = {}
    sprites = []
    atlas_images = {}  # path_id -> PIL Image
    # Collect Background textures + atlas used by Background* sprites
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ""
        except Exception:
            continue
        img = getattr(data, "image", None)
        if img is None:
            continue
        if name.startswith("Background"):
            fname = name.replace(" ", "_") + ".png"
            out = os.path.join(dest, fname)
            try:
                img.save(out)
                written += 1
            except Exception:
                continue
            textures[int(obj.path_id)] = {
                "name": name,
                "file": fname,
                "path_id": int(obj.path_id),
                "width": int(getattr(data, "m_Width", 0) or 0),
                "height": int(getattr(data, "m_Height", 0) or 0),
                "bytes": os.path.getsize(out) if os.path.isfile(out) else 0,
            }
        elif "SpriteAtlas" in name or "KSPedia" in name:
            try:
                atlas_images[int(obj.path_id)] = img.copy()
            except Exception:
                pass
            # Also keep atlas on disk for offline crops
            safe = name.replace(" ", "_") + ".png"
            try:
                out = os.path.join(dest, safe)
                if not os.path.isfile(out):
                    img.save(out)
                    written += 1
            except Exception:
                pass
    # Sprite map + atlas crops for Black/White
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ""
            tree = obj.read_typetree()
        except Exception:
            continue
        if "Background" not in name:
            continue
        rd = {}
        if isinstance(tree, dict):
            rd = tree.get("m_RD") or tree.get("m_RenderData") or {}
        tex = None
        if isinstance(rd, dict):
            tex = rd.get("texture") or rd.get("m_Texture")
        tid = 0
        if isinstance(tex, dict):
            tid = int(tex.get("m_PathID") or 0)
        entry_tex = textures.get(tid)
        fname = entry_tex["file"] if entry_tex else (name.replace(" ", "_") + ".png")
        # Crop from atlas when sprite points at atlas texture
        if tid in atlas_images and isinstance(rd, dict):
            rect = rd.get("textureRect") or rd.get("m_TextureRect") or {}
            try:
                ax = float(rect.get("x", 0) or 0)
                ay = float(rect.get("y", 0) or 0)
                aw = float(rect.get("width", 0) or 0)
                ah = float(rect.get("height", 0) or 0)
            except Exception:
                ax = ay = aw = ah = 0.0
            if aw > 0 and ah > 0:
                atlas = atlas_images[tid]
                atw, ath = atlas.size
                # Unity bottom-left → PIL top-left
                top = int(ath - (ay + ah))
                left = int(ax)
                crop = atlas.crop((left, top, int(ax + aw), int(top + ah)))
                fname = name.replace(" ", "_") + ".png"
                out = os.path.join(dest, fname)
                try:
                    crop.save(out)
                    written += 1
                except Exception:
                    pass
                textures[int(obj.path_id)] = {
                    "name": name,
                    "file": fname,
                    "path_id": int(obj.path_id),
                    "width": int(aw),
                    "height": int(ah),
                    "bytes": os.path.getsize(out) if os.path.isfile(out) else 0,
                }
                # Keep atlas tid on sprite entry for resolve
                entry_tex = None
        sprites.append({
            "name": name,
            "sprite_path_id": int(obj.path_id),
            "texture_path_id": tid,
            "file": fname,
        })
        # Ensure a texture catalog entry for cropped atlas sprites
        if name in ("BackgroundBlack", "BackgroundWhite") and name not in {
            t.get("name") for t in textures.values() if isinstance(t, dict)
        }:
            out = os.path.join(dest, fname)
            if os.path.isfile(out):
                textures[int(obj.path_id)] = {
                    "name": name,
                    "file": fname,
                    "path_id": int(obj.path_id),
                    "width": 1024,
                    "height": 768,
                    "bytes": os.path.getsize(out),
                }
    # Prefer named texture entries for Black/White crops
    tex_list = []
    seen_names = set()
    for t in textures.values():
        n = t.get("name") or ""
        if n in seen_names:
            continue
        seen_names.add(n)
        tex_list.append(t)
    manifest = {
        "source": os.path.abspath(squadcore_path),
        "textures": tex_list,
        "sprites": sprites,
    }
    with open(backgrounds_manifest_path(), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    global _BG_MANIFEST, _BG_BY_SPRITE, _BG_BY_TEX, _BG_BY_NAME
    _BG_MANIFEST = None
    _BG_BY_SPRITE = _BG_BY_TEX = _BG_BY_NAME = None
    return written