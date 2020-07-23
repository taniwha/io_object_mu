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

class WORKSPACE_PT_tools_mu_collider(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    #bl_context = ".objectmode"
    bl_label = "Add Mu Collider"

    def draw(self, context):
        layout = self.layout
        if context.mode in ['EDIT_MESH', 'OBJECT']:
            col = layout.column(align=True)
            col.label(text="Single Collider:")
            layout.operator("mucollider.mesh", text = "Mesh")
            layout.operator("mucollider.sphere", text = "Sphere")
            layout.operator("mucollider.capsule", text = "Capsule")
            layout.operator("mucollider.box", text = "Box")

        if context.mode in ['OBJECT']:
            col = layout.column(align=True)
            col.label(text="Multiple Colliders:")
            layout.operator("mucollider.from_mesh")
            layout.operator("mucollider.mesh_to_collider")

class OBJECT_PT_MuColliderPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_label = 'Mu Collider'

    @classmethod
    def poll(cls, context):
        muprops = context.active_object.muproperties
        return muprops.collider and muprops.collider != 'MU_COL_NONE'

    def draw(self, context):
        layout = self.layout
        muprops = context.active_object.muproperties
        row = layout.row()
        col = row.column()
        # can't change object types :/ (?)
        #col.prop(muprops, "collider")
        if muprops.collider == 'MU_COL_MESH':
            row = col.row()
            row.prop(muprops, "isTrigger")
            row.prop(muprops, "separate")
            row = col.row()
            row.operator("mucollider.unmake_mesh_collider", text = "Normal Mesh")
        elif muprops.collider == 'MU_COL_SPHERE':
            row = col.row()
            row.prop(muprops, "isTrigger")
            row.prop(muprops, "separate")
            col.prop(muprops, "radius")
            col.prop(muprops, "center")
        elif muprops.collider == 'MU_COL_CAPSULE':
            row = col.row()
            row.prop(muprops, "isTrigger")
            row.prop(muprops, "separate")
            col.prop(muprops, "radius")
            col.prop(muprops, "height")
            col.row().prop(muprops, "direction", expand=True)
            col.prop(muprops, "center")
        elif muprops.collider == 'MU_COL_BOX':
            row = col.row()
            row.prop(muprops, "isTrigger")
            row.prop(muprops, "separate")
            col.prop(muprops, "size")
            col.prop(muprops, "center")
        elif muprops.collider == 'MU_COL_WHEEL':
            row = col.row()
            row.prop(muprops, "isTrigger")
            row.prop(muprops, "separate")
            col.prop(muprops, "radius")
            col.prop(muprops, "center")
            col.prop(muprops, "mass")
            col.prop(muprops, "suspensionDistance")
            box = col.box()
            box.label(text="Suspension")
            muprops.suspensionSpring.draw(context, box)
            box = col.box()
            box.label(text="Forward Friction")
            muprops.forwardFriction.draw(context, box.box())
            box = col.box()
            box.label(text="Side Friction")
            muprops.sideFriction.draw(context, box.box())

classes_to_register = (
    WORKSPACE_PT_tools_mu_collider,
    OBJECT_PT_MuColliderPanel,
)
