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

mainTex_block = (
    ("node", "Output", 'ShaderNodeOutput', (630, 730)),
    ("node", "mainMaterial", 'ShaderNodeMaterial', (70, 680)),
    ("node", "geometry", 'ShaderNodeGeometry', (-590, 260)),
    ("node", "mainTex", 'ShaderNodeTexture', (-380, 480)),
    ("link", "geometry", "UV", "mainTex", "Vector"),
    ("link", "mainTex", "Color", "mainMaterial", "Color"),
    ("settex", "mainTex", "texture", "mainTex"),
    ("link", "mainMaterial", "Color", "Output", "Color"),
)

specular_block = (
    ("node", "specColor", 'ShaderNodeValToRGB', (-210, 410)),
    ("link", "mainTex", "Value", "specColor", "Fac"),
    ("link", "specColor", "Color", "mainMaterial", "Spec"),
    ("set", "specColor", "color_ramp.elements[1].color", "specColor"),
    #FIXME shinines
)

bumpmap_block = (
    ("node", "bumpMap", 'ShaderNodeMaterial', (-380, 480)),
    ("link", "bumpMap", "Normal", "mainMaterial", "Normal"),
    ("call", "bumpMap", "material.texture_slots.add()"),
    ("settex", "bumpMap", "material.texture_slots[0].texture", "bumpMap"),
    ("setval", "bumpMap", "material.texture_slots[0].texture_coords", 'UV'),
    ("setval", "bumpMap", "material.texture_slots[0].use_map_color_diffuse", False),
    ("setval", "bumpMap", "material.texture_slots[0].use_map_normal", True),
)

emissive_block = (
    ("node", "emissive", 'ShaderNodeTexture', (-400, 40)),
    ("node", "emissiveConvert", 'ShaderNodeRGBToBW', (-230, 30)),
    ("node", "emissiveColor", 'ShaderNodeValToRGB', (-50, 180)),
    ("node", "emissiveMaterial", 'ShaderNodeMaterial', (230, 400)),
    ("link", "geometry", "UV", "emissive", "Vector"),
    ("link", "emissive", "Color", "emissiveConvert", "Color"),
    ("link", "emissiveConvert", "Val", "emissiveColor", "Fac"),
    ("link", "emissiveColor", "Color", "emissiveMaterial", "Color"),
    ("settex", "emissive", "texture", "emissive"),
    ("set", "emissiveColor", "color_ramp.elements[1].color", "emissiveColor"),
    ("setval", "emissiveMaterial", "use_specular", False),
    ("setval", "emissiveMaterial", "material.emit", 1.0),
    ("node", "mix", 'ShaderNodeMixRGB', (430, 610)),
    ("link", "mainMaterial", "Color", "mix", "Color1"),
    ("link", "emissiveMaterial", "Color", "mix", "Color2"),
    ("link", "mix", "Color", "Output", "Color"),
    ("setval", "mix", "blend_type", 'ADD'),
    ("setval", "mix", "inputs['Fac'].default_value", 1.0),
)

alpha_cutoff_block = (
    ("node", "alphaCutoff", 'ShaderNodeMath', (-230, 30)),
    ("link", "mainTex", "Value", "alphaCutoff", 0),
    ("link", "alphaCutoff", "Value", "Output", "Alpha"),
    ("set", "alphaCutoff", "inputs[1].default_value", "cutoff"),
)

ksp_specular = mainTex_block + specular_block
ksp_bumped = mainTex_block + bumpmap_block
ksp_bumped_specular = mainTex_block + specular_block + bumpmap_block
ksp_emissive_diffuse = mainTex_block + emissive_block
ksp_emissive_specular = mainTex_block + emissive_block + specular_block
ksp_emissive_bumped_specular = (mainTex_block + emissive_block
                                + specular_block + bumpmap_block)
ksp_alpha_cutoff = mainTex_block + alpha_cutoff_block
ksp_alpha_cutoff_bumped = mainTex_block + alpha_cutoff_block + bumpmap_block
ksp_alpha_translucent = ()
ksp_alpha_translucent_specular = ()
ksp_unlit_transparent = ()
ksp_unlit = ()
ksp_diffuse = mainTex_block

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

def make_shader(id, mumat, mu):
    name = mumat.name
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
            n.location = s[3]
            if s[2] == "ShaderNodeMaterial":
                n.material = bpy.data.materials.new(n.name)
        elif s[0] == "link":
            n1 = nodes["%s.%s" % (name, s[1])]
            n2 = nodes["%s.%s" % (name, s[3])]
            links.new(n1.outputs[s[2]], n2.inputs[s[4]])
        elif s[0] == "set":
            n = nodes["%s.%s" % (name, s[1])]
            exec ("n.%s = mumat.%s" % (s[2], s[3]), {}, locals())
        elif s[0] == "settex":
            n = nodes["%s.%s" % (name, s[1])]
            tex = getattr(mumat,s[3])
            tex = bpy.data.textures[mu.obj.textures[tex.index].name]
            exec ("n.%s = tex" % s[2], {}, locals())
        elif s[0] == "setval":
            n = nodes["%s.%s" % (name, s[1])]
            exec ("n.%s = %s" % (s[2], repr(s[3])), {}, locals())
        elif s[0] == "call":
            n = nodes["%s.%s" % (name, s[1])]
            exec ("n.%s" % s[2], {}, locals())
    return mat
