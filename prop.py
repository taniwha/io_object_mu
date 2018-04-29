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
from .utils import strip_nnn
from .model import group_objects, instantiate_model, compile_model

def loaded_props_scene():
    if "loaded_props" not in bpy.data.scenes:
        return bpy.data.scenes.new("loaded_props")
    return bpy.data.scenes["loaded_props"]

class Prop:
    @classmethod
    def Preloaded(cls):
        preloaded = {}
        for g in bpy.data.groups:
            if g.name[:5] == "prop:":
                url = g.name[5:]
                prop = Prop("", ConfigNode.load(g.mumodelprops.config))
                prop.model = g
                preloaded[url] = prop
        return preloaded
    def __init__(self, path, cfg):
        self.cfg = cfg
        self.path = os.path.dirname(path)
        self.name = cfg.GetValue("name")
        self.model = None
    def get_model(self):
        if not self.model:
            self.model = compile_model(self.db, self.path, "prop", self.name,
                                       self.cfg, loaded_props_scene())
            props = self.model.mumodelprops
            props.config = self.cfg.ToString(-1)
        model = self.instantiate(Vector((0, 0, 0)),
                                 Quaternion((1,0,0,0)),
                                 Vector((1, 1, 1)))
        return model

    def instantiate(self, loc, rot, scale):
        obj = bpy.data.objects.new(self.name, None)
        obj.dupli_type='GROUP'
        obj.dupli_group=self.model
        obj.location = loc
        return obj

gamedata = None
def import_prop(filepath):
    global gamedata
    if not gamedata:
        from .__init__ import Preferences
        from .gamedata import GameData
        gamedata = GameData(Preferences().GameData)
    try:
        propcfg = ConfigNode.loadfile(filepath)
    except ConfigNodeError as e:
        print(filepath+e.message)
        return
    if filepath[:len(gamedata.root)] == gamedata.root:
        #the prop is in GameData
        propnode = propcfg.GetNode("PROP")
        name = propnode.GetValue("name")
        return gamedata.props[name]
    # load it directly
    return Prop(path, propcfg)

def import_prop_op(self, context, filepath):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False
    prop = import_prop(filepath).get_model()
    prop.location = context.scene.cursor_location
    prop.select = True
    context.scene.objects.link(prop)

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

def make_prop(obj):
    name = strip_nnn(obj.name)
    group = group_objects("prop:"+name, obj)
    obj.muproperties.modelType = 'PROP'
    #FIXME group instancing seems to work with the object's world location
    #rather than its local location
    group.dupli_offset = obj.location #FIXME update if the prop is later moved
    #necessary because groups don't support rotation or scale offsets
    obj.rotation_quaternion = Quaternion((1, 0, 0, 0))
    obj.scale = Vector((1, 1, 1))
    group.mumodelprops.name = name
    group.mumodelprops.type = "prop"

def make_props(self, context):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    selected = set()
    for obj in bpy.context.scene.objects:
        if obj.select:
            selected.add(obj)
    clean_selected(selected)

    for obj in selected:
        make_prop(obj)

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
        return import_prop_op(self, context, **keywords)

class MakeProps(bpy.types.Operator):
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
        for index, item in enumerate([p for p in bpy.data.groups
                                      if p.mumodelprops.type == 'prop']):
            enum_items.append((str(index), item.mumodelprops.name, '', index))
        return enum_items

    prop_item = EnumProperty(name="Prop", description="KSP internal prop",
                             items=prop_enum_items)

    def find_prop(self, context):
        prop_item = int(self.prop_item)
        for index, item in enumerate([p for p in bpy.data.groups
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
            context.scene.objects.link(obj)
            return {'FINISHED'}
        else:
            return {'CANCELLED'}

    def invoke(self, context, event):
        self.store_mouse_cursor(context, event)
        context.window_manager.invoke_search_popup(self)
        return {'CANCELLED'}

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
        layout.operator(MakeProps.bl_idname, text = MakeProps.bl_description);

def add_prop_menu_func(self, context):
    layout = self.layout
    if len(OBJECT_OT_add_ksp_prop._enum_item_cache) > 10:
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.operator(OBJECT_OT_add_ksp_prop.bl_idname, text="KSP Prop...",
                        icon='OUTLINER_OB_GROUP_INSTANCE')
    else:
        layout.operator_menu_enum(OBJECT_OT_add_ksp_prop.bl_idname,
                                  "prop_item", text="KSP Prop",
                                  icon='OUTLINER_OB_GROUP_INSTANCE')

def register():
    bpy.types.INFO_MT_add.append(add_prop_menu_func)

def unregister():
    pass
