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


def clearinverse(obj, recursive):
    # matrix_local = matrix_parent_inverse @ matrix_basis
    # matrix_local is the actual local transform,
    # matrix_basis is the transform visible in blender's UI
    # matrix_parent_inverse is what allows the UI matrix to look like world
    # coordinates when the object is parented to an object that has been
    # transformed prior to parenting but not after.
    # this effectively makes the UI reflect the actual local transform
    # FIXME need to apply to animations, too
    # FIXME be a little smarter about objects parented to bones: the tail
    # offset portion of the parent inverse is required for things to work
    # the way unity (and thus KSP) expects
    obj.matrix_basis = obj.matrix_local
    obj.matrix_parent_inverse.identity()
    if recursive:
        for child in obj.children:
            clearinverse(child, recursive)

def clearinverse_op(self, context, recursive):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        clearinverse(obj, recursive)

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_ClearInverse(bpy.types.Operator):
    '''Clear parent inverse matrix keeping world transform.'''
    bl_idname = "mesh.clearinverse"
    bl_label = "Clear Parent Inverse (keep world transform)"
    bl_description = """Clear parent inverse matrix keeping world transform."""
    bl_options = {'REGISTER', 'UNDO'}

    recursive: BoolProperty(name="Recursive",
                            description="Recurse object hierarchy.",
                            default=True)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.mode == 'OBJECT'

    def execute(self, context):
        keywords = self.as_keywords ()
        return clearinverse_op(self, context, **keywords)

def clear_inverse_menu_func(self, context):
    self.layout.operator(KSPMU_OT_ClearInverse.bl_idname, text = KSPMU_OT_ClearInverse.bl_label, icon='PLUGIN')

classes_to_register = (
    KSPMU_OT_ClearInverse,
)

#menus_to_register = (
#    (bpy.types.VIEW3D_MT_mesh_add, clear_inverse_menu_func),
#)
