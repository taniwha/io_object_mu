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
"""Resolve KSP #autoLOC_ / #LOC_ keys from Localization dictionary.cfg."""

from __future__ import annotations

import os
import re
from typing import Dict, Optional

_LOC_KEY_RE = re.compile(r"^#(?:auto)?LOC_[\w]+$", re.IGNORECASE)
_LOC_ASSIGN_RE = re.compile(
    r"(?m)^\s*(#(?:auto)?LOC_[\w]+)\s*=\s*(.*)$"
)

_DICT_CACHE: Dict[str, Dict[str, str]] = {}


def is_loc_key(text: str) -> bool:
    if not text:
        return False
    return bool(_LOC_KEY_RE.match(text.strip()))


def parse_dictionary_cfg(text: str) -> Dict[str, str]:
    """Parse Localization { en-us { #autoLOC_x = ... } } style files."""
    out: Dict[str, str] = {}
    if not text:
        return out
    for m in _LOC_ASSIGN_RE.finditer(text):
        key = m.group(1).strip()
        # Keep trailing spaces and ``\\n`` pads (FR showModCategory after spaces).
        val = m.group(2).rstrip("\r")
        val = val.replace(r"\n", "\n").replace(r"\t", "\t")
        out[key] = val
        if key.startswith("#"):
            out[key[1:]] = val
    return out


def load_dictionary_file(path: str) -> Dict[str, str]:
    if not path:
        return {}
    abspath = os.path.abspath(path)
    cached = _DICT_CACHE.get(abspath)
    if cached is not None:
        return cached
    try:
        with open(abspath, "r", encoding="utf-8", errors="replace") as f:
            data = parse_dictionary_cfg(f.read())
    except Exception:
        data = {}
    _DICT_CACHE[abspath] = data
    return data


def _prefs_gamedata() -> Optional[str]:
    """Addon Preferences → GameData Path (View3D Options)."""
    try:
        import bpy
        from ..preferences.preferences import Preferences
        prefs = Preferences()
        gd = (getattr(prefs, "GameData", None) or "").strip()
        if gd and os.path.isdir(gd):
            return os.path.abspath(gd)
    except Exception:
        pass
    return None


def find_gamedata_root(start: str) -> Optional[str]:
    """Walk parents until a folder named GameData is found."""
    pref = _prefs_gamedata()
    if pref:
        return pref
    if not start:
        return None
    cur = os.path.abspath(start)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    for _ in range(12):
        if not cur or cur == os.path.dirname(cur):
            break
        if os.path.basename(cur).lower() == "gamedata":
            return cur
        parent = os.path.dirname(cur)
        sibling = os.path.join(parent, "GameData")
        if os.path.isdir(sibling):
            return sibling
        cur = parent
    return None


def find_dictionary_near(filepath: str) -> str:
    """Prefer a Localization/dictionary.cfg near filepath (Squad or DLC)."""
    paths = find_all_dictionaries_near(filepath)
    return paths[0] if paths else ""


def find_all_dictionaries_near(filepath: str) -> list:
    """All Localization/dictionary.cfg under nearby GameData (DLC + Squad).

    Order: dictionaries under the same expansion as ``filepath`` first, then
    remaining GameData packs (so Serenity keys resolve when editing DLC pages).
    """
    gd = find_gamedata_root(filepath or "")
    if not filepath and not gd:
        return []
    if not filepath:
        filepath = gd or ""
    found = []
    seen = set()

    def _add(path: str):
        if not path:
            return
        ap = os.path.normcase(os.path.abspath(path))
        if ap in seen:
            return
        if os.path.isfile(path):
            seen.add(ap)
            found.append(os.path.abspath(path))

    # Prefer Localization next to the file (…/Serenity/KSPedia → …/Serenity/Localization)
    folder = os.path.dirname(os.path.abspath(filepath))
    for _ in range(6):
        _add(os.path.join(folder, "Localization", "dictionary.cfg"))
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent

    if gd and os.path.isdir(gd):
        # Walk GameData for every Localization/dictionary.cfg
        for root, dirs, files in os.walk(gd):
            if "dictionary.cfg" in files and (
                os.path.basename(root).lower() == "localization"
                or "localization" in root.replace("\\", "/").lower()
            ):
                _add(os.path.join(root, "dictionary.cfg"))
            depth = root[len(gd):].count(os.sep)
            if depth > 5:
                dirs[:] = []
        # Ensure Squad is present even if walk truncated
        _add(os.path.join(gd, "Squad", "Localization", "dictionary.cfg"))
        _add(
            os.path.join(
                gd, "SquadExpansion", "Serenity", "Localization", "dictionary.cfg"
            )
        )
        _add(
            os.path.join(
                gd,
                "SquadExpansion",
                "MakingHistory",
                "Localization",
                "dictionary.cfg",
            )
        )

    # Re-order: paths sharing the most path prefix with filepath first
    fp_abs = os.path.abspath(filepath).lower()
    def _score(p: str) -> tuple:
        pl = p.lower()
        # longer common prefix → better
        n = 0
        for a, b in zip(fp_abs.replace("\\", "/"), pl.replace("\\", "/")):
            if a != b:
                break
            n += 1
        return (-n, pl)

    found.sort(key=_score)
    return found


def load_merged_dictionary(filepath: str = "") -> Dict[str, str]:
    """Merge all nearby dictionary.cfg files (Squad + DLC expansions)."""
    out: Dict[str, str] = {}
    paths = find_all_dictionaries_near(filepath) if filepath else []
    # Merge farthest → closest so nearer expansion wins on key clashes
    for path in reversed(paths):
        try:
            out.update(load_dictionary_file(path))
        except Exception:
            pass
    return out


def resolve_loc(
    text: str,
    dictionary: Optional[Dict[str, str]] = None,
    *,
    filepath: str = "",
) -> str:
    """Return localized display string; pass through literals unchanged."""
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    if not is_loc_key(s):
        return s
    d = dictionary
    if d is None:
        d = load_merged_dictionary(filepath) if filepath else {}
    if s in d:
        return d[s]
    if s.startswith("#") and s[1:] in d:
        return d[s[1:]]
    return s
