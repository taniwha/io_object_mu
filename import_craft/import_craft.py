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
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

from ..import_mu import MuImportError
from ..cfgnode import ConfigNode, ConfigNodeError
from ..cfgnode import parse_vector, parse_quaternion
from ..preferences import Preferences
from ..utils import util_collection

from .gamedata import GameData, gamedata

def craft_collection():
    return util_collection("craft_collection")

def select_objects(obj):
    obj.select_set(True)
    for o in obj.children:
        select_objects(o)

def import_craft(filepath):
    global gamedata
    if not gamedata:
        gamedata = GameData(Preferences().GameData)
    try:
        craft = ConfigNode.loadfile(filepath)
    except ConfigNodeError as e:
        raise MuImportError("Craft", e.message)
    scene = bpy.context.scene
    craft_name = craft.GetValue("ship")
    if craft_name[:9] == "#autoLOC_" and craft_name in gamedata.localizations:
        craft_name = gamedata.localizations[craft_name].strip()
    vessel = bpy.data.collections.new(craft_name)
    craft_collection().children.link(vessel)
    root_pos = None
    for p in craft.GetNodes("PART"):
        pname = p.GetValue("part").split("_")[0]
        pos = parse_vector(p.GetValue("pos"))
        rot = parse_quaternion(p.GetValue("rot"))
        part = gamedata.parts[pname].get_model()
        if root_pos == None:
            root_pos = pos
        part.location = pos - root_pos
        part.rotation_mode = 'QUATERNION'
        part.rotation_quaternion = rot
        vessel.objects.link(part)
    obj = bpy.data.objects.new(craft_name, None)
    obj.instance_type = 'COLLECTION'
    obj.instance_collection = vessel
    obj.location = bpy.context.scene.cursor_location
    bpy.context.layer_collection.collection.objects.link(obj)
    return obj

def import_craft_op(self, context, filepath):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    try:
        obj = import_craft(filepath)
    except MuImportError as e:
        operator.report({'ERROR'}, e.message)
        return {'CANCELLED'}
    else:
        for o in bpy.context.scene.objects:
            o.select_set(False)
        select_objects(obj)
        bpy.context.view_layer.objects.active = obj
        return {'FINISHED'}
    finally:
        bpy.context.user_preferences.edit.use_global_undo = undo

class KSPMU_OT_ImportCraft(bpy.types.Operator, ImportHelper):
    '''Load a KSP craft file'''
    bl_idname = "import_object.ksp_craft"
    bl_label = "Import Craft"
    bl_description = """Import a KSP .craft (ship) file."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".craft"
    filter_glob: StringProperty(default="*.craft", options={'HIDDEN'})

    def execute(self, context):
        keywords = self.as_keywords (ignore=("filter_glob",
                                             "axis_forward", "axis_up"))
        return import_craft_op(self, context, **keywords)

def import_craft_menu_func(self, context):
    self.layout.operator(KSPMU_OT_ImportCraft.bl_idname, text="KSP Craft (.craft)")

classes_to_register = (
    KSPMU_OT_ImportCraft,
)

menus_to_register = (
    (bpy.types.TOPBAR_MT_file_import, import_craft_menu_func),
)
