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

class WORKSPACE_PT_tools_mu_tools2(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_category = "Mu Tools 2"
    bl_context = ".workspace"
    bl_label = "Export Mu"

    def draw(self, context):
        layout = self.layout
        #col = layout.column(align=True)
        layout.operator("object.mu_apply_scale", text = "Apply Scale");
        layout.operator("object.mu_clearinverse", text = "Clear Inverse");

classes_to_register = (
    WORKSPACE_PT_tools_mu_tools2,
)
