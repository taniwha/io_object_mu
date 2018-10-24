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

submodule_names = (
    "colorprops",
    "float2props",
    "float3props",
    "textureprops",
    "vectorprops",

    "cameraprops",
    "imageprops",
    "lightprops",

    "collider",
    "colorpalettes",
    "export_mu",
    "gamedata",
    "import_craft",
    "import_mu",
    "model",
    "part",
    "preferences",
    "prop",
    "properties",
    "quickhull",
    "shader",
    "shaderprops",
    "templates",
)

from bpy.props import PointerProperty
from bpy.utils import register_class, unregister_class

module = None
submodules = []
def register():
    global module
    module = __import__(name=__name__, fromlist=submodule_names)
    submodules[:] = [getattr(module, name) for name in submodule_names]
    for mod in submodules:
        m = [(),()]
        if hasattr(mod, "classes"):
            m[0] = mod.classes
            for cls in mod.classes:
                register_class(cls)
        if hasattr(mod, "menus"):
            m[1] = mod.menus
            for menu in mod.menus:
                menu[0].append(menu[1])
        if hasattr(mod, "custom_properties"):
            for prop in mod.custom_properties:
                setattr(prop[0], prop[1], PointerProperty(type=prop[2]))
        if m[0] or m[1]:
            submodules.append(m)


def unregister():
    for mod in reversed(submodules):
        for menu in reversed(mod[1]):
            menu[0].remove(menu[1])
        for cls in reversed(mod[0]):
            unregister_class(cls)

if __name__ == "__main__":
    register()
