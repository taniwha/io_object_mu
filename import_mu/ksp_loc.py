# vim:ts=4:et
"""KSP localization helpers for variant / part UI labels.

Resolves ``#autoLOC_*`` and ``#LOC_*`` keys to English (default) strings.
Sources (in order):
  1. Inline ``// #autoLOC_123 = English`` comments in cfg text
  2. Cached GameData Localization/**/en-us.cfg (and en.cfg) tables
  3. Built-in English table (VariantThemes + common Squad / ReStock keys)
  4. Fallback: themeName, bare key, or original string
"""

from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# Built-in English (VariantThemes.cfg + common Squad / ReStock surface themes)
# ---------------------------------------------------------------------------
_BUILTIN_EN = {
    # Squad VariantThemes (GameData/Squad/PartVariants/VariantThemes.cfg)
    "autoLOC_8007119": "White",
    "autoLOC_8007120": "Black and White",
    "autoLOC_8007121": "Gray and Orange",
    "autoLOC_8007117": "Dark",
    "autoLOC_8007101": "Gray",
    "autoLOC_8007100": "Orange",
    "autoLOC_8007118": "Gold",
    "autoLOC_8007115": "Bare",
    "autoLOC_8007114": "Shroud",
    "autoLOC_8003112": "Gray and White",
    "autoLOC_8003113": "Gray and White",
    "autoLOC_8003114": "Yellow and White",
    "autoLOC_8003115": "Yellow and White",
    "autoLOC_6005005": "Silver",
    "autoLOC_6005006": "Silver",
    "autoLOC_8320084": "Gray with Stripes",
    "autoLOC_8320085": "Ol' Zebra",
    "autoLOC_8003040": "A classic white look.",
    "autoLOC_8003041": "A black and white look.",
    "autoLOC_8003042": "A gray and orange look.",
    "autoLOC_8003043": "A dark look.",
    "autoLOC_8003044": "A gray look.",
    "autoLOC_8003045": "An orange look.",
    "autoLOC_8003046": "A gold look.",
    "autoLOC_8003047": "Bare metal.",
    "autoLOC_8003048": "Shroud style.",
    # Common manufacturers / misc often on parts
    "autoLOC_501633": "Probodobodyne Inc",
    "autoLOC_501638": "Jebediah Kerman's Junkyard and Spacecraft Parts Co",
    "autoLOC_501682": "Rokea Inc",
    # ReStock surface theme labels (main ReStock localization)
    "LOC_Restock_variant-surface_metal": "Metal",
    "LOC_Restock_variant-surface_white": "White",
    "LOC_Restock_variant-surface_orange": "Orange",
    "LOC_Restock_variant-surface_gold": "Gold",
    "LOC_Restock_variant-surface_dark": "Dark",
    "LOC_Restock_variant-surface_gray": "Gray",
    "LOC_Restock_variant-surface_grey": "Gray",
    "LOC_Restock_variant-surface_bare": "Bare",
    "LOC_Restock_variant-surface_silver": "Silver",
    "LOC_Restock_variant-surface_black": "Black",
}

# themeName → English (when displayName is missing / unresolved)
_THEME_EN = {
    "white": "White",
    "blackandwhite": "Black and White",
    "grayandorange": "Gray and Orange",
    "greyandorange": "Gray and Orange",
    "dark": "Dark",
    "gray": "Gray",
    "grey": "Gray",
    "orange": "Orange",
    "gold": "Gold",
    "bare": "Bare",
    "shroud": "Shroud",
    "grayandwhite": "Gray and White",
    "greyandwhite": "Gray and White",
    "yellowandwhite": "Yellow and White",
    "silver": "Silver",
    "metal": "Metal",
    "gray with stripes": "Gray with Stripes",
    "grey with stripes": "Gray with Stripes",
}

_LOC_KEY_RE = re.compile(
    r"^#?(autoLOC_\d+|LOC_[A-Za-z0-9_./-]+)$", re.I
)
_INLINE_COMMENT_RE = re.compile(
    r"#((?:auto)?LOC_[A-Za-z0-9_./-]+)\s*=\s*([^\n\r]+)", re.I
)
_LOC_FILE_ENTRY_RE = re.compile(
    r"^\s*#((?:auto)?LOC_[A-Za-z0-9_./-]+)\s*=\s*(.+)$", re.M | re.I
)

# GameData path → { key_without_hash: english }
_gamedata_cache = {}
_gamedata_scanned = set()


def _norm_key(key):
    if not key:
        return ""
    k = str(key).strip().strip('"').lstrip("#")
    return k


def _theme_label(theme_name):
    if not theme_name:
        return None
    t = str(theme_name).strip()
    hit = _THEME_EN.get(t.lower().replace("_", " ").replace("-", " "))
    if hit:
        return hit
    # CamelCase / bare name
    if t and not t.startswith("#"):
        return t
    return None


def load_localization_from_gamedata(gamedata_path, lang="en-us"):
    """Scan GameData for Localization tables (en-us preferred).

    Safe to call repeatedly; results are cached per GameData root.
    """
    if not gamedata_path or not os.path.isdir(gamedata_path):
        return
    key = os.path.normpath(gamedata_path).lower()
    if key in _gamedata_scanned:
        return
    _gamedata_scanned.add(key)
    table = _gamedata_cache.setdefault(key, {})
    lang_files = (
        "%s.cfg" % lang,
        "en-us.cfg",
        "en.cfg",
        "english.cfg",
    )
    for root, dirs, files in os.walk(gamedata_path):
        # Prune heavy dirs
        dirs[:] = [
            d
            for d in dirs
            if d.lower()
            not in ("thumbs", "cache", "plugins", "plugin", "ships", "saves")
        ]
        base = os.path.basename(root).lower()
        parent = os.path.basename(os.path.dirname(root)).lower()
        # Prefer **/Localization/en-us.cfg and any en-us.cfg under GameData
        interesting = False
        if base == "localization" or parent == "localization":
            interesting = True
        for fn in files:
            fl = fn.lower()
            if not fl.endswith(".cfg"):
                continue
            if not interesting and fl not in lang_files:
                continue
            if interesting and not any(
                fl == x or fl.endswith(x) for x in lang_files
            ):
                # still parse any cfg in Localization folder
                if not interesting:
                    continue
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception:
                continue
            for m in _LOC_FILE_ENTRY_RE.finditer(text):
                k = _norm_key(m.group(1))
                val = m.group(2).strip().split("//")[0].strip().strip('"')
                if k and val and k not in table:
                    table[k] = val
    return table


def harvest_inline_loc_comments(cfg_text, into=None):
    """Pull ``// #autoLOC_x = English`` style comments from a cfg string."""
    dest = into if into is not None else {}
    if not cfg_text:
        return dest
    for m in _INLINE_COMMENT_RE.finditer(cfg_text):
        k = _norm_key(m.group(1))
        val = m.group(2).strip().split("//")[0].strip().strip('"')
        if k and val and k not in dest:
            dest[k] = val
    return dest


def resolve_loc(
    text,
    *,
    theme_name=None,
    gamedata_path=None,
    inline_table=None,
    lang="en-us",
):
    """Resolve a displayName / title that may be a #autoLOC / #LOC key.

    Returns a human-readable English string when possible.
    """
    if text is None:
        text = ""
    raw = str(text).strip().strip('"')
    # Strip trailing // comments on same line
    if "//" in raw:
        raw = raw.split("//", 1)[0].strip()

    if gamedata_path:
        try:
            load_localization_from_gamedata(gamedata_path, lang=lang)
        except Exception:
            pass

    # Already plain text (no loc key)
    m = _LOC_KEY_RE.match(raw.lstrip("#") if raw.startswith("#") else raw)
    if not raw.startswith("#") and not _LOC_KEY_RE.match(raw):
        # Might still be "Name // comment"
        if raw:
            return raw
        lab = _theme_label(theme_name)
        return lab or ""

    key = _norm_key(raw)

    # 1) inline comments from this cfg
    if inline_table and key in inline_table:
        return inline_table[key]

    # 2) GameData tables
    if gamedata_path:
        gd_key = os.path.normpath(gamedata_path).lower()
        tab = _gamedata_cache.get(gd_key) or {}
        if key in tab:
            return tab[key]
        # try without auto prefix variants
        if key.startswith("autoLOC_") and key in tab:
            return tab[key]

    # 3) Built-in
    if key in _BUILTIN_EN:
        return _BUILTIN_EN[key]
    # LOC_ vs autoLOC_ flexibility
    alt = key[4:] if key.lower().startswith("loc_") else None
    if alt and ("LOC_" + alt) in _BUILTIN_EN:
        return _BUILTIN_EN["LOC_" + alt]

    # 4) themeName
    lab = _theme_label(theme_name)
    if lab:
        return lab

    # 5) last resort: strip # and underscores for readability
    if key:
        pretty = key
        for prefix in ("autoLOC_", "LOC_Restock_variant-surface_", "LOC_"):
            if pretty.startswith(prefix):
                pretty = pretty[len(prefix) :]
                break
        pretty = pretty.replace("_", " ").replace("-", " ").strip()
        if pretty and not pretty.isdigit():
            return pretty[:1].upper() + pretty[1:]
    return raw or (theme_name or "")


def gamedata_from_root(root):
    """Best-effort GameData path from an imported MU root object."""
    if root is None:
        return None
    mudir = None
    try:
        mudir = root.get("mu_dirname")
    except Exception:
        mudir = None
    if not mudir:
        try:
            p = root.get("ksp_mu_path") or root.get("mu_path")
            if p:
                mudir = os.path.dirname(p)
        except Exception:
            pass
    if not mudir:
        return None
    cur = mudir
    for _ in range(16):
        if not cur:
            break
        if os.path.basename(cur).lower() == "gamedata":
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None
