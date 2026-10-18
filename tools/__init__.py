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

from .. import register_submodules

submodule_names = (
    "applyscale",
    "clearinverse",
    "display",
    "panels",
    "wingtool",
)
register_submodules(__name__, submodule_names)

# Stock "Options" panels (Affect Only, etc.) share Tool + label "Options"
# with Mu. Hide them so our Options panel is the one before Prop Tools.
_hidden_options_panels = []


def _hide_stock_options_panels():
    global _hidden_options_panels
    _hidden_options_panels = []
    for name in (
        "VIEW3D_PT_tools_object_options",
        "VIEW3D_PT_tools_meshedit_options",
        "VIEW3D_PT_tools_armatureedit_options",
        "VIEW3D_PT_tools_posedit_options",
    ):
        cls = getattr(bpy.types, name, None)
        if cls is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
            _hidden_options_panels.append(cls)
        except Exception:
            pass


def _restore_stock_options_panels():
    global _hidden_options_panels
    for cls in _hidden_options_panels:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    _hidden_options_panels = []
