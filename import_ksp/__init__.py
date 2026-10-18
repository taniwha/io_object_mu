# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

from .. import register_submodules

submodule_names = (
    "properties",
    "import_ksp",
    "operators",
    "mu_ops",
    "panels",
)
register_submodules(__name__, submodule_names)

try:
    from .mu_ops import ensure_selection_handler, register_ui_delete_keymap
    ensure_selection_handler()
    register_ui_delete_keymap()
    try:
        from .menu_check import register_menu_check_wm_props
        register_menu_check_wm_props()
    except Exception:
        pass
except Exception:
    pass

try:
    from .blend_persist import ensure_blend_handlers
    ensure_blend_handlers()
except Exception:
    pass

