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
from .operators import KSPMU_OT_ScanModuleDefs

class KSPMU_UL_KSPModuleField_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if item:
            prop = getattr(data, item.property)[item.name]
            layout.prop(prop, "name", text="", emboss=False, icon_value=icon)
        else:
            layout.label(text="", icon_value=icon)

def draw_module(layout, module, index):
    box = layout.box()
    row = box.row()
    row.operator("object.kspmodule_expand", text="",
                 icon='TRIA_DOWN' if module.expanded else 'TRIA_RIGHT',
                 emboss=False).index = index
    row.label(text = module.name)
    rem_op = "object.remove_ksp_module"
    row.operator(rem_op, icon='X', text="").index = index
    if module.expanded:
        box.separator()
        row = box.row()
        col = row.column()
        col.template_list("KSPMU_UL_KSPModuleField_list",
                          f"{index}.{module.name}", module,
                          "fields", module, "index",
                          item_dyntip_propname="description")
        if len(module.fields) > module.index >= 0:
            module.draw_item(box)

class OBJECT_PT_KSPModulesPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_label = 'KSP Modules'

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        modules = context.active_object.kspmodules.modules
        row = layout.row()
        row.operator_menu_enum("object.add_ksp_module", "type")
        row.operator(KSPMU_OT_ScanModuleDefs.bl_idname, text="", icon='FILE_REFRESH')
        col = row.column()
        index = 0
        for mod in modules:
            draw_module (layout, mod, index)
            index += 1

classes_to_register = (
    KSPMU_UL_KSPModuleField_list,
    OBJECT_PT_KSPModulesPanel,
)
