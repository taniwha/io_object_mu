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

import bpy

from .operators import IO_OBJECT_MU_OT_shader_presets

class OBJECT_UL_ShaderProperty_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if item:
            layout.prop(item, "name", text="", emboss=False, icon_value=icon)
        else:
            layout.label(text="", icon_value=icon)

def draw_property_list(layout, propset, propsetname):
    box = layout.box()
    row = box.row()
    row.operator("object.mushaderprop_expand", text="",
                 icon='TRIA_DOWN' if propset.expanded else 'TRIA_RIGHT',
                 emboss=False).propertyset = propsetname
    row.label(text = propset.bl_label)
    row.label(text = "",
              icon = 'RADIOBUT_ON' if propset.properties else 'RADIOBUT_OFF')
    if propset.expanded:
        box.separator()
        row = box.row()
        col = row.column()
        col.template_list("OBJECT_UL_ShaderProperty_list", "", propset,
                          "properties", propset, "index")
        col = row.column(align=True)
        add_op = "object.mushaderprop_add"
        rem_op = "object.mushaderprop_remove"
        col.operator(add_op, icon='ADD', text="").propertyset = propsetname
        col.operator(rem_op, icon='REMOVE', text="").propertyset = propsetname
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

classes_to_register = (
    OBJECT_UL_ShaderProperty_list,
    OBJECT_PT_MuMaterialPanel,
)
