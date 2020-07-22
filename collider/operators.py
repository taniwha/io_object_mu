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
from .points import Points

def collect_points(reference):
    w2r = reference.matrix_world.inverted()
    points = Points()
    if bpy.context.mode == 'EDIT_MESH':
        for obj in bpy.context.objects_in_mode:
            if obj.type == 'MESH':
                o2r = w2r @ obj.matrix_world
                points.add_verts(obj.data.vertices, o2r, True)
    else:
        for obj in bpy.context.selected_objects:
            if obj.type == 'MESH':
                o2r = w2r @ obj.matrix_world
                depsgraph = bpy.context.evaluated_depsgraph_get()
                mesh = obj.evaluated_get(depsgraph).to_mesh()
                points.add_verts(mesh.vertices, o2r)
                obj.to_mesh_clear()
    return points

def can_fit_collider(self, context):
    if not hasattr(self, "fitSelected") or not self.fitSelected:
        return False
    if not context.active_object:
        return False
    if context.mode == 'EDIT_MESH' and bpy.context.objects_in_mode:
        return True
    if context.mode == 'OBJECT' and context.selected_objects:
        return True
    return False

def add_collider(self, context):
    context.preferences.edit.use_global_undo = False
    mesh = None
    points = None
    if can_fit_collider(self, context):
        points = collect_points(context.active_object)
    if type(self) == KSPMU_OT_ColliderMesh:
        mesh = bpy.data.meshes.new("collider")
    obj, cobj = create_collider_object("collider", mesh)
    bpy.context.layer_collection.collection.objects.link(obj)
    if points and points.valid:
        obj.parent = context.active_object
    else:
        obj.location = context.scene.cursor.location
    for o in context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    if type(self) == KSPMU_OT_ColliderMesh:
        obj.muproperties.collider = 'MU_COL_MESH'
    elif type(self) == KSPMU_OT_ColliderSphere:
        if points and points.valid:
            center, radius = points.calc_sphere()
        else:
            center, radius = self.center, self.radius
        obj.muproperties.radius = radius
        obj.muproperties.center = center
        obj.muproperties.collider = 'MU_COL_SPHERE'
    elif type(self) == KSPMU_OT_ColliderCapsule:
        obj.muproperties.radius = self.radius
        obj.muproperties.height = self.height
        obj.muproperties.direction = self.direction
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_CAPSULE'
    elif type(self) == KSPMU_OT_ColliderBox:
        if points and points.valid:
            size, center = points.calc_box()
        else:
            size, center = self.size, self.center
        obj.muproperties.size = size
        obj.muproperties.center = center
        obj.muproperties.collider = 'MU_COL_BOX'
    elif type(self) == KSPMU_OT_ColliderWheel:
        obj.muproperties.radius = self.radius
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_WHEEL'

    build_collider(cobj, obj.muproperties)
    context.view_layer.objects.active=obj

    context.preferences.edit.use_global_undo = True
    return {'FINISHED'}

def add_mesh_colliders(self, context, convex):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        obj.select_set(False)
        if obj.type != 'MESH':
            continue
        name = obj.name + ".collider"
        depsgraph = context.evaluated_depsgraph_get()
        objeval = obj.evaluated_get(depsgraph)
        if convex:
            mesh = objeval.to_mesh()
            mesh = quickhull(mesh)
        else:
            mesh = bpy.data.meshes.new_from_object(objeval)
        col = bpy.data.objects.new(name, mesh)
        context.scene.collection.objects.link(col)
        original_collection = col.users_collection
        if original_collection != obj.users_collection:
            bpy.data.collections[obj.users_collection[0].name].objects.link(col)
            original_collection[0].objects.unlink(col)
        col.parent = obj
        col.hide_set(True)
        bpy.context.view_layer.objects.active = col
        col.muproperties.collider = 'MU_COL_MESH'

    context.preferences.edit.use_global_undo = undo
    return {'FINISHED'}

def unmake_mesh_collider(self, context):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    obj = context.active_object
    obj.muproperties.collider = 'MU_COL_NONE'

    context.preferences.edit.use_global_undo = undo
    return {'FINISHED'}

def make_mesh_colliders(self, context):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select_get():
            continue
        if obj.type != 'MESH':
            continue
        if obj.muproperties.collider != 'MU_COL_NONE':
            continue
        obj.muproperties.collider = 'MU_COL_MESH'

    context.preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class KSPMU_OT_UnmakeMeshCollider(bpy.types.Operator):
    """Change a mesh collider into a normal mesh."""
    bl_idname = "mucollider.unmake_mesh_collider"
    bl_label = "Unmake Mesh Collider"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj != None
                and type(obj.data) == bpy.types.Mesh
                and obj.muproperties.collider == 'MU_COL_MESH')

    def execute(self, context):
        keywords = self.as_keywords ()
        return unmake_mesh_collider(self, context, **keywords)

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

    fitSelected: BoolProperty(name = "Fit Selected",
                    description="Fit collider to selection. Uses active "
                    "object as parent and reference frame.",
                    default=True)

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

    fitSelected: BoolProperty(name = "Fit Selected",
                    description="Fit collider to selection. Uses active "
                    "object as parent and reference frame.",
                    default=True)
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
    KSPMU_OT_UnmakeMeshCollider,
    KSPMU_OT_ColliderFromMesh,
    KSPMU_OT_MeshToCollider,
    KSPMU_OT_ColliderMesh,
    KSPMU_OT_ColliderSphere,
    KSPMU_OT_ColliderCapsule,
    KSPMU_OT_ColliderBox,
    KSPMU_OT_ColliderWheel,
)
