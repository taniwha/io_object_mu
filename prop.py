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

import os

import bpy, bmesh
from bpy_extras.io_utils import ImportHelper
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion
from pprint import pprint
from math import pi
from bpy_extras.io_utils import ExportHelper
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import FloatVectorProperty, PointerProperty

from .__init__ import Preferences
from .cfgnode import ConfigNode, ConfigNodeError
from .import_mu import import_mu
from .export_mu import strip_nnn

def collect_objects(parent):
    objects = [parent]
    for obj in parent.children:
        objects.append(collect_objects(obj))
    return objects

def process_prop(prop):
    prop.location = Vector((0, 0, 0))
    prop.rotation_quaternion = Quaternion((1,0,0,0))
    prop.scale = Vector((1,1,1))
    prop_objects = collect_objects(prop)

def import_mu_prop(self, context, filepath):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    print(Preferences().GameData)
    prop = import_mu(filepath, False)
    if not prop:
        bpy.context.user_preferences.edit.use_global_undo = undo
        operator.report({'ERROR'}, "Could not load prop")
        return {'CANCELLED'}
    process_prop(prop)

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class ImportProp(bpy.types.Operator, ImportHelper):
    '''Load a KSP Mu (.mu) File as a Prop'''
    bl_idname = "import_object.ksp_mu_prop"
    bl_label = "Import Mu Prop"
    bl_description = """Import a KSP .mu model as a prop."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".cfg"
    filter_glob = StringProperty(default="*.cfg", options={'HIDDEN'})

    def execute(self, context):
        keywords = self.as_keywords (ignore=("filter_glob",))
        return import_mu_prop(self, context, **keywords)

class VIEW3D_PT_tools_mu_props(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Mu Tools"
    bl_context = "objectmode"
    bl_label = "Prop Tools"

    def draw(self, context):
        layout = self.layout
        #col = layout.column(align=True)
        layout.operator(ImportProp.bl_idname, text = ImportProp.bl_description);
        #layout.operator("object.mu_volume", text = "Calc Mu Volume");
