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

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, MuMaterial

mainTex_block = (
    ("node", "Output", 'ShaderNodeOutput', (630, 730)),
    ("node", "mainMaterial", 'ShaderNodeMaterial', (70, 680)),
    ("node", "geometry", 'ShaderNodeGeometry', (-590, 260)),
    ("node", "mainTex", 'ShaderNodeTexture', (-380, 480)),
    ("link", "geometry", "UV", "mainTex", "Vector"),
    ("link", "mainTex", "Color", "mainMaterial", "Color"),
    ("settex", "mainTex", "texture", "_MainTex"),
    ("link", "mainMaterial", "Color", "Output", "Color"),
)

specular_block = (
    ("node", "specColor", 'ShaderNodeValToRGB', (-210, 410)),
    ("link", "mainTex", "Value", "specColor", "Fac"),
    ("link", "specColor", "Color", "mainMaterial", "Spec"),
    ("set", "specColor", "color_ramp.elements[1].color", "colorProps", "_SpecColor"),
    #FIXME shinines
)

bumpmap_block = (
    ("node", "bumpMap", 'ShaderNodeMaterial', (-380, 480)),
    ("link", "bumpMap", "Normal", "mainMaterial", "Normal"),
    ("call", "bumpMap", "material.texture_slots.add()"),
    ("settex", "bumpMap", "material.texture_slots[0].texture", "_BumpMap"),
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
    ("settex", "emissive", "texture", "_Emissive"),
    ("set", "emissiveColor", "color_ramp.elements[1].color", "colorProps", "_EmissiveColor"),
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
    ("set", "alphaCutoff", "inputs[1].default_value", "float3Props", "_Cutoff"),
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
ksp_particles_alpha_blended = mainTex_block
ksp_particles_additive = mainTex_block

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
"KSP/Particles/Alpha Blended":ksp_particles_alpha_blended,
"KSP/Particles/Additive":ksp_particles_additive,
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
    ('KSP/Particles/Alpha Blended', "KSP/Particles/Alpha Blended", ""),
    ('KSP/Particles/Additive', "KSP/Particles/Additive", ""),
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
    str="n.%s = matprops.%s['%s'].value" % (s[2], s[3], s[4])
    exec(str, {}, locals())

def node_settex(name, matprops, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    tex = matprops.textureProps[s[3]]
    if tex.tex in bpy.data.textures:
        tex = bpy.data.textures[tex.tex]
        exec("n.%s = tex" % s[2], {}, locals())

def node_setval(name, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    exec("n.%s = %s" % (s[2], repr(s[3])), {}, locals())

def node_call(name, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    exec("n.%s" % s[2], {}, locals())

def create_nodes(mat):
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    while len(links):
        links.remove(links[0])
    while len(nodes):
        nodes.remove(nodes[0])
    if mat.mumatprop.shaderName not in ksp_shaders:
        print("Unknown shader: '%s'" % mat.mumatprop.shaderName)
        return
    shader = ksp_shaders[mat.mumatprop.shaderName]
    for s in shader:
        #print(s)
        try :
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
        except:
           print("Exception in node setup code:")
           traceback.print_exc(file=sys.stdout)

def set_tex(mu, dst, src):
    try:
        dst.tex = mu.textures[src.index].name
    except IndexError:
        pass
    dst.scale = src.scale
    dst.offset = src.offset

def make_shader_prop(muprop, blendprop):
    for k in muprop:
        item = blendprop.add()
        item.name = k
        item.value = muprop[k]

def make_shader_tex_prop(mu, muprop, blendprop):
    for k in muprop:
        item = blendprop.add()
        item.name = k
        set_tex(mu, item, muprop[k])

def make_shader4(mumat, mu):
    mat = bpy.data.materials.new(mumat.name)
    matprops = mat.mumatprop
    matprops.shaderName = mumat.shaderName
    make_shader_prop(mumat.colorProperties, matprops.colorProps)
    make_shader_prop(mumat.vectorProperties, matprops.vectorProps)
    make_shader_prop(mumat.floatProperties2, matprops.float2Props)
    make_shader_prop(mumat.floatProperties3, matprops.float3Props)
    make_shader_tex_prop(mu, mumat.textureProperties, matprops.textureProps)
    create_nodes(mat)
    return mat

def make_shader(mumat, mu):
    return make_shader4(mumat, mu)

def shader_update(prop):
    def updater(self, context):
        print("shader_update")
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

class MuColorProp(bpy.types.PropertyGroup):
    value=FloatVectorProperty(name="", size = 4, subtype='COLOR', min = 0.0, max = 1.0, default = (1.0, 1.0, 1.0, 1.0), update=shader_update("specColor"))

class MuVectorProp(bpy.types.PropertyGroup):
    value=FloatVectorProperty(name="", size = 4, subtype='XYZ', min = 0.0, max = 1.0, default = (0.0, 0.0, 0.0, 0.0), update=shader_update("specColor"))

class MuFloatProp2(bpy.types.PropertyGroup):
    value=FloatProperty(name="", update=shader_update("specColor"))

class MuFloatProp3(bpy.types.PropertyGroup):
    value=FloatProperty(name="", update=shader_update("specColor"))

class MuMaterialProperties(bpy.types.PropertyGroup):
    name = StringProperty(name="Name")
    shaderName = StringProperty(name="Shader")
    colorProps = CollectionProperty(type=MuColorProp, name="Colors")
    colorProp_idx = IntProperty()
    vectorProps = CollectionProperty(type=MuVectorProp, name="Vectors")
    vectorProp_idx = IntProperty()
    float2Props = CollectionProperty(type=MuFloatProp2, name="Float2")
    float2Prop_idx = IntProperty()
    float3Props = CollectionProperty(type=MuFloatProp3, name="Float3")
    float3Prop_idx = IntProperty()
    textureProps = CollectionProperty(type=MuTextureProperties, name = "Textures")
    textureProp_idx = IntProperty()

class Property_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        layout.label(item.name)

def draw_texture_item(layout, item):
    row = layout.row()
    col = row.column()
    col.prop(item, "tex", "")
    col.prop(item, "scale", "")
    col.prop(item, "offset", "")

def draw_basic_item(layout, item):
    row = layout.row()
    col = row.column()
    col.prop(item, "name", "Name")
    col.prop(item, "value", "")

def draw_property_list(layout, properties, propname, draw_item):
        row = layout.row()
        col = row.column()
        col.template_list("Property_list", "", properties, propname+"s",
                          properties, propname+"_idx", rows=1)
        col = row.column(align=True)
        col.operator("object.entprop_add", icon='ZOOMIN', text="")
        col.operator("object.entprop_remove", icon='ZOOMOUT', text="")
        index = getattr(properties, propname+"_idx")
        proplist = getattr(properties, propname+"s")
        if len(proplist) > index >= 0:
            draw_item(layout, proplist[index])

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
        col.prop(matprops, "name")
        col.prop(matprops, "shaderName")
        draw_property_list(layout, matprops, "textureProp", draw_texture_item)
        draw_property_list(layout, matprops, "colorProp", draw_basic_item)
        draw_property_list(layout, matprops, "vectorProp", draw_basic_item)
        draw_property_list(layout, matprops, "float2Prop", draw_basic_item)
        draw_property_list(layout, matprops, "float3Prop", draw_basic_item)

def register():
    bpy.types.Material.mumatprop = PointerProperty(type=MuMaterialProperties)
