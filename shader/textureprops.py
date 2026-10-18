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
from struct import unpack
from pprint import pprint

import bpy
from mathutils import Vector
from bpy.props import BoolProperty, StringProperty
from bpy.props import CollectionProperty
from bpy.props import FloatVectorProperty, IntProperty

def _bump_dxt_nodes(nodes):
    out = []
    for n in nodes:
        if n.name == "dxtNormal":
            out.append(n)
        elif (n.type == "GROUP" and getattr(n, "node_tree", None)
              and n.node_tree.name == "dxtNormal"):
            out.append(n)
    return out


def _apply_bump_rgb_norm(mat, texprop):
    """Route _BumpMap through dxtNormal only for GA maps; RGB goes straight."""
    if texprop.name != "_BumpMap" or not mat or not mat.node_tree:
        return
    nt = mat.node_tree
    bump = nt.nodes.get("_BumpMap")
    if not bump:
        return
    use_rgb = bool(texprop.rgbNorm)
    dxts = _bump_dxt_nodes(nt.nodes)
    if not dxts:
        return
    color_out = bump.outputs.get("Color") or bump.outputs[0]
    for dxt in dxts:
        dxt_out = dxt.outputs[0] if dxt.outputs else None
        if not dxt_out:
            continue
        # Remember destinations currently fed by this dxt (or already by bump)
        dests = [(l.to_node, l.to_socket) for l in list(dxt_out.links)]
        if not dests:
            # Already bypassed: collect sockets fed by bump that dxt used to own
            dests = [(l.to_node, l.to_socket) for l in list(color_out.links)
                     if l.to_node != dxt]
        for to_node, to_socket in dests:
            for l in list(to_socket.links):
                nt.links.remove(l)
            if use_rgb:
                nt.links.new(color_out, to_socket)
            else:
                nt.links.new(dxt_out, to_socket)
        dxt.mute = use_rgb
        # Keep GA path wired from bump into dxt
        if not use_rgb:
            rgb_in = dxt.inputs[0] if dxt.inputs else None
            a_in = dxt.inputs[1] if len(dxt.inputs) > 1 else None
            if rgb_in is not None and not rgb_in.links:
                nt.links.new(color_out, rgb_in)
            if a_in is not None and not a_in.links and len(bump.outputs) > 1:
                nt.links.new(bump.outputs[1], a_in)


def texture_update_mapping(self, context):
    if not hasattr(context, "material") or not context.material:
        return
    mat = context.material
    nodes = mat.node_tree.nodes
    scale = Vector(self.scale)
    offset = Vector(self.offset)
    if self.name in nodes:
        if self.tex in bpy.data.images:
            img = bpy.data.images[self.tex]
            if img.muimageprop.invertY:
                scale.y *= -1
                offset.y = 1 - offset.y
        nodes[self.name].texture_mapping.translation.xy = offset
        nodes[self.name].texture_mapping.scale.xy = scale
    _apply_bump_rgb_norm(mat, self)

def texture_update_tex(self, context):
    if not hasattr(context, "material") or not context.material:
        return
    mat = context.material
    nodes = mat.node_tree.nodes
    if self.name in nodes and self.tex in bpy.data.images:
        nodes[self.name].image = bpy.data.images[self.tex]
        nodes[self.name].image.colorspace_settings.is_data = self.type

class MuTextureProperties(bpy.types.PropertyGroup):
    tex: StringProperty(name="tex", update=texture_update_tex)
    type: BoolProperty(name="type", description="Texture is a normal map", default = False, update=texture_update_tex)
    rgbNorm: BoolProperty(name="RGB Normal", description="Texture is RGB rather than GA (blender shader control, not exported)", update=texture_update_mapping)
    scale: FloatVectorProperty(name="scale", size = 2, subtype='XYZ', default = (1.0, 1.0), update=texture_update_mapping)
    offset: FloatVectorProperty(name="offset", size = 2, subtype='XYZ', default = (0.0, 0.0), update=texture_update_mapping)

class MuMaterialTexturePropertySet(bpy.types.PropertyGroup):
    bl_label = "Textures"
    properties: CollectionProperty(type=MuTextureProperties, name="Textures")
    index: IntProperty()
    expanded: BoolProperty()

    def draw_item(self, layout):
        item = self.properties[self.index]
        row = layout.row()
        col = row.column()
        col.prop(item, "name", text="Name")
        r = col.row()
        r.prop(item, "tex", text="")
        r.prop(item, "type", text="")
        r.prop(item, "rgbNorm", text="")
        col.prop(item, "scale", text="")
        col.prop(item, "offset", text="")

classes_to_register = (
    MuTextureProperties,
    MuMaterialTexturePropertySet,
)
