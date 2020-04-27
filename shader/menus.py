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

from .. import preferences
from . import shader

class IO_OBJECT_MU_MT_shader_presets(bpy.types.Menu):
    bl_label = "Shader Presets"
    bl_idname = "IO_OBJECT_MU_MT_shader_presets"
    preset_subdir = preferences.package_name + "/shaders"
    preset_operator = "script.execute_preset"
    draw = bpy.types.Menu.draw_preset

    @classmethod
    def reset_cb(cls, context):
        mat = context.material
        if mat.use_nodes:
            mat.node_tree.nodes.clear()
            mat.node_tree.links.clear()

    @classmethod
    def post_cb(cls, context):
        mat = context.material
        shader.create_nodes(mat)

classes_to_register = (
    IO_OBJECT_MU_MT_shader_presets,
)
