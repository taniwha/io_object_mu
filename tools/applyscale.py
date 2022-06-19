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
from mathutils import Matrix
from math import sqrt

from ..collider import update_collider

def vec(v):
    return "[%5.2f %5.2f %5.2f %5.2f]" % tuple(v)

def apply_scale(obj):
    s = obj.matrix_basis.to_scale()
    scale = Matrix(((s.x,  0,  0, 0),
                    (  0,s.y,  0, 0),
                    (  0,  0,s.z, 0),
                    (  0,  0,  0, 1)))
    muprops = obj.muproperties
    #FIXME apply to animation data and armatures
    if type(obj.data) is bpy.types.Mesh:
        mesh = obj.data
        for v in mesh.vertices:
            v.co = scale @ v.co
    elif muprops.collider != 'MU_COL_NONE':
        #NOTE mesh colliders handled above
        ct = muprops.collider
        avg_scale = scale.median_scale
        if ct == 'MU_COL_SPHERE':
            muprops.radius *= avg_scale
        elif ct == 'MU_COL_CAPSULE':
            if muprops.direction == 'MU_X':
                muprops.height *= s.x
                muprops.radius *= sqrt(abs(s.y * s.z))
            elif muprops.direction == 'MU_Y':
                muprops.height *= s.y
                muprops.radius *= sqrt(abs(s.z * s.x))
            elif muprops.direction == 'MU_Z':
                muprops.height *= s.z
                muprops.radius *= sqrt(abs(s.x * s.y))
        elif ct == 'MU_COL_BOX':
            muprops.size = scale @ muprops.size
        elif ct == 'MU_COL_WHEEL':
            muprops.mass *= abs(s.x * s.y * s.z)
            muprops.radius *= sqrt(abs(s.y * s.z))
            # not sure any of these are correct, but nobody uses wheel
            # colliders anymore anyway.
            muprops.suspensionDistance *= abs(s.z)
            muprops.suspensionSpring.sprint *= avg_scale
            muprops.suspensionSpring.damper *= avg_scale
        muprops.center = scale @ muprops.center
        update_collider(obj)
    for child in obj.children:
        child.matrix_basis = scale @ child.matrix_basis
        apply_scale(child)
    obj.scale = (1, 1, 1)

def apply_scale_op(self, context):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        apply_scale(obj)

    bpy.context.preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_ClearInverse(bpy.types.Operator):
    '''Apply scale recursively without affecting parent inverse matrix.'''
    bl_idname = "object.mu_apply_scale"
    bl_label = "Apply Scale recursively"
    bl_description = """Apply scale recursively without affecting parent inverse matrix."""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.mode == 'OBJECT'

    def execute(self, context):
        keywords = self.as_keywords ()
        return apply_scale_op(self, context, **keywords)

def apply_scale_menu_func(self, context):
    self.layout.operator(KSPMU_OT_ClearInverse.bl_idname, text = KSPMU_OT_ClearInverse.bl_label, icon='PLUGIN')

classes_to_register = (
    KSPMU_OT_ClearInverse,
)

#menus_to_register = (
#    (bpy.types.VIEW3D_MT_mesh_add, apply_scale_menu_func),
#)
