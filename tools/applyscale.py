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
from ..utils.action_compat import iter_action_fcurves

def vec(v):
    return "[%5.2f %5.2f %5.2f %5.2f]" % tuple(v)

def _iter_actions(obj):
    ad = obj.animation_data
    if not ad:
        return
    if ad.action:
        yield ad.action
    for track in ad.nla_tracks:
        for strip in track.strips:
            if strip.action:
                yield strip.action


def _scale_object_fcurves(obj, sx, sy, sz):
    """Scale location (and non-uniform-aware scale channels) on object actions."""
    for action in _iter_actions(obj):
        for fc in iter_action_fcurves(action):
            if fc.data_path == "location":
                mult = (sx, sy, sz)[fc.array_index] if fc.array_index < 3 else 1.0
                for kp in fc.keyframe_points:
                    kp.co[1] *= mult
                    kp.handle_left[1] *= mult
                    kp.handle_right[1] *= mult
            elif fc.data_path == "scale":
                mult = (sx, sy, sz)[fc.array_index] if fc.array_index < 3 else 1.0
                for kp in fc.keyframe_points:
                    # baked object scale becomes 1; keys store relative scale
                    kp.co[1] *= mult
                    kp.handle_left[1] *= mult
                    kp.handle_right[1] *= mult
            elif "pose.bones[" in fc.data_path and fc.data_path.endswith("location"):
                mult = (sx, sy, sz)[fc.array_index] if fc.array_index < 3 else 1.0
                for kp in fc.keyframe_points:
                    kp.co[1] *= mult
                    kp.handle_left[1] *= mult
                    kp.handle_right[1] *= mult


def apply_scale(obj):
    s = obj.matrix_basis.to_scale()
    scale = Matrix(((s.x,  0,  0, 0),
                    (  0,s.y,  0, 0),
                    (  0,  0,s.z, 0),
                    (  0,  0,  0, 1)))
    muprops = obj.muproperties
    if type(obj.data) is bpy.types.Mesh:
        mesh = obj.data
        for v in mesh.vertices:
            v.co = scale @ v.co
    elif type(obj.data) is bpy.types.Armature:
        # Bake object scale into edit bones so armature export stays consistent
        arm = obj.data
        prev = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = obj
        mode = obj.mode
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        for eb in arm.edit_bones:
            eb.head = scale @ eb.head
            eb.tail = scale @ eb.tail
        bpy.ops.object.mode_set(mode=mode if mode != 'EDIT' else 'OBJECT')
        if prev:
            bpy.context.view_layer.objects.active = prev
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
            muprops.suspensionSpring.spring *= avg_scale
            muprops.suspensionSpring.damper *= avg_scale
        muprops.center = scale @ muprops.center
        update_collider(obj)
    _scale_object_fcurves(obj, s.x, s.y, s.z)
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
