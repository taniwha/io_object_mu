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

from ..utils import strip_nnn

from .export import export_object
from .volume import model_volume

def export_mu(operator, context, filepath):
    export_object (context.active_object, filepath)
    return {'FINISHED'}

class KSPMU_OT_ExportMu(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File'''
    bl_idname = "export_object.ksp_mu"
    bl_label = "Export Mu"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (context.active_object != None
                and (not context.active_object.data
                     or type(context.active_object.data) == bpy.types.Mesh))

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob"))
        return export_mu(self, context, **keywords)

class KSPMU_OT_ExportMu_quick(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File, defaulting name to selected object'''
    bl_idname = "export_object.ksp_mu_quick"
    bl_label = "Export Mu (quick)"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (context.active_object != None
                and (not context.active_object.data
                     or type(context.active_object.data) == bpy.types.Mesh))

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob"))
        return export_mu(self, context, **keywords)

    def invoke(self, context, event):
        if context.active_object != None:
            self.filepath = strip_nnn(context.active_object.name) + self.filename_ext
        return ExportHelper.invoke(self, context, event)

class KSPMU_OT_MuVolume(bpy.types.Operator):
    bl_idname = 'object.mu_volume'
    bl_label = 'Mu Volume'

    @classmethod
    def poll(cls, context):
        return (context.active_object != None
                and (not context.active_object.data
                     or type(context.active_object.data) == bpy.types.Mesh))

    def execute(self, context):
        obj = context.active_object
        if obj.data and type(obj.data) == bpy.types.Mesh:
            vol = obj_volume(obj)
        else:
            vol = model_volume(obj)
        self.report({'INFO'}, 'Skin Volume = %g m^3, Ext Volume = %g m^3' % vol)
        return {'FINISHED'}
