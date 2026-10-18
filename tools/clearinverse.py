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
from mathutils import Matrix, Vector, Quaternion

from ..utils.action_compat import iter_action_fcurves


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


def _transform_object_fcurves(obj, delta):
    """Apply a delta matrix to location/rotation/scale fcurves on obj."""
    if delta == Matrix.Identity(4):
        return
    loc, rot, scale = delta.decompose()
    for action in _iter_actions(obj):
        # location
        locs = [None, None, None]
        for fc in iter_action_fcurves(action):
            if fc.data_path == "location" and 0 <= fc.array_index < 3:
                locs[fc.array_index] = fc
        if all(locs):
            n = len(locs[0].keyframe_points)
            if all(len(fc.keyframe_points) == n for fc in locs):
                for i in range(n):
                    for attr in ("co", "handle_left", "handle_right"):
                        p0 = getattr(locs[0].keyframe_points[i], attr)
                        p1 = getattr(locs[1].keyframe_points[i], attr)
                        p2 = getattr(locs[2].keyframe_points[i], attr)
                        v = delta @ Vector((p0[1], p1[1], p2[1], 1.0))
                        p0[1], p1[1], p2[1] = v.x, v.y, v.z
        # rotation_quaternion
        rots = [None, None, None, None]
        for fc in iter_action_fcurves(action):
            if fc.data_path == "rotation_quaternion" and 0 <= fc.array_index < 4:
                rots[fc.array_index] = fc
        if all(rots):
            n = len(rots[0].keyframe_points)
            if all(len(fc.keyframe_points) == n for fc in rots):
                for i in range(n):
                    for attr in ("co", "handle_left", "handle_right"):
                        pw = getattr(rots[0].keyframe_points[i], attr)
                        px = getattr(rots[1].keyframe_points[i], attr)
                        py = getattr(rots[2].keyframe_points[i], attr)
                        pz = getattr(rots[3].keyframe_points[i], attr)
                        q = rot @ Quaternion((pw[1], px[1], py[1], pz[1]))
                        pw[1], px[1], py[1], pz[1] = q.w, q.x, q.y, q.z


def clearinverse(obj, recursive):
    # matrix_local = matrix_parent_inverse @ matrix_basis
    # matrix_local is the actual local transform,
    # matrix_basis is the transform visible in blender's UI
    # matrix_parent_inverse is what allows the UI matrix to look like world
    # coordinates when the object is parented to an object that has been
    # transformed prior to parenting but not after.
    # this effectively makes the UI reflect the actual local transform
    old_basis = obj.matrix_basis.copy()
    new_basis = obj.matrix_local.copy()
    if obj.parent and obj.parent_type == 'BONE':
        armature = obj.parent.data
        bone = armature.bones[obj.parent_bone]
        length = (bone.tail - bone.head).magnitude
        new_basis = new_basis.copy()
        new_basis[1][3] += length
    # Delta that maps old basis coordinates into the cleared-inverse basis
    try:
        delta = new_basis @ old_basis.inverted()
    except ValueError:
        delta = Matrix.Identity(4)
    obj.matrix_basis = new_basis
    obj.matrix_parent_inverse.identity()
    if obj.parent and obj.parent_type == 'BONE':
        armature = obj.parent.data
        bone = armature.bones[obj.parent_bone]
        length = (bone.tail - bone.head).magnitude
        obj.matrix_parent_inverse[1][3] = -length
    _transform_object_fcurves(obj, delta)
    if recursive:
        for child in obj.children:
            clearinverse(child, recursive)

def clearinverse_op(self, context, recursive):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        clearinverse(obj, recursive)

    bpy.context.preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_ClearInverse(bpy.types.Operator):
    '''Clear parent inverse matrix keeping world transform.'''
    bl_idname = "object.mu_clearinverse"
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
