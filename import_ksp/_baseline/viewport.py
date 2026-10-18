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

import os
import re
import tempfile

import bpy
from mathutils import Vector


DEFAULT_PIXEL_SCALE = 0.001

# =============================================================================
# TMP → Blender layout coefficients
# Split: UNIVERSAL (all fonts) / per-font profiles (ksp, arial, …).
# FaceInfo size math lives in fonts_faceinfo.py (roles: sans/display/lcd/arial).
# =============================================================================

# --- Universal (shared) ---
TMP_USE_FACEINFO_SCALE = True
# Legacy empiric scales: FALLBACK only when FaceInfo path fails.
TMP_FONT_SIZE_SCALE = 1.15
TMP_FONT_SIZE_SCALE_BODY = 1.58
TMP_FONT_SIZE_SCALE_NOTE = 1.68
TMP_TITLE_X_SCALE = 1.0  # optional override; PBS Bold title via display_x_scale()
TMP_FONT_CELL_HEIGHT_FIT = 1.18
TMP_SHORT_LABEL_WRAP_BONUS_PX = 12.0
# Outline Noto is a hair wider than TMP SDF — keep this much wrap slack even
# on explicit-\\n blocks (AC Career Limits: bold "EVA allowed" was ~1 px over).
TMP_WRAP_SLACK_PX = 6.0
TMP_CELL_FACE_PAD_PX = 3.0
TMP_TABLE_COL_WIDTH_BONUS_PX = 8.0
TMP_TOP_ASCENDER_SNAP = True
TMP_SPLIT_BLANK_LINE_PARAS = True
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
# "ksp"  = stock KSPedia (Noto Sans / Amaranth / JD LCD outline stand-ins)
# "arial"= classic UI.Text Arial pages
# "opensans" = PlanetaryBaseInc UI.Text (OpenSans-* Font assets)
# Add new keys here for future faces; resolve via font_layout_profile().
FONT_LAYOUT_PROFILES = {
    "ksp": {
        # Stock KSPedia (Noto/Amaranth) — values from the ±2 px FaceInfo era
        # (experience/forces HARD). BODY 1.0 * (1.25/line_em) ≈ empiric 0.90.
        "LEAD_SPACE_SCALE": 1.0,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        # ConfB1 ``\\n…\\n    true``: half-glyph lift after full line drop.
        "LEAD_NL_MULTILINE_NUDGE": 0.5,
        "COLON_LABEL_NUDGE_X_PX": 16.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.55,
        "BODY_LINE_SPACING_MUL": 1.0,
        # 0 → fonts_faceinfo.ascender_snap_extra_bu
        "TOP_EXTRA_NUDGE_BU": 0.0,
        "BLOCK_NUDGE_X_PX": 0.0,
        "BLOCK_NUDGE_Y_PX": 0.0,
        "CHAR_SPACING_MUL": 1.0,
        "WORD_SPACING_MUL": 1.0,
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
        "CHAR_SPACING_MUL": 1.0,
        "WORD_SPACING_MUL": 1.0,
    },
    "opensans": {
        # PBS OpenSans body — general pages (Corridors/Storage/…).
        # Configuration intro (ConfSubheader*) pinned via INTRO_*; callouts via
        # CALLOUT_* — do not fold those Perfect values into the base.
        "LEAD_SPACE_SCALE": 0.92,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        "LEAD_NL_MULTILINE_NUDGE": 0.0,
        "COLON_LABEL_NUDGE_X_PX": 16.0,
        # Short follow-ups (Keep in mind / On planets…): 0.55 was a full line
        # too high; 1.75 overshot low. 1.5 ≈ Unity blank-line vs screenshot.
        "SHORT_FOLLOWUP_GAP_MUL": 1.5,
        # DP1 / GE6 short follow-ups were ~1 line low at SHORT=1.5 → 0.75.
        "DP_SHORT_FOLLOWUP_GAP_MUL": 0.75,
        # GE6 follow-up: 0.0/−35 glued under as (3–4 lines too high); ~0.9 + Y0.
        "GE_SHORT_FOLLOWUP_GAP_MUL": 0.9,
        # leadGen still ~−1.5 on CO → open a touch more.
        "BODY_LINE_SPACING_MUL": 0.958,
        "TOP_EXTRA_NUDGE_BU": -0.008,
        # Global med dL≈+2 → nudge 0.5 (Unity; ~−2 canvas).
        "BLOCK_NUDGE_X_PX": 0.5,
        # Storage OpenSans bodies ~4 canvas px low → −4/1.39 ≈ −2.9 on Y.
        "BLOCK_NUDGE_Y_PX": 3.1,
        # Global body med wr≈1.000; keep. Callouts get CALLOUT_* below.
        "CHAR_SPACING_MUL": 0.958,
        "WORD_SPACING_MUL": 0.972,
        # Blue italic runs under white headers were slightly wide.
        "ITALIC_CHAR_SPACING_MUL": 0.985,
        # −8 needed for CO1 soft-wrap; −4 left CO late again.
        "WRAP_BONUS_PX": -8.0,
        # Storage ST4: −4 still dropped "with"; widen so L1 ends …racks with.
        "STORAGE_WRAP_BONUS_PX": 6.0,
        # Storage OpenSans: 0.968 overshot; 0.948 ~−0.5px tight → 0.953.
        "STORAGE_CHAR_SPACING_MUL": 0.953,
        # ST4 leading +2–3 canvas px (same GE map: 0.958→~0.990).
        "STORAGE_BODY_LINE_SPACING_MUL": 0.990,
        # Reentry: widen so Meerkat keeps "will help you"; parachute.You break
        # comes from _prepare_display_body short-line ``.\\n`` heuristic.
        "RE_WRAP_BONUS_PX": -3.5,
        # RE9 Meerkat: −3.5 still wrapped "you"; +18 Unity ≈ keeps help-you on L2.
        "RE9_WRAP_BONUS_PX": 18.0,
        # RE8 body: ~1px left / 1px down + ~3px leading; Keep-in-mind gap.
        "RE_BLOCK_NUDGE_X_PX": -0.2,
        # RE9 Landing-without block ~2 canvas px right of ref (do not move RE8).
        "RE9_BLOCK_NUDGE_X_PX": -2.5,
        # RE9 (3 each) residual vs ref: ~2 canvas left + ~3 down (−2/1.39, +3/1.39).
        "RE9_EACH_BLOCK_NUDGE_X_PX": -4.0,
        "RE9_EACH_BLOCK_NUDGE_Y_PX": 8.2,
        "RE_BODY_LINE_SPACING_MUL": 0.997,
        "RE_SHORT_FOLLOWUP_GAP_MUL": 0.75,
        # RE9 (3 each): was full blank-line gap (orphan \\n skipped mul);
        # 0.7 ≈ −1 line vs unmul'd gap after joining ``separately``.
        "RE9_SHORT_FOLLOWUP_GAP_MUL": 0.7,
        # Getting into Space GE6: Blender wraps "…the couplers" until tb.w≥0.636
        # (+4); "some" still stays on L2 (L1 needs ≥0.645).
        "GE_WRAP_BONUS_PX": 4.0,
        # Was −35 (follow-up overlapped as); 0 lets gap mul place it.
        "GE_EACH_BLOCK_NUDGE_Y_PX": 0.0,
        # GE* leading ~+2.5 canvas px → 0.958*(52.7+1.8)/52.7 ≈ 0.991.
        "GE_BODY_LINE_SPACING_MUL": 0.991,
        # Landing Legs LL5: nodes needs tb.w≥0.880 (was 0.869 at WRAP−8).
        "LL_WRAP_BONUS_PX": 4.0,
        # LL leading +1 canvas px.
        "LL_BODY_LINE_SPACING_MUL": 0.971,
        # Letter tracking ~1 canvas px tight; LL7 word +1px wraps "course.".
        "LL_CHAR_SPACING_MUL": 0.948,
        "LL_WORD_SPACING_MUL": 0.965,
        "LL7_WORD_SPACING_MUL": 1.020,
        # LL7 "The landing…" follow-up was ~1 line low at SHORT=1.5.
        "LL_SHORT_FOLLOWUP_GAP_MUL": 0.75,
        # LL8 ALT overlay: ~1 letter right + ~5px high vs ref (on top of base Y).
        "LL8_BLOCK_NUDGE_X_PX": -11.0,
        "LL8_BLOCK_NUDGE_Y_PX": 6.7,
        "CALLOUT_WRAP_BONUS_PX": -3.0,
        # ConfB2 quote needs a touch more first-line room than T2/T3.
        "CALLOUT_B2_WRAP_BONUS_PX": 0.0,
        # Configuration intro under blue title (Perfect) — absolute muls.
        "INTRO_CHAR_SPACING_MUL": 0.918,
        "INTRO_WORD_SPACING_MUL": 0.935,
        "INTRO_BLOCK_NUDGE_X_PX": 27.0,
        # ConfT3 L1 Wgen=299 vs Wref=304 → CHAR *304/299; nudge −2 canvas px.
        "CALLOUT_CHAR_SPACING_MUL": 0.950,
        "CALLOUT_WORD_SPACING_MUL": 0.962,
        "CALLOUT_T23_CHAR_SPACING_MUL": 0.960,
        "CALLOUT_T23_WORD_SPACING_MUL": 0.973,
        # ConfT3 body leadGen=31.5 vs ref=33 → *33/31.5 on 0.948 ≈ 0.993.
        "CALLOUT_BODY_LINE_SPACING_MUL": 0.990,
        # Callout block nudges. T1/B1 are *local* pins (not global OpenSans X) —
        # only Own Subcategory uses them; T23 stays at 0. Was 24/12 → 9.2/4.8
        # still dL≈+4/+2 → −4/1.39 and −2/1.39.
        "CALLOUT_T1_BLOCK_NUDGE_X_PX": 6.3,
        "CALLOUT_B1_BLOCK_NUDGE_X_PX": 3.4,
        # Was 1.5; −2 canvas px / scale 1.39 ≈ −1.44 Unity → 0.06 ≈ 0.
        "CALLOUT_T23_BLOCK_NUDGE_X_PX": 0.0,
        # ConfB2 upper quote ~5 canvas px right of ref → −5/1.39 ≈ −3.6 Unity.
        "CALLOUT_B2_BLOCK_NUDGE_X_PX": -3.6,
        "CALLOUT_BLOCK_NUDGE_Y_PX": 2.5,
        # Reentry first bodies: was 3.1; +1 canvas down → 3.8.
        # Do not apply to short follow-ups (RE*_each / Keep in mind).
        "RE_BODY_BLOCK_NUDGE_Y_PX": 3.8,
    },
    # PBS Amaranth (UI.Text, non-SDF) — titles + section headers with ":".
    # Must NOT inherit OpenSans CHAR 0.97 / BLOCK −11 (body-only).
    "display": {
        "LEAD_SPACE_SCALE": 1.0,
        "LEAD_SPACE_SCALE_MIN_SP": 12,
        "LEAD_NL_MULTILINE_NUDGE": 0.0,
        # Section titles like ``Own Subcategory:`` are not table colon-labels.
        "COLON_LABEL_NUDGE_X_PX": 0.0,
        "SHORT_FOLLOWUP_GAP_MUL": 0.55,
        "BODY_LINE_SPACING_MUL": 1.0,
        "TOP_EXTRA_NUDGE_BU": -0.006,
        # Titles canvas dL≈0…+2 after TITLE_*; taglines (COSubHeader…) were
        # ~−10…−17 — pin SUBHEADER_BLOCK_NUDGE_X_PX separately.
        "BLOCK_NUDGE_X_PX": 6.0,
        "BLOCK_NUDGE_Y_PX": 9.5,
        "TITLE_BLOCK_NUDGE_X_PX": -4.5,
        # ConfS* / ST2 / DP4… were ~+3…+5 right and ~+1…+3 down vs ref.
        "COLON_HEADER_BLOCK_NUDGE_X_PX": 1.5,
        "COLON_HEADER_BLOCK_NUDGE_Y_PX": 6.0,
        # ST2 "Containers:" ~5 canvas px low → −5/1.39 ≈ −3.6 from colon Y.
        "ST2_BLOCK_NUDGE_Y_PX": 2.4,
        # Taglines ~4.5% wide (wr≈1.045) + L still −4…−6 after X=24.
        "SUBHEADER_BLOCK_NUDGE_X_PX": 30.0,
        "SUBHEADER_CHAR_SPACING_MUL": 0.962,
        "SUBHEADER_WORD_SPACING_MUL": 0.975,
        # Home Regular section headers (ConfS* / ST2) ~wr 1.00 at base.
        "CHAR_SPACING_MUL": 1.000,
        "WORD_SPACING_MUL": 1.000,
        # RE1 "Landing without atmosphere" ~2 canvas px right → −4.5 Unity from 6.0.
        "RE1_BLOCK_NUDGE_X_PX": 1.5,
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


def font_layout_profile(font_family=""):
    """Return layout profile key for a TMP/UI font family name."""
    fam = (font_family or "").lower()
    if "opensans" in fam or "open sans" in fam:
        return "opensans"
    if "arial" in fam or "liberation sans" in fam:
        return "arial"
    # PBS UI.Text Amaranth (no SDF) — own display profile (not OpenSans body).
    if "amaranth" in fam:
        return "display"
    return "ksp"


def font_layout_get(font_family, key, default=None):
    """Read a per-font layout coefficient (falls back to KSP, then default)."""
    prof = FONT_LAYOUT_PROFILES.get(font_layout_profile(font_family)) or {}
    if key in prof:
        return prof[key]
    ksp = FONT_LAYOUT_PROFILES.get("ksp") or {}
    if key in ksp:
        return ksp[key]
    return default


def _is_pbs_intro_body(name=""):
    """Configuration ConfSubheader* intro under blue title (Perfect)."""
    n = (name or "").lower().replace(" ", "")
    return n.startswith("confsubheader")


def _is_pbs_callout_body(name=""):
    """Configuration ConfT*/ConfB* under white headers (not ConfSubheader)."""
    n = (name or "").lower().replace(" ", "")
    return n.startswith("conft") or n.startswith("confb")


def _is_pbs_amaranth_subheader(name=""):
    """Page taglines under blue titles: COSubHeader, ST-Subheader, DPSubheader…"""
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    return "subheader" in n and not n.startswith("confsubheader")


def _is_pbs_colon_header(name=""):
    """White Amaranth section labels under callouts: ConfS*, ST2/3/5, DP4–6…"""
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    if n.startswith("confs") and not n.startswith("confsubheader"):
        return True
    # Short colon labels (not Subheader / Bold *Header).
    for p in (
        "st2", "st3", "st5",
        "dp2", "dp4", "dp5", "dp6", "dp8",
        "ll2", "ll3",
        "ge2", "ge3",
    ):
        if n == p or n.startswith(p + "("):
            return True
    return False


def _display_block_nudge_x_px(name=""):
    """Amaranth X nudge — taglines / colon headers pinned; else Bold base."""
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    if n == "re1" or n.startswith("re1("):
        return float(font_layout_get("Amaranth", "RE1_BLOCK_NUDGE_X_PX", 1.5))
    if _is_pbs_amaranth_subheader(name):
        return float(font_layout_get("Amaranth", "SUBHEADER_BLOCK_NUDGE_X_PX", 18.0))
    if _is_pbs_colon_header(name):
        return float(font_layout_get("Amaranth", "COLON_HEADER_BLOCK_NUDGE_X_PX", 3.0))
    return float(font_layout_get("Amaranth", "BLOCK_NUDGE_X_PX", 0.0))


def _display_block_nudge_y_px(name=""):
    """Amaranth Y nudge (+down). Colon headers were a few px low vs ref."""
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    if n == "st2" or n.startswith("st2("):
        return float(font_layout_get("Amaranth", "ST2_BLOCK_NUDGE_Y_PX", 2.4))
    if _is_pbs_colon_header(name):
        return float(font_layout_get("Amaranth", "COLON_HEADER_BLOCK_NUDGE_Y_PX", 7.0))
    if _is_pbs_amaranth_subheader(name):
        return float(font_layout_get("Amaranth", "BLOCK_NUDGE_Y_PX", 9.5))
    return float(font_layout_get("Amaranth", "BLOCK_NUDGE_Y_PX", 9.5))


def _opensans_block_nudge_x_px(name=""):
    """Absolute X nudge (px) — intro/callouts pinned; else profile base."""
    n = (name or "").lower().replace(" ", "")
    base = float(font_layout_get("OpenSans", "BLOCK_NUDGE_X_PX", 0.0))
    if _is_pbs_intro_body(name):
        return float(font_layout_get("OpenSans", "INTRO_BLOCK_NUDGE_X_PX", 27.0))
    if n.startswith("conft1"):
        return float(font_layout_get("OpenSans", "CALLOUT_T1_BLOCK_NUDGE_X_PX", 24.0))
    if n.startswith("confb1"):
        return float(font_layout_get("OpenSans", "CALLOUT_B1_BLOCK_NUDGE_X_PX", 12.0))
    if n.startswith("confb2"):
        return float(font_layout_get("OpenSans", "CALLOUT_B2_BLOCK_NUDGE_X_PX", -3.6))
    if n.startswith("conft2") or n.startswith("conft3") or n.startswith("confb"):
        return float(font_layout_get("OpenSans", "CALLOUT_T23_BLOCK_NUDGE_X_PX", 3.5))
    if n.startswith("ll8"):
        return float(font_layout_get("OpenSans", "LL8_BLOCK_NUDGE_X_PX", -11.0))
    if n.startswith("re9") and "each" in n:
        return float(font_layout_get("OpenSans", "RE9_EACH_BLOCK_NUDGE_X_PX", -4.0))
    if n.startswith("re9"):
        return float(font_layout_get("OpenSans", "RE9_BLOCK_NUDGE_X_PX", -2.5))
    if n.startswith("re") and not n.startswith("subheader"):
        return float(font_layout_get("OpenSans", "RE_BLOCK_NUDGE_X_PX", -0.2))
    return base


def _opensans_block_nudge_y_px(name=""):
    """OpenSans Y nudge (+down). Callouts under white headers were a few px low."""
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    base = float(font_layout_get("OpenSans", "BLOCK_NUDGE_Y_PX", 6.0))
    if n.startswith("ge6") and "each" in n:
        return float(font_layout_get("OpenSans", "GE_EACH_BLOCK_NUDGE_Y_PX", 0.0))
    if n.startswith("re9") and "each" in n:
        return float(font_layout_get("OpenSans", "RE9_EACH_BLOCK_NUDGE_Y_PX", 8.2))
    if n.startswith("ll8"):
        return float(font_layout_get("OpenSans", "LL8_BLOCK_NUDGE_Y_PX", 6.7))
    if _is_pbs_callout_body(name):
        return float(font_layout_get("OpenSans", "CALLOUT_BLOCK_NUDGE_Y_PX", 4.0))
    if _is_pbs_intro_body(name):
        return base
    # Reentry first bodies ~4 canvas px low. Short follow-ups (Keep in mind /
    # RE*_each) stay at base — they were already a line too high vs ref.
    if (
        n.startswith("re")
        and not n.startswith("subheader")
        and "each" not in n
    ):
        return float(font_layout_get("OpenSans", "RE_BODY_BLOCK_NUDGE_Y_PX", 3.8))
    return base


def _opensans_wrap_bonus_px(name=""):
    """Wrap slack (Unity px). CO* stays WRAP_BONUS; ST/RE/GE scoped separately."""
    n = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    if n.startswith("confb2"):
        return float(font_layout_get("OpenSans", "CALLOUT_B2_WRAP_BONUS_PX", 0.0))
    if n.startswith("st"):
        return float(font_layout_get("OpenSans", "STORAGE_WRAP_BONUS_PX", 6.0))
    if n.startswith("re9"):
        return float(font_layout_get("OpenSans", "RE9_WRAP_BONUS_PX", 18.0))
    if n.startswith("re"):
        return float(font_layout_get("OpenSans", "RE_WRAP_BONUS_PX", -6.0))
    if n.startswith("ge6"):
        return float(font_layout_get("OpenSans", "GE_WRAP_BONUS_PX", 4.0))
    if n.startswith("ll"):
        return float(font_layout_get("OpenSans", "LL_WRAP_BONUS_PX", 4.0))
    return float(font_layout_get("OpenSans", "WRAP_BONUS_PX", -8.0))


def _opensans_spacing_muls(font_family="", name="", italic=False):
    """CHAR/WORD muls; pin Configuration intro/callouts; general PBS body base."""
    fam_l = (font_family or "").lower().replace(" ", "")
    italic_mul = 1.0
    if bool(italic) or ("italic" in fam_l):
        italic_mul = float(
            font_layout_get(font_family, "ITALIC_CHAR_SPACING_MUL", 1.0)
        )

    if font_layout_profile(font_family) != "opensans":
        # Amaranth page taglines (COSubHeader / ST-Subheader / …).
        if _is_pbs_amaranth_subheader(name):
            ch = float(
                font_layout_get(font_family, "SUBHEADER_CHAR_SPACING_MUL", 0.955)
            )
            wd = float(
                font_layout_get(font_family, "SUBHEADER_WORD_SPACING_MUL", 0.968)
            )
            return ch * italic_mul, wd
        ch = float(font_layout_get(font_family, "CHAR_SPACING_MUL", 1.0))
        wd = float(font_layout_get(font_family, "WORD_SPACING_MUL", 1.0))
        return ch * italic_mul, wd

    n = (name or "").lower().replace(" ", "")
    # Configuration intro — keep Perfect values absolute.
    if _is_pbs_intro_body(name):
        ch = float(font_layout_get(font_family, "INTRO_CHAR_SPACING_MUL", 0.918))
        wd = float(font_layout_get(font_family, "INTRO_WORD_SPACING_MUL", 0.935))
        return ch * italic_mul, wd
    # Configuration callouts under white headers — Perfect absolute.
    if _is_pbs_callout_body(name):
        if n.startswith("conft1") or n.startswith("confb1"):
            ch = float(
                font_layout_get(font_family, "CALLOUT_CHAR_SPACING_MUL", 0.955)
            )
            wd = float(
                font_layout_get(font_family, "CALLOUT_WORD_SPACING_MUL", 0.968)
            )
        else:
            ch = float(
                font_layout_get(font_family, "CALLOUT_T23_CHAR_SPACING_MUL", 0.966)
            )
            wd = float(
                font_layout_get(font_family, "CALLOUT_T23_WORD_SPACING_MUL", 0.978)
            )
        return ch * italic_mul, wd
    # Landing Legs — LL5 keeps tighter word; LL7 needs wider to wrap "course.".
    if n.startswith("ll"):
        ch = float(font_layout_get(font_family, "LL_CHAR_SPACING_MUL", 0.948))
        if n.startswith("ll7"):
            wd = float(font_layout_get(font_family, "LL7_WORD_SPACING_MUL", 1.020))
        else:
            wd = float(font_layout_get(font_family, "LL_WORD_SPACING_MUL", 0.965))
        return ch * italic_mul, wd
    # Storage bodies — 0.948 was ~0.5px tight vs tip → 0.953.
    if n.startswith("st"):
        ch = float(font_layout_get(font_family, "STORAGE_CHAR_SPACING_MUL", 0.953))
        wd = float(font_layout_get(font_family, "WORD_SPACING_MUL", 1.0))
        return ch * italic_mul, wd
    # All other PBS OpenSans bodies (CO/DP/GE/RE/…).
    ch = float(font_layout_get(font_family, "CHAR_SPACING_MUL", 1.0))
    wd = float(font_layout_get(font_family, "WORD_SPACING_MUL", 1.0))
    return ch * italic_mul, wd


def _load_calib_nudges():
    """Optional debug fine-tunes. Off unless KSP_CALIB_NUDGES=1."""
    if os.environ.get("KSP_CALIB_NUDGES", "").strip() != "1":
        return
    try:
        import json
        path = os.path.join(os.path.dirname(__file__), "calib_nudges.json")
        if not os.path.isfile(path):
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
        # Leading spaces mark intentional overlay pads — never join those.
        # Soft-hyphen tails (``con-`` / ``tainers``) must stay broken.
        if (
            last
            and last_raw[:1] not in (" ", "\t")
            and (" " not in last)
            and last[:1].islower()
            and len(last) < 24
        ):
            prev = lines[-2].rstrip()
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
):
    """Two FONTs with controlled paragraph gap (generic blank-line split)."""
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.01
    collection.objects.link(root)
    top = float(box_y) + float(box_h) if box_h is not None else 0.0

    def _mk(part, body, box_top_y):
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
            nudge_name = "%s_%s" % (name, part)
            if font_layout_profile(font_family) == "opensans":
                nx = float(_opensans_block_nudge_x_px(nudge_name))
                ny = float(_opensans_block_nudge_y_px(nudge_name))
            elif font_layout_profile(font_family) == "display":
                nx = float(_display_block_nudge_x_px(nudge_name))
                ny = float(_display_block_nudge_y_px(nudge_name))
            else:
                nx = float(font_layout_get(font_family, "BLOCK_NUDGE_X_PX", 0.0))
                ny = float(font_layout_get(font_family, "BLOCK_NUDGE_Y_PX", 0.0))
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
    # Short follow-ups ("Keep in mind…") sit too low with a full blank-line gap.
    # DP1 warning needs a tighter mul than RE Keep-in-mind (scoped pin).
    if (
        para_each
        and "\n" not in para_each
        and len(para_each.strip()) <= 90
        and float(font_layout_get(font_family, "SHORT_FOLLOWUP_GAP_MUL", 0.0)) > 1e-6
    ):
        n = (name or "").lower().replace(" ", "")
        if n.startswith("ge"):
            gap *= float(
                font_layout_get(font_family, "GE_SHORT_FOLLOWUP_GAP_MUL", 0.9)
            )
        elif n.startswith("dp"):
            gap *= float(
                font_layout_get(font_family, "DP_SHORT_FOLLOWUP_GAP_MUL", 0.75)
            )
        elif n.startswith("ll"):
            gap *= float(
                font_layout_get(font_family, "LL_SHORT_FOLLOWUP_GAP_MUL", 0.75)
            )
        elif n.startswith("re9"):
            gap *= float(
                font_layout_get(font_family, "RE9_SHORT_FOLLOWUP_GAP_MUL", 0.7)
            )
        elif n.startswith("re"):
            gap *= float(
                font_layout_get(font_family, "RE_SHORT_FOLLOWUP_GAP_MUL", 0.75)
            )
        else:
            gap *= float(font_layout_get(font_family, "SHORT_FOLLOWUP_GAP_MUL", 1.0))
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
    """PNG bytes from a Blender Image (same path export uses)."""
    if image is None:
        return b""
    try:
        if image.packed_file is not None:
            data = image.packed_file.data
            if data:
                return bytes(data)
    except Exception:
        pass
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="ksp_hash_", suffix=".png")
    os.close(fd)
    try:
        image.filepath_raw = tmp
        image.file_format = "PNG"
        image.save()
        with open(tmp, "rb") as f:
            return f.read()
    except Exception:
        return b""
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def image_content_hash(image):
    """SHA1 of PNG bytes as Blender would export them."""
    import hashlib
    data = image_png_bytes(image)
    return hashlib.sha1(data).hexdigest() if data else ""


def image_from_png_bytes(name, png_bytes):
    """Create or replace a Blender Image from PNG bytes.

    Load via a short-lived temp file, copy pixels into a GENERATED image,
    then ``pack()`` from the buffer. Avoids Blender re-packing a deleted
    ``ksp_tex_*.png`` path (``Unable to pack file`` / empty filepath errors).
    """
    if not png_bytes:
        return None
    data = bytes(png_bytes)
    fd, tmp = tempfile.mkstemp(prefix="ksp_tex_", suffix=".png")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        loaded = bpy.data.images.load(tmp, check_existing=False)
        try:
            w = int(loaded.size[0])
            h = int(loaded.size[1])
            pixels = list(loaded.pixels)
        finally:
            try:
                bpy.data.images.remove(loaded)
            except Exception:
                pass
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    existing = bpy.data.images.get(name)
    if existing is not None:
        try:
            bpy.data.images.remove(existing)
        except Exception:
            pass

    img = bpy.data.images.new(name, max(w, 1), max(h, 1), alpha=True)
    try:
        img.pixels = pixels
    except Exception:
        pass
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
    # Trailing newlines only inflate Blender FONT height (blank 2nd line) and
    # make section titles overlap body text — strip for display.
    while body_eff.endswith("\n") or body_eff.endswith("\r"):
        body_eff = body_eff[:-1]
    body_eff = _prepare_display_body(body_eff)
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
        )
        curve.space_character = (
            tmp_char_word_spacing_factor(character_spacing) * ch_mul
        )
        curve.space_word = (
            tmp_char_word_spacing_factor(word_spacing) * wd_mul
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
    # OpenSans outline fills look heavier than Unity UI.Text raster — thin
    # Regular a touch (Bold/Italic keep full weight).
    try:
        fam_l = (font_family or "").lower().replace(" ", "")
        if (
            "opensans" in fam_l
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
            if word_wrap and float(lead_dx) > 1e-8 and float(tb.width) > float(lead_dx):
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
            nx = float(_opensans_block_nudge_x_px(name))
            ny = float(_opensans_block_nudge_y_px(name))
        elif font_layout_profile(font_family) == "display":
            nx = float(_display_block_nudge_x_px(name))
            ny = float(_display_block_nudge_y_px(name))
        else:
            nx = float(font_layout_get(font_family, "BLOCK_NUDGE_X_PX", 0.0))
            ny = float(font_layout_get(font_family, "BLOCK_NUDGE_Y_PX", 0.0))
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
    # PBS OpenSans: absolute wrap slack from profile (do not keep SHORT_LABEL
    # +12 — that delayed soft-wraps under white headers / CO1 / ST body).
    if (
        enable_word_wrapping
        and box_width is not None
        and font_layout_profile(font_family) == "opensans"
        and not is_short_label
        and not is_title
    ):
        if _is_pbs_intro_body(name):
            # Intro Perfect — leave width_bonus from slack/SHORT_LABEL as-is.
            pass
        elif _is_pbs_callout_body(name):
            n_call = (name or "").lower().replace(" ", "")
            if n_call.startswith("confb2"):
                width_bonus = float(_opensans_wrap_bonus_px(name))
            else:
                width_bonus = float(
                    font_layout_get(font_family, "CALLOUT_WRAP_BONUS_PX", 3.0)
                )
        else:
            width_bonus = float(_opensans_wrap_bonus_px(name))
    # Short Midline labels: no margin face_pad (Unity uses m_margin only).
    # Horizontal wrap-guard inset for CENTER is applied in create_ui_text.
    margin_eff = (ml + face_pad_l, mt, mr + face_pad_r, mb)

    # Content box in pivot-local Blender units (lower-left + size).
    # Wrap slack must NOT re-center the rect (center pivots would shift +X
    # when width_bonus is negative) — pin left/bottom from the Unity size,
    # then grow/shrink only ``box_w`` for Blender wrap.
    box_x = box_y = 0.0
    box_w = box_h = None
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
        box_w = (local[2] + float(width_bonus)) * sx
        box_h = local[3] * sx
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
                n_lines = max(
                    1,
                    plain_for_align_early.replace("\\n", "\n").count("\n") + 1,
                )
                pitch_px = (
                    float(font_size)
                    * float(tmp_line_em_ratio(font_family))
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
            if _is_pbs_callout_body(name):
                body_ls = float(font_layout_get(
                    font_family, "CALLOUT_BODY_LINE_SPACING_MUL", body_ls
                ))
            n_ls = (name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
            if n_ls.startswith("ge"):
                body_ls = float(font_layout_get(
                    font_family, "GE_BODY_LINE_SPACING_MUL", body_ls
                ))
            if n_ls.startswith("ll"):
                body_ls = float(font_layout_get(
                    font_family, "LL_BODY_LINE_SPACING_MUL", body_ls
                ))
            if n_ls.startswith("re"):
                body_ls = float(font_layout_get(
                    font_family, "RE_BODY_LINE_SPACING_MUL", body_ls
                ))
            if n_ls.startswith("st"):
                body_ls = float(font_layout_get(
                    font_family, "STORAGE_BODY_LINE_SPACING_MUL", body_ls
                ))
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
    # detection (otherwise RE9 ``them\\nseparately`` skips gap mul).
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
    if (
        align_y == "TOP"
        and align_x == "RIGHT"
        and box_h is not None
        and ("\n" in plain_for_align or "\\n" in plain_for_align)
    ):
        align_y = "CENTER"

    # Short table-like cells often serialize TopLeft but JPG is Middle*.
    # Prefer TMP Midline bits when present; else geometry heuristic.
    plain_strip = plain_for_align.strip()
    is_digit_cell = plain_strip.isdigit() or (
        len(plain_strip) <= 3 and plain_strip.replace(".", "").isdigit()
    )
    align_has_middle = False
    try:
        a = int(text_alignment or 0)
        align_has_middle = bool(a & 0x200)
    except Exception:
        align_has_middle = False
    if is_short_label or (is_short_cell and not wide_paragraph):
        # Wide TopLeft captions (engines mid line) keep TOP Y.
        if (align_y == "TOP" or align_has_middle) and not wide_paragraph:
            align_y = "CENTER"
        # Do NOT force Left → Center X. That triggers nowrap box widening and
        # shifts callouts (map/time) by ~½·bonus; engines captions would jump.
        align_has_center_x = False
        try:
            _a = int(text_alignment or 0)
            align_has_center_x = bool(_a & 0x2) or _a in (1, 4, 7)
        except Exception:
            align_has_center_x = False
        if (
            is_digit_cell
            or align_has_center_x
            or (
                is_short_label
                and not wide_paragraph
                and float(box_width or 0) < float(font_size) * 6.0
            )
        ):
            align_x = "CENTER"

    # Wide single-line captions: Middle only in *tight* rects (chip/Midline).
    # Loose TopLeft boxes (content_h > ~1.2*fs) must keep TOP — otherwise the
    # line drops by ~0.5*(box-line) vs JPG (engines mid caption ~+5 px).
    if (
        not is_title
        and not is_note
        and single_line
        and wide_paragraph
        and box_h is not None
        and align_y == "TOP"
    ):
        content_h_px = float(box_h) / max(float(sx), 1e-9)
        if content_h_px <= float(font_size) * 1.2:
            align_y = "CENTER"
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
        len(parsed.runs) <= 1
        or (len(colors) <= 1 and len(sizes) <= 1)
    )
    if uniform:
        bold, italic, underline, color, sz = dominant_style(parsed, base_color)
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
            )
            return root, parsed.plain
        # Tall Level/role columns: one FONT per row on grid pitch.
        if is_table_col and box_h is not None and _plain_multiline(plain_for_align):
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
        # grow box so "Own Subcategory:" / "Landing without atmosphere" stay 1 line.
        title_box_w = box_w
        title_box_x = box_x
        grow_single = bool(
            single_line and box_w is not None and (
                is_title
                or (
                    plain_strip.endswith(":")
                    and float(font_size) >= 20.0
                    and len(plain_strip) <= 40
                )
                or (
                    # Short section headers without trailing ':' (RE1).
                    float(font_size) >= 45.0
                    and len(plain_strip) <= 40
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
        obj = create_ui_text(
            collection,
            name,
            parsed.plain,
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
        )
        try:
            obj["ksp_text_align"] = "%s/%s" % (align_x, align_y)
            obj["ksp_line_spacing"] = float(line_spacing)
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
                # Extra X for Bold page titles (white Regular headers keep base).
                try:
                    tnx = float(font_layout_get(
                        font_family, "TITLE_BLOCK_NUDGE_X_PX", 0.0
                    ))
                    if abs(tnx) > 1e-9:
                        tb = obj.data.text_boxes[0]
                        tb.x = float(tb.x) + tnx * float(DEFAULT_PIXEL_SCALE)
                except Exception:
                    pass
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
        try:
            child["ksp_run_width"] = float(w + max(lead_dx, 0.0))
        except Exception:
            pass
        line_objs.append(child)

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
            for ch in part:
                if ch.isspace():
                    if cur:
                        tokens.append(cur)
                        cur = ""
                    tokens.append(ch)
                else:
                    cur += ch
            if cur:
                tokens.append(cur)
            for tok in tokens:
                trial = buf + tok
                trial_w = _measure_font_width(
                    collection, trial, fsize,
                    bold=run.bold, italic=run.italic,
                    font_family=font_family, locale=locale, name=name,
                )
                if (buf
                        and tok.strip()
                        and cursor_x - line_start_x + trial_w > (
                            (max_x - line_start_x) if max_x is not None
                            else 1e9
                        ) + 1e-6):
                    _place_segment(buf, run, fsize, col)
                    _flush_line()
                    cursor_y -= max(line_height, run_lh)
                    line_height = run_lh
                    if tok.isspace():
                        buf = ""
                        continue
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
    if is_table_col and box_h is not None and finished_lines:
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
    return root, parsed.plain

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
