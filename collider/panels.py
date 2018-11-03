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

class WORKSPACE_PT_tools_mu_collider(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_category = "Mu Tools"
    bl_context = ".workspace"
    bl_label = "Add Mu Collider"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Single Collider:")
        layout.operator("mucollider.mesh", text = "Mesh")
        layout.operator("mucollider.sphere", text = "Sphere")
        layout.operator("mucollider.capsule", text = "Capsule")
        layout.operator("mucollider.box", text = "Box")
        layout.operator("mucollider.wheel", text = "Wheel")

        col = layout.column(align=True)
        col.label(text="Multiple Colliders:")
        layout.operator("mucollider.from_mesh", text = "Selected Meshes")
        layout.operator("mucollider.mesh_to_collider", text = "Selected Meshes")

classes_to_register = (
    WORKSPACE_PT_tools_mu_collider,
)
