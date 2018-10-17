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
from bpy.types import Operator, Menu
from bl_operators.presets import AddPresetBase
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, MuMaterial
from . import shaderprops
from .colorprops import  MuMaterialColorPropertySet
from .float2props import MuMaterialFloat2PropertySet
from .float3props import MuMaterialFloat3PropertySet
from .textureprops import MuMaterialTexturePropertySet
from .vectorprops import MuMaterialVectorPropertySet

mainTex_block = (
    ("node", "mainTex", 'ShaderNodeTexImage', (-460, 300)),
    ("node", "uv", 'ShaderNodeUVMap', (-640, 120)),
    ("link", "uv", "UV", "mainTex", "Vector"),
    ("settex", "mainTex", "image", "_MainTex"),
)

specularity_block = (
    ("node", "specular", 'ShaderNodeEeveeSpecular', (60, 320)),
    ("node", "shininess", 'ShaderNodeMath', (-140, 240)),
    ("link", "mainTex", "Color", "specular", "Base Color"),
    ("link", "mainTex", "Alpha", "shininess", "inputs[1]"),
    ("link", "shininess", "outputs[0]", "specular", "Roughness"),
    ("set", "specular", "inputs['Specular'].default_value", "color.properties", "_SpecColor"),
    ("setval", "shininess", "inputs[0].default_value", 1),
    ("setval", "shininess", "hide", True),
)

specular_block = (
    ("node", "output", 'ShaderNodeOutputMaterial', (230, 320)),
    ("node", "geometry", 'ShaderNodeNewGeometry', (-140, 200)),
    ("link", "specular", "BSDF", "output", "Surface"),
    ("link", "geometry", "Normal", "specular", "Normal"),
)

bumpmap_block = (
    ("node", "bumpMap", 'ShaderNodeMaterial', (-380, 480)),
    ("link", "bumpMap", "Normal", "diffuseShader", "Normal"),
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
    ("set", "emissiveColor", "color_ramp.elements[1].color", "color.properties", "_EmissiveColor"),
    ("setval", "emissiveMaterial", "use_specular", False),
    ("setval", "emissiveMaterial", "material.emit", 1.0),
    ("node", "mix", 'ShaderNodeMixRGB', (430, 610)),
    ("link", "diffuseShader", "Color", "mix", "Color1"),
    ("link", "emissiveMaterial", "Color", "mix", "Color2"),
    ("link", "mix", "Color", "Output", "Color"),
    ("setval", "mix", "blend_type", 'ADD'),
    ("setval", "mix", "inputs['Fac'].default_value", 1.0),
)

alpha_cutoff_block = (
    ("node", "alphaCutoff", 'ShaderNodeMath', (-230, 30)),
    ("link", "mainTex", "Value", "alphaCutoff", 0),
    ("link", "alphaCutoff", "Value", "Output", "Alpha"),
    ("set", "alphaCutoff", "inputs[1].default_value", "float3.properties", "_Cutoff"),
)

ksp_specular = mainTex_block + specularity_block + specular_block
ksp_bumped = mainTex_block + bumpmap_block
ksp_bumped_specular = mainTex_block + specularity_block + bumpmap_block
ksp_emissive_diffuse = mainTex_block + emissive_block
ksp_emissive_specular = mainTex_block + emissive_block + specularity_block
ksp_emissive_bumped_specular = (mainTex_block + emissive_block
                                + specularity_block + bumpmap_block)
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

def node_node(name, nodes, s):
    n = nodes.new(s[2])
    #print(s[2])
    #for i in n.inputs:
    #    print(i.name)
    #for o in n.outputs:
    #    print(o.name)
    n.name = "%s.%s" % (name, s[1])
    n.label = s[1]
    n.location = s[3]
    if s[2] == "ShaderNodeMaterial":
        n.material = bpy.data.materials.new(n.name)

def node_link(name, nodes, links, s):
    n1 = nodes["%s.%s" % (name, s[1])]
    n2 = nodes["%s.%s" % (name, s[3])]
    if s[2][:7] == "outputs":
        op = eval("n1.%s" % s[2])
    else:
        op = n1.outputs[s[2]]
    if s[4][:6] == "inputs":
        ip = eval("n2.%s" % s[4])
    else:
        ip = n2.inputs[s[4]]
    links.new(op, ip)

def node_set(name, matprops, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    str="n.%s = matprops.%s['%s'].value" % (s[2], s[3], s[4])
    exec(str, {}, locals())

def node_settex(name, matprops, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    tex = matprops.texture.properties[s[3]]
    img = tex.tex
    if img[-4:-3] == ".":
        img = img[:-4]
    print("img =", img)
    if img in bpy.data.images:
        tex = bpy.data.images[img]
        exec("n.%s = tex" % s[2], {}, locals())

def node_setval(name, nodes, s):
    n = nodes["%s.%s" % (name, s[1])]
    #print(s)
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
    print(mat.mumatprop.shaderName)
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
        tex = mu.textures[src.index]
        dst.tex = tex.name
        dst.type = tex.type
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
    make_shader_prop(mumat.colorProperties, matprops.color.properties)
    make_shader_prop(mumat.vectorProperties, matprops.vector.properties)
    make_shader_prop(mumat.floatProperties2, matprops.float2.properties)
    make_shader_prop(mumat.floatProperties3, matprops.float3.properties)
    make_shader_tex_prop(mu, mumat.textureProperties, matprops.texture.properties)
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

def shader_items(self, context):
    slist = list(shader_properties.keys())
    slist.sort()
    enum = (('', "", ""),)
    enum += tuple(map(lambda s: (s, s, ""), slist))
    return enum

class IO_OBJECT_MU_MT_shader_presets(Menu):
    bl_label = "Shader Presets"
    bl_idname = "IO_OBJECT_MU_MT_shader_presets"
    preset_subdir = "io_object_mu/shaders"
    preset_operator = "script.execute_preset"
    draw = Menu.draw_preset


class IO_OBJECT_MU_OT_shader_presets(AddPresetBase, Operator):
    bl_idname = "io_object_mu.shader_presets"
    bl_label = "Shaders"
    bl_description = "Mu Shader Presets"
    preset_menu = "IO_OBJECT_MU_MT_shader_presets"
    preset_subdir = "io_object_mu/shaders"

    preset_defines = [
        "mat = bpy.context.material.mumatprop"
        ]
    preset_values = [
        "mat.name",
        "mat.shaderName",
        "mat.color",
        "mat.vector",
        "mat.float2",
        "mat.float3",
        "mat.texture",
        ]

# Draw into an existing panel
def panel_func(self, context):
    layout = self.layout

    row = layout.row(align=True)
    row.menu(OBJECT_MT_draw_presets.__name__, text=OBJECT_MT_draw_presets.bl_label)
    row.operator(AddPresetObjectDraw.bl_idname, text="", icon='ZOOMIN')
    row.operator(AddPresetObjectDraw.bl_idname, text="", icon='ZOOMOUT').remove_active = True

class MuMaterialProperties(bpy.types.PropertyGroup):
    name: StringProperty(name="Name")
    shaderName: StringProperty(name="Shader")
    color: PointerProperty(type = MuMaterialColorPropertySet)
    vector: PointerProperty(type = MuMaterialVectorPropertySet)
    float2: PointerProperty(type = MuMaterialFloat2PropertySet)
    float3: PointerProperty(type = MuMaterialFloat3PropertySet)
    texture: PointerProperty(type = MuMaterialTexturePropertySet)

class OBJECT_UL_Property_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if item:
            layout.prop(item, "name", text="", emboss=False, icon_value=icon)
        else:
            layout.label(text="", icon_value=icon)

def draw_property_list(layout, propset, propsetname):
    box = layout.box()
    row = box.row()
    row.operator("object.mushaderprop_expand",
                 icon='TRIA_DOWN' if propset.expanded else 'TRIA_RIGHT',
                 emboss=False).propertyset = propsetname
    row.label(text = propset.bl_label)
    row.label(text = "",
              icon = 'RADIOBUT_ON' if propset.properties else 'RADIOBUT_OFF')
    if propset.expanded:
        box.separator()
        row = box.row()
        col = row.column()
        col.template_list("OBJECT_UL_Property_list", "", propset, "properties", propset, "index")
        col = row.column(align=True)
        add_op = "object.mushaderprop_add"
        rem_op = "object.mushaderprop_remove"
        col.operator(add_op, icon='ZOOMIN', text="").propertyset = propsetname
        col.operator(rem_op, icon='ZOOMOUT', text="").propertyset = propsetname
        if len(propset.properties) > propset.index >= 0:
            propset.draw_item(box)

class OBJECT_PT_MuMaterialPanel(bpy.types.Panel):
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
        r = col.row(align=True)
        r.menu("IO_OBJECT_MU_MT_shader_presets",
               text=IO_OBJECT_MU_OT_shader_presets.bl_label)
        r.operator("io_object_mu.shader_presets", text="", icon='ADD')
        r.operator("io_object_mu.shader_presets", text="", icon='REMOVE').remove_active = True
        col.prop(matprops, "name")
        col.prop(matprops, "shaderName")
        draw_property_list(layout, matprops.texture, "texture")
        draw_property_list(layout, matprops.color, "color")
        draw_property_list(layout, matprops.vector, "vector")
        draw_property_list(layout, matprops.float2, "float2")
        draw_property_list(layout, matprops.float3, "float3")

classes = (
    IO_OBJECT_MU_MT_shader_presets,
    IO_OBJECT_MU_OT_shader_presets,
    MuMaterialProperties,
    OBJECT_UL_Property_list,
    OBJECT_PT_MuMaterialPanel,
)
custom_properties = (
    (bpy.types.Material, "mumatprop", MuMaterialProperties),
)
