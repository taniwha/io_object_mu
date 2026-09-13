# vim:ts=4:et
# <pep8 compliant>
"""Resolve GameData dependencies for .mu import (textures + nested CFG refs).

Scans the .mu texture table and sibling/parent part .cfg (MODEL / texture /
mainTextureURL) then loads missing images from GameData when files exist
elsewhere. Nested .mu MODEL refs are reported but not yet inlined.
"""

from __future__ import annotations

import os
import re

import bpy

from .textures import load_image

_TEX_EXTS = (".dds", ".mbm", ".tga", ".png")


def game_data_root(path):
    cur = os.path.abspath(path or "")
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    while cur and os.path.dirname(cur) != cur:
        if os.path.basename(cur).lower() == "gamedata":
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _find_part_cfg(mudir, muname):
    if not mudir:
        return None
    stem = re.sub(r"_temp(?:_\d+)?$", "", muname or "")
    candidates = []
    parent = os.path.dirname(mudir)
    for folder in (mudir, parent, os.path.dirname(parent)):
        if not folder or not os.path.isdir(folder):
            continue
        for name in (f"{stem}.cfg", f"{os.path.basename(mudir)}.cfg"):
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                candidates.append(p)
        try:
            for fn in os.listdir(folder):
                if fn.lower().endswith(".cfg"):
                    p = os.path.join(folder, fn)
                    if p not in candidates:
                        candidates.append(p)
        except Exception:
            pass
    want = (stem or "").lower()
    for p in candidates:
        try:
            text = open(p, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        base = os.path.splitext(os.path.basename(p))[0].lower()
        if want and (want in text.lower() or base == want):
            return p
    return candidates[0] if candidates else None


def _iter_cfg_urls(cfg_text):
    if not cfg_text:
        return
    patterns = (
        r"^\s*model\s*=\s*(.+)$",
        r"^\s*texture\s*=\s*(.+)$",
        r"^\s*mainTextureURL\s*=\s*(.+)$",
        r"^\s*normalTextureURL\s*=\s*(.+)$",
        r"^\s*textureURL\s*=\s*(.+)$",
    )
    for pat in patterns:
        for m in re.finditer(pat, cfg_text, re.M | re.I):
            raw = m.group(1).strip().strip('"').split("//")[0].strip()
            if not raw:
                continue
            if "," in raw and "texture" in pat.lower():
                parts = [x.strip() for x in raw.split(",")]
                if len(parts) >= 2:
                    raw = parts[-1]
            yield raw.replace("\\", "/")


def resolve_url_file(gd_root, mudir, url):
    if not url:
        return None
    url = url.replace("\\", "/").strip()
    base_url, ext = os.path.splitext(url)
    exts = [ext] if ext.lower() in _TEX_EXTS else list(_TEX_EXTS)
    if ext and ext.lower() not in _TEX_EXTS:
        base_url = url
        exts = list(_TEX_EXTS)
    candidates = []
    if gd_root:
        for e in exts:
            candidates.append(os.path.join(gd_root, *base_url.split("/")) + e)
    leaf = base_url.split("/")[-1]
    if mudir:
        cur = mudir
        for _ in range(5):
            for e in exts:
                candidates.append(os.path.join(cur, leaf + e))
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    if gd_root and (not ext or ext.lower() == ".mu"):
        mu_path = os.path.join(gd_root, *url.split("/"))
        if not mu_path.lower().endswith(".mu"):
            mu_path = mu_path + ".mu"
        if os.path.isfile(mu_path):
            return mu_path
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _find_under_gamedata(gd_root, base):
    cache = getattr(_find_under_gamedata, "_cache", None)
    if cache is None:
        cache = {}
        _find_under_gamedata._cache = cache
    key = (gd_root, base.lower())
    if key in cache:
        return cache[key]
    found = None
    want = base.lower()
    try:
        for root, _dirs, files in os.walk(gd_root):
            for fn in files:
                b, e = os.path.splitext(fn)
                if b.lower() == want and e.lower() in _TEX_EXTS:
                    found = os.path.join(root, fn)
                    break
            if found:
                break
    except Exception:
        found = None
    cache[key] = found
    return found


def preload_missing_textures(mu, mudir, gd_root=None):
    gd_root = gd_root or game_data_root(mudir)
    loaded = 0
    for tex in getattr(mu, "textures", None) or []:
        name = getattr(tex, "name", None) or ""
        base, _ext = os.path.splitext(name)
        if not base or base in bpy.data.images:
            continue
        local_hit = False
        for e in _TEX_EXTS:
            if mudir and os.path.isfile(os.path.join(mudir, base + e)):
                local_hit = True
                break
        if local_hit:
            continue
        path = resolve_url_file(gd_root, mudir, base)
        if not path and gd_root:
            path = _find_under_gamedata(gd_root, base)
        if not path:
            continue
        folder, filename = os.path.split(path)
        b2, e2 = os.path.splitext(filename)
        try:
            resolved = load_image(b2, e2, folder, getattr(tex, "type", 0))
            if resolved is not False:
                tex.type = resolved
                if (b2 != base and base not in bpy.data.images
                        and b2 in bpy.data.images):
                    try:
                        bpy.data.images[b2].name = base
                    except Exception:
                        pass
                loaded += 1
        except Exception as e:
            print(f"WARNING: dependency texture load {base}: {e}")
    return loaded


def preload_cfg_dependencies(mudir, muname, gd_root=None):
    gd_root = gd_root or game_data_root(mudir)
    cfg = _find_part_cfg(mudir, muname)
    if not cfg:
        return {"cfg": None, "textures": 0, "models": []}
    try:
        text = open(cfg, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return {"cfg": cfg, "textures": 0, "models": []}
    loaded = 0
    models = []
    for url in _iter_cfg_urls(text):
        path = resolve_url_file(gd_root, mudir, url)
        if not path:
            leaf = url.split("/")[-1]
            base, ext = os.path.splitext(leaf)
            if gd_root and (not ext or ext.lower() in _TEX_EXTS):
                path = _find_under_gamedata(gd_root, base)
        if not path:
            continue
        if path.lower().endswith(".mu"):
            models.append(path)
            continue
        base, ext = os.path.splitext(os.path.basename(path))
        if base in bpy.data.images:
            continue
        try:
            if load_image(base, ext, os.path.dirname(path), 0) is not False:
                loaded += 1
        except Exception as e:
            print(f"WARNING: cfg dep texture {url}: {e}")
    return {"cfg": cfg, "textures": loaded, "models": models}


def resolve_import_dependencies(mu, mudir):
    gd = game_data_root(mudir)
    n_mu = preload_missing_textures(mu, mudir, gd)
    muname = getattr(mu, "name", None) or ""
    info = preload_cfg_dependencies(mudir, muname, gd)
    n_cfg = int(info.get("textures") or 0)
    models = info.get("models") or []
    if n_mu or n_cfg or models:
        print(
            f"INFO: dependency resolve: mu_tex={n_mu} cfg_tex={n_cfg} "
            f"nested_mu={len(models)} cfg={info.get('cfg')!r}"
        )
        for m in models[:8]:
            print(f"INFO: dependency nested model (not inlined): {m}")
    return {"mu_textures": n_mu, "cfg_textures": n_cfg, "models": models}