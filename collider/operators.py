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
from bpy.props import BoolProperty, FloatProperty, EnumProperty
from bpy.props import FloatVectorProperty

from ..quickhull.convex_hull import quickhull
from .. import properties
from .collider import create_collider_object, build_collider

def add_collider(self, context):
    context.user_preferences.edit.use_global_undo = False
    for obj in context.scene.objects:
        obj.select_set(False)
    mesh = None
    if type(self) == KSPMU_OT_ColliderMesh:
        mesh = bpy.data.meshes.new("collider")
    obj, cobj = create_collider_object("collider", mesh)
    obj.location = context.scene.cursor_location
    obj.select_set(True)
    if type(self) == KSPMU_OT_ColliderMesh:
        obj.muproperties.collider = 'MU_COL_MESH'
    elif type(self) == KSPMU_OT_ColliderSphere:
        obj.muproperties.radius = self.radius
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_SPHERE'
    elif type(self) == KSPMU_OT_ColliderCapsule:
        obj.muproperties.radius = self.radius
        obj.muproperties.height = self.height
        obj.muproperties.direction = self.direction
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_CAPSULE'
    elif type(self) == KSPMU_OT_ColliderBox:
        obj.muproperties.size = self.size
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_BOX'
    elif type(self) == KSPMU_OT_ColliderWheel:
        obj.muproperties.radius = self.radius
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_WHEEL'

    build_collider(cobj, obj.muproperties)
    context.view_layer.objects.active=obj

    context.user_preferences.edit.use_global_undo = True
    return {'FINISHED'}

def add_mesh_colliders(self, context, convex):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        obj.select_set(False)
        if obj.type != 'MESH':
            continue
        name = obj.name + ".collider"
        mesh = obj.to_mesh(context.depsgraph, True)
        if convex:
            mesh = quickhull(mesh)
        col = bpy.data.objects.new(name, mesh)
        context.scene.collection.objects.link(col)
        col.parent = obj
        col.select_set(True)
        col.muproperties.collider = 'MU_COL_MESH'

    context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

def make_mesh_colliders(self, context):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        if obj.type != 'MESH':
            continue
        if obj.muproperties.collider != 'MU_COL_NONE':
            continue
        obj.muproperties.collider = 'MU_COL_MESH'

    context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_ColliderFromMesh(bpy.types.Operator):
    """Add mesh collider to selected meshes, basing the collider mesh on the original mesh"""
    bl_idname = "mucollider.from_mesh"
    bl_label = "Make Mesh Collider"
    bl_options = {'REGISTER', 'UNDO'}

    convex: BoolProperty(name="Make Convex",
                    description="Create a convex hull from the raw mesh.",
                    default=True)

    def execute(self, context):
        keywords = self.as_keywords ()
        return add_mesh_colliders(self, context, **keywords)

class KSPMU_OT_MeshToCollider(bpy.types.Operator):
    """Change selected mesh objects to mesh colliders"""
    bl_idname = "mucollider.mesh_to_collider"
    bl_label = "Convert to Mesh Collider"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        keywords = self.as_keywords ()
        return make_mesh_colliders(self, context, **keywords)

class KSPMU_OT_ColliderMesh(bpy.types.Operator):
    """Add Mesh Collider"""
    bl_idname = "mucollider.mesh"
    bl_label = "Add Mesh Collider"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return add_collider(self, context)

class KSPMU_OT_ColliderSphere(bpy.types.Operator):
    """Add Sphere Collider"""
    bl_idname = "mucollider.sphere"
    bl_label = "Add Sphere Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(name = "Radius", min = 0.0, default = 0.5)
    center: FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class KSPMU_OT_ColliderCapsule(bpy.types.Operator):
    """Add Capsule Collider"""
    bl_idname = "mucollider.capsule"
    bl_label = "Add Capsule Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(name = "Radius", min = 0.0, default = 0.5)
    height: FloatProperty(name = "Height", min = 0.0, default = 1.0)
    direction: EnumProperty(items = properties.dir_items, name = "Direction")
    center: FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class KSPMU_OT_ColliderBox(bpy.types.Operator):
    """Add Box Collider"""
    bl_idname = "mucollider.box"
    bl_label = "Add Box Collider"
    bl_options = {'REGISTER', 'UNDO'}

    size: FloatVectorProperty(name = "Size", size = 3, subtype = 'XYZ',
                               min = 0.0, default = (1.0,1.0,1.0))
    center: FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class KSPMU_OT_ColliderWheel(bpy.types.Operator):
    """Add Wheel Collider"""
    bl_idname = "mucollider.wheel"
    bl_label = "Add Wheel Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(name = "Radius", min = 0.0, default = 0.5)
    center: FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

classes_to_register = (
    KSPMU_OT_ColliderFromMesh,
    KSPMU_OT_MeshToCollider,
    KSPMU_OT_ColliderMesh,
    KSPMU_OT_ColliderSphere,
    KSPMU_OT_ColliderCapsule,
    KSPMU_OT_ColliderBox,
    KSPMU_OT_ColliderWheel,
)
