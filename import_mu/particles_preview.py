# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>
"""Viewport-only MuParticles preview (billboard + timeline swarm).

Source of truth for export remains obj["mu_particles"] JSON. Preview objects
are tagged mu_fx_preview=1 / ".fx_preview" in the name and skipped on export.

Animated particles use keyframed .fx_anim billboards + NLA (MuParticles), not
Blender Particle System OBJECT instances — those do not appear on the timeline
and often fail to draw in EEVEE after toggle.
"""

from __future__ import annotations

import json
import math
import os
import random
import re

import bpy
from mathutils import Vector

from ..utils.action_compat import ensure_action_assigned, push_action_to_nla


FX_PREVIEW_SUFFIX = ".fx_preview"
FX_EMITTER_SUFFIX = ".fx_emitter"
FX_PINST_SUFFIX = ".fx_pinst"
FX_ANIM_SUFFIX = ".fx_anim"

# KSPParticleEmitter.shape (legacy Mu ET_PARTICLES) — not Unity ShapeModule.
# Drill Dust/Rocks use Sphere (2) with shape1d≈0.01; the “cone” look is from
# localVelocity + rndVelocity, not from a Cone emitter shape.
_SHAPE_NAMES = {
    0: "Ellipsoid",
    1: "Ellipse",
    2: "Sphere",
    3: "Ring",
    4: "Cuboid",
    5: "Plane",
    6: "Line",
    7: "Point",
}


def is_fx_preview_object(obj) -> bool:
    if obj is None:
        return False
    if obj.get("mu_fx_preview"):
        return True
    name = obj.name or ""
    return (
        FX_PREVIEW_SUFFIX in name
        or FX_EMITTER_SUFFIX in name
        or FX_PINST_SUFFIX in name
        or FX_ANIM_SUFFIX in name
    )


def _parse_particles(obj):
    raw = obj.get("mu_particles") if hasattr(obj, "get") else None
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        return None


def _particle_material(obj, mu=None):
    """Pick Blender material for FX preview; match host name (Dust→DrillDust)."""
    names = []
    raw = obj.get("mu_particle_materials") if hasattr(obj, "get") else None
    if raw:
        try:
            names = json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            names = []
    oname = (obj.name or "").lower()
    # Prefer exact / partial name match (Dust↔DrillDust, Rocks↔DrillRocks)
    scored = []
    for n in names:
        mat = bpy.data.materials.get(n)
        if not mat:
            continue
        mn = (mat.name or "").lower()
        score = 0
        for key in ("dust", "rock", "smoke", "flame", "spark", "exhaust", "ion"):
            if key in oname and key in mn:
                score += 10
        if oname.replace("∧", "").split(".")[0] in mn:
            score += 5
        scored.append((score, mat))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] > 0:
        return scored[0][1]
    for n in names:
        mat = bpy.data.materials.get(n)
        if mat:
            return mat
    for mat in bpy.data.materials:
        mp = getattr(mat, "mumatprop", None)
        sn = ((mp.shaderName or "") if mp else "").lower()
        if "particle" not in sn:
            continue
        mn = (mat.name or "").lower()
        for key in ("dust", "rock", "smoke", "flame"):
            if key in oname and key in mn:
                return mat
    for mat in bpy.data.materials:
        mp = getattr(mat, "mumatprop", None)
        sn = ((mp.shaderName or "") if mp else "").lower()
        if "particle" in sn:
            return mat
    if obj.type == "MESH" and obj.data and obj.data.materials:
        for mat in obj.data.materials:
            if mat:
                return mat
    return None


def _ensure_particle_mat_blend(mat):
    """Force EEVEE alpha blend so soft particle TGA/DDS shows as transparent."""
    if not mat:
        return
    try:
        mat.blend_method = "BLEND"
    except Exception:
        pass
    try:
        mat.surface_render_method = "BLENDED"
    except Exception:
        pass
    try:
        mat.use_backface_culling = False
    except Exception:
        pass
    # Ensure _MainTex is assigned on the image node (DDS may load as stem name)
    if not mat.node_tree:
        return
    node = mat.node_tree.nodes.get("_MainTex")
    if node is None:
        return
    if node.image:
        return
    mp = getattr(mat, "mumatprop", None)
    if not mp:
        return
    for t in mp.texture.properties:
        if t.name == "_MainTex" and t.tex:
            img = bpy.data.images.get(t.tex)
            if img is None:
                # stem match DustParticle.tga → DustParticle
                stem = t.tex.rsplit(".", 1)[0]
                img = bpy.data.images.get(stem)
            if img is not None:
                node.image = img
            break


def _load_particle_image_from_dir(stem, mudir):
    """Load a particle/FX texture from a folder (.dds preferred).

    Matches case-insensitively and tries Squad/FX aliases (``rocketplume`` →
    ``rocketplume2.dds``, ``DiamondBLue`` → ``DiamondBlue.dds``).
    """
    import os
    if not mudir or not stem:
        return None

    def _finish(img, prefer_name):
        if img is None:
            return None
        try:
            if prefer_name and img.name != prefer_name:
                # Keep canonical stem when possible (avoid .001 clutter)
                if prefer_name not in bpy.data.images:
                    img.name = prefer_name
        except Exception:
            pass
        try:
            img.alpha_mode = "STRAIGHT"
        except Exception:
            pass
        try:
            fp = (img.filepath or "").lower()
            if fp.endswith(".dds"):
                img.muimageprop.invertY = True
        except Exception:
            pass
        if _image_looks_empty(img):
            return None
        return img

    for cand in _fx_stem_candidates(stem):
        existing = bpy.data.images.get(cand)
        if existing is None:
            # case-insensitive image datablock match
            cl = cand.lower()
            for im in bpy.data.images:
                if (im.name or "").lower() == cl:
                    existing = im
                    break
        if existing is not None:
            got = _finish(existing, cand)
            if got is not None:
                try:
                    fp = bpy.path.abspath(existing.filepath or "")
                except Exception:
                    fp = existing.filepath or ""
                if (fp and os.path.isfile(fp)) or existing.packed_file is not None:
                    return got

        # Exact path
        for ext in (".dds", ".tga", ".png", ".mbm"):
            path = os.path.join(mudir, cand + ext)
            if not os.path.isfile(path):
                continue
            try:
                img = bpy.data.images.load(path, check_existing=True)
                got = _finish(img, cand)
                if got is not None:
                    return got
            except Exception:
                continue

        # Case-insensitive directory scan (DiamondBLue vs DiamondBlue.dds)
        try:
            names = os.listdir(mudir)
        except Exception:
            names = []
        want = cand.lower()
        for name in names:
            base, ext = os.path.splitext(name)
            if ext.lower() not in (".dds", ".tga", ".png", ".mbm"):
                continue
            if base.lower() != want:
                continue
            path = os.path.join(mudir, name)
            try:
                img = bpy.data.images.load(path, check_existing=True)
                got = _finish(img, base)
                if got is not None:
                    return got
            except Exception:
                continue
    return None


def _gamedata_particle_dirs(mudir):
    """Walk up to GameData and collect Squad particle texture folders."""
    dirs = []
    if not mudir:
        mudir = ""
    d = mudir
    gamedata = None
    for _ in range(16):
        if not d:
            break
        if os.path.basename(d).lower() == "gamedata":
            gamedata = d
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # Addon bundled test GameData (smoke reimport uses a temp mudir)
    try:
        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        test_gd = os.path.join(addon_root, "test tools v2", "GameData")
        if os.path.isdir(test_gd):
            gamedata = gamedata or test_gd
            # Always include test GameData resources even when mudir had another root
            res = os.path.join(test_gd, "Squad", "Parts", "Resources")
            if os.path.isdir(res):
                for sub in ("MiniDrill", "RadialDrill"):
                    p = os.path.join(res, sub)
                    if os.path.isdir(p) and p not in dirs:
                        dirs.append(p)
    except Exception:
        pass
    if gamedata:
        resources = os.path.join(gamedata, "Squad", "Parts", "Resources")
        if os.path.isdir(resources):
            for sub in ("MiniDrill", "RadialDrill"):
                p = os.path.join(resources, sub)
                if os.path.isdir(p) and p not in dirs:
                    dirs.append(p)
            try:
                for name in os.listdir(resources):
                    p = os.path.join(resources, name)
                    if not os.path.isdir(p):
                        continue
                    if os.path.isfile(os.path.join(p, "DustParticle.dds")) or os.path.isfile(
                        os.path.join(p, "RockParticle.dds")
                    ):
                        if p not in dirs:
                            dirs.append(p)
            except Exception:
                pass
        # Squad/FX — exhaust plumes (afterburner_flame, IonPlume, ks*_Exhaust…)
        # ship textures beside the .mu (FlameBlueOrange.dds, rocketplume2.dds…).
        for fx_sub in (
            os.path.join(gamedata, "Squad", "FX"),
            os.path.join(gamedata, "Squad", "Effects"),
        ):
            if os.path.isdir(fx_sub) and fx_sub not in dirs:
                dirs.append(fx_sub)
    # Directories of any already-loaded particle / FX images
    for img in bpy.data.images:
        fp = getattr(img, "filepath", "") or ""
        if not fp:
            continue
        low = fp.replace("\\", "/").lower()
        if not any(
            k in low
            for k in (
                "dustparticle",
                "rockparticle",
                "/fx/",
                "/effects/",
                "flame",
                "plume",
                "plasma",
                "monoprop",
                "shock",
            )
        ):
            continue
        try:
            ab = bpy.path.abspath(fp)
        except Exception:
            ab = fp
        d = os.path.dirname(ab)
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs


def _make_billboard_preview_material(stem, img, host_name=""):
    """Simple EEVEE-visible soft particle mat (stock KSP particle graphs often
    leave billboards as opaque grey quads in GIF renders).

    Squad/FX additive plumes store the glow in RGB with opaque alpha≈1 — using
    Alpha as Mix Fac yields solid black cards. Fac = max(RGB) instead.
    """
    name = f"mu_fx_bill_{stem}_{host_name}"[:60]
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    # use_nodes deprecated Blender 5+ (always True)
    try:
        mat["mu_fx_preview"] = 1
    except Exception:
        pass
    _ensure_particle_mat_blend(mat)
    try:
        mat.shadow_method = "NONE"
    except Exception:
        pass
    try:
        mat.use_transparent_shadow = False
    except Exception:
        pass
    try:
        mat.blend_method = "BLEND"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (220, 0)
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (-20, 80)
    emit.inputs[1].default_value = 3.0
    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    trans.location = (-20, -80)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.name = "_MainTex"
    tex.label = "_MainTex"
    tex.location = (-400, 40)
    if img is not None:
        tex.image = img
        try:
            img.alpha_mode = "STRAIGHT"
        except Exception:
            pass
    nt.links.new(tex.outputs.get("Color") or tex.outputs[0], emit.inputs[0])

    # Multiply by Object Info Color so per-particle colorAnimation can keyframe
    # obj.color without cloning materials (default white = no tint change).
    try:
        obj_info = nt.nodes.new("ShaderNodeObjectInfo")
        obj_info.location = (-400, 200)
        try:
            mix_col = nt.nodes.new("ShaderNodeMixRGB")
        except Exception:
            mix_col = nt.nodes.new("ShaderNodeMix")
            try:
                mix_col.data_type = "RGBA"
            except Exception:
                pass
        mix_col.blend_type = "MULTIPLY"
        if "Fac" in mix_col.inputs:
            mix_col.inputs["Fac"].default_value = 1.0
        else:
            mix_col.inputs[0].default_value = 1.0
        mix_col.location = (-200, 100)
        a_in = mix_col.inputs.get("Color1") or mix_col.inputs.get("A") or mix_col.inputs[1]
        b_in = mix_col.inputs.get("Color2") or mix_col.inputs.get("B") or mix_col.inputs[2]
        res = mix_col.outputs.get("Color") or mix_col.outputs.get("Result") or mix_col.outputs[0]
        for link in list(nt.links):
            if link.to_socket == emit.inputs[0]:
                nt.links.remove(link)
        nt.links.new(tex.outputs[0], a_in)
        nt.links.new(obj_info.outputs.get("Color") or obj_info.outputs[1], b_in)
        nt.links.new(res, emit.inputs[0])
    except Exception:
        pass

    # Fac: prefer max(RGB) for additive FX (opaque DDS alpha); fall back to Alpha
    use_rgb_fac = True
    try:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
    except Exception:
        sep = nt.nodes.new("ShaderNodeSeparateRGB")
    sep.location = (-200, -140)
    vmax = nt.nodes.new("ShaderNodeMath")
    vmax.operation = "MAXIMUM"
    vmax.location = (0, -120)
    vmax2 = nt.nodes.new("ShaderNodeMath")
    vmax2.operation = "MAXIMUM"
    vmax2.location = (0, -260)
    nt.links.new(tex.outputs[0], sep.inputs[0])
    outs = list(sep.outputs)
    r = outs[0] if outs else None
    g = outs[1] if len(outs) > 1 else outs[0]
    b = outs[2] if len(outs) > 2 else outs[0]
    if r and g:
        nt.links.new(r, vmax.inputs[0])
        nt.links.new(g, vmax.inputs[1])
    nt.links.new(vmax.outputs[0], vmax2.inputs[0])
    if b:
        nt.links.new(b, vmax2.inputs[1])
    # Soft knee: boost mid luminance so soft flames read
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.location = (160, -140)
    mul.inputs[1].default_value = 1.35
    nt.links.new(vmax2.outputs[0], mul.inputs[0])
    clamp = nt.nodes.new("ShaderNodeMath")
    clamp.operation = "MINIMUM"
    clamp.location = (160, -260)
    clamp.inputs[1].default_value = 1.0
    nt.links.new(mul.outputs[0], clamp.inputs[0])
    nt.links.new(clamp.outputs[0], mix.inputs[0])
    if not use_rgb_fac:
        alpha_sock = None
        for sock in tex.outputs:
            if (sock.name or "").lower() == "alpha":
                alpha_sock = sock
                break
        if alpha_sock is not None:
            nt.links.new(alpha_sock, mix.inputs[0])

    nt.links.new(trans.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], output.inputs["Surface"])
    return mat


def _resolve_particle_image(stem, mudir):
    """Find particle/FX image, searching mudir + Squad/FX + GameData aliases."""
    search_dirs = []
    if mudir:
        search_dirs.append(mudir)
        parent = os.path.dirname(mudir)
        if parent:
            search_dirs.append(parent)
    for d in _gamedata_particle_dirs(mudir):
        if d not in search_dirs:
            search_dirs.append(d)
    for cand in _fx_stem_candidates(stem):
        for d in search_dirs:
            img = _load_particle_image_from_dir(cand, d)
            if img is not None and not _image_looks_empty(img):
                return img
        img = bpy.data.images.get(cand)
        if img is not None and not _image_looks_empty(img):
            return img
        # case-insensitive datablock
        cl = cand.lower()
        for im in bpy.data.images:
            if (im.name or "").lower() == cl and not _image_looks_empty(im):
                return im
    return None


def _image_looks_empty(img):
    """True when the image has no usable RGB (not merely black corners).

    Squad/FX flame & plume DDS are bright in the centre and black at the edges.
    Sampling only the first 16 texels falsely rejected FlameBlueOrange etc. and
    the preview fell back to DustParticle.
    """
    if img is None:
        return True
    try:
        w = int(getattr(img, "size", (0, 0))[0] or 0)
        h = int(getattr(img, "size", (0, 0))[1] or 0)
    except Exception:
        w, h = 0, 0
    if w <= 4:
        return True
    try:
        n = int(w) * int(h or 1) * 4
        px = img.pixels
        plen = len(px)
        if plen < 4:
            return True
        # ~512 RGB samples spread across the whole map
        step = max(4, (min(n, plen) // 512) // 4 * 4)
        mx = 0.0
        for i in range(0, min(n, plen) - 3, step):
            mx = max(mx, float(px[i]), float(px[i + 1]), float(px[i + 2]))
            if mx >= 0.02:
                return False
        return mx < 0.02
    except Exception:
        return False


# Stock Squad/FX material names → on-disk DDS stems (mu often omits the "2").
_FX_TEX_ALIASES = {
    "rocketplume": ("rocketplume2", "rocketplume"),
    "shockdiamond": ("shockdiamond2", "shockdiamond"),
    "diamondblue": ("DiamondBlue", "diamondBlue", "DiamondBLue"),
    "fireball": ("FlameRedOrange", "FlameBlueOrange", "smokepuff1"),
}


def _fx_stem_candidates(stem):
    """Ordered stems to try for a particle/FX maintex name."""
    if not stem:
        return []
    base = stem.rsplit(".", 1)[0]
    low = base.lower()
    out = []
    seen = set()

    def _add(s):
        if not s:
            return
        k = s.lower()
        if k not in seen:
            seen.add(k)
            out.append(s)

    _add(base)
    for alt in _FX_TEX_ALIASES.get(low, ()):
        _add(alt)
    # Common Squad suffix: name → name2
    if not low.endswith("2"):
        _add(base + "2")
    return out


def _boost_particle_tint(mat):
    """Raise near-invisible stock tint alpha on _TintColor / _Color nodes."""
    if not mat:
        return
    mp = getattr(mat, "mumatprop", None)
    if mp:
        for p in mp.color.properties:
            if p.name not in ("_TintColor", "_Color"):
                continue
            try:
                v = list(p.value)
            except Exception:
                continue
            if len(v) >= 4 and float(v[3]) < 0.3:
                v[3] = max(float(v[3]) * 10.0, 0.65)
                try:
                    p.value = tuple(v)
                except Exception:
                    pass
    nt = getattr(mat, "node_tree", None)
    if not nt:
        return
    for nname in ("_TintColor", "_Color"):
        node = nt.nodes.get(nname)
        if not node or not node.inputs:
            continue
        try:
            if len(node.inputs) > 1:
                a = float(node.inputs[1].default_value)
                if a < 0.3:
                    node.inputs[1].default_value = max(a * 10.0, 0.65)
        except Exception:
            pass
    opac = nt.nodes.get("_Opacity")
    if opac and hasattr(opac, "outputs") and opac.outputs:
        try:
            if float(opac.outputs[0].default_value) < 0.5:
                opac.outputs[0].default_value = 1.0
        except Exception:
            pass


def _bind_particle_maintex(mat, mu=None):
    """Ensure particle _MainTex node has a real DDS/TGA (not a black empty).

    Stock .mu lists DustParticle.tga / RockParticle.tga but Squad ships .dds
    beside the part. Force-resolve from mudir even if a blank image is linked.
    """
    if not mat or not mat.node_tree:
        return
    _ensure_particle_mat_blend(mat)
    node = mat.node_tree.nodes.get("_MainTex")
    if node is None:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and (
                (n.name or "").lower().startswith("_main")
                or "main" in (n.label or "").lower()
            ):
                node = n
                break
        if node is None:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE":
                    node = n
                    break
    if node is None:
        return

    mudir = getattr(mu, "mudir", None) if mu is not None else None
    stems = []
    mp = getattr(mat, "mumatprop", None)
    if mp:
        for t in mp.texture.properties:
            if t.name == "_MainTex" and t.tex:
                stems.append(t.tex.rsplit(".", 1)[0])
    mname = (mat.name or "").split("\u2227")[0]
    if mname and mname.lower() not in ("material", "particle"):
        stems.append(mname)
    low_m = (mname or "").lower()
    if "dust" in low_m:
        stems.append("DustParticle")
    if "rock" in low_m:
        stems.append("RockParticle")
    # Drill / soil FX only — do not steal exhaust plume maps with DustParticle
    is_soil = any(k in low_m for k in ("dust", "rock", "soil", "dirt")) or any(
        "dust" in (s or "").lower() or "rock" in (s or "").lower() for s in stems[:1]
    )
    if is_soil or not stems:
        stems.extend(["DustParticle", "RockParticle"])

    seen = set()
    uniq = []
    for s in stems:
        for cand in _fx_stem_candidates(s):
            k = cand.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(cand)

    search_dirs = []
    if mudir:
        search_dirs.append(mudir)
        parent = os.path.dirname(mudir)
        if parent:
            search_dirs.append(parent)
            if os.path.basename(parent).lower() == "resources":
                for sub in ("MiniDrill", "RadialDrill"):
                    d = os.path.join(parent, sub)
                    if os.path.isdir(d):
                        search_dirs.append(d)
    for d in _gamedata_particle_dirs(mudir):
        if d not in search_dirs:
            search_dirs.append(d)

    for stem in uniq:
        img = None
        for d in search_dirs:
            img = _load_particle_image_from_dir(stem, d)
            if img is not None and not _image_looks_empty(img):
                break
            img = None
        if img is None:
            cand = bpy.data.images.get(stem)
            if cand is not None and not _image_looks_empty(cand):
                img = cand
        if img is not None:
            node.image = img
            try:
                img.alpha_mode = "STRAIGHT"
            except Exception:
                pass
            try:
                nt = mat.node_tree
                for out_n in nt.nodes:
                    if out_n.type != "BSDF_PRINCIPLED":
                        continue
                    bc = out_n.inputs.get("Base Color")
                    al = out_n.inputs.get("Alpha")
                    if bc is not None and not bc.links and node.outputs:
                        nt.links.new(node.outputs[0], bc)
                    if al is not None and not al.links and len(node.outputs) > 1:
                        nt.links.new(node.outputs[1], al)
            except Exception:
                pass
            _boost_particle_tint(mat)
            return

    if node.image is None or _image_looks_empty(node.image):
        node.image = _soft_particle_fallback_image()
    _boost_particle_tint(mat)


def _soft_particle_fallback_image():
    """Procedural soft circle (viewport-only) when stock particle tex missing."""
    name = "mu_soft_particle"
    if name in bpy.data.images:
        return bpy.data.images[name]
    size = 64
    img = bpy.data.images.new(name, width=size, height=size, alpha=True)
    pixels = [0.0] * (size * size * 4)
    cx = cy = (size - 1) * 0.5
    for y in range(size):
        for x in range(size):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            r = (dx * dx + dy * dy) ** 0.5
            a = max(0.0, 1.0 - r)
            a = a * a
            i = (y * size + x) * 4
            pixels[i:i + 4] = [1.0, 1.0, 1.0, a]
    img.pixels = pixels
    img.pack()
    return img


def _ensure_quad_mesh(name: str, size: float):
    """Static-friendly billboard quad in the XZ plane (normal +Y).

    This is the orientation that read correctly for drill dust before the
    XY + face-to-camera experiments flipped the angle.
    """
    s = max(0.02, float(size) * 0.5)
    # XZ plane, facing +Y — original preview orientation
    verts = [(-s, 0, -s), (s, 0, -s), (s, 0, s), (-s, 0, s)]
    mesh = bpy.data.meshes.get(name)
    if mesh is not None and len(mesh.vertices) == 4:
        for i, co in enumerate(verts):
            mesh.vertices[i].co = co
        mesh.update()
        return mesh
    if mesh is not None:
        try:
            bpy.data.meshes.remove(mesh, do_unlink=True)
        except Exception:
            pass
    mesh = bpy.data.meshes.new(name)
    faces = [(0, 1, 2, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for i, loop in enumerate(mesh.loops):
        uv.data[i].uv = uvs[loop.vertex_index % 4]
    if not mesh.color_attributes:
        mesh.color_attributes.new("colors", "FLOAT_COLOR", "POINT")
        for d in mesh.color_attributes.active_color.data:
            d.color = (1, 1, 1, 1)
    return mesh


def _avg_size(data: dict) -> float:
    size = data.get("size") or [0.1, 0.1]
    try:
        a, b = float(size[0]), float(size[1])
        return max(0.02, (a + b) * 0.5)
    except Exception:
        return 0.1


def _part_hint(obj, mu=None) -> str:
    parts = []
    if mu is not None:
        parts.append(str(getattr(mu, "mudir", "") or ""))
        parts.append(str(getattr(mu, "name", "") or ""))
    cur = obj
    for _ in range(12):
        if cur is None:
            break
        parts.append(cur.name or "")
        cur = cur.parent
    return " ".join(parts).lower()


def _stock_particle_size(data: dict) -> float:
    """MuParticles size clamped by maxParticleSize (Unity/KSP units)."""
    size = _avg_size(data)
    try:
        mps = float(data.get("maxParticleSize") or 0)
        if mps > 0:
            size = min(size, mps) if size > 0 else mps
    except Exception:
        pass
    return float(size)


def _host_world_scale(obj) -> float:
    """Dominant world scale on the particle host (Radial DrillFixed is ~10×)."""
    if obj is None:
        return 1.0
    try:
        sc = obj.matrix_world.to_scale()
        return max(abs(float(sc.x)), abs(float(sc.y)), abs(float(sc.z)), 1e-6)
    except Exception:
        return 1.0


def _is_standalone_fx_mu(mu=None, obj=None) -> bool:
    """True for Squad/FX exhaust .mu (afterburner, IonPlume, ks*_Exhaust…).

    These have high localVelocity×energy (10m+ travel) but are authored as
    meter-scale thruster plumes — drill ImpactRange heuristics do not apply.
    """
    mudir = ""
    if mu is not None:
        mudir = str(getattr(mu, "mudir", "") or "")
    low = mudir.replace("\\", "/").lower()
    parts = [p for p in low.split("/") if p]
    if "fx" in parts:
        return True
    return False


def _preview_billboard_size(obj, data: dict, mu=None) -> float:
    """Parent-local billboard size from Mu size + host world scale.

    Static quads sit under Dust/Rocks without world-length shrink. Mini (~1×)
    needs a larger local mul so DDS reads; Radial (~10× parent) stays near stock
    local size so the hierarchy scale does the rest — matches the tuned look.

    Squad/FX exhaust: use authoring ``size`` (ignore tiny maxParticleSize — that
    is a Unity cull/LOD clamp and made plumes vanishingly small in the viewport).
    """
    if _is_standalone_fx_mu(mu, obj):
        size = _avg_size(data)
        return max(0.12, min(1.6, float(size) * 0.7))
    size = _stock_particle_size(data)
    axis_scale = _host_world_scale(obj)
    # scale≥4 (TriBit DrillFixed×10): mild local boost; else enlarge for tiny hosts
    if axis_scale >= 4.0:
        mul = 1.15
    else:
        mul = min(4.0, 4.0 / max(axis_scale, 0.5))
    return max(0.06, float(size) * mul)


def _shape_extent(data: dict) -> Vector:
    s3 = data.get("shape3d") or [0.1, 0.1, 0.1]
    try:
        return Vector((abs(float(s3[0])), abs(float(s3[1])), abs(float(s3[2]))))
    except Exception:
        return Vector((0.1, 0.1, 0.1))


def _fx_parent_for_host(obj, bill=None):
    """Parent FX under the KSP particle host (Dust/Rocks), not ImpactTransform."""
    return obj if obj is not None else bill


def _cfg_impact_range(mu=None, host=None) -> float | None:
    """ImpactRange from sibling part.cfg (prefer ModuleResourceHarvester).

    Drill FX plumes are authored in .mu; cfg ImpactRange is tip contact
    distance and the best absolute-meter hint for Radial (Harvester 5.42 ≈
    tuned 5.3). Asteroid/Comet modules often list a different range — ignore
    those when the surface harvester value is present.
    """
    mudir = getattr(mu, "mudir", None) if mu is not None else None
    muname = getattr(mu, "name", None) if mu is not None else None
    if not mudir:
        return None
    try:
        from .cfg_preview import _find_part_cfg
        cfg_path = _find_part_cfg(mudir, muname or "")
    except Exception:
        cfg_path = None
    if not cfg_path or not os.path.isfile(cfg_path):
        return None
    try:
        text = open(cfg_path, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return None

    def _float_ir(block: str):
        m = re.search(r"^\s*ImpactRange\s*=\s*([0-9.+-eE]+)", block, re.M)
        if not m:
            return None
        try:
            v = float(m.group(1))
            return v if v > 0 else None
        except Exception:
            return None

    # Prefer surface harvester (same ImpactTransform the dust sits near)
    for m in re.finditer(
        r"MODULE\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text, re.S
    ):
        block = m.group(1)
        if "ModuleResourceHarvester" not in block:
            continue
        v = _float_ir(block)
        if v is not None:
            return v
    # Fallback: first ImpactRange in file
    m = re.search(r"^\s*ImpactRange\s*=\s*([0-9.+-eE]+)", text, re.M)
    if m:
        try:
            v = float(m.group(1))
            return v if v > 0 else None
        except Exception:
            pass
    return None


def _physics_travel_meters(data: dict) -> float:
    """Rough world travel from |localVelocity| × max(energy) (Unity units ≈ m)."""
    try:
        lv = data.get("localVelocity") or [0, 0, 0]
        wv = data.get("worldVelocity") or [0, 0, 0]
        speed = (
            (float(lv[0]) + float(wv[0])) ** 2
            + (float(lv[1]) + float(wv[1])) ** 2
            + (float(lv[2]) + float(wv[2])) ** 2
        ) ** 0.5
    except Exception:
        speed = 0.0
    try:
        energy = data.get("energy") or [1.0, 1.0]
        e_max = max(float(energy[0]), float(energy[1]))
    except Exception:
        e_max = 1.0
    return max(0.0, float(speed) * max(0.05, e_max))


def _deploy_end_frame(host=None, mu=None) -> int:
    """Frame when Deploy finishes — FX hidden until then.

    Prefer NLA Deploy strips. Fallback: clip length from Actions (Mu Deploy
    max_key_time×fps: Mini 2.0s→48, Radial Drill_Deploy 6.625s→159).
    """
    fps = float(getattr(bpy.context.scene.render, "fps", 24) or 24)
    fallback = max(2, int(round(2.0 * fps)))  # generic short deploy

    best = 0
    # Prefer Deploy strips on objects in the same part hierarchy as host
    host_root = host
    if host is not None:
        for _ in range(16):
            if host_root is None or host_root.parent is None:
                break
            host_root = host_root.parent

    def _same_tree(o):
        if host_root is None:
            return True
        cur = o
        for _ in range(24):
            if cur is None:
                return False
            if cur == host_root:
                return True
            cur = cur.parent
        return False

    def _is_deploy_name(blob: str) -> bool:
        return any(k in blob for k in ("deploy", "extend", "unfold"))

    for o in bpy.data.objects:
        if not _same_tree(o):
            continue
        ad = getattr(o, "animation_data", None)
        if not ad:
            continue
        for track in getattr(ad, "nla_tracks", []) or []:
            tname = (getattr(track, "name", None) or "").lower()
            for strip in getattr(track, "strips", []) or []:
                sname = (getattr(strip, "name", None) or "").lower()
                aname = ""
                try:
                    aname = (strip.action.name or "").lower() if strip.action else ""
                except Exception:
                    pass
                blob = f"{tname} {sname} {aname}"
                if not _is_deploy_name(blob):
                    continue
                try:
                    best = max(best, int(round(float(strip.frame_end))))
                except Exception:
                    pass
        # Action fallback (before NLA push / missing strips)
        act = getattr(ad, "action", None)
        if act is not None:
            aname = (act.name or "").lower()
            if _is_deploy_name(aname):
                try:
                    fr = act.frame_range
                    best = max(best, int(round(float(fr[1]))))
                except Exception:
                    pass

    if best <= 1:
        # Last resort: scan all actions in the blend for Deploy length
        for act in bpy.data.actions:
            aname = (act.name or "").lower()
            if not _is_deploy_name(aname):
                continue
            try:
                fr = act.frame_range
                best = max(best, int(round(float(fr[1]))))
            except Exception:
                pass
    if best <= 1:
        # No Deploy found. Particle-only FX (Squad/FX/*.mu exhaust plumes) have
        # no Deploy — showing them from frame 48 left GIFs/PNGs empty. Only use
        # the short-deploy fallback when the part hierarchy already has NLA
        # (likely a drill whose Deploy name we missed).
        has_nla = False
        for o in bpy.data.objects:
            if not _same_tree(o):
                continue
            ad = getattr(o, "animation_data", None)
            if ad and (ad.nla_tracks or ad.action):
                has_nla = True
                break
        if has_nla:
            return int(fallback)
        return 1
    return int(best)


def _key_fx_visibility(obj, visible_from: int):
    """Mark FX as hidden until visible_from (no Action — export-safe)."""
    if obj is None:
        return
    try:
        obj["mu_fx_visible_from"] = int(visible_from)
    except Exception:
        pass
    try:
        obj.hide_viewport = True
        obj.hide_render = True
    except Exception:
        pass
    _ensure_fx_frame_handler()


_fx_frame_handler_registered = False


def _ensure_fx_frame_handler():
    """Keep post-deploy FX visibility in sync while scrubbing the timeline."""
    global _fx_frame_handler_registered
    if _fx_frame_handler_registered:
        return

    def _on_frame(scene, depsgraph=None):
        try:
            sync_particles_preview_for_frame(int(scene.frame_current))
        except Exception:
            pass

    try:
        # Avoid duplicate handlers across re-imports
        handlers = bpy.app.handlers.frame_change_post
        handlers[:] = [
            h for h in handlers
            if getattr(h, "__name__", "") != "_mu_fx_frame_sync"
        ]
        _on_frame.__name__ = "_mu_fx_frame_sync"
        handlers.append(_on_frame)
        _fx_frame_handler_registered = True
    except Exception:
        pass


def _ensure_particle_instance_object(bill, bill_mat, host_obj, col):
    """Dedicated PS instance mesh (no TrackTo).

    Particle OBJECT instances of a TrackTo-constrained billboard often draw
    as empty wireframe boxes in the viewport while the static host shows DDS.
    """
    name = f"{host_obj.name}{FX_PINST_SUFFIX}"
    inst = None
    parents = []
    if bill is not None and bill.parent is not None:
        parents.append(bill.parent)
    parents.append(host_obj)
    for parent in parents:
        for ch in parent.children:
            if FX_PINST_SUFFIX in (ch.name or "") and is_fx_preview_object(ch):
                inst = ch
                break
        if inst is not None:
            break
    if inst is None:
        inst = bpy.data.objects.get(name)
    if inst is None:
        mesh = bill.data if bill and bill.data else _ensure_quad_mesh(
            f"mu_fx_pinst_mesh_{host_obj.name}", 0.1
        )
        inst = bpy.data.objects.new(name, mesh)
        col.objects.link(inst)
        parent = bill.parent if bill is not None else host_obj
        inst.parent = parent
        inst.matrix_parent_inverse.identity()
        inst.location = (0, 0, 0)
        inst["mu_fx_preview"] = 1
    # Never leave TrackTo on the instance object
    for con in list(inst.constraints):
        try:
            inst.constraints.remove(con)
        except Exception:
            pass
    if bill_mat is not None:
        if inst.data.materials:
            inst.data.materials[0] = bill_mat
        else:
            inst.data.materials.append(bill_mat)
    try:
        inst.display_type = "TEXTURED"
    except Exception:
        pass
    # Must stay hide_render=False — EEVEE drops OBJECT instances when the
    # instance object's hide_render is True (falls back to white dots / nothing).
    # hide_viewport keeps the source out of the viewport; an extra static copy
    # in GIF is acceptable next to .fx_preview.
    inst.hide_viewport = True
    inst.hide_render = False
    return inst


def _clear_camera_pairing(obj):
    """Remove TrackTo / locked-track / copy-rotation that couple FX to the camera."""
    if obj is None:
        return
    for con in list(getattr(obj, "constraints", []) or []):
        ctype = getattr(con, "type", "") or ""
        if ctype in ("TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK", "COPY_ROTATION"):
            try:
                obj.constraints.remove(con)
            except Exception:
                pass
    # Fixed local pose — never bake face-to-camera
    try:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    except Exception:
        pass


def create_billboard_preview(obj, mu=None):
    """Create a fixed local quad under Dust/Rocks host (no camera pairing)."""
    data = _parse_particles(obj)
    if not data:
        return None
    # Reuse existing billboard for this host only
    preview = None
    expected = f"{obj.name}{FX_PREVIEW_SUFFIX}"
    for ch in obj.children:
        if is_fx_preview_object(ch) and FX_PREVIEW_SUFFIX in (ch.name or ""):
            if (ch.name or "").startswith(obj.name) or ch.name == expected:
                preview = ch
                break

    size = _preview_billboard_size(obj, data, mu)
    # User: origin is Dust/Rocks empties under Particles^, not ImpactTransform
    parent = _fx_parent_for_host(obj)
    visible_from = _deploy_end_frame(obj, mu)
    # Static quad stays in parent-local units (Radial ~10× parent scale is the
    # look the user liked). Do NOT apply world-length shrink here — that only
    # belongs on cone travel / animated swarm sizes.

    if preview is None:
        mesh = _ensure_quad_mesh(f"mu_fx_quad_{obj.name}", size)
        name = f"{obj.name}{FX_PREVIEW_SUFFIX}"
        col = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
        preview = bpy.data.objects.new(name, mesh)
        col.objects.link(preview)
        preview.parent = parent
        preview.matrix_parent_inverse.identity()
        preview.location = (0, 0, 0)
        preview["mu_fx_preview"] = 1
    else:
        try:
            if preview.parent != parent:
                preview.parent = parent
                preview.matrix_parent_inverse.identity()
            preview.location = (0, 0, 0)
        except Exception:
            pass
        try:
            if preview.data and len(preview.data.vertices) == 4:
                _ensure_quad_mesh(preview.data.name, size)
        except Exception:
            pass

    # Static: fixed XZ quad under Dust/Rocks — never TrackTo / face-to-camera
    _clear_camera_pairing(preview)
    _key_fx_visibility(preview, visible_from)

    mat = _particle_material(obj, mu)
    mudir = getattr(mu, "mudir", None) if mu is not None else None
    # Prefer a simple billboard mat so DDS actually reads in EEVEE GIF renders.
    # Squad/FX plumes: material / _MainTex name (FlameBlueOrange, plasma2…);
    # drill dust keeps DustParticle/RockParticle.
    stem = None
    oname = (obj.name or "").lower()
    if mat is not None:
        mp = getattr(mat, "mumatprop", None)
        if mp:
            for t in mp.texture.properties:
                if t.name == "_MainTex" and t.tex:
                    stem = t.tex.rsplit(".", 1)[0]
                    break
        if not stem:
            mn = (mat.name or "").split("\u2227")[0]
            if mn and mn.lower() not in ("material", "particle"):
                stem = mn
    if not stem:
        if "rock" in oname:
            stem = "RockParticle"
        elif "dust" in oname:
            stem = "DustParticle"
        else:
            stem = "DustParticle"
    img = None
    for cand in _fx_stem_candidates(stem):
        img = _resolve_particle_image(cand, mudir)
        if img is not None:
            stem = cand
            break
    if img is None and mat is not None:
        _bind_particle_maintex(mat, mu)
        node = mat.node_tree.nodes.get("_MainTex") if mat.node_tree else None
        if node and node.image and not _image_looks_empty(node.image):
            img = node.image
    if img is None:
        img = _soft_particle_fallback_image()
    bill_mat = _make_billboard_preview_material(stem, img, host_name=(obj.name or "fx"))
    if preview.data.materials:
        preview.data.materials[0] = bill_mat
    else:
        preview.data.materials.append(bill_mat)
    # Keep stock mat bound for color animation / particle system path
    if mat is not None:
        _bind_particle_maintex(mat, mu)
        _apply_color_animation_to_material(mat, data, preview)
    return preview


def _apply_color_animation_to_material(mat, data, host_obj):
    """Bake colorAnimation[0..4] into material _TintColor / Emission if present."""
    if not mat or not data.get("doesAnimateColor"):
        return
    frames = data.get("colorAnimation") or []
    if not frames:
        return
    # Drive mumatprop color prop when available (sync handler pushes to nodes)
    prop = None
    mp = getattr(mat, "mumatprop", None)
    if mp:
        for p in mp.color.properties:
            if p.name in ("_TintColor", "_Color", "_EmissiveColor"):
                prop = p
                break
    if prop is None and mat.node_tree:
        # Set node defaults for first/last key as static hint
        node = mat.node_tree.nodes.get("_TintColor") or mat.node_tree.nodes.get("_Color")
        if node and node.inputs:
            c = frames[-1] if frames else [1, 1, 1, 1]
            try:
                node.inputs[0].default_value = (float(c[0]), float(c[1]), float(c[2]), 1.0)
                if len(node.inputs) > 1:
                    node.inputs[1].default_value = float(c[3]) if len(c) > 3 else 1.0
            except Exception:
                pass
        return

    # Keyframe prop across scene frame_start..+24 (viewport only — not exported)
    scene = bpy.context.scene
    f0 = int(scene.frame_start)
    n = max(1, len(frames) - 1)
    for i, c in enumerate(frames):
        fr = f0 + int(round(24 * i / n)) if n else f0
        try:
            prop.value = (
                float(c[0]), float(c[1]), float(c[2]),
                float(c[3]) if len(c) > 3 else 1.0,
            )
            prop.keyframe_insert(data_path="value", frame=fr)
        except Exception:
            pass
    _tag_fx_only_animation(mat)


def _tag_fx_only_animation(mat):
    """Mark Actions created for particle color preview so export skips them."""
    ad = getattr(mat, "animation_data", None) if mat else None
    if not ad:
        return

    def _tag_action(action):
        if not action:
            return
        try:
            action["mu_fx_preview"] = 1
        except Exception:
            pass

    _tag_action(getattr(ad, "action", None))
    for track in getattr(ad, "nla_tracks", []) or []:
        try:
            track["mu_fx_preview"] = 1
        except Exception:
            pass
        for strip in getattr(track, "strips", []) or []:
            _tag_action(getattr(strip, "action", None))


def _emitter_mesh_for_shape(data: dict, name: str):
    """Tiny flat emitter (not a visible UV sphere — that looked like solid balls)."""
    ext = _shape_extent(data)
    s = max(0.01, max(ext.x, ext.y, ext.z) * 0.15)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    return mesh


def _remove_fx_anim_children(parent, host_obj):
    """Delete previous .fx_anim swarm for this host only (re-import safe)."""
    if parent is None:
        return
    prefix = f"{host_obj.name}{FX_ANIM_SUFFIX}"
    for ch in list(parent.children):
        n = ch.name or ""
        if not n.startswith(prefix):
            continue
        try:
            bpy.data.objects.remove(ch, do_unlink=True)
        except Exception:
            try:
                ch.parent = None
                ch.hide_viewport = True
                ch.hide_render = True
            except Exception:
                pass


def _particle_velocity_blender(data: dict, parent=None, host=None) -> Vector:
    """Unity local/world velocity → Blender local on an already-converted empty.

    KSP drill dust uses localVelocity Y≈-2 with rnd X/Z → inverted cone out of
    the tip. Prefer the hemisphere that points away from the part root (sky /
    outward), matching in-game spray.
    """
    lv = data.get("localVelocity") or [0, 0, 0]
    wv = data.get("worldVelocity") or [0, 0, 0]
    try:
        # Unity (x,y,z) → Blender (x, z, y)
        vel = Vector((
            float(lv[0]) + float(wv[0]),
            float(lv[2]) + float(wv[2]),
            float(lv[1]) + float(wv[1]),
        ))
    except Exception:
        vel = Vector((0.0, 0.0, -0.4))
    if vel.length < 1e-5:
        vel = Vector((0.0, 0.0, -0.4))
    # Flip if velocity shoots further into the part / into the ground
    if parent is not None and host is not None:
        try:
            tip = parent.matrix_world.translation
            root = host
            for _ in range(8):
                if root.parent is None:
                    break
                root = root.parent
            away = tip - root.matrix_world.translation
            if away.length > 1e-5:
                # Continue past tip along drill = into ground; spray is opposite
                into_ground = away.normalized()
                world_vel = parent.matrix_world.to_3x3() @ vel
                if world_vel.dot(into_ground) > 0:
                    vel = -vel
        except Exception:
            pass
    return vel


def _insert_loc_scale_keys(obj, frame, loc, scale, rotation=None):
    obj.location = loc
    obj.scale = scale
    if rotation is not None:
        try:
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = rotation
        except Exception:
            pass
    try:
        obj.keyframe_insert(data_path="location", frame=frame)
        obj.keyframe_insert(data_path="scale", frame=frame)
        if rotation is not None:
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)
    except Exception:
        pass


def _avg_emission_rate(data: dict) -> float:
    """Particles/second from MuParticles.emission [min,max]."""
    emission = data.get("emission") or [10, 10]
    try:
        return max(1.0, (float(emission[0]) + float(emission[1])) * 0.5)
    except Exception:
        return 10.0


def _steady_state_count(data: dict) -> int:
    """Approx visible particles ≈ emission_rate × lifetime when count==0."""
    rate = _avg_emission_rate(data)
    energy = data.get("energy") or [1.0, 1.0]
    try:
        life = max(0.15, (float(energy[0]) + float(energy[1])) * 0.5)
    except Exception:
        life = 1.0
    return max(8, int(round(rate * life)))


def _is_stretch_render_mode(data: dict) -> bool:
    """Unity ParticleRenderMode: Stretch≈3 (also HorizontalBillboard variants)."""
    try:
        mode = int(data.get("particleRenderMode") or 0)
    except Exception:
        mode = 0
    # 3 = Stretch, 4 = HorizontalBillboard sometimes used for trails
    return mode in (3, 4)


def _cone_basis(axis: Vector):
    """Orthonormal (u, v) perpendicular to axis for radial cone spread."""
    a = axis.normalized()
    tmp = Vector((0.0, 1.0, 0.0)) if abs(a.y) < 0.9 else Vector((1.0, 0.0, 0.0))
    u = a.cross(tmp)
    if u.length < 1e-8:
        u = a.cross(Vector((0.0, 0.0, 1.0)))
    u.normalize()
    v = a.cross(u).normalized()
    return u, v


def _cone_height_world(obj, data: dict, mu=None) -> float:
    """Max cone travel in world meters from .mu physics + cfg ImpactRange.

    Preserves the tuned Mini≈1.7 / Radial≈5.3 look without part-name hardcodes:
    - Large ImpactRange (≥3, e.g. Radial 5.42) is used directly for dust+rocks.
    - Short ImpactRange (Mini 1.08) is lifted toward |vel|×max(energy)×0.85
      and capped at ImpactRange×1.6 → ≈1.7.
    - Squad/FX exhaust: clamp to a few particle diameters (vel×energy is 10m+).
    """
    phys = _physics_travel_meters(data)
    if _is_standalone_fx_mu(mu, obj):
        psz = _avg_size(data)  # not maxParticleSize-clamped
        # Continuous flame length ≈ 2.5–4× sprite, never raw |vel|×energy
        return max(0.8, min(3.5, float(psz) * 2.8))
    ir = _cfg_impact_range(mu, obj)
    if ir is not None and ir > 0.05:
        if float(ir) >= 3.0:
            return max(0.35, float(ir))
        target = phys * 0.85 if phys > 0 else float(ir)
        if target > float(ir):
            return max(0.35, min(target, float(ir) * 1.6))
        return max(0.35, float(ir))
    if phys > 0.05:
        return max(0.35, phys * 0.85)
    return 1.5


def _parent_axis_world_scale(parent, axis_local) -> float:
    """How many world meters one parent-local unit along axis becomes.

    RadialDrill hosts sit under empties with ~10× world scale while Mini is ~1×.
    Cone travel keys are parent-local, so without compensation a 5.3 m intent
    renders as ~53 m world. Divide intended world lengths by this factor.
    """
    if parent is None:
        return 1.0
    try:
        a = Vector(axis_local)
        if a.length < 1e-8:
            a = Vector((0.0, 1.0, 0.0))
        else:
            a.normalize()
        w = parent.matrix_world.to_3x3() @ a
        s = float(w.length)
        if s > 1e-6:
            return s
    except Exception:
        pass
    try:
        sc = parent.matrix_world.to_scale()
        return max(abs(float(sc.x)), abs(float(sc.y)), abs(float(sc.z)), 1e-6)
    except Exception:
        return 1.0


def _world_len_to_local(parent, axis_local, world_len: float) -> float:
    """Convert a desired world-space length to parent-local units along axis."""
    s = _parent_axis_world_scale(parent, axis_local)
    return float(world_len) / max(s, 1e-6)


def _static_quad_normal_local(bill, parent, host=None, mu=None) -> Vector:
    """Unit normal of the static XZ quad in parent-local space.

    Mesh is XZ → geometric normal is ±Y. Prefer spray toward the drill body
    (out of the hole toward the bit), opposite the tip→into-ground direction.
    """
    axis = Vector((0.0, 1.0, 0.0))
    tip_obj = parent if parent is not None else bill
    if tip_obj is None:
        return axis
    try:
        tip = tip_obj.matrix_world.translation
        root = tip_obj
        for _ in range(10):
            if root.parent is None:
                break
            root = root.parent
        into_world = tip - root.matrix_world.translation
        if into_world.length > 1e-5:
            into_l = tip_obj.matrix_world.to_3x3().inverted() @ into_world.normalized()
            # Spray opposite tip→ground (= toward drill body)
            if axis.dot(into_l) > 0:
                axis = -axis
    except Exception:
        pass
    return axis


def _sample_color_animation(frames, t_frac):
    """Lerp colorAnimation[0..4] over particle life; returns (r,g,b,a)."""
    if not frames:
        return (1.0, 1.0, 1.0, 1.0)
    n = len(frames)
    if n == 1:
        c = frames[0]
        return (float(c[0]), float(c[1]), float(c[2]), float(c[3]) if len(c) > 3 else 1.0)
    t = max(0.0, min(1.0, float(t_frac))) * (n - 1)
    i0 = int(t)
    i1 = min(n - 1, i0 + 1)
    f = t - i0
    a, b = frames[i0], frames[i1]
    out = []
    for k in range(4):
        av = float(a[k]) if k < len(a) else (1.0 if k == 3 else 0.0)
        bv = float(b[k]) if k < len(b) else (1.0 if k == 3 else 0.0)
        out.append(av * (1.0 - f) + bv * f)
    return tuple(out)


def create_timeline_particle_billboards(obj, bill, mu=None):
    """Keyframed billboard swarm under Dust/Rocks: cone + NLA after deploy."""
    data = _parse_particles(obj)
    if not data or bill is None or bill.data is None:
        return []

    parent = _fx_parent_for_host(obj, bill)
    visible_from = _deploy_end_frame(obj, mu)
    _remove_fx_anim_children(parent, obj)

    col = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    bill_mat = None
    if bill.data.materials:
        bill_mat = bill.data.materials[0]

    count = max(0, min(500, int(data.get("count") or 0)))
    # Squad/FX often ships count=0 — derive from emission×energy (true rate)
    standalone = _is_standalone_fx_mu(mu, obj)
    steady = _steady_state_count(data)
    if count >= 8:
        n_parts = min(56, max(12, count))
    elif standalone:
        n_parts = min(48, max(28, steady if steady >= 12 else 36))
    else:
        n_parts = min(28, max(10, steady if steady >= 8 else 12))
    energy = data.get("energy") or [1.0, 1.0]
    try:
        life = max(0.25, (float(energy[0]) + float(energy[1])) * 0.5)
    except Exception:
        life = 1.0
    if standalone:
        # Short life + many particles → overlapping cards = continuous plume
        life = max(0.35, min(life, 0.55))
    fps = float(getattr(bpy.context.scene.render, "fps", 24) or 24)
    life_frames = max(12 if standalone else 18, int(round(life * fps)))
    emit_rate = _avg_emission_rate(data)
    # Stagger births from emission rate (frames between births ≈ fps/rate)
    birth_gap = max(1, int(round(fps / max(1.0, emit_rate))))

    stretch_mode = _is_stretch_render_mode(data)
    try:
        length_scale = float(data.get("lengthScale") or 1.0)
    except Exception:
        length_scale = 1.0
    try:
        velocity_scale = float(data.get("velocityScale") or 0.0)
    except Exception:
        velocity_scale = 0.0
    try:
        ang_vel = float(data.get("angularVelocity") or 0.0)
    except Exception:
        ang_vel = 0.0
    try:
        rnd_ang = float(data.get("rndAngularVelocity") or 0.0)
    except Exception:
        rnd_ang = 0.0
    rnd_rot = bool(data.get("rndRotation"))
    color_frames = []
    if data.get("doesAnimateColor") and data.get("colorAnimation"):
        color_frames = list(data.get("colorAnimation") or [])

    axis = _static_quad_normal_local(bill, parent, host=obj, mu=mu)
    vel0 = _particle_velocity_blender(data, parent=parent, host=obj)
    speed = max(0.35, vel0.length)
    u, v = _cone_basis(axis)
    # Intended world meters → parent-local (Radial Dust∧ is ~10× world scale)
    world_height = _cone_height_world(obj, data, mu)
    max_travel = _world_len_to_local(parent, axis, world_height)
    axis_scale = _parent_axis_world_scale(parent, axis)
    rv = data.get("rndVelocity") or [0.4, 0.0, 0.4]
    try:
        rad_w = max(0.15, 0.5 * (abs(float(rv[0])) + abs(float(rv[2]))))
        axis_jit_w = abs(float(rv[1])) * 0.25
    except Exception:
        rad_w = 0.4
        axis_jit_w = 0.0
    # Radial spread in world meters, then to local (readable plume width).
    # Keep a floor so chips clear thick drill shafts (Radial bit ~0.4 m).
    rad_w = min(rad_w, max(0.08, world_height * 0.22))
    rad_w = max(rad_w, min(0.65, world_height * 0.12))
    if standalone:
        rad_w = min(rad_w, max(0.04, world_height * 0.14))
    rad = rad_w / max(axis_scale, 1e-6)
    axis_jit = axis_jit_w / max(axis_scale, 1e-6)
    speed = speed / max(axis_scale, 1e-6)
    try:
        size_grow = float(data.get("sizeGrow") or 0.0)
    except Exception:
        size_grow = 0.0
    size = _preview_billboard_size(obj, data, mu)
    is_rocks = "rock" in (obj.name or "").lower()
    # Rocks: readable chips vs dust plume. Absolute Mini-sized meters vanish on
    # Radial (host ×10 + ImpactRange ~5 m) — size from plume height + mu size.
    if is_rocks:
        # ~8–12% of cone height, clamped; stock rock size is ~half of dust
        mesh_size_w = max(0.12, min(world_height * 0.10, 0.55))
        mesh_size_w = max(mesh_size_w, min(size * 0.85, 0.35))
    else:
        mesh_size_w = max(0.04, size * 0.55)
        # Longer-lived dust (energy max > 2, e.g. Radial) → slightly larger swarm quads
        try:
            e = data.get("energy") or [1.0, 1.0]
            if max(float(e[0]), float(e[1])) > 2.0:
                mesh_size_w *= 1.5
        except Exception:
            pass
    mesh_size = mesh_size_w / max(axis_scale, 1e-6)

    mesh_name = f"mu_fx_anim_mesh_{obj.name}"[:60]
    mesh = _ensure_quad_mesh(mesh_name, mesh_size)

    birth_center = Vector((0.0, 0.0, 0.0))
    # shape1d is Sphere radius (~0.01 on drills); keep a readable minimum
    try:
        shape_r = abs(float(data.get("shape1d") or 0.01))
    except Exception:
        shape_r = 0.01
    birth_jit_w = max(0.02, min(0.08, shape_r * 6.0))
    birth_jit = birth_jit_w / max(axis_scale, 1e-6)
    birth_jit_y = (birth_jit_w * 0.35) / max(axis_scale, 1e-6)

    rng = random.Random(hash(obj.name or "fx") & 0xFFFFFFFF)
    created = []
    # Key from frame 1 so Operate/Running clips authored at 1..N (Radial
    # Drill_Running=1..25) still drive FX when force-shown in GIF. Visibility
    # stays gated by mu_fx_visible_from until Deploy ends.
    f_start = 1
    span = 200
    cycles = max(2, int(span // max(8, life_frames + 4)))
    # Rocks: always emit a visible swarm (stock count is tiny on Radial)
    if is_rocks:
        n_parts = min(18, max(14, n_parts))
    # Stagger from emission rate; standalone keeps tighter overlap
    if standalone:
        stagger = max(1, min(birth_gap, life_frames // max(6, n_parts // 2)))
    else:
        stagger = birth_gap

    for i in range(n_parts):
        name = f"{obj.name}{FX_ANIM_SUFFIX}.{i:02d}"
        o = bpy.data.objects.new(name, mesh)
        col.objects.link(o)
        o.parent = parent
        o.matrix_parent_inverse.identity()
        o["mu_fx_preview"] = 1
        _clear_camera_pairing(o)
        try:
            o.display_type = "TEXTURED"
            o.color = (1.0, 1.0, 1.0, 1.0)
        except Exception:
            pass
        if bill_mat is not None:
            if o.data.materials:
                o.data.materials[0] = bill_mat
            else:
                o.data.materials.append(bill_mat)

        # Base orientation; spin keyed over life from angularVelocity
        try:
            o.rotation_mode = "XYZ"
            if rnd_rot:
                base_rot = (
                    rng.uniform(0, math.tau),
                    rng.uniform(0, math.tau),
                    rng.uniform(0, math.tau),
                )
            else:
                base_rot = (0.0, 0.0, rng.uniform(0, math.tau) if rnd_ang else 0.0)
            o.rotation_euler = base_rot
        except Exception:
            base_rot = (0.0, 0.0, 0.0)

        spin_rate = ang_vel + (rng.random() * 2.0 - 1.0) * rnd_ang

        if o.animation_data:
            try:
                o.animation_data_clear()
            except Exception:
                o.animation_data_create()

        act = bpy.data.actions.new(name=f"MuParticles_{obj.name}_{i:02d}"[:60])
        try:
            act["mu_fx_preview"] = 1
        except Exception:
            pass
        ensure_action_assigned(o, act)

        phase = int(i * stagger) % max(1, life_frames)
        birth0 = f_start + phase

        for cyc in range(cycles):
            gap = 3 if standalone else 6
            birth = birth0 + cyc * (life_frames + gap)
            start = birth_center + Vector((
                (rng.random() - 0.5) * birth_jit,
                (rng.random() - 0.5) * birth_jit_y,
                (rng.random() - 0.5) * birth_jit,
            ))
            theta = rng.random() * math.tau
            cone = rad * (0.55 + 0.9 * rng.random())
            dir_vec = (
                axis * (speed + (rng.random() - 0.5) * 2.0 * axis_jit)
                + (math.cos(theta) * u + math.sin(theta) * v) * cone
            )
            # Fixed absolute cone height in world meters (Mini 1.7 / Radial 5.3)
            travel = float(max_travel) * (0.75 + 0.25 * rng.random())
            if is_rocks:
                travel = float(max_travel) * (0.45 + 0.40 * rng.random())
            if dir_vec.length > 1e-6:
                disp = dir_vec.normalized() * travel
            else:
                disp = axis * travel
            grow = 1.0 + max(0.0, size_grow) * min(life, 2.5)
            if is_rocks:
                grow = max(grow, 1.15)
            s_birth = 0.12 + 0.18 * rng.random()
            s_mid = (0.85 + 0.55 * rng.random()) * max(1.0, grow * 0.65)
            s_peak = (1.15 + 0.55 * rng.random()) * max(1.0, grow)
            if is_rocks:
                s_birth = 0.35 + 0.25 * rng.random()
                s_mid = 0.85 + 0.40 * rng.random()
                s_peak = 1.15 + 0.45 * rng.random()
            s_fade = 0.02
            # Stretch along velocity: elongate local Y (billboard plane) by length/vel
            stretch_mul = 1.0
            if stretch_mode:
                stretch_mul = max(
                    1.0,
                    abs(length_scale) + abs(velocity_scale) * max(0.2, speed) * 0.35,
                )
            keys = (
                (0.0, start, (s_birth, s_birth, s_birth)),
                (0.25, start + disp * 0.25, (s_mid, s_mid * stretch_mul, s_mid)),
                (0.60, start + disp * 0.60, (s_peak, s_peak * stretch_mul, s_peak)),
                (0.85, start + disp * 0.85, (s_peak * 0.55, s_peak * 0.55 * stretch_mul, s_peak * 0.55)),
                (1.0, start + disp, (s_fade, s_fade, s_fade)),
            )
            for t_frac, loc, scl in keys:
                fr = birth + int(round(life_frames * t_frac))
                spin = spin_rate * life * t_frac
                rot = (
                    base_rot[0],
                    base_rot[1],
                    base_rot[2] + spin,
                )
                _insert_loc_scale_keys(o, fr, loc, scl, rotation=rot)
                if color_frames:
                    rgba = _sample_color_animation(color_frames, t_frac)
                    try:
                        o.color = rgba
                        o.keyframe_insert(data_path="color", frame=fr)
                    except Exception:
                        pass

        track, _strip = push_action_to_nla(o, act, "MuParticles")
        try:
            if track is not None:
                track["mu_fx_preview"] = 1
        except Exception:
            pass
        _key_fx_visibility(o, visible_from)
        created.append(o)

    return created


def create_particle_system_preview(obj, mu=None):
    """Legacy Particle System preview (kept for API; prefer timeline billboards).

    OBJECT instances do not land on the Dope Sheet/NLA and often fail to draw
    after Toggle Particles — create_timeline_particle_billboards is preferred.
    """
    data = _parse_particles(obj)
    if not data:
        return None
    for ch in obj.children:
        if is_fx_preview_object(ch) and FX_EMITTER_SUFFIX in (ch.name or ""):
            return ch

    mesh = _emitter_mesh_for_shape(data, f"mu_fx_emit_mesh_{obj.name}")
    name = f"{obj.name}{FX_EMITTER_SUFFIX}"
    col = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    emitter = bpy.data.objects.new(name, mesh)
    col.objects.link(emitter)
    emitter.parent = obj
    emitter.matrix_parent_inverse.identity()
    emitter.location = (0, 0, 0)
    emitter["mu_fx_preview"] = 1
    # Emitter geometry must NOT read as solid "balls" in viewport/GIF.
    emitter.show_instancer_for_viewport = False
    emitter.show_instancer_for_render = False
    try:
        emitter.hide_render = True
        emitter.hide_viewport = True
        emitter.display_type = "WIRE"
    except Exception:
        pass

    count = max(1, min(500, int(data.get("count") or 50)))
    emission = data.get("emission") or [10, 10]
    try:
        emit_rate = max(1.0, (float(emission[0]) + float(emission[1])) * 0.5)
    except Exception:
        emit_rate = 10.0
    energy = data.get("energy") or [1.0, 1.0]
    try:
        life = max(0.05, (float(energy[0]) + float(energy[1])) * 0.5)
    except Exception:
        life = 1.0
    size = _avg_size(data)

    # Emitter must be active for particle_system_add in some Blender builds
    try:
        bpy.context.view_layer.objects.active = emitter
        emitter.select_set(True)
        bpy.ops.object.particle_system_add()
    except Exception:
        # Manual particle settings
        psys = emitter.modifiers.new(name="MuParticles", type="PARTICLE_SYSTEM")
        del psys  # noqa — settings via particle_systems
    if not emitter.particle_systems:
        return emitter

    psys = emitter.particle_systems[-1]
    psys.name = "MuParticles"
    settings = psys.settings
    settings.count = count
    # Cover Deploy→Operate GIF scrub (stock life windows die before Drill)
    fps = float(getattr(bpy.context.scene.render, "fps", 24) or 24)
    settings.frame_start = 1
    settings.frame_end = 250
    settings.lifetime = max(12.0, min(90.0, life * fps * 1.5))
    settings.emit_from = "FACE"
    settings.physics_type = "NEWTON"
    settings.particle_size = size
    settings.size_random = 0.35
    settings.normal_factor = 0.0
    try:
        settings.use_dead = False
    except Exception:
        pass
    # Velocities (Unity local → Blender Y/Z swap approx: use as-is for preview)
    lv = data.get("localVelocity") or [0, 0, 0]
    wv = data.get("worldVelocity") or [0, 0, 0]
    rv = data.get("rndVelocity") or [0, 0, 0]
    try:
        settings.object_align_factor = (
            float(lv[0]) + float(wv[0]),
            float(lv[2]) + float(wv[2]),
            float(lv[1]) + float(wv[1]),
        )
        settings.factor_random = min(2.0, max(abs(float(x)) for x in rv) * 0.5 + 0.01)
    except Exception:
        pass
    force = data.get("force") or [0, 0, 0]
    try:
        # effector weights / brownian as rough stand-in
        settings.brownian_factor = min(2.0, abs(float(force[1])) * 0.1)
        settings.drag_factor = min(1.0, float(data.get("damping") or 0))
    except Exception:
        pass

    render_mode = int(data.get("particleRenderMode") or 0)
    # Prefer textured OBJECT billboards (HALO = solid balls — wrong for KSP FX).
    settings.render_type = "OBJECT"
    if render_mode in (3, 4):
        settings.render_type = "LINE"
        try:
            settings.length_random = min(1.0, float(data.get("lengthScale") or 0.5))
        except Exception:
            pass

    mat = _particle_material(obj, mu)
    if mat:
        _bind_particle_maintex(mat, mu)
        try:
            settings.material_slot = 1
        except Exception:
            pass
        if emitter.data.materials:
            emitter.data.materials[0] = mat
        else:
            emitter.data.materials.append(mat)
        bill = None
        for ch in obj.children:
            if FX_PREVIEW_SUFFIX in (ch.name or ""):
                bill = ch
                break
        if bill is None:
            for ch in obj.children:
                if FX_PREVIEW_SUFFIX in (ch.name or ""):
                    bill = ch
                    break
        if bill is not None:
            # Keep the simple billboard mat (already assigned); do not overwrite
            # with stock KSP particle graph (opaque grey in EEVEE GIF).
            bill_mat = None
            if bill.data and bill.data.materials:
                bill_mat = bill.data.materials[0]
            if bill_mat is not None:
                if emitter.data.materials:
                    emitter.data.materials[0] = bill_mat
                else:
                    emitter.data.materials.append(bill_mat)
            # Dedicated instance mesh COPY (no TrackTo) — same DDS as static bill
            pinst = _ensure_particle_instance_object(
                bill, bill_mat, obj, col
            )
            # Prefer a mesh copy so TrackTo on the billboard never affects PS
            try:
                if bill.data and (
                    pinst.data is None or pinst.data == bill.data
                ):
                    pinst.data = bill.data.copy()
                    pinst.data.name = f"mu_fx_pinst_mesh_{obj.name}"[:60]
                    if bill_mat is not None:
                        if pinst.data.materials:
                            pinst.data.materials[0] = bill_mat
                        else:
                            pinst.data.materials.append(bill_mat)
            except Exception:
                pass
            settings.render_type = "OBJECT"
            settings.instance_object = pinst
            settings.particle_size = 1.0
            try:
                settings.use_scale_instance = True
                settings.use_rotation_instance = False
                settings.use_rotations = False
                settings.display_method = "RENDER"
                settings.display_percentage = 100
            except Exception:
                pass
            # Keep billboard hidden until operate / Options Toggle
            try:
                settings["mu_rt_saved"] = "OBJECT"
                settings.render_type = "NONE"
            except Exception:
                pass
            try:
                bill.hide_render = True
                bill.hide_viewport = True
            except Exception:
                pass
            try:
                pinst.hide_viewport = True
                pinst.hide_render = False
            except Exception:
                pass
        else:
            # No billboard: soft halo with material (still better than solid)
            settings.render_type = "HALO"

    # Color over life
    if data.get("doesAnimateColor") and data.get("colorAnimation"):
        try:
            settings.color_maximum = 1.0
            # Use material keyframes from billboard path instead
        except Exception:
            pass

    # Approximate continuous emission
    try:
        settings.use_emit_random = True
        settings.timestep = 1.0 / max(1.0, emit_rate)
    except Exception:
        pass

    return emitter


def _face_billboards_to_camera(cam=None):
    """No-op (legacy). Static FX must never pair with the camera."""
    return


def sync_particles_preview_for_frame(frame=None):
    """Apply post-deploy visibility from mu_fx_visible_from (GIF / scrub)."""
    try:
        fr = int(frame if frame is not None else bpy.context.scene.frame_current)
    except Exception:
        fr = 1
    force_label = ""
    try:
        force_label = str(
            bpy.context.scene.get("mu_preview_fx_force", "") or ""
        ).strip()
    except Exception:
        force_label = ""

    def _host_label_of_fx_obj(o):
        n = o.name or ""
        base = n
        for suf in (FX_ANIM_SUFFIX, FX_PREVIEW_SUFFIX, FX_EMITTER_SUFFIX):
            if suf in base:
                base = base.split(suf)[0]
                break
        try:
            from ..utils import strip_nnn
            return strip_nnn(base) or base
        except Exception:
            return base.rstrip("\u2227")

    for o in list(bpy.data.objects):
        n = o.name or ""
        if not (
            o.get("mu_fx_preview")
            or FX_PREVIEW_SUFFIX in n
            or FX_ANIM_SUFFIX in n
        ):
            continue
        if FX_EMITTER_SUFFIX in n or FX_PINST_SUFFIX in n:
            continue
        # Preview Clip → Dust/Rocks: keep that host visible while scrubbing
        if force_label:
            hide = _host_label_of_fx_obj(o) != force_label
            try:
                o.hide_viewport = hide
                o.hide_render = hide
            except Exception:
                pass
            continue
        try:
            vf = int(o.get("mu_fx_visible_from") or 1)
        except Exception:
            vf = 1
        hide = fr < vf
        try:
            o.hide_viewport = hide
            o.hide_render = hide
        except Exception:
            pass
        # Keep particle DDS alpha readable (RockParticle is sparse — CHANNEL_PACKED
        # drops chips to invisible while Dust still faintly draws).
        if not hide and o.data and o.data.materials:
            mat = o.data.materials[0]
            if mat is not None and mat.node_tree:
                node = mat.node_tree.nodes.get("_MainTex")
                if node is not None and node.image is not None:
                    try:
                        if node.image.alpha_mode == "CHANNEL_PACKED":
                            node.image.alpha_mode = "STRAIGHT"
                    except Exception:
                        pass


def set_particles_preview_visible(visible):
    """Show/hide FX billboards (Toggle Particles).

    When showing, still honor mu_fx_visible_from vs current frame so Deploy
    scrub stays clean; Toggle at/after deploy end reveals dust.
    """
    try:
        fr = int(bpy.context.scene.frame_current)
    except Exception:
        fr = 1
    for o in list(bpy.data.objects):
        n = o.name or ""
        is_emit = FX_EMITTER_SUFFIX in n
        is_pinst = FX_PINST_SUFFIX in n
        is_anim = FX_ANIM_SUFFIX in n
        is_bill = (
            (bool(o.get("mu_fx_preview")) or (FX_PREVIEW_SUFFIX in n) or is_anim)
            and not is_emit
            and not is_pinst
        )
        if is_pinst:
            try:
                o.hide_viewport = True
                o.hide_render = False
            except Exception:
                pass
            continue
        if is_emit:
            try:
                o.hide_render = not visible
                o.hide_viewport = not visible
            except Exception:
                pass
            for psys in o.particle_systems:
                settings = psys.settings
                if not settings:
                    continue
                try:
                    if "mu_rt_saved" not in settings:
                        settings["mu_rt_saved"] = settings.render_type
                    settings.render_type = (
                        (settings.get("mu_rt_saved") or "OBJECT")
                        if visible else "NONE"
                    )
                except Exception:
                    try:
                        settings.render_type = "OBJECT" if visible else "NONE"
                    except Exception:
                        pass
            continue
        if not is_bill:
            continue
        if FX_PREVIEW_SUFFIX in n and FX_ANIM_SUFFIX not in n:
            _clear_camera_pairing(o)
        try:
            vf = int(o.get("mu_fx_visible_from") or 1)
        except Exception:
            vf = 1
        if not visible:
            hide = True
        else:
            # Options → Toggle Particles: force show for inspection
            hide = False
        try:
            o.hide_render = hide
            o.hide_viewport = hide
        except Exception:
            pass
        if visible and o.data and o.data.materials:
            mat = o.data.materials[0]
            if mat is not None:
                _ensure_particle_mat_blend(mat)
                node = mat.node_tree.nodes.get("_MainTex") if mat.node_tree else None
                if node is not None and node.image is not None:
                    try:
                        if node.image.alpha_mode == "CHANNEL_PACKED":
                            node.image.alpha_mode = "STRAIGHT"
                    except Exception:
                        pass


def _fx_parent_is(host, obj):
    cur = obj
    for _ in range(8):
        if cur is None:
            return False
        if cur == host:
            return True
        cur = cur.parent
    return False


def _fx_objects_for_host(host):
    """Billboard / swarm preview objects belonging to a MuParticles host."""
    if host is None:
        return []
    host_name = host.name or ""
    out = []
    stack = list(host.children)
    seen = set()
    while stack:
        o = stack.pop()
        if o is None:
            continue
        key = o.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        stack.extend(list(o.children))
        n = o.name or ""
        if not (
            o.get("mu_fx_preview")
            or FX_PREVIEW_SUFFIX in n
            or FX_ANIM_SUFFIX in n
            or FX_EMITTER_SUFFIX in n
        ):
            continue
        if FX_PINST_SUFFIX in n:
            continue
        if n.startswith(host_name) or _fx_parent_is(host, o):
            out.append(o)
    return out


def set_particles_preview_for_host(host, visible, force=True):
    """Show/hide FX preview for one Dust/Rocks-style MuParticles host.

    ``force=True`` ignores mu_fx_visible_from (Preview Clip inspection).
    """
    if host is None:
        return
    try:
        fr = int(bpy.context.scene.frame_current)
    except Exception:
        fr = 1
    for o in _fx_objects_for_host(host):
        n = o.name or ""
        if FX_EMITTER_SUFFIX in n:
            try:
                o.hide_viewport = not visible
                o.hide_render = not visible
            except Exception:
                pass
            continue
        if not visible:
            hide = True
        elif force:
            hide = False
        else:
            try:
                vf = int(o.get("mu_fx_visible_from") or 1)
            except Exception:
                vf = 1
            hide = fr < vf
        try:
            o.hide_viewport = hide
            o.hide_render = hide
        except Exception:
            pass
        if visible and not hide and o.data and getattr(o.data, "materials", None):
            mat = o.data.materials[0] if o.data.materials else None
            if mat is not None:
                try:
                    _ensure_particle_mat_blend(mat)
                except Exception:
                    pass


def particle_fx_host_label(obj):
    """Preview Clip enum id for a MuParticles host (Dust / Rocks)."""
    if obj is None:
        return ""
    try:
        from ..utils import strip_nnn
        return strip_nnn(obj.name) or ""
    except Exception:
        raw = obj.name or ""
        ind = raw.rfind("\u2227")
        if ind >= 0:
            raw = raw[:ind]
        return raw


def attach_particles_preview(obj, mu=None):
    """Create static billboard + keyframed .fx_anim swarm under Dust/Rocks host."""
    if not obj or not _parse_particles(obj):
        return
    try:
        bill = create_billboard_preview(obj, mu)
    except Exception as e:
        print(f"WARNING: fx billboard preview failed on {obj.name}: {e}")
        bill = None
    try:
        create_timeline_particle_billboards(obj, bill, mu)
    except Exception as e:
        print(f"WARNING: fx timeline particle preview failed on {obj.name}: {e}")
    try:
        sync_particles_preview_for_frame(1)
    except Exception:
        pass
    return bill
