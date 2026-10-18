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

"""Write / patch ModulePartVariants into a part .cfg from ``mu_variants`` JSON.

Preserves the rest of the original cfg text; upserts only the variants MODULE.
"""

from __future__ import annotations

import os
import re


def _texture_url_for_cfg(tex_value, mudir, gamedata_root=None):
    """Stock-like URL: stem without extension; GameData-relative when possible."""
    if not tex_value:
        return tex_value
    v = str(tex_value).strip().strip('"')
    # Already a GameData URL
    if "/" in v.replace("\\", "/") and not os.path.isabs(v):
        return os.path.splitext(v.replace("\\", "/"))[0]
    stem = os.path.splitext(os.path.basename(v))[0]
    folder = mudir or ""
    if gamedata_root and folder:
        try:
            rel = os.path.relpath(folder, gamedata_root).replace("\\", "/")
            if not rel.startswith(".."):
                return f"{rel}/{stem}".replace("//", "/")
        except Exception:
            pass
    return stem


def _find_gamedata_root(path):
    cur = os.path.abspath(path or "")
    for _ in range(16):
        if os.path.basename(cur).lower() == "gamedata":
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def format_module_part_variants(data, mudir=None):
    """Return MODULE { name = ModulePartVariants &  } text from mu_variants dict."""
    variants = data.get("variants") or []
    lines = ["\tMODULE", "\t{", "\t\tname = ModulePartVariants"]
    base = data.get("base")
    base_display = data.get("baseDisplayName")
    base_theme = data.get("baseThemeName")
    # Synthetic Stock is not a real VARIANT block   use baseDisplay/theme only
    stock_names = {
        v.get("name") for v in variants if v.get("stock")
    }
    if base and base not in stock_names:
        lines.append(f"\t\tbaseVariant = {base}")
    if base_display:
        lines.append(f"\t\tbaseDisplayName = {base_display}")
    if base_theme:
        lines.append(f"\t\tbaseThemeName = {base_theme}")
    gd = _find_gamedata_root(mudir) if mudir else None
    for v in variants:
        if v.get("stock"):
            continue
        name = v.get("name") or "Variant"
        lines.append("\t\tVARIANT")
        lines.append("\t\t{")
        lines.append(f"\t\t\tname = {name}")
        disp = v.get("displayName") or name
        lines.append(f"\t\t\tdisplayName = {disp}")
        theme = v.get("themeName") or name
        lines.append(f"\t\t\tthemeName = {theme}")
        objs = v.get("objects") or {}
        if objs:
            lines.append("\t\t\tGAMEOBJECTS")
            lines.append("\t\t\t{")
            for k, vis in objs.items():
                lines.append(
                    f"\t\t\t\t{k} = {'true' if vis else 'false'}"
                )
            lines.append("\t\t\t}")
        texs = v.get("textures") or {}
        # Separate EXTRA_INFO-ish keys if present
        extra_keys = {
            k for k in texs
            if k.lower() in (
                "fairingtextureurl", "fairingbasetextureurl",
                "defaultbasetextureurl", "textureurl",
            )
        }
        main_tex = {k: texs[k] for k in texs if k not in extra_keys}
        if main_tex:
            lines.append("\t\t\tTEXTURE")
            lines.append("\t\t\t{")
            for k, val in main_tex.items():
                url = _texture_url_for_cfg(val, mudir, gd)
                lines.append(f"\t\t\t\t{k} = {url}")
            lines.append("\t\t\t}")
        if extra_keys:
            lines.append("\t\t\tEXTRA_INFO")
            lines.append("\t\t\t{")
            for k in extra_keys:
                url = _texture_url_for_cfg(texs[k], mudir, gd)
                lines.append(f"\t\t\t\t{k} = {url}")
            lines.append("\t\t\t}")
        disabled = v.get("disabledAnimations") or []
        if disabled:
            lines.append(
                "\t\t\tdisabledAnimations = " + ", ".join(disabled)
            )
        lines.append("\t\t}")
    lines.append("\t}")
    return "\n".join(lines) + "\n"


def _extract_brace_block(text, open_brace_index):
    """Given index of '{', return (start_of_MODULE_or_block, end_exclusive)."""
    depth = 0
    i = open_brace_index
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return open_brace_index, i + 1
        i += 1
    return open_brace_index, len(text)


def find_module_part_variants_span(cfg_text):
    """Return (start, end) of MODULE { &  ModulePartVariants &  } or None."""
    if not cfg_text or "ModulePartVariants" not in cfg_text:
        return None
    for m in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        brace = m.end() - 1
        b0, b1 = _extract_brace_block(cfg_text, brace)
        body = cfg_text[b0 + 1:b1 - 1]
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if nm and nm.group(1).strip().strip('"') == "ModulePartVariants":
            # Include leading whitespace / MODULE keyword
            start = m.start()
            # Expand to line start
            while start > 0 and cfg_text[start - 1] in (" ", "\t"):
                start -= 1
            return start, b1
    return None


def update_mesh_model_refs(cfg_text, mu_basename):
    """If mesh=/model= basename differs from .mu stem, update it."""
    if not cfg_text or not mu_basename:
        return cfg_text
    stem = os.path.splitext(mu_basename)[0]

    def repl_mesh(m):
        key = m.group(1)
        val = m.group(2).strip().strip('"')
        # Keep GameData URLs; only bare filenames
        if "/" in val.replace("\\", "/"):
            return m.group(0)
        cur_stem = os.path.splitext(os.path.basename(val))[0]
        if cur_stem.lower() == stem.lower():
            return m.group(0)
        # Preserve extension style if any
        ext = os.path.splitext(val)[1]
        return f"{key} = {stem}{ext}"

    return re.sub(
        r"^(\s*(?:mesh|model)\s*)=\s*(.+)$",
        repl_mesh,
        cfg_text,
        flags=re.M | re.I,
    )


def patch_cfg_with_variants(cfg_text, data, mudir=None, mu_basename=None):
    """Return full cfg text with ModulePartVariants upserted from data."""
    module_txt = format_module_part_variants(data, mudir=mudir)
    text = cfg_text or ""
    if mu_basename:
        text = update_mesh_model_refs(text, mu_basename)
    span = find_module_part_variants_span(text)
    if span:
        start, end = span
        # Keep a blank line after if present
        return text[:start] + module_txt + text[end:]
    # Insert before final PART closing brace if possible
    # Find last top-level closing of PART
    part_m = re.search(r"PART\s*\{", text, re.I)
    if part_m:
        brace = part_m.end() - 1
        _b0, b1 = _extract_brace_block(text, brace)
        insert_at = b1 - 1
        # Back up over whitespace before }
        while insert_at > 0 and text[insert_at - 1] in (" ", "\t", "\r", "\n"):
            insert_at -= 1
        return text[:insert_at] + "\n" + module_txt + text[insert_at:]
    return text.rstrip() + "\n" + module_txt


def write_part_cfg(
    path,
    data,
    source_text=None,
    mudir=None,
    mu_basename=None,
    mu_sounds=None,
):
    """Write patched cfg to ``path``. Returns path.

    Patches ModulePartVariants from ``data`` when present, then EFFECTS/AUDIO
    from ``mu_sounds`` (animation sound preview round-trip).
    """
    if source_text is None:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                source_text = f.read()
        else:
            source_text = "PART\n{\n\tname = part\n}\n"
    out = source_text
    if data:
        out = patch_cfg_with_variants(
            out, data, mudir=mudir, mu_basename=mu_basename
        )
    elif mu_basename:
        out = update_mesh_model_refs(out, mu_basename)
    if mu_sounds:
        try:
            from .sounds_cfg import patch_cfg_with_sounds
            out = patch_cfg_with_sounds(out, mu_sounds)
        except Exception:
            pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    return path
