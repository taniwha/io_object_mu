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
import bmesh
from bpy.props import BoolProperty, FloatProperty, EnumProperty
from bpy.props import FloatVectorProperty
from mathutils import Vector

from ..quickhull import quickhull
from .. import properties
from . import box, capsule, sphere, wheel

def collider_collection(name):
    if "colliders" not in bpy.data.collections:
        cc = bpy.data.collections.new("colliders")
        cc.hide_viewport = True
        cc.hide_render = True
        cc.hide_select = True
        bpy.context.scene.collection.children.link(cc)
    cc = bpy.data.collections.new("collider:"+name)
    bpy.data.collections["colliders"].children.link(cc)
    return cc

def make_collider_mesh(mesh, vex_list):
    verts = []
    edges = []
    for vex in vex_list:
        v, e, m = vex
        base = len(verts)
        verts.extend(list(map(lambda x: m @ Vector(x), v)))
        edges.extend(list(map(lambda x: (x[0] + base, x[1] + base), e)))
    bm = bmesh.new()
    bv = [None] * len(verts)
    for i, v in enumerate(verts):
        bv[i] = bm.verts.new (v)
    for e in edges:
        bm.edges.new((bv[e[0]], bv[e[1]]))
    bm.to_mesh(mesh)
    return mesh

def build_collider(obj, muprops):
    mesh = obj.data
    mesh_data = None
    if muprops.collider == "MU_COL_MESH":
        mesh_data = box.mesh_data((0, 0, 0), (1, 1, 1))
    elif muprops.collider == "MU_COL_SPHERE":
        mesh_data = sphere.mesh_data(muprops.center, muprops.radius)
    elif muprops.collider == "MU_COL_CAPSULE":
        mesh_data = capsule.mesh_data(muprops.center, muprops.radius, muprops.height, muprops.direction)
    elif muprops.collider == "MU_COL_BOX":
        mesh_data = box.mesh_data(muprops.center, muprops.size)
    elif muprops.collider == "MU_COL_WHEEL":
        mesh_data = wheel.mesh_data(muprops.center, muprops.radius)
    if mesh_data:
        make_collider_mesh (mesh, mesh_data)

def update_collider(obj):
    if not obj:
        return
    muprops = obj.muproperties
    if not muprops.collider:
        return
    if muprops.collider != 'MU_COL_MESH':
        build_collider(obj.dupli_group.objects[0], obj.muproperties)

def create_collider_object(name, mesh):
    pref = "" if mesh else "mesh:"
    if not mesh:
        mesh = bpy.data.meshes.new(name)
    cobj = obj = bpy.data.objects.new(pref+name, mesh)
    # pref acts as an "is mesh collider" bool
    if pref:
        cobj = obj
        collection = collider_collection (name)
        collection.objects.link(obj)
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_size = 0.3
        obj.dupli_type = 'COLLECTION'
        obj.dupli_group = collection
        bpy.context.layer_collection.collection.objects.link(obj)
    else:
        bpy.context.layer_collection.collection.objects.link(obj)
    return obj, cobj

def add_collider(self, context):
    context.user_preferences.edit.use_global_undo = False
    for obj in context.scene.objects:
        obj.select_set('DESELECT')
    mesh = None
    if type(self) == KSPMU_OT_ColliderMesh:
        mesh = bpy.data.meshes.new("collider")
    obj, cobj = create_collider_object("collider", mesh)
    obj.location = context.scene.cursor_location
    obj.select_set('SELECT')
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
        obj.select_set('DESELECT')
        if obj.type != 'MESH':
            continue
        name = obj.name + ".collider"
        mesh = obj.to_mesh(context.scene, True, 'PREVIEW')
        if convex:
            mesh = quickhull(mesh)
        col = bpy.data.objects.new(name, mesh)
        col.parent = obj
        col.select_set('SELECT')
        context.scene.collection.objects.link(col)
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
    """Add Mesh Collider to Selected Meshes"""
    bl_idname = "mucollider.from_mesh"
    bl_label = "Add Mesh Collideri to Selected Meshes"
    bl_options = {'REGISTER', 'UNDO'}

    convex: BoolProperty(name="Make Convex",
                    description="Create a convex hull from the raw mesh.",
                    default=True)

    def execute(self, context):
        keywords = self.as_keywords ()
        return add_mesh_colliders(self, context, **keywords)

class KSPMU_OT_MeshToCollider(bpy.types.Operator):
    """Change Selected Meshes to Add Mesh Colliders"""
    bl_idname = "mucollider.mesh_to_collider"
    bl_label = "Change Selected Meshes to Add Mesh Colliders"
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

class INFO_MT_mucollider_add(bpy.types.Menu):
    bl_idname = "INFO_MT_mucollider_add"
    bl_label = "Mu Collider"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.operator("mucollider.mesh", text = "Mesh");
        layout.operator("mucollider.sphere", text = "Sphere");
        layout.operator("mucollider.capsule", text = "Capsule");
        layout.operator("mucollider.box", text = "Box");
        layout.operator("mucollider.wheel", text = "Wheel");

class WORKSPACE_PT_tools_mu_collider(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_category = "Mu Tools"
    bl_context = ".workspace"
    bl_label = "Add Mu Collider"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Single Collider:")
        layout.operator("mucollider.mesh", text = "Mesh")
        layout.operator("mucollider.sphere", text = "Sphere")
        layout.operator("mucollider.capsule", text = "Capsule")
        layout.operator("mucollider.box", text = "Box")
        layout.operator("mucollider.wheel", text = "Wheel")

        col = layout.column(align=True)
        col.label(text="Multiple Colliders:")
        layout.operator("mucollider.from_mesh", text = "Selected Meshes")
        layout.operator("mucollider.mesh_to_collider", text = "Selected Meshes")

def add_collider_menu_func(self, context):
    self.layout.menu("INFO_MT_mucollider_add", icon='PLUGIN')

classes_to_register = (
    KSPMU_OT_ColliderFromMesh,
    KSPMU_OT_MeshToCollider,
    KSPMU_OT_ColliderMesh,
    KSPMU_OT_ColliderSphere,
    KSPMU_OT_ColliderCapsule,
    KSPMU_OT_ColliderBox,
    KSPMU_OT_ColliderWheel,
    INFO_MT_mucollider_add,
    WORKSPACE_PT_tools_mu_collider,
)

menus_to_register = (
    (bpy.types.VIEW3D_MT_add, add_collider_menu_func),
)
