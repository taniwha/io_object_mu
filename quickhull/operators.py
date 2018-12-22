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
from .convex_hull import quickhull

def quickhull_op(self, context):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        obj.select_set(False)
        mesh = obj.to_mesh(context.depsgraph, True)
        if not mesh or not mesh.vertices:
            continue
        mesh = quickhull(mesh)
        hullobj = bpy.data.objects.new("ConvexHull", mesh)
        bpy.context.scene.collection.objects.link(hullobj)
        hullobj.select_set(True)
        hullobj.location = obj.location
        bpy.context.view_layer.objects.active = hullobj

    bpy.context.preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_QuickHull(bpy.types.Operator):
    '''Create a convex hull from an object.'''
    bl_idname = "mesh.quickhull"
    bl_label = "Convex Hull"
    bl_description = """Create a convex hull from an object."""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.mode == 'OBJECT'

    def execute(self, context):
        keywords = self.as_keywords ()
        return quickhull_op(self, context, **keywords)

def convex_hull_menu_func(self, context):
    self.layout.operator(KSPMU_OT_QuickHull.bl_idname, text = KSPMU_OT_QuickHull.bl_label, icon='PLUGIN')

classes_to_register = (
    KSPMU_OT_QuickHull,
)

menus_to_register = (
    (bpy.types.VIEW3D_MT_mesh_add, convex_hull_menu_func),
)
