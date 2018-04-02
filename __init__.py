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
    "blender": (2, 7, 0),
    "api": 35622,
    "location": "File > Import-Export",
    "description": "Import-Export KSP Mu format files. (.mu)",
    "warning": "not even alpha",
    "wiki_url": "",
    "tracker_url": "",
#    "support": 'OFFICIAL',
    "category": "Import-Export"}

# To support reload properly, try to access a package var, if it's there,
# reload everything
if "bpy" in locals():
    import imp
    if "import_mu" in locals():
        imp.reload(import_mu)
    if "export_mu" in locals():
        imp.reload(export_mu)


import bpy, os
from bpy.types import AddonPreferences, Menu
from bpy.props import StringProperty, BoolProperty

from . import collider, properties, shader
from . import export_mu
from . import import_mu
from . import import_craft
from . import prop
from . import quickhull

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

class InstallShaders(bpy.types.Operator):
    bl_idname = 'io_object_mu_presets.shaders'
    bl_label = 'Install KSP Shader Presets'

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        install_presets("shaders")
        self.report({'INFO'}, 'Shader presets installed.')
        return {'FINISHED'}

class IOObjectMu_AddonPreferences(AddonPreferences):
    bl_idname = __name__

    GameData = StringProperty(
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

def menu_func_import(self, context):
    self.layout.operator(import_mu.ImportMu.bl_idname, text="KSP Mu (.mu)")
    self.layout.operator(import_craft.ImportCraft.bl_idname, text="KSP Craft (.craft)")

def menu_func_export(self, context):
    self.layout.operator(export_mu.ExportMu.bl_idname, text="KSP Mu (.mu)")

class TEXT_MT_templates_kspcfg(Menu):
    bl_label = "KSP config"

    def draw (self, context):
        self.path_menu(
            bpy.utils.script_paths("templates_kspcfg"),
            "text.open",
            props_default={"internal": True},
        )

def text_func_templates(self, context):
    self.layout.menu("TEXT_MT_templates_kspcfg");

def Preferences():
    user_preferences = bpy.context.user_preferences
    addons = user_preferences.addons
    return addons["io_object_mu"].preferences

def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func_import)
    bpy.types.INFO_MT_file_export.append(menu_func_export)
    bpy.types.INFO_MT_mesh_add.append(quickhull.menu_func)
    bpy.types.TEXT_MT_templates.append(text_func_templates)

    properties.register()
    collider.register()
    shader.register()

def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func_import)
    bpy.types.INFO_MT_file_export.remove(menu_func_export)
    properties.unregister()
    collider.unregister()

if __name__ == "__main__":
    register()
