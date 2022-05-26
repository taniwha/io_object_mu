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
from bpy.props import StringProperty, EnumProperty

from ..utils import strip_nnn, collect_hierarchy_objects

from . import export
from . import volume

def export_mu(operator, context, filepath):
    collections = export.enable_collections()
    try:
        mu = export.export_object (context.active_object, filepath)
    finally:
        export.restore_collections(collections)
    for m in mu.messages:
        operator.report(m[0], m[1])
    return {'FINISHED'}

exportable_objects = {
    type(None),
    bpy.types.Mesh,
    bpy.types.Armature,
}

class KSPMU_OT_ExportMu(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File'''
    bl_idname = "export_object.ksp_mu"
    bl_label = "Export Mu"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob",
                                             "axis_forward", "axis_up"))
        return export_mu(self, context, **keywords)

class KSPMU_OT_ExportMu_quick(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File, defaulting name to selected object'''
    bl_idname = "export_object.ksp_mu_quick"
    bl_label = "Export Mu (quick)"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob",
                                             "axis_forward", "axis_up"))
        return export_mu(self, context, **keywords)

    def invoke(self, context, event):
        obj = context.active_object
        if obj != None:
            self.filepath = strip_nnn(obj.name) + self.filename_ext
        return ExportHelper.invoke(self, context, event)

volume_selection_enum = (
    ('ACTIVE', "Active", "Calculate volume of only the active object"),
    ('SELECTED', "Selected", "Calculate the volume of all selected objects"),
    ('HIERARCHY', "Hierarchy", "Calculate the volume of selected objects and their descendents"),
)

class KSPMU_OT_MuVolume(bpy.types.Operator):
    '''Calculate the volume of selected objects'''
    bl_idname = 'object.mu_volume'
    bl_label = 'Mu Volume'

    bl_options = {'PRESET'}

    selection: EnumProperty(name = "Selection",
                            description = "Which objects to measure",
                            items = volume_selection_enum)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        obj = context.active_object
        if self.selection == 'ACTIVE':
            if obj.data and type(obj.data) == bpy.types.Mesh:
                vol = volume.obj_volume(obj)
            else:
                vol = volume.model_volume(obj)
        elif self.selection == 'HIERARCHY':
            vol = (0, 0)
            for obj in bpy.context.selected_objects:
                v = volume.model_volume(obj)
                vol = vol[0] + v[0], vol[1] + v[1]
        else:
            vol = (0, 0)
            for obj in bpy.context.selected_objects:
                if obj.data and type(obj.data) == bpy.types.Mesh:
                    v = volume.obj_volume(obj)
                    vol = vol[0] + v[0], vol[1] + v[1]
        self.report({'INFO'}, 'Skin Volume = %g m^3, Ext Volume = %g m^3' % vol)
        return {'FINISHED'}

class KSPMU_OT_MuFindCoM(bpy.types.Operator):
    bl_idname = 'object.mu_snap_cursor_to_com'
    bl_label = 'Mu Center of Mass'

    @classmethod
    def poll(cls, context):
        #print(context.selected_objects)
        if len(context.selected_objects) == 1 and context.active_object:
            return True
        if context.selected_objects:
            return True
        return False

    def execute(self, context):
        obj = context.active_object
        if len(context.selected_objects) == 1 and context.active_object:
            objects = collect_hierarchy_objects(context.active_object)
            #print(objects)
        elif context.selected_objects:
            objects = context.selected_objects[:]
        pos = volume.find_com(objects)
        bpy.context.scene.cursor.location = pos
        return {'FINISHED'}
