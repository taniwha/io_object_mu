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
from bpy.props import BoolProperty
from mathutils import Vector
from math import atan, pi

from ..utils import strip_nnn, create_data_object
from ..cfgnode import ConfigNode

def vec(v):
    """
    Convert a vector to a string.

    Args:
        v: (array): write your description
    """
    return "[%5.2f %5.2f %5.2f %5.2f]" % tuple(v)

objects_to_add = (
    ('wing-tool.root.fore', Vector((0, 0, 1))),
    ('wing-tool.root.aft', Vector((0, 0, -1))),
    ('wing-tool.tip.fore', Vector((-1, 0, 1))),
    ('wing-tool.tip.aft', Vector((-1, 0, -1))),
)

def create_wingtool(collection):
    """
    Create a tooltooltool object.

    Args:
        collection: (str): write your description
    """
    wing_tool = create_data_object(collection, "wing-tool", None, None)
    for ota in objects_to_add:
        obj = create_data_object(collection, ota[0], None, None)
        obj.location = ota[1]
        obj.parent = wing_tool
    return wing_tool

def create_wingtool_op(self, context):
    """
    Create an optool context.

    Args:
        self: (todo): write your description
        context: (todo): write your description
    """
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    try:
        collection = bpy.context.layer_collection.collection
        wing_tool = create_wingtool(collection)
    except:
        raise
    else:
        for o in bpy.context.scene.objects:
            o.select_set(False)
        bpy.context.view_layer.objects.active = wing_tool
        wing_tool.location = bpy.context.scene.cursor.location
        wing_tool.select_set(True)
        for o in wing_tool.children:
            o.select_set(True)
        return {'FINISHED'}
    finally:
        bpy.context.preferences.edit.use_global_undo = undo

def measure_wing(wing_tool):
    """
    Return a measurement of the tool.

    Args:
        wing_tool: (todo): write your description
    """
    tools = {}
    for c in wing_tool.children:
        if c.name[:10] == "wing-tool.":
            tools[strip_nnn(c.name[10:])] = c

    root_x = (tools["root.fore"].location.x + tools["root.aft"].location.x) / 2
    root_z = (tools["root.fore"].location.z + tools["root.aft"].location.z) / 2
    tip_x = (tools["tip.fore"].location.x + tools["tip.aft"].location.x) / 2
    tip_z = (tools["tip.fore"].location.z + tools["tip.aft"].location.z) / 2
    root_chord = tools["root.fore"].location.z - tools["root.aft"].location.z
    tip_chord = tools["tip.fore"].location.z - tools["tip.aft"].location.z

    MAC = (abs(root_chord) + abs(tip_chord)) / 2
    b_2 = abs (tip_x - root_x)
    TaperRatio = abs(tip_chord) / (abs(root_chord) + 1e-8)
    MidChordSweep = atan((root_z - tip_z) / b_2) * 180 / pi
    cfg = ConfigNode()
    cfg.AddValue ("name", "FARWingAerodynamicModel")
    cfg.AddValue ("MAC", "%.4g" % MAC)
    cfg.AddValue ("MidChordSweep", "%.4g" % MidChordSweep)
    cfg.AddValue ("b_2", "%.4g" % b_2)
    cfg.AddValue ("TaperRatio", "%.4g" % TaperRatio)
    return cfg

def measure_wing_op(self, context):
    """
    Displays the state

    Args:
        self: (todo): write your description
        context: (todo): write your description
    """
    wing_tool = context.active_object
    if wing_tool.name[9] == ".":
        wing_tool = wing_tool.parent
    cfg = measure_wing(wing_tool)
    print(cfg.ToString())
    return {'FINISHED'}

class KSPMU_OT_AddWingTool(bpy.types.Operator):
    '''Create a rig for measuring wing properties for FAR.'''
    bl_idname = "object.mu_add_wing_tool"
    bl_label = "Wing Tool"
    bl_description = """Create a rig for measuring wing properties for FAR."""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """
        Poll the active poll mode.

        Args:
            cls: (todo): write your description
            context: (dict): write your description
        """
        return context.active_object and context.active_object.mode == 'OBJECT'

    def execute(self, context):
        """
        Creates a new keywords.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        keywords = self.as_keywords ()
        return create_wingtool_op(self, context, **keywords)

class KSPMU_OT_CalcWingProps(bpy.types.Operator):
    '''Measuring wing properties for FAR.'''
    bl_idname = "object.mu_calc_ping_props"
    bl_label = "Measure Wing Properties"
    bl_description = """Measure wing properties for FAR."""
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """
        Check if the status of the active.

        Args:
            cls: (todo): write your description
            context: (dict): write your description
        """
        if context.active_object and context.active_object.mode == 'OBJECT':
            if context.active_object.name[:9] == "wing-tool":
                return True
        return False

    def execute(self, context):
        """
        Execute a new context.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        keywords = self.as_keywords ()
        return measure_wing_op(self, context, **keywords)

def create_wingtool_menu_func(self, context):
    """
    Create the widget menu

    Args:
        self: (todo): write your description
        context: (todo): write your description
    """
    self.layout.operator(KSPMU_OT_AddWingTool.bl_idname, text = KSPMU_OT_AddWingTool.bl_label, icon='PLUGIN')

classes_to_register = (
    KSPMU_OT_AddWingTool,
    KSPMU_OT_CalcWingProps,
)

menus_to_register = (
    (bpy.types.VIEW3D_MT_add, create_wingtool_menu_func),
)
