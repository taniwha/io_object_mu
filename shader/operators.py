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
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty
from bl_operators.presets import AddPresetBase
from .shader_extract import record_material
from .shader import create_nodes

class KSPMU_OT_MuShaderPropExpand(bpy.types.Operator):
    '''Expand/collapse mu shader property set'''
    bl_idname = "object.mushaderprop_expand"
    bl_label = "Mu shader prop expand"
    propertyset: StringProperty()
    def execute(self, context):
        """
        Execute a dictionary of this query

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        propset.expanded = not propset.expanded
        return {'FINISHED'}


class KSPMU_OT_MuShaderPropAdd(bpy.types.Operator):
    '''Add a mu shader property'''
    bl_idname = "object.mushaderprop_add"
    bl_label = "Mu shader prop Add"
    propertyset: StringProperty()
    def execute(self, context):
        """
        Execute a property : param context : param. : param context

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        prop = propset.properties.add()
        prop.name = "New Property"
        for i, p in enumerate(propset.properties):
            if p == prop:
                propset.index = i
                break
        return {'FINISHED'}

class KSPMU_OT_MuShaderPropRemove(bpy.types.Operator):
    '''Remove a mu shader property'''
    bl_idname = "object.mushaderprop_remove"
    bl_label = "Mu shader prop Remove"
    propertyset: StringProperty()
    def execute(self, context):
        """
        Execute a dictionary of the context.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        if propset.index >= 0:
            propset.properties.remove(propset.index)
        return {'FINISHED'}

class IO_OBJECT_MU_OT_shader_presets(AddPresetBase, bpy.types.Operator):
    bl_idname = "io_object_mu.shader_presets"
    bl_label = "Shaders"
    bl_description = "Mu Shader Presets"
    preset_menu = "IO_OBJECT_MU_MT_shader_presets"
    preset_subdir = "io_object_mu/shaders"

    preset_defines = [
        "mat = bpy.context.material.mumatprop"
        ]
    preset_values = [
        "mat.name",
        "mat.shaderName",
        "mat.color",
        "mat.vector",
        "mat.float2",
        "mat.float3",
        "mat.texture",
        ]

def export_material(operator, context, filepath):
    """
    Export material as material

    Args:
        operator: (todo): write your description
        context: (todo): write your description
        filepath: (str): write your description
    """
    mat = context.material
    matnode = record_material(mat)
    of = open(filepath,"wt")
    of.write("shader " + matnode.ToString())
    return {'FINISHED'}

class IO_OBJECT_MU_OT_shader_rebuild(bpy.types.Operator):
    '''Rebuild the material node tree'''
    bl_idname = "io_object_mu.shader_rebuild"
    bl_label = "Rebuild Shader"

    @classmethod
    def poll(cls, context):
        """
        Return the context manager.

        Args:
            cls: (todo): write your description
            context: (dict): write your description
        """
        return hasattr(context, "material") and context.material != None

    def execute(self, context):
        """
        Execute nodes.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        create_nodes(context.material)
        return {'FINISHED'}

class IO_OBJECT_MU_OT_shader_export(bpy.types.Operator, ExportHelper):
    '''Save a material as a .cfg file'''
    bl_idname = "export_material.ksp_cfg"
    bl_label = "Export Material"

    filename_ext = ".cfg"
    filter_glob: StringProperty(default="*.cfg", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        """
        Return the context manager.

        Args:
            cls: (todo): write your description
            context: (dict): write your description
        """
        return hasattr(context, "material") and context.material != None

    def execute(self, context):
        """
        Execute a select context.

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob",
                                             "axis_forward", "axis_up"))
        return export_material(self, context, **keywords)

classes_to_register = (
    KSPMU_OT_MuShaderPropExpand,
    KSPMU_OT_MuShaderPropAdd,
    KSPMU_OT_MuShaderPropRemove,
    IO_OBJECT_MU_OT_shader_presets,
    IO_OBJECT_MU_OT_shader_rebuild,
    IO_OBJECT_MU_OT_shader_export,
)
