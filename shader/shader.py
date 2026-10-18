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

import sys, traceback

import bpy
from bpy.types import bpy_prop_array
from mathutils import Vector

from .shader_config import shader_configs

typemap = {
    'VALUE': "NodeSocketFloat",
    'RGBA': "NodeSocketColor",
    'SHADER': "NodeSocketShader",
}

use_index = { None, "Vector", "Value", "Shader" }

# Blender 4.0+/5.x removed legacy RGB/MixRGB/EeveeSpecular node types.
NODE_TYPE_MAP = {
    "ShaderNodeSeparateRGB": "ShaderNodeSeparateColor",
    "ShaderNodeCombineRGB": "ShaderNodeCombineColor",
    "ShaderNodeMixRGB": "ShaderNodeMix",
    "ShaderNodeEeveeSpecular": "ShaderNodeBsdfPrincipled",
}

# Ordered aliases: first match wins when looking up sockets by CFG name.
SOCKET_NAME_ALIASES = {
    "Image": ("Color", "Image"),
    "R": ("Red", "R"),
    "G": ("Green", "G"),
    "B": ("Blue", "B"),
    "Fac": ("Factor", "Fac"),
    "Color1": ("A", "Color1"),
    "Color2": ("B", "Color2"),
    "Specular": ("Specular IOR Level", "Specular"),
    "Emissive Color": ("Emission Color", "Emission", "Emissive Color"),
    "Transparency": ("Alpha", "Transparency"),
    "Clear Coat": ("Coat Weight", "Clearcoat", "Clear Coat"),
    "Clear Coat Roughness": ("Coat Roughness", "Clearcoat Roughness", "Clear Coat Roughness"),
    "Coat Normal": ("Coat Normal", "Clearcoat Normal", "Clear Coat Normal"),
}

# Material RNA props removed or relocated since Blender 4.x — skip quietly.
IGNORED_MATERIAL_PROPS = {
    "shadow_method",
    "alpha_threshold",
    "specular_color",
    "specular_intensity",
    "use_sss_translucency",
    "refraction_depth",
    "use_screen_refraction",
}

# Node props that do not exist on remapped types (handled specially).
IGNORED_NODE_PROPS = {
    "use_alpha",  # MixRGB; ShaderNodeMix has no direct equivalent
}

def parse_value(valstr):
    valstr = valstr.strip()
    if valstr in {"False", "false"}:
        return False
    if valstr in {"True", "true"}:
        return True
    if not valstr or valstr[0].isalpha() or valstr[0] in ["_"]:
        return valstr
    return eval(valstr)

def set_property(obj, prop, valstr):
    if prop in IGNORED_MATERIAL_PROPS or prop in IGNORED_NODE_PROPS:
        return
    # MixRGB use_clamp → ShaderNodeMix clamp_factor / clamp_result
    if prop == "use_clamp" and not hasattr(obj, "use_clamp"):
        if hasattr(obj, "clamp_factor"):
            prop = "clamp_factor"
        elif hasattr(obj, "clamp_result"):
            prop = "clamp_result"
        else:
            return
    if not hasattr(obj, prop):
        # blend_method values like HASHED still exist; other missing props stay quiet
        if prop in IGNORED_MATERIAL_PROPS:
            return
        print(f"WARNING: {obj} {prop} unknown property (old cfg?)")
        return
    attr = getattr(obj, prop)
    if type(attr) == bool:
        if valstr in {"False", "false"}:
            value = False
        if valstr in {"True", "true"}:
            value = True
    elif type(attr) == str:
        if valstr and valstr[0] in ['"', "'"]:
            value = eval(valstr)
        else:
            value = valstr
    else:
        value = eval(valstr)
    if type(attr) == bpy_prop_array:
        if type(value) not in [list, tuple]:
            # Attempt to convert scalar to tuple of the correct length
            try:
                value = (value,) * len(attr)
            except Exception as e:
                print(f"WARNING: {obj} {prop} simple type for array property could not be converted: {e}")
                value = None
        else:
            # CFG may store RGBA for Vector sockets that are RGB in Blender 5.x
            try:
                n = len(attr)
                if len(value) > n:
                    value = tuple(value[:n])
                elif len(value) < n:
                    value = tuple(value) + (0.0,) * (n - len(value))
            except Exception:
                pass
    elif type(attr) == float:
        if type(value) in [list, tuple]:
            # Quiet for Mix Factor etc.; only warn when unexpected
            value = value[0]
    try:
        setattr(obj, prop, value)
    except Exception as e:
        print(f"WARNING: {obj} {prop}={value!r} failed: {e}")

def _socket_by_name_and_type(sockets, name, prefer_types=None):
    """Pick a socket by name, preferring a type when duplicates exist (Mix Result)."""
    matches = [s for s in sockets if s.name == name]
    if not matches:
        return None
    if prefer_types:
        for t in prefer_types:
            for s in matches:
                if getattr(s, "type", None) == t:
                    return s
    return matches[0]


def resolve_socket_name(sockets, name, prefer_types=None):
    """Find a socket by CFG name, trying Blender 5.x aliases."""
    if name is None:
        return None
    found = _socket_by_name_and_type(sockets, name, prefer_types)
    if found is not None:
        return found
    for alias in SOCKET_NAME_ALIASES.get(name, ()):
        found = _socket_by_name_and_type(sockets, alias, prefer_types)
        if found is not None:
            return found
    return None

def find_socket(sockets, sock):
    if "," in sock:
        index, name = sock.split(",")
        name = name.strip()
    else:
        index = sock
        name = None
    if name in use_index:
        index = int(index.strip())
        return sockets[index]
    # MixRGB Color/Color1/Color2 were single RGBA sockets; ShaderNodeMix has
    # parallel Result/A/B per data type. Prefer RGBA or the link goes to the
    # float Result (0.0) and every KSP material shades black in EEVEE Next.
    prefer = None
    if name in {"Color", "Color1", "Color2", "Result", "A", "B", "Image"}:
        prefer = ("RGBA", "VECTOR", "VALUE")
    found = resolve_socket_name(sockets, name, prefer_types=prefer)
    if found is not None:
        return found
    # MixRGB "Color" output → Mix "Result" (RGBA)
    if name == "Color":
        found = _socket_by_name_and_type(sockets, "Result", ("RGBA",))
        if found is not None:
            return found
    if name in {"Color1", "A"}:
        found = _socket_by_name_and_type(sockets, "A", ("RGBA",))
        if found is not None:
            return found
    if name in {"Color2", "B"}:
        found = _socket_by_name_and_type(sockets, "B", ("RGBA",))
        if found is not None:
            return found
    # Fallback: use numeric index when the CFG name no longer matches.
    if name is not None:
        try:
            idx = int(index.strip())
            if 0 <= idx < len(sockets):
                return sockets[idx]
        except (ValueError, AttributeError):
            pass
    return None

def remap_node_type(sntype):
    """Map deprecated CFG node types to Blender 5.x equivalents."""
    return NODE_TYPE_MAP.get(sntype, sntype)

def create_shader_node(nodes, sntype):
    """Create a shader node, remapping removed types for Blender 4+/5.x."""
    mapped = remap_node_type(sntype)
    sn = nodes.new(mapped)
    if sntype == "ShaderNodeMixRGB" and mapped == "ShaderNodeMix":
        if hasattr(sn, "data_type"):
            sn.data_type = 'RGBA'
    return sn, mapped, sntype

def create_socket(node_tree, name, desc, dir, type):
    if hasattr(node_tree, "interface"):
        # new API as of blender 4.0
        return node_tree.interface.new_socket(name, description=desc,
                                              in_out=dir, socket_type=type)
    else:
        if dir == 'INPUT':
            return node_tree.inputs.new(type, name)
        elif dir == 'OUTPUT':
            return node_tree.outputs.new(type, name)
        else:
            raise RuntimeError

def build_interface(matname, node_tree, ntcfg):
    if ntcfg.HasNode("inputs"):
        inputs = ntcfg.GetNode("inputs")
        for ip in inputs.GetNodes("input"):
            type = typemap[ip.GetValue("type")]
            name = ip.GetValue("name")
            desc = ip.GetValue("description") or ""
            input = create_socket(node_tree, name, desc, "INPUT", type)
            if ip.HasValue("min_value"):
                value = ip.GetValue("min_value")
                set_property(input, "min_value", value)
            if ip.HasValue("max_value"):
                value = ip.GetValue("max_value")
                set_property(input, "min_value", value)
    if ntcfg.HasNode("outputs"):
        outputs = ntcfg.GetNode("outputs")
        for op in outputs.GetNodes("output"):
            type = typemap[op.GetValue("type")]
            name = op.GetValue("name")
            desc = ip.GetValue("description") or ""
            create_socket(node_tree, name, desc, "OUTPUT", type)

def _align_vector_math_inputs(sn, input_nodes):
    """Match CFG VectorMath inputs to the live socket layout for the operation."""
    input_nodes = list(input_nodes)
    n_sock = len(sn.inputs)
    if n_sock <= 0 or len(input_nodes) <= n_sock:
        return input_nodes
    scale_cfg = [ip for ip in input_nodes if ip.GetValue("name") == "Scale"]
    vec_cfg = [ip for ip in input_nodes if ip.GetValue("name") == "Vector"]
    other_cfg = [ip for ip in input_nodes
                 if ip.GetValue("name") not in ("Scale", "Vector")]
    aligned = []
    vi = 0
    for sock in sn.inputs:
        sname = getattr(sock, "name", "") or ""
        if sname == "Scale" and scale_cfg:
            aligned.append(scale_cfg[0])
        elif sname == "Vector" or getattr(sock, "type", "") == 'VECTOR':
            if vi < len(vec_cfg):
                aligned.append(vec_cfg[vi])
                vi += 1
            elif other_cfg:
                aligned.append(other_cfg.pop(0))
        elif scale_cfg and sname.lower() == "scale":
            aligned.append(scale_cfg[0])
        elif other_cfg:
            aligned.append(other_cfg.pop(0))
        elif vi < len(vec_cfg):
            aligned.append(vec_cfg[vi])
            vi += 1
        elif scale_cfg:
            aligned.append(scale_cfg[0])
    return aligned[:n_sock] if aligned else input_nodes[:n_sock]


def _find_node_input(sn, name, index, orig_type):
    """Resolve an input socket for setting default_value from CFG."""
    if name in use_index:
        return sn.inputs[index]
    found = resolve_socket_name(sn.inputs, name)
    if found is not None:
        return found
    if orig_type == "ShaderNodeVectorMath" and name == "Scale":
        # SCALE op: Scale is often inputs[1]; full layout keeps it at [3].
        if "Scale" in sn.inputs:
            return sn.inputs["Scale"]
        return sn.inputs[1] if len(sn.inputs) > 1 else None
    if 0 <= index < len(sn.inputs):
        return sn.inputs[index]
    return None

def _set_input_default(sn, input_sock, name, value, orig_type):
    """Set default_value, with EeveeSpecular Transparency→Alpha inversion."""
    if orig_type == "ShaderNodeEeveeSpecular" and name == "Transparency":
        # EeveeSpecular Transparency is 1-alpha; Principled uses Alpha.
        try:
            t = eval(value) if isinstance(value, str) else value
            value = str(1.0 - float(t))
        except Exception:
            pass
    # Specular color → Specular IOR Level float
    if name == "Specular" and input_sock and type(getattr(input_sock, "default_value", None)) == float:
        try:
            v = eval(value) if isinstance(value, str) else value
            if type(v) in (list, tuple):
                value = str(float(v[0]))
        except Exception:
            pass
    # ShaderNodeMix Factor is float; CFG may still carry MixRGB color defaults by index
    try:
        cur = getattr(input_sock, "default_value", None)
        parsed = eval(value) if isinstance(value, str) else value
        if type(cur) == float and type(parsed) in (list, tuple):
            value = str(float(parsed[0]))
        elif type(cur) in (list, tuple) or (hasattr(cur, "__len__") and not isinstance(cur, (str, bytes))):
            if type(parsed) not in (list, tuple):
                value = str((parsed, parsed, parsed, 1.0) if type(parsed) in (int, float) else parsed)
    except Exception:
        pass
    set_property(input_sock, "default_value", value)

def build_nodes(matname, node_tree, ntcfg):
    for value in ntcfg.values:
        attr, val = value.name, value.value
        if attr == "name":
            continue
        set_property(node_tree, attr, val)
    if not ntcfg.HasNode("nodes"):
        return
    refs = []
    nodes = node_tree.nodes
    # Track nodes remapped from EeveeSpecular for Transparency→Alpha invert links
    eevee_specular_nodes = set()
    for n in ntcfg.GetNode("nodes").nodes:
        sntype, sndata, line = n.name, n, n.line
        sn, mapped, orig_type = create_shader_node(nodes, sntype)
        if orig_type == "ShaderNodeEeveeSpecular":
            eevee_specular_nodes.add(sn)
        for snvalue in sndata.values:
            a, v = snvalue.name, snvalue.value
            v = v.strip()
            if a == "parent":
                refs.append((sn, a, v))
                continue
            elif a == "node_tree":
                sn.node_tree = bpy.data.node_groups[v]
            else:
                set_property(sn, a, v)
        if sndata.HasNode("inputs"):
            input_nodes = sndata.GetNode("inputs").GetNodes("input")
            is_vecmath = (
                sntype == "ShaderNodeVectorMath"
                or orig_type == "ShaderNodeVectorMath"
                or mapped == "ShaderNodeVectorMath"
            )
            if is_vecmath:
                # CFG was dumped with 3×Vector+Scale; Blender 5 SCALE often
                # exposes only Vector+Scale. Align CFG list to live sockets so
                # Scale=2 is not written onto the wrong socket as 0.
                input_nodes = _align_vector_math_inputs(sn, input_nodes)
            for i,ip in enumerate(input_nodes):
                if ip.HasValue("default_value"):
                    if sntype == "NodeReroute":
                        continue
                    value = ip.GetValue("default_value")
                    name = ip.GetValue("name")
                    # VectorMath has several sockets named "Vector" — always
                    # address by CFG order. Name lookup would hit inputs[0] twice
                    # and leave sub1's (1,1,0) unset → broken dxtNormal (black).
                    if is_vecmath:
                        input = sn.inputs[i] if i < len(sn.inputs) else None
                    else:
                        input = _find_node_input(sn, name, i, orig_type)
                    if input is None:
                        print(f"WARNING: {name} unknown input (old cfg?)")
                        continue
                    _set_input_default(sn, input, name, value, orig_type)
            # Changing operation can reset VectorMath defaults on Blender 5 —
            # re-apply CFG vector defaults once more after all props are set.
            if is_vecmath:
                for i, ip in enumerate(input_nodes):
                    if not ip.HasValue("default_value") or i >= len(sn.inputs):
                        continue
                    value = ip.GetValue("default_value")
                    name = ip.GetValue("name")
                    _set_input_default(sn, sn.inputs[i], name, value, orig_type)
        if sndata.HasNode("outputs"):
            for i,op in enumerate(sndata.GetNode("outputs").GetNodes("output")):
                if op.HasValue("default_value"):
                    if sntype == "NodeReroute":
                        continue
                    value = op.GetValue("default_value")
                    set_property(sn.outputs[i], "default_value", value)
    for r in refs:
        if r[1] == "parent" and r[2] in nodes:
            setattr(r[0], r[1], nodes[r[2]])
    if not ntcfg.HasNode("links"):
        return
    links = node_tree.links
    linknodes = ntcfg.GetNode("links")
    for ln in linknodes.GetNodes("link"):
        from_node = nodes[ln.GetValue("from_node")]
        to_node = nodes[ln.GetValue("to_node")]
        from_socket = find_socket(from_node.outputs, ln.GetValue("from_socket"))
        to_sock_spec = ln.GetValue("to_socket")
        to_socket = find_socket(to_node.inputs, to_sock_spec)
        if not (from_socket and to_socket):
            continue
        # EeveeSpecular Transparency was inverted alpha; invert when linking to Principled Alpha.
        if (to_node in eevee_specular_nodes
                and to_socket.name == "Alpha"
                and ("Transparency" in to_sock_spec or to_sock_spec.strip().endswith("Transparency"))):
            inv = nodes.new("ShaderNodeMath")
            inv.operation = 'SUBTRACT'
            inv.location = (to_node.location.x - 150, to_node.location.y - 50)
            inv.inputs[0].default_value = 1.0
            links.new(from_socket, inv.inputs[1])
            links.new(inv.outputs[0], to_socket)
        else:
            links.new(from_socket, to_socket)

def call_update(item, prop, context):
    """Invoke RNA Property update callback (Blender 5-safe).

    Blender 5 PropertyGroup instances no longer expose ``__annotations__``
    (see upstream issue #95); fall back to class annotations / RNA.
    """
    update = None
    for src in (item, type(item)):
        anns = getattr(src, "__annotations__", None)
        if not anns or prop not in anns:
            continue
        annotations = anns[prop]
        if hasattr(annotations, "keywords"):
            update = annotations.keywords.get("update")
        elif isinstance(annotations, (tuple, list)) and len(annotations) > 1:
            update = annotations[1].get("update") if isinstance(annotations[1], dict) else None
        if update:
            break
    if update is None:
        # Last resort: look up RNA property update function
        try:
            rna_prop = item.bl_rna.properties.get(prop)
            update = getattr(rna_prop, "update", None)
        except Exception:
            update = None
    if callable(update):
        update(item, context)

def set_tex(mu, dst, src, context):
    try:
        if src.index < 0:
            raise IndexError  # ick, but it works
        tex = mu.textures[src.index]
        if tex.name[-4:] in [".dds", ".png", ".tga", ".mbm"]:
            dst.tex = tex.name[:-4]
        else:
            dst.tex = tex.name
        
        # Ensure tex.type is 0/1 or True/False
        if tex.type in [0, 1]:
            dst.type = tex.type
        else:
            # Convert to a boolean or 0/1
            dst.type = bool(tex.type)
        
    except IndexError:
        pass
    
    if dst.tex in bpy.data.images:
        dst.rgbNorm = not bpy.data.images[dst.tex].muimageprop.convertNorm
    dst.scale = src.scale
    dst.offset = src.offset
    if context.material.node_tree:
        call_update(dst, "tex", context)
        # other properties are all updated in the one updater
        call_update(dst, "rgbNorm", context)

def make_shader_prop(muprop, blendprop, context):
    for k in muprop:
        item = blendprop.add()
        item.name = k
        item.value = muprop[k]
        if context.material.node_tree:
            call_update(item, "value", context)

def make_shader_tex_prop(mu, muprop, blendprop, context):
    for k in muprop:
        item = blendprop.add()
        item.name = k
        set_tex(mu, item, muprop[k], context)

# Map stock/Unity/KSP shader names (seen in Squad .mu) onto existing .cfg
# node graphs for Blender preview. mat.mumatprop.shaderName stays ORIGINAL
# so export writes the same shader string KSP expects.
#
# MU v4+ already round-trips ANY shaderName + named props (import/export).
# Aliases below are for EEVEE viewport only, and are used only when the
# mapped template shares the same material property set / blend intent.
SHADER_ALIASES = {
    # --- KSP alpha / mask variants (same props as target) ---
    "KSP/Alpha/CutoffBackground": "KSP/Alpha/Cutoff",
    "KSP/Bumped Specular (Stencil)": "KSP/Bumped Specular",
    # Depth mask spelling variants → special builder key (see create_nodes)
    "Depth Mask": "DepthMask",
    # Particles: Soft / Self-Illuminated share _MainTex/_Color/_InvFade
    "KSP/Particles/Additive (Soft)": "KSP/Particles/Additive",
    "KSP/Particles/Additive (Self-Illuminated)": "KSP/Particles/Additive",
    "KSP/Particles/Alpha Blended Scenery": "KSP/Particles/Alpha Blended",
    # Screen-space icon masks ≈ stock lit/unlit graphs (+ unused _MinX… floats)
    "KSP/ScreenSpaceMask": "KSP/Diffuse",
    "KSP/ScreenSpaceMaskAlphaCutoffBackground": "KSP/Alpha/Cutoff",
    "KSP/ScreenSpaceMaskBumped": "KSP/Bumped",
    "KSP/ScreenSpaceMaskBumpedSpecular(Transparent)": "KSP/Bumped Specular",
    "KSP/ScreenSpaceMaskNoAmbientHue": "KSP/Diffuse",
    "KSP/ScreenSpaceMaskNoAmbientHueBumped": "KSP/Bumped",
    "KSP/ScreenSpaceMaskSpecular": "KSP/Specular",
    "KSP/ScreenSpaceMaskUnlit": "KSP/Unlit",
    # Scenery ≈ part shaders (same _MainTex/_BumpMap/_Emissive props)
    "KSP/Scenery/Diffuse": "KSP/Diffuse",
    "KSP/Scenery/Specular": "KSP/Specular",
    "KSP/Scenery/Bumped": "KSP/Bumped",
    "KSP/Scenery/Bumped Specular": "KSP/Bumped Specular",
    "KSP/Scenery/Emissive/Diffuse": "KSP/Emissive/Diffuse",
    "KSP/Scenery/Emissive/Specular": "KSP/Emissive/Specular",
    "KSP/Scenery/Emissive/Bumped Specular": "KSP/Emissive/Bumped Specular",
    "KSP/Scenery/Alpha/Translucent": "KSP/Alpha/Translucent",
    "KSP/Scenery/Unlit/Transparent": "KSP/Alpha/Translucent",
    "KSP/Scenery/Diffuse Multiply": "KSP/Diffuse",
    "KSP/Scenery/Diffuse Multiply (Fixed UV)": "KSP/Diffuse",
    "KSP/Scenery/Diffuse Detail": "KSP/Diffuse",
    "KSP/Scenery/Diffuse Ground KSC": "KSP/Diffuse",
    "KSP/Scenery/Diffuse Ground KSC Specular": "KSP/Specular",
    "KSP/Scenery/Diffuse Ground KSC Specular Far Fix": "KSP/Specular",
    "KSP/Scenery/Reflective Water": "KSP/Specular (Transparent)",
    "KSP/Scenery/Decal/Blended": "KSP/Alpha/Translucent",
    "KSP/Scenery/Decal/Multiply": "KSP/Diffuse",
    # Editor gizmos (rare on .mu; unlit color preview)
    "KSP/EditorGizmos": "KSP/UnlitColor",
    "KSP/EditorGizmos (Emissive)": "KSP/Emissive/Diffuse",
    # FX: multi-pass engine effects → additive particle preview
    "KSP/FX/ReentryFlames 5-Pass": "KSP/Particles/Additive",
    "KSP/FX/ReentryFlames 10-Pass": "KSP/Particles/Additive",
    "KSP/FX/ReentryFlames 20-Pass": "KSP/Particles/Additive",
    "KSP/FX/ReentryDepth": "KSP/Particles/Additive",
    "KSP/FX/Depth Projection": "KSP/Particles/Additive",
    "KSP/Orbit Line": "KSP/UnlitColor",
    # Unity / Legacy / Mobile (props match stock KSP templates)
    "Standard": "KSP/Diffuse",
    "Standard (Specular setup)": "KSP/Specular",
    "Legacy Shaders/Diffuse": "KSP/Diffuse",
    "Legacy Shaders/Specular": "KSP/Specular",
    "Legacy Shaders/Bumped Diffuse": "KSP/Bumped",
    "Legacy Shaders/Bumped Specular": "KSP/Bumped Specular",
    "Legacy Shaders/Diffuse Detail": "KSP/Diffuse",
    "Legacy Shaders/VertexLit": "KSP/Diffuse",
    "Legacy Shaders/Self-Illumin/Diffuse": "KSP/Emissive/Diffuse",
    "Legacy Shaders/Self-Illumin/VertexLit": "KSP/Emissive/Diffuse",
    "Legacy Shaders/Transparent/Diffuse": "KSP/Alpha/Translucent",
    "Legacy Shaders/Transparent/VertexLit": "KSP/Alpha/Translucent",
    "Legacy Shaders/Transparent/Cutout/Diffuse": "KSP/Alpha/Cutoff",
    "Legacy Shaders/Transparent/Cutout/VertexLit": "KSP/Alpha/Cutoff",
    "Legacy Shaders/Transparent/Cutout/Bumped Diffuse": "KSP/Alpha/Cutoff Bumped",
    "Legacy Shaders/Transparent/Cutout/Bumped Specular": "KSP/Alpha/Cutoff Bumped",
    "Legacy Shaders/Particles/Additive": "KSP/Particles/Additive",
    "Legacy Shaders/Particles/Additive (Soft)": "KSP/Particles/Additive",
    "Legacy Shaders/Particles/Alpha Blended": "KSP/Particles/Alpha Blended",
    "Legacy Shaders/Particles/Alpha Blended Premultiply": "KSP/Particles/Alpha Blended",
    "Legacy Shaders/Particles/Alpha Blended Premultiply - UI": "KSP/Particles/Alpha Blended",
    "Legacy Shaders/Particles/~Additive-Multiply": "KSP/Particles/Additive",
    # Also cover Unity Particles/* without Legacy prefix when present on FX
    "Particles/Additive": "KSP/Particles/Additive",
    "Particles/Alpha Blended": "KSP/Particles/Alpha Blended",
    "Particles/Additive (Soft)": "KSP/Particles/Additive",
    "Particles/Standard Unlit": "KSP/Particles/Alpha Blended",
    "Mobile/Diffuse": "KSP/Diffuse",
    "Mobile/VertexLit": "KSP/Diffuse",
    "Mobile/Particles/Additive": "KSP/Particles/Additive",
    "Mobile/Particles/Alpha Blended": "KSP/Particles/Alpha Blended",
    "Mobile/Particles/Multiply": "KSP/Diffuse",
    "Unlit/Transparent": "KSP/Alpha/Translucent",
    "Unlit/Transparent Cutout": "KSP/Alpha/Cutoff",
    "Unlit/Color": "KSP/UnlitColor",
    "UnlitAlpha": "KSP/Alpha/Translucent",
    "Solid Color (Alpha)": "KSP/UnlitColor",
    "Sprites/Default": "KSP/Alpha/Translucent",
    "Sprite/Simple Texture (Unlit)": "KSP/Unlit",
    "MaskedTexture": "KSP/Unlit",
    "Parallax Specular (Alpha)": "KSP/Specular (Transparent)",
}


def _set_mat_blend(mat, blend, surface=None):
    """Apply Blender 5.x blend / surface_render_method safely."""
    try:
        mat.blend_method = blend
    except Exception:
        pass
    if surface is None:
        surface = 'BLENDED' if blend == 'BLEND' else 'DITHERED'
    try:
        mat.surface_render_method = surface
    except Exception:
        pass


def _build_depthmask_shader(mat):
    """IVA depth-only mask: write depth, hold out color (Eevee Holdout)."""
    # use_nodes deprecated Blender 5+ (always True)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (200, 0)
    hold = nodes.new("ShaderNodeHoldout")
    hold.location = (0, 0)
    hold.name = "DepthMaskHoldout"
    links.new(hold.outputs[0], out.inputs[0])
    # Named stub so mumatprop color/tex updates have a sink if present
    tint = nodes.new("ShaderNodeRGB")
    tint.name = "_Color"
    tint.location = (-200, -120)
    try:
        mat.blend_method = 'OPAQUE'
    except Exception:
        pass
    try:
        mat.use_holdout = True
    except Exception:
        pass
    try:
        mat.shadow_method = 'NONE'
    except Exception:
        pass


def _build_from_cfg_template(mat, template_name):
    """Instantiate an existing .cfg graph onto mat (preview only)."""
    if template_name not in shader_configs:
        _build_unknown_shader_fallback(mat, template_name)
        return False
    cfg = shader_configs[template_name]
    for node_tree_cfg in cfg.GetNodes("node_tree"):
        ntname = node_tree_cfg.GetValue("name")
        _ensure_shared_node_group(ntname, node_tree_cfg, mat.name)
    matcfg = cfg.GetNode("Material")
    for value in matcfg.values:
        name, val = value.name, value.value
        set_property(mat, name, val)
    if mat.node_tree:
        links = mat.node_tree.links
        nodes = mat.node_tree.nodes
        while len(links):
            links.remove(links[0])
        while len(nodes):
            nodes.remove(nodes[0])
    if mat.node_tree and matcfg.HasNode("node_tree"):
        build_nodes(mat.name, mat.node_tree, matcfg.GetNode("node_tree"))
        _fix_vertex_color_nodes(mat.node_tree)
        _fix_dxt_normal_groups()
    return True


def _ensure_image_tex_node(nodes, name, location=(-400, -280)):
    if name not in nodes:
        n = nodes.new("ShaderNodeTexImage")
        n.name = name
        n.label = name
        n.location = location
        n.hide = True
    return nodes[name]


def _wire_bump_to_normal(nt):
    """Ensure _BumpMap feeds Normal Map → Principled/StandardShader Normal."""
    if not nt:
        return
    nodes, links = nt.nodes, nt.links
    bump = _ensure_image_tex_node(nodes, "_BumpMap")
    target = nodes.get("StandardShader") or next(
        (n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if target is None:
        return
    nrm_in = target.inputs.get("Normal")
    if nrm_in is None:
        return
    nmap = nodes.get("Normal Map")
    if nmap is None:
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.name = "Normal Map"
        nmap.location = (-160, -280)
    color_out = bump.outputs.get("Color") or bump.outputs[0]
    if not nmap.inputs[1].links:
        links.new(color_out, nmap.inputs[1])
    if not nrm_in.links:
        links.new(nmap.outputs[0], nrm_in)


def _build_cutoff_bumped_shader(mat):
    """Cutoff + bump: start from Cutoff graph, ensure _BumpMap → Normal."""
    _build_from_cfg_template(mat, "KSP/Alpha/Cutoff")
    _wire_bump_to_normal(mat.node_tree)
    _set_mat_blend(mat, 'CLIP', 'DITHERED')


def _build_bumped_specular_transparent_shader(mat):
    """Bumped Specular with alpha blend (keeps _BumpMap unlike Specular Transparent)."""
    _build_from_cfg_template(mat, "KSP/Bumped Specular")
    _wire_bump_to_normal(mat.node_tree)
    _set_mat_blend(mat, 'BLEND', 'BLENDED')
    try:
        mat.use_transparent_shadow = False
    except Exception:
        pass


def _build_unlit_transparent_shader(mat):
    """Unlit + alpha blend (_MainTex/_Color/_Fresnel); not a lit Translucent."""
    _build_from_cfg_template(mat, "KSP/Unlit")
    _set_mat_blend(mat, 'BLEND', 'BLENDED')
    try:
        mat.use_transparent_shadow = False
    except Exception:
        pass
    # Stub _Fresnel float sink if preset/import provides it
    nt = mat.node_tree
    if nt and "_Fresnel" not in nt.nodes:
        fr = nt.nodes.new("ShaderNodeValue")
        fr.name = "_Fresnel"
        fr.label = "_Fresnel"
        fr.location = (-400, 120)
        fr.hide = True


def _build_lightwrapped_specular_shader(mat):
    """Specular with soft light-wrap: Specular base + Add Shader diffuse wrap."""
    _build_from_cfg_template(mat, "KSP/Specular")
    nt = mat.node_tree
    if not nt:
        return
    nodes, links = nt.nodes, nt.links
    out = nodes.get("Material Output") or next(
        (n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs[0].links:
        return
    surface_from = out.inputs[0].links[0].from_socket
    # Soft wrap: diffuse BSDF mixed in (approx Unity lightwrap)
    diff = nodes.new("ShaderNodeBsdfDiffuse")
    diff.name = "LightWrapDiffuse"
    diff.location = (surface_from.node.location.x, surface_from.node.location.y - 180)
    mix = nodes.new("ShaderNodeMixShader")
    mix.name = "LightWrapMix"
    mix.location = (out.location.x - 160, out.location.y)
    mix.inputs[0].default_value = 0.35
    # Prefer MainTex color into wrap diffuse if present
    main = nodes.get("_MainTex")
    if main and main.outputs:
        try:
            links.new(main.outputs[0], diff.inputs["Color"])
        except Exception:
            pass
    links.new(surface_from, mix.inputs[1])
    links.new(diff.outputs[0], mix.inputs[2])
    for l in list(out.inputs[0].links):
        links.remove(l)
    links.new(mix.outputs[0], out.inputs[0])


# Built in Python (no huge .cfg); shaderName on material stays original for export.
_SPECIAL_SHADER_BUILDERS = {
    "DepthMask": "_build_depthmask_shader",
    "KSP/Alpha/Cutoff Bumped": "_build_cutoff_bumped_shader",
    "KSP/Bumped Specular (Transparent)": "_build_bumped_specular_transparent_shader",
    "KSP/Alpha/Unlit Transparent": "_build_unlit_transparent_shader",
    "KSP/Lightwrapped/Specular": "_build_lightwrapped_specular_shader",
    "Diffuse Wrapped": "_build_lightwrapped_specular_shader",
}


def shader_viewport_support(shader_name):
    """Return how a shader name is handled for EEVEE preview.

    'native'  – dedicated .cfg template
    'special' – Python builder (full viewport for that shader)
    'alias'   – viewport via equivalent template (I/E still original name)
    'none'    – Principled fallback only
    """
    if not shader_name:
        return "none"
    if shader_name in _SPECIAL_SHADER_BUILDERS:
        return "special"
    lookup = SHADER_ALIASES.get(shader_name, shader_name)
    if lookup in _SPECIAL_SHADER_BUILDERS:
        return "special" if lookup == shader_name else "alias"
    if shader_name in shader_configs:
        return "native"
    if lookup in shader_configs:
        return "alias"
    return "none"


def create_nodes(mat):
    shaderName = mat.mumatprop.shaderName
    lookup = SHADER_ALIASES.get(shaderName, shaderName)
    aliased = lookup != shaderName
    # Special builders: exact name first, then alias target (e.g. Depth Mask)
    special = (_SPECIAL_SHADER_BUILDERS.get(shaderName)
               or _SPECIAL_SHADER_BUILDERS.get(lookup))
    if special:
        if aliased and shaderName not in _SPECIAL_SHADER_BUILDERS:
            print(f"INFO: shader '{shaderName}' → special preview '{lookup}' "
                  f"(export keeps original name)")
        getattr(sys.modules[__name__], special)(mat)
        _tune_eevee_next_preview(mat)
        return
    if lookup in shader_configs:
        if aliased:
            print(f"INFO: shader '{shaderName}' → preview as '{lookup}' "
                  f"(export keeps original name)")
        cfg = shader_configs[lookup]
        for node_tree_cfg in cfg.GetNodes("node_tree"):
            ntname = node_tree_cfg.GetValue("name")
            _ensure_shared_node_group(ntname, node_tree_cfg, mat.name)
        matcfg = cfg.GetNode("Material")
        for value in matcfg.values:
            name, val = value.name, value.value
            set_property(mat, name, val)
        if mat.node_tree:
            links = mat.node_tree.links
            nodes = mat.node_tree.nodes
            while len(links):
                links.remove(links[0])
            while len(nodes):
                nodes.remove(nodes[0])
        if mat.node_tree and matcfg.HasNode("node_tree"):
            build_nodes(mat.name, mat.node_tree, matcfg.GetNode("node_tree"))
            _fix_vertex_color_nodes(mat.node_tree)
            _fix_dxt_normal_groups()
            _tune_eevee_next_preview(mat)
        # Particle / additive aliases: force blend after inheriting template
        low = (shaderName or "").lower()
        if "particle" in low or "additive" in low or "reentry" in low:
            _set_mat_blend(mat, 'BLEND', 'BLENDED')
        elif "cutoff" in low or "cutout" in low or "depthmask" in low or "depth mask" in low:
            _set_mat_blend(mat, 'CLIP', 'DITHERED')
        elif ("transparent" in low or "translucent" in low
              or "(alpha)" in low or low.endswith("alpha")):
            _set_mat_blend(mat, 'BLEND', 'BLENDED')
        else:
            # Blender 5.x: blend OPAQUE is coerced to HASHED/DITHERED.
            # Keep dithered "opaque" and disable transparent shadows (old OPAQUE).
            try:
                mat.surface_render_method = 'DITHERED'
            except Exception:
                pass
            try:
                mat.use_transparent_shadow = False
            except Exception:
                pass
    else:
        print(f"WARNING: unknown shader: {shaderName} (using Principled fallback)")
        _build_unknown_shader_fallback(mat, shaderName)

def _fix_vertex_color_nodes(node_tree):
    """Blender 5 returns black if ShaderNodeVertexColor.layer_name is empty
    or names a missing color attribute.

    Import always creates a ``colors`` attribute (MU data or synthetic white).
    Force every Vertex Color node onto that name so MainColor (V*C*T) is not
    multiplied by 0 (common on docking ports and other parts with real VCols).
    """
    if not node_tree:
        return
    for n in node_tree.nodes:
        if n.type == 'VERTEX_COLOR' or n.bl_idname == 'ShaderNodeVertexColor':
            for attr in ("layer_name", "attribute_name"):
                if hasattr(n, attr):
                    try:
                        setattr(n, attr, "colors")
                    except Exception:
                        pass
        if n.type == 'GROUP' and getattr(n, "node_tree", None):
            _fix_vertex_color_nodes(n.node_tree)

def _maincolor_rgba_ok(ng):
    """True if Mix nodes feed the RGBA Result (not the float Result=0)."""
    if not ng:
        return False
    for n in ng.nodes:
        if n.bl_idname != "ShaderNodeMix":
            continue
        for s in n.outputs:
            if s.name == "Result" and getattr(s, "type", None) == "RGBA" and s.links:
                return True
    return False


def _clear_node_group(ng):
    """Clear nodes + interface so a shared group can be rebuilt in place."""
    try:
        ng.nodes.clear()
    except Exception:
        while ng.nodes:
            ng.nodes.remove(ng.nodes[0])
    if hasattr(ng, "interface"):
        for item in list(getattr(ng.interface, "items_tree", []) or []):
            try:
                ng.interface.remove(item)
            except Exception:
                pass


def _ensure_shared_node_group(ntname, node_tree_cfg, matname):
    """Create or repair shared shader groups without breaking other materials.

    Never ``remove()`` a shared group after materials already reference it —
    that cleared MainColor/dxtNormal mid-import and left BaseColor unlinked
    (solid grey/white, no textures).
    """
    ng = bpy.data.node_groups.get(ntname)
    if ng is None:
        ng = bpy.data.node_groups.new(ntname, "ShaderNodeTree")
        build_interface(matname, ng, node_tree_cfg)
        build_nodes(matname, ng, node_tree_cfg)
        if ntname == "dxtNormal":
            _fix_dxt_normal_groups()
        return ng
    if ntname == "MainColor" and not _maincolor_rgba_ok(ng):
        _clear_node_group(ng)
        build_interface(matname, ng, node_tree_cfg)
        build_nodes(matname, ng, node_tree_cfg)
        return ng
    if ntname == "dxtNormal":
        _fix_dxt_normal_groups()
    return ng


def _fix_dxt_normal_groups():
    """Ensure dxtNormal VectorMath defaults match CFG (GA→RGB unpack).

    ``sub1`` must subtract (1,1,0); Blender 5 often leaves (1,1,1) which makes
    ``1 - dot(n,n)`` negative and yields black/broken normals in the viewport.
    ``mul2`` must SCALE by 2; a misaligned CFG write can leave Scale at 0.
    """
    ng = bpy.data.node_groups.get("dxtNormal")
    if not ng:
        return
    sub1 = ng.nodes.get("sub1")
    if sub1 and sub1.type == 'VECT_MATH' and len(sub1.inputs) > 1:
        try:
            sub1.inputs[1].default_value = (1.0, 1.0, 0.0)
        except Exception:
            pass
    mul2 = ng.nodes.get("mul2")
    if mul2 and mul2.type == 'VECT_MATH':
        try:
            if "Scale" in mul2.inputs:
                mul2.inputs["Scale"].default_value = 2.0
            elif len(mul2.inputs) > 3:
                mul2.inputs[3].default_value = 2.0
            elif len(mul2.inputs) > 1 and type(
                    getattr(mul2.inputs[1], "default_value", None)) == float:
                mul2.inputs[1].default_value = 2.0
        except Exception:
            pass
    # SeparateColor must stay in RGB mode (CFG used SeparateRGB).
    for n in ng.nodes:
        if n.bl_idname == "ShaderNodeSeparateColor" and hasattr(n, "mode"):
            try:
                n.mode = 'RGB'
            except Exception:
                pass
        if n.bl_idname == "ShaderNodeCombineColor" and hasattr(n, "mode"):
            try:
                n.mode = 'RGB'
            except Exception:
                pass


def ensure_heat_emissive_map_visible(mat):
    """Restore stock EmissionMap after the old white-bypass (viewport-only).

    Previous bypass disconnected ``_Emissive`` → EmissionColor.EmissionMap and
    forced white, producing flat washed-out heat. Reconnect the map when the
    texture node still exists so TailA / Cone_Heat / engine heat match the
    pre-bypass look (map × _EmissiveColor). Export unchanged.
    """
    if not mat or not getattr(mat, "node_tree", None):
        return False
    nt = mat.node_tree
    ec = nt.nodes.get("EmissionColor")
    if ec is None or "EmissionMap" not in ec.inputs:
        return False
    changed = False
    sock = ec.inputs["EmissionMap"]
    emap = nt.nodes.get("_Emissive") or nt.nodes.get("_EmissiveMap")
    if emap is not None and not sock.links:
        try:
            out = emap.outputs.get("Color") or (
                emap.outputs[0] if emap.outputs else None
            )
            if out is not None:
                nt.links.new(out, sock)
                changed = True
        except Exception:
            pass
    # Drop stale white default left by bypass
    if not sock.links:
        try:
            # leave default; nothing to restore
            pass
        except Exception:
            pass
    try:
        if mat.get("mu_heat_emap_bypass"):
            del mat["mu_heat_emap_bypass"]
            changed = True
    except Exception:
        pass
    return changed


def _emissive_map_is_dark(mat, sample=256):
    """True when _Emissive image is missing or mostly near-black (SRB-style)."""
    nt = getattr(mat, "node_tree", None)
    if not nt:
        return True
    emap = nt.nodes.get("_Emissive") or nt.nodes.get("_EmissiveMap")
    img = getattr(emap, "image", None) if emap else None
    if img is None:
        return True
    try:
        px = img.pixels
        n = min(int(len(px) / 4), int(sample))
        if n <= 0:
            return True
        acc = 0.0
        for i in range(n):
            r, g, b = px[i * 4], px[i * 4 + 1], px[i * 4 + 2]
            acc += 0.2126 * r + 0.7152 * g + 0.0722 * b
        return (acc / n) < 0.08
    except Exception:
        return True


def enhance_heat_blackbody_preview(mat):
    """Soft EEVEE Next blackbody Add for dark-map heat (viewport-only).

    Bright maps (TailA / Cone_Heat) keep stock map × ``_EmissiveColor`` with
    soft Emission Strength. Dark / missing maps get a temperature ramp from
    color luminance (orange→yellow) and soft strength (~0.35), masked by the
    emissive map when present so heat stays on the nozzle — not a full-mesh
    lemon silhouette. Export unchanged.
    """
    if not mat or not getattr(mat, "node_tree", None):
        return False
    if mat.get("mu_heat_blackbody"):
        return False
    if not _emissive_map_is_dark(mat):
        return False
    nt = mat.node_tree
    emc = nt.nodes.get("_EmissiveColor")
    out_node = nt.nodes.get("Material Output") or next(
        (n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None
    )
    if emc is None or out_node is None or not out_node.inputs[0].links:
        return False
    try:
        surf_in = out_node.inputs[0]
        prev = surf_in.links[0].from_socket
        add = nt.nodes.new("ShaderNodeAddShader")
        add.name = "_MuHeatAdd"
        add.label = "_MuHeatAdd"
        add.location = (out_node.location.x - 180, out_node.location.y)
        em = nt.nodes.new("ShaderNodeEmission")
        em.name = "_MuHeatEmission"
        em.label = "_MuHeatEmission"
        em.location = (add.location.x - 200, add.location.y - 120)
        bb = nt.nodes.new("ShaderNodeBlackbody")
        bb.name = "_MuHeatBlackbody"
        bb.inputs[0].default_value = 1600.0
        bb.location = (em.location.x - 200, em.location.y)
        # Temp from _EmissiveColor RGB luminance (anim orange→yellow→white)
        rgb_bw = nt.nodes.new("ShaderNodeRGBToBW")
        rgb_bw.name = "_MuHeatColorLum"
        rgb_bw.location = (bb.location.x - 360, bb.location.y + 40)
        tmap = nt.nodes.new("ShaderNodeMapRange")
        tmap.name = "_MuHeatTemp"
        tmap.inputs[1].default_value = 0.0
        tmap.inputs[2].default_value = 1.0
        tmap.inputs[3].default_value = 900.0
        tmap.inputs[4].default_value = 2400.0
        tmap.clamp = True
        tmap.location = (bb.location.x - 180, bb.location.y)
        # Soft strength: alpha x luminance x ~0.35 so cold RGB=0 is zero glow
        # (alpha alone stays 1.0 on many engine curves and left mid-red at f0).
        str_mul = nt.nodes.new("ShaderNodeMath")
        str_mul.name = "_MuHeatEmStr"
        str_mul.operation = "MULTIPLY"
        str_mul.inputs[1].default_value = 0.35
        str_mul.location = (em.location.x - 200, em.location.y - 140)
        color_out = emc.outputs[0] if emc.outputs else None
        alpha_out = emc.outputs[1] if len(emc.outputs) > 1 else None
        if color_out is not None:
            nt.links.new(color_out, rgb_bw.inputs[0])
            nt.links.new(rgb_bw.outputs[0], tmap.inputs[0])
        elif alpha_out is not None:
            nt.links.new(alpha_out, tmap.inputs[0])
        strength_src = None
        # Gate by luminance first so blackbody is off when _EmissiveColor is cold
        lum_gate = nt.nodes.new("ShaderNodeMath")
        lum_gate.name = "_MuHeatLumGate"
        lum_gate.operation = "MULTIPLY"
        lum_gate.location = (str_mul.location.x - 160, str_mul.location.y)
        if color_out is not None:
            nt.links.new(rgb_bw.outputs[0], lum_gate.inputs[0])
        elif alpha_out is not None:
            nt.links.new(alpha_out, lum_gate.inputs[0])
        else:
            lum_gate.inputs[0].default_value = 0.0
        if alpha_out is not None:
            nt.links.new(alpha_out, lum_gate.inputs[1])
        else:
            lum_gate.inputs[1].default_value = 1.0
        nt.links.new(lum_gate.outputs[0], str_mul.inputs[0])
        strength_src = str_mul.outputs[0]
        # Mask by emissive map so glow stays on nozzle UVs, not whole mesh
        emap = nt.nodes.get("_Emissive") or nt.nodes.get("_EmissiveMap")
        if emap is not None and strength_src is not None:
            map_bw = nt.nodes.new("ShaderNodeRGBToBW")
            map_bw.name = "_MuHeatMapMask"
            map_bw.location = (str_mul.location.x - 160, str_mul.location.y - 80)
            map_mul = nt.nodes.new("ShaderNodeMath")
            map_mul.name = "_MuHeatMapStr"
            map_mul.operation = "MULTIPLY"
            map_mul.location = (str_mul.location.x + 160, str_mul.location.y - 40)
            emap_out = emap.outputs.get("Color") or (
                emap.outputs[0] if emap.outputs else None
            )
            if emap_out is not None:
                nt.links.new(emap_out, map_bw.inputs[0])
                nt.links.new(strength_src, map_mul.inputs[0])
                nt.links.new(map_bw.outputs[0], map_mul.inputs[1])
                strength_src = map_mul.outputs[0]
        nt.links.new(tmap.outputs[0], bb.inputs[0])
        nt.links.new(bb.outputs[0], em.inputs[0])
        if strength_src is not None:
            nt.links.new(strength_src, em.inputs[1])
        else:
            em.inputs[1].default_value = 0.35
        nt.links.new(prev, add.inputs[0])
        nt.links.new(em.outputs[0], add.inputs[1])
        nt.links.remove(surf_in.links[0])
        nt.links.new(add.outputs[0], surf_in)
        mat["mu_heat_blackbody"] = 1
        return True
    except Exception:
        return False


def _mat_wants_emissive_preview(mat, sn=""):
    """True when EEVEE should keep Emission Strength live (heat / RCS / lamps).

    KSP often animates ``_EmissiveColor`` on materials whose shader name already
    contains ``emissive``, but also synthesizes the prop on Specular mats, or
    uses mapped graphs (SpecPBR) without a StandardShader node.
    """
    sn = (sn or "").lower()
    if "emissive" in sn:
        return True
    nt = getattr(mat, "node_tree", None)
    if nt and (nt.nodes.get("_Emissive") or nt.nodes.get("_EmissiveColor")):
        return True
    mp = getattr(mat, "mumatprop", None)
    if not mp:
        return False
    try:
        if "_EmissiveColor" in mp.color.properties:
            return True
    except Exception:
        pass
    try:
        if "_Emissive" in mp.texture.properties:
            return True
    except Exception:
        pass
    return False


def _link_emissive_alpha_to_strength(nt, strength_socket):
    """Prefer ``_EmissiveColor`` Color4.Alpha → Emission Strength (heat dimming)."""
    return _link_emissive_alpha_scaled(nt, strength_socket, 1.0)


def _link_emissive_alpha_scaled(nt, strength_socket, scale=1.0):
    """Alpha × scale → Emission Strength (heat readable; RCS white cut in GIF)."""
    if not nt or strength_socket is None:
        return False
    emc = nt.nodes.get("_EmissiveColor")
    if emc is None or not emc.outputs:
        return False
    alpha_out = emc.outputs[1] if len(emc.outputs) > 1 else None
    if alpha_out is None:
        return False
    # Already linked via our scale node
    if strength_socket.links:
        fr = strength_socket.links[0].from_node
        if fr and fr.name == "_MuEmStrengthScale":
            try:
                fr.inputs[1].default_value = float(scale)
            except Exception:
                pass
            return True
        # Replace bare Alpha→Strength with scaled multiply
        for l in list(strength_socket.links):
            nt.links.remove(l)
    try:
        mul = nt.nodes.get("_MuEmStrengthScale")
        if mul is None:
            mul = nt.nodes.new("ShaderNodeMath")
            mul.name = "_MuEmStrengthScale"
            mul.label = "_MuEmStrengthScale"
            mul.operation = "MULTIPLY"
            mul.hide = True
            mul.location = (
                emc.location.x + 160,
                emc.location.y - 40,
            )
        mul.inputs[1].default_value = float(scale)
        nt.links.new(alpha_out, mul.inputs[0])
        nt.links.new(mul.outputs[0], strength_socket)
        return True
    except Exception:
        return False


def _boost_principled_emission(node_tree, em_strength, visited=None):
    """Set unlinked Emission Strength on Principled nodes (incl. nested groups)."""
    if not node_tree:
        return
    if visited is None:
        visited = set()
    tid = id(node_tree)
    if tid in visited:
        return
    visited.add(tid)
    for n in node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            es = n.inputs.get("Emission Strength")
            if es is not None and not es.links:
                es.default_value = em_strength
            alpha = n.inputs.get("Alpha")
            if alpha is not None and not alpha.links:
                alpha.default_value = 1.0
        if n.type == 'GROUP' and getattr(n, "node_tree", None):
            _boost_principled_emission(n.node_tree, em_strength, visited)


def _tune_eevee_next_preview(mat):
    """Viewport-only tuning so KSP mats stay readable under EEVEE Next.

    Keeps albedo from MainTex visible: no emission wash. Export unchanged.
    """
    if not mat or not mat.node_tree:
        return
    nt = mat.node_tree

    # Default: opaque KSP parts cast solid shadows. Particle/additive keep
    # transparent shadows off for cleaner FX. DepthMask uses Holdout.
    sn = ""
    try:
        sn = ((mat.mumatprop.shaderName or "") if hasattr(mat, "mumatprop") else "").lower()
    except Exception:
        sn = ""
    try:
        if "particle" in sn or "additive" in sn or "translucent" in sn or sn == "depthmask":
            mat.use_transparent_shadow = False
        else:
            # Prefer solid shadows for stock opaque/cutoff parts
            mat.use_transparent_shadow = False
    except Exception:
        pass

    # Additive / translucent flare: glow lives in RGB (Flare.dds alpha is ~1).
    # CHANNEL_PACKED there breaks MixShader Fac and pairs badly with castShadows.
    force_straight = ("additive" in sn) or ("particle" in sn) or ("flare" in (mat.name or "").lower())
    for n in nt.nodes:
        if n.type == 'TEX_IMAGE' and n.image:
            try:
                if force_straight:
                    n.image.alpha_mode = 'STRAIGHT'
                else:
                    # Keep alpha samples for gloss masks; do not premul RGB to ~0
                    n.image.alpha_mode = 'CHANNEL_PACKED'
            except Exception:
                pass

    # Default: mute bump/normal chain (Options → Toggle Bump/Normal to show).
    for n in nt.nodes:
        if n.type in {'NORMAL_MAP', 'BUMP'}:
            n.mute = True
        if n.name in {'_BumpMap', 'dxtNormal'}:
            n.mute = True
        # CFG often names the instance Group.001 — match by node_tree too
        if (n.type == 'GROUP' and n.node_tree
                and n.node_tree.name == 'dxtNormal'):
            n.mute = True
        if n.type == 'GROUP' and n.node_tree:
            for gn in n.node_tree.nodes:
                if gn.type in {'NORMAL_MAP', 'BUMP'}:
                    gn.mute = True

    mp = getattr(mat, "mumatprop", None)
    sn = ((mp.shaderName or "") if mp else sn or "").lower()
    is_em = _mat_wants_emissive_preview(mat, sn)
    # Soft EEVEE Next glow: Alpha × scale → Strength. 1.0+ blew heat to a flat
    # lemon silhouette; ~0.35 keeps orange→yellow ramp + mesh detail. Near-white
    # RCS end-of-clip is soft-clamped in colorprops (not crushed here).
    em_strength = 0.35 if is_em else 0.0

    ss = nt.nodes.get("StandardShader")
    if ss is not None:
        # Gloss from MainColor.Alpha is often ~0 on Squad DDS (unused alpha),
        # which forces Roughness≈1 and a muddy EEVEE Next look.
        if "Gloss" in ss.inputs:
            for l in list(ss.inputs["Gloss"].links):
                nt.links.remove(l)
            shin = 0.4
            if "Shininess" in ss.inputs:
                try:
                    shin = float(ss.inputs["Shininess"].default_value)
                except Exception:
                    pass
            ss.inputs["Gloss"].default_value = max(
                0.35, min(0.8, shin if shin > 0.05 else 0.45))

        # Emissive: prefer scaled Alpha → Strength (heat dimming) without the
        # old 2.0 wash. Non-emissive: force 0.
        if "Emission Strength" in ss.inputs:
            es_in = ss.inputs["Emission Strength"]
            if is_em:
                if not _link_emissive_alpha_scaled(nt, es_in, em_strength):
                    if not es_in.links:
                        es_in.default_value = em_strength
            else:
                for l in list(es_in.links):
                    nt.links.remove(l)
                es_in.default_value = 0.0

        if ss.node_tree:
            for gn in ss.node_tree.nodes:
                if gn.type == 'NORMAL_MAP':
                    gn.mute = True
            _boost_principled_emission(ss.node_tree, em_strength)
        return

    # SpecPBR / EeveeSpecular mapped graphs: boost nested Principled strength
    # so _EmissiveColor / EmissionColor actually reads in EEVEE Next.
    _boost_principled_emission(nt, em_strength)
    if is_em:
        # Some graphs expose Emission Strength on a group (StandardShader-like)
        for n in nt.nodes:
            if n.type != 'GROUP' or "Emission Strength" not in n.inputs:
                continue
            es_in = n.inputs["Emission Strength"]
            if not _link_emissive_alpha_scaled(nt, es_in, em_strength):
                if not es_in.links:
                    es_in.default_value = em_strength


def _build_unknown_shader_fallback(mat, shaderName):
    """Build a usable Principled tree for shaders without a .cfg mapping.

    Preserves round-trip of texture/color props via mumatprop; Eevee preview
    uses a simple Principled BSDF so particle/legacy materials still render.
    """
    # use_nodes deprecated Blender 5+ (always True)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.label = shaderName or "Unknown"
    links.new(bsdf.outputs[0], out.inputs[0])
    # Heuristic for common KSP particle / cutout shaders
    name = (shaderName or "").lower()
    if "particle" in name or "additive" in name:
        mat.blend_method = 'BLEND'
        try:
            mat.surface_render_method = 'BLENDED'
        except Exception:
            pass
        if "alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = 0.5
    elif "cutout" in name or "cutoff" in name or "depthmask" in name:
        mat.blend_method = 'CLIP'
        try:
            mat.surface_render_method = 'DITHERED'
        except Exception:
            pass

def make_shader4(mumat, mu):
    mat = bpy.data.materials.new(mumat.name)
    matprops = mat.mumatprop
    matprops.shaderName = mumat.shaderName
    create_nodes(mat)
    class Context:
        pass
    ctx = Context()
    ctx.material = mat
    make_shader_prop(mumat.colorProperties, matprops.color.properties, ctx)
    make_shader_prop(mumat.vectorProperties, matprops.vector.properties, ctx)
    make_shader_prop(mumat.floatProperties2, matprops.float2.properties, ctx)
    make_shader_prop(mumat.floatProperties3, matprops.float3.properties, ctx)
    make_shader_tex_prop(mu, mumat.textureProperties, matprops.texture.properties, ctx)
    return mat

def make_shader(mumat, mu):
    return make_shader4(mumat, mu)
