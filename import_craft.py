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
from mathutils import Vector,Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

from .cfgnode import ConfigNode, ConfigNodeError
from .gamedata import GameData
from .parser import parse_vector, parse_quaternion

gamedata = None

def select_objects(obj):
    obj.select = True
    for o in obj.children:
        select_objects(o)

def import_craft(filepath):
    global gamedata
    if not gamedata:
        from .__init__ import Preferences
        gamedata = GameData(Preferences().GameData)
    try:
        craft = ConfigNode.loadfile(filepath)
    except ConfigNodeError as e:
        print(filepath+e.message)
        return
    scene = bpy.context.scene
    vessel = bpy.data.objects.new(craft.GetValue("ship"), None)
    vessel.location = Vector((0, 0, 0))
    vessel.rotation_mode = 'QUATERNION'
    vessel.rotation_quaternion = Quaternion((1,0,0,0))
    vessel.scale = Vector((1, 1, 1))
    scene.objects.link(vessel)
    for p in craft.GetNodes("PART"):
        pname = p.GetValue("part").split("_")[0]
        pos = parse_vector(p.GetValue("pos"))
        rot = parse_quaternion(p.GetValue("rot"))
        part = gamedata.parts[pname].get_model()
        scene.objects.link(part)
        part.location = pos
        part.rotation_mode = 'QUATERNION'
        part.rotation_quaternion = rot
        part.parent = vessel
    return vessel

def import_craft_op(self, context, filepath):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    obj = import_craft(filepath)
    select_objects(obj)
    bpy.context.scene.objects.active = obj

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class ImportCraft(bpy.types.Operator, ImportHelper):
    '''Load a KSP craft file'''
    bl_idname = "import_object.ksp_craft"
    bl_label = "Import Craft"
    bl_description = """Import a KSP .craft (ship) file."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".craft"
    filter_glob = StringProperty(default="*.craft", options={'HIDDEN'})

    def execute(self, context):
        keywords = self.as_keywords(ignore=("filter_glob",))
        return import_craft_op(self, context, **keywords)
