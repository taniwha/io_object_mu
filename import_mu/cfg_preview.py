# vim:ts=4:et
# <pep8 compliant>
"""Viewport-only helpers from sibling part.cfg (inspired by modding workflows).

Markers are tagged mu_fx_preview / .cfg_preview and skipped by export filters.

ModulePartVariants: parse GAMEOBJECTS / TEXTURE switches, hide non-default
branches, store ``mu_variants`` JSON on the import root for Options UI.

TEXTURE / GAMEOBJECTS preview swaps are viewport-only: normal .mu export must
call ``prepare_stock_for_export`` (or ``restore_default_textures`` + base
variant) so stock materials are written. Use Export Active Variant to bake
the currently selected look.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import bpy
from mathutils import Vector


_CFG_PREVIEW_SUFFIX = ".cfg_preview"
_flag_preview_import_failed = False  # set if flag_preview.py is corrupt (UTF-16/nulls)
MU_VARIANTS_KEY = "mu_variants"
# Guard: secondary MODEL .mu imports must not recurse into MODEL loading.
_SECONDARY_MODEL_IMPORT = False
# Guard: apply_variant must not re-enter via Scene enum update callbacks
# (setting scene.mu_paint_variant / mu_mesh_variant from inside apply).
_VARIANT_APPLY_DEPTH = 0

MU_COLOR_CHANGER_KEY = "mu_color_changer"
MU_BROKEN_KEY = "mu_broken_names"
MU_JETTISON_KEY = "mu_jettison_names"
# Implicit KSP look when cfg has VARIANT blocks but no baseVariant= —
# stock .mu materials (e.g. Serenity "Gray with Stripes" color DDS).
STOCK_VARIANT_NAME = "Stock"

# ---------------------------------------------------------------------------
# Variant / B9 / secondary-MODEL console spam
# 0 = off (default), 1 = verbose INFO + WARNING related to variants
# ---------------------------------------------------------------------------
MU_VARIANT_LOG = 0


def _vlog(*args, **kwargs):
    """Print only when MU_VARIANT_LOG is non-zero."""
    if MU_VARIANT_LOG:
        print(*args, **kwargs)




def _parse_vec3(raw):
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if len(parts) < 3:
        return None
    try:
        # Unity XYZ → Blender X Z Y
        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        return Vector((x, z, y))
    except Exception:
        return None


def _muname_match_stems(muname):
    """Stems used to match a .mu against part.cfg (strip tester ``_temp``).

    Exported round-trips embed the Unity transform name (often ``Size1.5_…``
    with dots) while GameData paths / cfg use underscores (``Size1_5_…``).
    Always emit both forms so reimport can still find ModulePartVariants.
    """
    if not muname:
        return []
    # Strip Blender ∧ / .001 noise if a full object name sneaks in
    muname = muname.split("∧")[0].strip()
    if "." in muname:
        base, suf = muname.rsplit(".", 1)
        if suf.isdigit():
            muname = base
    stems = []

    def _add(s):
        if s and s not in stems:
            stems.append(s)

    _add(muname)
    # Size1_5_Tank_04_temp / Size1_5_Tank_04_temp_1 → Size1_5_Tank_04
    stripped = re.sub(r"_temp(?:_\d+)?$", "", muname, flags=re.I)
    _add(stripped)
    # Dot ↔ underscore aliases (export header vs MODEL= path)
    for s in list(stems):
        if "." in s:
            _add(s.replace(".", "_"))
        if "_" in s:
            # Only swap digit-boundary underscores that look like Size1_5 → Size1.5
            _add(re.sub(r"(?<=\d)_(?=\d)", ".", s))
    # Hyphen ↔ glued aliases (ReStock: restock-fuel-tank-* cfg vs restock-fueltank-*.mu)
    for s in list(stems):
        if "-" in s:
            _add(s.replace("-", ""))
            _add(s.replace("-", "_"))
        # fuel-tank ↔ fueltank / fuel_tank
        s2 = re.sub(r"fuel[_-]?tank", "fueltank", s, flags=re.I)
        _add(s2)
        s3 = re.sub(r"fueltank", "fuel-tank", s, flags=re.I)
        _add(s3)
        s4 = re.sub(r"fueltank", "fuel_tank", s, flags=re.I)
        _add(s4)
    return stems


def _find_part_cfg(mudir, muname, filepath_stem=None):
    """Locate part.cfg next to .mu or referencing this model.

    ``filepath_stem`` is the on-disk .mu basename (e.g. ``Size1_5_Tank_01_temp``)
    — preferred over the Unity transform name embedded in the .mu header after
    export/reimport (``Size1.5_Tank_01``), which otherwise misses underscore cfgs.
    """
    if not mudir:
        return None
    stems = []
    for src in (filepath_stem, muname):
        for s in _muname_match_stems(src):
            if s not in stems:
                stems.append(s)
    if not stems:
        return None
    candidates = []
    for stem in stems:
        for name in (stem + ".cfg", "part.cfg"):
            p = os.path.join(mudir, name)
            if os.path.isfile(p) and p not in candidates:
                candidates.append(p)
    if os.path.isdir(mudir):
        for fn in os.listdir(mudir):
            if fn.lower().endswith(".cfg"):
                p = os.path.join(mudir, fn)
                if p not in candidates:
                    candidates.append(p)
    parent = os.path.dirname(mudir)
    if parent and os.path.isdir(parent):
        for fn in os.listdir(parent):
            if fn.lower().endswith(".cfg"):
                p = os.path.join(parent, fn)
                if p not in candidates:
                    candidates.append(p)
    stem_lows = [s.lower() for s in stems if s]
    scored = []
    for p in candidates:
        try:
            text = open(p, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if "PART" not in text and "part" not in text[:200].lower():
            continue
        low = text.lower().replace("\\", "/")
        hit = next((s for s in stem_lows if s in low), None)
        # PART { name = science_module } matches mu stem science_module_small
        m_part = re.search(r"(?im)^\s*name\s*=\s*([^\s#/\"]+)", text)
        part_name = (m_part.group(1).strip() if m_part else "").lower()
        if part_name and hit is None:
            pn = part_name.replace(".", "_")
            for s in stem_lows:
                sn = s.replace(".", "_")
                if sn == pn or sn.startswith(pn + "_") or pn.startswith(sn + "_"):
                    hit = s
                    break
        if stem_lows and hit is None:
            # Also try basename match (Size1p5_Tank_01.cfg vs Size1_5_Tank_01)
            base = os.path.splitext(os.path.basename(p))[0].lower()
            base_norm = base.replace(".", "_").replace("p", "_")
            if not any(
                s.replace(".", "_").replace("p", "_") in base_norm
                or base_norm in s.replace(".", "_")
                for s in stem_lows
            ):
                continue
            hit = base
        score = 0
        if "modulepartvariants" in low:
            score += 10
        if part_name:
            pn = part_name.replace(".", "_")
            for s in stem_lows:
                sn = s.replace(".", "_")
                if sn == pn:
                    score += 24
                    break
                if sn.startswith(pn + "_") or pn.startswith(sn + "_"):
                    score += 20
                    break
        # Prefer cfg living next to the .mu over parent-folder noise
        try:
            if os.path.normcase(os.path.dirname(p)) == os.path.normcase(mudir):
                score += 6
        except Exception:
            pass
        for s in stem_lows:
            if f"mesh = {s}" in low or f"mesh={s}" in low:
                score += 5
            if f"model = " in low and s in low:
                score += 4
            if os.path.basename(p).lower().startswith(s.replace(".", "").replace("_", "")[:8]):
                score += 1
            if os.path.basename(p).lower().startswith(s.lower()):
                score += 3
            # Prefer non-temp stem over Foo_temp when both match
            if s == stem_lows[-1] and len(stem_lows) > 1:
                score += 2
        # Prefer cfg whose basename shares the part number token
        bn = os.path.splitext(os.path.basename(p))[0].lower()
        for s in stem_lows:
            sn = s.lower().replace(".", "_")
            bn_n = bn.replace(".", "_").replace("p", "_")
            if sn.replace("p", "_") == bn_n or sn in bn_n or bn_n in sn:
                score += 8
                break
        scored.append((score, p))
    if scored:
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]
    # Fallback: search GameData for ``{stem}.cfg`` when mudir is outside
    # (e.g. future OS-temp round-trip). Prefer non-recursive shallow match.
    gd = _game_data_root(mudir)
    if not gd:
        # Addon bundled test GameData
        try:
            addon_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            test_gd = os.path.join(addon_root, "test tools v2", "GameData")
            if os.path.isdir(test_gd):
                gd = test_gd
        except Exception:
            gd = None
    if gd and stem_lows:
        # Prefer underscore / stripped forms for filename match
        wants = []
        for s in stem_lows:
            wants.append(s.lower())
            wants.append(s.lower().replace(".", "_"))
            wants.append(s.lower().replace(".", "p").replace("_", "p"))
            # Size1_5 → Size1p5
            wants.append(re.sub(r"(\d)_(\d)", r"\1p\2", s.lower()))
        wants = list(dict.fromkeys(wants))
        # Avoid small.cfg matching science_module_small via ``base in w``.
        _trivial = frozenset({
            "small", "large", "tiny", "mini", "model", "part", "tank",
            "engine", "wing", "nose", "base", "body", "panel", "door",
            "light", "probe", "core",
        })

        def _gd_cfg_matches(base, w):
            if not base or not w:
                return False
            if base == w:
                return True
            if base in _trivial or w in _trivial:
                return False
            if len(base) < 6 or len(w) < 6:
                return False
            if (w.startswith(base + "_") or w.startswith(base + ".")
                    or base.startswith(w + "_") or base.startswith(w + ".")):
                return True
            # Long containment only (Size1p5Tank… aliases); never short tokens
            if len(base) >= 8 and len(w) >= 8 and (base in w or w in base):
                return True
            return False

        try:
            for root, _dirs, files in os.walk(gd):
                for fn in files:
                    if not fn.lower().endswith(".cfg"):
                        continue
                    base = os.path.splitext(fn)[0].lower()
                    if any(_gd_cfg_matches(base, w) for w in wants):
                        return os.path.join(root, fn)
        except Exception:
            pass
    # Never return an unmatched first candidate — that picked MonoPropMini.cfg
    # for Size1.5_Tank_* reimports and dropped ModulePartVariants.
    return None

def _make_marker(collection, parent, name, loc, display="PLAIN_AXES", size=0.15, color=(1, 0.4, 0.1, 1)):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = display
    obj.empty_display_size = size
    collection.objects.link(obj)
    obj.parent = parent
    obj.location = loc
    obj["mu_fx_preview"] = 1
    try:
        obj.color = color
    except Exception:
        pass
    return obj


def _variant_object_key(name):
    """Map Blender object name → ModulePartVariants GAMEOBJECTS key.

    Importer appends ``∧`` after Unity transform names (e.g. ``Orthogonal∧``),
    and Blender may add ``.001``. Stock cfg uses bare names (``Orthogonal``).
    """
    if not name:
        return ""
    try:
        from ..utils.utils import strip_nnn
        return strip_nnn(name) or ""
    except Exception:
        raw = name
        ind = raw.rfind("\u2227")
        if ind >= 0:
            raw = raw[:ind]
        ind = raw.rfind(".")
        if ind >= 0 and len(raw) - ind == 4 and raw[ind + 1:].isdigit():
            raw = raw[:ind]
        return raw


def _index_named_objects(root):
    """Map GAMEOBJECTS key → list of objects under root (exact Unity names)."""
    named = {}
    if root is None:
        return named
    stack = [root]
    while stack:
        o = stack.pop()
        raw = _variant_object_key(o.name or "")
        if raw:
            named.setdefault(raw, []).append(o)
            if "/" in raw:
                leaf = raw.rsplit("/", 1)[-1]
                if leaf:
                    named.setdefault(leaf, []).append(o)
        # Secondary MODEL tags — B9 transform= full path / leaf / (Clone)
        try:
            mleaf = o.get("mu_cfg_model_leaf") or ""
            if mleaf:
                named.setdefault(mleaf, []).append(o)
                named.setdefault(mleaf + "(Clone)", []).append(o)
            murl = o.get("mu_cfg_model") or ""
            if murl:
                named.setdefault(murl, []).append(o)
                named.setdefault(murl + "(Clone)", []).append(o)
                named.setdefault(murl.replace(chr(92), "/").split("/")[-1], []).append(o)
        except Exception:
            pass
        stack.extend(list(o.children))
    return named


def _b9_name_aliases(key):
    """Candidates for matching B9 transform= / GAMEOBJECTS names to hierarchy.

    Handles Unity runtime suffixes and GameData paths, e.g.::
        Bluedog_DB/Parts/Delta/DeltaK/bluedog_DeltaP_Stage(Clone)
        → bluedog_DeltaP_Stage(Clone), bluedog_DeltaP_Stage, …
    """
    if not key:
        return []
    n = str(key).strip().strip('"').replace("\\", "/")
    out = []
    seen = set()

    def add(s):
        s = (s or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    add(n)
    # strip (Clone) / (Clone)/…
    base = n
    for suf in ("(Clone)", " (Clone)"):
        if base.endswith(suf):
            base = base[: -len(suf)].rstrip()
            add(base)
    # leaf after last /
    leaf = base.split("/")[-1]
    add(leaf)
    if leaf.endswith("(Clone)"):
        add(leaf[: -len("(Clone)")].rstrip())
    # drop .mu-ish extensions
    for cand in list(out):
        if cand.lower().endswith(".mu"):
            add(cand[:-3])
    return out


def _lookup_named(named, key):
    """Resolve GAMEOBJECTS / B9 transform name → objects (case-insensitive).

    Short keys (Left/Right/Skin/…, len≤5) use *exact* match only — substring
    matching false-positives and leaves both sides visible (DropTank).
    """
    if not key or not named:
        return []
    aliases = _b9_name_aliases(key)
    # exact / case-insensitive on aliases
    for a in aliases:
        if a in named:
            return named[a]
        al = a.lower()
        for k, objs in named.items():
            if k.lower() == al:
                return objs
    # Short tokens: no fuzzy (Left must not match LeftWing etc. via contains)
    leaves = [a.lower() for a in aliases if a]
    if not leaves:
        return []
    if max(len(x) for x in leaves) <= 5:
        return []
    # Longer names: prefix / contains (path leaves, Clone suffixes already in aliases)
    hits = []
    for k, objs in named.items():
        kl = k.lower()
        for leaf in leaves:
            if not leaf or len(leaf) < 4:
                continue
            if kl == leaf or kl.startswith(leaf + ".") or kl.startswith(leaf + "("):
                hits.extend(objs)
                break
            # contains only when leaf is reasonably long
            if len(leaf) >= 6 and (leaf in kl or kl in leaf):
                hits.extend(objs)
                break
    return hits


def _set_object_hide(obj, hide):
    """Hide/show a single object (not children)."""
    if obj is None:
        return
    try:
        obj.hide_viewport = hide
        obj.hide_render = hide
        try:
            obj.hide_set(hide)
        except Exception:
            pass
        # ModuleLight Flare cards must never regain visible_shadow (opaque EEVEE blotches)
        flare = bool(obj.get("mu_light_flare"))
        for attr, val in (
            ("visible_camera", not hide),
            ("visible_shadow", False if flare else (not hide)),
            ("visible_transmission", not hide),
            ("visible_volume_scatter", not hide),
        ):
            if hasattr(obj, attr):
                try:
                    setattr(obj, attr, val)
                except Exception:
                    pass
        if hide:
            obj["mu_variant_hidden"] = 1
        elif "mu_variant_hidden" in obj:
            del obj["mu_variant_hidden"]
    except Exception:
        pass


def _set_branch_hide(obj, hide, keyed_names=None):
    """Hide/show obj and descendants, skipping children listed in GAMEOBJECTS.

    Critical for RCSBlock Orthogonal + thruster1..5: unhiding Orthogonal must
    NOT force all thrusters visible — each thrusterN has its own flag.
    """
    keyed = keyed_names or set()
    stack = [obj]
    while stack:
        o = stack.pop()
        _set_object_hide(o, hide)
        for ch in o.children:
            ckey = _variant_object_key(ch.name or "")
            if ckey and ckey in keyed:
                # Controlled by its own GAMEOBJECTS entry
                continue
            stack.append(ch)


def parse_module_jettison_names(cfg_text):
    """Return lowercased GO names from all ModuleJettison ``jettisonName`` lines.

    Used so fairing/shroud preview hide still covers jettison meshes that are
    also listed in ModulePartVariants GAMEOBJECTS (Poodle Shroud1/2, Terrier
    Short/TallShroud) without hiding non-jettison variant GOs (LV-1 ``Shroud``
    chamber).
    """
    if not cfg_text or "jettisonName" not in cfg_text:
        return []
    names = []
    seen = set()
    for m in re.finditer(
        r"^\s*jettisonName\s*=\s*(.+)$", cfg_text, re.M | re.I
    ):
        raw = m.group(1).strip().strip('"').split("//")[0].strip()
        for part in raw.replace(";", ",").split(","):
            n = part.strip()
            if not n:
                continue
            key = n.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(n)
    return names



def _parse_brace_blocks(text, keyword):
    """Yield body strings of KEYWORD { ... } with correct brace depth."""
    if not text:
        return
    for m in re.finditer(rf"{keyword}\s*\{{", text, re.I):
        s0 = m.end() - 1
        depth = 0
        j = s0
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    yield text[s0 + 1:j]
                    break
            j += 1


def _parse_b9_texture_block(body):
    """Parse one B9 SUBTYPE → TEXTURE { ... } block into a dict."""
    tex = {
        "texture": None,
        "currentTexture": None,
        "isNormalMap": False,
        "shaderProperty": None,
        "transforms": [],
        "baseTransforms": [],
    }
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip().lower()
        v = v.strip().split("//")[0].strip().strip('"')
        if k == "texture":
            tex["texture"] = v
        elif k == "currenttexture":
            tex["currentTexture"] = v
        elif k == "isnormalmap":
            tex["isNormalMap"] = v.lower() in ("true", "1", "yes")
        elif k == "shaderproperty":
            tex["shaderProperty"] = v
        elif k == "transform":
            if v:
                tex["transforms"].append(v)
        elif k == "basetransform":
            if v:
                tex["baseTransforms"].append(v)
    if not tex["texture"]:
        return None
    if not tex["shaderProperty"]:
        tex["shaderProperty"] = "_BumpMap" if tex["isNormalMap"] else "_MainTex"
    return tex



def _apply_variant_node_positions(root, chosen):
    """Move node_* empties (and cache) from B9/ModulePartVariants node data.

    ``chosen`` is a variant entry dict that may contain::
        "nodes": { "top": {"position": [x,y,z], "transform": "node_stack_top"}, ... }

    Positions are Blender-space (already converted from Unity when parsed).
    """
    if root is None or not chosen:
        return
    nodes = chosen.get("nodes") or {}
    if not nodes:
        return
    from mathutils import Vector

    def _find_named(want):
        want_l = (want or "").lower()
        if not want_l:
            return None
        stack = [root]
        seen = set()
        while stack:
            o = stack.pop()
            if o is None:
                continue
            try:
                key = o.as_pointer()
            except Exception:
                key = id(o)
            if key in seen:
                continue
            seen.add(key)
            try:
                stack.extend(list(o.children))
            except Exception:
                pass
            try:
                n = (o.name or "").split("\u2227", 1)[0].strip()
            except Exception:
                continue
            if n.lower() == want_l or n.lower().startswith(want_l + "."):
                return o
            # node_stack_top matches name "top" when B9 uses short NODE names
            if want_l.startswith("node_") and n.lower() == want_l:
                return o
            if n.lower() == ("node_" + want_l) or n.lower().startswith("node_" + want_l):
                return o
        return None

    for nname, ndata in nodes.items():
        if not isinstance(ndata, dict):
            continue
        pos = ndata.get("position")
        tform = ndata.get("transform")
        target = None
        if tform:
            target = _find_named(tform)
        if target is None:
            target = _find_named(nname)
        if target is None and not (nname or "").lower().startswith("node_"):
            target = _find_named("node_" + nname)
            if target is None:
                target = _find_named("node_stack_" + nname)
        if target is None or pos is None or len(pos) < 3:
            continue
        try:
            # CFG/B9 positions are model-space relative to part root
            local = Vector((float(pos[0]), float(pos[1]), float(pos[2])))
            # If target is parented under root, set local translation in root space
            if target.parent is not None:
                try:
                    # world desired = root @ local
                    world = root.matrix_world @ local
                    # convert to parent local
                    inv = target.parent.matrix_world.inverted()
                    target.location = inv @ world
                except Exception:
                    target.location = local
            else:
                target.location = local
        except Exception as e:
            print(f"WARNING: move node {nname}: {e}")


def parse_b9_part_switch(cfg_text):
    """Parse ModuleB9PartSwitch: transforms + full TEXTURE nodes per SUBTYPE.

    B9 enables listed transforms per subtype and disables the rest. TEXTURE
    blocks swap maps (optionally filtered by currentTexture / transform /
    baseTransform / shaderProperty / isNormalMap) — same coverage as the
    in-game plugin for viewport preview.
    """
    if not cfg_text or "ModuleB9PartSwitch" not in cfg_text:
        return None
    modules = []
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        if not re.search(r"^\s*name\s*=\s*ModuleB9PartSwitch\b", body, re.M | re.I):
            continue
        mid = re.search(r"^\s*moduleID\s*=\s*(.+)$", body, re.M | re.I)
        module_id = (
            mid.group(1).strip().strip('"').split("//")[0].strip()
            if mid else "B9"
        )
        subtypes = []
        all_transforms = set()
        for sbody in _parse_brace_blocks(body, "SUBTYPE"):
            nm = re.search(r"^\s*name\s*=\s*(.+)$", sbody, re.M | re.I)
            if not nm:
                continue
            sname = nm.group(1).strip().strip('"').split("//")[0].strip()
            title_m = re.search(r"^\s*title\s*=\s*(.+)$", sbody, re.M | re.I)
            title = (
                title_m.group(1).strip().strip('"').split("//")[0].strip()
                if title_m else sname
            )
            # Mesh visibility transforms: ONLY top-level transform= on the SUBTYPE.
            # Never take transform= from inside TEXTURE { } (those filter which
            # meshes get a paint map — they must NOT drive hide/show).
            transforms = []
            # Strip nested TEXTURE/NODE/MATERIAL blocks before scanning lines
            sbody_mesh = sbody
            for nest_kw in ("TEXTURE", "NODE", "MATERIAL", "TRANSFORM"):
                for nb in list(_parse_brace_blocks(sbody, nest_kw)):
                    # remove one occurrence of the nested body from scan text
                    # (brace content only — also drop the keyword line roughly)
                    sbody_mesh = sbody_mesh.replace(nb, "")
            for line in sbody_mesh.splitlines():
                line = line.strip()
                if re.match(r"(?i)^transform\s*=", line):
                    _, _, v = line.partition("=")
                    t = v.strip().split("//")[0].strip().strip('"')
                    if t:
                        transforms.append(t)
                        all_transforms.add(t)
            textures = []
            for tbody in _parse_brace_blocks(sbody, "TEXTURE"):
                td = _parse_b9_texture_block(tbody)
                if td:
                    textures.append(td)
            # B9 NODE { name=... position=x,y,z ... } — attach points per subtype
            nodes = {}
            for nbody in _parse_brace_blocks(sbody, "NODE"):
                nn = re.search(r"^\s*name\s*=\s*(.+)$", nbody, re.M | re.I)
                if not nn:
                    continue
                nname = nn.group(1).strip().strip('"').split("//")[0].strip()
                if not nname:
                    continue
                # Prefer explicit position = x,y,z (Unity Y-up)
                pos = None
                pm = re.search(r"^\s*position\s*=\s*(.+)$", nbody, re.M | re.I)
                if pm:
                    raw = pm.group(1).strip().split("//")[0].strip()
                    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
                    if len(parts) >= 3:
                        try:
                            ux, uy, uz = float(parts[0]), float(parts[1]), float(parts[2])
                            # Unity Y-up → Blender Z-up
                            pos = [ux, uz, uy]
                        except Exception:
                            pos = None
                # Optional transform = node empty name in hierarchy
                tm = re.search(r"^\s*transform\s*=\s*(.+)$", nbody, re.M | re.I)
                tform = (
                    tm.group(1).strip().strip('"').split("//")[0].strip()
                    if tm else None
                )
                nodes[nname] = {"position": pos, "transform": tform}
            # Bare node_stack_* = lines inside SUBTYPE (some packs)
            for line in sbody.splitlines():
                line = line.strip()
                if not re.match(r"(?i)^node_[A-Za-z0-9_.-]+\s*=", line):
                    continue
                if line.startswith("//"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                vals = v.split("//", 1)[0].strip().split(",")
                if len(vals) < 3:
                    continue
                try:
                    ux, uy, uz = float(vals[0]), float(vals[1]), float(vals[2])
                    nodes[k] = {"position": [ux, uz, uy], "transform": None}
                except Exception:
                    pass
            # TRANSFORM { transformName= rotationOffset= positionOffset= }
            xforms = []
            for tbody in _parse_brace_blocks(sbody, "TRANSFORM"):
                tnm = re.search(
                    r"^\s*transformName\s*=\s*(.+)$", tbody, re.M | re.I
                )
                if not tnm:
                    tnm = re.search(r"^\s*name\s*=\s*(.+)$", tbody, re.M | re.I)
                tname = (
                    tnm.group(1).strip().strip('"').split("//")[0].strip()
                    if tnm else ""
                )
                if not tname:
                    continue
                xf = {"name": tname}
                for key in ("rotationOffset", "positionOffset", "scaleOffset"):
                    m = re.search(
                        r"^\s*%s\s*=\s*(.+)$" % key, tbody, re.M | re.I
                    )
                    if not m:
                        continue
                    raw = m.group(1).strip().split("//")[0].strip()
                    parts = [
                        p.strip()
                        for p in raw.replace(";", ",").split(",")
                        if p.strip()
                    ]
                    if len(parts) >= 3:
                        try:
                            xf[key] = [
                                float(parts[0]), float(parts[1]), float(parts[2])
                            ]
                        except Exception:
                            pass
                xforms.append(xf)

            def _sub_meta(key):
                m = re.search(
                    r"^\s*%s\s*=\s*(.+)$" % re.escape(key), sbody, re.M | re.I
                )
                if not m:
                    return None
                return m.group(1).strip().strip('"').split("//")[0].strip()

            subtypes.append({
                "name": sname,
                "title": title,
                "transforms": transforms,
                "textures": textures,
                "nodes": nodes,
                "transform_ops": xforms,
                "primaryColor": _sub_meta("primaryColor"),
                "secondaryColor": _sub_meta("secondaryColor"),
                "parentID": _sub_meta("parentID"),
                "volumeAddedToParent": _sub_meta("volumeAddedToParent"),
                "tankType": _sub_meta("tankType"),
                "node": _sub_meta("node"),
            })
        if not subtypes:
            continue

        def _mod_meta(key):
            m = re.search(
                r"^\s*%s\s*=\s*(.+)$" % re.escape(key), body, re.M | re.I
            )
            if not m:
                return None
            return m.group(1).strip().strip('"').split("//")[0].strip()

        modules.append({
            "moduleID": module_id,
            "subtypes": subtypes,
            "all_transforms": sorted(all_transforms),
            "switcherDescription": _mod_meta("switcherDescription"),
            "switchInFlight": _mod_meta("switchInFlight"),
            "affectDragCubes": _mod_meta("affectDragCubes"),
            "baseVolume": _mod_meta("baseVolume"),
        })
    return modules or None


def b9_to_variant_info(modules):
    """Convert B9 modules into a ModulePartVariants-compatible info dict.

    ``textures`` is kept as a list of B9 TEXTURE descriptors under key
    ``b9_textures`` (applied by ``_apply_b9_textures``). Flat slot map is
    also filled for the simple single-TEXTURE case so stock path still works.
    """
    if not modules:
        return None
    variants = []
    base = None
    has_tex = False
    has_obj = False
    for mod in modules:
        mid = mod.get("moduleID") or "B9"
        all_t = mod.get("all_transforms") or []
        for i, st in enumerate(mod.get("subtypes") or []):
            sname = st.get("name") or ("Subtype%d" % i)
            enum_name = ("%s/%s" % (mid, sname)) if len(modules) > 1 else sname
            enabled = list(st.get("transforms") or [])
            objects = {}
            # Mesh-switch module: only subtypes that list transforms control
            # visibility of *this module's* all_transforms. Texture-only
            # subtypes leave objects {} so apply_variant does not hide the
            # whole part (previous bug: empty enabled → every transform False).
            if all_t and enabled:
                for t in all_t:
                    objects[t] = t in set(enabled)
                has_obj = True
            elif all_t and not (st.get("textures") or []):
                # Explicit empty mesh subtype → hide optional transforms
                for t in all_t:
                    objects[t] = False
                has_obj = True
            b9_tex = list(st.get("textures") or [])
            if b9_tex:
                has_tex = True
            # Flat map for the common single _MainTex case (ModulePartVariants path)
            flat = {}
            for td in b9_tex:
                slot = td.get("shaderProperty") or (
                    "_BumpMap" if td.get("isNormalMap") else "_MainTex"
                )
                url = td.get("texture")
                if url and slot not in flat:
                    flat[slot] = url
                    if slot == "_MainTex":
                        flat["mainTextureURL"] = url
            entry = {
                "name": enum_name,
                "displayName": st.get("title") or sname,
                "objects": objects,
                # Always list this module's transforms so empty subtypes
                # (Standard = no transform → hide TallDome) still exclusive-hide.
                "toggle_keys": list(all_t),
                "textures": flat,
                "b9_textures": b9_tex,
                "b9": True,
                "b9_moduleID": mid,
                "switcherDescription": mod.get("switcherDescription") or "",
                "nodes": dict(st.get("nodes") or {}),
                "transform_ops": list(st.get("transform_ops") or []),
            }
            for meta_k in (
                "primaryColor", "secondaryColor", "parentID",
                "volumeAddedToParent", "tankType", "node",
            ):
                if st.get(meta_k) is not None:
                    entry[meta_k] = st[meta_k]
            variants.append(entry)
            if base is None:
                base = enum_name
    if not variants:
        return None
    kind = "both" if (has_obj and has_tex) else ("texture" if has_tex else "model")
    # Carry module-level flags (first module) for CFG UI / tooling
    mod0 = modules[0] if modules else {}
    out = {
        "base": base,
        "variants": variants,
        "kind": kind,
        "source": "B9PartSwitch",
        "switchInFlight": mod0.get("switchInFlight"),
        "affectDragCubes": mod0.get("affectDragCubes"),
        "baseVolume": mod0.get("baseVolume"),
        "switcherDescription": mod0.get("switcherDescription"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _object_key_plain(name):
    n = (name or "").split("\u2227", 1)[0].strip()
    return n


def _collect_objects_for_b9_tex(root, transforms, base_transforms):
    """Objects targeted by B9 TEXTURE transform / baseTransform filters.

    Empty filters → entire hierarchy under root.
    """
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    if not transforms and not base_transforms:
        return list(stack)
    wanted = set()
    tset = list(transforms or [])
    bset = list(base_transforms or [])
    # Build name index once
    named = {}
    for o in stack:
        try:
            key = _object_key_plain(o.name)
            if key:
                named.setdefault(key, []).append(o)
        except Exception:
            pass
    for t in tset:
        for o in _lookup_named(named, t):
            wanted.add(o)
    for t in bset:
        for o in _lookup_named(named, t):
            wanted.add(o)
            try:
                for ch in getattr(o, "children_recursive", []) or []:
                    wanted.add(ch)
            except Exception:
                pass
    # Prefer targeted objects; only fall back to whole hierarchy if filters empty
    if transforms or base_transforms:
        return list(wanted)  # may be empty — caller skips; do NOT paint whole part
    return list(stack)


def _materials_on_objects(objs):
    mats = []
    seen = set()
    for o in objs or []:
        for slot in getattr(o, "material_slots", []) or []:
            mat = slot.material
            if mat is None:
                continue
            k = mat.as_pointer()
            if k in seen:
                continue
            seen.add(k)
            mats.append(mat)
    return mats


def _image_name_stem(img):
    if img is None:
        return ""
    try:
        n = img.name or ""
    except Exception:
        n = ""
    if not n:
        try:
            n = os.path.basename(bpy.path.abspath(img.filepath) or "")
        except Exception:
            n = ""
    return os.path.splitext(n)[0].lower()




def _image_name_stem(name):
    """Strip Blender .001 suffix and extension-ish tails for compare."""
    if not name:
        return ""
    n = str(name).strip()
    # Blender duplicate: foo.001
    import re
    n = re.sub(r"\.\d{3}$", "", n)
    return n.lower()


def _find_image_datablock(dname):
    """Resolve image by exact name, Blender .001 duplicate, or filepath stem.

    Texture cache / secondary MODEL imports often leave the real pixels on
    ``bluedog_Helios_Mesh.001`` while materials still reference ``bluedog_Helios_Mesh``.
    """
    if not dname:
        return None
    try:
        import bpy
    except Exception:
        return None
    if dname in bpy.data.images:
        img = bpy.data.images[dname]
        # Prefer non-empty / file-backed if multiple exist
        try:
            if img.filepath or (img.size[0] > 0):
                return img
        except Exception:
            return img
    stem = _image_name_stem(dname)
    # Exact stem match with .001/.002
    best = None
    for img in bpy.data.images:
        iname = img.name or ""
        if _image_name_stem(iname) != stem:
            # filepath basename
            try:
                fp = bpy.path.abspath(img.filepath) if img.filepath else ""
            except Exception:
                fp = ""
            if fp:
                import os
                base = os.path.splitext(os.path.basename(fp))[0]
                if _image_name_stem(base) != stem:
                    continue
            else:
                continue
        try:
            if img.size[0] > 0 or img.filepath:
                best = img
                break
        except Exception:
            best = img
            break
    return best


def _paint_target_materials(mats, filtered, data, td):
    """Choose which leaf materials get a B9 TEXTURE apply.

    Never blanket-apply Metal onto every mat when the transform filter only
    hits the tank body — lattice / Helios_Mesh must keep its own map.
    """
    mats = list(mats or [])
    if not mats:
        return []
    defaults = (data or {}).get("_default_maintex") or {}
    filtered = list(filtered or [])

    def _stem_for_mat(mat):
        d = defaults.get(mat.name) or ""
        if d:
            return _image_name_stem(d)
        try:
            node = _maintex_image_node(mat)
            img = getattr(node, "image", None) if node else None
            if img is not None:
                return _image_name_stem(img.name)
        except Exception:
            pass
        return ""

    ct = ((td or {}).get("currentTexture") or "").strip()
    ct_stem = _image_name_stem(ct) if ct else ""

    if filtered:
        seed = set()
        if ct_stem:
            seed.add(ct_stem)
        for mat in filtered:
            s = _stem_for_mat(mat)
            if s:
                seed.add(s)
        targets = []
        seen = set()
        for mat in filtered:
            if mat.name not in seen:
                targets.append(mat)
                seen.add(mat.name)
        for mat in mats:
            if mat.name in seen:
                continue
            s = _stem_for_mat(mat)
            if s and s in seed:
                targets.append(mat)
                seen.add(mat.name)
        if targets:
            return targets
        return filtered

    # No transform hits (typical secondary MODEL): paint the majority stock group
    # and/or mats matching currentTexture — leave unique maps (Helios) alone.
    if ct_stem:
        targets = [m for m in mats if _stem_for_mat(m) == ct_stem]
        if targets:
            return targets
    from collections import Counter
    counts = Counter()
    for m in mats:
        s = _stem_for_mat(m)
        if s:
            counts[s] += 1
    if counts:
        majority = counts.most_common(1)[0][0]
        targets = [m for m in mats if _stem_for_mat(m) == majority]
        if targets:
            print(
                "INFO: paint no-transform — applying to majority tex group %r (%d/%d mats)"
                % (majority, len(targets), len(mats))
            )
            return targets
    return mats


def _restore_default_textures(root, data):
    """Put materials back to maps cached at import (B9 paint off / Stock)."""
    if root is None or not data:
        return
    defaults = data.get("_default_maintex") or {}
    texprops = data.get("_default_texprops") or {}
    if not defaults and not texprops:
        # Nothing cached yet — do not wipe materials
        return
    mats = list(_iter_materials_under(root))
    # Include secondary MODEL materials so paint Green/Metal works on both
    for mat in mats:
        slots = dict(texprops.get(mat.name) or {})
        if not slots and defaults.get(mat.name):
            slots["_MainTex"] = defaults[mat.name]
        if not slots:
            continue
        for slot, dname in slots.items():
            if not dname:
                continue
            img = _find_image_datablock(dname)
            if img is None:
                continue
            try:
                _set_material_slot_image_viewport(mat, slot, img, data=data)
            except Exception:
                try:
                    _set_material_slot_image(mat, slot, img)
                except Exception:
                    pass


def _apply_b9_textures(root, data, chosen):
    """Full B9PartSwitch TEXTURE node application (viewport).

    Supports:
      texture, currentTexture, isNormalMap, shaderProperty,
      transform (multi), baseTransform (multi, +children).
    """
    entries = chosen.get("b9_textures") or []
    if not entries:
        # Paint/subtype with no TEXTURE block (e.g. Green) → restore stock maps
        try:
            _restore_default_textures(root, data)
        except Exception:
            pass
        return
    _ensure_default_textures_cached(root, data)
    for td in entries:
        url = td.get("texture")
        if not url:
            continue
        path = _resolve_texture_url(root, url)
        if not path:
            # try as-is relative path with extensions
            continue
        img = _load_variant_image(
            path, os.path.splitext(os.path.basename(path))[0]
        )
        if img is None:
            continue
        try:
            if td.get("isNormalMap"):
                img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
        slot = td.get("shaderProperty") or (
            "_BumpMap" if td.get("isNormalMap") else "_MainTex"
        )
        objs = _collect_objects_for_b9_tex(
            root, td.get("transforms") or [], td.get("baseTransforms") or []
        )
        if (td.get("transforms") or td.get("baseTransforms")) and not objs:
            print(
                "WARNING: B9 TEXTURE transform filter matched nothing: %s — "
                "falling back to all meshes"
                % ((td.get("transforms") or [])[:4],)
            )
            try:
                stack = [root] + list(getattr(root, "children_recursive", []) or [])
            except Exception:
                stack = [root]
            objs = [o for o in stack if getattr(o, "type", "") == "MESH"]
            if not objs:
                continue
        mats = list(_materials_on_objects(objs))
        # Always include secondary MODEL mesh materials (paint copies .sec_*)
        try:
            stack = [root] + list(getattr(root, "children_recursive", []) or [])
            sec_meshes = [
                o for o in stack
                if o.get("mu_secondary_model") and getattr(o, "type", "") == "MESH"
            ]
            if sec_meshes:
                mats = list(set(mats) | set(_materials_on_objects(sec_meshes)))
                print(
                    "INFO: B9 paint mats=%d (incl secondary meshes=%d)"
                    % (len(mats), len(sec_meshes))
                )
        except Exception as e:
            print("WARNING: secondary paint mats: %s" % e)
        cur_want = (td.get("currentTexture") or "").strip().lower()
        for mat in mats:
            if cur_want:
                # Only replace if the material currently uses this texture name
                node = _maintex_image_node(mat) if slot == "_MainTex" else None
                if node is None:
                    try:
                        from . import materials as _mats  # optional
                    except Exception:
                        pass
                    # fallback: any image texture node for this slot
                    try:
                        nt = mat.node_tree
                        if nt:
                            for n in nt.nodes:
                                if n.type == "TEX_IMAGE" and n.image:
                                    if slot.lower() in (n.name or "").lower() or slot == "_MainTex":
                                        node = n
                                        break
                    except Exception:
                        pass
                stem = _image_name_stem(node.image if node else None)
                if stem and stem != cur_want and cur_want not in stem:
                    continue
            if slot == "_MainTex" and not _mat_had_stock_slot(data, mat, slot):
                # still allow B9 swaps on mats that had a map; if stock empty skip
                # unless currentTexture matched something
                if not cur_want:
                    try:
                        if not any(
                            n.type == "TEX_IMAGE" and n.image
                            for n in (mat.node_tree.nodes if mat.node_tree else [])
                        ):
                            continue
                    except Exception:
                        continue
            _set_material_slot_image_viewport(mat, slot, img, data=data)
            # Metal/paint maps often carry alpha; force opaque so interior
            # panels do not show through (Green lattice stays correct).
            try:
                if hasattr(mat, "blend_method"):
                    mat.blend_method = "OPAQUE"
                if hasattr(mat, "shadow_method"):
                    mat.shadow_method = "OPAQUE"
            except Exception:
                pass


def parse_broken_transform_names(cfg_text):
    """Collect mesh/transform names that represent the *damaged* visual.

    Stock / mods:
      - object names containing .broken / _broken / broken / busted
      - ModuleWheelDamage: damagedTransformName / bustedWheelName
      - ModuleDeployable*: damagedObjectName (when present)
    """
    names = set()
    if not cfg_text:
        return []
    for key in (
        "damagedTransformName",
        "damagedObjectName",
        "bustedWheelName",
        "brokenObjectName",
        "brokenTransformName",
    ):
        for m in re.finditer(
            rf"^\s*{key}\s*=\s*(.+)$", cfg_text, re.M | re.I
        ):
            v = m.group(1).strip().strip('"').split("//")[0].strip()
            if v:
                names.add(v)
    return sorted(names)


def is_broken_object_name(name, cfg_broken_names=None):
    """True if this Blender object is a damaged/broken visual mesh."""
    n = (name or "").lower()
    if not n:
        return False
    wedge = "\u2227"
    key = n.split(wedge, 1)[0].strip()
    if cfg_broken_names:
        for bn in cfg_broken_names:
            bl = str(bn).lower()
            if key == bl or key.startswith(bl + ".") or bl in key:
                return True
    if ".broken" in n or n.endswith("broken") or "_broken" in n:
        return True
    if "busted" in n or n.startswith("damaged") or ".damaged" in n:
        return True
    return False


def _hide_object_branch(obj, hide=True):
    """Hide *obj* and every descendant (meshes, colliders, empties)."""
    n = 0
    if obj is None:
        return 0
    try:
        branch = [obj] + list(getattr(obj, "children_recursive", []) or [])
    except Exception:
        branch = [obj]
    for o in branch:
        try:
            o.hide_viewport = bool(hide)
            o.hide_render = bool(hide)
            n += 1
        except Exception:
            pass
    return n


def apply_broken_default_hide(root, cfg_text=None, hide=True):
    """Hide broken meshes under root (viewport). Keep visible if *only* broken.

    Debris / scrap parts that are entirely damaged geometry stay shown.
    Hides the whole branch under each broken root (children colliders/meshes).
    """
    if root is None:
        return 0
    cfg_names = parse_broken_transform_names(cfg_text or "")
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    broken_roots = []
    non_broken_mesh = 0
    for obj in stack:
        try:
            if is_broken_object_name(obj.name, cfg_names):
                # Only top-most broken in this branch (skip if parent already broken)
                parent = getattr(obj, "parent", None)
                skip = False
                while parent is not None:
                    if is_broken_object_name(getattr(parent, "name", ""), cfg_names):
                        skip = True
                        break
                    parent = getattr(parent, "parent", None)
                if not skip:
                    broken_roots.append(obj)
            elif getattr(obj, "type", None) == "MESH":
                on = (obj.name or "").lower()
                if "collider" in on or on.startswith("col"):
                    continue
                if is_broken_object_name(obj.name, cfg_names):
                    continue
                non_broken_mesh += 1
        except Exception:
            pass
    if not broken_roots:
        return 0
    if non_broken_mesh == 0:
        return 0
    n = 0
    for obj in broken_roots:
        n += _hide_object_branch(obj, hide=hide)
    try:
        root[MU_BROKEN_KEY] = json.dumps(
            [o.name for o in broken_roots if o and o.name]
        )
    except Exception:
        pass
    return n


def _attach_suspension_preview(root, cfg_text):
    """Synthesize a short location Action for ModuleWheelSuspension travel.

    Moves ``suspensionTransformName`` along local +Z (Blender) by
    ``suspensionDistance`` so amortyzatory / gear legs scrub in the Timeline.
    Tagged ``mu_fx_preview`` / cfg_preview so export skips it.
    """
    if root is None or not cfg_text or "ModuleWheelSuspension" not in cfg_text:
        return 0
    try:
        from ..utils.action_compat import fcurve_new, push_action_to_nla
    except Exception:
        return 0
    import math

    # Index objects under root once
    named = {}
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    for o in stack:
        try:
            n = (o.name or "").split("\u2227", 1)[0].strip()
            if n and n not in named:
                named[n] = o
            # also bare name
            if o.name and o.name not in named:
                named[o.name] = o
        except Exception:
            pass

    count = 0
    for m in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        if not re.search(r"^\s*name\s*=\s*ModuleWheelSuspension\b", body, re.M | re.I):
            continue
        tr = re.search(r"^\s*suspensionTransformName\s*=\s*(.+)$", body, re.M | re.I)
        if not tr:
            continue
        tname = tr.group(1).strip().strip('"').split("//")[0].strip()
        dist_m = re.search(r"^\s*suspensionDistance\s*=\s*([-\d.]+)", body, re.M | re.I)
        try:
            dist = float(dist_m.group(1)) if dist_m else 0.2
        except Exception:
            dist = 0.2
        if abs(dist) < 1e-6:
            continue
        obj = named.get(tname)
        if obj is None:
            # fuzzy
            tl = tname.lower()
            for k, v in named.items():
                if k.lower() == tl or k.lower().startswith(tl + "."):
                    obj = v
                    break
        if obj is None:
            continue
        # Axis: Unity suspension is typically local Y → Blender local Z after import
        axis = (0.0, 0.0, 1.0)
        ax_m = re.search(
            r"^\s*suspensionAxis\s*=\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)",
            body, re.M | re.I,
        )
        if ax_m:
            try:
                # Unity Y-up → Blender Z-up: (x,y,z)_u → (x,z,y)_b
                ux, uy, uz = (float(ax_m.group(i)) for i in (1, 2, 3))
                axis = (ux, uz, uy)
            except Exception:
                pass
        # Optional suspensionOffset / targetPosition (coverage report fields)
        offset = 0.0
        om = re.search(r"^\s*suspensionOffset\s*=\s*([-\d.]+)", body, re.M | re.I)
        if om:
            try:
                offset = float(om.group(1))
            except Exception:
                offset = 0.0
        target_pos = 0.5
        tpm = re.search(r"^\s*targetPosition\s*=\s*([-\d.]+)", body, re.M | re.I)
        if tpm:
            try:
                target_pos = float(tpm.group(1))
            except Exception:
                target_pos = 0.5
        try:
            obj["mu_suspension_distance"] = float(dist)
            obj["mu_suspension_offset"] = float(offset)
            obj["mu_suspension_target"] = float(target_pos)
            sm = re.search(r"^\s*springRatio\s*=\s*([-\d.]+)", body, re.M | re.I)
            dm = re.search(r"^\s*damperRatio\s*=\s*([-\d.]+)", body, re.M | re.I)
            if sm:
                obj["mu_suspension_spring"] = float(sm.group(1))
            if dm:
                obj["mu_suspension_damper"] = float(dm.group(1))
        except Exception:
            pass
        try:
            rest = list(obj.location)
            # Rest = offset + targetPosition * distance (KSP ride height)
            ride = float(offset) + float(target_pos) * float(dist)
            for i in range(3):
                rest[i] = float(rest[i]) + float(axis[i]) * ride
        except Exception:
            continue
        # Visible travel on the timeline: ≥10 frames (user request), default 24.
        f0 = 1
        f1 = max(f0 + 10, f0 + 24)
        # Animate full suspensionDistance from the ride-height rest pose
        travel = float(dist)
        if abs(travel) < 0.05:
            travel = 0.15 if travel >= 0 else -0.15
        act_name = "Suspension_%s" % (obj.name.split("∧")[0][:40])
        # Replace prior preview action of same name
        try:
            old = bpy.data.actions.get(act_name)
            if old is not None:
                bpy.data.actions.remove(old)
        except Exception:
            pass
        act = bpy.data.actions.new(act_name)
        try:
            act["mu_fx_preview"] = 1
            act["mu_cfg_preview"] = 1
        except Exception:
            pass
        try:
            ad = obj.animation_data
            if ad and ad.nla_tracks:
                for t in list(ad.nla_tracks):
                    if (t.name or "").startswith("Suspension"):
                        ad.nla_tracks.remove(t)
        except Exception:
            pass
        # Intermediate keys so the strip is clearly multi-frame in the editor
        frames = [f0]
        steps = max(10, f1 - f0)
        for s in range(1, steps):
            frames.append(f0 + s)
        frames.append(f1)
        frames = sorted(set(int(x) for x in frames))
        for i in range(3):
            delta = float(axis[i]) * travel
            try:
                # Blender 4/5: fcurve_new(action, datablock, data_path, index)
                fc = fcurve_new(act, obj, "location", index=i)
            except TypeError:
                try:
                    fc = fcurve_new(act, "location", index=i)
                except Exception:
                    continue
            except Exception:
                continue
            try:
                while fc.keyframe_points:
                    fc.keyframe_points.remove(fc.keyframe_points[0])
            except Exception:
                pass
            try:
                fc.keyframe_points.add(len(frames))
            except Exception:
                continue
            for ki, fr in enumerate(frames):
                t = 0.0 if f1 == f0 else (float(fr) - f0) / float(f1 - f0)
                val = float(rest[i]) + delta * t
                try:
                    fc.keyframe_points[ki].co = (float(fr), val)
                    fc.keyframe_points[ki].interpolation = "LINEAR"
                except Exception:
                    pass
            try:
                fc.update()
            except Exception:
                pass
        try:
            scene = bpy.context.scene
            if scene and int(scene.frame_end) < f1:
                scene.frame_end = int(f1)
        except Exception:
            pass
        try:
            track, strip = push_action_to_nla(obj, act, "SuspensionTravel")
            if track is not None:
                try:
                    # Off by default — enable from MU Options checkbox
                    track.mute = True
                except Exception:
                    pass
                try:
                    track["mu_fx_preview"] = 1
                    track["mu_suspension_preview"] = 1
                except Exception:
                    pass
            if strip is not None:
                try:
                    strip.frame_start = float(f0)
                    strip.frame_end = float(f1)
                    strip.action_frame_start = float(f0)
                    strip.action_frame_end = float(f1)
                except Exception:
                    pass
            # Do NOT assign ad.action — that forces motion even when NLA is muted.
            # Enable path assigns action only when the user ticks the checkbox.
            try:
                if obj.animation_data and obj.animation_data.action == act:
                    obj.animation_data.action = None
            except Exception:
                pass
            count += 1
        except Exception:
            try:
                if not obj.animation_data:
                    obj.animation_data_create()
                obj.animation_data.action = act
                count += 1
            except Exception:
                pass
    # Piston / strut tubes: LookAt + position constraints from CFG
    try:
        _attach_fx_lookat_constraints(root, cfg_text)
    except Exception as e:
        print(f"WARNING: suspension lookat: {e}")
    try:
        _force_constraint_eval(root)
    except Exception:
        pass
    return count


def parse_part_variants(cfg_text):
    """Return {base, variants:[{name, objects, textures, …}], kind}.

    ``kind`` is ``model``, ``texture``, or ``both``.

    When the cfg lists VARIANT blocks but omits ``baseVariant``, KSP keeps the
    .mu stock materials as the default look (Serenity robotics: color stripes
    vs Gray/plain TEXTURE). We insert a synthetic ``Stock`` entry for that.
    """
    if not cfg_text or "ModulePartVariants" not in cfg_text:
        return None
    m = re.search(r"^\s*baseVariant\s*=\s*(.+)$", cfg_text, re.M | re.I)
    base = m.group(1).strip().strip('"') if m else None
    base_display = None
    bd = re.search(r"^\s*baseDisplayName\s*=\s*(.+)$", cfg_text, re.M | re.I)
    if bd:
        base_display = bd.group(1).strip().strip('"').split("//")[0].strip()
    bt = re.search(r"^\s*baseThemeName\s*=\s*(.+)$", cfg_text, re.M | re.I)
    base_theme = None
    if bt:
        base_theme = bt.group(1).strip().strip('"').split("//")[0].strip()
    variants = []
    # Split on VARIANT { ... } blocks (brace depth)
    for block in re.finditer(
        r"VARIANT\s*\{", cfg_text, re.I
    ):
        start = block.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm:
            continue
        vname = nm.group(1).strip().strip('"')
        objects = {}
        go = re.search(r"GAMEOBJECTS\s*\{([^}]*)\}", body, re.I | re.S)
        if go:
            for line in go.group(1).splitlines():
                line = line.strip()
                if "=" not in line or line.startswith("//"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().split("//")[0].strip().lower()
                if k:
                    objects[k] = v in ("true", "1", "yes")
        textures = {}
        texture_blocks = []
        # All TEXTURE { } blocks (stock often has one per materialName)
        pos = 0
        while True:
            tm = re.search(r"TEXTURE\s*\{", body[pos:], re.I)
            if not tm:
                break
            start = pos + tm.end() - 1
            depth = 0
            i = start
            while i < len(body):
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        tbody = body[start + 1:i]
                        break
                i += 1
            else:
                break
            pos = i + 1
            block = {}
            for line in tbody.splitlines():
                line = line.strip()
                if "=" not in line or line.startswith("//"):
                    continue
                k, _, v = line.partition("=")
                block[k.strip()] = v.strip().split("//")[0].strip()
            if block:
                texture_blocks.append(block)
                # Flat map: first block wins for simple single-material parts
                for k, v in block.items():
                    if k not in textures:
                        textures[k] = v
        # EXTRA_INFO: fairing maps + flags (reverseDeployDirection, …)
        extra_info = {}
        extra = re.search(r"EXTRA_INFO\s*\{([^}]*)\}", body, re.I | re.S)
        if extra:
            for line in extra.group(1).splitlines():
                line = line.strip()
                if "=" not in line or line.startswith("//"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().split("//")[0].strip().strip('"')
                extra_info[k] = v
                # Texture-like keys still feed texture map for fairing previews
                if any(
                    x in k.lower()
                    for x in ("texture", "map", "url", "mat", "color")
                ):
                    textures[k] = v
        disabled = []
        dm = re.search(
            r"^\s*disabledAnimations\s*=\s*(.+)$", body, re.M | re.I
        )
        if dm:
            raw = dm.group(1).strip().strip('"')
            disabled = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        dn = re.search(r"^\s*displayName\s*=\s*(.+)$", body, re.M | re.I)
        display = None
        if dn:
            display = dn.group(1).strip().strip('"').split("//")[0].strip()
        tn = re.search(r"^\s*themeName\s*=\s*(.+)$", body, re.M | re.I)
        theme = None
        if tn:
            theme = tn.group(1).strip().strip('"').split("//")[0].strip()
        entry = {
            "name": vname,
            "objects": objects,
            "toggle_keys": list(objects.keys()),
            "textures": textures,
            "texture_blocks": texture_blocks,
            "disabledAnimations": disabled,
            "extra_info": extra_info,
        }
        if display:
            entry["displayName"] = display
        if theme:
            entry["themeName"] = theme
        variants.append(entry)
    if not variants:
        return None
    # No baseVariant → stock .mu materials are the default (not VARIANT[0]).
    # Serenity robotics: only VARIANT is Gray/plain TEXTURE; stripes live in .mu.
    if base is None:
        stock_label = base_display or base_theme or STOCK_VARIANT_NAME
        # Keep identifier enum-safe (no spaces); label carries theme name.
        stock_name = STOCK_VARIANT_NAME
        if any(v.get("name") == stock_name for v in variants):
            stock_name = "_Stock"
        variants.insert(0, {
            "name": stock_name,
            "objects": {},
            "textures": {},
            "disabledAnimations": [],
            "stock": True,
            "displayName": stock_label,
        })
        base = stock_name
    elif not any(v.get("name") == base for v in variants):
        # Squad sometimes leaves baseVariant as an old alias (TwoBell vs
        # DoubleBell on liquidEngine2-2_v2). Prefer a real VARIANT — never
        # invent empty stock GAMEOBJECTS (that shows every bell at once).
        resolved = _resolve_base_variant_alias(base, variants)
        if resolved:
            base = resolved
        else:
            base = variants[0]["name"]
    has_obj = any(v["objects"] for v in variants)
    has_tex = any(v["textures"] for v in variants)
    if has_obj and has_tex:
        kind = "both"
    elif has_tex:
        kind = "texture"
    else:
        kind = "model"
    out = {
        "base": base,
        "active": base,
        "kind": kind,
        "variants": variants,
        "source": "ModulePartVariants",
    }
    if base_display:
        out["baseDisplayName"] = base_display
    if base_theme:
        out["baseThemeName"] = base_theme
    # Inline // #autoLOC_x = English comments from this cfg
    try:
        from .ksp_loc import harvest_inline_loc_comments
        inline = harvest_inline_loc_comments(cfg_text)
        if inline:
            out["_loc_inline"] = inline
    except Exception:
        pass
    # Resolve displayName for storage (UI also resolves live from GameData)
    try:
        from .ksp_loc import resolve_loc
        for v in variants:
            dn = v.get("displayName") or ""
            theme = v.get("themeName") or ""
            if dn.startswith("#") or not dn:
                resolved = resolve_loc(
                    dn, theme_name=theme or v.get("name"), inline_table=out.get("_loc_inline")
                )
                if resolved and not resolved.startswith("#"):
                    v["displayName"] = resolved
    except Exception:
        pass
    return out


def _resolve_base_variant_alias(base, variants):
    """Map stale baseVariant names onto a real VARIANT block."""
    if not base:
        return None
    names = [v.get("name") for v in variants if v.get("name")]
    bl = base.lower()
    for n in names:
        if n.lower() == bl:
            return n
    # Common Squad renames
    aliases = {
        "twobell": "doublebell",
        "doublebell": "twobell",
        "onebell": "singlebell",
        "singlebell": "onebell",
    }
    want = aliases.get(bl)
    if want:
        for n in names:
            if n.lower() == want:
                return n
    # Conservative containment (TwoBell ⊂ … only when unique)
    hits = []
    for n in names:
        nl = n.lower()
        if len(bl) >= 5 and (bl in nl or nl in bl):
            hits.append(n)
    if len(hits) == 1:
        return hits[0]
    return None


def _iter_meshes_under(root):
    """Depth-first mesh objects under root (including root)."""
    if root is None:
        return
    stack = [root]
    while stack:
        o = stack.pop()
        if o.type == "MESH":
            yield o
        stack.extend(list(o.children))


def _is_collider_mesh(obj):
    if obj is None:
        return False
    if obj.get("mu_collider"):
        return True
    key = _variant_object_key(obj.name or "").lower()
    return key == "collider"


def has_visible_preview_mesh(root, skip_colliders=True):
    """True when at least one non-hidden render mesh remains under root."""
    for o in _iter_meshes_under(root):
        if o.hide_render or o.hide_viewport:
            continue
        if (o.name or "").startswith("mesh:"):
            continue
        if skip_colliders and _is_collider_mesh(o):
            continue
        data = getattr(o, "data", None)
        if data and getattr(data, "vertices", None) and len(data.vertices) > 0:
            return True
    return False


def pick_viable_base_variant(root, info):
    """Pick baseVariant or first variant that leaves visible geometry in this .mu."""
    if root is None or not info:
        return None
    variants = info.get("variants") or []
    order = []
    base = info.get("base")
    # Prefer B9 subtypes that actually enable a transform (Gray/GATV) over
    # MM-only paint names (White) that share the same moduleID.
    transform_first = []
    other = []
    for v in variants:
        n = v.get("name")
        if not n:
            continue
        objs = v.get("objects") or {}
        if objs and any(bool(x) for x in objs.values()):
            transform_first.append(n)
        else:
            other.append(n)
    if base:
        order.append(base)
    for n in transform_first + other:
        if n not in order:
            order.append(n)
    for name in order:
        if apply_variant(root, name, skip_textures=True) and has_visible_preview_mesh(
            root
        ):
            return name
    return base or (variants[0].get("name") if variants else None)


def variant_has_visible_geometry(root, variant_name):
    """True when applying variant_name would show at least one preview mesh."""
    if root is None or not variant_name:
        return False
    if apply_variant(root, variant_name, skip_textures=True):
        return has_visible_preview_mesh(root)
    return False


def find_cfg_for_part_name(game_data, part_name, mu_path=None):
    """Locate best PART/INTERNAL .cfg for a test ``part_name`` (+ optional .mu path)."""
    if not part_name or not game_data:
        return None
    gd = Path(game_data)
    if not gd.is_dir():
        return None
    mu_rel = None
    mu_stem = None
    if mu_path:
        try:
            mu_abs = Path(mu_path).resolve()
            mu_stem = mu_abs.stem.lower()
            mu_rel = str(mu_abs.relative_to(gd.resolve())).replace("\\", "/").lower()
        except Exception:
            mu_stem = Path(mu_path).stem.lower()
            mu_rel = None
    pn = str(part_name)
    pn_low = pn.lower()
    name_re = re.compile(
        rf"^\s*name\s*=\s*{re.escape(pn)}\s*(?://|$)",
        re.M | re.I,
    )
    best_path = None
    best_score = -1
    for cfg_path in gd.rglob("*.cfg"):
        try:
            text = cfg_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        low = text.lower().replace("\\", "/")
        score = 0
        if name_re.search(text):
            score += 40
            if re.search(r"^\s*INTERNAL\s*\{", text, re.M | re.I):
                score += 8
            elif "PART" in text[:400]:
                score += 5
        if mu_rel and mu_rel.replace(".mu", "") in low:
            score += 35
        elif mu_stem and mu_stem in low:
            score += 22
        if pn_low in low:
            score += 6
        if "modulepartvariants" in low:
            score += 12
        if score < 18:
            continue
        if score > best_score:
            best_score = score
            best_path = cfg_path
    return str(best_path) if best_path else None


def apply_part_cfg_preview(root, cfg_path, mudir=None, apply_base=True):
    """Apply ModulePartVariants / jettison from a specific PART .cfg (test harness)."""
    if root is None or not cfg_path or not os.path.isfile(cfg_path):
        return False
    try:
        text = open(cfg_path, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return False
    if mudir:
        try:
            root["mu_dirname"] = mudir
        except Exception:
            pass
    attach_path = (root.get("mu_cfg_path") or "").strip()
    try:
        root["mu_cfg_path"] = cfg_path
    except Exception:
        pass
    info = parse_part_variants(text)
    if info is None:
        # B9PartSwitch mesh/resource switches → same Options dropdown
        try:
            b9mods = parse_b9_part_switch(text)
            info = b9_to_variant_info(b9mods)
        except Exception as e:
            _vlog("WARNING: B9PartSwitch parse:", e)
            info = None
    elif "ModuleB9PartSwitch" in text:
        # Merge B9 subtypes as extra variants (prefixed when needed)
        try:
            b9mods = parse_b9_part_switch(text)
            b9info = b9_to_variant_info(b9mods)
            if b9info and b9info.get("variants"):
                existing = {v.get("name") for v in info.get("variants") or []}
                for v in b9info["variants"]:
                    if v.get("name") not in existing:
                        info.setdefault("variants", []).append(v)
        except Exception as e:
            _vlog("WARNING: B9PartSwitch merge:", e)
    try:
        import re as _re
        import os as _os
        _m = _re.search(r"^\s*name\s*=\s*(\S+)", text, _re.M | _re.I)
        pname = _m.group(1).strip().strip('"') if _m else None
        mudir_local = mudir
        if not mudir_local and cfg_path:
            mudir_local = _os.path.dirname(cfg_path)
        if info is None:
            info = {"base": None, "variants": [], "kind": "texture", "source": "MM_paint"}
        info = merge_mm_paint_into_variants(info, mudir_local, pname or "")
        if info and not info.get("variants") and info.get("source") == "MM_paint":
            info = None
    except Exception as e:
        _vlog("WARNING: MM paint merge:", e)
    if info:
        # Keep stock texture snapshot from import_mu.attach_cfg (must not
        # re-cache after a variant TEXTURE swap — that poisons restore/export).
        try:
            prev_data = json.loads(root.get(MU_VARIANTS_KEY) or "{}")
        except Exception:
            prev_data = {}
        # attach_cfg may have picked a sibling PART in shared Assets/ folders.
        if (
            attach_path
            and os.path.normcase(attach_path) != os.path.normcase(cfg_path)
        ):
            for key in ("_default_maintex", "_default_texprops", "_default_texmapping"):
                prev_data.pop(key, None)
        for key in ("_default_maintex", "_default_texprops", "_default_texmapping"):
            if prev_data.get(key):
                info[key] = prev_data[key]
        root[MU_VARIANTS_KEY] = json.dumps(info)
        try:
            data = json.loads(root[MU_VARIANTS_KEY])
            if not data.get("_default_maintex") or not data.get("_default_texmapping"):
                _ensure_default_textures_cached(root, data)
            root[MU_VARIANTS_KEY] = json.dumps(data)
        except Exception:
            pass
        if apply_base:
            base = pick_viable_base_variant(root, info) or info.get("base")
            if not base and info.get("variants"):
                base = info["variants"][0].get("name")
            if base:
                apply_variant(root, base)
    else:
        # Harness cfg has no ModulePartVariants — drop stale attach_cfg variants
        # (shared .mu e.g. rocketNoseConeSize4 vs protectiveRocketNoseMk7_v2).
        try:
            prev_data = json.loads(root.get(MU_VARIANTS_KEY) or "{}")
        except Exception:
            prev_data = {}
        keep = {}
        for key in ("_default_maintex", "_default_texprops", "_default_texmapping"):
            if prev_data.get(key):
                keep[key] = prev_data[key]
        if keep:
            root[MU_VARIANTS_KEY] = json.dumps(keep)
        elif MU_VARIANTS_KEY in root:
            del root[MU_VARIANTS_KEY]
    jettison = parse_module_jettison_names(text)
    if jettison:
        try:
            root[MU_JETTISON_KEY] = json.dumps([str(n).lower() for n in jettison])
        except Exception:
            pass
        try:
            if MU_VARIANTS_KEY in root:
                data = json.loads(root[MU_VARIANTS_KEY])
                data["jettisonNames"] = [str(n).lower() for n in jettison]
                root[MU_VARIANTS_KEY] = json.dumps(data)
        except Exception:
            pass
    return True


def _find_variant_entry(variants, name):
    for v in variants or []:
        if v.get("name") == name:
            return v
    # bare subtype vs module/subtype
    bare = name.split("/")[-1] if name else ""
    for v in variants or []:
        vn = v.get("name") or ""
        if vn == bare or vn.endswith("/" + bare):
            return v
    return None




def _b9_scope_match(key_plain, scope_l):
    """Map object plain-name → scope key (strict, case-insensitive).

    Exact match only after stripping ∧ / .001 / (Clone).  Never let ``Vega``
    match ``Vega_Tank1`` — that hid the whole part root and stacked Type+Dome.
    """
    if not key_plain:
        return None
    kl = key_plain.lower().strip()
    if kl.endswith("(clone)"):
        kl = kl[: -len("(clone)")].rstrip()
    if kl in scope_l:
        return kl
    return None


def _apply_b9_module_exclusive(root, chosen, all_variants, active_modules=None):
    """Force exclusive visibility for one B9 module's transform set.

    Cross-module nesting (TallDome under Extended): hide Type by mesh only so
    a Dome child can still be shown without un-hiding the long body mesh.
    """
    if root is None or not chosen or not chosen.get("b9"):
        return 0
    mid = chosen.get("b9_moduleID")
    enabled = set()
    for k, v in (chosen.get("objects") or {}).items():
        if v:
            enabled.add(str(k).strip())
    scope = set()
    for v in all_variants or []:
        if mid and (v.get("b9_moduleID") or "") != mid:
            continue
        if not mid and v is not chosen:
            continue
        for k in (v.get("objects") or {}).keys():
            scope.add(str(k).strip())
        for k in (v.get("toggle_keys") or []):
            scope.add(str(k).strip())
    for k in (chosen.get("objects") or {}).keys():
        scope.add(str(k).strip())
    if not scope:
        return 0

    # Other mesh modules' transform names (never mass-unhide those bodies)
    other_scope = set()
    for v in all_variants or []:
        om = v.get("b9_moduleID") or ""
        if mid and om and om != mid and _variant_is_mesh_switch(v, all_variants):
            for k in (v.get("objects") or {}).keys():
                other_scope.add(str(k).strip().lower())
            for k in (v.get("toggle_keys") or []):
                other_scope.add(str(k).strip().lower())

    def plain(name):
        k = _variant_object_key(name or "")
        if k.lower().endswith("(clone)"):
            k = k[: -len("(clone)")].rstrip() if k.endswith("(clone)") else k[:-7].rstrip()
        return (k or "").strip()

    scope_l = {s.lower(): s for s in scope if s}
    enabled_l = {s.lower() for s in enabled if s}
    other_l = set(other_scope)

    def _is_renderable(o):
        try:
            return o.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}
        except Exception:
            return False

    def _mark_branch(obj, hidden):
        st = [obj]
        while st:
            cur = st.pop()
            try:
                if hidden:
                    cur["mu_b9_exclusive_hide"] = 1
                elif "mu_b9_exclusive_hide" in cur:
                    del cur["mu_b9_exclusive_hide"]
            except Exception:
                pass
            try:
                st.extend(list(cur.children))
            except Exception:
                pass

    def _hide_type_branch(obj, hide):
        """Hide/show a Type/Dome transform without trapping foreign-module children.

        hide=True: hide renderable meshes under obj; keep EMPTY parents visible
        so a nested TallDome (other module) can still be shown.  Also hide the
        empty if it has NO other-module descendants.
        hide=False: unhide branch, but re-hide meshes marked exclusive from
        other modules.
        """
        # Collect descendants that belong to other mesh modules
        foreign = []
        try:
            stack = list(obj.children)
        except Exception:
            stack = []
        while stack:
            ch = stack.pop()
            try:
                ck = plain(ch.name or "").lower()
            except Exception:
                ck = ""
            if ck and ck in other_l:
                foreign.append(ch)
                continue  # don't walk into foreign module root
            try:
                stack.extend(list(ch.children))
            except Exception:
                pass

        if hide:
            # Hide renderables under this transform (not foreign subtrees)
            st = [obj]
            seen = set()
            while st:
                cur = st.pop()
                try:
                    pid = cur.as_pointer()
                except Exception:
                    pid = id(cur)
                if pid in seen:
                    continue
                seen.add(pid)
                try:
                    ck = plain(cur.name or "").lower()
                except Exception:
                    ck = ""
                if cur is not obj and ck and ck in other_l:
                    continue
                if _is_renderable(cur):
                    try:
                        _set_object_hide(cur, True)
                        cur["mu_b9_exclusive_hide"] = 1
                    except Exception:
                        pass
                elif cur is obj and not foreign:
                    # No nested other-module transforms: hide whole empty
                    try:
                        _set_object_hide(cur, True)
                        cur["mu_b9_exclusive_hide"] = 1
                    except Exception:
                        pass
                try:
                    for ch in cur.children:
                        try:
                            ckk = plain(ch.name or "").lower()
                        except Exception:
                            ckk = ""
                        if ckk and ckk in other_l:
                            continue
                        st.append(ch)
                except Exception:
                    pass
            _mark_branch(obj, True)
            # Clear mark on foreign children — they are other module's problem
            for f in foreign:
                try:
                    if "mu_b9_exclusive_hide" in f:
                        del f["mu_b9_exclusive_hide"]
                except Exception:
                    pass
        else:
            # Show this transform
            try:
                _set_object_hide(obj, False)
            except Exception:
                pass
            st = [obj]
            while st:
                cur = st.pop()
                try:
                    ck = plain(cur.name or "").lower()
                except Exception:
                    ck = ""
                if cur is not obj and ck and ck in other_l:
                    continue
                try:
                    if cur.get("mu_b9_exclusive_hide") and _is_renderable(cur):
                        # stay hidden only if still disabled by *this* scope
                        pass
                    _set_object_hide(cur, False)
                    if "mu_b9_exclusive_hide" in cur:
                        del cur["mu_b9_exclusive_hide"]
                except Exception:
                    try:
                        _set_object_hide(cur, False)
                    except Exception:
                        pass
                try:
                    for ch in cur.children:
                        try:
                            ckk = plain(ch.name or "").lower()
                        except Exception:
                            ckk = ""
                        if ckk and ckk in other_l:
                            continue
                        st.append(ch)
                except Exception:
                    pass
            _mark_branch(obj, False)

    n = 0
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    # Other mesh modules' currently enabled transforms (GammaTank while Dome on)
    peer_enabled = set()
    am = dict(active_modules or {})
    mid = chosen.get("b9_moduleID") if chosen else None
    if am:
        for v in all_variants or []:
            om = v.get("b9_moduleID") or ""
            if not om or om == mid:
                continue
            bare = am.get(om)
            if not bare:
                continue
            vname = v.get("name") or ""
            if (
                vname == bare
                or vname.endswith("/" + bare)
                or vname.split("/")[-1] == bare
            ):
                for k, val in (v.get("objects") or {}).items():
                    if val:
                        peer_enabled.add(str(k).strip().lower())

    def _parent_peer_key(obj):
        p = getattr(obj, "parent", None)
        guard = 0
        while p is not None and guard < 32:
            guard += 1
            try:
                pk = plain(p.name or "").lower()
            except Exception:
                pk = ""
            if pk and pk in other_l:
                return pk
            p = getattr(p, "parent", None)
        return None

    for o in stack:
        try:
            key = plain(o.name or "")
        except Exception:
            continue
        hit = _b9_scope_match(key, scope_l)
        if hit is None:
            continue
        show = hit in enabled_l
        # TallDome under Extended while Type=Gamma → force hide this TallDome
        ppeer = _parent_peer_key(o)
        if ppeer is not None and peer_enabled and ppeer not in peer_enabled:
            show = False
        try:
            _hide_type_branch(o, not show)
            n += 1
        except Exception:
            try:
                _set_object_hide(o, not show)
                _mark_branch(o, not show)
                n += 1
            except Exception:
                pass

    # Empty subtype: hide all in scope
    if not enabled_l and scope_l:
        for o in stack:
            try:
                key = plain(o.name or "")
            except Exception:
                continue
            if _b9_scope_match(key, scope_l) is None:
                continue
            try:
                _hide_type_branch(o, True)
                n += 1
            except Exception:
                pass

    # When showing objects nested under a hidden Type parent empty, ensure
    # parent empties are visible but Type body meshes stay hidden.
    if enabled_l:
        for o in stack:
            try:
                key = plain(o.name or "")
            except Exception:
                continue
            hit = _b9_scope_match(key, scope_l)
            if hit is None or hit not in enabled_l:
                continue
            # Walk parents: unhide empties, keep exclusive-hidden meshes hidden
            p = getattr(o, "parent", None)
            guard = 0
            while p is not None and guard < 24:
                guard += 1
                try:
                    if _is_renderable(p):
                        if p.get("mu_b9_exclusive_hide"):
                            _set_object_hide(p, True)
                        p = getattr(p, "parent", None)
                        continue
                    # empty parent — must be visible for nested child
                    _set_object_hide(p, False)
                    # re-hide renderable siblings under this parent that are
                    # exclusive-hidden (Type body next to TallDome)
                    for sib in list(getattr(p, "children", []) or []):
                        if sib is o:
                            continue
                        try:
                            if sib.get("mu_b9_exclusive_hide") or _is_renderable(sib):
                                sk = plain(sib.name or "").lower()
                                # if sibling is a Type transform body or mesh under disabled type
                                if sib.get("mu_b9_exclusive_hide"):
                                    _set_object_hide(sib, True)
                        except Exception:
                            pass
                except Exception:
                    pass
                p = getattr(p, "parent", None)

    print(
        "INFO: B9 exclusive module=%r enabled=%s scope=%s touched=%d"
        % (mid or "?", sorted(enabled)[:8], sorted(scope)[:8], n)
    )
    return n



def _apply_one_variant_objects(root, named, chosen, all_variants):
    """Show/hide meshes for a single variant entry. Returns matched key count."""
    if not chosen:
        return 0
    obj_map = dict(chosen.get("objects") or {})
    is_stock = bool(chosen.get("stock"))
    if "toggle_keys" in chosen:
        scope_keys = list(chosen.get("toggle_keys") or [])
    elif chosen.get("b9"):
        scope_keys = list(obj_map.keys())
    else:
        scope_keys = []
        for v in all_variants or []:
            if v.get("b9"):
                continue
            scope_keys.extend((v.get("objects") or {}).keys())
        scope_keys = list(dict.fromkeys(scope_keys))

    def _present(key):
        return bool(_lookup_named(named, key))

    present_keys = set()
    matched_show = 0
    matched_hide = 0
    for k in list(scope_keys) + list(obj_map.keys()):
        if _present(k):
            present_keys.add(k)

    if not present_keys:
        return 0

    if is_stock and not obj_map:
        for key in present_keys:
            for o in _lookup_named(named, key):
                _set_branch_hide(o, False, keyed_names=present_keys)
                matched_show += 1
        return matched_show

    obj_map_l = {str(k).lower(): bool(v) for k, v in obj_map.items()}
    # First pass: count how many "show" targets actually exist
    show_keys = []
    hide_keys = []
    for key in present_keys:
        if key in obj_map:
            vis = bool(obj_map[key])
        elif str(key).lower() in obj_map_l:
            vis = obj_map_l[str(key).lower()]
        else:
            if chosen.get("b9") and not obj_map:
                continue
            vis = False
        if vis:
            show_keys.append(key)
        else:
            hide_keys.append(key)

    # Safety: missing SHOW targets (secondary MODEL not loaded) — still HIDE
    # the transforms that exist.  Old code returned 0 and left Skin+GATV both
    # visible (Agena Avionics). Only skip hides when *nothing* in scope exists.
    show_matched = sum(1 for k in show_keys if _present(k))
    if obj_map and show_keys and show_matched == 0 and hide_keys:
        print(
            "WARNING: variant %r show transforms %s missing — still hiding %s"
            % (chosen.get("name"), show_keys[:6], hide_keys[:6])
        )
        # fall through: hide_keys still applied below

    def _unhide_ancestors(obj):
        # Parent empties (MODEL holders) must be visible or children stay invisible
        p = getattr(obj, "parent", None)
        guard = 0
        while p is not None and guard < 32:
            guard += 1
            try:
                _set_object_hide(p, False)
            except Exception:
                pass
            p = getattr(p, "parent", None)

    for key in show_keys:
        for o in _lookup_named(named, key):
            _unhide_ancestors(o)
            _set_branch_hide(o, False, keyed_names=present_keys)
            matched_show += 1
    for key in hide_keys:
        for o in _lookup_named(named, key):
            _set_branch_hide(o, True, keyed_names=present_keys)
            matched_hide += 1

    # Multi-MODEL / B9: exclusive model-group visibility (no side-by-side)
    if chosen.get("b9") and (obj_map or chosen.get("toggle_keys") is not None):
        enabled = [k for k, v in obj_map.items() if v]
        if not enabled and obj_map:
            enabled = []
        leaves = _enabled_transforms_to_model_leaves(root, enabled, list(obj_map.keys()))
        # Fallback: subtype name / module often encodes which MODEL leaf
        if not leaves and enabled:
            for t in enabled:
                for a in _b9_name_aliases(t):
                    al = a.lower().replace("(clone)", "")
                    try:
                        stack = [root] + list(
                            getattr(root, "children_recursive", []) or []
                        )
                    except Exception:
                        stack = [root]
                    for o in stack:
                        if not o.get("mu_secondary_model"):
                            continue
                        ml = (o.get("mu_cfg_model_leaf") or "").lower()
                        # SSPS lives under DeltaK secondary — any hit on secondary
                        # object named like transform → that leaf
                        on = _variant_object_key(o.name or "").lower()
                        if on == al or al in on or on in al:
                            if ml:
                                leaves.add(ml)
            if not leaves:
                # Last resort: if any enabled transform resolved under secondary tree
                named = _index_named_objects(root)
                for t in enabled:
                    for o in _lookup_named(named, t):
                        if o.get("mu_secondary_model"):
                            ml = (o.get("mu_cfg_model_leaf") or "").lower()
                            if ml:
                                leaves.add(ml)
                        else:
                            leaves.add("__primary__")
        # Exclusive primary/secondary visibility is applied once in
        # apply_variant (mesh switch) — do not call _set_model_group_visible
        # here or every paint/mesh click double-toggles the tree.
    return matched_show + matched_hide



def _object_looks_like_collider(obj):
    """Best-effort collider detect (no hard dependency on tools.display)."""
    if obj is None:
        return False
    try:
        if (obj.name or "").startswith("mesh:"):
            return True
        if "collider" in (obj.name or "").lower():
            return True
        muprops = getattr(obj, "muproperties", None)
        if muprops and getattr(muprops, "collider", None) not in (None, "", "MU_COL_NONE"):
            return True
        for col in getattr(obj, "users_collection", []) or []:
            cn = col.name or ""
            if cn.endswith(".collider") or ".collider." in cn:
                return True
    except Exception:
        pass
    return False


def _colliders_should_stay_hidden(root):
    """Respect AutohideColliders and current primary collider visibility."""
    try:
        from ..preferences import Preferences
        if bool(getattr(Preferences(), "AutohideColliders", False)):
            return True
    except Exception:
        pass
    try:
        cols = [
            o for o in _iter_model_group_objects(root, "__primary__")
            if _object_looks_like_collider(o)
        ]
        if cols:
            hidden = sum(1 for o in cols if getattr(o, "hide_viewport", False))
            return hidden >= (len(cols) + 1) // 2
    except Exception:
        pass
    try:
        sc = bpy.context.scene
        if sc is not None and "mu_colliders_hidden" in sc:
            return bool(sc["mu_colliders_hidden"])
    except Exception:
        pass
    return False


def _materials_for_model_leaf(root, leaf):
    """Materials used by MESH objects of one model group only."""
    objs = [
        o for o in _iter_model_group_objects(root, leaf)
        if getattr(o, "type", "") == "MESH"
    ]
    return list(_materials_on_objects(objs))



def _mesh_state_key(data, variants=None):
    """Stable key for paint memory: secondary leaf + active mesh module subtypes.

    Independent mesh modules (Upper/Lower endcaps) share leaf=__primary__ but
    must not share one paint slot — otherwise Blue sticks across first mesh
    change. Secondary MODEL leaves stay isolated via leaf:: prefix.
    """
    variants = variants if variants is not None else ((data or {}).get("variants") or [])
    leaf = (data or {}).get("active_mesh_leaf") or "__primary__"
    am = dict((data or {}).get("active_modules") or {})
    parts = []
    for mid in sorted(am.keys()):
        bare = am.get(mid) or ""
        if not bare or mid == "_mpv":
            continue
        name = "%s/%s" % (mid, bare)
        entry = _find_variant_entry(variants, name)
        if entry is None:
            entry = _find_variant_entry(variants, bare)
        if entry is not None and _variant_is_mesh_switch(entry, variants):
            parts.append(name)
    if not parts:
        # Stock exclusive / single MPV mesh
        active = (data or {}).get("active") or ""
        if active:
            entry = _find_variant_entry(variants, active)
            if entry is not None and _variant_is_mesh_switch(entry, variants):
                parts.append(active)
            elif am.get("_mpv"):
                parts.append(am["_mpv"])
    core = "|".join(parts) if parts else "__default_mesh__"
    if leaf and leaf != "__primary__":
        return "%s::%s" % (leaf, core)
    return core


def _resolve_paint_for_key(
    data, mesh_key, paint_by_model, default_paint, allow_legacy_leaf=False
):
    """Return (paint_name, entry) for this mesh key.

    Remembered name must still be a valid independent paint entry (meshes
    with fewer/other paints fall back to default).  Legacy leaf keys are
    only used when allow_legacy_leaf=True — never on first visit to a mesh
    state, or Blue from Default would stick on Low Profile.
    """
    variants = (data or {}).get("variants") or []
    tn = ""
    if mesh_key and paint_by_model:
        tn = paint_by_model.get(mesh_key) or ""
    if not tn and allow_legacy_leaf and paint_by_model:
        leaf = (data or {}).get("active_mesh_leaf") or "__primary__"
        tn = paint_by_model.get(leaf) or ""
    entry = _find_variant_entry(variants, tn) if tn else None
    if entry is not None and _variant_is_paint_switch(entry, variants):
        return tn, entry
    if default_paint:
        entry = _find_variant_entry(variants, default_paint)
        if entry is not None and _variant_is_paint_switch(entry, variants):
            return default_paint, entry
    for v in variants:
        if _variant_is_paint_switch(v, variants):
            return v.get("name"), v
    return None, None


def _default_paint_variant_name(data):
    """Default *independent* paint subtype (not exclusive B9 transform family)."""
    variants = (data or {}).get("variants") or []
    for v in variants:
        if _variant_is_paint_switch(v, variants):
            return v.get("name")
    return None


def _apply_paint_to_leaf(root, data, paint_entry, leaf):
    """Apply one paint variant only to materials of *leaf* model group."""
    if root is None or paint_entry is None:
        return
    mats = _materials_for_model_leaf(root, leaf)
    if not mats:
        print("INFO: paint leaf=%s no mesh materials" % leaf)
        return
    entries = paint_entry.get("b9_textures") or []
    # Stock ModulePartVariants: TEXTURE { mainTextureURL = ... } (no b9_textures)
    if not entries and (
        paint_entry.get("textures") or paint_entry.get("texture_blocks")
    ) and not paint_entry.get("stock"):
        try:
            _apply_variant_textures(root, data, paint_entry)
            ntex = len(paint_entry.get("texture_blocks") or []) or len(
                paint_entry.get("textures") or {}
            )
            print(
                "INFO: stock TEXTURE apply leaf=%s blocks/keys=%s name=%r"
                % (leaf, ntex, paint_entry.get("name"))
            )
        except Exception as e:
            _vlog("WARNING: stock TEXTURE apply: %s" % e)
        return
    if not entries:
        # Ensure secondary MODEL mats are in the stock cache before restore
        _ensure_default_textures_cached(root, data)
        defaults = data.get("_default_maintex") or {}
        texprops = data.get("_default_texprops") or {}
        n_restored = 0
        for mat in mats:
            slots = dict(texprops.get(mat.name) or {})
            if not slots and defaults.get(mat.name):
                slots["_MainTex"] = defaults[mat.name]
            if not slots:
                continue
            for slot, dname in slots.items():
                if not dname:
                    continue
                img = _find_image_datablock(dname)
                if img is None:
                    continue
                try:
                    if _set_material_slot_image_viewport(mat, slot, img, data=data):
                        n_restored += 1
                except Exception:
                    pass
        print(
            "INFO: paint restore leaf=%s mats=%d restored=%d"
            % (leaf, len(mats), n_restored)
        )
        return
    for td in entries:
        url = td.get("texture")
        if not url:
            continue
        path = _resolve_texture_url(root, url)
        if not path:
            continue
        img = _load_variant_image(
            path, os.path.splitext(os.path.basename(path))[0]
        )
        if img is None:
            continue
        try:
            if td.get("isNormalMap"):
                img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
        slot = td.get("shaderProperty") or (
            "_BumpMap" if td.get("isNormalMap") else "_MainTex"
        )
        tset = list(td.get("transforms") or [])
        # MM paint.cfg stores singular transform= not transforms=[]
        one = td.get("transform")
        if one and one not in tset:
            tset.append(one)
        # baseTransform also scopes B9 TEXTURE
        for bt in td.get("baseTransforms") or []:
            if bt and bt not in tset:
                tset.append(bt)
        bt1 = td.get("baseTransform")
        if bt1 and bt1 not in tset:
            tset.append(bt1)
        target_mats = list(mats)
        filter_hits = 0
        if tset:
            # Same naming as B9 exclusive / GAMEOBJECTS (wedge, .001, case)
            named = _index_named_objects(root)
            hit = []
            for t in tset:
                hit.extend(_lookup_named(named, t))
            # Fallback: walk leaf objects with _variant_object_key
            if not hit:
                for o in _iter_model_group_objects(root, leaf):
                    try:
                        key = _variant_object_key(o.name or "")
                    except Exception:
                        key = (o.name or "").split("∧")[0].split(".")[0]
                    kl = (key or "").lower()
                    for t in tset:
                        tl = (t or "").lower()
                        if not tl:
                            continue
                        if kl == tl or kl.endswith(tl) or tl.endswith(kl):
                            hit.append(o)
                            break
            if hit:
                filtered = list(_materials_on_objects(hit))
                filter_hits = len(filtered)
                target_mats = _paint_target_materials(mats, filtered, data, td)
                if filter_hits < len(mats):
                    print(
                        "INFO: paint transform filter partial (%d/%d) — "
                        "targets=%d (skin/group, not interior)"
                        % (filter_hits, len(mats), len(target_mats))
                    )
            else:
                # No transform objects found — do NOT paint every mat (that
                # paints interior with skin DDS and leaves missing maps).
                # Prefer currentTexture group; else materials that already had
                # a MainTex in the stock cache.
                target_mats = _paint_target_materials(mats, [], data, td)
                print(
                    "INFO: paint transform filter matched nothing on leaf=%s "
                    "— targets=%d/%d (majority/currentTexture, not all)"
                    % (leaf, len(target_mats), len(mats))
                )
        for mat in target_mats:
            try:
                _set_material_slot_image_viewport(mat, slot, img, data=data)
                if hasattr(mat, "blend_method"):
                    mat.blend_method = "OPAQUE"
                try:
                    mat.update_tag()
                except Exception:
                    pass
            except Exception:
                pass
        # Restore stock maps on leaf materials NOT in the paint target so
        # interior keeps its textures when only Skin is painted.
        try:
            target_set = set(id(m) for m in target_mats)
            defaults = (data or {}).get("_default_maintex") or {}
            texprops = (data or {}).get("_default_texprops") or {}
            for mat in mats:
                if id(mat) in target_set:
                    continue
                slots = dict(texprops.get(mat.name) or {})
                if not slots and defaults.get(mat.name):
                    slots["_MainTex"] = defaults[mat.name]
                for sname, dname in slots.items():
                    if not dname:
                        continue
                    dimg = _find_image_datablock(dname)
                    if dimg is None:
                        continue
                    try:
                        _set_material_slot_image_viewport(
                            mat, sname, dimg, data=data
                        )
                    except Exception:
                        pass
        except Exception as e:
            print("WARNING: paint interior restore: %s" % e)
        try:
            for o in _iter_model_group_objects(root, leaf):
                if getattr(o, "type", "") == "MESH":
                    o.update_tag()
        except Exception:
            pass
        print(
            "INFO: paint apply leaf=%s slot=%s mats=%d filter_hits=%d tex=%s"
            % (leaf, slot, len(target_mats), filter_hits, os.path.basename(path))
        )




def _build_named_map(root):
    """Map lowercased plain names → list of objects under root."""
    named = {}
    if root is None:
        return named
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    for o in stack:
        try:
            n = (o.name or "").split("\u2227")[0].split(".")[0].strip()
        except Exception:
            continue
        if not n:
            continue
        named.setdefault(n.lower(), []).append(o)
        named.setdefault(n, []).append(o)
    return named


def _apply_variant_transform_ops(root, chosen):
    """Apply B9 TRANSFORM rotationOffset / positionOffset (Unity → Blender)."""
    if not chosen:
        return 0
    ops = chosen.get("transform_ops") or []
    if not ops:
        return 0
    from mathutils import Euler, Vector
    import math
    named = _build_named_map(root)
    n = 0
    for xf in ops:
        name = xf.get("name") or ""
        objs = _lookup_named(named, name) if named else []
        if not objs:
            continue
        for o in objs:
            try:
                if "positionOffset" in xf:
                    ux, uy, uz = xf["positionOffset"][:3]
                    o.location = Vector((float(ux), float(uz), float(uy)))
                if "rotationOffset" in xf:
                    rx, ry, rz = xf["rotationOffset"][:3]
                    o.rotation_mode = "XYZ"
                    o.rotation_euler = Euler(
                        (
                            math.radians(float(rx)),
                            math.radians(float(rz)),
                            math.radians(float(ry)),
                        ),
                        "XYZ",
                    )
                if "scaleOffset" in xf:
                    sx, sy, sz = xf["scaleOffset"][:3]
                    o.scale = Vector((float(sx), float(sz), float(sy)))
                n += 1
            except Exception as e:
                _vlog("WARNING: transform_ops %s: %s" % (name, e))
    return n


def _apply_variant_disabled_animations(root, chosen, all_variants=None):
    """Mute NLA tracks listed in disabledAnimations for the active variant."""
    if root is None:
        return 0
    all_disabled = set()
    for v in all_variants or []:
        for a in v.get("disabledAnimations") or []:
            if a:
                all_disabled.add(str(a).strip().lower())
    active = set()
    for a in (chosen or {}).get("disabledAnimations") or []:
        if a:
            active.add(str(a).strip().lower())
    if not all_disabled and not active:
        return 0
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    n = 0
    for o in stack:
        ad = getattr(o, "animation_data", None)
        if not ad or not ad.nla_tracks:
            continue
        for track in ad.nla_tracks:
            tn = (track.name or "").strip().lower()
            if not tn:
                continue
            should_mute = any(a == tn or a in tn or tn in a for a in active)
            is_candidate = any(
                a == tn or a in tn or tn in a for a in all_disabled
            )
            if not is_candidate and not should_mute:
                continue
            try:
                track.mute = bool(should_mute)
                n += 1
            except Exception:
                pass
    return n


def _attach_control_surface_preview(root, cfg_text):
    """Tag ModuleControlSurface / ModuleAeroSurface for Tools menu."""
    if not cfg_text:
        return 0
    if "ModuleControlSurface" not in cfg_text and "ModuleAeroSurface" not in cfg_text:
        return 0
    made = 0
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm:
            continue
        mod = nm.group(1).strip().strip('"')
        if mod not in ("ModuleControlSurface", "ModuleAeroSurface"):
            continue
        def gv(k, b=body):
            m = re.search(r"^\s*%s\s*=\s*(.+)$" % k, b, re.M | re.I)
            return m.group(1).strip().strip('"').split("//")[0].strip() if m else ""
        info = {
            "module": mod,
            "transformName": gv("transformName") or gv("ctrlSurfaceTransform"),
            "ctrlSurfaceRange": gv("ctrlSurfaceRange") or gv("deployAngle"),
            "authorityLimiter": gv("authorityLimiter"),
        }
        try:
            root["mu_control_surface"] = json.dumps(info)
        except Exception:
            pass
        tname = info.get("transformName") or ""
        if tname:
            o = _find_child_named(root, tname)
            if o is not None:
                try:
                    o["mu_control_surface"] = 1
                    made += 1
                except Exception:
                    pass
    if made:
        _vlog("INFO: control surface preview tags: %d" % made)
    return made


def _attach_animate_generic_preview(root, cfg_text):
    """Tag ModuleAnimateGeneric clips (actionGUIName / animationName)."""
    if not cfg_text or "ModuleAnimateGeneric" not in cfg_text:
        return 0
    made = 0
    infos = []
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "ModuleAnimateGeneric":
            continue
        def gv(k, b=body):
            m = re.search(r"^\s*%s\s*=\s*(.+)$" % k, b, re.M | re.I)
            return m.group(1).strip().strip('"').split("//")[0].strip() if m else ""
        info = {
            "animationName": gv("animationName"),
            "actionGUIName": gv("actionGUIName"),
            "startEventGUIName": gv("startEventGUIName"),
            "endEventGUIName": gv("endEventGUIName"),
            "layer": gv("layer"),
        }
        infos.append(info)
        aname = info.get("animationName") or ""
        if not aname:
            continue
        try:
            stack = [root] + list(getattr(root, "children_recursive", []) or [])
        except Exception:
            stack = [root]
        for o in stack:
            ad = getattr(o, "animation_data", None)
            if not ad or not ad.nla_tracks:
                continue
            for track in ad.nla_tracks:
                tn = track.name or ""
                if tn == aname or aname in tn:
                    try:
                        track["mu_animate_generic"] = 1
                        track["mu_anim_gui"] = info.get("actionGUIName") or aname
                        made += 1
                    except Exception:
                        pass
    if infos:
        try:
            root["mu_animate_generic"] = json.dumps(infos)
        except Exception:
            pass
    if made:
        _vlog("INFO: ModuleAnimateGeneric tags: %d" % made)
    return made


def ensure_default_variant_for_preview(root, scene=None):
    """Apply base/default variant and force depsgraph eval (thumbnails / batch).

    Ensures GAMEOBJECTS visibility and TEXTURE swaps match the cfg default
    before a viewport or offscreen render. Safe no-op when no ``mu_variants``.
    """
    if root is None:
        return False
    try:
        data = json.loads(root[MU_VARIANTS_KEY]) if MU_VARIANTS_KEY in root else None
    except Exception:
        data = None
    if not data or not (data.get("variants") or []):
        return False
    base = data.get("base") or data.get("active")
    if not base and data.get("variants"):
        base = data["variants"][0].get("name")
    if not base:
        return False
    try:
        apply_variant(root, base)
    except Exception as e:
        _vlog("WARNING: ensure_default_variant apply: %s" % e)
        return False
    # Force evaluation so hide flags / materials are settled for render
    try:
        import bpy as _bpy
        sc = scene or getattr(_bpy.context, "scene", None)
        if sc is not None:
            sc.frame_set(int(getattr(sc, "frame_current", 1) or 1))
        vl = getattr(_bpy.context, "view_layer", None)
        if vl is not None:
            vl.update()
        dg = _bpy.context.evaluated_depsgraph_get()
        if dg is not None:
            dg.update()
    except Exception as e:
        _vlog("WARNING: ensure_default_variant eval: %s" % e)
    _vlog("INFO: ensure_default_variant_for_preview → %r" % base)
    return True


def apply_variant(root, variant_name, skip_textures=False):
    """Show/hide GAMEOBJECTS + swap TEXTURE maps for the named variant."""
    global _VARIANT_APPLY_DEPTH
    # Skip during undo/redo (RNA may fire; Object IDs may be freed)
    try:
        from ..tools import display as _disp
        if getattr(_disp, "_UNDO_REDO_DEPTH", 0) > 0:
            return 0
    except Exception:
        pass
    if root is None:
        return 0
    try:
        _ = root.name
    except ReferenceError:
        return 0
    except Exception:
        pass
    if _VARIANT_APPLY_DEPTH > 0:
        return 0
    _VARIANT_APPLY_DEPTH += 1
    try:
        return _apply_variant_body(root, variant_name, skip_textures)
    except ReferenceError:
        return 0
    finally:
        _VARIANT_APPLY_DEPTH = max(0, _VARIANT_APPLY_DEPTH - 1)


def _apply_variant_body(root, variant_name, skip_textures=False):
    """Internal implementation of apply_variant (re-entrancy isolated)."""
    if root is None or MU_VARIANTS_KEY not in root:
        return False
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return False
    variants = data.get("variants") or []
    chosen = _find_variant_entry(variants, variant_name)
    if chosen is None:
        _vlog("WARNING: unknown variant %r" % (variant_name,))
        return False

    _ensure_default_textures_cached(root, data)
    named = _index_named_objects(root)

    # --- multi-module active state ---
    active_modules = dict(data.get("active_modules") or {})
    if chosen.get("b9") and chosen.get("b9_moduleID"):
        mid = chosen["b9_moduleID"]
        bare = (chosen.get("name") or "").split("/")[-1]
        active_modules[mid] = bare
        data["active_modules"] = active_modules
    else:
        # ModulePartVariants is a single exclusive switch
        active_modules = {"_mpv": chosen.get("name")}
        data["active_modules"] = active_modules

    # Resolve which entries to apply
    to_apply = []
    if chosen.get("b9") and data.get("active_modules"):
        for mid, bare in data["active_modules"].items():
            if mid == "_mpv":
                continue
            # prefer moduleID/bare, else bare
            entry = _find_variant_entry(variants, "%s/%s" % (mid, bare))
            if entry is None:
                entry = _find_variant_entry(variants, bare)
            if entry is not None and entry.get("b9_moduleID") == mid:
                to_apply.append(entry)
            elif entry is not None and not entry.get("b9_moduleID"):
                to_apply.append(entry)
        if not to_apply:
            to_apply = [chosen]
    else:
        to_apply = [chosen]

    # Objects: only when the user picked a MESH variant (not on pure paint clicks)
    any_mesh = False
    mesh_leaves = set()
    mesh_switched = bool(chosen) and _variant_is_mesh_switch(
        chosen, data.get("variants") or []
    )
    paint_chosen = bool(chosen) and (
        _variant_is_paint_switch(chosen, data.get("variants") or [])
        or bool(chosen.get("b9_textures") or chosen.get("textures"))
    )

    # Also force object apply when the chosen entry clearly toggles transforms
    # (guards against mis-classified moduleIDs like textureSwitchSide).
    # True for "show X" and for empty subtypes that must HIDE optional
    # transforms (meshSwitchDome/Standard → hide TallDome).
    force_objs = bool(
        (chosen.get("objects") or {})
        or (chosen.get("toggle_keys") or [])
    )
    if mesh_switched or force_objs:
        for entry in to_apply:
            # Only apply object maps from mesh entries — never from pure paint
            if not (
                _variant_is_mesh_switch(entry)
                or (
                    (entry.get("objects") or {})
                    and any(bool(x) for x in (entry.get("objects") or {}).values())
                )
            ):
                continue
            n = _apply_one_variant_objects(root, named, entry, variants)
            if entry.get("b9"):
                n2 = _apply_b9_module_exclusive(root, entry, variants, active_modules=data.get("active_modules"))
                n = max(n, n2)
            if n:
                any_mesh = True
            obj_map = entry.get("objects") or {}
            enabled = [k for k, v in obj_map.items() if v]
            leaves = _enabled_transforms_to_model_leaves(
                root, enabled, list(obj_map.keys())
            )
            if not leaves:
                bare = (entry.get("name") or "").split("/")[-1].lower()
                primary_leaf = (root.get("mu_cfg_model_leaf") or "").lower()
                try:
                    stack = [root] + list(getattr(root, "children_recursive", []) or [])
                except Exception:
                    stack = [root]
                sec_leaves = {
                    (o.get("mu_cfg_model_leaf") or "").lower()
                    for o in stack
                    if o.get("mu_secondary_model") and o.get("mu_cfg_model_leaf")
                }
                for sl in sec_leaves:
                    token = bare.replace("-", "").replace("_", "")
                    slab = sl.replace("-", "").replace("_", "")
                    if token and token in slab:
                        leaves.add(sl)
                if not leaves and primary_leaf:
                    leaves.add("__primary__")
                if not leaves and enabled:
                    if sec_leaves and bare and primary_leaf and bare not in primary_leaf.replace("_", ""):
                        leaves.add(next(iter(sec_leaves)))
                    else:
                        leaves.add("__primary__")
            mesh_leaves |= leaves
        # Exclusive MODEL groups (primary vs secondary .mu) only when this part
        # actually loaded extra MODEL blocks.  Transform switches inside one
        # .mu (HighTanks / LowTanks) must rely solely on _apply_one_variant_objects
        # — calling _set_model_group_visible(__primary__) would unhide everything
        # again and undo the dome switch.
        has_secondary = False
        try:
            has_secondary = int(root.get("mu_secondary_models") or 0) > 0
        except Exception:
            has_secondary = False
        if not has_secondary:
            try:
                stack = [root] + list(getattr(root, "children_recursive", []) or [])
                has_secondary = any(o.get("mu_secondary_model") for o in stack)
            except Exception:
                pass
        multi_leaf = any(
            (l or "").lower() not in ("", "__primary__") for l in mesh_leaves
        )
        if mesh_leaves and (has_secondary or multi_leaf):
            try:
                _set_model_group_visible(root, mesh_leaves)
            except Exception as e:
                print(f"WARNING: final model group visibility: {e}")
            # Model-group pass force-unhides ALL primary objects (so secondary
            # rim can toggle). That undoes B9 exclusive hides like TallDome
            # on meshSwitchDome/Standard. Re-apply exclusive for every active
            # mesh module after the group pass.
            if mesh_switched or any_mesh:
                for entry in to_apply:
                    if not entry.get("b9"):
                        continue
                    if not (
                        _variant_is_mesh_switch(entry, variants)
                        or (entry.get("objects") or {})
                        or (entry.get("toggle_keys") or [])
                    ):
                        continue
                    try:
                        _apply_b9_module_exclusive(root, entry, variants, active_modules=data.get("active_modules"))
                    except Exception as e:
                        print(
                            "WARNING: re-exclusive after model groups: %s" % e
                        )
        elif mesh_switched and any_mesh:
            print(
                "INFO: in-model mesh switch (transforms only, no secondary MODEL)"
            )

    # --- Independent mesh vs paint state (per model leaf) ---
    paint_by_model = dict(data.get("paint_by_model") or {})
    default_paint = _default_paint_variant_name(data)

    active_leaf = data.get("active_mesh_leaf") or "__primary__"
    if mesh_switched and mesh_leaves:
        active_leaf = next(iter(mesh_leaves))
    elif mesh_switched:
        active_leaf = "__primary__"
    data["active_mesh_leaf"] = active_leaf

    if not skip_textures:
        if mesh_switched:
            # Stock MPV exclusive: VARIANT may carry both GAMEOBJECTS + TEXTURE
            # --- Texture handling after a MESH switch ---
            variants_all = data.get("variants") or []
            objs = chosen.get("objects") or {}
            b9_transform_mesh = bool(
                chosen.get("b9")
                and objs
                and any(bool(x) for x in objs.values())
            )
            stock_exclusive_tex = (
                not chosen.get("b9")
                and bool(chosen.get("textures") or chosen.get("texture_blocks"))
                and not _module_has_transform_subtypes(chosen, variants_all)
            )
            # Paint memory keyed by mesh state (multi-module + secondary leaf)
            mesh_key = _mesh_state_key(data, variants_all)
            data["active_mesh_paint_key"] = mesh_key
            first_visit = mesh_key not in paint_by_model
            paint_sync = ""

            if stock_exclusive_tex:
                try:
                    _apply_variant_textures(root, data, chosen)
                except Exception as e:
                    print("WARNING: stock mesh+TEXTURE: %s" % e)
                paint_by_model[mesh_key] = chosen.get("name")
                paint_sync = chosen.get("name") or ""
                print(
                    "INFO: mesh switch → stock exclusive %r key=%s"
                    % (chosen.get("name"), mesh_key)
                )
            elif (
                b9_transform_mesh
                and (chosen.get("b9_textures") or chosen.get("textures"))
            ):
                # Exclusive transform + own TEXTURE (Agena Seasat etc.)
                try:
                    _apply_paint_to_leaf(root, data, chosen, active_leaf)
                except Exception as e:
                    print("WARNING: B9 mesh TEXTURE: %s" % e)
                paint_by_model[mesh_key] = chosen.get("name")
                paint_sync = chosen.get("name") or ""
                print(
                    "INFO: mesh switch → self TEXTURE %r key=%s"
                    % (chosen.get("name"), mesh_key)
                )
            else:
                # Pure mesh switch (endcaps / secondary MODEL / mounts):
                # first visit → always default paint (never inherit Blue from
                # another mesh state via leaf legacy). Return visit → remembered.
                if first_visit:
                    tn, target_entry = None, None
                    if default_paint:
                        tn = default_paint
                        target_entry = _find_variant_entry(
                            variants_all, default_paint
                        )
                        if (
                            target_entry is not None
                            and not _variant_is_paint_switch(
                                target_entry, variants_all
                            )
                        ):
                            target_entry = None
                else:
                    tn, target_entry = _resolve_paint_for_key(
                        data,
                        mesh_key,
                        paint_by_model,
                        default_paint,
                        allow_legacy_leaf=False,
                    )
                # Always restore stock maps first so a texture-less default
                # subtype (Orange = primaryColor only) actually undoes Blue.
                try:
                    _restore_default_textures(root, data)
                except Exception:
                    pass
                if (
                    target_entry is not None
                    and _variant_is_paint_switch(target_entry, variants_all)
                ):
                    paint_by_model[mesh_key] = tn
                    if target_entry.get("b9_moduleID"):
                        am = dict(data.get("active_modules") or {})
                        am[target_entry["b9_moduleID"]] = tn.split("/")[-1]
                        data["active_modules"] = am
                    # Re-apply only when subtype has real TEXTURE maps
                    has_tex = bool(
                        target_entry.get("b9_textures")
                        or target_entry.get("textures")
                        or target_entry.get("texture_blocks")
                    )
                    if has_tex:
                        try:
                            _apply_paint_to_leaf(
                                root, data, target_entry, active_leaf
                            )
                        except Exception as e:
                            print("WARNING: mesh→paint: %s" % e)
                    paint_sync = tn
                    print(
                        "INFO: mesh switch → paint %r key=%s first_visit=%s "
                        "has_tex=%s"
                        % (tn, mesh_key, first_visit, has_tex)
                    )
                else:
                    if default_paint:
                        paint_by_model[mesh_key] = default_paint
                        de = _find_variant_entry(variants_all, default_paint)
                        if de is not None and de.get("b9_moduleID"):
                            am = dict(data.get("active_modules") or {})
                            am[de["b9_moduleID"]] = (
                                default_paint.split("/")[-1]
                            )
                            data["active_modules"] = am
                        paint_sync = default_paint
                    print(
                        "INFO: mesh switch → default/restore key=%s paint=%r"
                        % (mesh_key, paint_sync)
                    )

            try:
                sc = bpy.context.scene
                if sc is not None:
                    sc["mu_mesh_variant_sync"] = chosen.get("name") or ""
                    sc["mu_paint_variant_sync"] = paint_sync or ""
            except Exception:
                pass
        elif paint_chosen:
            # Explicit paint change → only current leaf materials
            pe = chosen
            # Remember paint under current mesh state key (+ leaf legacy)
            mk = data.get("active_mesh_paint_key") or _mesh_state_key(
                data, data.get("variants") or []
            )
            data["active_mesh_paint_key"] = mk
            paint_by_model[mk] = pe.get("name")
            paint_by_model[active_leaf] = pe.get("name")
            if pe.get("b9_moduleID"):
                am = dict(data.get("active_modules") or {})
                am[pe["b9_moduleID"]] = (pe.get("name") or "").split("/")[-1]
                data["active_modules"] = am
            ntex = len(pe.get("b9_textures") or [])
            nstock = len(pe.get("texture_blocks") or []) or len(
                pe.get("textures") or {}
            )
            print(
                "INFO: paint switch → %r leaf=%s b9_textures=%d stock_tex=%d"
                % (pe.get("name"), active_leaf, ntex, nstock)
            )
            _apply_paint_to_leaf(root, data, pe, active_leaf)
            try:
                sc = bpy.context.scene
                pn = pe.get("name")
                if sc is not None and pn:
                    sc["mu_paint_variant_sync"] = pn
            except Exception:
                pass

    data["paint_by_model"] = paint_by_model
    data["active_mesh_leaf"] = active_leaf
    try:
        root[MU_VARIANTS_KEY] = json.dumps(data)
    except Exception:
        pass

    # Nodes from the mesh-bearing entry (or chosen)
    node_entry = chosen
    for e in to_apply:
        if e.get("nodes"):
            node_entry = e
            break
    try:
        _apply_variant_node_positions(root, node_entry)
    except Exception as e:
        _vlog(f"WARNING: variant node positions: {e}")

    # B9 TRANSFORM rotationOffset / positionOffset
    try:
        for e in to_apply:
            if e.get("transform_ops"):
                _apply_variant_transform_ops(root, e)
    except Exception as e:
        _vlog(f"WARNING: variant transform_ops: {e}")

    # disabledAnimations → mute listed NLA tracks
    try:
        _apply_variant_disabled_animations(
            root, chosen, data.get("variants") or []
        )
    except Exception as e:
        _vlog(f"WARNING: disabledAnimations: {e}")

    data["active"] = variant_name
    root[MU_VARIANTS_KEY] = json.dumps(data)
    try:
        import bpy as _bpy
        br = getattr(_bpy.context.window_manager, "ksp_mu_browser", None)
        show = False
        if br is not None:
            show = bool(getattr(br, "show_attach_points", False))
        if not show:
            try:
                show = any(
                    (o.name or "").startswith("MU_ATTACH_")
                    or o.get("ksp_attach_node")
                    for o in _bpy.data.objects
                )
            except Exception:
                show = False
        if show:
            from ..mu_browser.operators import update_attach_point_markers
            update_attach_point_markers(_bpy.context, True)
    except Exception as e:
        _vlog(f"WARNING: attach markers after variant: {e}")
    return True



def _game_data_root(mudir):
    """Walk up from part folder to …/GameData."""
    cur = mudir
    for _ in range(12):
        if not cur:
            return None
        if os.path.basename(cur).lower() == "gamedata":
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def _resolve_texture_url(root, url):
    """Resolve KSP ``mainTextureURL`` (GameData-relative, no extension) to a file."""
    if not url:
        return None
    url = url.replace("\\", "/").strip().strip('"')
    mudir = None
    try:
        mudir = root.get("mu_dirname") if root is not None else None
    except Exception:
        mudir = None
    if not mudir:
        # Infer from any image filepath under this import
        for mat in _iter_materials_under(root):
            node = _maintex_image_node(mat)
            if node is None or node.image is None:
                continue
            try:
                fp = bpy.path.abspath(node.image.filepath)
            except Exception:
                fp = node.image.filepath
            if fp and os.path.isfile(fp):
                mudir = os.path.dirname(fp)
                break
    candidates = []
    gd = _game_data_root(mudir) if mudir else None
    if gd:
        base = os.path.join(gd, *url.split("/"))
        for ext in (".dds", ".png", ".tga", ".mbm"):
            candidates.append(base + ext)
    if mudir:
        leaf = url.split("/")[-1]
        for ext in (".dds", ".png", ".tga", ".mbm"):
            candidates.append(os.path.join(mudir, leaf + ext))
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _iter_materials_under(root):
    seen = set()
    stack = [root] if root is not None else []
    while stack:
        o = stack.pop()
        if o.type == "MESH" and getattr(o, "data", None):
            for slot in o.material_slots:
                mat = slot.material
                if mat is not None and mat.name not in seen:
                    seen.add(mat.name)
                    yield mat
        stack.extend(list(o.children))


def _maintex_image_node(mat):
    nt = getattr(mat, "node_tree", None)
    if not nt:
        return None
    node = nt.nodes.get("_MainTex")
    if node is not None and getattr(node, "image", None) is not None:
        return node
    # Fallback: first image node feeding Principled Base Color / SpecPBR
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image is not None:
            return n
    return None


def _curve_end_value(curve_body, default=0.0):
    """Last ``key = t value …`` sample from a ModuleColorChanger *Curve block."""
    if not curve_body:
        return float(default)
    last = default
    for m in re.finditer(
        r"^\s*key\s*=\s*([-\d.]+)\s+([-\d.]+)", curve_body, re.M | re.I
    ):
        try:
            last = float(m.group(2))
        except Exception:
            pass
    return float(last)


def apply_color_changer_preview(root, info):
    """Viewport NLA: ModuleColorChanger lights off→on (Cupola / cabin windows).

    Stock ``_EmissiveColor`` stays at cfg OFF in mumatprop (export/reimport safe).
    A preview-only material Action (``mu_fx_preview``) drives the ON colour so
    scrubbing / GIF matches other glow clips. Export skips that Action.
    """
    if not root or not info:
        return 0
    from ..utils.action_compat import (
        ensure_action_assigned,
        fcurve_new,
        push_action_to_nla,
    )
    try:
        from ..shader.colorprops import apply_color_prop_to_nodes
    except Exception:
        apply_color_prop_to_nodes = None
    try:
        from ..shader.shader import ensure_heat_emissive_map_visible
    except Exception:
        ensure_heat_emissive_map_visible = None

    prop_name = info.get("shaderProperty") or "_EmissiveColor"
    off = list(info.get("off") or (0.0, 0.0, 0.0, 1.0))
    on = list(info.get("on") or (1.0, 1.0, 0.7, 1.0))
    while len(off) < 4:
        off.append(1.0)
    while len(on) < 4:
        on.append(1.0)
    off = tuple(float(x) for x in off[:4])
    on = tuple(float(x) for x in on[:4])
    mat_filter = None
    if info.get("useMaterialsList") or info.get("materialsNames"):
        names = info.get("materialsNames") or []
        mat_filter = {n.lower() for n in names if n}
    included = info.get("includedRenderers") or []
    included_set = {n.lower() for n in included if n} if included else None

    scene = bpy.context.scene
    try:
        fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)
    except Exception:
        fps = 24.0
    fps = max(1.0, fps)
    # ~1s fade (ModuleColorChanger animRate≈0.8 → similar feel)
    f0 = int(scene.frame_start) if scene else 1
    f1 = f0 + max(12, int(round(fps * 1.0)))

    n = 0
    for mat in _iter_materials_under(root):
        if mat_filter is not None:
            stem = (mat.name or "").split("∧")[0]
            if "." in stem:
                b, s = stem.rsplit(".", 1)
                if s.isdigit():
                    stem = b
            if stem.lower() not in mat_filter and (mat.name or "").lower() not in mat_filter:
                continue
        if included_set is not None:
            # includedRenderers names mesh/renderer hosts — keep mats used by them
            used = False
            for o in bpy.data.objects:
                if not o.data or not hasattr(o.data, "materials"):
                    continue
                oname = (o.name or "").split("∧")[0]
                if "." in oname:
                    b, s = oname.rsplit(".", 1)
                    if s.isdigit():
                        oname = b
                if oname.lower() not in included_set:
                    continue
                if mat.name in (m.name for m in o.data.materials if m):
                    used = True
                    break
            if not used:
                continue
        mp = getattr(mat, "mumatprop", None)
        if not mp:
            continue
        prop = None
        prop_idx = -1
        try:
            for i, p in enumerate(mp.color.properties):
                if p.name == prop_name:
                    prop = p
                    prop_idx = i
                    break
        except Exception:
            continue
        if prop is None or prop_idx < 0:
            continue
        # Keep stock OFF for export; nodes follow via sync handler
        try:
            prop.value = off
        except Exception:
            pass
        if apply_color_prop_to_nodes is not None:
            try:
                apply_color_prop_to_nodes(mat, prop)
            except Exception:
                pass
        if ensure_heat_emissive_map_visible is not None:
            try:
                ensure_heat_emissive_map_visible(mat)
            except Exception:
                pass
        nt = getattr(mat, "node_tree", None)
        if nt:
            mul = nt.nodes.get("_MuEmStrengthScale")
            if mul is not None and mul.inputs:
                try:
                    mul.inputs[1].default_value = max(
                        float(mul.inputs[1].default_value), 1.1
                    )
                except Exception:
                    pass

        # Already have a preview ColorChanger track?
        ad = getattr(mat, "animation_data", None)
        if ad and ad.nla_tracks:
            skip = False
            for t in ad.nla_tracks:
                tn = (t.name or "")
                if tn.startswith("ColorChangerLights"):
                    skip = True
                    break
            if skip:
                n += 1
                continue

        act_name = f"ColorChangerLights.{mat.name}"[:60]
        act = bpy.data.actions.get(act_name)
        if act is None:
            act = bpy.data.actions.new(name=act_name)
        try:
            act["mu_fx_preview"] = 1
        except Exception:
            pass
        try:
            act["mu_color_changer_preview"] = 1
        except Exception:
            pass
        ensure_action_assigned(mat, act)
        path = f"mumatprop.color.properties[{prop_idx}].value"
        for i in range(4):
            try:
                fc = fcurve_new(act, mat, path, i)
            except Exception:
                continue
            try:
                while fc.keyframe_points:
                    fc.keyframe_points.remove(fc.keyframe_points[0])
            except Exception:
                pass
            try:
                fc.keyframe_points.add(2)
                fc.keyframe_points[0].co = (float(f0), float(off[i]))
                fc.keyframe_points[0].interpolation = "LINEAR"
                fc.keyframe_points[1].co = (float(f1), float(on[i]))
                fc.keyframe_points[1].interpolation = "LINEAR"
            except Exception:
                pass
        track, _strip = push_action_to_nla(mat, act, "ColorChangerLights")
        # NLATrack may not support IDProperties in Blender 5 — name is the marker
        try:
            if track is not None and hasattr(track, "name"):
                track.name = "ColorChangerLights"
        except Exception:
            pass
        try:
            mat["mu_color_changer_preview"] = 1
        except Exception:
            pass
        n += 1
    return n


def parse_module_color_changer(cfg_text):
    """Parse first ModuleColorChanger → emissive window-light preview targets.

    Skips heat-shield burn modules (``_BurnColor``, editor-off without light flags).
    Returns dict with shaderProperty + off/on RGBA (+ optional materialsNames), or None.
    """
    if not cfg_text or "ModuleColorChanger" not in cfg_text:
        return None
    for block in re.finditer(
        r"MODULE\s*\{", cfg_text, re.I
    ):
        start = block.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "ModuleColorChanger":
            continue
        prop = "_EmissiveColor"
        pm = re.search(r"^\s*shaderProperty\s*=\s*(.+)$", body, re.M | re.I)
        if pm:
            prop = pm.group(1).strip().strip('"')
        # Heat shields use _BurnColor — not cabin lights
        if "burn" in prop.lower():
            continue

        def _bool_field(name, default=False):
            m = re.search(rf"^\s*{name}\s*=\s*(.+)$", body, re.M | re.I)
            if not m:
                return default
            v = m.group(1).strip().strip('"').lower()
            return v in ("true", "1", "yes")

        toggle_ed = _bool_field("toggleInEditor", False)
        use_rate = _bool_field("useRate", False)
        use_mats = _bool_field("useMaterialsList", False)
        mats = []
        mm = re.search(r"^\s*materialsNames\s*=\s*(.+)$", body, re.M | re.I)
        if mm:
            mats = [
                x.strip()
                for x in mm.group(1).strip().strip('"').split(",")
                if x.strip()
            ]
            if mats:
                use_mats = True
        included = []
        ir = re.search(r"^\s*includedRenderers\s*=\s*(.+)$", body, re.M | re.I)
        if ir:
            included = [
                x.strip()
                for x in ir.group(1).strip().strip('"').split(",")
                if x.strip()
            ]
        # Lights: emissive + editor toggle / rate / materials list (EVA)
        if prop != "_EmissiveColor" and not mats and not included:
            continue
        if not (toggle_ed or use_rate or use_mats or included):
            continue

        def _curve(name):
            m = re.search(
                rf"{name}\s*\{{([^}}]*)\}}", body, re.I | re.S
            )
            return m.group(1) if m else ""

        on = (
            _curve_end_value(_curve("redCurve"), 1.0),
            _curve_end_value(_curve("greenCurve"), 1.0),
            _curve_end_value(_curve("blueCurve"), 1.0),
            _curve_end_value(_curve("alphaCurve"), 1.0),
        )
        # EVA-style solid tint when curves missing but RGB colors set
        if not _curve("redCurve"):
            def _f(n, d):
                m = re.search(rf"^\s*{n}\s*=\s*(.+)$", body, re.M | re.I)
                if not m:
                    return d
                try:
                    return float(m.group(1).strip().strip('"'))
                except Exception:
                    return d
            on = (
                _f("redColor", on[0]),
                _f("greenColor", on[1]),
                _f("blueColor", on[2]),
                _curve_end_value(_curve("alphaCurve"), on[3]),
            )
        out = {
            "shaderProperty": prop,
            "off": (0.0, 0.0, 0.0, 1.0),
            "on": on,
        }
        if mats:
            out["materialsNames"] = mats
            out["useMaterialsList"] = True
        if included:
            out["includedRenderers"] = included
        return out
    return None


def _ensure_default_textures_cached(root, data):
    """Remember per-material stock texture names (before any TEXTURE preview swap).

    Merges incrementally so secondary MODEL materials loaded later still get
    stock baselines (Green restore). Includes empty ``tex`` slots (flag
    placeholders) and node ``texture_mapping`` per slot.
    """
    defaults = dict(data.get("_default_maintex") or {})
    texprops = dict(data.get("_default_texprops") or {})
    mapping = dict(data.get("_default_texmapping") or {})
    changed = False
    for mat in _iter_materials_under(root):
        mname = getattr(mat, "name", None) or ""
        if not mname:
            continue
        # MainTex baseline
        if mname not in defaults:
            try:
                node = _maintex_image_node(mat)
                img = getattr(node, "image", None) if node else None
                defaults[mname] = img.name if img else ""
                changed = True
            except Exception:
                defaults[mname] = ""
                changed = True
        # All texture property slots
        if mname not in texprops:
            slots = {}
            try:
                for tp in mat.mumatprop.texture.properties:
                    name = getattr(tp, "name", None)
                    if not name:
                        continue
                    slots[name] = getattr(tp, "tex", None) or ""
            except Exception:
                pass
            texprops[mname] = slots
            changed = True
        # UV mapping baseline
        if mname not in mapping:
            mat_map = {}
            try:
                for tp in mat.mumatprop.texture.properties:
                    name = getattr(tp, "name", None)
                    if not name:
                        continue
                    node = _shader_slot_image_node(mat, name)
                    if node is None:
                        continue
                    mat_map[name] = {
                        "scale": (
                            float(node.texture_mapping.scale[0]),
                            float(node.texture_mapping.scale[1]),
                        ),
                        "translation": (
                            float(node.texture_mapping.translation[0]),
                            float(node.texture_mapping.translation[1]),
                        ),
                    }
            except Exception:
                pass
            if mat_map:
                mapping[mname] = mat_map
                changed = True
    if changed or data.get("_default_maintex") is None:
        data["_default_maintex"] = defaults
        data["_default_texprops"] = texprops
        data["_default_texmapping"] = mapping



def _mat_had_stock_slot(data, mat, slot):
    """True when this material had a non-empty stock map for ``slot``.

    TEXTURE variants must not paint Dark/Gray onto flag / empty placeholders
    (smallClaw / GrapplingDevice ``flagMat``) — those leak into .mu export.
    """
    if mat is None or not slot:
        return False
    texprops = (data.get("_default_texprops") or {}).get(mat.name) or {}
    if slot in texprops:
        return bool(texprops.get(slot))
    if slot == "_MainTex":
        return bool((data.get("_default_maintex") or {}).get(mat.name))
    return False


def _clear_material_slot_image(mat, slot_name):
    """Clear Image Texture node + mumatprop.tex for a slot (stock was empty)."""
    if mat is None or not slot_name:
        return False
    cleared = False
    nt = getattr(mat, "node_tree", None)
    if nt:
        node = _shader_slot_image_node(mat, slot_name)
        if node is not None:
            node.image = None
            cleared = True
    try:
        for tp in mat.mumatprop.texture.properties:
            if tp.name != slot_name:
                continue
            tp.tex = ""
            cleared = True
            break
    except Exception:
        pass
    return cleared


def restore_default_textures(root):
    """Undo ModulePartVariants TEXTURE preview swaps (export-safe stock maps).

    Viewport may still show a paint variant; call this before .mu export so
    ``mumatprop.tex`` matches the imported stock names (Serenity Gray/plain).
    Keeps MassiveBooster ESA preview intact until export restore.
    """
    if root is None or MU_VARIANTS_KEY not in root:
        return False
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return False
    _ensure_default_textures_cached(root, data)
    defaults = data.get("_default_maintex") or {}
    texprops = data.get("_default_texprops") or {}
    restored = False
    for mat in _iter_materials_under(root):
        slots = dict(texprops.get(mat.name) or {})
        if not slots and defaults.get(mat.name):
            slots["_MainTex"] = defaults[mat.name]
        for slot, dname in slots.items():
            if not dname:
                if _clear_material_slot_image(mat, slot):
                    restored = True
                continue
            if dname not in bpy.data.images:
                continue
            img = bpy.data.images[dname]
            _configure_variant_image(img, getattr(img, "filepath", "") or "")
            if _set_material_slot_image(mat, slot, img):
                restored = True
    base = data.get("base")
    if base:
        data["active"] = base
    root[MU_VARIANTS_KEY] = json.dumps(data)
    return restored


def get_active_variant_name(root):
    """Return currently active ModulePartVariants name, or None."""
    if root is None or MU_VARIANTS_KEY not in root:
        return None
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return None
    return data.get("active") or data.get("base") or None


def add_variant_duplicate(root, new_name=None):
    """Duplicate active (or Stock/base) variant; return new name or None.

    Only updates ``mu_variants`` JSON (cfg ModulePartVariants). Does **not**
    create Blender Collection / Outliner entries — GAMEOBJECTS/TEXTURE state
    is applied via ``apply_variant``; no meshes are invented.
    """
    if root is None or MU_VARIANTS_KEY not in root:
        return None
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return None
    variants = list(data.get("variants") or [])
    if not variants:
        return None
    active = data.get("active") or data.get("base")
    src = None
    for v in variants:
        if v.get("name") == active:
            src = v
            break
    if src is None:
        src = variants[0]
    base_name = new_name or f"{src.get('name') or 'Variant'}_copy"
    existing = {v.get("name") for v in variants}
    name = base_name
    n = 2
    while name in existing:
        name = f"{base_name}_{n}"
        n += 1
    import copy
    dup = copy.deepcopy(src)
    dup["name"] = name
    dup["displayName"] = name
    dup["themeName"] = name
    dup.pop("stock", None)
    variants.append(dup)
    data["variants"] = variants
    data["active"] = name
    root[MU_VARIANTS_KEY] = json.dumps(data)
    apply_variant(root, name)
    return name


def remove_active_variant(root):
    """Remove active variant unless it is Stock or the only remaining entry.

    Only removes the name from ``mu_variants`` JSON and re-applies the new
    active via ``apply_variant``. Does **not** delete imported meshes or
    Outliner collections (those are .mu hierarchy / vis groups, not cfg
    VARIANT entries).

    Returns True on success.
    """
    if root is None or MU_VARIANTS_KEY not in root:
        return False
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return False
    variants = list(data.get("variants") or [])
    if len(variants) <= 1:
        return False
    active = data.get("active") or data.get("base")
    chosen = next((v for v in variants if v.get("name") == active), None)
    if chosen is None:
        return False
    # Never delete synthetic Stock / sole base
    if chosen.get("stock") or chosen.get("name") == STOCK_VARIANT_NAME:
        return False
    # Never delete B9 subtypes that come from the part .cfg — removing them
    # breaks Mesh/Paint enums and paint_by_model memory.
    if chosen.get("b9") or chosen.get("b9_moduleID"):
        return False
    if chosen.get("name") == data.get("base"):
        # Reassign base to first remaining non-removed variant later
        pass
    variants = [v for v in variants if v.get("name") != active]
    if not variants:
        return False
    data["variants"] = variants
    if data.get("base") == active:
        data["base"] = variants[0].get("name")
    new_active = data.get("base") or variants[0].get("name")
    if not any(v.get("name") == new_active for v in variants):
        new_active = variants[0].get("name")
    data["active"] = new_active
    root[MU_VARIANTS_KEY] = json.dumps(data)
    apply_variant(root, new_active)
    return True


def prepare_stock_for_export(root):
    """Switch hierarchy to stock/base materials + GAMEOBJECTS for normal export.

    Returns the previous active variant name (for ``finish_stock_export``),
    or None when the root has no ``mu_variants``.
    """
    if root is None or MU_VARIANTS_KEY not in root:
        return None
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return None
    prev = data.get("active") or data.get("base")
    base = data.get("base")
    if base:
        # GAMEOBJECTS only — TEXTURE swaps are viewport-only and restored below.
        apply_variant(root, base, skip_textures=True)
    restore_default_textures(root)
    return prev


def finish_stock_export(root, previous_variant):
    """Re-apply the viewport preview variant after a stock .mu export."""
    if root is None or not previous_variant:
        return False
    ok = bool(apply_variant(root, previous_variant))
    try:
        scene = bpy.context.scene
        if hasattr(scene, "mu_active_variant"):
            scene["mu_active_variant"] = previous_variant
    except Exception:
        pass
    return ok


def _configure_variant_image(img, path):
    """Match import_mu.textures.load_image so EEVEE does not premul-black DDS."""
    if img is None:
        return
    try:
        # Squad diffuse DDS often has near-zero alpha; STRAIGHT → black in EEVEE.
        img.alpha_mode = "CHANNEL_PACKED"
    except Exception:
        pass
    try:
        img.colorspace_settings.is_data = False
    except Exception:
        pass
    if path and str(path).lower().endswith(".dds"):
        try:
            img.muimageprop.invertY = True
        except Exception:
            pass


def _load_variant_image(path, name_hint):
    """Load variant DDS/PNG from GameData (reuses path-keyed cache)."""
    if not path or not os.path.isfile(path):
        return None
    path = os.path.normpath(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    name = name_hint or stem
    # Prefer import_mu.textures path cache — shared with primary MODEL load
    try:
        from .textures import _find_cached_image, _register_cached_image
        cached = _find_cached_image(path)
        if cached is not None:
            _configure_variant_image(cached, path)
            return cached
    except Exception:
        _register_cached_image = None
    if name in bpy.data.images:
        img = bpy.data.images[name]
        try:
            existing = os.path.normpath(bpy.path.abspath(img.filepath)) if img.filepath else ""
            if existing and existing != path:
                img.filepath = path
                img.reload()
        except Exception:
            pass
        _configure_variant_image(img, path)
        try:
            if _register_cached_image:
                _register_cached_image(path, img)
        except Exception:
            pass
        return img
    try:
        img = bpy.data.images.load(path)
        img.name = name
        _configure_variant_image(img, path)
        try:
            if _register_cached_image:
                _register_cached_image(path, img)
        except Exception:
            pass
        return img
    except Exception:
        return None


def _shader_slot_image_node(mat, slot_name):
    """Image Texture node for a mumatprop slot (handles _MainTex alias)."""
    if slot_name == "_MainTex":
        return _maintex_image_node(mat)
    nt = getattr(mat, "node_tree", None)
    if not nt or not slot_name:
        return None
    node = nt.nodes.get(slot_name)
    if node is None or not hasattr(node, "image"):
        return None
    return node


def _apply_texprop_mapping(mat, texprop):
    """Push scale/offset (+ DDS invertY) onto the Image Texture node."""
    nt = getattr(mat, "node_tree", None)
    if not nt or not texprop or not getattr(texprop, "name", None):
        return
    node = _shader_slot_image_node(mat, texprop.name)
    if node is None:
        return
    try:
        scale = Vector((float(texprop.scale[0]), float(texprop.scale[1])))
        offset = Vector((float(texprop.offset[0]), float(texprop.offset[1])))
    except Exception:
        scale = Vector((1.0, 1.0))
        offset = Vector((0.0, 0.0))
    tex_name = getattr(texprop, "tex", "") or ""
    if tex_name in bpy.data.images:
        img = bpy.data.images[tex_name]
        try:
            if img.muimageprop.invertY:
                scale = Vector((scale.x, -scale.y))
                offset = Vector((offset.x, 1.0 - offset.y))
        except Exception:
            pass
    try:
        node.texture_mapping.translation.xy = offset
        node.texture_mapping.scale.xy = scale
    except Exception:
        pass


def _set_material_slot_image_viewport(mat, slot_name, img, data=None):
    """Viewport-only variant swap: change node image only (UV stays from import).

    ModulePartVariants TEXTURE maps share the same UV layout as stock .mu;
    re-applying scale/offset/invertY scrambles mapping (adapter zebra, etc.).
    ``data`` is ignored (kept for call-site compatibility).
    """
    del data
    if mat is None or img is None or not slot_name:
        return False
    node = _shader_slot_image_node(mat, slot_name)
    if node is None:
        return False
    is_bump = slot_name == "_BumpMap"
    try:
        for tp in mat.mumatprop.texture.properties:
            if tp.name == slot_name:
                is_bump = bool(getattr(tp, "type", False))
                break
    except Exception:
        pass
    node.image = img
    try:
        node.image.colorspace_settings.is_data = is_bump
    except Exception:
        pass
    # Keep MU texture prop in sync so later restore/export sees the swap
    try:
        for tp in mat.mumatprop.texture.properties:
            if tp.name == slot_name:
                tp.tex = img.name
                break
    except Exception:
        pass
    try:
        mat.update_tag()
    except Exception:
        pass
    return True


def _set_material_slot_image(mat, slot_name, img):
    """Assign image to shader slot node + keep mumatprop.tex / UV mapping in sync."""
    if mat is None or img is None or not slot_name:
        return False
    node = _shader_slot_image_node(mat, slot_name)
    if node is None:
        return False
    node.image = img
    try:
        for tp in mat.mumatprop.texture.properties:
            if tp.name != slot_name:
                continue
            tp.tex = img.name
            _apply_texprop_mapping(mat, tp)
            return True
    except Exception:
        pass
    try:
        if img.muimageprop.invertY:
            node.texture_mapping.scale.xy = (1.0, -1.0)
            node.texture_mapping.translation.xy = (0.0, 1.0)
    except Exception:
        pass
    return True


def _apply_one_stock_texture_map(root, data, tex_map, mats):
    """Apply one stock TEXTURE { } key/value map to matching materials."""
    if not tex_map or not mats:
        return 0
    slot_urls = {}
    material_filter = None
    for k, v in (tex_map or {}).items():
        if not v:
            continue
        key = (k or "").strip()
        if key in ("mainTextureURL", "mainTexture", "FairingsTextureURL"):
            slot_urls["_MainTex"] = v
        elif key in ("TextureNormalURL", "FairingsNormalURL", "_BumpMap"):
            slot_urls["_BumpMap"] = v
        elif key.startswith("_"):
            slot_urls[key] = v
        elif key == "materialName":
            material_filter = v

    def _mat_matches(mat):
        if not material_filter:
            return True
        mn = (mat.name or "").split(".")[0]
        want = material_filter
        if want == "FairingsMat":
            return mn in ("FairingIconShell", "FairingsMat", "FairingShell")
        return mn == want or want in mn

    n = 0
    if slot_urls:
        for slot, url in slot_urls.items():
            path = _resolve_texture_url(root, url)
            if not path:
                _vlog("WARNING: stock TEXTURE resolve failed: %s" % url)
                continue
            img = _load_variant_image(
                path, os.path.splitext(os.path.basename(path))[0]
            )
            if img is None:
                continue
            for mat in mats:
                if not _mat_matches(mat):
                    continue
                if not _mat_had_stock_slot(data, mat, slot):
                    continue
                if _set_material_slot_image_viewport(mat, slot, img, data=data):
                    n += 1
    # EXTRA_INFO style base maps
    base_tex = (tex_map or {}).get("BaseTextureName") or (tex_map or {}).get(
        "DefaultBaseTextureURL"
    )
    base_nm = (tex_map or {}).get("BaseNormalsName") or (tex_map or {}).get(
        "DefaultBaseNormalsURL"
    )
    base_mat_name = (tex_map or {}).get("BaseMaterialName") or "FairingBase"
    if base_tex or base_nm:
        for mat in mats:
            mn = (mat.name or "").split(".")[0]
            if mn != base_mat_name and base_mat_name not in mn:
                continue
            if base_tex:
                path = _resolve_texture_url(root, base_tex)
                if path:
                    img = _load_variant_image(
                        path, os.path.splitext(os.path.basename(path))[0]
                    )
                    if img and _set_material_slot_image_viewport(
                        mat, "_MainTex", img, data=data
                    ):
                        n += 1
            if base_nm:
                path = _resolve_texture_url(root, base_nm)
                if path:
                    img = _load_variant_image(
                        path, os.path.splitext(os.path.basename(path))[0]
                    )
                    if img and _set_material_slot_image_viewport(
                        mat, "_BumpMap", img, data=data
                    ):
                        n += 1
    return n


def _apply_variant_textures(root, data, chosen):
    """Apply ModulePartVariants TEXTURE + B9PartSwitch TEXTURE switches."""
    _ensure_default_textures_cached(root, data)
    # Full B9 TEXTURE nodes (transform-scoped, currentTexture, normals…)
    if chosen.get("b9_textures"):
        try:
            _apply_b9_textures(root, data, chosen)
        except Exception as e:
            _vlog("WARNING: B9 TEXTURE apply:", e)
        # Still fall through for any flat slot map on the same subtype
    mats = list(_iter_materials_under(root))
    if not mats:
        return

    blocks = list(chosen.get("texture_blocks") or [])
    if not blocks and (chosen.get("textures") or {}):
        blocks = [chosen.get("textures") or {}]
    total = 0
    for tex_map in blocks:
        total += _apply_one_stock_texture_map(root, data, tex_map, mats)
    if total:
        print(
            "INFO: stock TEXTURE maps applied=%d variant=%r"
            % (total, chosen.get("name"))
        )
    return



def find_variant_root(obj=None, context=None):
    """Prefer active object / active collection hierarchy for mu_variants.

    When multiple imported .mu with variants share a scene, Options must
    target the selection's import root — not the first root in bpy.data.
    """
    def _walk_up(o):
        cur = o
        while cur is not None:
            if MU_VARIANTS_KEY in cur:
                return cur
            cur = cur.parent
        return None

    def _scan_objects(objects):
        # Prefer roots (no parent) that carry variants, else any match
        roots = []
        any_hit = []
        for o in objects:
            if MU_VARIANTS_KEY not in o:
                continue
            any_hit.append(o)
            if o.parent is None:
                roots.append(o)
        if roots:
            return roots[0]
        return any_hit[0] if any_hit else None

    if obj is not None:
        hit = _walk_up(obj)
        if hit is not None:
            return hit

    ctx = context
    if ctx is None:
        try:
            ctx = bpy.context
        except Exception:
            ctx = None

    # Active collection: if user selected a collection in the outliner
    if ctx is not None:
        col = getattr(ctx, "collection", None)
        if col is not None:
            # Collection itself may be the import root name — scan its objects
            hit = _scan_objects(list(getattr(col, "all_objects", []) or []))
            if hit is not None:
                # Prefer variant root that belongs to this collection
                return hit
        # Selected objects (multi-select): first that resolves
        for o in list(getattr(ctx, "selected_objects", []) or []):
            hit = _walk_up(o)
            if hit is not None:
                return hit
        ao = getattr(ctx, "active_object", None)
        if ao is not None:
            hit = _walk_up(ao)
            if hit is not None:
                return hit

    for o in bpy.data.objects:
        if o.parent is None and MU_VARIANTS_KEY in o:
            return o
    for o in bpy.data.objects:
        if MU_VARIANTS_KEY in o:
            return o
    return None


def _module_has_transform_subtypes(v, all_variants=None):
    """True if any subtype of the same B9 moduleID toggles transforms."""
    if not v:
        return False
    mid = v.get("b9_moduleID")
    if not mid:
        return False
    for o in all_variants or []:
        if (o.get("b9_moduleID") or "") != mid:
            continue
        objs = o.get("objects") or {}
        if objs and any(bool(x) for x in objs.values()):
            # Ignore pure paint modules that only got TEXTURE-filter transforms
            omid = (o.get("b9_moduleID") or "").lower()
            if any(x in omid for x in ("paint", "color", "skin", "coating")):
                if o.get("b9_textures") or o.get("textures"):
                    continue
            return True
    return False


def _variant_is_node_only(v):
    """B9 subtype that only toggles attach nodes (No/Yes) — no mesh, no paint."""
    if not v:
        return False
    objs = v.get("objects") or {}
    has_vis = objs and any(bool(x) for x in objs.values())
    has_tex = bool(
        v.get("b9_textures")
        or v.get("textures")
        or v.get("texture_blocks")
    )
    if has_vis or has_tex:
        return False
    mid = (v.get("b9_moduleID") or "").lower()
    name = (v.get("name") or "").lower()
    if any(x in mid for x in ("node", "attach", "attache")):
        return True
    if any(x in name for x in ("attachenodes", "/yes", "/no")) and not has_vis:
        # weak: only with empty objects
        if "node" in mid or "attach" in mid:
            return True
    if v.get("nodes") and not has_vis and not has_tex:
        return True
    # Empty B9 subtype with no mesh/texture (attach node toggles often look like this)
    if v.get("b9") and not objs and not has_tex:
        if "paint" in mid or "color" in mid or "texture" in mid or "mesh" in mid:
            return False
        if "node" in mid or "attach" in mid or "mirror" in mid:
            return True
    return False


def _variant_is_mesh_switch(v, all_variants=None):
    """True if this entry toggles meshes/models (not pure paint / node-only)."""
    if not v:
        return False
    if _variant_is_node_only(v):
        return False
    objs = v.get("objects") or {}
    mid = (v.get("b9_moduleID") or "").lower()
    # Paint module with textures: never mesh even if MM leaked a transform key
    if any(x in mid for x in ("paint", "color", "skin", "coating")):
        if v.get("b9_textures") or v.get("textures") or v.get("texture_blocks"):
            return False
        # Orange subtype with only primaryColor and no transforms
        if not objs or not any(bool(x) for x in objs.values()):
            return False
    if objs and any(bool(x) for x in objs.values()):
        return True
    # Empty subtype of a transform module (Standard hides TallDome; No Rim hides rim)
    if (
        objs
        and not any(bool(x) for x in objs.values())
        and (v.get("toggle_keys") or list(objs.keys()))
    ):
        if all_variants is not None and _module_has_transform_subtypes(
            v, all_variants
        ):
            if not any(x in mid for x in ("paint", "color", "skin", "coating")):
                return True
        elif any(
            x in mid
            for x in ("mesh", "model", "dome", "rim", "end", "tank", "side", "switch")
        ):
            return True
    if all_variants is not None and _module_has_transform_subtypes(v, all_variants):
        # Sibling of transform module — but not if we are pure paint mid
        if any(x in mid for x in ("paint", "color", "skin", "coating")):
            return False
        return True
    if objs:
        if not v.get("b9"):
            return True
        if any(
            x in mid
            for x in (
                "tank", "model", "mesh", "side", "dome", "size", "variant",
                "switchside", "switchmesh", "switchmodel", "end", "cap",
            )
        ):
            return True
        if "switch" in mid and "paint" not in mid and "color" not in mid:
            if any(x in mid for x in ("side", "mesh", "model", "dome", "end", "tank")):
                return True
        return False
    return False


def _variant_is_paint_switch(v, all_variants=None):
    """True if this entry is primarily independent texture/paint."""
    if not v:
        return False
    if _variant_is_node_only(v):
        return False
    if _variant_is_mesh_switch(v, all_variants):
        return False
    mid = (v.get("b9_moduleID") or "").lower()
    # Genuine paint module
    if any(x in mid for x in ("paint", "color", "skin", "coating")):
        return True
    if v.get("b9_textures"):
        return True
    if v.get("textures"):
        return True
    if v.get("texture_blocks"):
        return True
    if "texture" in mid or "tex" in mid:
        # textureSwitch* without objects / not mesh
        return True
    if v.get("stock") and not v.get("b9"):
        return True
    # Do NOT treat empty B9 (node switches) as paint
    return False



def _variant_ui_label(v, root=None, inline_table=None):
    """Human label for a variant entry (resolves #autoLOC / #LOC / themeName)."""
    try:
        from .ksp_loc import resolve_loc, gamedata_from_root
    except Exception:
        from ksp_loc import resolve_loc, gamedata_from_root  # type: ignore
    name = (v or {}).get("name") or "?"
    bare = name.split("/")[-1] if "/" in name else name
    dn = (v or {}).get("displayName") or ""
    theme = (v or {}).get("themeName") or ""
    gd = gamedata_from_root(root) if root is not None else None
    label = resolve_loc(
        dn or "",
        theme_name=theme or bare,
        gamedata_path=gd,
        inline_table=inline_table,
    )
    if not label or label.startswith("#"):
        label = resolve_loc(
            bare,
            theme_name=theme,
            gamedata_path=gd,
            inline_table=inline_table,
        )
    if not label or label.startswith("#"):
        label = theme or bare
    return label


def get_variant_items(scene, context):
    """Enum items callback for Options → Part Variant dropdown (all)."""
    root = find_variant_root(
        getattr(context, "active_object", None) if context else None,
        context=context,
    )
    items = [("NONE", "(no variants)", "No ModulePartVariants on import")]
    if root is None:
        return items
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return items
    items = []
    base = data.get("base") or ""
    inline = data.get("_loc_inline") or {}
    for v in data.get("variants") or []:
        name = v.get("name") or "?"
        if v.get("stock") or name == STOCK_VARIANT_NAME:
            label = (
                _variant_ui_label(v, root, inline)
                or data.get("baseDisplayName")
                or data.get("baseThemeName")
                or "Stock"
            )
        else:
            label = _variant_ui_label(v, root, inline)
        if name == base and label and "(default)" not in label:
            label = f"{label} (default)"
        items.append((name, label, f"Activate variant '{name}'"))
    return items or [("NONE", "(no variants)", "")]


def get_mesh_switch_groups(root=None, context=None, data=None):
    """Independent B9 mesh modules as separate UI groups (Dome, Rim, …).

    Returns list of dicts:
      {module_id, label, items: [(identifier, name, desc), ...]}
    Stock / hierarchy mesh variants (no moduleID) go in one group "Mesh".
    """
    if data is None:
        if root is None:
            root = find_variant_root(
                getattr(context, "active_object", None) if context else None,
                context=context,
            )
        if root is None or MU_VARIANTS_KEY not in root:
            return []
        try:
            data = json.loads(root[MU_VARIANTS_KEY])
        except Exception:
            return []
    variants = data.get("variants") or []
    inline = data.get("_loc_inline") or {}
    # module_id → [(name, label)]
    groups_map = {}
    order = []
    for v in variants:
        if not _variant_is_mesh_switch(v, variants):
            continue
        mid = v.get("b9_moduleID") or ""
        key = mid or "_mesh"
        if key not in groups_map:
            groups_map[key] = []
            order.append(key)
        name = v.get("name") or "?"
        bare = name.split("/")[-1] if "/" in name else name
        label = _variant_ui_label(v, root, inline) if root is not None else bare
        if v.get("b9") and label and len(str(label)) > 28:
            label = bare
        if not label:
            label = bare
        groups_map[key].append((name, label, "Mesh / model variant"))
    out = []
    for key in order:
        items = groups_map[key]
        if not items:
            continue
        # Label from switcherDescription of first variant in group
        label = "Mesh"
        if key != "_mesh":
            label = None
            for v in variants:
                if (v.get("b9_moduleID") or "") == key:
                    label = (v.get("switcherDescription") or "").strip()
                    if label:
                        break
            if not label:
                # meshSwitchDome → Dome, meshSwitchRim → Rim
                label = key
                for prefix in ("meshSwitch", "textureSwitch", "switch", "mesh"):
                    if label.lower().startswith(prefix.lower()):
                        label = label[len(prefix) :]
                        break
                label = label or key
        out.append({"module_id": key, "label": label, "items": items})
    return out


def get_mesh_variant_items(scene, context):
    """Dropdown: first mesh switch group (or all if single group)."""
    groups = get_mesh_switch_groups(context=context)
    if not groups:
        return [("NONE", "(no mesh variants)", "")]
    items = list(groups[0]["items"])
    return items or [("NONE", "(no mesh variants)", "")]


def get_mesh_variant_2_items(scene, context):
    """Second independent mesh module (e.g. Rim)."""
    groups = get_mesh_switch_groups(context=context)
    if len(groups) < 2:
        return [("NONE", "(none)", "")]
    return list(groups[1]["items"]) or [("NONE", "(none)", "")]


def get_mesh_variant_3_items(scene, context):
    """Third independent mesh module."""
    groups = get_mesh_switch_groups(context=context)
    if len(groups) < 3:
        return [("NONE", "(none)", "")]
    return list(groups[2]["items"]) or [("NONE", "(none)", "")]


def get_mesh_variant_4_items(scene, context):
    """Fourth independent mesh module."""
    groups = get_mesh_switch_groups(context=context)
    if len(groups) < 4:
        return [("NONE", "(none)", "")]
    return list(groups[3]["items"]) or [("NONE", "(none)", "")]


def get_paint_variant_items(scene, context):
    """Dropdown: texture / paint switches only (independent of mesh)."""
    root = find_variant_root(
        getattr(context, "active_object", None) if context else None,
        context=context,
    )
    items = [("NONE", "(no paint variants)", "")]
    if root is None or MU_VARIANTS_KEY not in root:
        return items
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return items
    items = []
    inline = data.get("_loc_inline") or {}
    for v in data.get("variants") or []:
        if not _variant_is_paint_switch(v, data.get("variants") or []):
            continue
        name = v.get("name") or "?"
        bare = name.split("/")[-1] if "/" in name else name
        label = _variant_ui_label(v, root, inline)
        if v.get("b9") and label and len(label) > 28:
            label = bare
        if not label:
            label = bare
        items.append((name, label, "Paint / texture variant"))
    return items or [("NONE", "(no paint variants)", "")]


def _cfg_mu_identity_certain(cfg_path, text, muname, filepath_stem=None):
    """True when this .cfg is confidently the sibling of the imported .mu."""
    stems = []
    for src in (filepath_stem, muname):
        for s in _muname_match_stems(src):
            if s and s.lower() not in stems:
                stems.append(s.lower())
    if not stems or not text:
        return False
    cfg_stem = os.path.splitext(os.path.basename(cfg_path or ""))[0].lower()
    # Exact cfg basename ↔ mu stem (e.g. fuelTank.cfg + fuelTank.mu)
    if cfg_stem and cfg_stem != "part":
        for s in stems:
            sn = s.replace(".", "_").replace("p", "_")
            bn = cfg_stem.replace(".", "_").replace("p", "_")
            if sn == bn or sn == cfg_stem or cfg_stem == s:
                return True
    # Explicit mesh= / model= reference to this .mu stem
    for s in stems:
        esc = re.escape(s)
        if re.search(rf"^\s*mesh\s*=\s*.*{esc}\b", text, re.M | re.I):
            return True
        if re.search(rf"^\s*model\s*=\s*.*{esc}", text, re.M | re.I):
            return True
        # mesh = model when file is model.mu — still "certain" only if unique
        # handled via basename / PART name below when stems include "model"
    return False


def _cfg_collection_name(cfg_path, text):
    """Preferred Outliner collection name from a confidently matched .cfg."""
    cfg_stem = os.path.splitext(os.path.basename(cfg_path or ""))[0]
    if cfg_stem and cfg_stem.lower() != "part":
        return cfg_stem
    # Generic part.cfg — use PART { name = ... }
    part_m = re.search(r"PART\s*\{", text or "", re.I)
    if not part_m:
        return None
    rest = text[part_m.end():]
    nm = re.search(r"^\s*name\s*=\s*([^\r\n]+)", rest, re.M | re.I)
    if not nm:
        return None
    name = nm.group(1).strip().strip('"').split("//")[0].strip()
    return name or None


def _rename_import_collections(root, new_base):
    """Rename main / .vis / .collider hierarchy when name differs from .mu stem."""
    if root is None or not new_base:
        return
    leaf = None
    try:
        leaf = root.users_collection[0] if root.users_collection else None
    except Exception:
        leaf = None
    if leaf is None:
        return
    main = None
    old_base = None
    leaf_name = leaf.name or ""
    for suffix in (".vis", ".collider"):
        if leaf_name.endswith(suffix):
            old_base = leaf_name[: -len(suffix)]
            main = bpy.data.collections.get(old_base)
            break
    if main is None:
        # Walk parents of leaf in the collection tree
        for col in bpy.data.collections:
            if leaf.name in [c.name for c in col.children]:
                main = col
                old_base = col.name
                break
    if main is None:
        if leaf_name != new_base and new_base not in bpy.data.collections:
            try:
                leaf.name = new_base
            except Exception:
                pass
        return
    if old_base == new_base:
        return
    target = new_base
    n = 0
    while target in bpy.data.collections and bpy.data.collections[target] != main:
        n += 1
        target = f"{new_base}.{n:03d}"
    for child in list(main.children):
        cname = child.name or ""
        if old_base and cname == old_base + ".vis":
            try:
                child.name = target + ".vis"
            except Exception:
                pass
        elif old_base and cname == old_base + ".collider":
            try:
                child.name = target + ".collider"
            except Exception:
                pass
    try:
        main.name = target
    except Exception:
        pass



def _parse_cfg_model_blocks(cfg_text):
    """Parse PART → MODEL { model = … position/rotation/scale } blocks."""
    models = []
    if not cfg_text:
        return models
    for body in _parse_brace_blocks(cfg_text, "MODEL"):
        mm = re.search(r"^\s*model\s*=\s*(.+)$", body, re.M | re.I)
        if not mm:
            continue
        url = mm.group(1).strip().strip('"').split("//")[0].strip()
        if not url:
            continue
        entry = {
            "model": url,
            "position": (0.0, 0.0, 0.0),
            "rotation": (0.0, 0.0, 0.0),
            "scale": (1.0, 1.0, 1.0),
        }
        pm = re.search(
            r"^\s*position\s*=\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)",
            body, re.M | re.I,
        )
        if pm:
            try:
                # Unity Y-up → Blender Z-up
                ux, uy, uz = (float(pm.group(i)) for i in (1, 2, 3))
                entry["position"] = (ux, uz, uy)
            except Exception:
                pass
        rm = re.search(
            r"^\s*rotation\s*=\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)",
            body, re.M | re.I,
        )
        if rm:
            try:
                ux, uy, uz = (float(rm.group(i)) for i in (1, 2, 3))
                entry["rotation"] = (ux, uz, uy)
            except Exception:
                pass
        sm = re.search(
            r"^\s*scale\s*=\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)",
            body, re.M | re.I,
        )
        if sm:
            try:
                entry["scale"] = tuple(float(sm.group(i)) for i in (1, 2, 3))
            except Exception:
                pass
        else:
            sm1 = re.search(r"^\s*scale\s*=\s*([-\d.]+)\s*$", body, re.M | re.I)
            if sm1:
                try:
                    s = float(sm1.group(1))
                    entry["scale"] = (s, s, s)
                except Exception:
                    pass
        models.append(entry)
    return models


def _resolve_model_mu_path(model_url, mudir, cfg_path=None):
    """Resolve GameData-relative MODEL path to an on-disk .mu file."""
    if not model_url:
        return None
    url = model_url.replace("\\", "/").strip()
    if url.lower().endswith(".mu"):
        url = url[:-3]
    candidates = []
    # next to cfg / mudir
    for base in (mudir, os.path.dirname(cfg_path) if cfg_path else None):
        if not base:
            continue
        candidates.append(os.path.join(base, os.path.basename(url) + ".mu"))
        candidates.append(os.path.join(base, url.split("/")[-1] + ".mu"))
    # GameData root
    gd = None
    try:
        gd = _game_data_root(mudir)
    except Exception:
        gd = None
    if not gd and cfg_path:
        try:
            gd = _game_data_root(os.path.dirname(cfg_path))
        except Exception:
            pass
    if gd:
        candidates.append(os.path.join(gd, url + ".mu"))
        candidates.append(os.path.join(gd, url.replace("/", os.sep) + ".mu"))
    # walk parents looking for GameData-ish
    cur = mudir
    for _ in range(8):
        if not cur or not os.path.isdir(cur):
            break
        candidates.append(os.path.join(cur, os.path.basename(url) + ".mu"))
        parent = os.path.dirname(cur.rstrip("/\\"))
        if parent == cur:
            break
        cur = parent
    seen = set()
    for c in candidates:
        if not c:
            continue
        c = os.path.normpath(c)
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            return c
    return None


def _tag_secondary_model_tree(obj, model_url):
    """Mark hierarchy as viewport-only secondary MODEL (skipped on .mu export)."""
    if obj is None:
        return
    try:
        stack = [obj] + list(getattr(obj, "children_recursive", []) or [])
    except Exception:
        stack = [obj]
    leaf = (model_url or "").replace("\\", "/").split("/")[-1]
    for o in stack:
        try:
            o["mu_fx_preview"] = 1
            o["mu_secondary_model"] = 1
            o["mu_cfg_model"] = model_url or ""
            o["mu_cfg_model_leaf"] = leaf
        except Exception:
            pass



def _dedupe_materials_under(obj, suffix):
    """Force unique material datablocks for secondary MODEL isolation."""
    if obj is None:
        return
    try:
        stack = [obj] + list(getattr(obj, "children_recursive", []) or [])
    except Exception:
        stack = [obj]
    for o in stack:
        for slot in getattr(o, "material_slots", []) or []:
            mat = slot.material
            if mat is None:
                continue
            try:
                new_mat = mat.copy()
                try:
                    new_mat.name = (mat.name or "Mat")[:40] + suffix
                except Exception:
                    pass
                slot.material = new_mat
            except Exception:
                pass


def _find_part_main_collection(root):
    """Return the imported part main collection (parent of .vis / .collider)."""
    if root is None:
        return None
    cols = list(getattr(root, "users_collection", []) or [])
    for c in cols:
        name = c.name or ""
        if name.endswith(".vis") or name.endswith(".collider"):
            # climb to parent collection
            for parent in bpy.data.collections:
                if c.name in [ch.name for ch in parent.children]:
                    return parent
        # object linked directly to main
        for ch in c.children:
            if (ch.name or "").endswith(".vis"):
                return c
    for c in cols:
        return c
    return None


def _ensure_variants_collection(root):
    """Create main.variants under the part main collection (sibling of .vis/.collider).

    Isolated viewport-only models (extra MODEL blocks / B9 mesh subtypes).
    Export already skips mu_fx_preview — safe.
    """
    main = _find_part_main_collection(root)
    if main is None:
        # fallback: scene collection child
        name = "MU_VARIANTS"
        col = bpy.data.collections.get(name)
        if col is None:
            col = bpy.data.collections.new(name)
            try:
                bpy.context.scene.collection.children.link(col)
            except Exception:
                pass
        return col
    vname = (main.name or "part") + ".variants"
    existing = None
    for ch in main.children:
        if (ch.name or "") == vname or (ch.name or "").endswith(".variants"):
            existing = ch
            break
    if existing is not None:
        return existing
    col = bpy.data.collections.new(vname)
    try:
        main.children.link(col)
    except Exception:
        try:
            bpy.context.scene.collection.children.link(col)
        except Exception:
            pass
    return col


def _set_collection_exclude(col, exclude):
    """Exclude/include a collection from the view layer (Blender 3+ / 4+ / 5+)."""
    if col is None:
        return
    try:
        layer = bpy.context.view_layer.layer_collection
    except Exception:
        return

    found = [False]

    def _walk(lc):
        if lc.collection == col:
            try:
                lc.exclude = bool(exclude)
                found[0] = True
            except Exception:
                pass
            # Always recurse into children so nested secondary hierarchies
            # (part.variants / leaf / leaf.vis) are toggled together.
            for ch in lc.children:
                _walk(ch)
            return True
        for ch in lc.children:
            if _walk(ch):
                return True
        return False

    try:
        _walk(layer)
    except Exception as e:
        print("WARNING: collection exclude walk: %s" % e)
    if not found[0]:
        print(
            "WARNING: layer_collection not found for %r (exclude=%s)"
            % (getattr(col, "name", col), exclude)
        )


def _set_collection_tree_exclude(col, exclude):
    """Exclude/include *col* and every nested child collection in the view layer."""
    if col is None:
        return
    stack = [col]
    seen = set()
    while stack:
        c = stack.pop()
        if c is None or id(c) in seen:
            continue
        seen.add(id(c))
        _set_collection_exclude(c, exclude)
        try:
            stack.extend(list(c.children))
        except Exception:
            pass


def _iter_model_group_objects(root, leaf):
    """Yield objects belonging to a model group.

    leaf=None / '__primary__' → non-secondary objects under root.
    leaf=str → objects tagged mu_cfg_model_leaf matching leaf.
    """
    if root is None:
        return
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    leaf_l = (leaf or "").lower()
    primary = leaf is None or leaf_l in ("", "__primary__")
    for o in stack:
        if primary:
            if o.get("mu_secondary_model"):
                continue
            yield o
        else:
            if not o.get("mu_secondary_model"):
                continue
            ol = (o.get("mu_cfg_model_leaf") or "").lower()
            if ol == leaf_l:
                yield o


def _set_model_group_visible(root, visible_leaves):
    """Exclusive model-group visibility for multi-MODEL / B9 mesh switches.

    visible_leaves: set of leaf names and/or '__primary__'.
    Only those groups stay visible; others are hidden (overlay at same origin).
    """
    if root is None:
        return
    vis = {str(x).lower() for x in (visible_leaves or set())}
    if not vis:
        vis = {"__primary__"}
    leaves = set()
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    for o in stack:
        if o.get("mu_secondary_model"):
            leaf = (o.get("mu_cfg_model_leaf") or "").lower()
            if leaf:
                leaves.add(leaf)

    show_primary = "__primary__" in vis
    n_pri = 0
    # Prefer hierarchy walk; also sweep .vis collection for strays
    primary_objs = list(_iter_model_group_objects(root, "__primary__"))
    try:
        main = _find_part_main_collection(root)
        if main:
            for ch in main.children:
                if (ch.name or "").endswith(".vis"):
                    for o in ch.objects:
                        if o not in primary_objs and not o.get("mu_secondary_model"):
                            primary_objs.append(o)
    except Exception:
        pass
    for o in primary_objs:
        if o == root:
            continue
        if o.get("ksp_attach_node") or (o.name or "").startswith("MU_ATTACH"):
            continue
        if o.get("mu_fx_preview") and not o.get("mu_secondary_model"):
            continue
        # Do not undo B9 exclusive hides (TallDome on Standard, etc.)
        if show_primary and o.get("mu_b9_exclusive_hide"):
            continue
        try:
            _set_object_hide(o, not show_primary)
            n_pri += 1
        except Exception:
            pass

    n_sec = 0
    for leaf in leaves:
        show = leaf in vis
        for o in _iter_model_group_objects(root, leaf):
            try:
                _set_object_hide(o, not show)
                if show:
                    # ancestors (holder) must be visible
                    p = o.parent
                    g = 0
                    while p is not None and g < 24:
                        g += 1
                        try:
                            _set_object_hide(p, False)
                        except Exception:
                            pass
                        p = p.parent
                n_sec += 1
            except Exception:
                pass

    try:
        vcol = None
        main = _find_part_main_collection(root)
        if main:
            for ch in main.children:
                if (ch.name or "").endswith(".variants"):
                    vcol = ch
                    break
        any_sec = any(leaf in vis for leaf in leaves)
        if vcol is not None:
            # Secondary import creates nested main/vis/collider under .variants.
            # Un-exclude the WHOLE tree when any secondary leaf is active.
            if any_sec:
                _set_collection_tree_exclude(vcol, exclude=False)
                _vlog("INFO: .variants collection tree INCLUDE (%s)" % (vcol.name,))
            else:
                _set_collection_tree_exclude(vcol, exclude=True)
                _vlog("INFO: .variants collection tree EXCLUDE (%s)" % (vcol.name,))
        else:
            _vlog("WARNING: no .variants collection under main=%r" % (
                getattr(main, "name", None),))
    except Exception as e:
        _vlog("WARNING: variants collection toggle: %s" % e)

    # Hard fallback: if showing secondary, also link meshes into primary .vis
    # so they stay visible even when layer_collection exclude fails.
    if any(leaf != "__primary__" for leaf in vis):
        try:
            vis_col = None
            main = _find_part_main_collection(root)
            if main:
                for ch in main.children:
                    if (ch.name or "").endswith(".vis"):
                        vis_col = ch
                        break
            shown = 0
            for leaf in vis:
                if leaf == "__primary__":
                    continue
                for o in _iter_model_group_objects(root, leaf):
                    try:
                        _set_object_hide(o, False)
                        if vis_col is not None and o.name not in vis_col.objects:
                            vis_col.objects.link(o)
                        shown += 1
                    except Exception:
                        pass
            _vlog("INFO: secondary hard-unhide+link count=%d" % shown)
        except Exception as e:
            _vlog("WARNING: secondary hard-unhide: %s" % e)

    # Re-apply collider hide preference after any unhide
    try:
        hide_cols = _colliders_should_stay_hidden(root)
        if hide_cols:
            for o in (
                list(_iter_model_group_objects(root, "__primary__"))
                + [
                    o
                    for leaf in leaves
                    for o in _iter_model_group_objects(root, leaf)
                ]
            ):
                if _object_looks_like_collider(o):
                    _set_object_hide(o, True)
    except Exception as e:
        print("WARNING: rehide colliders: %s" % e)
    # Shroud / fairing: if Autohide or majority of primary shrouds hidden
    try:
        from ..tools.display import (
            _is_shroud_or_fairing_object,
            _set_object_hide as _disp_hide,
        )
    except Exception:
        _is_shroud_or_fairing_object = None
    if _is_shroud_or_fairing_object is not None:
        try:
            primary_sh = [
                o for o in _iter_model_group_objects(root, "__primary__")
                if _is_shroud_or_fairing_object(o)
            ]
            hide_sh = False
            if primary_sh:
                hide_sh = (
                    sum(1 for o in primary_sh if getattr(o, "hide_viewport", False))
                    >= (len(primary_sh) + 1) // 2
                )
            try:
                sc = bpy.context.scene
                if sc is not None and "mu_shrouds_hidden" in sc:
                    hide_sh = bool(sc["mu_shrouds_hidden"])
            except Exception:
                pass
            if hide_sh:
                for leaf in list(leaves) + ["__primary__"]:
                    for o in _iter_model_group_objects(root, leaf):
                        if _is_shroud_or_fairing_object(o):
                            _set_object_hide(o, True)
        except Exception as e:
            print("WARNING: rehide shrouds: %s" % e)

    print(
        "INFO: model groups visible=%s primary=%s sec_objs=%d pri_objs=%d leaf_paint_scope=ok"
        % (sorted(vis), show_primary, n_sec, n_pri)
    )


def _enabled_transforms_to_model_leaves(root, enabled_names, all_names):
    """Map B9 enabled transform names → model group leaves to show."""
    named = _index_named_objects(root)
    leaves = set()
    primary_base = (root.get("mu_cfg_model_leaf") or root.get("ksp_mu_name") or "").lower()
    for t in enabled_names or []:
        objs = _lookup_named(named, t)
        if not objs:
            # transform names the path itself as model leaf
            for a in _b9_name_aliases(t):
                al = a.lower().replace("(clone)", "")
                if primary_base and (al == primary_base or primary_base in al or al in primary_base):
                    leaves.add("__primary__")
                # match secondary leaf tags
                try:
                    stack = [root] + list(getattr(root, "children_recursive", []) or [])
                except Exception:
                    stack = [root]
                for o in stack:
                    ml = (o.get("mu_cfg_model_leaf") or "").lower()
                    if ml and (al == ml or ml in al or al in ml):
                        leaves.add(ml)
            continue
        for o in objs:
            if o.get("mu_secondary_model"):
                ml = (o.get("mu_cfg_model_leaf") or "").lower()
                if ml:
                    leaves.add(ml)
            else:
                leaves.add("__primary__")
    return leaves


def _load_secondary_models_from_cfg(root, cfg_text, mudir, cfg_path, primary_stem):
    """Import extra PART MODEL .mu files into an isolated ``.variants`` collection.

    Design (attach-points style, export-safe):
      • Primary .mu stays the only exportable hierarchy.
      • Extra MODEL blocks → children under ``main.variants / <leaf>``.
      • Tagged ``mu_fx_preview`` + ``mu_secondary_model`` (export skips).
      • Same origin as primary (no side-by-side duplicates).
      • Mesh B9 switches exclusivity via ``_set_model_group_visible``.
      • Not for editing — open that .mu alone to edit/export.
    """
    global _SECONDARY_MODEL_IMPORT
    if _SECONDARY_MODEL_IMPORT or root is None:
        return 0
    models = _parse_cfg_model_blocks(cfg_text)
    if len(models) <= 1:
        return 0

    primary_path = ""
    try:
        primary_path = os.path.normcase(os.path.abspath(root.get("ksp_mu_path") or ""))
    except Exception:
        primary_path = ""
    primary_base = ""
    if primary_path:
        primary_base = os.path.splitext(os.path.basename(primary_path))[0].lower()
    elif primary_stem:
        primary_base = os.path.splitext(str(primary_stem))[0].lower()
    try:
        if primary_base:
            root["mu_cfg_model_leaf"] = primary_base
            root["mu_cfg_model"] = primary_base
    except Exception:
        pass

    loaded_paths = set()
    if primary_path:
        loaded_paths.add(primary_path)

    variants_col = _ensure_variants_collection(root)
    loaded = 0
    from mathutils import Euler
    import math

    for entry in models:
        url = entry["model"]
        leaf = url.replace("\\", "/").split("/")[-1]
        leaf_l = leaf.lower()
        if primary_base and leaf_l == primary_base:
            _vlog(f"INFO: MODEL skip primary {leaf}")
            continue
        mu_path = _resolve_model_mu_path(url, mudir, cfg_path)
        if not mu_path:
            _vlog(f"WARNING: secondary MODEL not found on disk: {url}")
            continue
        abs_p = os.path.normcase(os.path.abspath(mu_path))
        if abs_p in loaded_paths or (primary_path and abs_p == primary_path):
            _vlog(f"INFO: MODEL skip already loaded {leaf}")
            continue

        # Sub-collection under .variants
        sub_name = leaf[:50]
        sub_col = None
        try:
            for ch in variants_col.children:
                if (ch.name or "") == sub_name:
                    sub_col = ch
                    break
            if sub_col is None:
                sub_col = bpy.data.collections.new(sub_name)
                variants_col.children.link(sub_col)
        except Exception:
            sub_col = variants_col

        _vlog(f"INFO: loading secondary MODEL {url} → {mu_path}")
        _SECONDARY_MODEL_IMPORT = True
        sec_root = None
        try:
            from .import_mu import import_mu as _import_mu
            sec_root, _mu = _import_mu(
                sub_col, mu_path, create_colliders=True, force_armature=False
            )
        except Exception as e:
            _vlog(f"WARNING: secondary MODEL import failed ({url}): {e}")
            sec_root = None
        finally:
            _SECONDARY_MODEL_IMPORT = False

        if sec_root is None:
            continue
        loaded_paths.add(abs_p)

        # Holder at PRIMARY origin — variants overlay, never sit side-by-side
        holder_name = leaf + "(Clone)"
        holder = None
        try:
            holder = bpy.data.objects.new(holder_name, None)
            holder.empty_display_type = "PLAIN_AXES"
            holder.empty_display_size = 0.02
            try:
                sub_col.objects.link(holder)
            except Exception:
                pass
            holder.parent = root
            # MODEL position from cfg (usually 0); keep at part origin
            holder.location = entry.get("position") or (0.0, 0.0, 0.0)
            try:
                holder.rotation_mode = "XYZ"
                rx, ry, rz = entry.get("rotation") or (0.0, 0.0, 0.0)
                holder.rotation_euler = Euler(
                    (math.radians(rx), math.radians(ry), math.radians(rz)), "XYZ"
                )
            except Exception:
                pass
            try:
                holder.scale = entry.get("scale") or (1.0, 1.0, 1.0)
            except Exception:
                pass
            holder["mu_fx_preview"] = 1
            holder["mu_secondary_model"] = 1
            holder["mu_cfg_model"] = url
            holder["mu_cfg_model_leaf"] = leaf
        except Exception as e:
            print(f"WARNING: secondary holder: {e}")
            holder = root

        try:
            sec_root.parent = holder if holder is not root else root
            # Zero local transform so mesh coincides with primary
            sec_root.location = (0.0, 0.0, 0.0)
            try:
                sec_root.rotation_euler = (0.0, 0.0, 0.0)
            except Exception:
                pass
            try:
                sec_root.matrix_parent_inverse.identity()
            except Exception:
                pass
        except Exception as e:
            print(f"WARNING: reparent secondary: {e}")

        # Move every secondary object into sub_col only (isolated)
        try:
            stack = [sec_root] + list(getattr(sec_root, "children_recursive", []) or [])
            if holder is not root:
                stack.insert(0, holder)
            for o in stack:
                if o is None:
                    continue
                for c in list(getattr(o, "users_collection", []) or []):
                    try:
                        if c != sub_col:
                            c.objects.unlink(o)
                    except Exception:
                        pass
                try:
                    if o.name not in sub_col.objects:
                        sub_col.objects.link(o)
                except Exception:
                    pass
        except Exception as e:
            print(f"WARNING: secondary collection isolate: {e}")

        try:
            _dedupe_materials_under(sec_root, ".sec_" + leaf[:12])
        except Exception:
            pass
        _tag_secondary_model_tree(holder if holder is not root else sec_root, url)
        _tag_secondary_model_tree(sec_root, url)
        try:
            sec_root["mu_secondary_model"] = 1
            sec_root["mu_fx_preview"] = 1
            sec_root["ksp_mu_path"] = abs_p
            sec_root["mu_cfg_model_leaf"] = leaf
        except Exception:
            pass

        # Start hidden — primary is default until B9 switches
        try:
            for o in stack:
                _set_object_hide(o, True)
        except Exception:
            pass

        loaded += 1
        _vlog(f"INFO: secondary hierarchy root={sec_root.name!r} leaf={leaf}")

    if loaded:
        _vlog(f"INFO: secondary MODEL(s) loaded: {loaded} (isolated in .variants, export skips)")
        try:
            root["mu_secondary_models"] = loaded
        except Exception:
            pass
        # Cache stock textures for secondary materials too (paint restore)
        try:
            if MU_VARIANTS_KEY in root:
                data = json.loads(root[MU_VARIANTS_KEY])
                _ensure_default_textures_cached(root, data)
                root[MU_VARIANTS_KEY] = json.dumps(data)
        except Exception as e:
            print(f"WARNING: secondary texture cache: {e}")
        # Default visibility: primary only (force unhide primary meshes)
        try:
            _set_model_group_visible(root, {"__primary__"})
        except Exception as e:
            print(f"WARNING: default model visibility: {e}")
        try:
            for o in _iter_model_group_objects(root, "__primary__"):
                if o == root:
                    continue
                if o.get("mu_secondary_model"):
                    continue
                _set_object_hide(o, False)
        except Exception:
            pass
        try:
            if MU_VARIANTS_KEY in root:
                data = json.loads(root[MU_VARIANTS_KEY])
                active_modules = dict(data.get("active_modules") or {})
                for v in data.get("variants") or []:
                    if not v.get("b9"):
                        continue
                    mid = v.get("b9_moduleID") or ""
                    if mid and mid not in active_modules:
                        bare = (v.get("name") or "").split("/")[-1]
                        active_modules[mid] = bare
                if active_modules:
                    data["active_modules"] = active_modules
                    root[MU_VARIANTS_KEY] = json.dumps(data)
                active = data.get("active") or data.get("base")
                if not active and data.get("variants"):
                    active = data["variants"][0].get("name")
                if active:
                    apply_variant(root, active)
        except Exception as e:
            _vlog(f"WARNING: re-apply variant after secondary MODEL: {e}")
    return loaded




# Theme suffixes ReStock / Squad use on parallel meshes in one .mu
# Compound themes MUST be longer than simple ones (BlackWhite before White).
_HIERARCHY_THEME_SUFFIXES = (
    # Compound surface themes (VariantThemes / ReStock mesh names)
    "BlackAndWhite", "BlackWhite", "GrayAndOrange", "GreyAndOrange",
    "GrayAndWhite", "GreyAndWhite", "YellowAndWhite", "GrayWithStripes",
    "GreyWithStripes", "BlackAndOrange", "WhiteAndBlack",
    # Simple themes
    "White", "Metal", "Orange", "Grey", "Gray", "Dark", "Gold", "Silver",
    "Bare", "Black", "Shroud", "Yellow", "Brown", "Green", "Blue", "Red",
    "Camo", "Stripe", "Stripes", "Foil", "Blankets", "Blank",
)

# Engine-cluster / mount count suffixes: 5mMountSaturnX3 / X4 / X7
_HIERARCHY_COUNT_RE = re.compile(
    r"^(?P<head>.+?)(?P<token>X\d+|\d+x|\d+X)$", re.I
)

# Theme residual for sibling common-prefix grouping (5mSmall + BlackWhite/Orange)
_HIERARCHY_THEME_SET = frozenset(
    s.lower() for s in _HIERARCHY_THEME_SUFFIXES
)


def _hierarchy_split_variant_token(plain):
    """Split ``5mSmallBlackWhite`` / ``ConeSphere1875White`` / ``…X7`` → (prefix, label)."""
    if not plain or len(plain) < 3:
        return None
    # 1) Color / surface themes (longest suffix first — BlackWhite before White)
    for suf in sorted(_HIERARCHY_THEME_SUFFIXES, key=len, reverse=True):
        if plain.endswith(suf) and len(plain) > len(suf):
            head = plain[: -len(suf)]
            if head and (
                head[-1].isdigit()
                or head[-1] in "_-"
                or head[-1].islower()
                or head[-1].isupper()  # 5mSmall + BlackWhite
            ):
                return head, suf
    # 2) Count / cluster tokens: X3, X4, 3x, 7X
    m = _HIERARCHY_COUNT_RE.match(plain)
    if m:
        head = m.group("head")
        token = m.group("token")
        if head and len(head) >= 2 and len(token) >= 2:
            tl = token.lower()
            if tl.endswith("x") and tl[:-1].isdigit():
                label = "X" + tl[:-1]
            elif tl.startswith("x") and tl[1:].isdigit():
                label = "X" + tl[1:]
            else:
                label = token.upper()
            return head, label
    return None


def _hierarchy_groups_from_siblings(root):
    """Fallback: siblings under one parent sharing a long common prefix.

    Example under ``Size4_Tank_02``:
      5mSmallBlackWhite, 5mSmallOrange → prefix 5mSmall, labels BlackWhite/Orange
    """
    groups = {}
    if root is None:
        return groups
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    # parent_ptr → [plain names]
    by_parent = {}
    for o in stack:
        if o is root:
            continue
        try:
            plain = (o.name or "").split("∧")[0].split(".")[0].strip()
        except Exception:
            continue
        if not plain:
            continue
        nl = plain.lower()
        if nl.startswith("node_") or nl.startswith("mu_attach"):
            continue
        if "collider" in nl or nl.startswith("col"):
            continue
        try:
            pkey = o.parent.as_pointer() if o.parent else 0
        except Exception:
            pkey = id(o.parent) if o.parent else 0
        by_parent.setdefault(pkey, []).append(plain)

    for plain_list in by_parent.values():
        names = sorted(set(plain_list))
        if len(names) < 2:
            continue
        # Common prefix length
        a, b = names[0], names[-1]
        i = 0
        while i < len(a) and i < len(b) and a[i] == b[i]:
            i += 1
        # Also check all names share this prefix
        prefix = a[:i]
        while prefix and not all(n.startswith(prefix) for n in names):
            prefix = prefix[:-1]
        if len(prefix) < 3:
            continue
        # Residuals = theme tokens; empty residual = base "Stock"
        # (Tank0625_16 + Tank0625_16_White share prefix Tank0625_16).
        tmap = {}
        ok = True
        for n in names:
            residual = n[len(prefix):]
            if residual.startswith("_") or residual.startswith("-"):
                residual = residual[1:]
            if not residual:
                residual = "Stock"
            elif len(residual) < 2:
                ok = False
                break
            # Accept known theme, Stock, or CamelCase residual
            if (
                residual == "Stock"
                or residual.lower() in _HIERARCHY_THEME_SET
                or residual[0].isupper()
            ):
                tmap[residual] = n
            else:
                ok = False
                break
        if ok and len(tmap) >= 2:
            groups.setdefault(prefix, {}).update(tmap)
    return groups



def _discover_paint_cfg_files(mudir, part_name=None):
    """Find ModuleManager paint patch .cfg near the part (Paint/ folders)."""
    import os
    found = []
    if not mudir or not os.path.isdir(mudir):
        return found
    candidates = []
    for base in (mudir, os.path.dirname(mudir)):
        if not base or not os.path.isdir(base):
            continue
        paint_dir = os.path.join(base, "Paint")
        if os.path.isdir(paint_dir):
            for root, _dirs, files in os.walk(paint_dir):
                for f in files:
                    if f.lower().endswith(".cfg"):
                        candidates.append(os.path.join(root, f))
        # Loose *paint*.cfg in the part folder
        try:
            for f in os.listdir(base):
                fl = f.lower()
                if fl.endswith(".cfg") and "paint" in fl:
                    candidates.append(os.path.join(base, f))
        except Exception:
            pass
    # de-dupe preserve order
    seen = set()
    for p in candidates:
        ap = os.path.normpath(p)
        if ap not in seen:
            seen.add(ap)
            found.append(ap)
    return found


def _parse_mm_b9_subtype_patches(cfg_text, part_name):
    """Parse @PART[name] … @MODULE[ModuleB9PartSwitch] SUBTYPE / %SUBTYPE blocks.

    Returns list of dicts:
      {moduleID, subtype_name, transforms, textures, primaryColor, secondaryColor}
    """
    if not cfg_text or not part_name:
        return []
    import re
    out = []
    part_l = part_name.lower()
    # Split on @PART[ … ] roughly
    for pm in re.finditer(
        r"@PART\[([^\]]+)\][^{]*\{", cfg_text, re.I
    ):
        selectors = pm.group(1)
        # Match part name in selector list (wildcards * ?)
        matched = False
        for sel in selectors.split(","):
            sel = sel.strip().split(":")[0].strip()
            if not sel:
                continue
            # wildcard
            if "*" in sel or "?" in sel:
                import fnmatch
                if fnmatch.fnmatch(part_name, sel) or fnmatch.fnmatch(part_l, sel.lower()):
                    matched = True
                    break
            elif sel.lower() == part_l:
                matched = True
                break
        if not matched:
            continue
        # Extract brace body of this @PART
        start = pm.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        part_body = cfg_text[start + 1 : i]
        # Find @MODULE[ModuleB9PartSwitch] with optional HAS[#moduleID[...]]
        for mm in re.finditer(
            r"@MODULE\[ModuleB9PartSwitch\]([^{]*)\{", part_body, re.I
        ):
            has = mm.group(1) or ""
            mid = None
            hm = re.search(r"#moduleID\[([^\]]+)\]", has, re.I)
            if hm:
                mid = hm.group(1).strip()
            mstart = mm.end() - 1
            depth = 0
            j = mstart
            while j < len(part_body):
                if part_body[j] == "{":
                    depth += 1
                elif part_body[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            mod_body = part_body[mstart + 1 : j]
            # SUBTYPE { } and %SUBTYPE[Name] { }
            for sm in re.finditer(
                r"(?:%?SUBTYPE(?:\[([^\]]+)\])?)\s*\{", mod_body, re.I
            ):
                sname_bracket = sm.group(1)
                sstart = sm.end() - 1
                depth = 0
                k = sstart
                while k < len(mod_body):
                    if mod_body[k] == "{":
                        depth += 1
                    elif mod_body[k] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                sbody = mod_body[sstart + 1 : k]
                nm = re.search(r"^\s*name\s*=\s*(.+)$", sbody, re.M | re.I)
                sname = (
                    nm.group(1).strip().strip('"').split("//")[0].strip()
                    if nm
                    else (sname_bracket or "").strip()
                )
                if not sname:
                    continue
                # Top-level transform= only (not TEXTURE { transform = } filters)
                transforms = []
                sbody_mesh = sbody
                for nest_kw in ("TEXTURE", "NODE", "MATERIAL", "TRANSFORM"):
                    for nb in list(_parse_brace_blocks(sbody, nest_kw)):
                        sbody_mesh = sbody_mesh.replace(nb, "")
                for line in sbody_mesh.splitlines():
                    line = line.strip()
                    if re.match(r"(?i)^transform\s*=", line):
                        _, _, v = line.partition("=")
                        t = v.strip().split("//")[0].strip().strip('"')
                        if t:
                            transforms.append(t)
                textures = []
                for tbody in _parse_brace_blocks(sbody, "TEXTURE"):
                    def gv(key, b=tbody):
                        m = re.search(
                            r"^\s*%s\s*=\s*(.+)$" % key, b, re.M | re.I
                        )
                        return (
                            m.group(1).strip().strip('"').split("//")[0].strip()
                            if m
                            else None
                        )
                    tr = gv("transform")
                    btr = gv("baseTransform")
                    textures.append(
                        {
                            "texture": gv("texture"),
                            "currentTexture": gv("currentTexture"),
                            "shaderProperty": gv("shaderProperty"),
                            "isNormalMap": (gv("isNormalMap") or "").lower()
                            in ("true", "1", "yes"),
                            "transform": tr,
                            "transforms": [tr] if tr else [],
                            "baseTransform": btr,
                            "baseTransforms": [btr] if btr else [],
                        }
                    )
                def gv2(key):
                    m = re.search(
                        r"^\s*%s\s*=\s*(.+)$" % key, sbody, re.M | re.I
                    )
                    return (
                        m.group(1).strip().strip('"').split("//")[0].strip()
                        if m
                        else None
                    )
                out.append(
                    {
                        "moduleID": mid or "B9",
                        "subtype_name": sname,
                        "transforms": transforms,
                        "textures": [t for t in textures if t.get("texture")],
                        "primaryColor": gv2("primaryColor"),
                        "secondaryColor": gv2("secondaryColor"),
                    }
                )
    return out


def merge_mm_paint_into_variants(info, mudir, part_name):
    """Merge Paint/**/paint.cfg MM patches into parsed B9 variant info."""
    if not info or not mudir or not part_name:
        return info
    files = _discover_paint_cfg_files(mudir, part_name)
    if not files:
        return info
    patches = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
        except Exception:
            continue
        patches.extend(_parse_mm_b9_subtype_patches(txt, part_name))
    if not patches:
        return info
    variants = list(info.get("variants") or [])
    # Index existing by moduleID/subtype and bare subtype
    by_key = {}
    for i, v in enumerate(variants):
        name = v.get("name") or ""
        by_key[name.lower()] = i
        bare = name.split("/")[-1].lower()
        by_key.setdefault(bare, i)
        mid = (v.get("b9_moduleID") or "").lower()
        if mid:
            by_key[("%s/%s" % (mid, bare)).lower()] = i

    added = 0
    merged_tex = 0
    for p in patches:
        mid = p.get("moduleID") or "B9"
        sname = p.get("subtype_name") or ""
        keys = [
            ("%s/%s" % (mid, sname)).lower(),
            sname.lower(),
        ]
        idx = None
        for k in keys:
            if k in by_key:
                idx = by_key[k]
                break
        if idx is not None:
            entry = variants[idx]
            # Merge textures
            existing = list(entry.get("b9_textures") or [])
            have = {
                (
                    (t.get("texture") or ""),
                    (t.get("transform") or ""),
                    (t.get("shaderProperty") or ""),
                )
                for t in existing
            }
            for t in p.get("textures") or []:
                key = (
                    (t.get("texture") or ""),
                    (t.get("transform") or ""),
                    (t.get("shaderProperty") or ""),
                )
                if key not in have:
                    existing.append(t)
                    have.add(key)
                    merged_tex += 1
            entry["b9_textures"] = existing
            # Flat map
            flat = dict(entry.get("textures") or {})
            for td in existing:
                slot = td.get("shaderProperty") or (
                    "_BumpMap" if td.get("isNormalMap") else "_MainTex"
                )
                url = td.get("texture")
                if url and slot not in flat:
                    flat[slot] = url
                    if slot == "_MainTex":
                        flat["mainTextureURL"] = url
            entry["textures"] = flat
            if p.get("transforms"):
                objs = dict(entry.get("objects") or {})
                for t in p["transforms"]:
                    objs[t] = True
                if objs:
                    entry["objects"] = objs
                    entry["toggle_keys"] = list(
                        dict.fromkeys(
                            list(entry.get("toggle_keys") or [])
                            + list(objs.keys())
                        )
                    )
            if p.get("primaryColor"):
                entry["primaryColor"] = p["primaryColor"]
            if p.get("secondaryColor"):
                entry["secondaryColor"] = p["secondaryColor"]
        else:
            # New subtype from MM
            b9_tex = list(p.get("textures") or [])
            flat = {}
            for td in b9_tex:
                slot = td.get("shaderProperty") or (
                    "_BumpMap" if td.get("isNormalMap") else "_MainTex"
                )
                url = td.get("texture")
                if url and slot not in flat:
                    flat[slot] = url
                    if slot == "_MainTex":
                        flat["mainTextureURL"] = url
            objects = {}
            for t in p.get("transforms") or []:
                objects[t] = True
            enum_name = "%s/%s" % (mid, sname)
            # Prefer short name if only one paint module
            entry = {
                "name": enum_name,
                "displayName": sname,
                "objects": objects,
                "toggle_keys": list(objects.keys()),
                "textures": flat,
                "b9_textures": b9_tex,
                "b9": True,
                "b9_moduleID": mid,
                "nodes": {},
                "transform_ops": [],
                "mm_paint": True,
            }
            if p.get("primaryColor"):
                entry["primaryColor"] = p["primaryColor"]
            if p.get("secondaryColor"):
                entry["secondaryColor"] = p["secondaryColor"]
            variants.append(entry)
            by_key[enum_name.lower()] = len(variants) - 1
            by_key[sname.lower()] = len(variants) - 1
            added += 1
    if added or merged_tex:
        info = dict(info)
        info["variants"] = variants
        # Recompute kind
        has_obj = any((v.get("objects") or {}) for v in variants)
        has_tex = any(
            (v.get("b9_textures") or v.get("textures")) for v in variants
        )
        info["kind"] = (
            "both" if (has_obj and has_tex) else ("texture" if has_tex else "model")
        )
        _vlog(
            "INFO: MM paint patches merged for %s: +%d subtypes, %d textures (%d files)"
            % (part_name, added, merged_tex, len(files))
        )
    return info


def _apply_shabby_material_hints(root, mudir, part_name):
    """Parse nearby SHABBY_MATERIAL_DEF / REPLACE — store metalness hints on mats.

    Full Shabby/Deferred shader rebuild is out of scope; we only tag materials
    so Tools / future viewport can pick up _Metalness multipliers.
    """
    import os, re
    if not mudir or not os.path.isdir(mudir):
        return 0
    defs = {}  # name → {float props}
    replaces = []  # {materialDef, targets[]}
    files = []
    for base in (mudir, os.path.dirname(mudir)):
        if not base or not os.path.isdir(base):
            continue
        try:
            for f in os.listdir(base):
                if f.lower().endswith(".cfg") and (
                    "material" in f.lower() or f.startswith("000_")
                ):
                    files.append(os.path.join(base, f))
        except Exception:
            pass
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
        except Exception:
            continue
        for body in _parse_brace_blocks(txt, "SHABBY_MATERIAL_DEF"):
            nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
            if not nm:
                continue
            dname = nm.group(1).strip().strip('"')
            floats = {}
            for fb in _parse_brace_blocks(body, "FLOAT"):
                for line in fb.splitlines():
                    line = line.strip()
                    if "=" in line and not line.startswith("//"):
                        k, _, v = line.partition("=")
                        try:
                            floats[k.strip()] = float(v.strip().split("//")[0])
                        except Exception:
                            pass
            defs[dname] = floats
        for body in _parse_brace_blocks(txt, "SHABBY_MATERIAL_REPLACE"):
            md = re.search(r"^\s*materialDef\s*=\s*(.+)$", body, re.M | re.I)
            if not md:
                continue
            targets = re.findall(
                r"^\s*targetMaterial\s*=\s*(.+)$", body, re.M | re.I
            )
            replaces.append(
                {
                    "materialDef": md.group(1).strip().strip('"'),
                    "targets": [
                        t.strip().strip('"').split("//")[0].strip()
                        for t in targets
                    ],
                }
            )
        # Also @PART-scoped replaces: scan for SHABBY_MATERIAL_REPLACE inside
        for body in re.findall(
            r"SHABBY_MATERIAL_REPLACE\s*\{([^}]*)\}", txt, re.I | re.S
        ):
            md = re.search(r"^\s*materialDef\s*=\s*(.+)$", body, re.M | re.I)
            if not md:
                continue
            targets = re.findall(
                r"^\s*targetMaterial\s*=\s*(.+)$", body, re.M | re.I
            )
            replaces.append(
                {
                    "materialDef": md.group(1).strip().strip('"'),
                    "targets": [
                        t.strip().strip('"').split("//")[0].strip()
                        for t in targets
                    ],
                }
            )
    if not replaces and not defs:
        return 0
    # Tag matching Blender materials under root
    tagged = 0
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    mats = set()
    for o in stack:
        for slot in getattr(o, "material_slots", []) or []:
            if slot.material:
                mats.add(slot.material)
    target_map = {}
    for r in replaces:
        dname = r.get("materialDef")
        props = defs.get(dname) or {}
        for t in r.get("targets") or []:
            target_map[t.lower()] = (dname, props)
    for mat in mats:
        ml = (mat.name or "").lower()
        # strip .001
        base = ml.split(".")[0]
        hit = target_map.get(ml) or target_map.get(base)
        if not hit:
            for tk, val in target_map.items():
                if tk in ml or ml in tk:
                    hit = val
                    break
        if not hit:
            continue
        dname, props = hit
        try:
            mat["mu_shabby_def"] = dname
            for k, v in props.items():
                mat["mu_shabby_%s" % k] = v
            tagged += 1
        except Exception:
            pass
    if tagged:
        _vlog("INFO: Shabby material hints tagged: %d" % tagged)
    return tagged


def synthesize_variants_from_hierarchy(root):
    """Build ModulePartVariants-like info from parallel meshes in a .mu.

    Covers:
      • ``ConeSphere1875White`` / ``Metal`` / ``Orange``
      • ``5mSmallBlackWhite`` / ``5mSmallOrange`` (compound themes)
      • ``5mMountSaturnX3`` / ``X4`` / ``X7``
      • sibling common-prefix groups under one parent

    Used when cfg is missing or has no ModulePartVariants.
    """
    if root is None:
        return None
    try:
        stack = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        stack = [root]
    by_plain = {}
    for o in stack:
        if o is root:
            continue
        try:
            n = (o.name or "").split("∧")[0].split(".")[0].strip()
        except Exception:
            continue
        if not n:
            continue
        nl = n.lower()
        if nl.startswith("node_") or nl.startswith("mu_attach"):
            continue
        if "collider" in nl or nl.startswith("col"):
            continue
        by_plain.setdefault(n, []).append(o)

    groups = {}  # prefix → {label: object_name}
    for plain in by_plain:
        split = _hierarchy_split_variant_token(plain)
        if not split:
            continue
        prefix, label = split
        groups.setdefault(prefix, {})[label] = plain

    # Pair themed meshes with bare base (Tank0625_16_White → prefix
    # Tank0625_16_ / Tank0625_16 + object Tank0625_16 as Stock).
    for prefix, tmap in list(groups.items()):
        if any(v in by_plain for v in tmap.values()) and "Stock" not in tmap:
            for cand in (
                prefix,
                prefix.rstrip("_-"),
                prefix.rstrip("_-") + "_",
            ):
                if cand and cand in by_plain and cand not in tmap.values():
                    tmap.setdefault("Stock", cand)
                    break

    # Sibling fallback (and merge larger groups)
    try:
        for prefix, tmap in _hierarchy_groups_from_siblings(root).items():
            if len(tmap) >= 2:
                cur = groups.setdefault(prefix, {})
                for lab, name in tmap.items():
                    cur.setdefault(lab, name)
    except Exception:
        pass

    best_prefix = None
    best_map = {}
    for prefix, tmap in groups.items():
        if len(tmap) >= 2 and len(tmap) > len(best_map):
            best_prefix = prefix
            best_map = tmap
    if not best_map or len(best_map) < 2:
        return None

    if not best_map or len(best_map) < 2:
        return None

    all_names = list(best_map.values())
    variants = []
    # Default preference: color themes first, else lowest count (X3 before X7)
    order = list(best_map.keys())
    preferred_colors = (
        "Stock", "Default", "White", "BlackWhite", "BlackAndWhite",
        "Metal", "Grey", "Gray", "Orange",
    )
    if any(p in best_map for p in preferred_colors):
        order = [p for p in preferred_colors if p in best_map] + [
            t for t in order if t not in preferred_colors
        ]
    else:
        def _sort_key(lab):
            m = re.match(r"^X?(\d+)$", str(lab), re.I)
            return (0, int(m.group(1))) if m else (1, str(lab))
        order = sorted(order, key=_sort_key)

    base = None
    for theme in order:
        oname = best_map[theme]
        objects = {n: (n == oname) for n in all_names}
        # Friendly label for counts: "X7" → "7 mounts"
        disp = theme
        cm = re.match(r"^X(\d+)$", str(theme), re.I)
        if cm:
            disp = "%s mounts" % cm.group(1)
        elif str(theme).lower() in ("stock", "default"):
            disp = "Default"
        elif str(theme).lower() in ("blackwhite", "blackandwhite"):
            disp = "Black and White"
        elif str(theme).lower() in ("grayandorange", "greyandorange"):
            disp = "Gray and Orange"
        entry = {
            "name": theme,
            "displayName": disp,
            "themeName": theme,
            "objects": objects,
            "toggle_keys": list(all_names),
            "textures": {},
            "texture_blocks": [],
            "disabledAnimations": [],
            "inferred": True,
        }
        variants.append(entry)
        if base is None:
            base = theme
    _vlog(
        "INFO: inferred %d mesh variants from hierarchy prefix=%r themes=%s"
        % (len(variants), best_prefix, list(best_map.keys()))
    )
    return {
        "base": base,
        "active": base,
        "kind": "model",
        "variants": variants,
        "source": "hierarchy",
    }


def attach_cfg_viewport_markers(root, mudir, muname, filepath_stem=None):
    """Add CoM / CoP / CoL empties + apply default part variant."""
    # Secondary MODEL imports are mesh-only (viewport FX). Never attach a
    # sibling part.cfg — shared folders (DeltaK/) pick random PART and wipe
    # textures / variants on the primary.
    if _SECONDARY_MODEL_IMPORT or (root is not None and root.get("mu_secondary_model")):
        return
    cfg = _find_part_cfg(mudir, muname, filepath_stem=filepath_stem)
    if root is None:
        return
    if not cfg:
        # Still try hierarchy-inferred variants (ReStock multi-mesh .mu without matched cfg)
        try:
            inferred = synthesize_variants_from_hierarchy(root)
            if inferred and inferred.get("variants"):
                root[MU_VARIANTS_KEY] = __import__("json").dumps(inferred)
                base = inferred.get("base") or inferred["variants"][0].get("name")
                if base:
                    apply_variant(root, base)
                _vlog("INFO: no part.cfg matched — using hierarchy-inferred variants")
        except Exception as e:
            _vlog(f"WARNING: hierarchy variants without cfg: {e}")
        return
    try:
        root["mu_dirname"] = mudir or os.path.dirname(cfg)
        root["mu_cfg_path"] = cfg
    except Exception:
        pass
    try:
        text = open(cfg, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return
    # Preload GameData localization (en-us) for #autoLOC / #LOC variant labels
    try:
        from .ksp_loc import load_localization_from_gamedata, gamedata_from_root
        gd = gamedata_from_root(root)
        if gd:
            load_localization_from_gamedata(gd, lang="en-us")
    except Exception:
        pass
    # Full .cfg tree — every parameter stored (coverage report / round-trip)
    try:
        from .cfg_store import attach_full_cfg_tree
        attach_full_cfg_tree(root, cfg, text=text)
    except Exception as e:
        print(f"WARNING: full cfg tree: {e}")
    # When cfg↔mu identity is certain, rename Outliner collections from the
    # .mu stem (often "model") to the cfg basename / PART name.
    try:
        if _cfg_mu_identity_certain(cfg, text, muname, filepath_stem):
            col_name = _cfg_collection_name(cfg, text)
            if col_name:
                _rename_import_collections(root, col_name)
    except Exception as e:
        print(f"WARNING: cfg collection rename: {e}")
    col = root.users_collection[0] if root.users_collection else bpy.context.scene.collection
    for key, disp, size, rgba in (
        ("CoMOffset", "SPHERE", 0.12, (1.0, 0.35, 0.1, 1.0)),
        ("CoPOffset", "CIRCLE", 0.12, (0.2, 0.6, 1.0, 1.0)),
        ("CoLOffset", "CONE", 0.12, (0.3, 1.0, 0.4, 1.0)),
    ):
        m = re.search(rf"^\s*{key}\s*=\s*(.+)$", text, re.M | re.I)
        if not m:
            continue
        loc = _parse_vec3(m.group(1))
        if loc is None:
            continue
        _make_marker(
            col, root, f"{root.name}.{key}{_CFG_PREVIEW_SUFFIX}",
            loc, display=disp, size=size, color=rgba,
        )
    for o in list(bpy.data.objects):
        n = (o.name or "").lower()
        if any(k in n for k in ("thrusttransform", "fxtransform", "thrust_transform")):
            try:
                if o.type == "EMPTY":
                    o.empty_display_type = "SINGLE_ARROW"
                    o.empty_display_size = max(0.2, o.empty_display_size)
            except Exception:
                pass
    info = parse_part_variants(text)
    # No ModulePartVariants in cfg (or cfg mismatch): infer from .mu hierarchy
    # (ReStock White/Metal/Orange parallel meshes).
    if not info or not (info.get("variants") or []):
        try:
            inferred = synthesize_variants_from_hierarchy(root)
            if inferred and inferred.get("variants"):
                info = inferred
        except Exception as e:
            _vlog(f"WARNING: hierarchy variant infer: {e}")
    # B9PartSwitch must feed the same Options -> Part Variant enum as
    # ModulePartVariants.  attach_cfg_viewport_markers() is the normal import
    # path, while apply_part_cfg_preview() is only the explicit cfg-preview
    # harness.  Without this merge the B9 parser exists, but its SUBTYPEs are
    # never stored in MU_VARIANTS_KEY during a normal .mu import.
    if "ModuleB9PartSwitch" in text:
        try:
            b9mods = parse_b9_part_switch(text)
            b9info = b9_to_variant_info(b9mods)
            if b9info and b9info.get("variants"):
                b9_has_xform = any(
                    (v.get("objects") or {})
                    and any(bool(x) for x in (v.get("objects") or {}).values())
                    for v in b9info["variants"]
                )
                # Hierarchy-inferred White/Metal must NOT outrank real B9
                # transform switchers (Agena Avionics Gray/GATV/Split).
                if info is None or (
                    b9_has_xform
                    and (info.get("source") or "") in ("hierarchy", "", None)
                ):
                    info = b9info
                elif b9_has_xform and not any(
                    (v.get("objects") or {})
                    and any(bool(x) for x in (v.get("objects") or {}).values())
                    for v in (info.get("variants") or [])
                ):
                    info = b9info
                else:
                    existing = {
                        v.get("name") for v in info.get("variants") or []
                    }
                    for v in b9info["variants"]:
                        if v.get("name") not in existing:
                            info.setdefault("variants", []).append(v)
                    # Prefer B9 base when it is a transform subtype
                    if b9_has_xform and b9info.get("base"):
                        info["base"] = b9info["base"]
        except Exception as e:
            _vlog(f"WARNING: B9PartSwitch attach parse: {e}")
    # ModuleManager Paint/**/paint.cfg patches (Bluedog/Agena style)
    try:
        pname = None
        if cfg:
            try:
                with open(cfg, "r", encoding="utf-8", errors="ignore") as _fh:
                    _ct = _fh.read(8192)
                import re as _re
                _m = _re.search(
                    r"^\s*name\s*=\s*(\S+)", _ct, _re.M | _re.I
                )
                if _m:
                    pname = _m.group(1).strip().strip('"')
            except Exception:
                pass
        pname = pname or filepath_stem or muname
        if info is None:
            info = {
                "base": None,
                "variants": [],
                "kind": "texture",
                "source": "MM_paint",
            }
        info = merge_mm_paint_into_variants(info, mudir, pname)
        if info and not info.get("variants"):
            if info.get("source") == "MM_paint":
                info = None
    except Exception as e:
        _vlog(f"WARNING: MM paint merge: {e}")
    if info:
        root[MU_VARIANTS_KEY] = json.dumps(info)
        # Snapshot stock _MainTex names before any VARIANT TEXTURE apply.
        try:
            data = json.loads(root[MU_VARIANTS_KEY])
            _ensure_default_textures_cached(root, data)
            root[MU_VARIANTS_KEY] = json.dumps(data)
        except Exception:
            pass
        base = pick_viable_base_variant(root, info) or info.get("base")
        if not base and info.get("variants"):
            base = info["variants"][0]["name"]
        if base:
            apply_variant(root, base)
        # Sync Options enum to default variant
        try:
            scene = bpy.context.scene
            if hasattr(scene, "mu_active_variant"):
                scene.mu_active_variant = base
        except Exception:
            pass
    jettison = parse_module_jettison_names(text)
    if jettison:
        try:
            root[MU_JETTISON_KEY] = json.dumps(
                [str(n).lower() for n in jettison]
            )
        except Exception:
            pass
        # Also embed in mu_variants so GIF/PNG helpers that only read that
        # blob still see ModuleJettison covers.
        try:
            if MU_VARIANTS_KEY in root:
                data = json.loads(root[MU_VARIANTS_KEY])
                data["jettisonNames"] = [str(n).lower() for n in jettison]
                root[MU_VARIANTS_KEY] = json.dumps(data)
        except Exception:
            pass
    cc = parse_module_color_changer(text)
    if cc:
        try:
            root[MU_COLOR_CHANGER_KEY] = json.dumps(cc)
        except Exception:
            pass
        try:
            apply_color_changer_preview(root, cc)
        except Exception as e:
            print(f"WARNING: color changer preview: {e}")
    # ModuleProceduralFairing: base mesh should use FairingBase, not panel diff
    try:
        _apply_procedural_fairing_textures(root, text)
    except Exception as e:
        print(f"WARNING: fairing textures: {e}")
    # ModuleAeroSurface (airbrake): synthesize Flap deploy NLA
    try:
        _attach_aero_surface_preview(root, text)
    except Exception as e:
        _vlog(f"WARNING: aero surface preview: {e}")
    # FXModuleLookAtConstraint / FXModuleConstrainPosition (wheel pistons, struts)
    try:
        _attach_fx_lookat_constraints(root, text)
    except Exception as e:
        print(f"WARNING: FX lookat/constrain: {e}")
    # Damaged / .broken meshes — hidden by default (Tools → Broken to show)
    try:
        apply_broken_default_hide(root, text, hide=True)
    except Exception as e:
        print(f"WARNING: broken hide: {e}")
    # ModuleWheelSuspension travel preview (amortyzatory)
    try:
        _attach_suspension_preview(root, text)
    except Exception as e:
        print(f"WARNING: suspension preview: {e}")
    # Extra MODEL { } .mu files from part.cfg (viewport-only, export-skipped)
    if not _SECONDARY_MODEL_IMPORT and not root.get("mu_secondary_model"):
        try:
            _load_secondary_models_from_cfg(
                root,
                text,
                mudir,
                cfg,
                primary_stem=filepath_stem or muname or "",
            )
        except Exception as e:
            _vlog(f"WARNING: secondary MODEL load: {e}")
    # Ensure LookAt / suspension constraints evaluate (no random rest until click)
    try:
        _force_constraint_eval(root)
    except Exception:
        pass
    try:
        _apply_shabby_material_hints(root, mudir, muname)
    except Exception as e:
        _vlog(f"WARNING: shabby materials: {e}")
    try:
        _attach_deployable_solar_preview(root, text)
    except Exception as e:
        _vlog(f"WARNING: solar panel preview: {e}")
    try:
        _attach_docking_node_preview(root, text)
    except Exception as e:
        _vlog(f"WARNING: docking node preview: {e}")
    try:
        _attach_parachute_preview(root, text)
    except Exception as e:
        _vlog(f"WARNING: parachute preview: {e}")
    try:
        _attach_control_surface_preview(root, text)
    except Exception as e:
        _vlog(f"WARNING: control surface preview: {e}")
    try:
        _attach_animate_generic_preview(root, text)
    except Exception as e:
        _vlog(f"WARNING: animate generic preview: {e}")
    # Serenity / Breaking Ground: synthesize ServoOperate from ModuleRobotic*
    try:
        from .robotics_preview import attach_robotics_preview
        attach_robotics_preview(root, text)
    except Exception as e:
        print(f"WARNING: robotics preview: {e}")
    # ModuleLight Flare (gear / lamp additive halo) — no shadows + soft glow
    try:
        from .flare_preview import attach_flare_preview
        attach_flare_preview(root, text)
    except Exception as e:
        print(f"WARNING: flare preview: {e}")
    # FlagDecal viewport preview (flags/ + Options enum)
    # Corrupt UTF-16/null-byte modules warn once, then skip.
    global _flag_preview_import_failed
    if not _flag_preview_import_failed:
        try:
            fp_path = os.path.join(os.path.dirname(__file__), 'flag_preview.py')
            with open(fp_path, 'rb') as _fh:
                if b'\x00' in _fh.read(512):
                    raise SyntaxError('source code string cannot contain null bytes')
            from .flag_preview import attach_flag_preview
            attach_flag_preview(root, text, mudir=mudir or os.path.dirname(cfg))
        except SyntaxError as e:
            _flag_preview_import_failed = True
            print(f"WARNING: flag preview: {e} (further imports suppressed)")
        except Exception as e:
            print(f"WARNING: flag preview: {e}")


def _object_plain_name(obj):
    """Unity GO name without MU import suffix / Blender .001."""
    try:
        n = (obj.name or "").split("∧")[0].strip()
    except Exception:
        return ""
    if "." in n:
        b, s = n.rsplit(".", 1)
        if s.isdigit():
            n = b
    return n


def _find_child_named(root, name, *, prefer_animated=True, exclude_root=True):
    """Find a hierarchy object by Unity-style name.

    Prefers exact plain-name matches that are *not* the part root (so LookAt
    targets resolve to the moving piston tip / arm, not the import root when
    names collide or CFG points at a transform that shares a basename).
    When *prefer_animated* is set, objects that already host NLA / action win.
    """
    want = (name or "").strip().lower()
    if not want or root is None:
        return None
    exact = []
    fuzzy = []
    stack = [root]
    seen = set()
    while stack:
        o = stack.pop()
        if o is None:
            continue
        try:
            key = o.as_pointer()
        except Exception:
            key = id(o)
        if key in seen:
            continue
        seen.add(key)
        try:
            stack.extend(list(o.children))
        except Exception:
            pass
        if exclude_root and o == root:
            # Still allow root if it is the only match later
            plain = _object_plain_name(o)
            if plain.lower() == want:
                exact.append(o)
            continue
        plain = _object_plain_name(o)
        pl = plain.lower()
        if not pl:
            continue
        if pl == want:
            exact.append(o)
        elif pl.startswith(want + ".") or want.startswith(pl + "."):
            fuzzy.append(o)
        elif pl.endswith("/" + want) or want in pl:
            # path-like or compound names
            fuzzy.append(o)

    def _score(o):
        score = 0
        try:
            # deeper in hierarchy = more specific transform
            depth = 0
            p = o.parent
            while p is not None:
                depth += 1
                p = p.parent
            score += depth * 10
        except Exception:
            pass
        if prefer_animated:
            try:
                ad = getattr(o, "animation_data", None)
                if ad and (ad.nla_tracks or ad.action):
                    score += 100
            except Exception:
                pass
        try:
            if getattr(o, "type", "") in ("EMPTY", "MESH"):
                score += 5
        except Exception:
            pass
        # Prefer non-root
        try:
            if o != root:
                score += 20
        except Exception:
            pass
        return score

    pool = exact or fuzzy
    if not pool:
        # last resort: allow root exact match
        plain = _object_plain_name(root)
        if plain.lower() == want:
            return root
        return None
    pool.sort(key=_score, reverse=True)
    return pool[0]


def _best_track_axis(obj, target):
    """Pick TRACK axis so the tube aims at *target* without a 90° flip.

    Uses the rest-pose vector (obj → target) expressed in *obj* local space and
    picks the local ±X/±Y/±Z most aligned with it. Longest-mesh-axis alone was
    wrong for some wheels (black tubes spun sideways = quaternion/euler look).
    """
    try:
        from mathutils import Vector
        # World vector from obj origin toward target origin
        ow = obj.matrix_world.to_translation()
        tw = target.matrix_world.to_translation()
        world_dir = tw - ow
        if world_dir.length < 1e-8:
            return "TRACK_Z"
        # Into obj local space (rotation only)
        local_dir = obj.matrix_world.to_3x3().inverted() @ world_dir
        local_dir.normalize()
        candidates = [
            ("TRACK_X", Vector((1, 0, 0))),
            ("TRACK_NEGATIVE_X", Vector((-1, 0, 0))),
            ("TRACK_Y", Vector((0, 1, 0))),
            ("TRACK_NEGATIVE_Y", Vector((0, -1, 0))),
            ("TRACK_Z", Vector((0, 0, 1))),
            ("TRACK_NEGATIVE_Z", Vector((0, 0, -1))),
        ]
        best_name = "TRACK_Z"
        best_dot = -2.0
        for name, axis in candidates:
            d = local_dir.dot(axis)
            if d > best_dot:
                best_dot = d
                best_name = name
        return best_name
    except Exception:
        return "TRACK_Z"


def _apply_procedural_fairing_textures(root, cfg_text):
    """Apply ModuleProceduralFairing DefaultBaseTextureURL / TextureURL to mats."""
    if not cfg_text or "ModuleProceduralFairing" not in cfg_text:
        return
    m = re.search(
        r"MODULE\s*\{[^}]*name\s*=\s*ModuleProceduralFairing[^}]*\}",
        cfg_text,
        re.I | re.S,
    )
    # Broader: find the MODULE block properly
    body = None
    for block in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = block.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if nm and nm.group(1).strip().strip('"') == "ModuleProceduralFairing":
            break
        body = None
    if not body:
        return

    def _val(key):
        mm = re.search(rf"^\s*{key}\s*=\s*(.+)$", body, re.M | re.I)
        if not mm:
            return None
        return mm.group(1).strip().strip('"').split("//")[0].strip()

    base_url = _val("DefaultBaseTextureURL")
    base_nm = _val("DefaultBaseNormalsURL")
    shell_url = _val("TextureURL")
    shell_nm = _val("TextureNormalURL")
    vdata = None
    try:
        if root is not None and MU_VARIANTS_KEY in root:
            vdata = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        vdata = None
    for mat in _iter_materials_under(root):
        mn = (mat.name or "").split(".")[0]
        if mn == "FairingBase" and base_url:
            path = _resolve_texture_url(root, base_url)
            if path:
                img = _load_variant_image(
                    path, os.path.splitext(os.path.basename(path))[0]
                )
                if img is not None:
                    _set_material_slot_image_viewport(
                        mat, "_MainTex", img, data=vdata
                    )
            if base_nm:
                path = _resolve_texture_url(root, base_nm)
                if path:
                    img = _load_variant_image(
                        path, os.path.splitext(os.path.basename(path))[0]
                    )
                    if img is not None:
                        _set_material_slot_image_viewport(
                            mat, "_BumpMap", img, data=vdata
                        )
        elif mn in ("FairingIconShell", "FairingsMat") and shell_url:
            path = _resolve_texture_url(root, shell_url)
            if path:
                img = _load_variant_image(
                    path, os.path.splitext(os.path.basename(path))[0]
                )
                if img is not None:
                    _set_material_slot_image_viewport(
                        mat, "_MainTex", img, data=vdata
                    )



def _track_axis_to_track_up(track_axis):
    """Map Blender constraint track axis name → (track_char, up_char) for to_track_quat."""
    # to_track_quat(track, up) uses chars like '-Z', 'Y'
    mapping = {
        "TRACK_X": ("X", "Z"),
        "TRACK_NEGATIVE_X": ("-X", "Z"),
        "TRACK_Y": ("Y", "Z"),
        "TRACK_NEGATIVE_Y": ("-Y", "Z"),
        "TRACK_Z": ("Z", "Y"),
        "TRACK_NEGATIVE_Z": ("-Z", "Y"),
    }
    return mapping.get(track_axis, ("Z", "Y"))


def _apply_single_lookat_rotation(obj, target, track_axis="TRACK_Z"):
    """Orient *obj* so its local track axis points at *target* (world-space).

    Only writes rotation (local quaternion). Location stays under NLA/parent
    control so SuspensionTravel translation is not overwritten.
    """
    if obj is None or target is None:
        return False
    try:
        from mathutils import Vector
        # Use current world matrices (after location anim / parent eval)
        ow = obj.matrix_world.to_translation()
        tw = target.matrix_world.to_translation()
        direction = tw - ow
        if direction.length < 1e-8:
            return False
        direction.normalize()
        track, up = _track_axis_to_track_up(track_axis)
        q_world = direction.to_track_quat(track, up)
        if obj.parent is not None:
            parent_q = obj.parent.matrix_world.to_quaternion()
            q_local = parent_q.inverted() @ q_world
        else:
            q_local = q_world
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = q_local
        return True
    except Exception:
        return False


def _iter_mu_lookat_bindings():
    """Yield (obj, target, track_axis) for objects tagged with mu_lookat_target."""
    for obj in bpy.data.objects:
        try:
            tname = obj.get("mu_lookat_target")
        except Exception:
            continue
        if not tname:
            continue
        target = bpy.data.objects.get(str(tname))
        if target is None:
            # Blender may rename .001 — match plain prefix
            want = str(tname)
            for o in bpy.data.objects:
                n = o.name or ""
                if n == want or n.startswith(want + "."):
                    target = o
                    break
        if target is None:
            continue
        axis = "TRACK_Z"
        try:
            axis = str(obj.get("mu_lookat_axis") or "TRACK_Z")
        except Exception:
            pass
        yield obj, target, axis


def _apply_all_mu_lookat_rotations(scene=None, depsgraph=None):
    """Frame handler: orient every mu_lookat_* binding. Deterministic, no cycles."""
    # Undo/redo may free targets mid-frame — never crash the handler.
    try:
        from ..tools import display as _disp
        if getattr(_disp, "_UNDO_REDO_DEPTH", 0) > 0:
            return None
    except Exception:
        pass
    # Two passes so mutual pairs settle (A→B then B→A then A→B)
    for _pass in range(2):
        for obj, target, axis in _iter_mu_lookat_bindings():
            try:
                _apply_single_lookat_rotation(obj, target, axis)
            except Exception:
                pass


_MU_LOOKAT_HANDLER_REGISTERED = False


def _ensure_mu_lookat_handler():
    """Register frame_change_post once so LookAt updates during timeline scrub."""
    global _MU_LOOKAT_HANDLER_REGISTERED
    if _MU_LOOKAT_HANDLER_REGISTERED:
        return
    try:
        # Avoid duplicate registrations across reload
        handlers = bpy.app.handlers.frame_change_post
        if _apply_all_mu_lookat_rotations not in handlers:
            handlers.append(_apply_all_mu_lookat_rotations)
        _MU_LOOKAT_HANDLER_REGISTERED = True
    except Exception as e:
        print(f"WARNING: mu lookat handler: {e}")


def _attach_fx_lookat_constraints(root, cfg_text):
    """Apply FXModuleLookAtConstraint + FXModuleConstrainPosition from part.cfg.

    LookAt is implemented as custom-prop bindings + a frame_change_post handler
    (not DAMPED_TRACK). Mutual A↔B pairs caused depsgraph cycles with constraints:
    tubes spawned at random orientations until the user clicked the timeline, and
    sometimes stayed wrong while animating. Manual look-at is deterministic.
    """
    if root is None or not cfg_text:
        return 0
    if (
        "FXModuleLookAtConstraint" not in cfg_text
        and "FXModuleConstrainPosition" not in cfg_text
        and "CONSTRAINLOOKFX" not in cfg_text
        and "CONSTRAINFX" not in cfg_text
    ):
        return 0
    made = 0

    def _find(name):
        return _find_child_named(root, name)

    # Collect LookAt pairs first (detect mutual)
    pairs = []  # (r_obj, t_obj, r_name, t_name)
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm:
            continue
        mod = nm.group(1).strip().strip('"').split("//")[0].strip()
        if mod != "FXModuleLookAtConstraint":
            continue
        for cbody in _parse_brace_blocks(body, "CONSTRAINLOOKFX"):
            tgt = re.search(r"^\s*targetName\s*=\s*(.+)$", cbody, re.M | re.I)
            rot = re.search(r"^\s*rotatorsName\s*=\s*(.+)$", cbody, re.M | re.I)
            if not tgt or not rot:
                continue
            t_name = tgt.group(1).strip().strip('"').split("//")[0].strip()
            r_name = rot.group(1).strip().strip('"').split("//")[0].strip()
            t_obj = _find(t_name)
            r_obj = _find(r_name)
            if t_obj is None or r_obj is None:
                print(
                    f"WARNING: LookAt missing target={t_name!r} rotator={r_name!r}"
                )
                continue
            try:
                if t_obj == root:
                    alt = _find_child_named(
                        root, t_name, prefer_animated=True, exclude_root=True
                    )
                    if alt is not None and alt != root:
                        t_obj = alt
                if r_obj == root:
                    alt = _find_child_named(
                        root, r_name, prefer_animated=True, exclude_root=True
                    )
                    if alt is not None and alt != root:
                        r_obj = alt
            except Exception:
                pass
            if t_obj == root or r_obj == root:
                print(
                    f"WARNING: LookAt skipped (resolved to root) "
                    f"target={t_name!r} rotator={r_name!r}"
                )
                continue
            pairs.append((r_obj, t_obj, r_name, t_name))

    # Tag bindings (both sides of mutual pairs — handler does two passes)
    for r_obj, t_obj, r_name, t_name in pairs:
        try:
            # Remove leftover constraint-based lookats from older imports
            for c in list(r_obj.constraints):
                cn = c.name or ""
                if cn.startswith("MuLookAt") or cn.startswith("AeroLookAt"):
                    r_obj.constraints.remove(c)
            axis = _best_track_axis(r_obj, t_obj)
            r_obj["mu_lookat_target"] = t_obj.name
            r_obj["mu_lookat_axis"] = axis
            # Apply immediately so viewport is correct without timeline click
            _apply_single_lookat_rotation(r_obj, t_obj, axis)
            made += 1
        except Exception as e:
            print(f"WARNING: LookAt {r_name}->{t_name}: {e}")

    # --- Constrain position / rotation (real constraints, one-way only) ---
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm:
            continue
        mod = nm.group(1).strip().strip('"').split("//")[0].strip()
        if mod != "FXModuleConstrainPosition":
            continue
        match_rot = True
        match_pos = True
        mr = re.search(r"^\s*matchRotation\s*=\s*(.+)$", body, re.M | re.I)
        if mr:
            match_rot = mr.group(1).strip().split("//")[0].strip().lower() in (
                "true", "1", "yes",
            )
        mp = re.search(r"^\s*matchPosition\s*=\s*(.+)$", body, re.M | re.I)
        if mp:
            match_pos = mp.group(1).strip().split("//")[0].strip().lower() in (
                "true", "1", "yes",
            )
        for cbody in _parse_brace_blocks(body, "CONSTRAINFX"):
            tgt = re.search(r"^\s*targetName\s*=\s*(.+)$", cbody, re.M | re.I)
            mov = re.search(r"^\s*moversName\s*=\s*(.+)$", cbody, re.M | re.I)
            if not tgt or not mov:
                continue
            t_name = tgt.group(1).strip().strip('"').split("//")[0].strip()
            m_name = mov.group(1).strip().strip('"').split("//")[0].strip()
            t_obj = _find(t_name)
            m_obj = _find(m_name)
            if t_obj is None or m_obj is None:
                print(
                    f"WARNING: ConstrainFX missing target={t_name!r} mover={m_name!r}"
                )
                continue
            try:
                if t_obj == root:
                    alt = _find_child_named(
                        root, t_name, prefer_animated=True, exclude_root=True
                    )
                    if alt is not None:
                        t_obj = alt
                if m_obj == root:
                    alt = _find_child_named(
                        root, m_name, prefer_animated=True, exclude_root=True
                    )
                    if alt is not None:
                        m_obj = alt
            except Exception:
                pass
            if t_obj == root or m_obj == root:
                print(
                    f"WARNING: ConstrainFX skipped (resolved to root) "
                    f"target={t_name!r} mover={m_name!r}"
                )
                continue
            try:
                for c in list(m_obj.constraints):
                    cn = c.name or ""
                    if cn.startswith("MuConstrain"):
                        m_obj.constraints.remove(c)
                if match_pos:
                    c = m_obj.constraints.new("COPY_LOCATION")
                    c.name = "MuConstrainLoc"
                    c.target = t_obj
                    c.use_x = c.use_y = c.use_z = True
                    made += 1
                if match_rot:
                    # LookAt handler owns rotation when mu_lookat_target is set
                    if not m_obj.get("mu_lookat_target"):
                        c = m_obj.constraints.new("COPY_ROTATION")
                        c.name = "MuConstrainRot"
                        c.target = t_obj
                        c.use_x = c.use_y = c.use_z = True
                        made += 1
            except Exception as e:
                print(f"WARNING: ConstrainFX {m_name}->{t_name}: {e}")

    if made:
        _vlog(f"INFO: FX constraints/bindings attached: {made}")
        try:
            _ensure_mu_lookat_handler()
        except Exception:
            pass
        try:
            # Settle mutual pairs + COPY_LOCATION
            _apply_all_mu_lookat_rotations()
            _force_constraint_eval(root)
            _apply_all_mu_lookat_rotations()
        except Exception as e:
            print(f"WARNING: FX constraint eval: {e}")
    return made


def _force_constraint_eval(root=None):
    """Force depsgraph evaluation (COPY_LOCATION etc.) with a real VIEW_3D context."""
    try:
        scene = bpy.context.scene
        if scene is None:
            return
        fr = int(getattr(scene, "frame_current", 1) or 1)

        def _do_update():
            try:
                scene.frame_set(fr)
            except Exception:
                try:
                    scene.frame_set(int(scene.frame_start) or 1)
                except Exception:
                    pass
            try:
                dg = bpy.context.evaluated_depsgraph_get()
                if dg is not None:
                    dg.update()
            except Exception:
                pass
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass

        # Import often runs without VIEW_3D context — frame_set is a no-op then.
        applied = False
        try:
            wm = bpy.context.window_manager
            for window in wm.windows:
                screen = window.screen
                if screen is None:
                    continue
                for area in screen.areas:
                    if area.type != "VIEW_3D":
                        continue
                    region = next(
                        (r for r in area.regions if r.type == "WINDOW"), None
                    )
                    kw = dict(window=window, screen=screen, area=area, scene=scene)
                    if region is not None:
                        kw["region"] = region
                    try:
                        with bpy.context.temp_override(**kw):
                            _do_update()
                        applied = True
                        break
                    except Exception:
                        continue
                if applied:
                    break
        except Exception:
            pass
        if not applied:
            _do_update()
        # Flush matrix on constrained objects
        if root is not None:
            try:
                stack = [root] + list(getattr(root, "children_recursive", []) or [])
            except Exception:
                stack = [root]
            for o in stack:
                try:
                    if getattr(o, "constraints", None):
                        if any(
                            (c.name or "").startswith("MuConstrain")
                            for c in o.constraints
                        ):
                            _ = o.matrix_world.copy()
                    if o.get("mu_lookat_target"):
                        _ = o.matrix_world.copy()
                except Exception:
                    pass
    except Exception:
        pass



def _attach_deployable_solar_preview(root, cfg_text):
    """ModuleDeployableSolarPanel — play animationName if present on hierarchy."""
    if root is None or not cfg_text or "ModuleDeployableSolarPanel" not in cfg_text:
        return 0
    made = 0
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "ModuleDeployableSolarPanel":
            continue
        anim = re.search(r"^\s*animationName\s*=\s*(.+)$", body, re.M | re.I)
        pivot = re.search(r"^\s*pivotName\s*=\s*(.+)$", body, re.M | re.I)
        ray = re.search(r"^\s*raycastTransformName\s*=\s*(.+)$", body, re.M | re.I)
        wind = re.search(r"^\s*windResistance\s*=\s*(.+)$", body, re.M | re.I)
        info = {
            "animationName": anim.group(1).strip().strip('"').split("//")[0].strip() if anim else "",
            "pivotName": pivot.group(1).strip().strip('"').split("//")[0].strip() if pivot else "",
            "raycastTransformName": ray.group(1).strip().strip('"').split("//")[0].strip() if ray else "",
            "windResistance": wind.group(1).strip().split("//")[0].strip() if wind else "",
        }
        try:
            root["mu_solar_panel"] = json.dumps(info)
        except Exception:
            pass
        # Unmute NLA tracks matching animationName so Preview Clip can find them
        aname = info.get("animationName") or ""
        if aname:
            try:
                stack = [root] + list(getattr(root, "children_recursive", []) or [])
            except Exception:
                stack = [root]
            for o in stack:
                ad = getattr(o, "animation_data", None)
                if not ad or not ad.nla_tracks:
                    continue
                for track in ad.nla_tracks:
                    tn = track.name or ""
                    if tn == aname or aname in tn:
                        try:
                            track["mu_solar_anim"] = 1
                        except Exception:
                            pass
                        made += 1
        # Mark pivot empty
        if info.get("pivotName"):
            p = _find_child_named(root, info["pivotName"])
            if p is not None:
                try:
                    p["mu_solar_pivot"] = 1
                    if p.type == "EMPTY":
                        p.empty_display_type = "PLAIN_AXES"
                        p.empty_display_size = max(0.15, p.empty_display_size)
                except Exception:
                    pass
                made += 1
    if made:
        _vlog(f"INFO: solar panel preview tags: {made}")
    return made


def _attach_docking_node_preview(root, cfg_text):
    """ModuleDockingNode — tag reference node + nodeType for viewport."""
    if root is None or not cfg_text or "ModuleDockingNode" not in cfg_text:
        return 0
    made = 0
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm:
            continue
        mod = nm.group(1).strip().strip('"').split("//")[0].strip()
        if mod not in ("ModuleDockingNode", "ModuleDockingNodeBase"):
            continue
        ref = re.search(r"^\s*referenceAttachNode\s*=\s*(.+)$", body, re.M | re.I)
        ntype = re.search(r"^\s*nodeType\s*=\s*(.+)$", body, re.M | re.I)
        ctrl = re.search(r"^\s*controlTransformName\s*=\s*(.+)$", body, re.M | re.I)
        node_name = re.search(r"^\s*nodeTransformName\s*=\s*(.+)$", body, re.M | re.I)
        info = {
            "referenceAttachNode": ref.group(1).strip().strip('"').split("//")[0].strip() if ref else "",
            "nodeType": ntype.group(1).strip().strip('"').split("//")[0].strip() if ntype else "",
            "controlTransformName": ctrl.group(1).strip().strip('"').split("//")[0].strip() if ctrl else "",
            "nodeTransformName": node_name.group(1).strip().strip('"').split("//")[0].strip() if node_name else "",
        }
        try:
            root["mu_docking_node"] = json.dumps(info)
        except Exception:
            pass
        for key in ("nodeTransformName", "controlTransformName", "referenceAttachNode"):
            name = info.get(key) or ""
            if not name:
                continue
            # referenceAttachNode is often "top" → node_stack_top
            candidates = [name, "node_" + name, "node_stack_" + name]
            obj = None
            for c in candidates:
                obj = _find_child_named(root, c)
                if obj is not None:
                    break
            if obj is None:
                continue
            try:
                obj["mu_docking_ref"] = key
                if obj.type == "EMPTY":
                    obj.empty_display_type = "CIRCLE"
                    obj.empty_display_size = max(0.2, obj.empty_display_size)
                    obj.color = (0.2, 0.8, 1.0, 1.0)
                made += 1
            except Exception:
                pass
    if made:
        _vlog(f"INFO: docking node preview: {made}")
    return made


def _attach_parachute_preview(root, cfg_text):
    """ModuleParachute — tag canopy/semiDeployed/fullyDeployed animation names."""
    if root is None or not cfg_text or "ModuleParachute" not in cfg_text:
        return 0
    made = 0
    for body in _parse_brace_blocks(cfg_text, "MODULE"):
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "ModuleParachute":
            continue
        def _gv(key):
            m = re.search(rf"^\s*{key}\s*=\s*(.+)$", body, re.M | re.I)
            return m.group(1).strip().strip('"').split("//")[0].strip() if m else ""
        info = {
            "semiDeployedAnimation": _gv("semiDeployedAnimation"),
            "fullyDeployedAnimation": _gv("fullyDeployedAnimation"),
            "capName": _gv("capName"),
            "canopyName": _gv("canopyName"),
            "animationName": _gv("animationName"),
        }
        try:
            root["mu_parachute"] = json.dumps(info)
        except Exception:
            pass
        for key in ("capName", "canopyName"):
            name = info.get(key) or ""
            if not name:
                continue
            o = _find_child_named(root, name)
            if o is None:
                continue
            try:
                o["mu_parachute_mesh"] = key
                # Cap often hidden when deployed — leave visible for editing
                made += 1
            except Exception:
                pass
        # Tag matching NLA clips
        for aname in (
            info.get("semiDeployedAnimation"),
            info.get("fullyDeployedAnimation"),
            info.get("animationName"),
        ):
            if not aname:
                continue
            try:
                stack = [root] + list(getattr(root, "children_recursive", []) or [])
            except Exception:
                stack = [root]
            for o in stack:
                ad = getattr(o, "animation_data", None)
                if not ad or not ad.nla_tracks:
                    continue
                for track in ad.nla_tracks:
                    tn = track.name or ""
                    if tn == aname or aname in tn:
                        try:
                            track["mu_parachute_anim"] = 1
                        except Exception:
                            pass
                        made += 1
    if made:
        _vlog(f"INFO: parachute preview tags: {made}")
    return made


def _attach_aero_surface_preview(root, cfg_text):
    """Synthesize Deploy NLA for ModuleAeroSurface (airbrake Flap)."""
    if not cfg_text or "ModuleAeroSurface" not in cfg_text:
        return 0
    import math
    from ..utils.action_compat import fcurve_new, push_action_to_nla

    made = 0
    for block in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = block.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "ModuleAeroSurface":
            continue
        tname = "Flap"
        tm = re.search(r"^\s*transformName\s*=\s*(.+)$", body, re.M | re.I)
        if tm:
            tname = tm.group(1).strip().strip('"').split("//")[0].strip()
        rng = 70.0
        rm = re.search(r"^\s*ctrlSurfaceRange\s*=\s*([0-9.+-eE]+)", body, re.M | re.I)
        if rm:
            try:
                rng = float(rm.group(1))
            except Exception:
                pass
        flap = _find_child_named(root, tname)
        if flap is None:
            print(f"WARNING: aero surface: missing transform {tname!r}")
            continue
        # Already has real animation?
        ad = getattr(flap, "animation_data", None)
        if ad and ad.nla_tracks:
            has_real = False
            for t in ad.nla_tracks:
                if t.get("mu_fx_preview") or t.get("mu_robotic_preview"):
                    continue
                if t.name:
                    has_real = True
                    break
            if has_real:
                continue
        scene = bpy.context.scene
        try:
            fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)
        except Exception:
            fps = 24.0
        fps = max(1.0, fps)
        f0 = float(scene.frame_start)
        # Unity/KSP aero surface typically pitches about local X
        flap.rotation_mode = "XYZ"
        rest = list(flap.rotation_euler)
        act = bpy.data.actions.new(name=f"AeroSurfaceDeploy.{flap.name}")
        try:
            act["mu_fx_preview"] = 1
        except Exception:
            pass
        fc = fcurve_new(act, flap, "rotation_euler", index=0)
        fc.keyframe_points.add(2)
        fc.keyframe_points[0].co = f0, float(rest[0])
        fc.keyframe_points[0].interpolation = "LINEAR"
        fc.keyframe_points[1].co = f0 + fps * 1.0, float(rest[0]) + math.radians(rng)
        fc.keyframe_points[1].interpolation = "LINEAR"
        track, _strip = push_action_to_nla(flap, act, "AeroSurfaceDeploy")
        made += 1
        _vlog(f"INFO: aero surface preview -> {flap.name} (range {rng} deg)")
        # FXModuleLookAtConstraint piston pair
        for cm in re.finditer(
            r"CONSTRAINLOOKFX\s*\{([^}]*)\}", body, re.I | re.S
        ):
            pass  # LookAts are in a separate MODULE
        break
    # Separate FXModuleLookAtConstraint blocks
    for block in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = block.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "FXModuleLookAtConstraint":
            continue
        for cm in re.finditer(
            r"CONSTRAINLOOKFX\s*\{([^}]*)\}", body, re.I | re.S
        ):
            cbody = cm.group(1)
            tgt = re.search(r"^\s*targetName\s*=\s*(.+)$", cbody, re.M | re.I)
            rot = re.search(r"^\s*rotatorsName\s*=\s*(.+)$", cbody, re.M | re.I)
            if not tgt or not rot:
                continue
            t_obj = _find_child_named(root, tgt.group(1).strip().strip('"'))
            r_obj = _find_child_named(root, rot.group(1).strip().strip('"'))
            if t_obj is None or r_obj is None:
                continue
            try:
                for c in list(r_obj.constraints):
                    if (c.name or "").startswith("AeroLookAt"):
                        r_obj.constraints.remove(c)
                c = r_obj.constraints.new("DAMPED_TRACK")
                c.name = "AeroLookAt"
                c.target = t_obj
                c.track_axis = _best_track_axis(r_obj, t_obj)
            except Exception as e:
                print(f"WARNING: aero lookat: {e}")
    return made
