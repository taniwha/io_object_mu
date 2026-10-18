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
from bpy.props import EnumProperty
from mathutils import Quaternion


_ATTACH_NODE_TYPES = (
    ('node_stack_top', "Stack Top", "Create Empty named node_stack_top"),
    ('node_stack_bottom', "Stack Bottom", "Create Empty named node_stack_bottom"),
    ('node_stack_left', "Stack Left", "Create Empty named node_stack_left"),
    ('node_stack_right', "Stack Right", "Create Empty named node_stack_right"),
    ('node_stack_front', "Stack Front", "Create Empty named node_stack_front"),
    ('node_stack_back', "Stack Back", "Create Empty named node_stack_back"),
    ('node_attach', "Surface Attach", "Create Empty named node_attach"),
)


class KSPMU_OT_AddAttachNode(bpy.types.Operator):
    '''Create a KSP attach-node Empty parented to the active object'''
    bl_idname = "object.mu_add_attach_node"
    bl_label = "Add Attach Node"
    bl_options = {'REGISTER', 'UNDO'}

    node_type: EnumProperty(
        name="Type",
        items=_ATTACH_NODE_TYPES,
        default='node_stack_top',
    )

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        parent = context.active_object
        if parent is None:
            self.report({'WARNING'}, "No active object")
            return {'CANCELLED'}

        empty = bpy.data.objects.new(self.node_type, None)
        empty.empty_display_type = 'SINGLE_ARROW'
        empty.empty_display_size = 0.5
        empty.rotation_mode = 'QUATERNION'
        # Match import_mu orientation: Blender SINGLE_ARROW is +Z, KSP node
        # points along Unity +Z (= Blender +Y).
        empty.rotation_quaternion = Quaternion(
            (0.5 ** 0.5, -(0.5 ** 0.5), 0, 0)
        )

        col = context.collection
        if col is None:
            col = context.scene.collection
        col.objects.link(empty)
        empty.parent = parent
        empty.location = (0.0, 0.0, 0.0)

        for obj in context.selected_objects:
            obj.select_set(False)
        empty.select_set(True)
        context.view_layer.objects.active = empty
        self.report({'INFO'}, f"Created {empty.name}")
        return {'FINISHED'}


class WORKSPACE_PT_tools_mu_tools2(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_context = ".objectmode"
    bl_label = "Mu Hierarchy"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        #col = layout.column(align=True)
        layout.operator("object.mu_apply_scale", text = "Apply Scale");
        layout.operator("object.mu_clearinverse", text = "Clear Inverse");
        layout.operator("object.mu_calc_ping_props", text = "Measure Wing");
        layout.operator_menu_enum(
            "object.mu_add_attach_node", "node_type", text="Add Attach Node"
        )


classes_to_register = (
    KSPMU_OT_AddAttachNode,
    WORKSPACE_PT_tools_mu_tools2,
)
