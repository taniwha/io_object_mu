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

bl_info = {
    "name": "Mu model format (KSP)",
    "author": "Bill Currie",
    "blender": (2, 80, 0),
    "api": 35622,
    "location": "File > Import-Export",
    "description": "Import-Export KSP Mu format files. (.mu)",
    "warning": "not even alpha",
    "wiki_url": "",
    "tracker_url": "",
#    "support": 'OFFICIAL',
    "category": "Import-Export"}

submodules = (
    "colorprops",
    "float2props",
    "float3props",
    "textureprops",
    "vectorprops",

    "collider",
    "export_mu",
    "import_craft",
    "import_mu",
    "preferences",
    "prop",
    "properties",
    "shader",
)

from bpy.utils import register_submodule_factory

register, unregister = register_submodule_factory(__name__, submodules)

if __name__ == "__main__":
    register()
