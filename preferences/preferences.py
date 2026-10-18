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
from bpy.types import AddonPreferences
from bpy.props import StringProperty, BoolProperty

package_name = __package__.split(".")[0]


class IOObjectMu_AddonPreferences(AddonPreferences):
    """Persistent addon settings (drawn in View3D Options, not here)."""
    bl_idname = package_name

    GameData: StringProperty(
        name="GameData Path",
        description="Path to KSP GameData tree",
        subtype='DIR_PATH')

    AutohideColliders: BoolProperty(
        name="Autohide Mesh Colliders",
        description="Automatically hide new mesh colliders",
        default=False)

    WritePartCfg: BoolProperty(
        name="Write / Update Part Cfg",
        description=(
            "When enabled: Mu export to a new folder writes a patched part.cfg, "
            "and Save Part Cfg is available. ModulePartVariants live in the cfg "
            "(GAMEOBJECTS/TEXTURE), not as Outliner collections"
        ),
        default=True)

    def draw(self, context):
        layout = self.layout
        layout.label(text="See View3D Sidebar ▸ Tool ▸ Options")


def Preferences():
    preferences = bpy.context.preferences
    addons = preferences.addons
    prefs = addons[package_name]
    return prefs.preferences


classes_to_register = (
    IOObjectMu_AddonPreferences,
)
