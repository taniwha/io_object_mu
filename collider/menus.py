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

class INFO_MT_mucollider_add(bpy.types.Menu):
    bl_idname = "INFO_MT_mucollider_add"
    bl_label = "Mu Collider"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.operator("mucollider.mesh", text = "Mesh");
        layout.operator("mucollider.sphere", text = "Sphere");
        layout.operator("mucollider.capsule", text = "Capsule");
        layout.operator("mucollider.box", text = "Box");
        layout.operator("mucollider.wheel", text = "Wheel");

def add_collider_menu_func(self, context):
    self.layout.menu("INFO_MT_mucollider_add", icon='PLUGIN')

classes_to_register = (
    INFO_MT_mucollider_add,
)

menus_to_register = (
    (bpy.types.VIEW3D_MT_add, add_collider_menu_func),
)
