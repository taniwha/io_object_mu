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
from mathutils import Vector
from bpy.types import PropertyGroup
from bpy.utils import register_class, unregister_class
from bpy.props import BoolProperty, BoolVectorProperty
from bpy.props import CollectionProperty
from bpy.props import EnumProperty
from bpy.props import FloatProperty, FloatVectorProperty
from bpy.props import IntProperty, IntVectorProperty
from bpy.props import PointerProperty
from bpy.props import StringProperty

from .module import ksp_module_items, build_modules, available_modules_map
from .properties import module_active_field

class KSPMU_OT_ModuleExpand(bpy.types.Operator):
    bl_label = "KSP module expand"
    bl_idname = "object.kspmodule_expand"
    index: IntProperty()
    def execute(self, context):
        """
        Execute the command.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        module = context.active_object.kspmodules.modules[self.index]
        module.expanded = not module.expanded
        return {'FINISHED'}

class KSPMU_OT_ScanModuleDefs(bpy.types.Operator):
    '''Rescan loaded module definitions: *.mod in blender text blocks'''
    bl_idname = "scene.scan_module_defs"
    bl_label = "RELOAD"

    def execute(self, context):
        """
        Execute a dictionary of the modules.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        build_modules()
        return {'FINISHED'}

class KSPMU_OT_AddModule(bpy.types.Operator):
    """Add a KSP module to the part. Note that where the module is placed
    in the hierarchy is irrelevant: modules will be collected from all objects
    in the exported model and written to the config in the same order in which
    they were found. No checking is done for duplicates: they will be
    written to the config file as-is."""
    bl_idname = "object.add_ksp_module"
    bl_label = "Add KSP Module"
    type: EnumProperty(name="Module Type", items=ksp_module_items)

    def execute(self, context):
        """
        Execute the given context.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        kspmodules = context.active_object.kspmodules
        module = available_modules_map[self.type]
        kspmodules.modules.add().initialize(module)
        return {'FINISHED'}

class KSPMU_OT_RemoveModule(bpy.types.Operator):
    """Remove the KSP module from the part."""
    bl_label = "Remove KSP Module"
    bl_idname = "object.remove_ksp_module"
    index: IntProperty()
    def execute(self, context):
        """
        Execute the command.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        kspmodules = context.active_object.kspmodules
        if len(kspmodules.modules) > self.index >= 0:
            kspmodules.modules.remove(self.index)
            module_active_field.clear()
        return {'FINISHED'}

classes_to_register = (
    KSPMU_OT_ModuleExpand,
    KSPMU_OT_ScanModuleDefs,
    KSPMU_OT_AddModule,
    KSPMU_OT_RemoveModule,
)
