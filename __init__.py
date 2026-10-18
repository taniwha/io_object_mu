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
    "version": (1, 0, 0),
    "author": "Bill Currie",
    # Minimum: EEVEE Next / Mix node / node-group interface (Blender 4.2 LTS).
    "blender": (4, 2, 0),
    "api": 35622,
    "location": "File > Import-Export",
    "description": (
        "Import-Export KSP MU (.mu), KSP (.ksp), CRAFT (.craft) format files. "
        "Targets KSP 1.12.x."
    ),
    "doc_url": "https://github.com/taniwha/io_object_mu",
    "tracker_url": "https://github.com/taniwha/io_object_mu/issues",
#    "support": 'OFFICIAL',
    "category": "Import-Export"}

_MIN_BLENDER = (4, 2, 0)

submodule_names = (
    "collider",
    "export_craft",
    "export_ksp",
    "export_mu",
    "import_craft",
    "import_ksp",
    "import_mu",
    "mu_browser",
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
    import bpy
    ver = tuple(bpy.app.version[:3])
    if ver < _MIN_BLENDER:
        print(
            "ERROR: Mu model format (KSP) requires Blender %d.%d.%d or newer "
            "(this is %d.%d.%d). Addon not registered."
            % (_MIN_BLENDER + ver)
        )
        return

    global preloaded_modules
    preloaded_modules = set(sys.modules.keys())
    register_submodules(__name__, submodule_names);
    preloaded_modules = None
    try:
        from .tools import _hide_stock_options_panels
        _hide_stock_options_panels()
    except Exception:
        pass
    try:
        from .translations import register as register_translations
        register_translations()
    except Exception:
        pass
    try:
        from .shader.colorprops import register_handlers as _mu_color_handlers
        _mu_color_handlers()
    except Exception:
        pass
    try:
        from .tools.display import register as _mu_display_register
        _mu_display_register()
    except Exception:
        pass
    try:
        from .preferences import colorpalettes as _mu_colorpalettes
        _mu_colorpalettes.register()
    except Exception:
        pass
    try:
        from .import_mu.name_protect import ensure_name_protect_handler
        ensure_name_protect_handler()
    except Exception:
        pass


def unregister():
    try:
        from .mu_browser.panels import remove_alc_redraw_handler
        remove_alc_redraw_handler()
    except Exception:
        pass
    try:
        from .import_mu.name_protect import remove_name_protect_handler
        remove_name_protect_handler()
    except Exception:
        pass
    try:
        from .import_ksp.mu_ops import (
            remove_selection_handler,
            unregister_ui_delete_keymap,
        )
        unregister_ui_delete_keymap()
        remove_selection_handler()
    except Exception:
        pass
    try:
        from .import_ksp.blend_persist import remove_blend_handlers
        remove_blend_handlers()
    except Exception:
        pass
    try:
        from .preferences import colorpalettes as _mu_colorpalettes
        _mu_colorpalettes.unregister()
    except Exception:
        pass
    try:
        from .tools.display import unregister as _mu_display_unregister
        _mu_display_unregister()
    except Exception:
        pass
    try:
        from .shader.colorprops import unregister_handlers as _mu_color_unhandlers
        _mu_color_unhandlers()
    except Exception:
        pass
    try:
        from .translations import unregister as unregister_translations
        unregister_translations()
    except Exception:
        pass
    try:
        from .tools import _restore_stock_options_panels
        _restore_stock_options_panels()
    except Exception:
        pass
    for mod in reversed(registered_submodules):
        for menu in reversed(mod[1]):
            try:
                menu[0].remove(menu[1])
            except Exception:
                pass
        for cls in reversed(mod[0]):
            # Background quit / partial register can leave classes without bl_rna
            try:
                unregister_class(cls)
            except RuntimeError:
                pass
    registered_submodules.clear()

if __name__ == "__main__":
    register()
