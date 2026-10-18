# vim:ts=4:et
# <pep8 compliant>
"""Resolve outline fonts: embedded -> bundled DB -> OS -> download -> closest."""

from __future__ import annotations

import hashlib
import os
import re
from difflib import SequenceMatcher
from typing import Dict, Optional, Tuple

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_CACHE_DIR = os.path.join(_FONTS_DIR, "_cache")
_EMBEDDED_DIR = os.path.join(_FONTS_DIR, "_embedded")
_ACTIVE_EMBEDDED: Dict[str, str] = {}

_DOWNLOAD_URLS = {
    "notosans-regular": (
        "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/"
        "NotoSans/NotoSans-Regular.ttf"
    ),
    "notosans-bold": (
        "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/"
        "NotoSans/NotoSans-Bold.ttf"
    ),
    "notosans-italic": (
        "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/"
        "NotoSans/NotoSans-Italic.ttf"
    ),
    "opensans-regular": (
        "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/"
        "OpenSans-Regular.ttf"
    ),
    "opensans-bold": (
        "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/"
        "OpenSans-Bold.ttf"
    ),
    "opensans-italic": (
        "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/"
        "OpenSans-Italic.ttf"
    ),
    "amaranth-regular": (
        "https://github.com/googlefonts/amaranth/raw/main/fonts/ttf/"
        "Amaranth-Regular.ttf"
    ),
    "amaranth-bold": (
        "https://github.com/googlefonts/amaranth/raw/main/fonts/ttf/"
        "Amaranth-Bold.ttf"
    ),
}

_ROLE_ALIASES = {
    "opensans": ("open sans", "opensans"),
    "arial": ("arial", "liberation sans", "helvetica"),
    "amaranth": ("amaranth", "display"),
    "sans": ("noto sans", "notosans", "roboto", "source sans"),
    "cjk": ("noto sans cjk", "notosanscjk", "yahei", "source han", "pingfang"),
    "lcd": ("jd lcd", "jd-lcd", "lcd"),
}


def _ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def clear_embedded_fonts() -> None:
    _ACTIVE_EMBEDDED.clear()


def register_embedded_font(name: str, path: str) -> None:
    if not name or not path:
        return
    key = _norm_name(name)
    if key:
        _ACTIVE_EMBEDDED[key] = path
    bare = re.sub(r"(regular|bold|italic|light|extrabold|sdf)+$", "", key)
    if bare and bare not in _ACTIVE_EMBEDDED:
        _ACTIVE_EMBEDDED[bare] = path


def embedded_font_path(name: str) -> Optional[str]:
    key = _norm_name(name)
    if not key:
        return None
    path = _ACTIVE_EMBEDDED.get(key)
    if path and os.path.isfile(path):
        return path
    for k, p in _ACTIVE_EMBEDDED.items():
        if (key in k or k in key) and p and os.path.isfile(p):
            return p
    return None


def _font_data_to_bytes(raw) -> Optional[bytes]:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw)
    if isinstance(raw, list):
        try:
            return bytes(raw)
        except Exception:
            return None
    return None


def extract_embedded_fonts_from_env(env, bundle_key: str = "") -> Dict[str, str]:
    out = {}
    if env is None:
        return out
    _ensure_dir(_EMBEDDED_DIR)
    tag = _norm_name(os.path.basename(bundle_key or "bundle")) or "bundle"
    for obj in getattr(env, "objects", []) or []:
        try:
            if obj.type.name != "Font":
                continue
        except Exception:
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = str(getattr(data, "m_Name", "") or "") or "Font"
        blob = _font_data_to_bytes(getattr(data, "m_FontData", None))
        if not blob or len(blob) < 8:
            continue
        sig = blob[:4]
        if sig not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"):
            if b"OTTO" not in blob[:16] and b"\x00\x01\x00\x00" not in blob[:16]:
                continue
        ext = ".otf" if sig == b"OTTO" else ".ttf"
        safe = re.sub(r"[^\w\-]+", "_", name)[:80] or "Font"
        digest = hashlib.md5(blob[:64] + str(len(blob)).encode()).hexdigest()[:8]
        path = os.path.join(_EMBEDDED_DIR, "%s_%s_%s%s" % (tag, safe, digest, ext))
        if not os.path.isfile(path):
            try:
                with open(path, "wb") as f:
                    f.write(blob)
            except Exception:
                continue
        out[name] = path
        register_embedded_font(name, path)
    if bundle_key:
        try:
            key = os.path.abspath(bundle_key)
            mtime = os.path.getmtime(key) if os.path.isfile(key) else 0.0
            _EXTRACT_CACHE[key] = (mtime, dict(out))
        except Exception:
            pass
    return out


# abspath -> (mtime, result dict) — avoid re-parsing .ksp/.lang on every locale switch
_EXTRACT_CACHE: Dict[str, tuple] = {}


def extract_embedded_fonts_from_path(filepath: str) -> Dict[str, str]:
    if not filepath or not os.path.isfile(filepath):
        return {}
    try:
        key = os.path.abspath(filepath)
        mtime = os.path.getmtime(key)
    except Exception:
        key = filepath
        mtime = 0.0
    cached = _EXTRACT_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return dict(cached[1])
    try:
        import UnityPy
        env = UnityPy.load(filepath)
    except Exception:
        return {}
    out = extract_embedded_fonts_from_env(env, filepath)
    try:
        _EXTRACT_CACHE[key] = (mtime, dict(out))
    except Exception:
        pass
    return out


def font_codepoint_coverage(path: str, text: str) -> Tuple[int, int]:
    if not path or not text or not os.path.isfile(path):
        return (0, 0)
    needed = [ord(c) for c in text if ord(c) > 127 and not c.isspace()]
    if not needed:
        return (0, 0)
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(path, fontNumber=0, lazy=True)
        cps = set()
        for table in font["cmap"].tables:
            cps |= set(table.cmap)
        try:
            font.close()
        except Exception:
            pass
        uniq = set(needed)
        covered = sum(1 for o in uniq if o in cps)
        return (covered, len(uniq))
    except Exception:
        pass
    # Blender's Python often lacks fontTools — guess from filename + script.
    pl = path.replace("\\", "/").lower()
    uniq = set(needed)
    has_cjk = any(
        o >= 0x4E00 or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF
        for o in uniq
    )
    has_cyr = any(0x0400 <= o <= 0x04FF for o in uniq)
    has_greek = any(0x0370 <= o <= 0x03FF for o in uniq)
    cjk_ok = any(
        tok in pl
        for tok in (
            "cjk", "yahei", "msyh", "sourcehan", "simsun", "malgun",
            "gothic", "yugoth", "notosanssc", "notosansjp", "notosanskr",
        )
    )
    cyr_ok = any(
        tok in pl
        for tok in (
            "noto", "opensans", "arial", "segoe", "dejavu", "roboto",
            "liberation", "source sans", "sourcesans",
        )
    )
    # Display faces (Amaranth / JD LCD) are Latin-only stand-ins.
    latin_only = any(tok in pl for tok in ("amaranth", "jd-lcd", "jd_lcd", "lcd"))
    covered = 0
    for o in uniq:
        if o >= 0x4E00 or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
            if cjk_ok:
                covered += 1
        elif 0x0400 <= o <= 0x04FF or 0x0370 <= o <= 0x03FF:
            if cyr_ok and not latin_only:
                covered += 1
        else:
            covered += 1
    if has_cjk and not cjk_ok:
        return (0, len(uniq))
    if (has_cyr or has_greek) and (latin_only or not cyr_ok):
        return (0, len(uniq))
    return (covered, len(uniq))


def font_covers_text(path: str, text: str, min_ratio: float = 0.92) -> bool:
    covered, needed = font_codepoint_coverage(path, text)
    if needed <= 0:
        return True
    return (covered / float(needed)) >= float(min_ratio)


def _win_fonts(*names):
    windir = os.environ.get("WINDIR", r"C:\Windows")
    base = os.path.join(windir, "Fonts")
    return [os.path.join(base, n) for n in names]


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def closest_role_for_name(font_family: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", (font_family or "").lower()).strip()
    if not key:
        return "sans"
    compact = key.replace(" ", "")
    best_role = "sans"
    best = 0.0
    for role, aliases in _ROLE_ALIASES.items():
        for alias in aliases:
            a = alias.replace(" ", "")
            if a in compact or compact in a:
                return role
            ratio = SequenceMatcher(None, compact, a).ratio()
            if ratio > best:
                best = ratio
                best_role = role
    return best_role if best >= 0.45 else "sans"


def download_font(key: str) -> Optional[str]:
    url = _DOWNLOAD_URLS.get(_norm_name(key))
    if not url:
        nk = _norm_name(key)
        for cand in _DOWNLOAD_URLS:
            if cand in nk or nk in cand:
                url = _DOWNLOAD_URLS[cand]
                key = cand
                break
    if not url:
        return None
    _ensure_dir(_CACHE_DIR)
    dest = os.path.join(_CACHE_DIR, "%s.ttf" % _norm_name(key))
    if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
        return dest
    try:
        from urllib.request import Request, urlopen
        req = Request(url, headers={"User-Agent": "io_object_mu-kspedia/1.0"})
        with urlopen(req, timeout=20) as resp:
            data = resp.read()
        if not data or len(data) < 1000:
            return None
        with open(dest, "wb") as f:
            f.write(data)
        return dest
    except Exception:
        return None


def measure_font_metrics(path: str) -> Optional[dict]:
    if not path or not os.path.isfile(path):
        return None
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(path, fontNumber=0, lazy=True)
        upem = float(font["head"].unitsPerEm or 1000.0)
        os2 = font["OS/2"]
        hhea = font["hhea"]
        asc = float(getattr(os2, "sTypoAscender", None) or hhea.ascent or upem * 0.8)
        desc = float(getattr(os2, "sTypoDescender", None) or hhea.descent or -upem * 0.2)
        gap = float(getattr(hhea, "lineGap", 0) or 0)
        italic = float(getattr(font["post"], "italicAngle", 0) or 0)
        advances = []
        try:
            metrics = font["hmtx"].metrics
            cmap = {}
            for table in font["cmap"].tables:
                cmap.update(table.cmap)
            for code in range(ord("A"), ord("Z") + 1):
                g = cmap.get(code)
                if g and g in metrics:
                    advances.append(float(metrics[g][0]))
        except Exception:
            advances = []
        avg = (sum(advances) / len(advances) / upem) if advances else 0.5
        try:
            font.close()
        except Exception:
            pass
        return {
            "upem": upem,
            "asc_ratio": abs(asc) / upem,
            "desc_ratio": abs(desc) / upem,
            "line_ratio": (abs(asc) + abs(desc) + gap) / upem,
            "italic": abs(italic),
            "avg_width": avg,
        }
    except Exception:
        return None


_REF_METRICS = None


def _reference_metrics() -> Dict[str, dict]:
    global _REF_METRICS
    if _REF_METRICS is not None:
        return _REF_METRICS
    samples = {
        "opensans": "OpenSans-Regular.ttf",
        "arial": None,
        "amaranth": "Amaranth-Regular.ttf",
        "ksp": "NotoSans-Regular.ttf",
    }
    out = {}
    for role, fname in samples.items():
        path = os.path.join(_FONTS_DIR, fname) if fname else None
        if role == "arial":
            path = _first_existing(_win_fonts("arial.ttf")) or os.path.join(
                _FONTS_DIR, "OpenSans-Regular.ttf"
            )
        m = measure_font_metrics(path) if path else None
        if m:
            out[role] = m
    _REF_METRICS = out
    return out


def nearest_layout_profile_key(font_family: str, font_path: str = "") -> str:
    role_guess = closest_role_for_name(font_family)
    if role_guess in ("opensans", "arial", "amaranth"):
        return role_guess
    if role_guess in ("cjk", "lcd"):
        return "ksp"
    metrics = measure_font_metrics(font_path) if font_path else None
    refs = _reference_metrics()
    if not metrics or not refs:
        return "ksp"
    best_key = "ksp"
    best_dist = 1e9
    for key, ref in refs.items():
        dist = (
            abs(metrics["asc_ratio"] - ref["asc_ratio"]) * 2.0
            + abs(metrics["line_ratio"] - ref["line_ratio"]) * 1.5
            + abs(metrics["avg_width"] - ref["avg_width"]) * 3.0
            + abs(metrics["italic"] - ref["italic"]) * 0.02
        )
        if dist < best_dist:
            best_dist = dist
            best_key = key
    return best_key


def synthesize_layout_profile(font_family: str, font_path: str = "") -> Tuple[str, dict]:
    from . import viewport

    base_key = nearest_layout_profile_key(font_family, font_path)
    base = dict(
        viewport.FONT_LAYOUT_PROFILES.get(base_key)
        or viewport.FONT_LAYOUT_PROFILES["ksp"]
    )
    metrics = measure_font_metrics(font_path) if font_path else None
    refs = _reference_metrics()
    ref = refs.get(base_key)
    if metrics and ref and ref.get("avg_width"):
        width_ratio = float(metrics["avg_width"]) / float(ref["avg_width"])
        if "CHAR_SPACING_MUL" in base:
            base["CHAR_SPACING_MUL"] = float(base["CHAR_SPACING_MUL"]) / max(
                width_ratio, 0.5
            )
        if "WORD_SPACING_MUL" in base:
            base["WORD_SPACING_MUL"] = float(base["WORD_SPACING_MUL"]) / max(
                (width_ratio * 0.5 + 0.5), 0.5
            )
        if ref.get("line_ratio") and metrics.get("line_ratio"):
            lr = float(metrics["line_ratio"]) / float(ref["line_ratio"])
            if "BODY_LINE_SPACING_MUL" in base:
                base["BODY_LINE_SPACING_MUL"] = float(
                    base["BODY_LINE_SPACING_MUL"]
                ) / max(lr, 0.5)
    key = "auto_" + (_norm_name(font_family)[:40] or base_key)
    return key, base


def resolve_outline_font_path(
    font_family: str = "",
    text: str = "",
    script: str = "latin",
    bold: bool = False,
    italic: bool = False,
    bundled_face_path=None,
    resolve_role_path=None,
) -> Optional[str]:
    candidates = []
    # Prefer covering faces first for Cyrillic/Greek — embedded Amaranth
    # from EN TMP assets would otherwise win before coverage filtering.
    prefer_coverage_first = script in ("cyrillic", "greek", "cjk", "mixed", "hangul", "kana")
    if not prefer_coverage_first:
        emb = embedded_font_path(font_family)
        if emb:
            candidates.append(emb)
        if bundled_face_path:
            try:
                p = bundled_face_path(font_family)
                if p:
                    candidates.append(p)
            except Exception:
                pass
    role = closest_role_for_name(font_family)
    if resolve_role_path:
        try:
            p = resolve_role_path(script, role, bold, italic)
            if p:
                candidates.append(p)
        except Exception:
            pass
    if script in ("cjk", "mixed"):
        candidates.extend(
            [
                os.path.join(_FONTS_DIR, "NotoSansCJKsc-Regular.otf"),
                os.path.join(_FONTS_DIR, "MicrosoftYaHei.ttc"),
            ]
            + _win_fonts("msyh.ttc", "simsun.ttc")
        )
    elif script == "cyrillic":
        candidates.extend(
            [
                os.path.join(_FONTS_DIR, "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"),
                os.path.join(_FONTS_DIR, "NotoSans-Regular.ttf"),
                os.path.join(_FONTS_DIR, "OpenSans-Bold.ttf" if bold else "OpenSans-Regular.ttf"),
                os.path.join(_FONTS_DIR, "OpenSans-Regular.ttf"),
            ]
            + _win_fonts("arialbd.ttf" if bold else "arial.ttf", "arial.ttf", "segoeui.ttf")
        )
    elif script == "greek":
        candidates.extend(
            [
                os.path.join(_FONTS_DIR, "NotoSans-Regular.ttf"),
                os.path.join(_FONTS_DIR, "OpenSans-Regular.ttf"),
            ]
            + _win_fonts("arial.ttf", "segoeui.ttf")
        )
    elif script in ("hangul", "kana") and resolve_role_path:
        try:
            p = resolve_role_path(script, "cjk", bold, italic)
            if p:
                candidates.append(p)
        except Exception:
            pass
    if prefer_coverage_first:
        emb = embedded_font_path(font_family)
        if emb:
            candidates.append(emb)
        if bundled_face_path:
            try:
                p = bundled_face_path(font_family)
                if p:
                    candidates.append(p)
            except Exception:
                pass

    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if not os.path.isfile(path):
            continue
        if not text or font_covers_text(path, text):
            return path

    if role == "opensans":
        dl_keys = [
            "opensans-bold" if bold else (
                "opensans-italic" if italic else "opensans-regular"
            )
        ]
    elif role == "amaranth" and script not in ("cyrillic", "greek", "cjk", "mixed"):
        dl_keys = ["amaranth-bold" if bold else "amaranth-regular"]
    else:
        dl_keys = [
            "notosans-bold" if bold else (
                "notosans-italic" if italic else "notosans-regular"
            )
        ]
    for k in dl_keys:
        path = download_font(k)
        if path and (not text or font_covers_text(path, text)):
            return path

    fallback_pool = [
        os.path.join(_FONTS_DIR, "NotoSansCJKsc-Regular.otf"),
        os.path.join(_FONTS_DIR, "NotoSans-Regular.ttf"),
        os.path.join(_FONTS_DIR, "OpenSans-Regular.ttf"),
        os.path.join(_FONTS_DIR, "Amaranth-Regular.ttf"),
        os.path.join(_FONTS_DIR, "MicrosoftYaHei.ttc"),
    ] + _win_fonts("arial.ttf", "msyh.ttc", "segoeui.ttf")
    best = None
    best_score = -1.0
    for path in fallback_pool:
        if not path or not os.path.isfile(path):
            continue
        covered, needed = font_codepoint_coverage(path, text or "")
        score = 0.5 if needed <= 0 else (covered / float(needed))
        if score > best_score:
            best_score = score
            best = path
            if score >= 0.99:
                break
    return best
