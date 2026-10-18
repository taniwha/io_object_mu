# vim:ts=4:et
# <pep8 compliant>
"""Addon-bundled stock KSP assets (Unity-embedded, not shipped in GameData).

Used as fallback after the user GameData path from Preferences.
"""
from __future__ import annotations

import os
from typing import Optional

_AUDIO_EXTS = (".wav", ".ogg", ".flac", ".mp3")


def bundled_stock_root() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "bundled_stock")


def bundled_sounds_dir() -> str:
    return os.path.join(bundled_stock_root(), "Sounds")


def bundled_fonts_dir() -> str:
    return os.path.join(bundled_stock_root(), "Fonts")


def resolve_bundled_sound(clip: str) -> Optional[str]:
    """Resolve bare or path clip against ``bundled_stock/Sounds``."""
    if not clip:
        return None
    clip = clip.strip().strip('"').replace("\\", "/")
    sounds = bundled_sounds_dir()
    if not os.path.isdir(sounds):
        return None
    bare = os.path.basename(clip)
    stem = os.path.splitext(bare)[0]
    names = []
    if bare.lower().endswith(_AUDIO_EXTS):
        names.append(bare)
    else:
        for e in _AUDIO_EXTS:
            names.append(stem + e)
    for name in names:
        p = os.path.join(sounds, name)
        if os.path.isfile(p):
            return os.path.abspath(p)
    try:
        lower_map = {fn.lower(): fn for fn in os.listdir(sounds)}
    except Exception:
        return None
    for name in names:
        hit = lower_map.get(name.lower())
        if hit:
            return os.path.abspath(os.path.join(sounds, hit))
    return None


def resolve_bundled_font(name: str) -> Optional[str]:
    """Resolve a font basename (with or without .ttf) under bundled Fonts."""
    if not name:
        return None
    fonts = bundled_fonts_dir()
    if not os.path.isdir(fonts):
        return None
    bare = os.path.basename(name.strip())
    cands = [bare]
    if not bare.lower().endswith(".ttf"):
        cands.append(bare + ".ttf")
    for c in cands:
        p = os.path.join(fonts, c)
        if os.path.isfile(p):
            return os.path.abspath(p)
    try:
        lower_map = {fn.lower(): fn for fn in os.listdir(fonts)}
    except Exception:
        return None
    for c in cands:
        hit = lower_map.get(c.lower())
        if hit:
            return os.path.abspath(os.path.join(fonts, hit))
    return None
