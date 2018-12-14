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

import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Quaternion
from bpy.props import StringProperty, EnumProperty

from ..preferences import Preferences
from ..cfgnode import ConfigNode, ConfigNodeError
from ..utils import strip_nnn
from ..model import instantiate_model

def import_prop_op(self, context, filepath):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    prop = import_prop(filepath).get_model()
    context.layer_collection.collection.objects.link(prop)
    prop.location = context.scene.cursor_location
    prop.select_set(True)

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

def clean_selected(selected):
    def ancestor_selected(o, sel):
        if not o:
            return False
        return ancestor_selected(o.parent, sel)
    objects = list(selected)
    for o in objects:
        if ancestor_selected(o, selected):
            selected.remove(o)

def make_props(self, context):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    selected = set()
    for obj in bpy.context.scene.objects:
        if obj.select_get():
            selected.add(obj)
    clean_selected(selected)

    for obj in selected:
        make_prop(obj)

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_ImportProp(bpy.types.Operator, ImportHelper):
    '''Load a KSP Mu (.mu) File as a Prop'''
    bl_idname = "import_object.ksp_mu_prop"
    bl_label = "Import Mu Prop"
    bl_description = """Import a KSP .mu model as a prop."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".cfg"
    filter_glob: StringProperty(default="*.cfg", options={'HIDDEN'})

    def execute(self, context):
        keywords = self.as_keywords (ignore=("filter_glob",))
        return import_prop_op(self, context, **keywords)

class KSPMU_OT_MakeProps(bpy.types.Operator):
    bl_idname = "object.make_ksp_props"
    bl_label = "Make KSP Props"
    bl_description = """Make KSP props from selected objects."""
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return make_props(self, context)

class OBJECT_OT_add_ksp_prop(bpy.types.Operator):
    bl_idname = "object.add_ksp_prop"
    bl_label = "Add KSP Prop"
    bl_description = """Add a KSP internal space prop instance."""
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "prop_item"

    _enum_item_cache = []

    def prop_enum_items(self, context):
        enum_items = OBJECT_OT_add_ksp_prop._enum_item_cache
        enum_items.clear()
        for index, item in enumerate([p for p in loaded_props_collection().children
                                      if p.mumodelprops.type == 'prop']):
            enum_items.append((str(index), item.mumodelprops.name, '', index))
        return enum_items

    prop_item: EnumProperty(name="Prop", description="KSP internal prop",
                            items=prop_enum_items)

    def find_prop(self, context):
        prop_item = int(self.prop_item)
        for index, item in enumerate([p for p in bpy.data.collections
                                      if p.mumodelprops.type == 'prop']):
            if index == prop_item:
                return item
        return None

    def execute(self, context):
        prop = self.find_prop(context)
        self._enum_item_cache.clear()
        if prop:
            loc = context.scene.cursor_location
            muscene = context.scene.musceneprops
            if muscene.internal:
                loc = muscene.internal.matrix_world.inverted() * loc
            rot = Vector((0, 0, 0))
            scale = Vector((1, 1, 1))
            obj = instantiate_model(prop, prop.mumodelprops.name,
                                    loc, rot, scale)
            obj.muproperties.modelType = 'PROP'
            obj.parent = muscene.internal
            context.layer_collection.collection.objects.link(obj)
            return {'FINISHED'}
        else:
            return {'CANCELLED'}

    def invoke(self, context, event):
        self.store_mouse_cursor(context, event)
        context.window_manager.invoke_search_popup(self)
        return {'CANCELLED'}

classes_to_register = (
    KSPMU_OT_ImportProp,
    KSPMU_OT_MakeProps,
    OBJECT_OT_add_ksp_prop,
)
