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
    "collider",
    "export_mu",
    "import_craft",
    "import_mu",
    "model",
    "module",
    "preferences",
    "prop",
    "properties",
    "quickhull",
    "shader",
    "tools",
)

from bpy.props import PointerProperty
from bpy.utils import register_class, unregister_class

import importlib
import sys

registered_submodules = []

# When the addon is reloaded, this module gets reloaded, however none
# of the other modules from this addon get reloaded. As a result, they
# don't call register_submodules (only run when the module is loaded) and
# thus they don't end up registering everything.
#
# This is set before any loading starts (in register), to a set of all the
# names of the modules loaded as of when loading starts. While doing the
# module loading, check if a module is present in this list. If so, reload
# it and remove it from the set (to prevent it from getting reloaded twice).
preloaded_modules = None

def register_submodules(name, submodule_names):
    global preloaded_modules
    module = __import__(name=name, fromlist=submodule_names)
    submodules = [getattr(module, name) for name in submodule_names]
    for mod in submodules:

        # Look through the modules present when register was called. If this
        # module was already loaded, then reload it.
        if mod.__name__ in preloaded_modules:
            mod = importlib.reload(mod)

            # Prevent the module from getting reloaded more than once
            preloaded_modules.remove(mod.__name__)

        m = [(),()]
        if hasattr(mod, "classes_to_register"):
            m[0] = mod.classes_to_register
            for cls in mod.classes_to_register:
                register_class(cls)
        if hasattr(mod, "menus_to_register"):
            m[1] = mod.menus_to_register
            for menu in mod.menus_to_register:
                menu[0].append(menu[1])
        if hasattr(mod, "custom_properties_to_register"):
            for prop in mod.custom_properties_to_register:
                setattr(prop[0], prop[1], PointerProperty(type=prop[2]))
        if m[0] or m[1]:
            registered_submodules.append(m)

def register():
    global preloaded_modules
    preloaded_modules = set(sys.modules.keys())
    register_submodules(__name__, submodule_names);
    preloaded_modules = None

def unregister():
    for mod in reversed(registered_submodules):
        for menu in reversed(mod[1]):
            menu[0].remove(menu[1])
        for cls in reversed(mod[0]):
            unregister_class(cls)
    registered_submodules.clear()

if __name__ == "__main__":
    register()
