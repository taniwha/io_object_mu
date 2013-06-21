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

from struct import unpack

import bpy
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum

ksp_specular = (
)
ksp_bumped = (
)
ksp_bumped_specular = (
)
ksp_emissive_diffuse = (
)
ksp_emissive_specular = (
    ("node", "Output", 'ShaderNodeOutput'),
    ("node", "mainMaterial", 'ShaderNodeMaterial'),
    ("node", "geometry", 'ShaderNodeGeometry'),
    ("node", "mainTex", 'ShaderNodeTexture'),
    ("node", "specColor", 'ShaderNodeValToRGB'),
    ("node", "emissive", 'ShaderNodeTexture'),
    ("node", "emissiveConvert", 'ShaderNodeRGBToBW'),
    ("node", "emissiveColor", 'ShaderNodeValToRGB'),
    ("node", "emissiveMaterial", 'ShaderNodeMaterial'),
    ("node", "mix", 'ShaderNodeMixRGB'),
    ("link", "geometry", "UV", "mainTex", "Vector"),
    ("link", "mainTex", "Color", "mainMaterial", "Color"),
    ("link", "mainTex", "Value", "specColor", "Fac"),
    ("link", "specColor", "Color", "mainMaterial", "Spec"),
    ("link", "mainMaterial", "Color", "mix", "Color1"),
    ("link", "geometry", "UV", "emissive", "Vector"),
    ("link", "emissive", "Color", "emissiveConvert", "Color"),
    ("link", "emissiveConvert", "Val", "emissiveColor", "Fac"),
    ("link", "emissiveColor", "Color", "emissiveMaterial", "Color"),
    ("link", "emissiveMaterial", "Color", "mix", "Color2"),
    ("link", "mix", "Color", "Output", "Color"),
)
ksp_emissive_bumped_specular = (
)
ksp_alpha_cutoff = (
)
ksp_alpha_cutoff_bumped = (
)
ksp_alpha_translucent = (
)
ksp_alpha_translucent_specular = (
)
ksp_unlit_transparent = (
)
ksp_unlit = (
)
ksp_diffuse = (
)

ksp_shaders = {
"KSP/Specular":ksp_specular,
"KSP/Bumped":ksp_bumped,
"KSP/Bumped Specular":ksp_bumped_specular,
"KSP/Emissive/Diffuse":ksp_emissive_diffuse,
"KSP/Emissive/Specular":ksp_emissive_specular,
"KSP/Emissive/Bumped Specular":ksp_emissive_bumped_specular,
"KSP/Alpha/Cutoff":ksp_alpha_cutoff,
"KSP/Alpha/Cutoff Bumped":ksp_alpha_cutoff_bumped,
"KSP/Alpha/Translucent":ksp_alpha_translucent,
"KSP/Alpha/Translucent Specular":ksp_alpha_translucent_specular,
"KSP/Alpha/Unlit Transparent":ksp_unlit_transparent,
"KSP/Unlit":ksp_unlit,
"KSP/Diffuse":ksp_diffuse,
}

def make_shader(id, name):
    shader = ksp_shaders[id]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    while len(nodes):
        nodes.remove(nodes[0])
    links = mat.node_tree.links
    for s in shader:
        if s[0] == "node":
            n = nodes.new(s[2])
            n.name = "%s.%s" % (name, s[1])
            n.label = s[1]
        elif s[0] == "link":
            n1 = nodes["%s.%s" % (name, s[1])]
            n2 = nodes["%s.%s" % (name, s[3])]
            links.new(n1.outputs[s[2]], n2.inputs[s[4]])
    return mat
