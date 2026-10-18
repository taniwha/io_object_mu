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
"""KSPedia viewport fonts for all stock KSP locales.

KSP TMP font assets (from GameData):
  - NotoSans-Regular SDF     (Latin / Greek / Cyrillic body)
  - Amaranth-Regular SDF     (display titles, squadcore.ksp)
  - JD-LCD_rounded SDF       (numeric LCD, kspfonts.ksp)
  - NotoSansCJK*-Regular SDF (CJK fallbacks, embedded in some pages)

Blender FONT curves need outline faces.  Bundled OFL Noto Sans covers
Latin scripts; CJK / Hangul / Kana resolve to system Noto CJK / YaHei /
Malgun / Yu Gothic when present.  Call ``apply_fonts_to_curve`` with the
plain text (and optional TMP family hint) so the right face is chosen.
"""

from __future__ import annotations

import os
import re

import bpy


_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_CACHE = {}  # path -> VectorFont

# Stock KSP Localization blocks (Squad dictionary.cfg).  GameData may ship
# a subset; the plugin still maps glyphs for the full stock set.
KSP_LOCALES = (
    "en-us",
    "es-es",
    "ja",
    "pt-br",
    "ru",
    "zh-cn",
)

# TMP SDF asset name / family -> role
# Longer / more specific keys first so "NotoSansCJK" is not matched as "NotoSans".
_TMP_FAMILY_ROLE = {
    "arial": "arial",
    "liberation sans": "arial",
    "opensans": "opensans",
    "open sans": "opensans",
    "notosanscjk": "cjk",
    "noto sans cjk": "cjk",
    "amaranth": "display",
    "jd lcd": "lcd",
    "jd-lcd": "lcd",
    "jd_lcd": "lcd",
    "calibri": "calibri",
    "kalibri": "calibri",
    "headingfont": "heading",
    "dotty": "dotty",
    "perfect dos": "dos",
    "twinmarker": "marker",
    "notosans": "sans",
    "noto sans": "sans",
}


def fonts_dir():
    return _FONTS_DIR


def list_bundled_standin_stems():
    """TTF/OTF stems shipped under ``import_ksp/fonts`` (plugin native faces)."""
    out = []
    seen = set()
    try:
        names = os.listdir(_FONTS_DIR)
    except Exception:
        return out
    for fn in sorted(names, key=lambda s: s.lower()):
        base, ext = os.path.splitext(fn)
        if ext.lower() not in (".ttf", ".otf"):
            continue
        stem = (base or "").strip()
        if not stem:
            continue
        key = stem.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(stem)
    return out


def samples_dir():
    return os.path.join(os.path.dirname(__file__), "samples")


def template_ksp_path():
    p = os.path.join(samples_dir(), "template_kspedia_ui.ksp")
    return p if os.path.isfile(p) else ""


def _load_vfont(path):
    if not path or not os.path.isfile(path):
        return None
    if path in _CACHE:
        vf = _CACHE[path]
        try:
            _ = vf.name
            return vf
        except ReferenceError:
            _CACHE.pop(path, None)
    try:
        vf = bpy.data.fonts.load(path, check_existing=True)
    except Exception:
        return None
    _CACHE[path] = vf
    return vf


def _bundled(filename):
    return _load_vfont(os.path.join(_FONTS_DIR, filename))


def _first_existing(candidates):
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _win_fonts(*names):
    windir = os.environ.get("WINDIR", r"C:\Windows")
    base = os.path.join(windir, "Fonts")
    return [os.path.join(base, n) for n in names]


def detect_script(text):
    """Return primary script tag for font selection.

    Values: 'cjk', 'hangul', 'kana', 'cyrillic', 'greek', 'latin', 'mixed'.
    """
    if not text:
        return "latin"
    has_cjk = has_hangul = has_kana = has_cyr = has_greek = has_lat = False
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            has_hangul = True
        elif 0x3040 <= o <= 0x30FF:
            has_kana = True
        elif (
            0x4E00 <= o <= 0x9FFF
            or 0x3400 <= o <= 0x4DBF
            or 0xF900 <= o <= 0xFAFF
            or 0x20000 <= o <= 0x2A6DF
        ):
            has_cjk = True
        elif 0x0400 <= o <= 0x04FF:
            has_cyr = True
        elif 0x0370 <= o <= 0x03FF:
            has_greek = True
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            has_lat = True
    flags = [has_hangul, has_kana, has_cjk, has_cyr, has_greek]
    if sum(1 for f in flags if f) > 1:
        return "mixed"
    if has_hangul:
        return "hangul"
    if has_kana:
        return "kana"
    if has_cjk:
        return "cjk"
    if has_cyr:
        return "cyrillic"
    if has_greek:
        return "greek"
    return "latin"


def _is_cjk_wrap_char(ch: str) -> bool:
    """Ideograph / kana / hangul syllable — Blender needs a break opportunity."""
    if not ch:
        return False
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0xF900 <= o <= 0xFAFF
        or 0x20000 <= o <= 0x2A6DF
        or 0x3040 <= o <= 0x30FF
        or 0xAC00 <= o <= 0xD7AF
        or 0x1100 <= o <= 0x11FF
    )


def insert_cjk_wrap_breaks(text: str) -> str:
    """Deprecated alias — Blender FONT ignores U+200B; prefer wrap_cjk_to_width."""
    return text or ""


def wrap_cjk_to_width(
    collection,
    text: str,
    size: float,
    max_width_bu: float,
    bold: bool = False,
    italic: bool = False,
    font_family: str = "",
    locale: str = "",
    name: str = "",
) -> str:
    """Insert ``\\n`` so CJK runs fit ``max_width_bu`` (Blender wraps on WS/NL only)."""
    if not text or collection is None:
        return text or ""
    try:
        limit = float(max_width_bu)
    except Exception:
        return text
    if limit < 1e-6:
        return text
    try:
        from .viewport import _measure_font_width
    except Exception:
        return text

    def _width(s: str) -> float:
        try:
            return float(_measure_font_width(
                collection, s, size,
                bold=bold, italic=italic,
                font_family=font_family, locale=locale, name=name,
            ))
        except Exception:
            return float(size) * 0.9 * max(len(s), 1)

    out_paras = []
    for para in (text or "").split("\n"):
        if not para:
            out_paras.append("")
            continue
        # Tokenize: keep ASCII runs; split CJK per glyph; keep spaces.
        tokens = []
        cur = ""
        for ch in para:
            if ch.isspace():
                if cur:
                    tokens.append(cur)
                    cur = ""
                tokens.append(ch)
            elif _is_cjk_wrap_char(ch):
                if cur:
                    tokens.append(cur)
                    cur = ""
                tokens.append(ch)
            else:
                cur += ch
        if cur:
            tokens.append(cur)
        lines = []
        buf = ""
        for tok in tokens:
            trial = buf + tok
            if buf and tok.strip() and _width(trial) > limit + 1e-6:
                lines.append(buf.rstrip("\r"))
                # New line: drop leading spaces from continuation (Unity-like).
                buf = tok.lstrip(" \t") if tok.isspace() else tok
                if tok.isspace():
                    buf = ""
                    continue
            else:
                buf = trial
        if buf:
            lines.append(buf.rstrip("\r"))
        out_paras.extend(lines if lines else [""])
    return "\n".join(out_paras)


def tmp_family_role(family_or_name):
    """Map TMP font asset / family name to a role key."""
    if not family_or_name:
        return "sans"
    key = re.sub(r"[^a-z0-9]+", " ", str(family_or_name).lower()).strip()
    key_compact = key.replace(" ", "")
    # Longest needle first (dict order is insertion order on 3.7+)
    for needle, role in sorted(
        _TMP_FAMILY_ROLE.items(), key=lambda kv: -len(kv[0].replace(" ", ""))
    ):
        if needle.replace(" ", "") in key_compact or needle in key:
            return role
    if "cjk" in key_compact:
        return "cjk"
    if "lcd" in key_compact:
        return "lcd"
    if "amaranth" in key_compact:
        return "display"
    if "opensans" in key_compact or "open sans" in key:
        return "opensans"
    return "sans"


def _style_hints_from_family(font_family, bold=False, italic=False):
    """Derive bold/italic from Unity Font asset names (OpenSans-Italic, …)."""
    fam = re.sub(r"[^a-z0-9]+", "", str(font_family or "").lower())
    if "italic" in fam:
        italic = True
    if "extrabold" in fam or "bold" in fam:
        bold = True
    if "light" in fam and "bold" not in fam:
        bold = False
    return bool(bold), bool(italic)


def _bundled_face_path(font_family):
    """Exact bundled TTF for Unity Font names like ``OpenSans-Regular``."""
    raw = str(font_family or "").strip()
    if not raw:
        return None
    base = re.sub(r"(?i)\s*SDF.*$", "", raw).strip()
    base = base.replace(" ", "")
    if not base:
        return None
    for ext in (".ttf", ".otf"):
        path = os.path.join(_FONTS_DIR, base + ext)
        if os.path.isfile(path):
            return path
    # OpenSansRegular → OpenSans-Regular
    m = re.match(r"(?i)(opensans)(light|extrabold|bold)?(italic)?$", base)
    if m:
        parts = ["OpenSans"]
        if m.group(2):
            parts.append(m.group(2).title().replace("Extrabold", "ExtraBold"))
        elif not m.group(3):
            parts.append("Regular")
        if m.group(3):
            parts.append("Italic")
        path = os.path.join(_FONTS_DIR, "-".join(parts) + ".ttf")
        if os.path.isfile(path):
            return path
    # Stock Unity-embedded faces from AssetRipper (addon bundled_stock/Fonts)
    try:
        from ..stock_assets import resolve_bundled_font
        # Try exact stem, then Calibri weight variants
        hit = resolve_bundled_font(base)
        if hit:
            return hit
        low = base.lower()
        aliases = {
            "calibri": "calibri.ttf",
            "calibriregular": "calibri.ttf",
            "calibribold": "calibrib.ttf",
            "calibriitalic": "calibrii.ttf",
            "calibrilight": "calibril.ttf",
            "calibriz": "calibriz.ttf",
            "kalibri": "kalibri.ttf",
            "headingfont": "HEADINGFONT.ttf",
            "dotty": "dotty.ttf",
            "perfectdosvga437": "Perfect DOS VGA 437.ttf",
            "twinmarkerext": "TwinMarkerExt.ttf",
        }
        for key, fn in aliases.items():
            if key in low:
                hit = resolve_bundled_font(fn)
                if hit:
                    return hit
    except Exception:
        pass
    return None


def _opensans_path(bold=False, italic=False):
    if bold and italic:
        name = "OpenSans-BoldItalic.ttf"
    elif bold:
        name = "OpenSans-Bold.ttf"
    elif italic:
        name = "OpenSans-Italic.ttf"
    else:
        name = "OpenSans-Regular.ttf"
    path = os.path.join(_FONTS_DIR, name)
    return path if os.path.isfile(path) else None


def has_outline_standin(font_family):
    """True when a Blender outline TTF/OTF exists for this Unity/TMP name."""
    fam = str(font_family or "").strip()
    if not fam:
        return False
    if _bundled_face_path(fam):
        return True
    # Strip common TMP suffixes before role resolve.
    bare = re.sub(r"(?i)\s*SDF.*$", "", fam).strip() or fam
    role = tmp_family_role(bare)
    bold, italic = _style_hints_from_family(bare, bold=False, italic=False)
    path = resolve_font_path("latin", role, bold=bold, italic=italic)
    if path and os.path.isfile(path):
        return True
    # Known system faces for classic UI.Text
    if role == "arial":
        return bool(_first_existing(_win_fonts("arial.ttf")))
    return False


def resolve_font_path(script="latin", role="sans", bold=False, italic=False):
    """Pick the best outline font path for script + TMP role."""
    # CJK / Hangul / Kana need glyph coverage first (localized titles may
    # still reference Amaranth from the EN page asset).
    use_latin_display = script not in ("cjk", "mixed", "hangul", "kana")
    # Amaranth / LCD are Latin-only — never force them for Cyrillic/Greek.
    if script in ("cyrillic", "greek") and role in ("display", "lcd"):
        use_latin_display = False
    # Display / LCD titles stay Latin-capable faces when glyphs allow.
    if use_latin_display and role == "display":
        # Amaranth titles (squadcore TMP); prefer Bold when TMP Bold bit set.
        if bold:
            candidates = [
                os.path.join(_FONTS_DIR, "Amaranth-Bold.ttf"),
                os.path.join(_FONTS_DIR, "Amaranth-Regular.ttf"),
            ] + _win_fonts(
                "Amaranth-Bold.ttf", "Amaranth-Regular.ttf", "Amaranth.ttf"
            )
        else:
            candidates = [
                os.path.join(_FONTS_DIR, "Amaranth-Regular.ttf"),
                os.path.join(_FONTS_DIR, "Amaranth-Bold.ttf"),
            ] + _win_fonts(
                "Amaranth-Regular.ttf", "Amaranth.ttf", "Amaranth-Bold.ttf"
            )
        path = _first_existing(candidates)
        if path:
            return path
        role = "sans"
        bold = True
    if use_latin_display and role == "opensans":
        path = _opensans_path(bold=bold, italic=italic)
        if path:
            return path
        role = "arial"
    if use_latin_display and role in ("calibri", "heading", "dotty", "dos", "marker"):
        try:
            from ..stock_assets import resolve_bundled_font
            prefer = {
                "calibri": (
                    "calibrib.ttf" if bold else "calibri.ttf",
                    "calibri.ttf",
                    "kalibri.ttf",
                ),
                "heading": ("HEADINGFONT.ttf",),
                "dotty": ("dotty.ttf",),
                "dos": ("Perfect DOS VGA 437.ttf",),
                "marker": ("TwinMarkerExt.ttf",),
            }.get(role, ())
            for fn in prefer:
                path = resolve_bundled_font(fn)
                if path:
                    return path
        except Exception:
            pass
        role = "sans"
    if use_latin_display and role == "arial":
        if bold and italic:
            names = ("arialbi.ttf",)
        elif bold:
            names = ("arialbd.ttf",)
        elif italic:
            names = ("ariali.ttf",)
        else:
            names = ("arial.ttf",)
        path = _first_existing(_win_fonts(*names, "arial.ttf"))
        if path:
            return path
        # Prefer OpenSans stand-in over Noto when Arial is missing.
        path = _opensans_path(bold=bold, italic=italic)
        if path:
            return path
        role = "sans"
    if use_latin_display and role == "lcd":
        path = _first_existing(
            [
                os.path.join(_FONTS_DIR, "JD-LCD_rounded.ttf"),
                os.path.join(_FONTS_DIR, "JD_LCD_rounded.ttf"),
            ]
            + _win_fonts("consola.ttf", "lucon.ttf", "cour.ttf")
        )
        if path:
            return path
        role = "sans"

    if script in ("cjk", "mixed"):
        # Prefer Regular (Bold fills counters / looks ink-blobby in viewport).
        path = _first_existing(
            [
                os.path.join(
                    _FONTS_DIR,
                    "NotoSansCJKsc-Bold.otf" if bold else "NotoSansCJKsc-Regular.otf",
                ),
                os.path.join(_FONTS_DIR, "NotoSansCJKsc-Regular.otf"),
                os.path.join(_FONTS_DIR, "MicrosoftYaHei.ttc"),
                os.path.join(_FONTS_DIR, "NotoSansSC-Regular.otf"),
                os.path.join(_FONTS_DIR, "NotoSansCJKsc-DemiLight.otf"),
            ]
            + _win_fonts(
                "msyhbd.ttc" if bold else "msyh.ttc",
                "msyh.ttc",
                "NotoSansCJKsc-Bold.otf" if bold else "NotoSansCJKsc-Regular.otf",
                "NotoSansCJKsc-Regular.otf",
                "simsun.ttc",
                "NotoSansCJKsc-DemiLight.otf",
            )
        )
        if path:
            return path
    if script == "hangul":
        path = _first_existing(
            [
                os.path.join(
                    _FONTS_DIR,
                    "MalgunGothic-Bold.ttf" if bold else "MalgunGothic-Regular.ttf",
                ),
                os.path.join(_FONTS_DIR, "MalgunGothic-Regular.ttf"),
                os.path.join(_FONTS_DIR, "NotoSansCJKkr-Regular.otf"),
            ]
            + _win_fonts(
                "malgun.ttf",
                "malgunbd.ttf" if bold else "malgun.ttf",
                "NanumBarunGothic.ttf",
            )
        )
        if path:
            return path
    if script == "kana":
        path = _first_existing(
            [
                os.path.join(_FONTS_DIR, "MSGothic.ttc"),
                os.path.join(_FONTS_DIR, "NotoSansCJKjp-Regular.otf"),
            ]
            + _win_fonts(
                "msgothic.ttc",
                "YuGothM.ttc",
                "yugothic.ttf",
                "meiryo.ttc",
            )
        )
        if path:
            return path

    # Latin / Cyrillic / Greek — bundled Noto Sans (covers Cyrillic+Greek)
    if bold and italic:
        return _first_existing(
            [os.path.join(_FONTS_DIR, "NotoSans-BoldItalic.ttf")]
            + _win_fonts("arialbi.ttf", "seguisbi.ttf")
        )
    if bold:
        return _first_existing(
            [os.path.join(_FONTS_DIR, "NotoSans-Bold.ttf")]
            + _win_fonts("arialbd.ttf", "seguisb.ttf")
        )
    if italic:
        return _first_existing(
            [os.path.join(_FONTS_DIR, "NotoSans-Italic.ttf")]
            + _win_fonts("ariali.ttf", "seguili.ttf")
        )
    return _first_existing(
        [os.path.join(_FONTS_DIR, "NotoSans-Regular.ttf")]
        + _win_fonts("arial.ttf", "segoeui.ttf")
    )


def get_ksp_fonts():
    """Return (regular, bold, italic, bold_italic) VectorFont or Nones."""
    return (
        _bundled("NotoSans-Regular.ttf"),
        _bundled("NotoSans-Bold.ttf"),
        _bundled("NotoSans-Italic.ttf"),
        _bundled("NotoSans-BoldItalic.ttf"),
    )


def apply_fonts_to_curve(
    curve,
    bold=False,
    italic=False,
    text="",
    font_family="",
    locale="",
):
    """Assign outline fonts on a FONT curve for the given text / TMP family.

    ``font_family`` may be a TMP asset name (e.g. ``NotoSansCJK01-Regular SDF``),
    a Unity UI.Text Font name (``OpenSans-Regular`` / ``Amaranth-Bold``), or a
    face family (``Noto Sans`` / ``Arial``).  ``locale`` is optional
    (``zh-cn``, ``ja``, …) and biases CJK face choice when glyphs are ambiguous.

    Resolution order: embedded .ksp Font → bundled DB → OS → download →
    closest covering face we ship.
    """
    bold, italic = _style_hints_from_family(font_family, bold=bold, italic=italic)
    role = tmp_family_role(font_family)
    script = detect_script(text or "")
    # Locale only biases face when body is empty/ambiguous — never remap
    # clear Latin leftovers (ConfB2 EN quote, ALT, …) on zh-cn pages.
    if not (text or "").strip() and locale:
        loc = str(locale).lower()
        if loc.startswith("zh"):
            script = "cjk"
        elif loc.startswith("ja"):
            script = "kana"
        elif loc.startswith("ko"):
            script = "hangul"
        elif loc.startswith("ru"):
            script = "cyrillic"

    # Cascade via fonts_resolve (coverage-aware for Cyrillic / CJK / …).
    primary = None
    # CJK: pin bundled Regular/Bold first — fonts_resolve can land on DemiLight.
    # Cyrillic/Greek titles: skip Amaranth role path; resolve by coverage.
    if script in ("cjk", "mixed", "hangul", "kana"):
        primary = resolve_font_path(script, role, bold=bold, italic=False)
        if not primary:
            primary = resolve_font_path(script, role, bold=False, italic=False)
    if not primary:
        try:
            from .fonts_resolve import resolve_outline_font_path
            primary = resolve_outline_font_path(
                font_family=font_family,
                text=text or "",
                script=script,
                bold=bold,
                italic=italic,
                bundled_face_path=_bundled_face_path,
                resolve_role_path=resolve_font_path,
            )
        except Exception:
            primary = None
    if not primary:
        primary = _bundled_face_path(font_family)
        # Bundled Amaranth must not stick when the body needs Cyrillic.
        if primary and text:
            try:
                from .fonts_resolve import font_covers_text
                if not font_covers_text(primary, text):
                    primary = None
            except Exception:
                if script in ("cyrillic", "greek", "cjk", "mixed", "hangul", "kana"):
                    pl = primary.replace("\\", "/").lower()
                    if any(t in pl for t in ("amaranth", "jd-lcd", "jd_lcd")):
                        primary = None
    if not primary:
        primary = resolve_font_path(script, role, bold=bold, italic=italic)
    # Ensure layout knobs exist for unknown Unity faces.
    try:
        from .viewport import ensure_font_layout_profile
        ensure_font_layout_profile(font_family, primary or "")
    except Exception:
        pass
    vf = _load_vfont(primary) if primary else None
    if vf is None:
        # Last resort: bundled regular
        reg, bold_f, ital, bi = get_ksp_fonts()
        vf = reg
        if vf is None:
            return False
        try:
            curve.font = vf
            if bold_f is not None:
                curve.font_bold = bold_f
            if ital is not None:
                curve.font_italic = ital
            if bi is not None:
                curve.font_bold_italic = bi
        except Exception:
            curve.font = vf
        return True

    # Style slots: match the primary family (OpenSans / Arial / Amaranth /
    # Noto) so markup bold never jumps to a heavier unrelated face.
    # CJK/Hangul/Kana first: Unity often keeps OpenSans/Amaranth as the
    # face *name* on zh pages — Latin bold slots still paint tofu/squares.
    if script in ("cjk", "mixed", "hangul", "kana"):
        reg = _load_vfont(resolve_font_path(script, "sans", bold=False, italic=False))
        bold_f = _load_vfont(resolve_font_path(script, "sans", bold=True, italic=False))
        ital = None
        bi = None
    elif role == "opensans":
        reg = _load_vfont(_opensans_path(False, False))
        bold_f = _load_vfont(_opensans_path(True, False))
        ital = _load_vfont(_opensans_path(False, True))
        bi = _load_vfont(_opensans_path(True, True))
    elif role == "arial":
        reg = _load_vfont(
            _first_existing(_win_fonts("arial.ttf")) or _opensans_path(False, False)
        )
        bold_f = _load_vfont(
            _first_existing(_win_fonts("arialbd.ttf")) or _opensans_path(True, False)
        )
        ital = _load_vfont(
            _first_existing(_win_fonts("ariali.ttf")) or _opensans_path(False, True)
        )
        bi = _load_vfont(
            _first_existing(_win_fonts("arialbi.ttf")) or _opensans_path(True, True)
        )
    elif role == "display" and script in ("latin",):
        reg = _load_vfont(os.path.join(_FONTS_DIR, "Amaranth-Regular.ttf"))
        bold_f = _load_vfont(os.path.join(_FONTS_DIR, "Amaranth-Bold.ttf"))
        ital = None
        bi = None
    else:
        # Cyrillic/Greek (and unknown): Noto style slots — Amaranth has no
        # Cyrillic cmap and paints tofu/squares in the viewport.
        reg, bold_f, ital, bi = get_ksp_fonts()
    try:
        curve.font = vf
        if bold_f is not None:
            curve.font_bold = bold_f
        if ital is not None:
            curve.font_italic = ital
        if bi is not None:
            curve.font_bold_italic = bi
        # Whole-object style: keep the already-chosen Unity face when the
        # asset name already encodes weight (OpenSans-Italic). Otherwise
        # pick the matching role face for FontStyle bits.
        fam_l = re.sub(r"[^a-z0-9]+", "", str(font_family or "").lower())
        named_weight = any(
            tok in fam_l
            for tok in ("bold", "italic", "light", "extrabold", "regular")
        )
        # Named Latin display faces (Amaranth-Bold) must not override a
        # coverage-picked Noto primary for Cyrillic/Greek bodies.
        if named_weight and script in (
            "cyrillic", "greek", "mixed", "cjk", "hangul", "kana",
        ):
            named_weight = False
        if not named_weight:
            if bold and italic:
                path_bi = resolve_font_path(script, role, bold=True, italic=True)
                vf_bi = _load_vfont(path_bi) if path_bi else None
                if vf_bi is not None:
                    curve.font = vf_bi
            elif bold:
                path_b = resolve_font_path(script, role, bold=True, italic=False)
                vf_b = _load_vfont(path_b) if path_b else None
                if vf_b is not None:
                    curve.font = vf_b
            elif italic:
                path_i = resolve_font_path(script, role, bold=False, italic=True)
                vf_i = _load_vfont(path_i) if path_i else None
                if vf_i is not None:
                    curve.font = vf_i
    except Exception:
        try:
            curve.font = vf
        except Exception:
            return False

    try:
        # Prefer real italic face; avoid double-shear on CJK
        if italic and script in ("latin", "cyrillic", "greek"):
            ital_path = (
                _bundled_face_path(font_family)
                or resolve_font_path(script, role, bold=bold, italic=True)
            )
            if ital_path and os.path.isfile(ital_path):
                curve.shear = 0.0
            else:
                curve.shear = 0.35
        else:
            curve.shear = 0.0
    except Exception:
        pass

    try:
        curve["ksp_font_script"] = script
        curve["ksp_font_role"] = role
        curve["ksp_font_path"] = primary or ""
    except Exception:
        pass
    # CJK outline faces read a bit smaller than OpenSans at the same curve.size.
    if script in ("cjk", "mixed", "hangul", "kana"):
        try:
            if not curve.get("ksp_cjk_size_boost"):
                curve.size = float(curve.size) * 1.42
                curve["ksp_cjk_size_boost"] = 1.42
        except Exception:
            pass
    # Latin leftovers on CJK pages: auto-match capital height to CJK body.
    elif script == "latin" and locale and str(locale).lower().startswith(
        ("zh", "ja", "ko")
    ):
        try:
            if not curve.get("ksp_cjk_context_latin_mul"):
                mul = _latin_optical_mul_for_cjk_context(
                    float(curve.size), collection=None
                )
                if abs(mul - 1.0) > 1e-3:
                    curve.size = float(curve.size) * float(mul)
                curve["ksp_cjk_context_latin_mul"] = float(mul)
        except Exception:
            pass
    return True


_CJK_LATIN_OPTICAL_MUL = None


def _latin_optical_mul_for_cjk_context(base_size: float, collection=None) -> float:
    """``size`` multiplier so Latin caps ≈ CJK ideographs after CJK boost.

    Measured once from outline faces (no hard locale tables).
    """
    global _CJK_LATIN_OPTICAL_MUL
    if _CJK_LATIN_OPTICAL_MUL is not None:
        return float(_CJK_LATIN_OPTICAL_MUL)
    boost = 1.42
    try:
        import bpy

        def _h(path, sample, size):
            if not path or not os.path.isfile(path):
                return None
            vf = _load_vfont(path)
            if vf is None:
                return None
            cu = bpy.data.curves.new(name="_ksp_opt_Curve", type="FONT")
            cu.body = sample
            cu.size = max(float(size), 1e-4)
            cu.font = vf
            ob = bpy.data.objects.new("_ksp_opt", cu)
            try:
                bpy.context.scene.collection.objects.link(ob)
            except Exception:
                pass
            try:
                bpy.context.view_layer.update()
                h = float(ob.dimensions.y)
            except Exception:
                h = 0.0
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
            except Exception:
                pass
            try:
                bpy.data.curves.remove(cu)
            except Exception:
                pass
            return h if h > 1e-8 else None

        cjk_p = resolve_font_path("cjk", "sans", bold=False, italic=False)
        lat_p = _opensans_path(False, False)
        h_cjk = _h(cjk_p, "国", 1.0)
        h_lat = _h(lat_p, "H", 1.0)
        if h_cjk and h_lat and h_lat > 1e-8:
            _CJK_LATIN_OPTICAL_MUL = float(boost) * float(h_cjk) / float(h_lat)
        else:
            _CJK_LATIN_OPTICAL_MUL = float(boost)
    except Exception:
        _CJK_LATIN_OPTICAL_MUL = float(boost)
    m = float(_CJK_LATIN_OPTICAL_MUL)
    if m < 0.85:
        m = 0.85
    if m > 2.2:
        m = 2.2
    _CJK_LATIN_OPTICAL_MUL = m
    return m