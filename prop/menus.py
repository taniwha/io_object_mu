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

import os

import bpy

from .operators import OBJECT_OT_add_ksp_prop

def add_prop_menu_func(self, context):
    """
    Add a custom menu item to the menu.

    Args:
        self: (todo): write your description
        context: (todo): write your description
    """
    layout = self.layout
    if len(OBJECT_OT_add_ksp_prop._enum_item_cache) > 10:
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.operator(OBJECT_OT_add_ksp_prop.bl_idname,
                        text="KSP Prop...",
                        icon='OUTLINER_OB_GROUP_INSTANCE')
    else:
        layout.operator_menu_enum(OBJECT_OT_add_ksp_prop.bl_idname,
                                  "prop_item", text="KSP Prop",
                                  icon='OUTLINER_OB_GROUP_INSTANCE')

menus_to_register = (
    (bpy.types.VIEW3D_MT_add, add_prop_menu_func),
)
