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
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>
"""ModuleLight flare mesh preview (gear / lamp halo).

KSP ModuleLight looks up a transform named Flare (flareRendererName, default
"Flare"). Stock landing gear ship a cross-card mesh with
KSP/Alpha/Translucent Additive + Flare.dds — a soft additive halo, not
particles and not a Unity LensFlare asset.

In Blender 5.2 EEVEE, shadow_method=NONE from the shader .cfg is ignored, and
castShadows=True from the .mu sets visible_shadow. With
use_transparent_shadow=False the invisible additive card still stamps an
opaque shadow silhouette onto part textures. This module:

* disables viewport/render shadow casting on flare meshes (export flags untouched)
* rebuilds an EEVEE-readable additive glow (DDS alpha is unused / always 1)
* keeps stock mumatprop for round-trip export
"""

from __future__ import annotations

import re

import bpy


MU_LIGHT_FLARE_KEY = "mu_light_flare"


def _object_key(name: str) -> str:
    n = (name or "").split("\u2227")[0]
    if "." in n:
        base, suf = n.rsplit(".", 1)
        if suf.isdigit():
            n = base
    return n.strip()


def _shader_name(mat) -> str:
    try:
        return (mat.mumatprop.shaderName or "") if mat else ""
    except Exception:
        return ""


def _is_additive_or_translucent(shader: str) -> bool:
    low = (shader or "").lower()
    return ("additive" in low) or ("translucent" in low) or ("particle" in low)


def is_flare_object(obj, flare_names=None) -> bool:
    """True for ModuleLight flare renderer meshes."""
    if obj is None or obj.type != "MESH":
        return False
    if obj.get(MU_LIGHT_FLARE_KEY):
        return True
    key = _object_key(obj.name or "").lower()
    names = flare_names or {"flare"}
    if key in names or key.startswith("flare"):
        return True
    for slot in getattr(obj, "material_slots", []) or []:
        mat = slot.material
        if not mat:
            continue
        sh = _shader_name(mat)
        if not _is_additive_or_translucent(sh):
            continue
        mname = (mat.name or "").lower()
        if "flare" in mname or "flare" in key:
            return True
        try:
            for tp in mat.mumatprop.texture.properties:
                if tp.name == "_MainTex" and "flare" in (tp.tex or "").lower():
                    return True
        except Exception:
            pass
    return False


def parse_module_light_flare_names(cfg_text: str) -> set:
    """Collect flareRendererName values from ModuleLight blocks (default Flare)."""
    names = set()
    if not cfg_text or "ModuleLight" not in cfg_text:
        return {"flare"}
    for block in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = block.end() - 1
        depth = 0
        i = start
        body = None
        while i < len(cfg_text):
            if cfg_text[i] == "{":
                depth += 1
            elif cfg_text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        if not body:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm or nm.group(1).strip().strip('"') != "ModuleLight":
            continue
        fr = re.search(r"^\s*flareRendererName\s*=\s*(.+)$", body, re.M | re.I)
        if fr:
            names.add(fr.group(1).strip().strip('"').split("//")[0].strip().lower())
        else:
            names.add("flare")
    return names or {"flare"}


def disable_flare_shadows(obj) -> None:
    """Stop EEVEE opaque silhouettes from additive flare cards."""
    if obj is None:
        return
    try:
        obj.visible_shadow = False
    except Exception:
        pass
    try:
        obj.visible_diffuse = True
        obj.visible_glossy = True
        obj.visible_transmission = True
        obj.visible_volume_scatter = False
    except Exception:
        pass
    for slot in getattr(obj, "material_slots", []) or []:
        mat = slot.material
        if not mat:
            continue
        try:
            mat.use_transparent_shadow = False
        except Exception:
            pass
        try:
            if hasattr(mat, "shadow_method"):
                mat.shadow_method = "NONE"
        except Exception:
            pass
        try:
            mat.blend_method = "BLEND"
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "BLENDED"
        except Exception:
            pass


def _find_maintex_image(mat):
    if not mat or not mat.node_tree:
        return None
    node = mat.node_tree.nodes.get("_MainTex")
    if node is not None and getattr(node, "image", None) is not None:
        return node.image
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image is not None:
            return n.image
    try:
        for tp in mat.mumatprop.texture.properties:
            if tp.name == "_MainTex" and tp.tex:
                img = bpy.data.images.get(tp.tex)
                if img is not None:
                    return img
    except Exception:
        pass
    return None


def _tint_rgb(mat):
    """RGB from stock _TintColor (ignore near-zero alpha — ModuleLight OFF in asset)."""
    rgb = (0.82, 0.82, 0.72)
    try:
        for p in mat.mumatprop.color.properties:
            if p.name != "_TintColor":
                continue
            v = list(p.value)
            if len(v) >= 3:
                rgb = (float(v[0]), float(v[1]), float(v[2]))
            break
    except Exception:
        pass
    return rgb


def _new_mix_rgb(nt):
    """Blender 5 prefers ShaderNodeMix; fall back to MixRGB."""
    try:
        n = nt.nodes.new("ShaderNodeMix")
        try:
            n.data_type = "RGBA"
        except Exception:
            pass
        try:
            n.blend_type = "MULTIPLY"
        except Exception:
            pass
        return n, True
    except Exception:
        n = nt.nodes.new("ShaderNodeMixRGB")
        try:
            n.blend_type = "MULTIPLY"
        except Exception:
            pass
        return n, False


def rebuild_flare_additive_material(mat) -> bool:
    """Replace node graph with Emission x Transparent additive halo (preview only).

    Stock Flare.dds stores the glow in RGB; alpha is constantly 1 / CHANNEL_PACKED,
    so TintA*TexA stays dead when ModuleLight leaves _TintColor.a=0. Export still
    reads mumatprop / texture names — nodes are viewport-only.
    """
    if not mat:
        return False
    img = _find_maintex_image(mat)
    tint = _tint_rgb(mat)
    try:
        mat["mu_flare_preview_mat"] = 1
    except Exception:
        pass
    try:
        mat.blend_method = "BLEND"
    except Exception:
        pass
    try:
        mat.surface_render_method = "BLENDED"
    except Exception:
        pass
    try:
        mat.use_transparent_shadow = False
    except Exception:
        pass
    try:
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "NONE"
    except Exception:
        pass

    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (420, 0)

    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (220, 0)

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.name = "Emission"
    emit.location = (20, 80)
    emit.inputs[1].default_value = 3.0

    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    trans.location = (20, -80)

    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.name = "_MainTex"
    tex.label = "_MainTex"
    tex.location = (-360, 40)
    if img is not None:
        tex.image = img
        try:
            img.alpha_mode = "STRAIGHT"
        except Exception:
            pass

    tint_node = nt.nodes.new("ShaderNodeRGB")
    tint_node.name = "_TintColor"
    tint_node.label = "_TintColor"
    tint_node.location = (-360, -160)
    tint_node.outputs[0].default_value = (tint[0], tint[1], tint[2], 1.0)

    mul, is_mix = _new_mix_rgb(nt)
    mul.location = (-120, 60)
    # Fac / A socket
    try:
        mul.inputs[0].default_value = 1.0
    except Exception:
        pass

    try:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
    except Exception:
        sep = nt.nodes.new("ShaderNodeSeparateRGB")
    sep.location = (-120, -120)

    vmax = nt.nodes.new("ShaderNodeMath")
    vmax.operation = "MAXIMUM"
    vmax.location = (40, -140)
    vmax2 = nt.nodes.new("ShaderNodeMath")
    vmax2.operation = "MAXIMUM"
    vmax2.location = (40, -280)

    # Mix color sockets: ShaderNodeMix uses A/B or Color1/Color2
    def _mix_in(node, which):
        for name in (("A", "B") if which == 0 else ("B", "A")):
            if name in node.inputs:
                return node.inputs[name]
        # MixRGB: Color1=1, Color2=2
        idx = 1 if which == 0 else 2
        return node.inputs[idx]

    nt.links.new(tex.outputs[0], _mix_in(mul, 0))
    nt.links.new(tint_node.outputs[0], _mix_in(mul, 1))
    # Mix output
    mout = mul.outputs.get("Result") or mul.outputs.get("Color") or mul.outputs[0]
    nt.links.new(mout, emit.inputs[0])
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
    nt.links.new(vmax2.outputs[0], mix.inputs[0])
    nt.links.new(trans.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return True


def _iter_meshes_under(root):
    if root is None:
        for o in bpy.data.objects:
            if o.type == "MESH":
                yield o
        return
    stack = [root]
    seen = set()
    while stack:
        o = stack.pop()
        if o.name in seen:
            continue
        seen.add(o.name)
        if o.type == "MESH":
            yield o
        stack.extend(list(o.children))


def attach_flare_preview(root, cfg_text: str = None) -> int:
    """Tag ModuleLight flare meshes, kill shadows, rebuild additive glow.

    Returns number of flare objects handled.
    """
    flare_names = parse_module_light_flare_names(cfg_text or "")
    flare_names.add("flare")
    count = 0
    for obj in list(_iter_meshes_under(root)):
        if not is_flare_object(obj, flare_names):
            hit = False
            for slot in getattr(obj, "material_slots", []) or []:
                mat = slot.material
                if not mat:
                    continue
                if (mat.name or "").lower() == "flare" and _is_additive_or_translucent(
                    _shader_name(mat)
                ):
                    hit = True
                    break
            if not hit:
                continue
        try:
            obj[MU_LIGHT_FLARE_KEY] = 1
        except Exception:
            pass
        disable_flare_shadows(obj)
        for slot in getattr(obj, "material_slots", []) or []:
            mat = slot.material
            if not mat:
                continue
            try:
                rebuild_flare_additive_material(mat)
            except Exception as e:
                print(f"WARNING: flare material preview on {obj.name}: {e}")
        count += 1
    return count


def mesh_should_skip_viewport_shadows(obj, renderer=None) -> bool:
    """True when Unity transparent/additive would not stamp opaque EEVEE shadows."""
    if obj is not None and obj.get(MU_LIGHT_FLARE_KEY):
        return True
    if is_flare_object(obj):
        return True
    for slot in getattr(obj, "material_slots", []) or []:
        mat = slot.material
        if mat and _is_additive_or_translucent(_shader_name(mat)):
            return True
    return False