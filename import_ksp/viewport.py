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
"""Viewport helpers for KSPedia UI preview in Blender.

Preview approximates Unity TMP SDF layout in Blender FONT curves.
Export writes Unity typetree fields only (not Blender curve metrics).
"""

from __future__ import annotations

import io
import os
import re

import bpy
from mathutils import Vector


DEFAULT_PIXEL_SCALE = 0.001

# =============================================================================
# TMP → Blender *glyph* coefficients (tracking, wrap, in-rect BLOCK_NUDGE).
# FaceInfo size math: fonts_faceinfo.py. Outliner un-nest is locale_switch
# (bake loc/rot/scale); these knobs cannot fold into object.location.
# =============================================================================

# --- Universal (shared) ---
TMP_USE_FACEINFO_SCALE = True
# Legacy empiric scales: FALLBACK only when FaceInfo path fails.
TMP_FONT_SIZE_SCALE = 1.15
TMP_FONT_SIZE_SCALE_BODY = 1.58
TMP_FONT_SIZE_SCALE_NOTE = 1.68
TMP_TITLE_X_SCALE = 1.040  # Action Sets short; engines title already a touch wide
TMP_FONT_CELL_HEIGHT_FIT = 1.18
# Tall multi-line shrink (content_h/n_lines) only for near-square panels
# (EVA/applauncher aspect ~1.5–7). Landscape body (KerbNet ~13–20) keeps
# FaceInfo size so same m_fontSize ⇒ same curve.size. Gate is dimensionless:
# aspect = box_w/content_h  vs  FaceInfo line_em × this mul (sans ~1.36×6 ≈ 8.2).
TMP_TALL_CLAMP_MAX_ASPECT_LINE_EM = 6.0
TMP_SHORT_LABEL_WRAP_BONUS_PX = 18.0
# Outline Noto is a hair wider than TMP SDF — keep this much wrap slack even
# on explicit-\\n blocks (AC Career Limits: bold "EVA allowed" was ~1 px over).
# Engines/SSTO / intakes: gen wrapped 1 line early (ref 2 → gen 3).
TMP_WRAP_SLACK_PX = 14.000
# Extra advance after bold/colored rich runs (outline Bold wider than measure).
TMP_RICH_RUN_PAD_PX = 2.0
TMP_CELL_FACE_PAD_PX = 3.0
TMP_TABLE_COL_WIDTH_BONUS_PX = 8.0
TMP_TOP_ASCENDER_SNAP = True
TMP_SPLIT_BLANK_LINE_PARAS = False
# One FONT per Unity element. Color/size runs stay in TMP markup (export).
TMP_SPLIT_RICH_RUNS = False
TMP_SPLIT_TABLE_ROWS = False
TMP_PARAGRAPH_GAP_EM = 0.0  # 0 → FaceInfo; else * font_size
TMP_PARAGRAPH_GAP_LINE_MUL = 1.55
TMP_TABLE_ROW_PITCH_PX = 0.0
TMP_TABLE_COL_NUDGE_Y_PX = 0.0
TMP_TEXT_NUDGE_PX = {}  # optional; KSP_CALIB_NUDGES=1
TMP_TABLE_HEADER_LABELS = frozenset()
TMP_NOTE_NUDGE_X_PX = 0.0
TMP_NOTE_NUDGE_Y_PX = 0.0
TMP_BODY_BLOCK_NUDGE_Y_PX = 0.0
TMP_INTRO_PARAGRAPH_GAP_PX = 0.0
TMP_INTRO_EACH_RECT_Y_PX = 0.0
TMP_TABLE_ROW_COUNT = 0.0
TMP_FONT_TITLE_MIN_PX = 60.0
TMP_TABLE_HEADER_CELL_FIT = TMP_FONT_CELL_HEIGHT_FIT
TMP_TABLE_HEADER_SIZE_MUL = 1.0
TMP_TABLE_HEADER_WRAP_BONUS_PX = 12.0

# --- Per-font profiles ---
# "ksp"      = stock KSPedia (Noto Sans / JD LCD outline stand-ins)
# "arial"    = classic UI.Text Arial pages
# "opensans" = PlanetaryBaseInc UI.Text (OpenSans-* Font assets)
# "amaranth" = PlanetaryBaseInc UI.Text Amaranth titles/headers
# Add new keys here for future faces; resolve via font_layout_profile().
FONT_LAYOUT_PROFILES = {
    "ksp": {
        # Stock KSPedia (Noto body + Amaranth-SDF titles). No role table.
        "LEAD_SPACE_SCALE": 1.0,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        # ConfB1 ``\\n…\\n    true``: half-glyph lift after full line drop.
        "LEAD_NL_MULTILINE_NUDGE": 0.5,
        "COLON_LABEL_NUDGE_X_PX": 16.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.55,
        # Intakes/lift/engines: gen leading opens vs ref (~+line by L3).
        "BODY_LINE_SPACING_MUL": 0.905,
        # 0 → fonts_faceinfo.ascender_snap_extra_bu
        "TOP_EXTRA_NUDGE_BU": 0.0,
        # Engines/intakes/lift: gen ~+2–4 px right of ref.
        "BLOCK_NUDGE_X_PX": 0.750,
        # Same set: gen ~3–6 px low.
        "BLOCK_NUDGE_Y_PX": 12.000,
        # Jet Engines title low+right; Action Sets was low.
        "TITLE_BLOCK_NUDGE_Y_PX": 7.000,
        "CHAR_SPACING_MUL": 1.0,
        # 0.95 caused early wrap (engines 2→3 lines); intakes width_d ~+14.
        "CHAR_SPACING_EXTRA_PX": 0.700,
        # Mild title tracking (Action Sets) without oversizing Jet titles.
        "TITLE_CHAR_SPACING_EXTRA_PX": 0.500,
        # 0.850 overshot; attachments (intakes/lift) still a hair wide at 0.965.
        "WORD_SPACING_MUL": 0.950,
    },
    "arial": {
        # Unity UI.Text Arial pads tighter than Blender Arial outline.
        "LEAD_SPACE_SCALE": 0.68,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        "LEAD_NL_MULTILINE_NUDGE": 0.5,
        "COLON_LABEL_NUDGE_X_PX": 16.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.55,
        # PBS pages liked a touch more leading than stock KSP.
        "BODY_LINE_SPACING_MUL": 1.08,
        "TOP_EXTRA_NUDGE_BU": 0.0,
        "BLOCK_NUDGE_X_PX": 0.0,
        "BLOCK_NUDGE_Y_PX": 0.0,
        # Pin to 0 — must not inherit stock-KSP TITLE/EXTRA knobs.
        "TITLE_BLOCK_NUDGE_Y_PX": 0.0,
        "CHAR_SPACING_MUL": 1.0,
        "CHAR_SPACING_EXTRA_PX": 0.0,
        "WORD_SPACING_MUL": 1.0,
    },
    # PBS OpenSans — family defaults only. Per-block layout is FONT_ROLE_LAYOUT
    # (role table, no page IDs). Snapshot: import_ksp/_baseline/viewport.py.
    "opensans": {
        "LEAD_SPACE_SCALE": 0.92,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        "LEAD_NL_MULTILINE_NUDGE": 0.0,
        "COLON_LABEL_NUDGE_X_PX": 16.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.75,
        "BODY_LINE_SPACING_MUL": 0.990,
        "TOP_EXTRA_NUDGE_BU": -0.008,
        "BLOCK_NUDGE_X_PX": 0.5,
        "BLOCK_NUDGE_Y_PX": 3.1,
        "TITLE_BLOCK_NUDGE_Y_PX": 0.0,
        "CHAR_SPACING_MUL": 0.958,
        # ~−1 canvas px word gap vs 0.972 (body under headers).
        "WORD_SPACING_MUL": 0.957,
        "CHAR_SPACING_EXTRA_PX": 0.0,
        "ITALIC_CHAR_SPACING_MUL": 0.985,
        # Body wrap: start from 7.
        "WRAP_BONUS_PX": 7.0,
        # Pull at most this many Unity px to keep one more word on L1.
        "WRAP_PULL_MAX_PX": 6.0,
        # Narrow OpenSans columns (Configuration callouts) — Unity px.
        "CALLOUT_BOX_MAX_PX": 620.0,
        "CALLOUT_MID_BOX_MAX_PX": 900.0,
    },
    # PBS Amaranth — family defaults; roles in FONT_ROLE_LAYOUT["amaranth"].
    "amaranth": {
        "LEAD_SPACE_SCALE": 1.0,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        "LEAD_NL_MULTILINE_NUDGE": 0.0,
        "COLON_LABEL_NUDGE_X_PX": 0.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.55,
        "BODY_LINE_SPACING_MUL": 1.0,
        "TOP_EXTRA_NUDGE_BU": -0.006,
        "BLOCK_NUDGE_X_PX": 6.0,
        "BLOCK_NUDGE_Y_PX": 9.5,
        "CHAR_SPACING_MUL": 1.000,
        "CHAR_SPACING_EXTRA_PX": 0.0,
        "WORD_SPACING_MUL": 1.000,
    },
    # CJK stand-in outline (Noto Sans CJK / YaHei). Wider glyphs than Latin
    # OpenSans — keep tracking near 1.0 and let fit_text_object_to_box shrink.
    "cjk": {
        "LEAD_SPACE_SCALE": 1.0,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        "LEAD_NL_MULTILINE_NUDGE": 0.0,
        "COLON_LABEL_NUDGE_X_PX": 8.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.7,
        "BODY_LINE_SPACING_MUL": 1.02,
        "TOP_EXTRA_NUDGE_BU": -0.004,
        "BLOCK_NUDGE_X_PX": 0.0,
        "BLOCK_NUDGE_Y_PX": 2.0,
        "CHAR_SPACING_MUL": 1.0,
        "CHAR_SPACING_EXTRA_PX": 0.0,
        "WORD_SPACING_MUL": 1.0,
        "WRAP_BONUS_PX": 4.0,
    },
}

# Role table (PBS OpenSans / Amaranth UI.Text only). Stock KSP has no roles.
FONT_ROLE_LAYOUT = {
    "opensans": {
        "body": {
            "CHAR_SPACING_MUL": 0.958,
            "WORD_SPACING_MUL": 0.957,
            "BODY_LINE_SPACING_MUL": 0.990,
            "WRAP_BONUS_PX": 3.5,
            "BLOCK_NUDGE_X_PX": 0.5,
            "BLOCK_NUDGE_Y_PX": 3.1,
        },
        "intro": {
            "CHAR_SPACING_MUL": 0.958,
            "WORD_SPACING_MUL": 0.957,
            "BODY_LINE_SPACING_MUL": 0.990,
            "WRAP_BONUS_PX": None,
            "BLOCK_NUDGE_X_PX": 0.0,
            "BLOCK_NUDGE_Y_PX": 0.0,
        },
        "callout": {
            "CHAR_SPACING_MUL": 0.955,
            "WORD_SPACING_MUL": 0.953,
            "BODY_LINE_SPACING_MUL": 0.990,
            "WRAP_BONUS_PX": 7.0,
            "BLOCK_NUDGE_X_PX": 3.0,
            "BLOCK_NUDGE_Y_PX": 2.5,
        },
        "callout_quote": {
            "CHAR_SPACING_MUL": 0.960,
            "WORD_SPACING_MUL": 0.958,
            "BODY_LINE_SPACING_MUL": 0.990,
            "WRAP_BONUS_PX": 7.0,
            "BLOCK_NUDGE_X_PX": -3.6,
            "BLOCK_NUDGE_Y_PX": 2.5,
        },
        "callout_code": {
            "CHAR_SPACING_MUL": 0.950,
            "WORD_SPACING_MUL": 0.947,
            "BODY_LINE_SPACING_MUL": 0.990,
            "WRAP_BONUS_PX": 7.0,
            "BLOCK_NUDGE_X_PX": 3.4,
            "BLOCK_NUDGE_Y_PX": 2.5,
        },
        "short_followup": {
            "CHAR_SPACING_MUL": 0.958,
            "WORD_SPACING_MUL": 0.957,
            "BODY_LINE_SPACING_MUL": 0.990,
            "WRAP_BONUS_PX": 7.0,
            "BLOCK_NUDGE_X_PX": -2.0,
            "BLOCK_NUDGE_Y_PX": 6.0,
            "SHORT_FOLLOWUP_GAP_MUL": 0.75,
        },
        "label_overlay": {
            "CHAR_SPACING_MUL": 0.958,
            "WORD_SPACING_MUL": 0.957,
            "BODY_LINE_SPACING_MUL": 0.958,
            "WRAP_BONUS_PX": 7.0,
            "BLOCK_NUDGE_X_PX": -11.0,
            "BLOCK_NUDGE_Y_PX": 6.7,
        },
    },
    "amaranth": {
        "title": {
            "CHAR_SPACING_MUL": 1.035,
            "WORD_SPACING_MUL": 1.0,
            "BLOCK_NUDGE_X_PX": -22.0,
            "BLOCK_NUDGE_Y_PX": 12.0,
        },
        "tagline": {
            "CHAR_SPACING_MUL": 1.0,
            "WORD_SPACING_MUL": 1.0,
            "BLOCK_NUDGE_X_PX": 0.0,
            "BLOCK_NUDGE_Y_PX": 5.0,
        },
        "colon_header": {
            "CHAR_SPACING_MUL": 1.0,
            "WORD_SPACING_MUL": 1.0,
            "BLOCK_NUDGE_X_PX": 1.5,
            "BLOCK_NUDGE_Y_PX": 4.0,
        },
        "section_label": {
            "CHAR_SPACING_MUL": 1.0,
            "WORD_SPACING_MUL": 1.0,
            "BLOCK_NUDGE_X_PX": 1.5,
            "BLOCK_NUDGE_Y_PX": 6.0,
        },
    },
}

# Back-compat module aliases → KSP profile (callers should prefer font_layout_get).
TMP_LEAD_SPACE_SCALE = FONT_LAYOUT_PROFILES["ksp"]["LEAD_SPACE_SCALE"]
TMP_LEAD_SPACE_SCALE_MIN_SP = FONT_LAYOUT_PROFILES["ksp"]["LEAD_SPACE_SCALE_MIN_SP"]
TMP_LEAD_NL_MULTILINE_NUDGE = FONT_LAYOUT_PROFILES["ksp"]["LEAD_NL_MULTILINE_NUDGE"]
TMP_COLON_LABEL_NUDGE_X_PX = FONT_LAYOUT_PROFILES["ksp"]["COLON_LABEL_NUDGE_X_PX"]
TMP_SHORT_FOLLOWUP_GAP_MUL = FONT_LAYOUT_PROFILES["ksp"]["SHORT_FOLLOWUP_GAP_MUL"]
TMP_BODY_LINE_SPACING_MUL = FONT_LAYOUT_PROFILES["ksp"]["BODY_LINE_SPACING_MUL"]
TMP_TOP_EXTRA_NUDGE_BU = FONT_LAYOUT_PROFILES["ksp"]["TOP_EXTRA_NUDGE_BU"]

# Optional override for the current create_rich_ui_text call (CJK etc.).
_LAYOUT_FORCE_PROFILE = ""


def font_layout_profile(font_family="", text="", locale=""):
    """Return layout profile key for a TMP/UI font family name."""
    if _LAYOUT_FORCE_PROFILE and _LAYOUT_FORCE_PROFILE in FONT_LAYOUT_PROFILES:
        return _LAYOUT_FORCE_PROFILE
    fam = (font_family or "").lower()
    try:
        from .fonts_util import detect_script
        script = detect_script(text or "")
    except Exception:
        script = "latin"
    # Layout follows *text* script, not page locale — Latin leftovers on zh-cn
    # must keep Amaranth/OpenSans knobs (title nudge, spacing muls).
    if script in ("cjk", "mixed", "hangul", "kana"):
        if "cjk" in FONT_LAYOUT_PROFILES:
            return "cjk"
    if "opensans" in fam or "open sans" in fam:
        return "opensans"
    if "arial" in fam or "liberation sans" in fam:
        return "arial"
    # PBS UI.Text Amaranth (no SDF). Stock Amaranth-* SDF stays on "ksp".
    if "amaranth" in fam and "sdf" not in fam:
        return "amaranth"
    if "cjk" in fam or "yahei" in fam or "sourcehan" in fam:
        return "cjk"
    auto_key = "auto_" + "".join(ch for ch in fam if ch.isalnum())[:40]
    if auto_key and auto_key in FONT_LAYOUT_PROFILES:
        return auto_key
    return "ksp"


def _is_calibrated_family(font_family=""):
    fam = (font_family or "").lower()
    if not fam:
        return True
    if "opensans" in fam or "open sans" in fam:
        return True
    if "arial" in fam or "liberation sans" in fam:
        return True
    if "amaranth" in fam and "sdf" not in fam:
        return True
    if "notosans" in fam or "noto sans" in fam:
        return True
    if "jd" in fam and "lcd" in fam:
        return True
    return False


def ensure_font_layout_profile(font_family="", font_path=""):
    """Synthesize FONT_LAYOUT_PROFILES knobs for unknown faces (in-place).

    Known calibrated faces are left untouched. Unknown faces clone the nearest
    calibrated profile and scale tracking / leading from outline metrics.
    """
    fam = (font_family or "").strip()
    if not fam or _is_calibrated_family(fam):
        return font_layout_profile(fam)
    auto_key = "auto_" + "".join(ch for ch in fam.lower() if ch.isalnum())[:40]
    if auto_key in FONT_LAYOUT_PROFILES:
        return auto_key
    try:
        from .fonts_resolve import synthesize_layout_profile
        key, prof = synthesize_layout_profile(fam, font_path or "")
    except Exception:
        return "ksp"
    if key and isinstance(prof, dict):
        FONT_LAYOUT_PROFILES[key] = prof
        return key
    return "ksp"


def font_layout_get(font_family, key, default=None):
    """Read a per-font layout coefficient (falls back to KSP, then default)."""
    try:
        ensure_font_layout_profile(font_family)
    except Exception:
        pass
    prof = FONT_LAYOUT_PROFILES.get(font_layout_profile(font_family)) or {}
    if key in prof:
        return prof[key]
    ksp = FONT_LAYOUT_PROFILES.get("ksp") or {}
    if key in ksp:
        return ksp[key]
    return default


def profile_own_get(font_family, key, default=None):
    """Read a layout key from this family only — never inherit KSP knobs."""
    prof = FONT_LAYOUT_PROFILES.get(font_layout_profile(font_family)) or {}
    if key in prof:
        return prof[key]
    return default


def _char_spacing_extra_px(font_family, fs_px):
    """Canvas-px tracking addend (stock KSP only). Titles add TITLE_* too."""
    if font_layout_profile(font_family) != "ksp":
        return float(profile_own_get(font_family, "CHAR_SPACING_EXTRA_PX", 0.0) or 0.0)
    extra = float(profile_own_get(font_family, "CHAR_SPACING_EXTRA_PX", 0.0) or 0.0)
    try:
        fs = float(fs_px)
    except Exception:
        fs = 0.0
    if fs >= float(TMP_FONT_TITLE_MIN_PX):
        extra += float(
            profile_own_get(font_family, "TITLE_CHAR_SPACING_EXTRA_PX", 0.0) or 0.0
        )
    return extra


def role_layout_get(font_family, role, key, default=None):
    """Read a role-table knob; fall back to family profile, then default."""
    prof = font_layout_profile(font_family)
    roles = FONT_ROLE_LAYOUT.get(prof) or {}
    table = roles.get(role) or {}
    if key in table:
        return table[key]
    return font_layout_get(font_family, key, default)


def classify_text_role(
    font_family="",
    font_size=40.0,
    plain="",
    name="",
    is_title=False,
    box_width_px=None,
    italic=False,
    bold=False,
    part=None,
):
    """Map a text element to a layout role (no page IDs like RE9/ST2/LL8)."""
    prof = font_layout_profile(font_family)
    raw = plain or ""
    plain_s = raw.strip()
    visible = (
        raw.replace("\u2007", "").replace("\u00a0", "").replace("\u2008", "")
        .strip()
    )
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    part_l = (part or "").lower()

    if prof == "amaranth":
        if is_title or (
            bool(bold) and float(font_size) >= float(TMP_FONT_TITLE_MIN_PX)
        ):
            return "title"
        if "subheader" in n:
            return "tagline"
        if plain_s.endswith(":") and len(plain_s) <= 48:
            return "colon_header"
        if len(visible) <= 40 and "\n" not in plain_s and "\\n" not in plain_s:
            return "section_label"
        return "tagline"

    if prof != "opensans":
        return "body"

    if (
        part_l == "each"
        and "\n" not in plain_s
        and "\\n" not in plain_s
        and len(plain_s) <= 90
    ):
        return "short_followup"

    # Figure-space / heavy lead pad + short token (e.g. ALT overlays).
    stripped_lead = raw.lstrip("\u2007\u2008\u00a0 \t")
    lead_n = len(raw) - len(stripped_lead)
    if lead_n >= 4 and len(visible) <= 8 and "\n" not in visible:
        return "label_overlay"

    # Unity role convention: OpenSans *Subheader* under blue title = intro.
    if "subheader" in n:
        return "intro"

    vis_l = visible.lstrip()
    if bool(italic):
        if vis_l.startswith('"') or vis_l.startswith("\u201c"):
            return "callout_quote"
        return "callout_code"

    bw = float(box_width_px) if box_width_px is not None else None
    callout_max = float(font_layout_get(font_family, "CALLOUT_BOX_MAX_PX", 620.0))
    mid_max = float(font_layout_get(font_family, "CALLOUT_MID_BOX_MAX_PX", 900.0))
    if bw is not None and bw <= callout_max:
        return "callout"
    # Artwork-hole strings (spaces reserved for a baked button) — any locale.
    if bw is not None and bw <= mid_max and _has_artwork_hole(raw):
        return "callout"
    return "body"


def _role_block_nudge_x_px(font_family, role):
    return float(role_layout_get(font_family, role, "BLOCK_NUDGE_X_PX", 0.0) or 0.0)


def _role_block_nudge_y_px(font_family, role):
    return float(role_layout_get(font_family, role, "BLOCK_NUDGE_Y_PX", 0.0) or 0.0)


def _amaranth_block_nudge_x_px(name="", plain="", font_size=40.0, is_title=False, bold=False):
    role = classify_text_role(
        "Amaranth", font_size, plain, name, is_title=is_title, bold=bold,
    )
    return _role_block_nudge_x_px("Amaranth", role)


def _amaranth_block_nudge_y_px(name="", plain="", font_size=40.0, is_title=False, bold=False):
    role = classify_text_role(
        "Amaranth", font_size, plain, name, is_title=is_title, bold=bold,
    )
    return _role_block_nudge_y_px("Amaranth", role)


def _opensans_block_nudge_x_px(
    name="", plain="", box_width_px=None, italic=False, bold=False, part=None,
    text_role=None,
):
    role = text_role or classify_text_role(
        "OpenSans", 40.0, plain, name,
        box_width_px=box_width_px, italic=italic, bold=bold, part=part,
    )
    return _role_block_nudge_x_px("OpenSans", role)


def _opensans_block_nudge_y_px(
    name="", plain="", box_width_px=None, italic=False, bold=False, part=None,
    text_role=None,
):
    role = text_role or classify_text_role(
        "OpenSans", 40.0, plain, name,
        box_width_px=box_width_px, italic=italic, bold=bold, part=part,
    )
    return _role_block_nudge_y_px("OpenSans", role)


def _opensans_wrap_bonus_px(name="", plain="", box_width_px=None, italic=False, text_role=None):
    role = text_role or classify_text_role(
        "OpenSans", 40.0, plain, name,
        box_width_px=box_width_px, italic=italic,
    )
    val = role_layout_get("OpenSans", role, "WRAP_BONUS_PX", 7.0)
    if val is None:
        return None
    return float(val)


def _opensans_spacing_muls(
    font_family="", name="", italic=False, plain="", box_width_px=None,
    text_role=None, part=None, is_title=False, bold=False, font_size=40.0,
):
    """CHAR/WORD muls from text role (+ italic family mul)."""
    fam_l = (font_family or "").lower().replace(" ", "")
    italic_mul = 1.0
    if bool(italic) or ("italic" in fam_l):
        italic_mul = float(
            font_layout_get(font_family, "ITALIC_CHAR_SPACING_MUL", 1.0)
        )
    role = text_role or classify_text_role(
        font_family, font_size, plain, name,
        is_title=is_title, box_width_px=box_width_px,
        italic=italic, bold=bold, part=part,
    )
    ch = float(role_layout_get(font_family, role, "CHAR_SPACING_MUL", 1.0) or 1.0)
    wd = float(role_layout_get(font_family, role, "WORD_SPACING_MUL", 1.0) or 1.0)
    return ch * italic_mul, wd


def _wrap_pull_extra_px(
    collection, plain, box_w_bu, size, font_family="", name="",
    italic=False, bold=False, locale="", text_role=None,
):
    """If one more word almost fits on L1 (deficit ≤ WRAP_PULL_MAX), add it."""
    if collection is None or box_w_bu is None or float(box_w_bu) < 1e-6:
        return 0.0
    text = (plain or "").replace("\n", " ").replace("\\n", " ").strip()
    words = text.split()
    if len(words) < 2:
        return 0.0
    max_px = float(font_layout_get(font_family, "WRAP_PULL_MAX_PX", 8.0))
    best_k = 0
    try:
        for k in range(1, len(words) + 1):
            prefix = " ".join(words[:k])
            w = float(_measure_font_width(
                collection, prefix, size,
                bold=bold, italic=italic, font_family=font_family,
                locale=locale, name=name,
            ))
            if w <= float(box_w_bu) + 1e-6:
                best_k = k
            else:
                break
        if best_k < 1 or best_k >= len(words):
            return 0.0
        w2 = float(_measure_font_width(
            collection, " ".join(words[: best_k + 1]), size,
            bold=bold, italic=italic, font_family=font_family,
            locale=locale, name=name,
        ))
        deficit_bu = w2 - float(box_w_bu)
        deficit_px = deficit_bu / float(DEFAULT_PIXEL_SCALE)
        if 1e-6 < deficit_px <= max_px:
            return float(deficit_px)
    except Exception:
        return 0.0
    return 0.0


# Back-compat aliases used by older call sites / rich-text branches.
def _is_pbs_intro_body(name="", plain="", box_width_px=None, italic=False):
    return classify_text_role(
        "OpenSans", 40.0, plain, name, box_width_px=box_width_px, italic=italic,
    ) == "intro"


def _is_pbs_callout_body(name="", plain="", box_width_px=None, italic=False):
    role = classify_text_role(
        "OpenSans", 40.0, plain, name, box_width_px=box_width_px, italic=italic,
    )
    return role in ("callout", "callout_quote", "callout_code")


def _is_pbs_amaranth_subheader(name="", plain=""):
    return classify_text_role("Amaranth", 40.0, plain, name) == "tagline"


def _is_pbs_colon_header(name="", plain=""):
    return classify_text_role("Amaranth", 40.0, plain, name) == "colon_header"


def _glue_trailing_colon(text: str) -> str:
    """Keep trailing ``:`` with the last word so Blender never orphans it.

    ``word:`` is already one token; ``word :`` → ``word\\u00a0:``.
    """
    t = text or ""
    if not t.rstrip().endswith(":"):
        return t
    # Trailing spaces after colon stay as-is; glue only the last word + ':' .
    core = t.rstrip("\r\n")
    trail = t[len(core):]
    if core.endswith(" :"):
        return core[:-2] + "\u00a0:" + trail
    return t


def _wrap_colon_header_to_width(
    collection, text, size, max_w, *,
    bold=False, italic=False, font_family="", locale="", name="",
) -> str:
    """Force a 2nd line for a tall overflowing colon header.

    Blender FONT only wraps when glyphs exceed ``text_boxes.width``. Outline
    faces are often a hair narrower than TMP SDF, so the string still fits
    on one line after we decided Unity would wrap. Insert ``\\n`` at the
    last space that keeps line 1 inside ``max_w``; if the whole string
    fits, wrap the last two tokens (``de survie :``).
    """
    t = _glue_trailing_colon(text or "")
    if (not t.strip()) or "\n" in t or max_w is None or float(max_w) <= 1e-8:
        return t
    parts = t.split(" ")
    if len(parts) < 2:
        return t
    best = 0
    try:
        for i in range(1, len(parts)):
            prefix = " ".join(parts[:i])
            w = _measure_font_width(
                collection, prefix, size,
                bold=bold, italic=italic, font_family=font_family,
                locale=locale, name=name,
            )
            if float(w) <= float(max_w):
                best = i
            else:
                break
    except Exception:
        best = 0
    if best <= 0:
        best = 1
    elif best >= len(parts):
        # Outline fitted; Unity still overflowed — wrap last two tokens.
        best = len(parts) - 2 if len(parts) >= 3 else max(1, len(parts) - 1)
    return " ".join(parts[:best]) + "\n" + " ".join(parts[best:])


def _colon_header_box_can_wrap(box_h_bu, pixel_scale, font_size_px) -> bool:
    """True when the Unity rect is tall enough for a 2nd wrapped line."""
    if box_h_bu is None:
        return False
    try:
        sx = float(pixel_scale) if pixel_scale else float(DEFAULT_PIXEL_SCALE)
        h_px = float(box_h_bu) / max(sx, 1e-9)
        fs = float(font_size_px)
    except Exception:
        return False
    if fs < 1.0 or h_px < 1.0:
        return False
    # Two lines at ~1.25 em plus a little slack — must fit inside this rect
    # (proxy for "won't spill onto text below").
    return h_px >= fs * 2.35


def _load_calib_nudges():
    """Optional debug fine-tunes. Off unless KSP_CALIB_NUDGES=1.

    Looks only for a local ``calib_nudges.debug.json`` (not shipped).
    """
    if os.environ.get("KSP_CALIB_NUDGES", "").strip() != "1":
        return
    try:
        import json
        path = os.path.join(
            os.path.dirname(__file__), "calib_nudges.debug.json"
        )
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nudges = data.get("text_nudges") or {}
        if isinstance(nudges, dict):
            for k, v in nudges.items():
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    TMP_TEXT_NUDGE_PX[str(k).lower()] = (float(v[0]), float(v[1]))
        for key in (
            "TMP_TITLE_X_SCALE",
            "TMP_FONT_SIZE_SCALE_BODY",
            "TMP_FONT_SIZE_SCALE_NOTE",
            "TMP_BODY_LINE_SPACING_MUL",
            "TMP_FONT_CELL_HEIGHT_FIT",
            "TMP_SHORT_LABEL_WRAP_BONUS_PX",
            "TMP_TABLE_COL_WIDTH_BONUS_PX",
            "TMP_TOP_EXTRA_NUDGE_BU",
            "TMP_PARAGRAPH_GAP_EM",
            "TMP_TABLE_ROW_PITCH_PX",
            "TMP_TABLE_COL_NUDGE_Y_PX",
            "TMP_USE_FACEINFO_SCALE",
        ):
            if key in data:
                globals()[key] = type(globals().get(key, 0.0))(data[key])
        # Keep KSP profile in sync when calib overrides shared aliases.
        ksp = FONT_LAYOUT_PROFILES.setdefault("ksp", {})
        for src, dst in (
            ("TMP_BODY_LINE_SPACING_MUL", "BODY_LINE_SPACING_MUL"),
            ("TMP_TOP_EXTRA_NUDGE_BU", "TOP_EXTRA_NUDGE_BU"),
        ):
            if src in data:
                ksp[dst] = float(globals()[src])
    except Exception:
        pass


_load_calib_nudges()

# FONT objects for table header labels — snapped to a shared baseline per row.
_TABLE_HEADER_FONTS = []


def _font_glyph_cy(obj):
    """World-ish glyph center Y (object-local bound_box + location.y)."""
    try:
        bpy.context.view_layer.update()
        bbs = [Vector(c) for c in obj.bound_box]
        return float(obj.location.y) + 0.5 * (
            min(v.y for v in bbs) + max(v.y for v in bbs)
        )
    except Exception:
        return float(obj.location.y)


def _register_table_header_font(obj):
    """Track header FONT and equalize glyph centers on the same table row."""
    if obj is None:
        return
    _TABLE_HEADER_FONTS.append(obj)
    alive = []
    for o in _TABLE_HEADER_FONTS:
        try:
            _ = o.name
            alive.append(o)
        except Exception:
            pass
    _TABLE_HEADER_FONTS[:] = alive
    if len(alive) < 2:
        return
    used = set()
    for i, a in enumerate(alive):
        if i in used:
            continue
        ya = float(a.location.y)
        group = [a]
        used.add(i)
        for j, b in enumerate(alive):
            if j in used:
                continue
            if abs(float(b.location.y) - ya) <= 0.025:
                group.append(b)
                used.add(j)
        # Roles header row: Level + Pilots + Engineers + Scientists.
        if len(group) < 3:
            continue
        try:
            bpy.context.view_layer.update()
            cys = [_font_glyph_cy(o) for o in group]
            target = sorted(cys)[len(cys) // 2]
            for o, cy in zip(group, cys):
                dy = target - cy
                if abs(dy) < 1e-9:
                    continue
                try:
                    tb = o.data.text_boxes[0]
                    tb.y = float(tb.y) + dy
                except Exception:
                    o.location = (
                        o.location.x, o.location.y + dy, o.location.z,
                    )
        except Exception:
            pass


def _nudge_for_plain(plain):
    """Return (dx_px, dy_px) for the longest matching nudge prefix."""
    pl = (plain or "").strip().lower()
    if not pl:
        return 0.0, 0.0
    best = ""
    best_xy = (0.0, 0.0)
    for prefix, xy in TMP_TEXT_NUDGE_PX.items():
        p = (prefix or "").lower()
        if p and pl.startswith(p) and len(p) > len(best):
            best = p
            best_xy = (float(xy[0]), float(xy[1]))
    return best_xy


def _apply_px_nudge_to_font(obj, dx_px, dy_px, sx):
    """Shift a FONT object by Unity-px nudge (+y = Blender up)."""
    if obj is None or (abs(dx_px) < 1e-9 and abs(dy_px) < 1e-9):
        return
    dx = float(dx_px) * float(sx)
    dy = float(dy_px) * float(sx)
    try:
        tb = obj.data.text_boxes[0]
        tb.x = float(tb.x) + dx
        tb.y = float(tb.y) + dy
    except Exception:
        obj.location = (obj.location.x + dx, obj.location.y + dy, obj.location.z)


def _plain_multiline(plain):
    pl = plain or ""
    return (chr(10) in pl) or ("\\n" in pl)


def _plain_n_lines(plain):
    pl = (plain or "").replace("\\n", chr(10))
    return max(pl.count(chr(10)) + 1, 1)


def _looks_like_table_column(plain, box_width, font_size) -> bool:
    """True for Level/skill digit columns — not bullet lists or body prose.

    Tall multi-line TMP boxes are common for tables, bullet lists, and wrapped
    paragraphs. Grid row placement must only run on short-line *narrow*
    columns; applying it to EVA bullet lists remaps lines onto ``box_h/n``
    tighter than glyph height and piles rows on top of each other.
    """
    raw = _normalize_tmp_newlines(plain or "")
    # Space/newline-padded overlays (PBI Configuration blue labels) sit in
    # gaps of white body text — not table grids. Leading ``\\n`` or indented
    # continuation lines must keep natural FONT line pitch.
    if raw[:1] in ("\n", "\r"):
        return False
    raw_lines = raw.split("\n")
    if any(
        (ln.startswith("  ") or ln.startswith("\t")) and ln.strip()
        for ln in raw_lines[1:]
    ):
        return False
    lines = [
        ln.strip()
        for ln in raw_lines
        if ln.strip()
    ]
    if len(lines) < 2:
        return False
    n_bullet = 0
    for ln in lines:
        s = ln.lstrip()
        if not s:
            continue
        if s[0] in "•·●○▪▫*-–—" or s.lower().startswith("and more"):
            n_bullet += 1
        # Long prose line => never a skill/digit column.
        if len(s) > 48:
            return False
    if n_bullet >= 2:
        return False
    avg = sum(len(ln) for ln in lines) / float(len(lines))
    try:
        bw = float(box_width) if box_width is not None else 1e9
        fs = float(font_size) if font_size else 14.0
    except Exception:
        return False
    # Digit index column (Level 0..5).
    if all((ln.isdigit() or ln == "") for ln in lines):
        return True
    # Skill columns: short lines inside a moderately narrow box.
    # EVA bullet box is ~670px wide at fs=40 — excluded by width caps.
    if avg <= 24.0 and bw <= fs * 16.0:
        return True
    if avg <= 42.0 and bw <= fs * 11.0 and len(lines) >= 3:
        return True
    return False

def _normalize_tmp_newlines(plain):
    return (plain or "").replace("\\n", "\n").replace("\r\n", "\n")


def preserve_overlay_newlines(plain):
    """Keep ``token<spaces>\\nleftover`` pads; restore if Unity/FONT glued them.

    FR ConfB1 ships (or roundtrips to) ``\\nshowModCategory         true``.
    EN/ES keep the enter after the pad (``true`` on the next line). Blender
    FONT and the orphan-join heuristic used to eat that ``\\n`` after trailing
    spaces. Restore only for space-pad overlays and a short leftover token.
    """
    text = plain or ""
    if not text or "<color" in text.lower():
        return text
    try:
        if not is_space_pad_overlay(text):
            return text
        if is_origin_overlay_text(text):
            return text
    except Exception:
        return text
    out = []
    changed = False
    for line in text.split("\n"):
        m = re.match(r"^(.*\S)([ \t]{2,})(\S{1,32})$", line)
        leftover = m.group(3) if m else ""
        if (
            m
            and leftover[:1].islower()
            and (" " not in leftover)
            and ("/" not in leftover)
            and ("." not in leftover)
        ):
            out.append(m.group(1) + m.group(2))
            out.append(leftover)
            changed = True
        else:
            out.append(line)
    return "\n".join(out) if changed else text


def _prepare_display_body(plain):
    """Normalize Unity-baked soft wraps for Blender FONT preview.

    Safe rules only — do NOT collapse space-padded overlay gaps
    (Configuration ``true`` / ConfB2 quote slots).

    - Keep soft-hyphen line breaks (``con-\\ntainers``) — Unity UI.Text
      shows the hyphenated wrap; joining made Storage ST7 diverge from ref
    - Join a trailing orphan word (``them\\nseparately``) when the last
      line has no leading spaces (not an indented overlay) and the previous
      line is not a soft-hyphen break
    - Sentence period butting into the next capital (``factors.The`` /
      ``parachute.You``):
        * Long current line (≥48 chars) → ``. `` so soft-wrap can keep
          ``The system`` on L1 (Storage ST1).
        * Short current line → ``.\\n`` so mid-block sentences like
          ``parachute.You can then…`` break like the screenshot (keeps
          Keep-in-mind from sitting a full line too high).
      Never split acronyms (``S.A.S.`` / ``U.S.A.``).
    """
    text = _normalize_tmp_newlines(plain or "")
    if not text:
        return text
    text = preserve_overlay_newlines(text)

    # Lang typos / export glitches: ``：：`` / ``::`` at EOL (zh ConfS3).
    text = re.sub(r"[：:]{2,}([ \t]*)$", r"：\1", text, flags=re.M)
    text = re.sub(r"[：:]{2,}(\n)", r"：\1", text)

    # Unity soft-wrap residue ``word- cont`` (hyphen + spaces, still one
    # paragraph): the space after ``-`` is real in the screenshot (CO1
    # ``space- stations``) — do NOT glue into ``word-cont`` / U+2011 (□ in
    # Open Sans). Only force the break Unity already took: newline before
    # the hyphenated token. Soft-hyphen EOL ``con-\\ntainers`` stays (no
    # spaces-only gap after ``-``).
    text = re.sub(
        r"[ \t]+([A-Za-z0-9]+)-[ \t]+([a-z]+)",
        r"\n\1- \2",
        text,
    )

    def _period_fix(m):
        start = m.start()
        line_start = text.rfind("\n", 0, start) + 1
        line_len = start - line_start
        # Long lead-in (ST1): glue with space. Short mid-block (RE8): break.
        if line_len >= 48:
            return ". " + m.group(1)
        return ".\n" + m.group(1)

    # Require lowercase/digit/closing paren before '.' so "S.A.S." stays one
    # token (was becoming "S.\\nA.\\nS." and stacking in table cells / body).
    text = re.sub(r"(?<=[a-z0-9)])\.([A-Z])", _period_fix, text)
    lines = text.split("\n")
    if len(lines) >= 2:
        last_raw = lines[-1]
        last = last_raw.strip()
        prev_raw = lines[-2]
        # Space-padded overlay lines (FR showModCategory + spaces + \\n + true)
        # must keep that enter — joining glued ``true`` onto the pad.
        # Leading spaces on the leftover line are also intentional pads.
        if prev_raw.endswith((" ", "\t")) or last_raw[:1] in (" ", "\t"):
            return text
        if is_space_pad_overlay(text) or is_artwork_overlay(text):
            return text
        # Soft-hyphen tails (``con-`` / ``tainers``) must stay broken.
        if (
            last
            and last_raw[:1] not in (" ", "\t")
            and (" " not in last)
            and last[:1].islower()
            and len(last) < 24
        ):
            prev = prev_raw.rstrip()
            if (
                prev
                and not prev.endswith((".", "!", "?", ":", ";", "-"))
            ):
                lines[-2] = prev + " " + last
                lines.pop()
                text = "\n".join(lines)
    return text


def _split_intro_paragraphs(plain):
    """Split any wide body on a blank line into (first, rest) paragraphs."""
    if not TMP_SPLIT_BLANK_LINE_PARAS:
        return None
    pl = _normalize_tmp_newlines(plain).strip()
    if "\n\n" not in pl:
        return None
    first, second = pl.split("\n\n", 1)
    first = first.strip()
    second = second.strip()
    if not first or not second:
        return None
    return first, second


def _table_row_pitch(box_h, sx, n_lines=None, row_pitch_px=None):
    """Row pitch for tall columns (Blender units).

    Prefer explicit ``row_pitch_px`` (sibling median), then debug
    ``TMP_TABLE_ROW_PITCH_PX``, else ``box_h / n_lines``.
    """
    if row_pitch_px is not None and float(row_pitch_px) > 1e-6:
        return float(row_pitch_px) * float(sx)
    pitch_px = float(TMP_TABLE_ROW_PITCH_PX)
    if pitch_px > 1e-6:
        return pitch_px * float(sx)
    n_rows = float(n_lines) if (n_lines is not None and int(n_lines) > 0) else 1.0
    if float(TMP_TABLE_ROW_COUNT) > 1e-6 and (
        n_lines is None or int(n_lines) <= 0
    ):
        n_rows = max(float(TMP_TABLE_ROW_COUNT), 1.0)
    return float(box_h) / max(n_rows, 1.0)


def _place_font_center_y(obj, target_cy):
    """Shift FONT text_box so glyph vertical center hits target_cy (local)."""
    if obj is None or obj.type != "FONT":
        return
    bpy.context.view_layer.update()
    bbs = [Vector(c) for c in obj.bound_box]
    cy = 0.5 * (min(v.y for v in bbs) + max(v.y for v in bbs))
    dy = float(target_cy) - cy
    if abs(dy) < 1e-9:
        return
    try:
        tb = obj.data.text_boxes[0]
        tb.y = float(tb.y) + dy
    except Exception:
        obj.location = (obj.location.x, obj.location.y + dy, obj.location.z)


def _center_tall_column_font(obj, plain_for_align, box_h, sx, row_pitch_px=None):
    """Legacy bulk pad — prefer per-row creators."""
    if obj is None or box_h is None or not _plain_multiline(plain_for_align):
        return
    n_lines = _plain_n_lines(plain_for_align)
    try:
        bpy.context.view_layer.update()
        bbs = [Vector(c) for c in obj.bound_box]
        total_h = max(v.y for v in bbs) - min(v.y for v in bbs)
        line_h = total_h / float(n_lines)
        row_pitch = _table_row_pitch(
            box_h, sx, n_lines, row_pitch_px=row_pitch_px
        )
        pad = 0.5 * (row_pitch - line_h)
        dy_bu = -pad + float(TMP_TABLE_COL_NUDGE_Y_PX) * float(sx)
        if abs(dy_bu) > 1e-9:
            _apply_px_nudge_to_font(obj, 0.0, dy_bu / float(sx), sx)
    except Exception:
        pass


def _place_finished_lines_on_grid(
    finished_lines, box_top, box_h, sx, row_pitch_px=None
):
    """Set each finished line center to box_top - (i+0.5)*row_pitch."""
    if not finished_lines or box_h is None:
        return
    row_pitch = _table_row_pitch(
        box_h, sx, n_lines=len(finished_lines), row_pitch_px=row_pitch_px
    )
    col_nudge = float(TMP_TABLE_COL_NUDGE_Y_PX) * float(sx)
    bpy.context.view_layer.update()
    for i, objs in enumerate(finished_lines):
        if not objs:
            continue
        target_cy = float(box_top) - (i + 0.5) * row_pitch + col_nudge
        centers = []
        for c in objs:
            bbs = [Vector(bb) for bb in c.bound_box]
            centers.append(
                float(c.location.y)
                + 0.5 * (min(v.y for v in bbs) + max(v.y for v in bbs))
            )
        cy = sum(centers) / float(len(centers))
        dy = target_cy - cy
        if abs(dy) > 1e-9:
            for c in objs:
                c.location = (c.location.x, c.location.y + dy, c.location.z)


def _center_tall_column_root(root, plain_for_align, box_h, sx, box_top=None,
                             finished_lines=None, row_pitch_px=None):
    """Place multi-style tall column lines on the JPG Level grid."""
    if root is None or box_h is None:
        return
    try:
        if finished_lines:
            top = float(box_top) if box_top is not None else None
            if top is None:
                tops = []
                for objs in finished_lines:
                    for c in objs:
                        tops.append(float(c.location.y))
                top = max(tops) if tops else 0.0
            _place_finished_lines_on_grid(
                finished_lines, top, box_h, sx, row_pitch_px=row_pitch_px
            )
            return
        # Fallback: group children by location.y
        bpy.context.view_layer.update()
        kids = [c for c in root.children if c.type == "FONT"]
        if not kids:
            return
        groups = {}
        for c in kids:
            groups.setdefault(round(float(c.location.y), 5), []).append(c)
        ordered = [groups[k] for k in sorted(groups.keys(), reverse=True)]
        top = float(box_top) if box_top is not None else max(
            float(c.location.y) for c in ordered[0]
        )
        _place_finished_lines_on_grid(
            ordered, top, box_h, sx, row_pitch_px=row_pitch_px
        )
    except Exception:
        pass


def _create_tall_column_rows(
    collection, name, lines, fsize, color, align_x, box_x, box_y, box_w, box_h,
    sx, font_family="", locale="", bold=False, italic=False, underline=False,
    line_spacing=0.0, ls_mul=1.0, row_pitch_px=None,
    character_spacing=0.0, word_spacing=0.0,
):
    """One FONT per table row at y = top - (i+0.5)*row_pitch."""
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.01
    collection.objects.link(root)
    top = float(box_y) + float(box_h)
    row_pitch = _table_row_pitch(
        box_h, sx, n_lines=len(lines), row_pitch_px=row_pitch_px
    )
    col_nudge = float(TMP_TABLE_COL_NUDGE_Y_PX) * float(sx)
    for i, line in enumerate(lines):
        child = create_ui_text(
            collection,
            "%s_r%d" % (name, i),
            line,
            fsize,
            color,
            align_x=align_x,
            align_y="TOP",
            bold=bold,
            italic=italic,
            box_width=box_w,
            box_height=None,
            line_spacing=line_spacing,
            word_wrap=False,
            box_x=box_x,
            box_y=0.0,
            font_family=font_family,
            locale=locale,
            line_spacing_mul=ls_mul,
            character_spacing=character_spacing,
            word_spacing=word_spacing,
        )
        child.parent = root
        # Hang from content-box top initially, then center into row i.
        try:
            tb = child.data.text_boxes[0]
            tb.x = float(box_x)
            tb.y = float(top)
            # Widen so long skill lines don't wrap inside the row slot.
            extra = float(TMP_TABLE_COL_WIDTH_BONUS_PX) * float(sx)
            tb.width = (float(box_w) + extra) if box_w is not None else tb.width
            tb.height = 0.0
        except Exception:
            pass
        child.location = (0.0, 0.0, 0.0)
        target_cy = top - (i + 0.5) * row_pitch + col_nudge
        _place_font_center_y(child, target_cy)
        if underline:
            add_text_underline(collection, child, color, name="%s_r%d" % (name, i))
        try:
            child["ksp_text_align"] = "%s/TOP" % align_x
            child["ksp_line_spacing"] = float(line_spacing)
        except Exception:
            pass
    try:
        root["ksp_text_align"] = "%s/TOP" % align_x
        root["ksp_line_spacing"] = float(line_spacing)
        root["ksp_text_underline"] = bool(underline)
    except Exception:
        pass
    return root


def _find_para_child(root, part):
    """Find FONT child for blank-line split (``as`` / ``each``)."""
    if root is None:
        return None
    want = str(part)
    for c in root.children:
        if c.type != "FONT":
            continue
        if str(c.get("ksp_para_part", "") or "") == want:
            return c
    suf = "_%s" % want
    for c in root.children:
        if c.type != "FONT":
            continue
        n = c.name or ""
        if n.endswith(suf) or (" %s" % want) in n or n.endswith(" %s)" % want):
            return c
    return None


def _create_intro_split_paragraphs(
    collection, name, para_as, para_each, fsize, color, align_x, box_x, box_y,
    box_w, box_h, sx, font_family="", locale="", bold=False, italic=False,
    underline=False, line_spacing=0.0, ls_mul=1.0, word_wrap=True,
    paragraph_spacing=0.0, font_size_px=40.0,
    character_spacing=0.0, word_spacing=0.0,
    unity_box_width_px=None,
):
    """Two FONTs with controlled paragraph gap (generic blank-line split)."""
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.01
    collection.objects.link(root)
    top = float(box_y) + float(box_h) if box_h is not None else 0.0

    def _mk(part, body, box_top_y):
        role = classify_text_role(
            font_family, font_size_px, body, name,
            box_width_px=unity_box_width_px, italic=italic, bold=bold,
            part=part,
        )
        # Internal curve name keeps _as/_each; object name is Outliner-friendly.
        obj = create_ui_text(
            collection,
            "%s_%s" % (name, part),
            body,
            fsize,
            color,
            align_x=align_x,
            align_y="TOP",
            bold=bold,
            italic=italic,
            box_width=box_w,
            box_height=None,
            line_spacing=line_spacing,
            word_wrap=word_wrap,
            box_x=box_x,
            box_y=0.0,
            font_family=font_family,
            locale=locale,
            line_spacing_mul=ls_mul,
            character_spacing=character_spacing,
            word_spacing=word_spacing,
            tmp_font_size=float(font_size_px),
            text_role=role,
            unity_box_width_px=unity_box_width_px,
        )
        try:
            obj.name = "%s (%s)" % (
                name, "1 as" if part == "as" else "3 each"
            )
            obj["ksp_para_part"] = str(part)
        except Exception:
            pass
        obj.parent = root
        try:
            tb = obj.data.text_boxes[0]
            tb.x = float(box_x)
            tb.y = float(box_top_y)
            if box_w is not None:
                tb.width = float(box_w)
            tb.height = 0.0
        except Exception:
            pass
        obj.location = (0.0, 0.0, 0.0)
        try:
            from .fonts_faceinfo import ascender_snap_extra_bu
            extra = float(font_layout_get(font_family, "TOP_EXTRA_NUDGE_BU", 0.0))
            if abs(extra) < 1e-12:
                extra = ascender_snap_extra_bu(font_size_px, sx, font_family)
            bpy.context.view_layer.update()
            bbs = [Vector(c) for c in obj.bound_box]
            max_y = max(v.y for v in bbs)
            dy = float(box_top_y) - max_y + extra
            if abs(dy) > 1e-9:
                tb = obj.data.text_boxes[0]
                tb.y = float(tb.y) + dy
        except Exception:
            pass
        if underline:
            add_text_underline(
                collection, obj, color, name="%s_%s" % (name, part)
            )
        # create_ui_text applies block nudge, then we overwrite tb.y — reapply.
        try:
            if font_layout_profile(font_family) == "opensans":
                nx = float(_opensans_block_nudge_x_px(
                    name, plain=body, box_width_px=unity_box_width_px,
                    italic=italic, bold=bold, part=part, text_role=role,
                ))
                ny = float(_opensans_block_nudge_y_px(
                    name, plain=body, box_width_px=unity_box_width_px,
                    italic=italic, bold=bold, part=part, text_role=role,
                ))
            elif font_layout_profile(font_family) == "amaranth":
                try:
                    fs_n = float(font_size_px)
                except Exception:
                    fs_n = 0.0
                is_title_n = bool(
                    (role == "title")
                    or fs_n >= float(TMP_FONT_TITLE_MIN_PX)
                )
                if role:
                    nx = float(_role_block_nudge_x_px(font_family, role))
                    ny = float(_role_block_nudge_y_px(font_family, role))
                else:
                    nx = float(_amaranth_block_nudge_x_px(
                        name, plain=body, bold=bold,
                        font_size=fs_n or 40.0, is_title=is_title_n,
                    ))
                    ny = float(_amaranth_block_nudge_y_px(
                        name, plain=body, bold=bold,
                        font_size=fs_n or 40.0, is_title=is_title_n,
                    ))
            else:
                nx = float(font_layout_get(font_family, "BLOCK_NUDGE_X_PX", 0.0))
                ny = float(font_layout_get(font_family, "BLOCK_NUDGE_Y_PX", 0.0))
                try:
                    fs = float(font_size_px)
                except Exception:
                    fs = 0.0
                if fs >= float(TMP_FONT_TITLE_MIN_PX):
                    tny = profile_own_get(font_family, "TITLE_BLOCK_NUDGE_Y_PX", None)
                    if tny is not None:
                        ny = float(tny)
            if abs(nx) > 1e-9 or abs(ny) > 1e-9:
                tb = obj.data.text_boxes[0]
                tb.x = float(tb.x) + nx * float(DEFAULT_PIXEL_SCALE)
                tb.y = float(tb.y) - ny * float(DEFAULT_PIXEL_SCALE)
        except Exception:
            pass
        return obj

    obj_as = _mk("as", para_as, top)
    ndx, ndy = _nudge_for_plain(para_as)
    _apply_px_nudge_to_font(obj_as, ndx, ndy, sx)

    # Outliner spacer so as / each read as two blocks (name sorts between).
    try:
        sep = bpy.data.objects.new("%s (2 ──)" % name, None)
        sep.empty_display_type = "PLAIN_AXES"
        sep.empty_display_size = 0.001
        collection.objects.link(sep)
        sep.parent = root
        sep.location = (0.0, 0.0, 0.0)
        sep.hide_render = True
        sep["ksp_para_sep"] = True
    except Exception:
        sep = None

    bpy.context.view_layer.update()
    bbs = [Vector(c) for c in obj_as.bound_box]
    as_min = min(v.y for v in bbs)
    as_max = max(v.y for v in bbs)
    as_h = as_max - as_min
    if as_h < 1e-6:
        as_h = _font_obj_height(
            obj_as, size=fsize, n_lines=max(1, para_as.count("\n") + 1),
        )
    if as_h < 1e-6:
        # Last resort: line-pitch estimate so the second paragraph moves.
        try:
            ls = float(obj_as.data.space_line) or 1.25
        except Exception:
            ls = 1.25
        as_h = float(fsize) * ls * max(1, para_as.count("\n") + 1)
    # Prefer live bound min_y; if degenerate, hang below content-box top.
    if abs(as_max - as_min) >= 1e-6:
        as_bottom = as_min
    else:
        as_bottom = float(top) - float(as_h)
    if abs(float(paragraph_spacing)) > 1e-6:
        gap = float(font_size_px) * (float(paragraph_spacing) / 100.0) * float(sx)
    elif float(TMP_INTRO_PARAGRAPH_GAP_PX) > 1e-6:
        gap = float(TMP_INTRO_PARAGRAPH_GAP_PX) * float(sx)
    elif float(TMP_PARAGRAPH_GAP_EM) > 1e-6:
        gap = float(font_size_px) * float(TMP_PARAGRAPH_GAP_EM) * float(sx)
    else:
        # One blank TMP line ≈ LineHeight/PointSize * mul (universal).
        try:
            from .fonts_faceinfo import tmp_line_em_ratio
            line_em = tmp_line_em_ratio(font_family)
        except Exception:
            line_em = 1.36
        gap = (
            float(font_size_px)
            * float(line_em)
            * float(TMP_PARAGRAPH_GAP_LINE_MUL)
            * float(sx)
        )
    # Short follow-ups sit too low with a full blank-line gap — one role mul.
    if (
        para_each
        and "\n" not in para_each
        and len(para_each.strip()) <= 90
        and float(font_layout_get(font_family, "SHORT_FOLLOWUP_GAP_MUL", 0.0)) > 1e-6
    ):
        gap *= float(role_layout_get(
            font_family, "short_followup", "SHORT_FOLLOWUP_GAP_MUL",
            font_layout_get(font_family, "SHORT_FOLLOWUP_GAP_MUL", 0.75),
        ) or 0.75)
    each_top = as_bottom - gap
    each_top += float(TMP_INTRO_EACH_RECT_Y_PX) * float(sx)

    obj_each = _mk("each", para_each, each_top)
    ndx2, ndy2 = _nudge_for_plain(para_each)
    _apply_px_nudge_to_font(obj_each, ndx2, ndy2, sx)

    try:
        root["ksp_text_align"] = "%s/TOP" % align_x
        root["ksp_line_spacing"] = float(line_spacing)
        root["ksp_text_underline"] = bool(underline)
        root["ksp_text_display"] = "%s\n\n%s" % (para_as, para_each)
        root["ksp_para_split"] = True
    except Exception:
        pass
    return root


# EEVEE MixShader(Emission) reads partial alphas ~2x too opaque vs Unity
# UI alpha-over. Raise alpha to this power (1→1, mid-tones drop; opaque icons
# and Background* stay solid).
UI_IMAGE_ALPHA_GAMMA = 1.7


def srgb_to_linear_channel(c):
    """Unity UI colors are sRGB; Blender emission inputs are scene-linear."""
    x = max(0.0, min(1.0, float(c)))
    if x <= 0.04045:
        return x / 12.92
    return ((x + 0.055) / 1.055) ** 2.4


def srgb_color_to_linear(color):
    """Convert an sRGB RGBA tuple to linear RGBA for emission materials."""
    if color is None:
        return (1.0, 1.0, 1.0, 1.0)
    r = srgb_to_linear_channel(color[0] if len(color) > 0 else 1.0)
    g = srgb_to_linear_channel(color[1] if len(color) > 1 else 1.0)
    b = srgb_to_linear_channel(color[2] if len(color) > 2 else 1.0)
    a = float(color[3]) if len(color) > 3 else 1.0
    return (r, g, b, a)


def image_png_bytes(image):
    """PNG bytes from a Blender Image (RAM only — no temp files)."""
    if image is None:
        return b""
    try:
        if image.packed_file is not None:
            data = image.packed_file.data
            if data:
                return bytes(data)
    except Exception:
        pass
    try:
        from PIL import Image as PILImage
        w, h = int(image.size[0]), int(image.size[1])
        pixels = list(image.pixels)
        raw = bytearray(w * h * 4)
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 4
                o = ((h - 1 - y) * w + x) * 4
                raw[o] = int(max(0, min(255, pixels[i] * 255.0)))
                raw[o + 1] = int(max(0, min(255, pixels[i + 1] * 255.0)))
                raw[o + 2] = int(max(0, min(255, pixels[i + 2] * 255.0)))
                raw[o + 3] = int(max(0, min(255, pixels[i + 3] * 255.0)))
        img = PILImage.frombytes("RGBA", (w, h), bytes(raw))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return b""


def fit_blender_image_to_canvas(image, target_w: int, target_h: int):
    """Return a packed Blender image fitted into ``target_w x target_h``.

    Used when replacing KSPedia page art so Unity Texture2D size stays stable.
    """
    tw = max(1, int(target_w or 0))
    th = max(1, int(target_h or 0))
    if image is None:
        return None
    try:
        sw = int(image.size[0])
        sh = int(image.size[1])
    except Exception:
        return image
    if sw == tw and sh == th:
        return image
    try:
        from PIL import Image as PILImage
        from .bundle import fit_rgba_into_canvas
    except Exception:
        # Fallback: leave original (export will still fit via apply_texture_png).
        return image
    png = image_png_bytes(image)
    if not png:
        return image
    try:
        pil = PILImage.open(io.BytesIO(png)).convert("RGBA")
        fitted = fit_rgba_into_canvas(pil, tw, th)
        buf = io.BytesIO()
        fitted.save(buf, format="PNG")
        name = "%s_%dx%d" % ((image.name or "ksp_img").split(".")[0][:40], tw, th)
        return image_from_png_bytes(name, buf.getvalue())
    except Exception:
        return image


def image_content_hash(image):
    """SHA1 of PNG bytes as Blender would export them."""
    import hashlib
    data = image_png_bytes(image)
    return hashlib.sha1(data).hexdigest() if data else ""


def image_from_png_bytes(name, png_bytes):
    """Create a packed Blender Image from PNG bytes in RAM (no temp files).

    ``Image.pack(data=…)`` + ``reload()`` leaves filepath empty and Blender
    reports ``Image "" not available`` with black planes. Decode with PIL,
    fill a GENERATED image, then ``pack(as_png=True)`` from the pixel buffer.
    """
    if not png_bytes:
        return None
    data = bytes(png_bytes)
    try:
        from PIL import Image as PILImage
        pil = PILImage.open(io.BytesIO(data)).convert("RGBA")
        w, h = int(pil.size[0]), int(pil.size[1])
    except Exception:
        return None
    if w < 1 or h < 1:
        return None

    base = name or "ksp_tex"
    unique = base
    if bpy.data.images.get(unique) is not None:
        n = 1
        while bpy.data.images.get("%s.%03d" % (base, n)) is not None:
            n += 1
        unique = "%s.%03d" % (base, n)

    img = bpy.data.images.new(unique, w, h, alpha=True)
    try:
        img.file_format = "PNG"
    except Exception:
        pass
    try:
        img.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    try:
        flipped = pil.transpose(PILImage.FLIP_TOP_BOTTOM)
        raw = flipped.tobytes("raw", "RGBA")
        nfloat = w * h * 4
        floats = [float(raw[i]) / 255.0 for i in range(nfloat)]
        img.pixels.foreach_set(floats)
    except Exception:
        return None
    try:
        img.pack(as_png=True)
    except TypeError:
        try:
            img.pack()
        except Exception:
            pass
    except Exception:
        try:
            img.pack()
        except Exception:
            pass
    return img



def make_unlit_image_material(name, image, color=(1.0, 1.0, 1.0, 1.0)):
    """Unlit UI image plane with Unity Image alpha semantics.

    Opacity = (texture.alpha * Image.color.a) ** UI_IMAGE_ALPHA_GAMMA.
    Power curve keeps opaque Background*/icons solid while milky highlight
    panels let BackgroundBlueGrid show through like EN KSPedia JPGs.
    ``color`` is Unity sRGB RGBA.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (520, 0)
    emit = nodes.new("ShaderNodeEmission")
    emit.location = (240, 60)
    emit.inputs["Strength"].default_value = 1.0
    trans = nodes.new("ShaderNodeBsdfTransparent")
    trans.location = (240, -100)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (380, 0)
    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-420, 40)
    tex.image = image

    lin = srgb_color_to_linear(color) if color is not None else (1.0, 1.0, 1.0, 1.0)
    color_a = max(0.0, min(1.0, float(lin[3])))
    gamma = max(0.05, float(UI_IMAGE_ALPHA_GAMMA))

    rgb = tex.outputs["Color"]
    if tuple(lin[:3]) != (1.0, 1.0, 1.0):
        mul = nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        mul.inputs["B"].default_value = (
            float(lin[0]), float(lin[1]), float(lin[2]), 1.0
        )
        mul.location = (-180, 80)
        links.new(tex.outputs["Color"], mul.inputs["A"])
        rgb = mul.outputs["Result"]
    links.new(rgb, emit.inputs["Color"])

    # alpha = tex.a * color.a
    amul = nodes.new("ShaderNodeMath")
    amul.operation = "MULTIPLY"
    amul.location = (-180, -80)
    links.new(tex.outputs["Alpha"], amul.inputs[0])
    amul.inputs[1].default_value = color_a
    # fac = alpha ** gamma  (opaque unchanged, milky panels more see-through)
    apow = nodes.new("ShaderNodeMath")
    apow.operation = "POWER"
    apow.location = (20, -80)
    links.new(amul.outputs["Value"], apow.inputs[0])
    apow.inputs[1].default_value = gamma

    links.new(apow.outputs["Value"], mix.inputs["Fac"])
    links.new(trans.outputs["BSDF"], mix.inputs[1])
    links.new(emit.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    mat.blend_method = "BLEND"
    try:
        mat.surface_render_method = "BLENDED"
    except Exception:
        pass
    try:
        mat.use_backface_culling = False
    except Exception:
        pass
    try:
        mat["ksp_ui_color_a"] = float(color_a)
        mat["ksp_ui_alpha_gamma"] = float(gamma)
    except Exception:
        pass
    return mat



def make_unlit_color_material(name, color=(1.0, 1.0, 1.0, 1.0)):
    """Flat emission material for UI text / solids.

    ``color`` is Unity/TMP sRGB; converted to linear for Blender so cyan
    titles match EN KSPedia reference saturation (not washed gray-blue).
    """
    lin = srgb_color_to_linear(color)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    emit = nodes.new("ShaderNodeEmission")
    emit.location = (100, 0)
    emit.inputs["Color"].default_value = (
        float(lin[0]), float(lin[1]), float(lin[2]), 1.0
    )
    emit.inputs["Strength"].default_value = 1.0
    if float(lin[3]) < 0.999:
        trans = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        mix.inputs["Fac"].default_value = float(lin[3])
        links.new(trans.outputs["BSDF"], mix.inputs[1])
        links.new(emit.outputs["Emission"], mix.inputs[2])
        links.new(mix.outputs["Shader"], out.inputs["Surface"])
        mat.blend_method = 'BLEND'
    else:
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
    try:
        mat.surface_render_method = 'BLENDED'
    except Exception:
        pass
    # Material-list swatch uses diffuse_color, not the Emission node.
    try:
        mat.diffuse_color = (
            float(lin[0]), float(lin[1]), float(lin[2]), 1.0
        )
    except Exception:
        pass
    return mat


def create_image_plane(collection, name, width, height, material=None,
                       pivot=(0.5, 0.5)):
    """Create an XY quad with Unity-style pivot at the object origin."""
    w = max(float(width), 1e-6)
    h = max(float(height), 1e-6)
    try:
        px = float(pivot[0])
        py = float(pivot[1])
    except Exception:
        px, py = 0.5, 0.5
    # Object origin = Unity pivot; verts span the rect around it
    x0, x1 = -px * w, (1.0 - px) * w
    y0, y1 = -py * h, (1.0 - py) * h
    verts = [
        (x0, y0, 0.0),
        (x1, y0, 0.0),
        (x1, y1, 0.0),
        (x0, y1, 0.0),
    ]
    faces = [(0, 1, 2, 3)]
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for i, uvco in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = uvco
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if material is not None:
        if mesh.materials:
            mesh.materials[0] = material
        else:
            mesh.materials.append(material)
    return obj


def create_ui_text(
    collection,
    name,
    body,
    size,
    color=(1.0, 1.0, 1.0, 1.0),
    align_x="LEFT",
    align_y="TOP",
    bold=False,
    italic=False,
    box_width=None,
    box_height=None,
    line_spacing=0.0,
    word_wrap=True,
    box_x=0.0,
    box_y=0.0,
    font_family="",
    locale="",
    line_spacing_mul=1.0,
    character_spacing=0.0,
    word_spacing=0.0,
    tmp_font_size=None,
    text_role=None,
    unity_box_width_px=None,
):
    """Create a FONT curve object for UI text (plain body, no TMP tags).

    ``box_x`` / ``box_y`` / ``box_width`` / ``box_height`` are the TMP content
    rectangle in pivot-local Blender units (lower-left origin, +X/+Y extent).
    This is required so RIGHT/CENTER alignment stays inside the RectTransform
    instead of spilling from the pivot into neighboring text.
    """
    raw_body = body or ""
    # Unity UI.Text space/newline padding → offsets / NBSP (Blender strips ASCII).
    lead_dx = lead_dy = 0.0
    space_dx = 0.0
    body_eff = raw_body
    if raw_body[:1] in ("\n", "\r", " ", "\t") or (
        not word_wrap and raw_body[:1].isspace()
    ):
        try:
            lh_est = max(float(size), 1e-4) * 1.25
            lead_dx, lead_dy, body_eff, space_dx = _leading_ws_to_offsets(
                collection, raw_body, size,
                bold=bold, italic=italic, font_family=font_family,
                locale=locale, line_height=lh_est, name=name,
            )
        except Exception:
            lead_dx = lead_dy = space_dx = 0.0
            body_eff = raw_body
    # Trailing newlines inflate Blender FONT height on section titles.
    # Overlay pads (showModCategory / ALT) use that enter after spaces —
    # stripping it glued ``true`` onto the pad (FR ConfB1).
    overlay_keep_nl = False
    try:
        overlay_keep_nl = bool(
            is_space_pad_overlay(raw_body or body_eff)
            or is_artwork_overlay(raw_body or body_eff)
        )
    except Exception:
        overlay_keep_nl = False
    if not overlay_keep_nl:
        while body_eff.endswith("\n") or body_eff.endswith("\r"):
            body_eff = body_eff[:-1]
    body_eff = _prepare_display_body(body_eff)
    try:
        _fs_role = float(tmp_font_size) if tmp_font_size else 40.0
    except Exception:
        _fs_role = 40.0
    _role = text_role or classify_text_role(
        font_family,
        _fs_role,
        body_eff or raw_body,
        name,
        is_title=_fs_role >= float(TMP_FONT_TITLE_MIN_PX),
        box_width_px=unity_box_width_px,
        italic=italic,
        bold=bold,
    )
    curve = bpy.data.curves.new(name=name + "_Curve", type='FONT')
    curve.body = body_eff
    curve.size = max(float(size), 1e-4)
    try:
        curve.align_x = align_x
    except Exception:
        curve.align_x = 'LEFT'
    try:
        curve.align_y = align_y
    except Exception:
        curve.align_y = 'TOP'
    from .layout import tmp_line_spacing_factor, tmp_char_word_spacing_factor
    try:
        curve.space_line = (
            tmp_line_spacing_factor(line_spacing) * float(line_spacing_mul)
        )
    except Exception:
        pass
    # Refine leading-newline Y using the actual Blender line pitch.
    if abs(lead_dy) > 1e-12 and raw_body:
        n_nl = 0
        for ch in raw_body:
            if ch == "\n":
                n_nl += 1
            elif ch not in ("\r",):
                break
        if n_nl > 0:
            try:
                lh = float(curve.size) * float(curve.space_line)
            except Exception:
                lh = float(curve.size) * 1.25
            lead_dy = -float(n_nl) * lh
            # ``\\nshowModCategory\\n    true``: leading drop + 2nd line sits
            # ~½ glyph below the host line ("is … true").
            if "\n" in body_eff and float(
                font_layout_get(font_family, "LEAD_NL_MULTILINE_NUDGE", 0.0)
            ) > 1e-9:
                lead_dy += (
                    float(font_layout_get(font_family, "LEAD_NL_MULTILINE_NUDGE", 0.0))
                    * float(curve.size)
                )
    # TMP m_characterSpacing / m_wordSpacing are %% of default (0 = stock 1.0).
    try:
        ch_mul, wd_mul = _opensans_spacing_muls(
            font_family, name=name, italic=italic,
            plain=body_eff or raw_body, box_width_px=unity_box_width_px,
            text_role=_role,
        )
        curve.space_character = (
            tmp_char_word_spacing_factor(character_spacing) * ch_mul
        )
        curve.space_word = (
            tmp_char_word_spacing_factor(word_spacing) * wd_mul
        )
        # Optional absolute +N canvas-px tracking (stock KSP only — no KSP fallback).
        try:
            fs_px = (
                float(tmp_font_size)
                if tmp_font_size is not None and float(tmp_font_size) > 1.0
                else float(size) / max(float(DEFAULT_PIXEL_SCALE), 1e-9)
            )
        except Exception:
            fs_px = 40.0
        extra_ch = float(_char_spacing_extra_px(font_family, fs_px))
        if abs(extra_ch) > 1e-12:
            curve.space_character = (
                float(curve.space_character) + extra_ch / max(fs_px, 1.0)
            )
    except Exception:
        pass
    # Shear approximates italic when a dedicated italic font is missing
    if italic:
        try:
            curve.shear = 0.35
        except Exception:
            pass
    has_box = box_width is not None and float(box_width) > 1e-6
    bw = bh = 0.0
    box_top = 0.0
    need_vshift = False
    if has_box:
        try:
            tb = curve.text_boxes[0]
            # API box_x/box_y are Unity content-box *lower-left* (pivot-local).
            bw = float(box_width)
            bh = float(box_height) if (
                box_height is not None and float(box_height) > 1e-6
            ) else 0.0
            box_top = float(box_y) + bh if bh > 1e-6 else float(box_y)
            tb.x = float(box_x)
            tb.width = bw
            if not word_wrap:
                # Blender FONT wraps on text_boxes.width even with "no wrap".
                # Widen for wrap-guard:
                #   LEFT  — grow right (keep left edge)
                #   RIGHT — grow left (keep right edge)
                #   CENTER — grow left by WRAP_BONUS + FACE_PAD. A symmetric
                #   −½·bonus widen centers on the expanded box and sits
                #   ~5–6 px right of Unity Midline/golden (outline fonts have
                #   no SDF padding inset that TMP accounts for).
                extra = (
                    float(TMP_SHORT_LABEL_WRAP_BONUS_PX)
                    * float(DEFAULT_PIXEL_SCALE)
                )
                face_bu = (
                    float(TMP_CELL_FACE_PAD_PX) * float(DEFAULT_PIXEL_SCALE)
                )
                if align_x == "CENTER":
                    # Symmetric widen from FaceInfo pad + wrap bonus so Midline
                    # stays on the Unity content-box center (no left-only bias).
                    grow = float(extra) + float(face_bu)
                    tb.x = float(box_x) - 0.5 * grow
                    tb.width = bw + grow
                elif align_x == "RIGHT":
                    grow = float(extra) + float(face_bu)
                    tb.x = float(box_x) - grow
                    tb.width = bw + grow
                else:
                    tb.x = float(box_x)
                    tb.width = bw + extra + face_bu
            # Blender quirk (5.x): when text_boxes.height > 0, glyphs rise
            # *above* text_boxes.y instead of hanging below it.  That pushes
            # KSPedia TOP callouts onto baked leader/frame lines.  Always lay
            # out with y at the content-box top and height=0 (width still
            # drives LEFT/RIGHT/CENTER + wrapping).  Midline/Bottom then get
            # a manual vertical shift after fonts are applied.
            tb.y = box_top
            tb.height = 0.0
            if align_y in ("CENTER", "BOTTOM") and bh > 1e-6:
                need_vshift = True
                try:
                    curve.align_y = "TOP"
                except Exception:
                    pass
        except Exception:
            pass
    elif not word_wrap:
        try:
            curve.text_boxes[0].width = 0.0
            curve.text_boxes[0].height = 0.0
            curve.text_boxes[0].x = 0.0
            curve.text_boxes[0].y = 0.0
        except Exception:
            pass
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    # KSPedia uses Noto Sans SDF assets.  Use the bundled outline faces for a
    # faithful, portable Blender preview instead of Blender's default font.
    try:
        from .fonts_util import apply_fonts_to_curve
        apply_fonts_to_curve(
            curve, bold=bold, italic=italic,
            text=body_eff or "", font_family=font_family, locale=locale,
        )
    except Exception:
        pass
    # After CJK face + size boost: insert real newlines (Blender ignores ZWSP).
    if word_wrap and has_box and bw > 1e-6:
        try:
            from .fonts_util import detect_script, wrap_cjk_to_width
            if detect_script(body_eff or "") in (
                "cjk", "mixed", "hangul", "kana",
            ):
                wrapped = wrap_cjk_to_width(
                    collection, body_eff, float(curve.size), float(bw),
                    bold=bold, italic=italic, font_family=font_family,
                    locale=locale, name=name,
                )
                if wrapped and wrapped != body_eff:
                    body_eff = wrapped
                    curve.body = body_eff
        except Exception:
            pass
    # OpenSans outline fills look heavier than Unity UI.Text raster — thin
    # Regular a touch (Bold/Italic keep full weight). Skip when face is CJK.
    try:
        fam_l = (font_family or "").lower().replace(" ", "")
        face_l = ""
        try:
            face_l = (curve.font.name or "").lower() if curve.font else ""
        except Exception:
            face_l = ""
        is_cjk_face = any(
            tok in face_l for tok in ("cjk", "yahei", "noto sans cjk", "source han")
        )
        if (
            not is_cjk_face
            and "opensans" in fam_l
            and "italic" not in fam_l
            and "bold" not in fam_l
            and not bold
            and not italic
        ):
            curve.offset = -0.012 * float(curve.size)
    except Exception:
        pass
    # Horizontal scale for outline vs Unity raster (OpenSans / Amaranth).
    # Object scale also multiplies text_boxes.*; keep the Unity box anchor
    # fixed in world X. Do NOT rewrite tb.width — PBS pages pad figure-spaces
    # for italic overlays; changing wrap width desyncs those slots.
    try:
        from .fonts_faceinfo import outline_x_scale
        xs = float(outline_x_scale(font_family))
        if abs(xs - 1.0) > 1e-6:
            obj.scale = (xs, float(obj.scale[1]), float(obj.scale[2]))
            try:
                tb = curve.text_boxes[0]
                if align_x == "RIGHT":
                    right = float(tb.x) + float(tb.width)
                    tb.x = right / xs - float(tb.width)
                elif align_x == "CENTER":
                    mid = float(tb.x) + 0.5 * float(tb.width)
                    tb.x = mid / xs - 0.5 * float(tb.width)
                else:
                    tb.x = float(tb.x) / xs
            except Exception:
                pass
    except Exception:
        pass
    # Manual vertical align inside the content box (see comment above).
    if need_vshift:
        try:
            bpy.context.view_layer.update()
            bbs = [Vector(c) for c in obj.bound_box]
            min_y = min(v.y for v in bbs)
            max_y = max(v.y for v in bbs)
            box_bottom = float(box_y)
            if align_y == "CENTER":
                dy = ((box_top + box_bottom) * 0.5) - ((min_y + max_y) * 0.5)
            else:
                dy = box_bottom - min_y
            if abs(dy) > 1e-9:
                curve.text_boxes[0].y = float(curve.text_boxes[0].y) + dy
        except Exception:
            pass
    elif (
        TMP_TOP_ASCENDER_SNAP
        and has_box
        and align_y == "TOP"
        and bh >= 0.0
    ):
        # Unity Top: line ascenders meet the top of the rect. Blender FONT TOP
        # with height=0 sits a few px lower — snap glyph tops up to box_top.
        try:
            bpy.context.view_layer.update()
            bbs = [Vector(c) for c in obj.bound_box]
            max_y = max(v.y for v in bbs)
            extra = float(font_layout_get(font_family, "TOP_EXTRA_NUDGE_BU", 0.0))
            if abs(extra) < 1e-12:
                try:
                    from .fonts_faceinfo import ascender_snap_extra_bu
                    if tmp_font_size is not None and float(tmp_font_size) > 1.0:
                        approx_fs = float(tmp_font_size)
                    else:
                        # Fallback: invert FaceInfo-ish curve.size → px.
                        approx_fs = max(
                            float(size) / max(float(DEFAULT_PIXEL_SCALE), 1e-9) / 1.58,
                            14.0,
                        )
                    extra = ascender_snap_extra_bu(
                        approx_fs, DEFAULT_PIXEL_SCALE, font_family
                    )
                except Exception:
                    extra = 0.006
            dy = box_top - max_y + extra
            if abs(dy) > 1e-9:
                curve.text_boxes[0].y = float(curve.text_boxes[0].y) + dy
        except Exception:
            pass
    # Unity UI.Text leading \\n → box Y; leading spaces → figure-space in body.
    if abs(lead_dx) > 1e-12 or abs(lead_dy) > 1e-12:
        try:
            tb = curve.text_boxes[0]
            tb.x = float(tb.x) + float(lead_dx)
            tb.y = float(tb.y) + float(lead_dy)
            # Rare box_dx path: shrink wrap width after a true box indent.
            # Space-padded PBS overlays (ConfB*/ConfSubheader2) must keep the
            # Unity sizeDelta width — shrinking to leftover glyphs clips them.
            overlay_pad = False
            try:
                overlay_pad = is_space_pad_overlay(raw_body or body_eff or "")
            except Exception:
                overlay_pad = False
            if (
                word_wrap
                and not overlay_pad
                and float(lead_dx) > 1e-8
                and float(tb.width) > float(lead_dx)
            ):
                rem = float(tb.width) - float(lead_dx)
                try:
                    body_w = _measure_font_width(
                        collection, body_eff, size,
                        bold=bold, italic=italic,
                        font_family=font_family, locale=locale,
                    )
                    floor = max(float(size) * 4.0, float(body_w) * 0.45)
                except Exception:
                    floor = float(size) * 8.0
                if rem >= floor:
                    tb.width = rem
        except Exception:
            obj.location = (
                float(obj.location.x) + float(lead_dx),
                float(obj.location.y) + float(lead_dy),
                float(obj.location.z),
            )
    try:
        # Prefer measured first-line space pad (NBSP); fall back to box indent.
        obj["ksp_lead_dx"] = float(space_dx if abs(space_dx) > 1e-12 else lead_dx)
        obj["ksp_lead_dy"] = float(lead_dy)
    except Exception:
        pass
    # Slight Z bias so text draws above sibling image planes
    mat = make_unlit_color_material(name + "_Mat", color)
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    # Store style hints
    try:
        obj["ksp_text_bold"] = bool(bold)
        obj["ksp_text_italic"] = bool(italic)
        obj["ksp_text_align"] = "%s/%s" % (align_x, align_y)
    except Exception:
        pass
    # Per-face block nudge (px → BU). +X right, +Y down on the KSPedia canvas
    # (Blender UI Y is up, so Y nudge subtracts from location/tb.y).
    try:
        if font_layout_profile(font_family) == "opensans":
            nx = float(_opensans_block_nudge_x_px(
                name, plain=body_eff or raw_body,
                box_width_px=unity_box_width_px, italic=italic, bold=bold,
                text_role=_role,
            ))
            ny = float(_opensans_block_nudge_y_px(
                name, plain=body_eff or raw_body,
                box_width_px=unity_box_width_px, italic=italic, bold=bold,
                text_role=_role,
            ))
        elif font_layout_profile(font_family) == "amaranth":
            # Prefer caller role (create_rich passes "title"); reclassify with
            # real font size so bold page titles are not treated as section_label.
            try:
                fs_n = float(tmp_font_size) if tmp_font_size is not None else 0.0
            except Exception:
                fs_n = 0.0
            is_title_n = bool(
                _role == "title" or fs_n >= float(TMP_FONT_TITLE_MIN_PX)
            )
            if _role:
                nx = float(_role_block_nudge_x_px(font_family, _role))
                ny = float(_role_block_nudge_y_px(font_family, _role))
            else:
                nx = float(_amaranth_block_nudge_x_px(
                    name, plain=body_eff or raw_body, bold=bold,
                    font_size=fs_n or 40.0, is_title=is_title_n,
                ))
                ny = float(_amaranth_block_nudge_y_px(
                    name, plain=body_eff or raw_body, bold=bold,
                    font_size=fs_n or 40.0, is_title=is_title_n,
                ))
        else:
            nx = float(font_layout_get(font_family, "BLOCK_NUDGE_X_PX", 0.0))
            ny = float(font_layout_get(font_family, "BLOCK_NUDGE_Y_PX", 0.0))
            try:
                fs = float(tmp_font_size) if tmp_font_size is not None else 0.0
            except Exception:
                fs = 0.0
            if fs >= float(TMP_FONT_TITLE_MIN_PX):
                tny = profile_own_get(font_family, "TITLE_BLOCK_NUDGE_Y_PX", None)
                if tnx is not None:
                    nx = float(tnx)
                if tny is not None:
                    ny = float(tny)
        if abs(nx) > 1e-9 or abs(ny) > 1e-9:
            bu_x = nx * float(DEFAULT_PIXEL_SCALE)
            bu_y = -ny * float(DEFAULT_PIXEL_SCALE)
            try:
                tb = curve.text_boxes[0]
                tb.x = float(tb.x) + bu_x
                tb.y = float(tb.y) + bu_y
            except Exception:
                obj.location = (
                    float(obj.location.x) + bu_x,
                    float(obj.location.y) + bu_y,
                    float(obj.location.z),
                )
    except Exception:
        pass
    return obj


def add_text_underline(collection, text_obj, color, name=None):
    """Add a thin local-space underline bar beneath a FONT object.

    Blender FONT curves have no TMP underline equivalent.  The bar is parented
    to the text object so it follows layout, transforms and rich-text runs.
    """
    if text_obj is None or text_obj.type != 'FONT':
        return None
    try:
        bpy.context.view_layer.update()
        corners = [Vector(c) for c in text_obj.bound_box]
        min_x = min(c.x for c in corners)
        max_x = max(c.x for c in corners)
        min_y = min(c.y for c in corners)
        max_y = max(c.y for c in corners)
    except Exception:
        return None
    width = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, float(text_obj.data.size) * 0.03)
    thickness = max(height * 0.045, 0.00015)
    # Font bounds can omit descenders; keep a small gap below visible glyphs.
    y = min_y - thickness * 1.5
    mat = make_unlit_color_material((name or text_obj.name) + "_UnderlineMat", color)
    bar = create_image_plane(
        collection, (name or text_obj.name) + "_Underline", width, thickness,
        mat, pivot=(0.5, 0.5),
    )
    bar.parent = text_obj
    bar.location = ((min_x + max_x) * 0.5, y, 0.0001)
    bar["ksp_text_underline"] = True
    return bar



def tmp_font_size_to_blender(font_size, pixel_scale=DEFAULT_PIXEL_SCALE,
                             max_height_px=None, cell_fit=None,
                             font_family="", canvas_scale=1.0):
    """Map Unity TMP m_fontSize (px) to Blender FONT curve.size.

    Prefer FaceInfo CapHeight formula (universal). Fall back to legacy
    TITLE/BODY/NOTE empiric scales if FaceInfo path is disabled.
    """
    fs = max(float(font_size), 1.0)
    if TMP_USE_FACEINFO_SCALE:
        try:
            from .fonts_faceinfo import tmp_font_size_universal
            size = tmp_font_size_universal(
                fs, pixel_scale, font_family, canvas_scale
            )
        except Exception:
            size = fs * float(pixel_scale) * float(TMP_FONT_SIZE_SCALE_BODY)
    else:
        if fs >= float(TMP_FONT_TITLE_MIN_PX):
            scale = float(TMP_FONT_SIZE_SCALE)
        elif fs <= 36.0:
            scale = float(TMP_FONT_SIZE_SCALE_NOTE)
        else:
            scale = float(TMP_FONT_SIZE_SCALE_BODY)
        size = fs * float(pixel_scale) * scale
    if max_height_px is not None:
        try:
            mh = float(max_height_px)
        except Exception:
            mh = 0.0
        if mh > 1e-6:
            fit = float(
                TMP_FONT_CELL_HEIGHT_FIT if cell_fit is None else cell_fit
            )
            cap = mh * float(pixel_scale) * fit
            if size > cap > 1e-8:
                size = cap
    return max(size, 1e-4)


def _font_obj_width(obj, size=None, text=""):
    """Best-effort rendered width of an existing FONT object."""
    if obj is None:
        return 0.0
    w = 0.0
    try:
        w = float(obj.dimensions.x)
    except Exception:
        w = 0.0
    if w < 1e-8:
        try:
            bbs = [Vector(c) for c in obj.bound_box]
            w = max(v.x for v in bbs) - min(v.x for v in bbs)
        except Exception:
            w = 0.0
    if w < 1e-8 and text:
        try:
            w = float(size or getattr(obj.data, "size", 0.05)) * 0.5 * len(text)
        except Exception:
            w = 0.0
    return max(w, 0.0)


def _font_obj_height(obj, size=None, n_lines=1):
    """Best-effort rendered height of an existing FONT object."""
    if obj is None:
        return 0.0
    h = 0.0
    try:
        h = float(obj.dimensions.y)
    except Exception:
        h = 0.0
    if h < 1e-8:
        try:
            bbs = [Vector(c) for c in obj.bound_box]
            h = max(v.y for v in bbs) - min(v.y for v in bbs)
        except Exception:
            h = 0.0
    if h < 1e-8:
        try:
            sz = float(size or getattr(obj.data, "size", 0.05))
            ls = 1.25
            try:
                ls = float(obj.data.space_line) or ls
            except Exception:
                pass
            h = sz * ls * max(int(n_lines), 1)
        except Exception:
            h = 0.0
    return max(h, 0.0)


def _measure_font_width(collection, text, size, bold=False, italic=False,
                        font_family="", locale="", name=""):
    """Measure rendered width of a short string (temp FONT, then remove)."""
    if not text:
        return 0.0
    # Blender FONT often collapses pure whitespace → 0 width. Probe with
    # flanking glyphs so space-padded Unity UI.Text overlays measure correctly.
    space_only = (not text.strip()) and any(ch == " " or ch == "\t" for ch in text)
    if space_only:
        n_sp = sum(1 for ch in text if ch == " " or ch == "\t")
        w_full = _measure_font_width(
            collection, "M" + (" " * n_sp) + "M", size,
            bold=bold, italic=italic, font_family=font_family, locale=locale,
            name=name,
        )
        w_mm = _measure_font_width(
            collection, "MM", size,
            bold=bold, italic=italic, font_family=font_family, locale=locale,
            name=name,
        )
        return max(w_full - w_mm, float(size) * 0.25 * n_sp)
    curve = bpy.data.curves.new(name="_ksp_measure_Curve", type="FONT")
    curve.body = text
    curve.size = max(float(size), 1e-4)
    try:
        curve.align_x = "LEFT"
        curve.align_y = "TOP"
    except Exception:
        pass
    # Match create_ui_text spacing so figure-space pads land on the same
    # advances as the final FONT (CHAR/WORD profile muls + callout boost).
    try:
        from .layout import tmp_char_word_spacing_factor
        ch_mul, wd_mul = _opensans_spacing_muls(
            font_family, name=name, italic=italic,
        )
        curve.space_character = tmp_char_word_spacing_factor(0.0) * ch_mul
        curve.space_word = tmp_char_word_spacing_factor(0.0) * wd_mul
        fs_px = float(size) / max(float(DEFAULT_PIXEL_SCALE), 1e-9)
        extra_ch = float(_char_spacing_extra_px(font_family, fs_px))
        if abs(extra_ch) > 1e-12:
            curve.space_character = (
                float(curve.space_character) + extra_ch / max(fs_px, 1.0)
            )
    except Exception:
        pass
    obj = bpy.data.objects.new("_ksp_measure", curve)
    collection.objects.link(obj)
    try:
        from .fonts_util import apply_fonts_to_curve
        apply_fonts_to_curve(
            curve, bold=bold, italic=italic,
            text=text, font_family=font_family, locale=locale,
        )
    except Exception:
        pass
    try:
        bpy.context.view_layer.update()
        w = _font_obj_width(obj, size=size, text=text)
    except Exception:
        w = float(size) * 0.5 * len(text)
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
    try:
        bpy.data.curves.remove(curve)
    except Exception:
        pass
    return max(w, 0.0)


def _leading_ws_to_offsets(
    collection, body, size, bold=False, italic=False,
    font_family="", locale="", line_height=None, name="",
):
    """Map leading UI.Text padding for Blender FONT.

    Returns ``(box_dx, box_dy, body_eff, space_dx)``:
    - Leading ``\\n`` → ``box_dy`` (Blender collapses blank prefix lines).
    - Leading spaces → **figure-space (U+2007) prefix** in ``body_eff`` (not ``box_dx``).

    Unity indents only the *first* line with leading spaces; soft-wrapped
    continuations restart at the rect's left. Shifting ``text_boxes.x`` and
    shrinking width indented every wrapped line — ConfB2's quote then landed
    on top of ConfT2's ``is enabled``. ASCII/NBSP prefixes are collapsed by
    Blender FONT; figure space (U+2007) keeps advance. ``space_dx`` is the
    measured first-line pad (for ``ksp_lead_dx`` / smokes).
    """
    text = body or ""
    if not text:
        return 0.0, 0.0, text, 0.0
    i = 0
    n_nl = 0
    while i < len(text) and text[i] in ("\n", "\r"):
        if text[i] == "\n":
            n_nl += 1
        i += 1
    n_sp = 0
    while i < len(text) and text[i] in (" ", "\t"):
        n_sp += 1
        i += 1
    if n_nl == 0 and n_sp == 0:
        return 0.0, 0.0, text, 0.0
    stripped = text[i:]
    lh = float(line_height) if line_height is not None else float(size) * 1.25
    dy = -float(n_nl) * lh
    space_dx = 0.0
    if n_sp > 0:
        # Target first-line advance (Unity pads tighter than Blender outline).
        space_dx = _measure_font_width(
            collection, " " * n_sp, size,
            bold=bold, italic=italic, font_family=font_family, locale=locale,
            name=name,
        )
        if space_dx < 1e-8:
            space_dx = float(size) * 0.25 * float(n_sp)
        if int(n_sp) >= int(font_layout_get(
            font_family, "LEAD_SPACE_SCALE_MIN_SP", TMP_LEAD_SPACE_SCALE_MIN_SP
        )):
            space_dx *= float(font_layout_get(
                font_family, "LEAD_SPACE_SCALE", TMP_LEAD_SPACE_SCALE
            ))
        # Blender FONT collapses leading ASCII/NBSP; U+2007 keeps first-line
        # advance. Soft-wrap then restarts at the rect left like Unity UI.Text.
        fig = "\u2007"
        n_keep = 1
        best_w = 0.0
        for n in range(1, max(int(n_sp) * 3, 8) + 1):
            w = _measure_font_width(
                collection, fig * n, size,
                bold=bold, italic=italic, font_family=font_family, locale=locale,
                name=name,
            )
            n_keep = n
            best_w = w
            if w >= float(space_dx) * 0.98:
                break
        prefix = fig * n_keep
        if best_w > 1e-8:
            space_dx = float(best_w)
        # If the payload is wider than (will-be) remaining first-line width,
        # insert an explicit break so line-2 starts at the left of the full
        # rect (Unity), instead of relying on FONT wrap + condensed tracking.
        # box_width is unknown here — caller may condense; keep prefix+core.
        stripped = prefix + stripped
    return 0.0, dy, stripped, space_dx


def _figure_space_indent_lines(text: str, min_spaces: int = 4) -> str:
    """Keep mid-body callout indents after a blank line (ES RE8).

    Skip PBS overlay pads (ConfB*/ConfSubheader2) and ConfT* hole lines
    (spaces then \"is enabled\") — those need ``_ui_text_leading_pad``.
    """
    if not text or "\n" not in text:
        return text or ""
    lead = text.lstrip("\r")
    if lead[:1] in ("\n", " ", "\t"):
        return text
    out = []
    prev_blank = False
    for ln in text.split("\n"):
        stripped = ln.lstrip(" \t")
        i = len(ln) - len(stripped)
        if not stripped:
            out.append(ln)
            prev_blank = True
            continue
        if prev_blank and i >= int(min_spaces):
            out.append("\u2007" * i + stripped)
        else:
            out.append(ln)
        prev_blank = False
    return "\n".join(out)


_ARTWORK_HOLE_RE = re.compile(
    r"(?:\S[\u2007\u2008\u00a0 \t]{6,}\S)|(?:\S[\u2007\u2008\u00a0 \t]{8,}$)",
    re.MULTILINE,
)


def _visible_overlay_payload(text: str) -> str:
    t = (text or "").replace("\\n", "\n")
    for ch in ("\u2007", "\u2008", "\u00a0"):
        t = t.replace(ch, " ")
    return t.strip()


def _has_artwork_hole(text: str) -> bool:
    """Control-sized space hole near the lead-in (button / token on artwork).

    Long body sentences that leave a gap for a *nested* overlay (path, quote)
    are not themselves overlays.
    """
    t = (text or "").replace("\\n", "\n")
    if not t or "<color" in t.lower():
        return False
    vis = _visible_overlay_payload(t)
    if not vis or not any(ch.isalnum() for ch in vis):
        return False
    norm = (
        t.replace("\u2007", " ").replace("\u2008", " ").replace("\u00a0", " ")
    )
    # Wrapped line that starts in the hole, then continues as words.
    if re.search(r"(?:^|\n)[ \t]{8,}\S", norm):
        return True
    # Button/token hole in the opening (e.g. ``is         .``).
    return bool(_ARTWORK_HOLE_RE.search(norm[:100]))


def is_space_pad_overlay(text: str = "") -> bool:
    """Leading newline/space pad that parks a short leftover on artwork."""
    t = text or ""
    if "<color" in t.lower():
        return False
    vis = _visible_overlay_payload(t)
    if not vis or len(vis) >= 160:
        return False
    lead = t.lstrip("\r")
    if lead.startswith("\n"):
        return True
    n_sp = len(lead) - len(lead.lstrip(" \t"))
    if n_sp >= 4:
        return True
    n_fig = len(t) - len(t.lstrip("\u2007\u2008"))
    return n_fig >= 4


def is_origin_overlay_text(text: str = "") -> bool:
    """Hole overlay: visible text interrupted by a space run for a button."""
    if is_space_pad_overlay(text):
        return False
    return _has_artwork_hole(text)


def is_artwork_overlay(text: str = "", obj=None) -> bool:
    """Import-stamped or content-detected text sitting on shared artwork."""
    try:
        if obj is not None and (
            obj.get("ksp_artwork_overlay") or obj.get("ksp_origin_box")
        ):
            return True
    except Exception:
        pass
    return bool(is_space_pad_overlay(text) or is_origin_overlay_text(text))


def is_short_token_overlay(text: str = "", name: str = "") -> bool:
    """LL8 / ALT leftover: locale .lang pad inside the pinned artwork box.

    Origin stays on the import pin (shared screenshot). ConfB* quotes stay
    fully image-locked including the FONT text_boxes.
    """
    n = (name or "").strip()
    if n.upper() == "LL8":
        return True
    vis = _visible_overlay_payload(text)
    if vis and vis.strip().upper() == "ALT":
        return True
    return False


def overlay_lead_prefix(text: str) -> str:
    """Leading newlines / spaces / figure-spaces that park a token on artwork."""
    t = text or ""
    i = 0
    while i < len(t) and t[i] in ("\n", "\r", " ", "\t", "\u2007", "\u2008", "\u00a0"):
        i += 1
    return t[:i]


def lock_short_overlay_text(old_obj, new_text: str) -> str:
    """No-op: short tokens (ALT) keep the locale .lang pad and AP.

    Import-lead rewrite stacked EN spaces onto every language and hid
    RectTransform offsets from the sibling .lang.
    """
    return new_text


def _is_space_pad_overlay(name: str = "", text: str = "") -> bool:
    """Compat wrapper — detection is by string, not GameObject name."""
    return is_space_pad_overlay(text)


def _is_origin_overlay_text(
    name="", text="", box_width=None, box_height=None, font_size=14.0,
) -> bool:
    """Compat wrapper — hole overlays from the string, not ConfT1/T2 names."""
    return is_origin_overlay_text(text)


def snapshot_font_materials(obj):
    """Material slots + per-character indices (Blender FONT multimaterial)."""
    out = {"materials": [], "indices": [], "body": ""}
    if obj is None or getattr(obj, "type", "") != "FONT" or obj.data is None:
        return out
    curve = obj.data
    try:
        out["body"] = curve.body or ""
    except Exception:
        out["body"] = ""
    try:
        for mat in list(curve.materials) or []:
            col = None
            name = ""
            try:
                name = str(mat.name or "") if mat is not None else ""
            except Exception:
                name = ""
            if mat is not None:
                try:
                    if mat.use_nodes and mat.node_tree:
                        for nd in mat.node_tree.nodes:
                            if getattr(nd, "type", "") == "EMISSION":
                                v = nd.inputs["Color"].default_value
                                col = (
                                    float(v[0]), float(v[1]), float(v[2]),
                                    float(v[3]) if len(v) > 3 else 1.0,
                                )
                                break
                except Exception:
                    col = None
                if col is None:
                    try:
                        v = mat.diffuse_color
                        col = (float(v[0]), float(v[1]), float(v[2]), 1.0)
                    except Exception:
                        col = None
            out["materials"].append({"name": name, "color": col, "id": mat})
    except Exception:
        pass
    # Single-slot FONTs have no per-letter indices. Walking body_format on
    # every locale capture used to throw / abort the whole page snapshot, so
    # present_* shrank to the painted box and every other row went Missing.
    if len(out["materials"]) > 1:
        try:
            fmt = curve.body_format
            body = out["body"]
            for i in range(len(body)):
                try:
                    out["indices"].append(int(fmt[i].material_index))
                except Exception:
                    out["indices"].append(0)
        except Exception:
            pass
    return out


def restore_font_materials(obj, snap, *, require_same_body=True) -> bool:
    """Re-apply painted FONT materials after a locale rebuild."""
    if obj is None or not snap:
        return False
    mats = snap.get("materials") or []
    if len(mats) <= 1 and len(set(snap.get("indices") or [0])) <= 1:
        return False
    if getattr(obj, "type", "") != "FONT" or obj.data is None:
        return False
    curve = obj.data
    body = ""
    try:
        body = curve.body or ""
    except Exception:
        return False
    if require_same_body and body != (snap.get("body") or ""):
        return False
    slot_mats = []
    for i, info in enumerate(mats):
        mat = info.get("id") if isinstance(info, dict) else info
        try:
            _ = mat.name
        except Exception:
            mat = None
        if mat is None and isinstance(info, dict):
            name = str(info.get("name") or "")
            if name:
                try:
                    import bpy
                    mat = bpy.data.materials.get(name)
                except Exception:
                    mat = None
            if mat is None:
                col = info.get("color") if isinstance(info, dict) else None
                if col is not None and len(col) >= 3:
                    mat = make_unlit_color_material(
                        (name or (obj.name + "_Mat%s" % i)),
                        tuple(float(c) for c in col[:4]),
                    )
            elif isinstance(info, dict) and info.get("color") is not None:
                try:
                    _set_unlit_material_color(mat, info.get("color"))
                except Exception:
                    pass
        slot_mats.append(mat)
    if not any(slot_mats):
        return False
    try:
        while len(curve.materials) < len(slot_mats):
            curve.materials.append(None)
        for i, mat in enumerate(slot_mats):
            if mat is not None:
                curve.materials[i] = mat
    except Exception:
        return False
    indices = snap.get("indices") or []
    if require_same_body and body != (snap.get("body") or ""):
        return True
    if len(set(indices)) <= 1:
        return True
    try:
        fmt = curve.body_format
        n = min(len(body), len(indices))
        for i in range(n):
            fmt[i].material_index = int(indices[i])
    except Exception:
        pass
    return True


def _rgba4(color, fallback=(1.0, 1.0, 1.0, 1.0)):
    seq = list(color if color is not None else fallback) + [1.0, 1.0, 1.0, 1.0]
    return (float(seq[0]), float(seq[1]), float(seq[2]), float(seq[3]))


def _rgb_close(a, b, eps=0.02) -> bool:
    try:
        return all(abs(float(a[i]) - float(b[i])) <= eps for i in range(3))
    except Exception:
        return False


def _set_unlit_material_color(mat, color) -> None:
    """Keep Emission and the material-list swatch in sync (sRGB in, linear out)."""
    if mat is None:
        return
    lin = srgb_color_to_linear(_rgba4(color))
    try:
        if getattr(mat, "use_nodes", False) and mat.node_tree:
            for nd in mat.node_tree.nodes:
                if getattr(nd, "type", "") == "EMISSION":
                    nd.inputs["Color"].default_value = (
                        float(lin[0]), float(lin[1]), float(lin[2]), 1.0
                    )
                    break
    except Exception:
        pass
    try:
        mat.diffuse_color = (
            float(lin[0]), float(lin[1]), float(lin[2]), 1.0
        )
    except Exception:
        pass


def apply_parsed_run_materials(obj, parsed, base_color=(1.0, 1.0, 1.0, 1.0)) -> bool:
    """Map TMP ``<color>`` / ``<b>`` runs onto FONT material slots + bold.

    Slot 0 is always Unity ``m_Color`` / ``base_color``. Extra colours get
    ``_Mat1``, ``_Mat2``, … — never paint the default slot with the longest
    tagged run (that made the first swatch inherit the added colour).
    """
    if obj is None or parsed is None:
        return False
    if getattr(obj, "type", "") != "FONT" or obj.data is None:
        return False
    runs = list(getattr(parsed, "runs", None) or [])
    if len(runs) <= 1:
        # Single run may still need bold.
        if runs and bool(getattr(runs[0], "bold", False)):
            try:
                fmt = obj.data.body_format
                body = obj.data.body or ""
                for i in range(len(body)):
                    fmt[i].use_bold = True
                return True
            except Exception:
                return False
        return False
    base = _rgba4(base_color)
    colors = []
    for run in runs:
        if not (run.text or "").strip():
            continue
        col = _rgba4(getattr(run, "color", None), base)
        if not any(_rgb_close(col, c) for c in colors):
            colors.append(col)
    any_bold = any(bool(getattr(r, "bold", False)) for r in runs if (r.text or "").strip())
    if len(colors) <= 1 and not any_bold:
        return False
    curve = obj.data
    body = curve.body or ""
    if not body:
        return False
    slot_by_col = []
    try:
        if curve.materials:
            _set_unlit_material_color(curve.materials[0], base)
        slot_by_col.append((base, 0))
        for col in colors:
            if any(_rgb_close(col, k) for k, _s in slot_by_col):
                continue
            mat = make_unlit_color_material(
                "%s_Mat%s" % (obj.name, len(curve.materials)), col
            )
            curve.materials.append(mat)
            slot_by_col.append((col, len(curve.materials) - 1))
    except Exception:
        return False

    def _slot_for(col):
        for k, s in slot_by_col:
            if _rgb_close(col, k):
                return s
        return 0

    run_chars = []
    run_bolds = []
    for run in runs:
        col = _rgba4(getattr(run, "color", None), base)
        mi = _slot_for(col)
        bold = bool(getattr(run, "bold", False))
        for _ch in (run.text or ""):
            run_chars.append(mi)
            run_bolds.append(bold)
    try:
        fmt = curve.body_format
        n = min(len(body), len(run_chars))
        if n <= 0:
            return True
        if len(run_chars) != len(body) and run_chars:
            for i in range(len(body)):
                j = int(i * len(run_chars) / max(len(body), 1))
                j = min(j, len(run_chars) - 1)
                fmt[i].material_index = int(run_chars[j])
                try:
                    fmt[i].use_bold = bool(run_bolds[j])
                except Exception:
                    pass
        else:
            for i in range(n):
                fmt[i].material_index = int(run_chars[i])
                try:
                    fmt[i].use_bold = bool(run_bolds[i])
                except Exception:
                    pass
    except Exception:
        return False
    return True


def _dbg_agent_log(hypothesis_id, location, message, data=None, run_id="pre"):
    # #region agent log
    try:
        import json, time
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "debug-e00182.log"
        )
        rec = {
            "sessionId": "e00182",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


def create_rich_ui_text(
    collection,
    name,
    raw_text,
    font_size,
    base_color=(1.0, 1.0, 1.0, 1.0),
    pixel_scale=DEFAULT_PIXEL_SCALE,
    pivot=(0.0, 1.0),
    box_width=None,
    box_height=None,
    font_style=0,
    is_rich_text=True,
    text_alignment=0,
    line_spacing=0.0,
    enable_word_wrapping=True,
    margin=(0.0, 0.0, 0.0, 0.0),
    font_family="",
    locale="",
    character_spacing=0.0,
    word_spacing=0.0,
    paragraph_spacing=0.0,
    enable_auto_sizing=False,
    font_size_min=0.0,
    font_size_max=0.0,
    overflow_mode=0,
    row_pitch_px=None,
):
    """Build viewport text from TMP markup.

    Returns (root_object, display_plain).
    Raw markup must stay on ``ksp_ui.text`` for export; viewport shows
    stripped / styled content only.

    Text is laid out inside the RectTransform content box (pivot-local
    text_boxes offsets) so RIGHT/CENTER alignment matches Unity TMP —
    not the pivot alone.

    Multi-color runs become sibling FONT objects under an empty, laid out
    left-to-right / top-to-bottom using measured dimensions.
    """
    from .layout import (
        tmp_content_box_local,
        tmp_line_spacing_factor,
        tmp_text_align,
    )
    from .tmp_markup import TextStyle, dominant_style, parse_tmp_rich_text
    # font_size_min/max / overflow_mode: Unity fields for future autosize;
    # preview clamps via enable_auto_sizing + short-cell FaceInfo fit.

    raw_before = raw_text or ""
    raw_text = _figure_space_indent_lines(raw_before)

    global _LAYOUT_FORCE_PROFILE
    _prev_force = _LAYOUT_FORCE_PROFILE
    try:
        from .fonts_util import detect_script
        _script = detect_script(raw_text or "")
    except Exception:
        _script = "latin"
    _loc = (locale or "").lower()
    # Force CJK layout knobs only when *this* string is CJK — not for whole
    # zh-cn page (would smash Latin Amaranth/OpenSans titles & overlays).
    if _script in ("cjk", "mixed", "hangul", "kana"):
        _LAYOUT_FORCE_PROFILE = "cjk"
    try:
        result = _create_rich_ui_text_impl(
            collection, name, raw_text, font_size, base_color, pixel_scale,
            pivot, box_width, box_height, font_style, is_rich_text,
            text_alignment, line_spacing, enable_word_wrapping, margin,
            font_family, locale, character_spacing, word_spacing,
            paragraph_spacing, enable_auto_sizing, font_size_min, font_size_max,
            overflow_mode, row_pitch_px,
        )
        try:
            obj = result[0] if result else None
            if obj is not None:
                pref = overlay_lead_prefix(raw_before)
                if pref and (
                    obj.get("ksp_artwork_overlay")
                    or obj.get("ksp_origin_box")
                    or is_space_pad_overlay(raw_before)
                ):
                    obj["ksp_overlay_prefix"] = pref
                    try:
                        body = obj.data.body or ""
                        bpref = overlay_lead_prefix(body)
                        if bpref:
                            obj["ksp_overlay_body_prefix"] = bpref
                    except Exception:
                        pass
        except Exception:
            pass
        return result
    finally:
        _LAYOUT_FORCE_PROFILE = _prev_force


def _create_rich_ui_text_impl(
    collection,
    name,
    raw_text,
    font_size,
    base_color=(1.0, 1.0, 1.0, 1.0),
    pixel_scale=DEFAULT_PIXEL_SCALE,
    pivot=(0.0, 1.0),
    box_width=None,
    box_height=None,
    font_style=0,
    is_rich_text=True,
    text_alignment=0,
    line_spacing=0.0,
    enable_word_wrapping=True,
    margin=(0.0, 0.0, 0.0, 0.0),
    font_family="",
    locale="",
    character_spacing=0.0,
    word_spacing=0.0,
    paragraph_spacing=0.0,
    enable_auto_sizing=False,
    font_size_min=0.0,
    font_size_max=0.0,
    overflow_mode=0,
    row_pitch_px=None,
):
    from .layout import (
        tmp_content_box_local,
        tmp_line_spacing_factor,
        tmp_text_align,
    )
    from .tmp_markup import TextStyle, dominant_style, parse_tmp_rich_text

    base_bold = bool(int(font_style) & 1)
    base_italic = bool(int(font_style) & 2)
    base_underline = bool(int(font_style) & 4)
    style0 = TextStyle(
        bold=base_bold,
        italic=base_italic,
        underline=base_underline,
        color=tuple(base_color),
        size=float(font_size),
    )
    parsed = parse_tmp_rich_text(raw_text or "", style0)
    if not is_rich_text:
        from .tmp_markup import ParsedRichText, TextRun
        plain = raw_text or ""
        parsed = ParsedRichText(
            raw=plain,
            plain=plain,
            runs=[TextRun(
                text=plain, bold=base_bold, italic=base_italic,
                underline=base_underline, color=tuple(base_color), size=float(font_size),
            )],
            has_markup=False,
        )

    align_x, align_y = tmp_text_align(text_alignment, pivot)
    sx = float(pixel_scale)
    # Soft L/R inset ≈ TMP mesh padding so table cell copy doesn't kiss grid
    # lines. Top/bottom left alone (TOP snap / Midline handle vertical).
    try:
        ml, mt, mr, mb = [float(v) for v in margin]
    except Exception:
        ml = mt = mr = mb = 0.0
    # Soft L/R inset for tall multi-line columns so body copy doesn't kiss
    # grid lines. Skip on short one-line cells — padding there squeezes
    # headers like "Scientists" into the right divider.
    content_h_guess = None
    if box_height is not None:
        content_h_guess = float(box_height) - mt - mb
        if content_h_guess < 1.0:
            content_h_guess = float(box_height)
    face_pad_l = face_pad_r = 0.0
    width_bonus = 0.0
    is_title = float(font_size) >= float(TMP_FONT_TITLE_MIN_PX)
    # Stock KSPedia section titles use Amaranth even when m_fontAsset is an
    # external PPtr that failed to resolve (font_family empty → would pick Noto).
    if is_title and not (font_family or "").strip():
        font_family = "Amaranth"
    is_tall_col = (
        content_h_guess is not None
        and content_h_guess > float(font_size) * 1.45
    )
    is_short_cell = (
        content_h_guess is not None
        and float(font_size) < float(TMP_FONT_TITLE_MIN_PX)
        and content_h_guess <= float(font_size) * 1.5
    )
    plain_for_align_early = (parsed.plain or "").strip()
    single_line_early = (
        ("\n" not in plain_for_align_early)
        and ("\\n" not in plain_for_align_early)
    )
    # Short single-line cells (table labels/values): Middle* + no wrap squeeze.
    is_short_label = bool(is_short_cell and single_line_early)
    # Table grid only for short-line columns (not Career Limits / body prose).
    is_table_col = bool(
        is_tall_col
        and _looks_like_table_column(
            plain_for_align_early, box_width, font_size
        )
    )
    try:
        from .fonts_faceinfo import tmp_padding_px
        pad_floor = max(
            float(TMP_CELL_FACE_PAD_PX),
            0.35 * tmp_padding_px(font_size, font_family),
        )
    except Exception:
        pad_floor = float(TMP_CELL_FACE_PAD_PX)
    if is_table_col:
        # Table columns: soft left inset so body copy clears grid lines.
        face_pad_l = pad_floor
        face_pad_r = 0.0
        width_bonus = float(TMP_TABLE_COL_WIDTH_BONUS_PX)
    elif is_short_label and box_width is not None and float(box_width) > 1.0:
        # Colon headers (ConfS*): outline glyphs + punctuation need slack so
        # "…Vital:" does not spill past sizeDelta (ES/IT longer than EN).
        width_bonus = float(TMP_SHORT_LABEL_WRAP_BONUS_PX)
    elif (
        enable_word_wrapping
        and box_width is not None
        and float(box_width) > float(font_size) * 12.0
        and float(font_size) < float(TMP_FONT_TITLE_MIN_PX)
        and not is_short_label
        # Explicit \\n bullet lists (EVA) must wrap to the *true* rect —
        # large width_bonus made lines stay unwrapped and overflow the grey
        # panel (applauncher / deployedscience / maneuver callouts).
        and not _plain_multiline(plain_for_align_early)
    ):
        # Soft-wrap body: outline glyphs are a touch wider than TMP SDF.
        # One SHORT_LABEL bonus (~12px) is enough; the old 20–32px slack
        # pushed glyphs past grey/blueprint Images behind the text.
        width_bonus = float(TMP_SHORT_LABEL_WRAP_BONUS_PX)
    # Always keep a few px wrap slack for outline vs SDF — including texts
    # that already have Unity \\n between rows (Career Limits Level 2/3).
    if (
        enable_word_wrapping
        and box_width is not None
        and float(box_width) > 1.0
        and not is_short_label
        and not is_title
    ):
        width_bonus = max(float(width_bonus), float(TMP_WRAP_SLACK_PX))
    # PBS OpenSans: wrap slack from text role (+ content pull after box_w).
    _italic_early = (
        "italic" in (font_family or "").lower()
        or (int(font_style or 0) & 2) != 0
    )
    _bold_early = (
        "bold" in (font_family or "").lower()
        or (int(font_style or 0) & 1) != 0
    )
    _text_role = classify_text_role(
        font_family, font_size, plain_for_align_early, name,
        is_title=is_title, box_width_px=box_width,
        italic=_italic_early, bold=_bold_early,
    )
    if (
        enable_word_wrapping
        and box_width is not None
        and font_layout_profile(font_family) == "opensans"
        and not is_short_label
        and not is_title
    ):
        wb = _opensans_wrap_bonus_px(
            name, plain=plain_for_align_early, box_width_px=box_width,
            italic=_italic_early, text_role=_text_role,
        )
        if wb is None:
            pass  # intro: keep slack/SHORT_LABEL
        else:
            width_bonus = float(wb)
    # Short Midline labels: no margin face_pad (Unity uses m_margin only).
    # Horizontal wrap-guard inset for CENTER is applied in create_ui_text.
    margin_eff = (ml + face_pad_l, mt, mr + face_pad_r, mb)

    # Content box in pivot-local Blender units (lower-left + size).
    # Wrap slack must NOT re-center the rect (center pivots would shift +X
    # when width_bonus is negative) — pin left/bottom from the Unity size,
    # then grow/shrink only ``box_w`` for Blender wrap.
    box_x = box_y = 0.0
    box_w = box_h = None
    unity_box_w_bu = None
    max_h_px = None
    if box_width is not None and box_height is not None:
        local = tmp_content_box_local(
            float(box_width),
            float(box_height),
            pivot,
            margin_eff,
        )
        box_x = local[0] * sx
        box_y = local[1] * sx
        unity_box_w_bu = float(local[2]) * sx
        box_w = (local[2] + float(width_bonus)) * sx
        box_h = local[3] * sx
        # Content-driven: pull one more L1 word if deficit ≤ WRAP_PULL_MAX_PX.
        if (
            enable_word_wrapping
            and font_layout_profile(font_family) == "opensans"
            and not is_short_label
            and not is_title
            and _text_role not in ("intro",)
        ):
            try:
                fsize_probe = tmp_font_size_to_blender(
                    font_size, pixel_scale, max_height_px=None,
                    font_family=font_family,
                )
                pull = float(_wrap_pull_extra_px(
                    collection, plain_for_align_early, box_w, fsize_probe,
                    font_family=font_family, name=name,
                    italic=_italic_early, bold=_bold_early,
                    locale=locale, text_role=_text_role,
                ))
                if pull > 1e-6:
                    width_bonus = float(width_bonus) + pull
                    box_w = (local[2] + float(width_bonus)) * sx
            except Exception:
                pass
        content_h = content_h_guess if content_h_guess is not None else float(box_height)
        wide_paragraph = (
            box_width is not None
            and float(box_width) > float(font_size) * 8.0
        )
        # Clamp short cells when autosize OR FaceInfo size exceeds fit cap.
        fit = float(TMP_FONT_CELL_HEIGHT_FIT)
        face_bu = tmp_font_size_to_blender(
            font_size, pixel_scale, max_height_px=None, font_family=font_family,
        )
        cap_bu = float(content_h) * float(sx) * fit
        short_needs_clamp = (
            float(font_size) < float(TMP_FONT_TITLE_MIN_PX)
            and content_h <= float(font_size) * 1.5
            and not wide_paragraph
            and face_bu > cap_bu > 1e-8
        )
        if enable_auto_sizing or short_needs_clamp:
            max_h_px = content_h
        elif (
            # Tall explicit multi-line blocks (EVA bullets): shrink when the
            # TMP line box × n_lines exceeds the RectTransform height so text
            # stays inside the grey panel instead of overlapping the footer.
            is_tall_col
            and _plain_multiline(plain_for_align_early)
            and not is_table_col
            and content_h > 1.0
        ):
            try:
                from .fonts_faceinfo import tmp_line_em_ratio
                line_em = float(tmp_line_em_ratio(font_family))
                # Landscape body (high aspect) → FaceInfo size; near-square
                # panels stay eligible for content_h/n shrink. See
                # TMP_TALL_CLAMP_MAX_ASPECT_LINE_EM.
                aspect = float(box_width) / max(float(content_h), 1e-6)
                if aspect > line_em * float(TMP_TALL_CLAMP_MAX_ASPECT_LINE_EM):
                    max_h_px = None
                else:
                    n_lines = max(
                        1,
                        plain_for_align_early.replace("\\n", "\n").count("\n") + 1,
                    )
                    pitch_px = (
                        float(font_size)
                        * line_em
                        * float(tmp_line_spacing_factor(line_spacing))
                    )
                    if n_lines * pitch_px > float(content_h) * 1.02:
                        # Cap glyph height so n_lines fit in content_h.
                        max_h_px = float(content_h) / float(n_lines)
            except Exception:
                max_h_px = None
        else:
            max_h_px = None
    elif box_width is not None:
        # Width-only: still offset horizontally around pivot.
        local = tmp_content_box_local(
            float(box_width),
            float(box_width),
            pivot,
            margin_eff,
        )
        box_x = local[0] * sx
        box_y = 0.0
        unity_box_w_bu = float(local[2]) * sx
        box_w = (local[2] + float(width_bonus)) * sx
        box_h = None

    header_fit = float(TMP_TABLE_HEADER_CELL_FIT)
    default_size = tmp_font_size_to_blender(
        font_size, pixel_scale, max_height_px=max_h_px, cell_fit=header_fit,
        font_family=font_family,
    )
    ls_factor = tmp_line_spacing_factor(line_spacing)
    try:
        from .fonts_faceinfo import tmp_line_em_ratio
        line_em = tmp_line_em_ratio(font_family)
        # Map TMP line box to Blender space_line (default ≈1.25 relative).
        body_ls = float(font_layout_get(
            font_family, "BODY_LINE_SPACING_MUL", TMP_BODY_LINE_SPACING_MUL
        ))
        # UI.Text OpenSans outline: Blender space_line=1.0 already tracks the
        # TTF's built-in line gap. Do NOT apply the TMP 1.25/line_em remap
        # (that left ConfT wraps ~1.00 and too open vs Unity raster).
        if font_layout_profile(font_family) == "opensans":
            body_ls = float(role_layout_get(
                font_family, _text_role, "BODY_LINE_SPACING_MUL", body_ls
            ) or body_ls)
            ls_mul = body_ls
        else:
            ls_mul = body_ls * (1.25 / max(line_em, 0.5))
        if is_title:
            ls_mul = 1.0
    except Exception:
        ls_mul = 1.0 if is_title else float(font_layout_get(
            font_family, "BODY_LINE_SPACING_MUL", TMP_BODY_LINE_SPACING_MUL
        ))
    ls_factor *= ls_mul

    plain_lower = (parsed.plain or "").lower()
    # Edge newlines are Unity padding, not real multi-line content.
    # Normalize Unity soft-wraps before blank-line split / short-followup
    # detection (otherwise orphan ``them\\nseparately`` skips gap mul).
    plain_for_align = _prepare_display_body(
        (parsed.plain or "").strip("\n\r")
    )
    is_note = plain_lower.lstrip().startswith("note:")
    note_dx = note_dy = 0.0
    single_line = ("\n" not in plain_for_align) and ("\\n" not in plain_for_align)
    wide_paragraph = (
        box_width is not None
        and float(box_width) > float(font_size) * 8.0
    )

    # Side callouts: TopRight multiline → Center Y on the baked leader.
    # Hole overlays (ConfT1/T2) stay TOP — CENTER Y inside the hole is the
    # jump to the former box center.
    origin_overlay = _is_origin_overlay_text(
        name, raw_text, box_width, box_height, font_size,
    )
    if (
        not origin_overlay
        and align_y == "TOP"
        and align_x == "RIGHT"
        and box_h is not None
        and ("\n" in plain_for_align or "\\n" in plain_for_align)
    ):
        align_y = "CENTER"

    # Honor Unity alignment bits only — do NOT invent Middle Y for short/narrow
    # TopLeft rects (controls-flight "Pitch forward" etc. sat ~½·(box−line) low).
    plain_strip = plain_for_align.strip()
    is_digit_cell = plain_strip.isdigit() or (
        len(plain_strip) <= 3 and plain_strip.replace(".", "").isdigit()
    )
    align_has_center_x = False
    try:
        _a = int(text_alignment or 0)
        align_has_center_x = bool(_a & 0x2) or _a in (1, 4, 7)
    except Exception:
        align_has_center_x = False
    if is_digit_cell or (align_has_center_x and not origin_overlay):
        align_x = "CENTER"

    # Multi-line Level index column (0..5): Center X like JPG.
    if is_table_col:
        _pl = plain_for_align.replace("\\n", "\n")
        _lines = _pl.split("\n")
        if _lines and all(
            (ln.strip().isdigit() or ln.strip() == "") for ln in _lines
        ):
            align_x = "CENTER"

    # Single run or uniform style → one FONT
    colors = {r.color for r in parsed.runs if r.text.strip()}
    sizes = {r.size for r in parsed.runs if r.text.strip()}
    uniform = (
        (not TMP_SPLIT_RICH_RUNS)
        or len(parsed.runs) <= 1
        or (len(colors) <= 1 and len(sizes) <= 1)
    )
    if uniform:
        bold, italic, underline, color, sz = dominant_style(parsed, base_color)
        # One FONT + extra slots for <color> runs. Slot 0 must stay Unity
        # m_Color — longest tagged run used to paint the default material.
        try:
            distinct = set()
            for r in parsed.runs:
                if not (r.text or "").strip():
                    continue
                cc = r.color if getattr(r, "color", None) is not None else base_color
                distinct.add(tuple(round(float(x), 3) for x in list(cc)[:3]))
            if len(distinct) > 1:
                color = tuple(base_color)
        except Exception:
            pass
        _text_role = classify_text_role(
            font_family, font_size, plain_for_align, name,
            is_title=is_title, box_width_px=box_width,
            italic=italic, bold=bold,
        )
        fsize = tmp_font_size_to_blender(
            sz if sz else font_size, pixel_scale,
            max_height_px=max_h_px, cell_fit=header_fit,
            font_family=font_family,
        )
        # Blank-line paragraphs: independent RectY + metric gap.
        intro_parts = (
            _split_intro_paragraphs(plain_for_align)
            if (wide_paragraph and box_h is not None)
            else None
        )
        if intro_parts is not None:
            para_as, para_each = intro_parts
            root = _create_intro_split_paragraphs(
                collection, name, para_as, para_each, fsize, color, align_x,
                box_x, box_y if box_h is not None else 0.0, box_w, box_h, sx,
                font_family=font_family, locale=locale, bold=bold,
                italic=italic, underline=underline, line_spacing=line_spacing,
                ls_mul=ls_mul, word_wrap=bool(enable_word_wrapping),
                paragraph_spacing=paragraph_spacing,
                font_size_px=float(font_size),
                character_spacing=character_spacing,
                word_spacing=word_spacing,
                unity_box_width_px=box_width,
            )
            return root, parsed.plain
        # Tall Level/role columns: one FONT per row on grid pitch.
        if (
            TMP_SPLIT_TABLE_ROWS
            and is_table_col
            and box_h is not None
            and _plain_multiline(plain_for_align)
        ):
            lines = _normalize_tmp_newlines(plain_for_align).split(chr(10))
            root = _create_tall_column_rows(
                collection, name, lines, fsize, color, align_x,
                box_x, box_y if box_h is not None else 0.0, box_w, box_h, sx,
                font_family=font_family, locale=locale, bold=bold,
                italic=italic, underline=underline, line_spacing=line_spacing,
                ls_mul=ls_mul, row_pitch_px=row_pitch_px,
                character_spacing=character_spacing,
                word_spacing=word_spacing,
            )
            ndx, ndy = _nudge_for_plain(plain_for_align)
            if abs(ndx) > 1e-9 or abs(ndy) > 1e-9:
                for c in root.children:
                    c.location = (
                        c.location.x + ndx * sx,
                        c.location.y + ndy * sx,
                        c.location.z,
                    )
            return root, parsed.plain
        force_no_wrap = (
            is_short_label
            or is_title
            or (not enable_word_wrapping)
        )
        # Single-line titles / section labels: Blender wraps on text_boxes.width;
        # grow box so "Own Subcategory:" / "Landing without atmosphere" stay 1 line
        # — unless a colon header sits in a tall rect that can take a 2nd line.
        title_box_w = box_w
        title_box_x = box_x
        display_plain = parsed.plain
        colon_label = bool(
            single_line
            and plain_strip.endswith(":")
            and float(font_size) >= 20.0
            and len(plain_strip) <= 40
            and not is_title
        )
        colon_can_wrap = bool(
            colon_label
            and enable_word_wrapping
            and _colon_header_box_can_wrap(box_h, sx, font_size)
        )
        colon_overflows = False
        wrap_against = unity_box_w_bu if unity_box_w_bu else box_w
        if colon_can_wrap and wrap_against is not None:
            try:
                need_c = _measure_font_width(
                    collection, plain_strip or parsed.plain, fsize,
                    bold=bold, italic=italic, font_family=font_family,
                    locale=locale, name=name,
                )
                from .fonts_faceinfo import display_x_scale, tmp_padding_px
                xs_c = float(display_x_scale(font_family))
                need_c *= xs_c
                pad_c = max(
                    12.0 * sx,
                    float(tmp_padding_px(font_size, font_family)) * sx,
                    0.08 * float(need_c),
                )
                # Compare to the Unity rect, not the Blender wrap-slack box.
                # Slack made FR ConfS3 look like it fit on one line.
                colon_overflows = float(need_c) + float(pad_c) > float(wrap_against)
            except Exception:
                colon_overflows = False
        # Tall colon header that overflows: wrap inside the rect (glue "word:").
        if colon_can_wrap and colon_overflows:
            force_no_wrap = False
            try:
                display_plain = _wrap_colon_header_to_width(
                    collection, parsed.plain or "", fsize, wrap_against,
                    bold=bold, italic=italic, font_family=font_family,
                    locale=locale, name=name,
                )
            except Exception:
                display_plain = _glue_trailing_colon(parsed.plain or "")
            if unity_box_w_bu is not None:
                title_box_w = float(unity_box_w_bu)
                title_box_x = float(box_x)
        grow_single = bool(
            single_line and box_w is not None and (
                is_title
                or (
                    # Colon labels: grow only when a 2nd line would not fit
                    # in this text's own tall box (else wrap above).
                    colon_label
                    and not (colon_can_wrap and colon_overflows)
                )
                or (
                    # Short section headers without trailing ':' (RE1).
                    float(font_size) >= 45.0
                    and len(plain_strip) <= 40
                    and not plain_strip.endswith(":")
                )
                or (
                    # Barely-overflow one-liners in a *short* rect (Subheader,
                    # Landing-Leg captions) — prefer 1 line over colliding.
                    # Compare height in Unity px (not BU vs curve.size) so a
                    # tall callout rect (Cargo Mode ~235px) never matches.
                    # Skip wide soft-wrap body/callouts: growing the box past
                    # the page Background lets glyphs exit the blue panel.
                    box_h is not None
                    and (
                        float(box_h) / max(float(sx), 1e-9)
                    ) <= float(font_size) * 2.6
                    and 0 < len(plain_strip) <= 120
                    and not wide_paragraph
                    and not (colon_can_wrap and colon_overflows)
                )
            )
        )
        if grow_single:
            force_no_wrap = True
            try:
                need = _measure_font_width(
                    collection, plain_strip or parsed.plain, fsize,
                    bold=bold, italic=italic, font_family=font_family,
                    locale=locale, name=name,
                )
                from .fonts_faceinfo import display_x_scale, tmp_padding_px
                xs = display_x_scale(font_family)
                if abs(float(TMP_TITLE_X_SCALE) - 1.0) > 1e-6:
                    xs = float(TMP_TITLE_X_SCALE)
                elif is_title:
                    fam_l = (font_family or "").lower()
                    if "amaranth" in fam_l and "sdf" not in fam_l:
                        xs = 1.045
                need *= float(xs)
                pad = max(
                    12.0 * sx,
                    float(tmp_padding_px(font_size, font_family)) * sx,
                    0.08 * float(need),
                )
                if need + pad > float(box_w):
                    title_box_w = need + pad
                    dw = float(title_box_w) - float(box_w)
                    if align_x == "CENTER":
                        title_box_x = float(box_x) - 0.5 * dw
                    elif align_x == "RIGHT":
                        title_box_x = float(box_x) - dw
            except Exception:
                title_box_w = box_w
                title_box_x = box_x
        # Always pass title_box_* (defaults to box_*); grow_single widens
        # section labels too, not only is_title headers.
        # ConfT1/T2: keep the Unity hole content box (top-left of the rect).
        # Zeroing box_x glued glyphs to the pivot (former box center).
        obj = create_ui_text(
            collection,
            name,
            display_plain,
            fsize,
            color,
            align_x=align_x,
            align_y=align_y,
            bold=bold,
            italic=italic,
            box_width=title_box_w,
            box_height=box_h,
            line_spacing=line_spacing,
            word_wrap=False if force_no_wrap else bool(enable_word_wrapping),
            box_x=title_box_x,
            box_y=box_y if box_h is not None else 0.0,
            font_family=font_family,
            locale=locale,
            line_spacing_mul=ls_mul,
            character_spacing=character_spacing,
            word_spacing=word_spacing,
            tmp_font_size=float(sz if sz else font_size),
            text_role=_text_role,
            unity_box_width_px=box_width,
        )
        try:
            obj["ksp_text_align"] = "%s/%s" % (align_x, align_y)
            obj["ksp_line_spacing"] = float(line_spacing)
            if origin_overlay or _is_space_pad_overlay(name, raw_text):
                obj["ksp_origin_box"] = True
                obj["ksp_artwork_overlay"] = True
        except Exception:
            pass
        try:
            apply_parsed_run_materials(obj, parsed, base_color)
        except Exception:
            pass
        if underline:
            add_text_underline(collection, obj, color, name=name)
        obj["ksp_text_underline"] = bool(underline)
        # Left colon-labels (Habitat MK2:) — nudge a few px away from body.
        colon_nudge = float(font_layout_get(
            font_family, "COLON_LABEL_NUDGE_X_PX", TMP_COLON_LABEL_NUDGE_X_PX
        ))
        if (
            plain_strip.endswith(":")
            and float(font_size) >= 40.0
            and len(plain_strip) <= 24
            and single_line
            and abs(colon_nudge) > 1e-6
        ):
            try:
                dx = -colon_nudge * float(sx)
                tb = obj.data.text_boxes[0]
                tb.x = float(tb.x) + dx
            except Exception:
                obj.location = (
                    obj.location.x - colon_nudge * float(sx),
                    obj.location.y,
                    obj.location.z,
                )
        if is_title:
            try:
                from .fonts_faceinfo import display_x_scale
                xs = display_x_scale(font_family)
                if abs(float(TMP_TITLE_X_SCALE) - 1.0) > 1e-6:
                    xs = float(TMP_TITLE_X_SCALE)
                else:
                    # PBS UI.Text Amaranth Bold (ConfHeader) needs ~5% more
                    # X than Regular section headers at the same CAP.
                    fam_l = (font_family or "").lower()
                    if "amaranth" in fam_l and "sdf" not in fam_l:
                        xs = 1.045
                old_sx = float(obj.scale[0]) or 1.0
                obj.scale = (xs, 1.0, 1.0)
                # Same left-edge compensate as create_ui_text outline_x_scale.
                if abs(float(xs) - old_sx) > 1e-6:
                    try:
                        tb = obj.data.text_boxes[0]
                        if align_x == "RIGHT":
                            right = float(tb.x) + float(tb.width)
                            tb.x = right * old_sx / xs - float(tb.width)
                        elif align_x == "CENTER":
                            mid = float(tb.x) + 0.5 * float(tb.width)
                            tb.x = mid * old_sx / xs - 0.5 * float(tb.width)
                        else:
                            tb.x = float(tb.x) * old_sx / xs
                    except Exception:
                        pass
                # TITLE_BLOCK_NUDGE_* applied in create_ui_text for is_title.
            except Exception:
                pass
        if abs(note_dx) > 1e-9 or abs(note_dy) > 1e-9:
            try:
                tb = obj.data.text_boxes[0]
                tb.x = float(tb.x) + note_dx
                tb.y = float(tb.y) + note_dy
            except Exception:
                obj.location = (
                    obj.location.x + note_dx,
                    obj.location.y + note_dy,
                    obj.location.z,
                )
        # Optional debug nudges (KSP_CALIB_NUDGES=1 only).
        ndx, ndy = _nudge_for_plain(plain_for_align)
        if abs(ndx) > 1e-9 or abs(ndy) > 1e-9:
            try:
                tb = obj.data.text_boxes[0]
                tb.x = float(tb.x) + ndx * sx
                tb.y = float(tb.y) + ndy * sx
            except Exception:
                obj.location = (
                    obj.location.x + ndx * sx,
                    obj.location.y + ndy * sx,
                    obj.location.z,
                )
        if is_short_label:
            _register_table_header_font(obj)
        return obj, parsed.plain

    # Multi-style: empty root at pivot + FONT children laid out like TMP
    # (top→bottom, wrap inside content box). Horizontal align is *per line*
    # (Unity TopRight flush-right each line toward the callout dots — a
    # whole-block shift left shorter lines ragged on the right).
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.01
    collection.objects.link(root)

    left = box_x if box_w is not None else 0.0
    bottom = box_y if box_h is not None else 0.0
    top = (bottom + box_h) if box_h is not None else 0.0
    right = (left + box_w) if box_w is not None else None
    cursor_x = left
    cursor_y = top
    # ls_factor already maps TMP LineHeight → Blender (includes 1.25/line_em).
    # Do NOT multiply another 1.25 here — that overshot Strategies/MC/RnD/TS
    # callouts by ~30% (rich size=40 + <size=35> path).
    line_height = default_size * ls_factor
    line_start_x = left
    max_x = right
    run_counter = [0]
    # Each entry: list of FONT objects on the current line
    line_objs = []
    finished_lines = []  # list[list[obj]]

    def _flush_line():
        nonlocal line_objs, cursor_x
        if line_objs:
            finished_lines.append(line_objs)
            line_objs = []
        cursor_x = line_start_x

    def _place_segment(seg_text, run, fsize, col):
        if not seg_text:
            return
        nonlocal cursor_x, cursor_y, line_height
        idx = run_counter[0]
        run_counter[0] = idx + 1
        child = create_ui_text(
            collection,
            "%s_r%s" % (name, idx),
            seg_text,
            fsize,
            col,
            align_x="LEFT",
            align_y="TOP",
            bold=run.bold,
            italic=run.italic,
            box_width=None,
            line_spacing=line_spacing,
            word_wrap=False,
            font_family=font_family,
            locale=locale,
            line_spacing_mul=ls_mul,
            character_spacing=character_spacing,
            word_spacing=word_spacing,
        )
        child.parent = root
        child.location = (cursor_x, cursor_y, 0.02)
        if run.underline:
            add_text_underline(
                collection, child, col, name="%s_r%s" % (name, idx),
            )
        child["ksp_text_underline"] = bool(run.underline)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        # dimensions.x is often 0 right after create — always prefer measure.
        w = _font_obj_width(child, size=fsize, text=seg_text)
        if w < 1e-6:
            w = _measure_font_width(
                collection, (child.data.body if child.type == "FONT" else seg_text),
                fsize, bold=run.bold, italic=run.italic,
                font_family=font_family, locale=locale, name=name,
            )
        try:
            lead_dx = float(child.get("ksp_lead_dx", 0.0))
        except Exception:
            lead_dx = 0.0
        cursor_x += max(w, 0.0) + max(lead_dx, 0.0)
        # Bold/colored outline runs often render wider than the measure pass.
        if run.bold or (
            run.color is not None and run.color != base_color
        ):
            try:
                cursor_x += float(TMP_RICH_RUN_PAD_PX) * float(sx)
                w += float(TMP_RICH_RUN_PAD_PX) * float(sx)
            except Exception:
                pass
        try:
            child["ksp_run_width"] = float(w + max(lead_dx, 0.0))
        except Exception:
            pass
        line_objs.append(child)
        # #region agent log
        if run.bold or (run.color is not None and run.color != base_color):
            _dbg_agent_log(
                "H3",
                "viewport.rich_place",
                "colored_or_bold_run",
                {
                    "name": name or "",
                    "bold": bool(run.bold),
                    "w": round(float(w), 5),
                    "cursor_x": round(float(cursor_x), 5),
                    "seg": repr((seg_text or "")[:60]),
                    "pad_px": float(TMP_RICH_RUN_PAD_PX),
                },
            )
        # #endregion

    def _split_long_token(tok: str):
        """Break paths / long identifiers so they can wrap (GameData/…)."""
        if not tok or tok.isspace() or len(tok) < 12:
            return [tok]
        parts = []
        buf = ""
        for ch in tok:
            buf += ch
            if ch in "/\\-_." and len(buf) >= 4:
                parts.append(buf)
                buf = ""
        if buf:
            parts.append(buf)
        return parts if parts else [tok]

    for i, run in enumerate(parsed.runs):
        if not run.text:
            continue
        fsize = tmp_font_size_to_blender(
            run.size if run.size else font_size, pixel_scale,
            max_height_px=max_h_px, cell_fit=header_fit,
            font_family=font_family,
        )
        col = run.color if run.color is not None else base_color
        run_lh = fsize * ls_factor
        parts = run.text.split("\n")
        for pi, part in enumerate(parts):
            if pi > 0:
                _flush_line()
                cursor_y -= max(line_height, run_lh)
                # New line: pitch from this run size, not prior max (b40→s35).
                line_height = run_lh
            else:
                line_height = max(line_height, run_lh)
            if part == "":
                # Empty split piece (leading/trailing/blank line). When pi > 0
                # the Y step above already advanced to the next line.
                continue
            # Word-wrap rich runs inside the TMP content box.
            if max_x is None or not enable_word_wrapping:
                _place_segment(part, run, fsize, col)
                continue
            buf = ""
            tokens = []
            cur = ""
            try:
                from .fonts_util import _is_cjk_wrap_char as _cjk_ch
            except Exception:
                def _cjk_ch(_c):
                    return False
            for ch in part:
                if ch.isspace():
                    if cur:
                        tokens.append(cur)
                        cur = ""
                    tokens.append(ch)
                elif _cjk_ch(ch):
                    # Per-glyph tokens so CJK wraps like Unity TMP.
                    if cur:
                        tokens.append(cur)
                        cur = ""
                    tokens.append(ch)
                else:
                    cur += ch
            if cur:
                tokens.append(cur)
            # Further split path-like tokens.
            flat = []
            for tok in tokens:
                if tok and not tok.isspace() and any(c in tok for c in "/\\"):
                    flat.extend(_split_long_token(tok))
                else:
                    flat.append(tok)
            tokens = flat
            for tok in tokens:
                trial = buf + tok
                trial_w = _measure_font_width(
                    collection, trial, fsize,
                    bold=run.bold, italic=run.italic,
                    font_family=font_family, locale=locale, name=name,
                )
                limit = (
                    ((max_x - line_start_x) if max_x is not None else 1e9)
                    + 1e-6
                )
                used = cursor_x - line_start_x
                if (
                    buf
                    and tok.strip()
                    and used + trial_w > limit
                ):
                    _place_segment(buf, run, fsize, col)
                    _flush_line()
                    cursor_y -= max(line_height, run_lh)
                    line_height = run_lh
                    if tok.isspace():
                        buf = ""
                        continue
                    buf = tok
                elif (
                    (not buf)
                    and tok.strip()
                    and used + trial_w > limit
                    and used > 1e-6
                ):
                    # Token alone does not fit remainder — wrap first.
                    _flush_line()
                    cursor_y -= max(line_height, run_lh)
                    line_height = run_lh
                    buf = tok
                else:
                    buf = trial
            if buf:
                _place_segment(buf, run, fsize, col)
    _flush_line()

    # Per-line horizontal align + optional vertical block align.
    try:
        bpy.context.view_layer.update()
        for objs in finished_lines:
            if not objs or box_w is None:
                continue
            min_x = min(c.location.x for c in objs)
            widths = []
            for c in objs:
                rw = 0.0
                try:
                    rw = float(c.get("ksp_run_width", 0.0))
                except Exception:
                    rw = 0.0
                if rw < 1e-8:
                    rw = _font_obj_width(c, size=default_size)
                if rw < 1e-8:
                    try:
                        rw = _measure_font_width(
                            collection, c.data.body, float(c.data.size),
                            bold=bool(c.get("ksp_text_bold", False)),
                            italic=bool(c.get("ksp_text_italic", False)),
                            font_family=font_family, locale=locale, name=name,
                        )
                    except Exception:
                        rw = 0.0
                widths.append(rw)
            max_x_line = max(
                c.location.x + w for c, w in zip(objs, widths)
            )
            dx = 0.0
            if align_x == "RIGHT" and right is not None:
                dx = right - max_x_line
            elif align_x == "CENTER" and right is not None:
                dx = (left + right) * 0.5 - (min_x + max_x_line) * 0.5
            if abs(dx) > 1e-9:
                for c in objs:
                    c.location = (c.location.x + dx, c.location.y, c.location.z)
        if box_h is not None and align_y in ("BOTTOM", "CENTER"):
            kids = [c for c in root.children if c.type == "FONT"]
            if kids:
                min_y = min(
                    c.location.y - max(float(c.dimensions.y), 0.0) for c in kids
                )
                max_y = max(c.location.y for c in kids)
                dy = 0.0
                if align_y == "BOTTOM":
                    dy = bottom - min_y
                else:
                    dy = (bottom + top) * 0.5 - (min_y + max_y) * 0.5
                if abs(dy) > 1e-9:
                    for c in root.children:
                        c.location = (
                            c.location.x, c.location.y + dy, c.location.z,
                        )
        elif (
            TMP_TOP_ASCENDER_SNAP
            and box_h is not None
            and align_y == "TOP"
            and finished_lines
            and finished_lines[0]
        ):
            # Snap first-line glyph tops to content-box top (uniform TOP path).
            peak = None
            for c in finished_lines[0]:
                for bb in c.bound_box:
                    y = c.location.y + float(bb[1])
                    peak = y if peak is None else max(peak, y)
            if peak is not None:
                nudge = float(font_layout_get(font_family, "TOP_EXTRA_NUDGE_BU", 0.0)) * (
                    float(sx) / 0.001
                )
                dy = top - peak + nudge
                if abs(dy) > 1e-9:
                    for c in root.children:
                        c.location = (
                            c.location.x, c.location.y + dy, c.location.z,
                        )
    except Exception:
        pass

    # Table columns (rich text): per-row JPG grid — only when wrap did not
    # invent extra visual lines (Career Limits etc. keep natural leading).
    if TMP_SPLIT_TABLE_ROWS and is_table_col and box_h is not None and finished_lines:
        if len(finished_lines) == _plain_n_lines(plain_for_align):
            _center_tall_column_root(
                root, plain_for_align, box_h, sx, box_top=top,
                finished_lines=finished_lines, row_pitch_px=row_pitch_px,
            )
    # Intro split is handled on the uniform path; multi-style intro is rare.

    if abs(note_dx) > 1e-9 or abs(note_dy) > 1e-9:
        try:
            for c in root.children:
                c.location = (
                    c.location.x + note_dx,
                    c.location.y + note_dy,
                    c.location.z,
                )
        except Exception:
            pass

    ndx, ndy = _nudge_for_plain(plain_for_align)
    if abs(ndx) > 1e-9 or abs(ndy) > 1e-9:
        try:
            for c in root.children:
                c.location = (
                    c.location.x + ndx * sx,
                    c.location.y + ndy * sx,
                    c.location.z,
                )
        except Exception:
            pass

    try:
        root["ksp_text_align"] = "%s/%s" % (align_x, align_y)
    except Exception:
        pass
    # #region agent log
    try:
        from .locale_switch import _dbg, _dbg_curve
        _dbg("A,D", "create_rich_ui_text baseline", {
            "obj": getattr(root, "name", ""),
            "curve": _dbg_curve(root),
            "plain": (parsed.plain or "")[:40],
        }, limit=14)
    except Exception:
        pass
    # #endregion
    return root, parsed.plain


def fit_text_object_to_box(
    obj,
    box_width_px=None,
    box_height_px=None,
    pixel_scale=DEFAULT_PIXEL_SCALE,
    locale="",
    plain="",
    max_iters=10,
    soft=False,
):
    """Shrink character / line spacing (then size) so text fits the Rect box.

    Used after locale switch when .lang ships a different sizeDelta and the
    translated string is longer than the English calibration assumed.
    ``soft`` raises floors so short section labels are not crushed to spaghetti.
    """
    if obj is None:
        return False
    try:
        sx = float(pixel_scale) if pixel_scale else DEFAULT_PIXEL_SCALE
    except Exception:
        sx = DEFAULT_PIXEL_SCALE
    max_w = None
    max_h = None
    try:
        if box_width_px is not None and float(box_width_px) > 1.0:
            max_w = float(box_width_px) * sx * 1.02
        if box_height_px is not None and float(box_height_px) > 1.0:
            max_h = float(box_height_px) * sx * 1.02
    except Exception:
        return False
    if max_w is None and max_h is None:
        return False

    fonts = []
    if getattr(obj, "type", "") == "FONT" and getattr(obj, "data", None):
        fonts = [obj]
    else:
        try:
            fonts = [
                c for c in getattr(obj, "children_recursive", []) or []
                if getattr(c, "type", "") == "FONT" and getattr(c, "data", None)
                and not c.get("ksp_outline_ghost")
            ]
        except Exception:
            fonts = []
    if not fonts:
        return False

    try:
        from .fonts_util import detect_script
        script = detect_script(plain or "")
    except Exception:
        script = "latin"
    # Script from glyphs only — locale must not soften Latin fit on zh-cn.
    is_cjk = script in ("cjk", "mixed", "hangul", "kana")

    changed = False
    # Remember original sizes so CJK fit cannot crush glyphs.
    orig_sizes = {}
    for fobj in fonts:
        try:
            orig_sizes[fobj] = float(fobj.data.size)
        except Exception:
            pass

    max_iters_eff = 4 if is_cjk else int(max_iters)
    if soft:
        max_iters_eff = min(max_iters_eff, 3)
    char_floor = 0.90 if soft else (0.70 if is_cjk else 0.75)
    word_floor = 0.90 if soft else (0.70 if is_cjk else 0.75)
    size_floor_mul = 0.94 if soft else (0.92 if is_cjk else 0.85)
    for _ in range(max_iters_eff):
        # Force depsgraph-ish bounds by reading dimensions
        try:
            if getattr(obj, "type", "") == "FONT":
                dim_x = float(obj.dimensions.x)
                dim_y = float(obj.dimensions.y)
            else:
                dim_x = max(float(c.dimensions.x) for c in fonts)
                try:
                    dim_y = float(obj.dimensions.y)
                    if dim_y < 1e-6:
                        dim_y = max(float(c.dimensions.y) for c in fonts)
                except Exception:
                    dim_y = max(float(c.dimensions.y) for c in fonts)
        except Exception:
            break
        over_w = max_w is not None and dim_x > max_w
        over_h = max_h is not None and dim_y > max_h
        if not over_w and not over_h:
            break
        for fobj in fonts:
            curve = fobj.data
            try:
                if over_w:
                    curve.space_character = max(
                        char_floor,
                        float(curve.space_character) * (0.96 if is_cjk else 0.93),
                    )
                    curve.space_word = max(
                        word_floor,
                        float(curve.space_word) * (0.97 if is_cjk else 0.95),
                    )
                if over_h:
                    curve.space_line = max(
                        0.85 if is_cjk else 0.80,
                        float(curve.space_line) * (0.96 if is_cjk else 0.94),
                    )
                # CJK: soft fit may shrink a little after wrap; hard path stays shy.
                if (over_w or over_h) and not is_cjk:
                    floor = float(orig_sizes.get(fobj, curve.size)) * size_floor_mul
                    curve.size = max(floor, float(curve.size) * (0.98 if soft else 0.97))
                elif (over_w or over_h) and is_cjk:
                    floor = float(orig_sizes.get(fobj, curve.size)) * (
                        0.88 if soft else 0.92
                    )
                    curve.size = max(
                        floor, float(curve.size) * (0.97 if soft else 0.99)
                    )
                changed = True
            except Exception:
                pass
    return changed


def attach_text_outline_preview(
    obj,
    outline_width_px=1.0,
    outline_color=(0.0, 0.0, 0.0, 1.0),
    pixel_scale=DEFAULT_PIXEL_SCALE,
    effect_distance=(1.0, -1.0),
):
    """Approximate TMP/UI Outline/Shadow with offset FONT ghost copies.

    Unity Outline draws the mesh several times at ``effectDistance`` offsets;
    we spawn up to 4 dim copies behind the main text.
    """
    if obj is None or getattr(obj, "type", "") != "FONT":
        return
    # Never stack outline ghosts on already-ghosted copies.
    try:
        if obj.get("ksp_outline_ghost"):
            return
    except Exception:
        pass
    # Remove previous ghosts so locale rebuild / re-attach cannot duplicate ALT.
    try:
        for child in list(obj.children):
            if child.get("ksp_outline_ghost"):
                data = getattr(child, "data", None)
                bpy.data.objects.remove(child, do_unlink=True)
                if data is not None and getattr(data, "users", 1) == 0:
                    try:
                        bpy.data.curves.remove(data)
                    except Exception:
                        pass
    except Exception:
        pass
    try:
        sx = float(pixel_scale)
        dx_u, dy_u = float(effect_distance[0]), float(effect_distance[1])
        if abs(dx_u) < 1e-6 and abs(dy_u) < 1e-6:
            w = max(float(outline_width_px), 1.0)
            dx_u, dy_u = w, -w
        offs = (
            (dx_u, dy_u),
            (-dx_u, dy_u),
            (dx_u, -dy_u),
            (-dx_u, -dy_u),
        )
        col = tuple(float(c) for c in outline_color[:4])
        if len(col) < 4:
            col = (0.0, 0.0, 0.0, 0.6)
        src = obj.data
        for i, (ox, oy) in enumerate(offs[:4]):
            ghost_data = src.copy()
            ghost = bpy.data.objects.new("%s_outline%d" % (obj.name, i), ghost_data)
            ghost.parent = obj
            ghost.location = (ox * sx, oy * sx, -0.0005 * (i + 1))
            ghost.scale = (1.0, 1.0, 1.0)
            ghost.rotation_euler = (0.0, 0.0, 0.0)
            try:
                ghost.hide_select = True
            except Exception:
                pass
            # Link into same collections as parent
            for coln in list(obj.users_collection) or []:
                try:
                    coln.objects.link(ghost)
                except Exception:
                    pass
            try:
                mat = make_unlit_color_material(
                    "%s_olmat%d" % (obj.name, i), col
                )
                if ghost.data.materials:
                    ghost.data.materials[0] = mat
                else:
                    ghost.data.materials.append(mat)
            except Exception:
                pass
            try:
                ghost["ksp_outline_ghost"] = True
            except Exception:
                pass
    except Exception:
        pass


def ui_element_local_pos(element, pixel_scale=DEFAULT_PIXEL_SCALE):
    """Deprecated shim — prefer layout.compute_all_rects."""
    ax, ay = element.anchored_position
    sx = float(pixel_scale)
    return Vector((ax * sx, ay * sx, 0.0))


def ui_element_text_pos(element, pixel_scale=DEFAULT_PIXEL_SCALE):
    """Deprecated shim — prefer layout.compute_all_rects."""
    ax, ay = element.anchored_position
    sx = float(pixel_scale)
    return Vector((ax * sx, ay * sx, 0.001))


def setup_ui_view(context=None):
    """Set active 3D view to orthographic MATERIAL shading for UI preview."""
    ctx = context or bpy.context
    screen = getattr(ctx, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        if space is None:
            continue
        try:
            space.shading.type = 'MATERIAL'
        except Exception:
            pass
        try:
            region = space.region_3d
            if region is not None:
                region.view_perspective = 'ORTHO'
        except Exception:
            pass
        break
