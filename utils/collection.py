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

from .scene import util_scene

def util_collection(name):
    """
    Renders a view.

    Args:
        name: (str): write your description
    """
    scene = util_scene()
    if name not in bpy.data.collections:
        util_col = bpy.data.collections.new(name)
        util_col.hide_viewport = True
        util_col.hide_render = True
        util_col.hide_select = True
        scene.collection.children.link(util_col)
    return bpy.data.collections[name]
