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

import bpy, os
from bpy.types import AddonPreferences, Menu
from bpy.props import StringProperty, BoolProperty

def install_presets(subdir):
    presets=bpy.utils.script_paths("presets")
    dst=presets[-1] + "/" + shader.IO_OBJECT_MU_MT_shader_presets.preset_subdir
    src=os.path.dirname(os.path.abspath(__file__)) + "/presets/" + subdir
    if not os.access(dst, os.F_OK):
        os.makedirs(dst)
    names = os.listdir(src)
    for name in names:
        s = src + "/" + name
        d = dst + "/" + name
        with open(s, "rb") as fsrc:
            with open(d, "wb") as fdst:
                while True:
                    buf = fsrc.read(16*1024)
                    if not buf:
                        break
                    fdst.write(buf)

class KSPMU_OT_InstallShaders(bpy.types.Operator):
    bl_idname = 'io_object_mu_presets.shaders'
    bl_label = 'Install KSP Shader Presets'

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        install_presets("shaders")
        self.report({'INFO'}, 'Shader presets installed.')
        return {'FINISHED'}

class KSPMU_OT_CreateColorPalettes(bpy.types.Operator):
    bl_idname = 'io_object_mu_presets.color_palettes'
    bl_label = 'Create Community Color Palettes'

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        colorpalettes.install()
        self.report({'INFO'}, 'Color palettes created.')
        return {'FINISHED'}

class IOObjectMu_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    GameData: StringProperty(
        name="GameData Path",
        description="Path to KSP GameData tree",
        subtype='DIR_PATH')

    def draw(self, context):
        layout = self.layout
        box = layout.box ()
        box.label(text="KSP:")
        box.prop(self, "GameData")
        box.label(text="Shaders:")
        box.operator(InstallShaders.bl_idname, InstallShaders.bl_label);
        box.label(text="Color Paletes:")
        cbox = box.box()
        cbox.operator(CreateColorPalettes.bl_idname, CreateColorPalettes.bl_label);
        cbox.label(text="NOTE: this must be done for each new blend file or saved to your startup file.", icon="LAYER_USED")
        cbox.label(text="NOTE2: overwrites existing palettes that have the same names", icon="LAYER_USED")

def Preferences():
    user_preferences = bpy.context.user_preferences
    addons = user_preferences.addons
    return addons[__package__].preferences

classes = (
    IOObjectMu_AddonPreferences,
)
register, unregister = bpy.utils.register_classes_factory(classes)
