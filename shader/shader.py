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
    if not hasattr(obj, prop):
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
    elif type(attr) == float:
        if type(value) in [list, tuple]:
            print(f"WARNING: {obj} {prop} array type for simple property (old blender?)")
            value = value[0]
    setattr(obj, prop, value)

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
    elif name in sockets:
        return sockets[name]
    return None

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
    for n in ntcfg.GetNode("nodes").nodes:
        sntype, sndata, line = n.name, n, n.line
        sn = nodes.new(sntype)
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
            if sntype == "ShaderNodeVectorMath":
                # blender 2.82 has only 2 vector and 1 float input nodes
                # but blender 2.90 (2.83?) has 3 vector inputs
                # fortunately, the affects only the wrap operation which
                # none of the shaders use
                if len(sn.inputs) < 4:
                    del input_nodes[2]
            for i,ip in enumerate(input_nodes):
                if ip.HasValue("default_value"):
                    if sntype == "NodeReroute":
                        continue
                    value = ip.GetValue("default_value")
                    name = ip.GetValue("name")
                    if name in use_index:
                        input = sn.inputs[i]
                    elif name in sn.inputs:
                        input = sn.inputs[name]
                    elif sntype == "ShaderNodeVectorMath" and name == "Scale":
                        input = sn.inputs[1]
                        set_property(input, "default_value", value)
                    else:
                        print(f"WARNING: {name} unknown input (old cfg?)")
                        continue
                    set_property (input, "default_value", value)
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
        to_socket = find_socket(to_node.inputs, ln.GetValue("to_socket"))
        if from_socket and to_socket:
            links.new(from_socket, to_socket)

def call_update(item, prop, context):
    annotations = item.__annotations__[prop]
    if hasattr(annotations, "keywords"):
        keywords = annotations.keywords
    else:
        keywords = annotations[1]
    keywords["update"](item, context)

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

def create_nodes(mat):
    shaderName = mat.mumatprop.shaderName
    if shaderName in shader_configs:
        cfg = shader_configs[shaderName]
        for node_tree_cfg in cfg.GetNodes("node_tree"):
            ntname = node_tree_cfg.GetValue("name")
            if not ntname in bpy.data.node_groups:
                node_tree = bpy.data.node_groups.new(ntname, "ShaderNodeTree")
                build_interface(mat.name, node_tree, node_tree_cfg)
                build_nodes(mat.name, node_tree, node_tree_cfg)
        matcfg = cfg.GetNode("Material")
        for value in matcfg.values:
            name, val = value.name, value.value
            set_property(mat, name, val)
        if mat.use_nodes:
            links = mat.node_tree.links
            nodes = mat.node_tree.nodes
            while len(links):
                links.remove(links[0])
            while len(nodes):
                nodes.remove(nodes[0])
        if mat.use_nodes and matcfg.HasNode("node_tree"):
            build_nodes(mat.name, mat.node_tree, matcfg.GetNode("node_tree"))
    else:
        print(f"WARNING: unknown shader: {shaderName}")

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
