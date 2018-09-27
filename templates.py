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

# copied from io_scene_obj

# <pep8 compliant>

import bpy
from bpy.types import Menu

class TEXT_MT_templates_kspcfg(Menu):
    bl_label = "KSP config"

    def draw (self, context):
        self.path_menu(
            bpy.utils.script_paths("templates_kspcfg"),
            "text.open",
            props_default={"internal": True},
        )

def text_func_templates(self, context):
    self.layout.menu("TEXT_MT_templates_kspcfg");

classes = (
    TEXT_MT_templates_kspcfg,
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.VIEW3D_MT_add.append(text_func_templates)

def unregister():
    bpy.types.INFO_MT_add.remove(text_func_templates)

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
