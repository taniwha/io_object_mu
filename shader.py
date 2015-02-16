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
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
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
    ("setval", "bumpMap", "material.texture_slots[0].texture.use_normal_map", True),
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

shader_items=(
    ('', "", ""),
    ('KSP/Specular', "KSP/Specular", ""),
    ('KSP/Bumped', "KSP/Bumped", ""),
    ('KSP/Bumped Specular', "KSP/Bumped Specular", ""),
    ('KSP/Emissive/Diffuse', "KSP/Emissive/Diffuse", ""),
    ('KSP/Emissive/Specular', "KSP/Emissive/Specular", ""),
    ('KSP/Emissive/Bumped Specular', "KSP/Emissive/Bumped Specular", ""),
    ('KSP/Alpha/Cutoff', "KSP/Alpha/Cutoff", ""),
    ('KSP/Alpha/Cutoff Bumped', "KSP/Alpha/Cutoff Bumped", ""),
    ('KSP/Alpha/Translucent', "KSP/Alpha/Translucent", ""),
    ('KSP/Alpha/Translucent Specular', "KSP/Alpha/Translucent Specular", ""),
    ('KSP/Alpha/Unlit Transparent', "KSP/Alpha/Unlit Transparent", ""),
    ('KSP/Unlit', "KSP/Unlit", ""),
    ('KSP/Diffuse', "KSP/Diffuse", ""),
)

def node_node(name, nodes, s):
    n = nodes.new(s[2])
    n.name = "%s.%s" % (name, s[1])
    n.label = s[1]
    n.location = s[3]
    if s[2] == "ShaderNodeMaterial":
        n.material = bpy.data.materials.new(n.name)

def node_link(name, nodes, links, s):
    n1 = nodes["%s.%s" % (name, s[1])]
    n2 = nodes["%s.%s" % (name, s[3])]
    links.new(n1.outputs[s[2]], n2.inputs[s[4]])

def node_set(name, matprops, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    exec ("n.%s = matprops.%s" % (s[2], s[3]), {}, locals())

def node_settex(name, matprops, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    tex = getattr(matprops,s[3])
    if tex.tex in bpy.data.textures:
        tex = bpy.data.textures[tex.tex]
        exec ("n.%s = tex" % s[2], {}, locals())

def node_setval(name, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    exec ("n.%s = %s" % (s[2], repr(s[3])), {}, locals())

def node_call(name, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    exec ("n.%s" % s[2], {}, locals())

def create_nodes(mat):
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    while len(links):
        links.remove(links[0])
    while len(nodes):
        nodes.remove(nodes[0])
    shader = ksp_shaders[mat.mumatprop.shader]
    for s in shader:
        if s[0] == "node":
            node_node(mat.name, nodes, s)
        elif s[0] == "link":
            node_link(mat.name, nodes, links, s)
        elif s[0] == "set":
            node_set(mat.name, mat.mumatprop, nodes, s)
        elif s[0] == "settex":
            node_settex(mat.name, mat.mumatprop, nodes, s)
        elif s[0] == "setval":
            node_setval(mat.name, nodes, s)
        elif s[0] == "call":
            node_call(mat.name, nodes, s)

def set_tex(mu, dst, src):
    try:
        dst.tex = mu.textures[src.index].name
    except IndexError:
        pass
    dst.scale = src.scale
    dst.offset = src.offset

def make_shader(mumat, mu):
    mat = bpy.data.materials.new(mumat.name)
    matprops = mat.mumatprop
    id = MuEnum.ShaderNames[mumat.type]
    matprops.shader = id
    if matprops.shader == 'KSP/Specular':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        matprops.specColor = mumat.specColor
        matprops.shininess = mumat.shininess
    elif matprops.shader == 'KSP/Bumped':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        set_tex(mu, matprops.bumpMap, mumat.bumpMap)
    elif matprops.shader == 'KSP/Bumped Specular':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        set_tex(mu, matprops.bumpMap, mumat.bumpMap)
        matprops.specColor = mumat.specColor
        matprops.shininess = mumat.shininess
    elif matprops.shader == 'KSP/Emissive/Diffuse':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        set_tex(mu, matprops.emissive, mumat.emissive)
        matprops.emissiveColor = mumat.emissiveColor
    elif matprops.shader == 'KSP/Emissive/Specular':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        matprops.specColor = mumat.specColor
        matprops.shininess = mumat.shininess
        set_tex(mu, matprops.emissive, mumat.emissive)
        matprops.emissiveColor = mumat.emissiveColor
    elif matprops.shader == 'KSP/Emissive/Bumped Specular':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        set_tex(mu, matprops.bumpMap, mumat.bumpMap)
        matprops.specColor = mumat.specColor
        matprops.shininess = mumat.shininess
        set_tex(mu, matprops.emissive, mumat.emissive)
        matprops.emissiveColor = mumat.emissiveColor
    elif matprops.shader == 'KSP/Alpha/Cutoff':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        matprops.cutoff = mumat.cutoff
    elif matprops.shader == 'KSP/Alpha/Cutoff Bumped':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        set_tex(mu, matprops.bumpMap, mumat.bumpMap)
        matprops.cutoff = mumat.cutoff
    elif matprops.shader == 'KSP/Alpha/Translucent':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
    elif matprops.shader == 'KSP/Alpha/Translucent Specular':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        matprops.gloss = mumat.gloss
        matprops.specColor = mumat.specColor
        matprops.shininess = mumat.shininess
    elif matprops.shader == 'KSP/Alpha/Unlit Transparent':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        matprops.color = mumat.color
    elif matprops.shader == 'KSP/Unlit':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
        matprops.color = mumat.color
    elif matprops.shader == 'KSP/Diffuse':
        set_tex(mu, matprops.mainTex, mumat.mainTex)
    create_nodes(mat)
    return mat

def shader_update(prop):
    def updater(self, context):
        if not hasattr(context, "material"):
            return
        mat = context.material
        if type(self) == MuTextureProperties:
            pass
        elif type(self) == MuMaterialProperties:
            if (prop) == "shader":
                create_nodes(mat)
            else:
                shader = ksp_shaders[mat.mumatprop.shader]
                nodes = mat.node_tree.nodes
                for s in shader:
                    if s[0] == "set" and s[3] == prop:
                        node_set(mat.name, mat.mumatprop, nodes, s)
                    elif s[0] == "settex" and s[3] == prop:
                        node_settex(mat.name, mat.mumatprop, nodes, s)
    return updater

class MuTextureProperties(bpy.types.PropertyGroup):
    tex = StringProperty(name="tex", update=shader_update("tex"))
    scale = FloatVectorProperty(name="scale", size = 2, subtype='XYZ', default = (1.0, 1.0), update=shader_update("scale"))
    offset = FloatVectorProperty(name="offset", size = 2, subtype='XYZ', default = (0.0, 0.0), update=shader_update("offset"))

class MuMaterialProperties(bpy.types.PropertyGroup):
    shader = EnumProperty(items = shader_items, name = "Shader", update=shader_update("shader"))
    mainTex = PointerProperty(type=MuTextureProperties, name = "mainTex")
    specColor = FloatVectorProperty(name="specColor", size = 4, subtype='COLOR', min = 0.0, max = 1.0, default = (1.0, 1.0, 1.0, 1.0), update=shader_update("specColor"))
    shininess = FloatProperty(name="shininess", update=shader_update("shininess"))
    bumpMap = PointerProperty(type=MuTextureProperties, name = "bumpMap")
    emissive = PointerProperty(type=MuTextureProperties, name = "emissive")
    emissiveColor = FloatVectorProperty(name="emissiveColor", size = 4, subtype='COLOR', min = 0.0, max = 1.0, default = (1.0, 1.0, 1.0, 1.0), update=shader_update("emissiveColor"))
    cutoff = FloatProperty(name="cutoff", min=0, max=1, update=shader_update("cutoff"))
    gloss = FloatProperty(name="gloss", update=shader_update("gloss"))
    color = FloatVectorProperty(name="color", size = 4, subtype='COLOR', min = 0.0, max = 1.0, default = (1.0, 1.0, 1.0, 1.0), update=shader_update("color"))

class MuMaterialPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'
    bl_label = 'Mu Shader'

    @classmethod
    def poll(cls, context):
        return context.material != None

    def drawtex(self, layout, texprop):
        box = layout.box()
        box.prop(texprop, "tex")
        box.prop(texprop, "scale")
        box.prop(texprop, "offset")

    def draw(self, context):
        layout = self.layout
        matprops = context.material.mumatprop
        row = layout.row()
        col = row.column()
        col.prop(matprops, "shader")
        if matprops.shader == 'KSP/Specular':
            self.drawtex(col, matprops.mainTex)
            col.prop(matprops, "specColor")
            col.prop(matprops, "shininess")
        elif matprops.shader == 'KSP/Bumped':
            self.drawtex(col, matprops.mainTex)
            self.drawtex(col, matprops.bumpMap)
        elif matprops.shader == 'KSP/Bumped Specular':
            self.drawtex(col, matprops.mainTex)
            self.drawtex(col, matprops.bumpMap)
            col.prop(matprops, "specColor")
            col.prop(matprops, "shininess")
        elif matprops.shader == 'KSP/Emissive/Diffuse':
            self.drawtex(col, matprops.mainTex)
            self.drawtex(col, matprops.emissive)
            col.prop(matprops, "emissiveColor")
        elif matprops.shader == 'KSP/Emissive/Specular':
            self.drawtex(col, matprops.mainTex)
            col.prop(matprops, "specColor")
            col.prop(matprops, "shininess")
            self.drawtex(col, matprops.emissive)
            col.prop(matprops, "emissiveColor")
        elif matprops.shader == 'KSP/Emissive/Bumped Specular':
            self.drawtex(col, matprops.mainTex)
            self.drawtex(col, matprops.bumpMap)
            col.prop(matprops, "specColor")
            col.prop(matprops, "shininess")
            self.drawtex(col, matprops.emissive)
            col.prop(matprops, "emissiveColor")
        elif matprops.shader == 'KSP/Alpha/Cutoff':
            self.drawtex(col, matprops.mainTex)
            col.prop(matprops, "cutoff")
        elif matprops.shader == 'KSP/Alpha/Cutoff Bumped':
            self.drawtex(col, matprops.mainTex)
            self.drawtex(col, matprops.bumpMap)
            col.prop(matprops, "cutoff")
        elif matprops.shader == 'KSP/Alpha/Translucent':
            self.drawtex(col, matprops.mainTex)
        elif matprops.shader == 'KSP/Alpha/Translucent Specular':
            self.drawtex(col, matprops.mainTex)
            col.prop(matprops, "gloss")
            col.prop(matprops, "specColor")
            col.prop(matprops, "shininess")
        elif matprops.shader == 'KSP/Alpha/Unlit Transparent':
            self.drawtex(col, matprops.mainTex)
            col.prop(matprops, "color")
        elif matprops.shader == 'KSP/Unlit':
            self.drawtex(col, matprops.mainTex)
            col.prop(matprops, "color")
        elif matprops.shader == 'KSP/Diffuse':
            self.drawtex(col, matprops.mainTex)

def register():
    bpy.types.Material.mumatprop = PointerProperty(type=MuMaterialProperties)
