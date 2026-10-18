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
"""TMP Font Asset FaceInfo → Blender FONT size (universal, not page-calib).

Stock KSPedia has no CanvasScaler (canvas_scale=1).  curve.size is derived
from m_fontSize and SDF FaceInfo (CapHeight/PointSize/Scale), with one
CAP_SIZE_FACTOR per outline role (sans/display/lcd/cjk).
"""

from __future__ import annotations

import json
import os

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

_FACEINFO_FALLBACK = {
    "sans": {
        "PointSize": 68.0, "Scale": 0.92, "CapHeight": 48.5625,
        "LineHeight": 92.625, "Ascender": 72.6875, "Padding": 8.0,
        "Name": "Noto Sans",
    },
    # Windows Arial outline stand-in for classic UI.Text Arial.
    "arial": {
        "PointSize": 72.0, "Scale": 1.0, "CapHeight": 51.0,
        "LineHeight": 86.0, "Ascender": 72.0, "Padding": 5.0,
        "Name": "Arial",
    },
    # PBS / PlanetaryBaseInc body (OpenSans-* embedded in the .ksp).
    "opensans": {
        "PointSize": 72.0, "Scale": 1.0, "CapHeight": 50.0,
        "LineHeight": 86.0, "Ascender": 72.0, "Padding": 5.0,
        "Name": "Open Sans",
    },
    "display": {
        "PointSize": 72.0, "Scale": 1.0, "CapHeight": 52.0,
        "LineHeight": 90.0, "Ascender": 70.0, "Padding": 8.0,
        "Name": "Amaranth",
    },
    "lcd": {
        "PointSize": 64.0, "Scale": 1.0, "CapHeight": 46.0,
        "LineHeight": 80.0, "Ascender": 60.0, "Padding": 6.0,
        "Name": "JD LCD",
    },
    "cjk": {
        "PointSize": 68.0, "Scale": 0.92, "CapHeight": 48.5625,
        "LineHeight": 92.625, "Ascender": 72.6875, "Padding": 8.0,
        "Name": "Noto Sans CJK",
    },
}

# Calibrated so outline size matches former empiric TMP scales:
#   sans:    1.58 / (Scale * CapHeight/PointSize)  → ~2.405
#   Slightly tightened (−1.5%) vs early FaceInfo so long body lines
#   don't outrun JPG glyphs left→right on experience / tables.
#   display: 1.15 / (Scale * CapHeight/PointSize)  (Amaranth titles)
#   arial / opensans: UI.Text outline stand-ins (PBS uses OpenSans).
# Over-large display factor wraps KSPedia section titles in Blender FONT.
_CAP_SIZE_FACTOR = {
    # ~2.405 matched empiric body 1.58; tightened so near-miss one-liners
    # (facilities-ac "EVA allowed") stay on one line with bold outline.
    "sans": 2.35,
    # Arial UI.Text: slightly smaller than Noto stand-in so OCR x-drift
    # on PBS Configuration/Corridors stays within soft tol.
    "arial": 2.12,
    # OpenSans UI.Text — 2.02 widened wraps/OCR; 1.98 was 8×HARD.
    "opensans": 1.98,
    "display": 1.593,
    "lcd": 2.30,
    "cjk": 2.35,
}

# Amaranth outline vs Unity UI.Text raster (section ``…:`` headers).
# ConfHeader (is_title) uses TMP_TITLE_X_SCALE for the blue page title.
_DISPLAY_X_SCALE = 1.0
# Prefer CHAR_SPACING_MUL for PBS body width; obj.scale desyncs figure-space overlays.
_OPENSANS_X_SCALE = 1.0
_FACEINFO_CACHE = None


def _tmp_family_role(font_family):
    try:
        from .fonts_util import tmp_family_role
        return tmp_family_role(font_family) or "sans"
    except Exception:
        fam = (font_family or "").lower()
        if "arial" in fam or "liberation" in fam:
            return "arial"
        if "opensans" in fam or "open sans" in fam:
            return "opensans"
        if "amaranth" in fam:
            return "display"
        if "lcd" in fam:
            return "lcd"
        if "cjk" in fam:
            return "cjk"
        return "sans"


def _load_bundled_faceinfo_json():
    global _FACEINFO_CACHE
    if _FACEINFO_CACHE is not None:
        return _FACEINFO_CACHE
    _FACEINFO_CACHE = {}
    try:
        for name in os.listdir(_FONTS_DIR):
            if not name.endswith("_SDF_tmp.json"):
                continue
            path = os.path.join(_FONTS_DIR, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            fi = data.get("m_fontInfo") or data.get("m_faceInfo") or {}
            if not isinstance(fi, dict) or not fi:
                continue
            fam = (fi.get("Name") or data.get("m_Name") or name).lower()
            role = "sans"
            if "arial" in fam:
                role = "arial"
            elif "amaranth" in fam:
                role = "display"
            elif "lcd" in fam:
                role = "lcd"
            elif "cjk" in fam:
                role = "cjk"
            _FACEINFO_CACHE[role] = {
                "PointSize": float(fi.get("PointSize") or 68.0),
                "Scale": float(fi.get("Scale") or 1.0),
                "CapHeight": float(fi.get("CapHeight") or 48.0),
                "LineHeight": float(fi.get("LineHeight") or 92.0),
                "Ascender": float(fi.get("Ascender") or 72.0),
                "Padding": float(fi.get("Padding") or 8.0),
                "Name": fi.get("Name") or data.get("m_Name") or "",
            }
    except Exception:
        pass
    return _FACEINFO_CACHE


def faceinfo_for_family(font_family=""):
    role = _tmp_family_role(font_family)
    cache = _load_bundled_faceinfo_json()
    if role in cache:
        return dict(cache[role])
    fam = (font_family or "").lower()
    for info in cache.values():
        n = (info.get("Name") or "").lower()
        if fam and n and (fam in n or n in fam):
            return dict(info)
    return dict(_FACEINFO_FALLBACK.get(role) or _FACEINFO_FALLBACK["sans"])


def tmp_font_size_universal(font_size, pixel_scale=0.001, font_family="",
                            canvas_scale=1.0):
    """Map Unity TMP m_fontSize (px) → Blender curve.size via FaceInfo."""
    fs = max(float(font_size), 1.0)
    sx = float(pixel_scale)
    cs = float(canvas_scale) if canvas_scale else 1.0
    role = _tmp_family_role(font_family)
    fi = faceinfo_for_family(font_family)
    pt = max(float(fi.get("PointSize") or 68.0), 1e-6)
    scale = float(fi.get("Scale") or 1.0)
    cap = float(fi.get("CapHeight") or (pt * 0.7))
    factor = float(_CAP_SIZE_FACTOR.get(role) or _CAP_SIZE_FACTOR["sans"])
    size = fs * scale * (cap / pt) * cs * sx * factor
    return max(size, 1e-4)


def tmp_line_em_ratio(font_family=""):
    fi = faceinfo_for_family(font_family)
    pt = max(float(fi.get("PointSize") or 68.0), 1e-6)
    lh = float(fi.get("LineHeight") or (pt * 1.2))
    return max(lh / pt, 0.5)


def tmp_padding_px(font_size, font_family=""):
    fi = faceinfo_for_family(font_family)
    pt = max(float(fi.get("PointSize") or 68.0), 1e-6)
    pad = float(fi.get("Padding") or 0.0)
    return float(font_size) * (pad / pt)


def display_x_scale(font_family=""):
    role = _tmp_family_role(font_family)
    if role == "display":
        return float(_DISPLAY_X_SCALE)
    if role == "opensans":
        return float(_OPENSANS_X_SCALE)
    return 1.0


def outline_x_scale(font_family=""):
    """Horizontal condensation for outline stand-ins (applied to obj.scale.x)."""
    return float(display_x_scale(font_family))


def ascender_snap_extra_bu(font_size, pixel_scale=0.001, font_family=""):
    """Engine quirk: Blender TOP sits low vs Unity; scale with Ascender/PointSize."""
    fi = faceinfo_for_family(font_family)
    pt = max(float(fi.get("PointSize") or 68.0), 1e-6)
    asc = float(fi.get("Ascender") or pt)
    # Former hardcode 0.006 BU ≈ 6 px @ 0.001; scale mildly with font size.
    # Body (< title threshold) used to overshoot ~5–8 px high vs JPG.
    base = 0.006 * (float(font_size) / 40.0) * (asc / pt) / 1.07
    if float(font_size) < 60.0:
        # Body TOP snap: Noto 0.55·former; PBS OpenSans/Arial still sat
        # ~6–10 px high vs screenshot after bg align — no upward boost.
        role = _tmp_family_role(font_family)
        if role in ("arial", "opensans"):
            body_mul = 0.0
        elif role == "display":
            # UI.Text Amaranth section headers (no SDF) — mild lift only.
            body_mul = 0.20
        else:
            body_mul = 0.55
        base *= body_mul
        return max(base, 0.0) * (float(pixel_scale) / 0.001)
    return max(base, 0.002) * (float(pixel_scale) / 0.001)
