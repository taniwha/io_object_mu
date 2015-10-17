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
from bpy_extras.object_utils import object_data_add
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum
from . import properties

collider_sphere_ve = (
    [(-1.000, 0.000, 0.000), (-0.866, 0.000, 0.500), (-0.500, 0.000, 0.866),
     ( 0.000, 0.000, 1.000), ( 0.500, 0.000, 0.866), ( 0.866, 0.000, 0.500),
     ( 1.000, 0.000, 0.000), ( 0.866, 0.000,-0.500), ( 0.500, 0.000,-0.866),
     ( 0.000, 0.000,-1.000), (-0.500, 0.000,-0.866), (-0.866, 0.000,-0.500),

     ( 0.000,-1.000, 0.000), ( 0.000,-0.866, 0.500), ( 0.000,-0.500, 0.866),
     ( 0.000, 0.000, 1.000), ( 0.000, 0.500, 0.866), ( 0.000, 0.866, 0.500),
     ( 0.000, 1.000, 0.000), ( 0.000, 0.866,-0.500), ( 0.000, 0.500,-0.866),
     ( 0.000, 0.000,-1.000), ( 0.000,-0.500,-0.866), ( 0.000,-0.866,-0.500),

     (-1.000, 0.000, 0.000), (-0.866, 0.500, 0.000), (-0.500, 0.866, 0.000),
     ( 0.000, 1.000, 0.000), ( 0.500, 0.866, 0.000), ( 0.866, 0.500, 0.000),
     ( 1.000, 0.000, 0.000), ( 0.866,-0.500, 0.000), ( 0.500,-0.866, 0.000),
     ( 0.000,-1.000, 0.000), (-0.500,-0.866, 0.000), (-0.866,-0.500, 0.000)],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 6, 7), ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11, 0),
     (12,13), (13,14), (14,15), (15,16), (16,17), (17,18),
     (18,19), (19,20), (20,21), (21,22), (22,23), (23,12),
     (24,25), (25,26), (26,27), (27,28), (28,29), (29,30),
     (30,31), (31,32), (32,33), (33,34), (34,35), (35,24)])
collider_capsule_cyl_ve = (
    [(-1.000, 0.000,-1.000), (-0.866, 0.500,-1.000), (-0.500, 0.866,-1.000),
     ( 0.000, 1.000,-1.000), ( 0.500, 0.866,-1.000), ( 0.866, 0.500,-1.000),
     ( 1.000, 0.000,-1.000), ( 0.866,-0.500,-1.000), ( 0.500,-0.866,-1.000),
     ( 0.000,-1.000,-1.000), (-0.500,-0.866,-1.000), (-0.866,-0.500,-1.000),
     (-1.000, 0.000, 1.000), (-0.866, 0.500, 1.000), (-0.500, 0.866, 1.000),
     ( 0.000, 1.000, 1.000), ( 0.500, 0.866, 1.000), ( 0.866, 0.500, 1.000),
     ( 1.000, 0.000, 1.000), ( 0.866,-0.500, 1.000), ( 0.500,-0.866, 1.000),
     ( 0.000,-1.000, 1.000), (-0.500,-0.866, 1.000), (-0.866,-0.500, 1.000),],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 6, 7), ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11, 0),
     (12,13), (13,14), (14,15), (15,16), (16,17), (17,18),
     (18,19), (19,20), (20,21), (21,22), (22,23), (23,12),
     ( 0,12), ( 3,15), ( 6,18), ( 9,21)])
collider_capsule_end_ve = (
    [(-1.000, 0.000, 0.000), (-0.866, 0.000, 0.500), (-0.500, 0.000, 0.866),
     ( 0.000, 0.000, 1.000),
     ( 0.500, 0.000, 0.866), ( 0.866, 0.000, 0.500), ( 1.000, 0.000, 0.000),
     ( 0.000,-1.000, 0.000), ( 0.000,-0.866, 0.500), ( 0.000,-0.500, 0.866),
     ( 0.000, 0.000, 1.000),
     ( 0.000, 0.500, 0.866), ( 0.000, 0.866, 0.500), ( 0.000, 1.000, 0.000),],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11,12), (12,13)])
collider_box_ve = (
    [(-0.5,-0.5,-0.5), (-0.5,-0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5,-0.5),
     ( 0.5, 0.5,-0.5), ( 0.5, 0.5, 0.5), ( 0.5,-0.5, 0.5), ( 0.5,-0.5,-0.5)],
     [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4),
      ( 4, 5), ( 5, 6), ( 6, 7), ( 7, 0),
      ( 6, 1), ( 5, 2), ( 7, 4), ( 3, 0)])
collider_wheel_ve = (
    [( 0.000,-1.000, 0.000), ( 0.000,-0.866, 0.500), ( 0.000,-0.500, 0.866),
     ( 0.000, 0.000, 1.000), ( 0.000, 0.500, 0.866), ( 0.000, 0.866, 0.500),
     ( 0.000, 1.000, 0.000), ( 0.000, 0.866,-0.500), ( 0.000, 0.500,-0.866),
     ( 0.000, 0.000,-1.000), ( 0.000,-0.500,-0.866), ( 0.000,-0.866,-0.500)],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 6, 7), ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11, 0)])

def make_collider_mesh(mesh, vex_list):
    verts = []
    edges = []
    for vex in vex_list:
        v, e, m = vex
        base = len(verts)
        verts.extend(list(map(lambda x: m * Vector(x), v)))
        edges.extend(list(map(lambda x: (x[0] + base, x[1] + base), e)))
    if mesh.vertices:
        bm = bmesh.new()
        bv = [None] * len(verts)
        for i, v in enumerate(verts):
            bv[i] = bm.verts.new (v)
        for e in edges:
            bm.edges.new((bv[e[0]], bv[e[1]]))
        bm.to_mesh(mesh)
    else:
        mesh.from_pydata(verts, edges, [])
    return mesh

def translate(d):
    return Matrix.Translation(Vector(d))

def scale(s):
    s = Vector(s)
    return Matrix(((s.x,  0,  0, 0),
                   (  0,s.y,  0, 0),
                   (  0,  0,s.z, 0),
                   (  0,  0,  0, 1)))

def rotate(r):
    return Quaternion(r).normalized().to_matrix().to_4x4()

def sphere(mesh, center, radius):
    m = translate(center) * scale((radius,)*3)
    col = (collider_sphere_ve + (m,)),
    make_collider_mesh(mesh, col)

def capsule(mesh, center, radius, height, direction):
    height -= 2 * radius
    if direction == 0 or direction == 'MU_X':
        # rotate will normalize the quaternion
        r = rotate((1, 0, 1, 0))
    elif direction == 2 or direction == 'MU_Y':
        # rotate will normalize the quaternion
        r = rotate((1,-1, 0, 0))
    elif direction == 1 or direction == 'MU_Z':
        # the mesh is setup for running along Z (Unity Y), so don't rotate
        r = rotate((1, 0, 0, 0))
    r = translate(center) * r
    m = (Matrix.Translation(Vector((0, 0, height/2)))
         * Matrix.Scale(radius, 4))
    col = (collider_capsule_end_ve + (r * m,)),
    m = Matrix.Scale(-1,4) * m
    col = col + ((collider_capsule_end_ve + (r * m,)),)
    m = Matrix(((radius,      0,        0, 0),
                (     0, radius,        0, 0),
                (     0,      0, height/2, 0),
                (     0,      0,        0, 1)))
    col = col + ((collider_capsule_cyl_ve + (r * m,)),)
    make_collider_mesh(mesh, col)

def box(mesh, center, size):
    m = translate(center) * scale(size)
    col = (collider_box_ve + (m,)),
    make_collider_mesh(mesh, col)

def wheel(mesh, center, radius):
    m = translate(center) * scale((radius,)*3)
    col = (collider_wheel_ve + (m,)),
    make_collider_mesh(mesh, col)

def build_collider(obj):
    muprops = obj.muproperties
    mesh = obj.data
    if muprops.collider == "MU_COL_MESH":
        box(mesh, (0, 0, 0), (1, 1, 1))
    elif muprops.collider == "MU_COL_SPHERE":
        sphere(mesh, muprops.center, muprops.radius)
    elif muprops.collider == "MU_COL_CAPSULE":
        capsule(mesh, muprops.center, muprops.radius, muprops.height, muprops.direction)
    elif muprops.collider == "MU_COL_BOX":
        box(mesh, muprops.center, muprops.size)
    elif muprops.collider == "MU_COL_WHEEL":
        wheel(mesh, muprops.center, muprops.radius)

def update_collider(obj):
    if not obj:
        return
    muprops = obj.muproperties
    if not muprops.collider:
        return
    build_collider(obj)

def add_collider(self, context):
    context.user_preferences.edit.use_global_undo = False
    name = "collider"
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = context.scene.cursor_location
    obj.select = True
    context.scene.objects.link(obj)
    bpy.context.scene.objects.active=obj
    if type(self) == ColliderMesh:
        obj.muproperties.collider = 'MU_COL_MESH'
    elif type(self) == ColliderSphere:
        obj.muproperties.radius = self.radius
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_SPHERE'
    elif type(self) == ColliderCapsule:
        obj.muproperties.radius = self.radius
        obj.muproperties.height = self.height
        obj.muproperties.direction = self.direction
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_CAPSULE'
    elif type(self) == ColliderBox:
        obj.muproperties.size = self.size
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_BOX'
    elif type(self) == ColliderWheel:
        obj.muproperties.radius = self.radius
        obj.muproperties.center = self.center
        obj.muproperties.collider = 'MU_COL_WHEEL'

    build_collider(obj)
    context.user_preferences.edit.use_global_undo = True
    return {'FINISHED'}

def add_mesh_colliders(self, context):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        if not obj.select:
            continue
        obj.select = False
        if obj.type != 'MESH':
            continue
        name = obj.name + ".collider"
        col = bpy.data.objects.new(name, obj.data)
        col.parent = obj
        col.select = True
        context.scene.objects.link(col)
        col.muproperties.collider = 'MU_COL_MESH'

    context.user_preferences.edit.use_global_undo = True
    return {'FINISHED'}

class ColliderFromMesh(bpy.types.Operator):
    """Add Mesh Collider to Selected Meshes"""
    bl_idname = "mucollider.from_mesh"
    bl_label = "Add Mesh Collideri to Selected Meshes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return add_mesh_colliders(self, context)

class ColliderMesh(bpy.types.Operator):
    """Add Mesh Collider"""
    bl_idname = "mucollider.mesh"
    bl_label = "Add Mesh Collider"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return add_collider(self, context)

class ColliderSphere(bpy.types.Operator):
    """Add Sphere Collider"""
    bl_idname = "mucollider.sphere"
    bl_label = "Add Sphere Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius = FloatProperty(name = "Radius", min = 0.0, default = 0.5)
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class ColliderCapsule(bpy.types.Operator):
    """Add Capsule Collider"""
    bl_idname = "mucollider.capsule"
    bl_label = "Add Capsule Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius = FloatProperty(name = "Radius", min = 0.0, default = 0.5)
    height = FloatProperty(name = "Height", min = 0.0, default = 1.0)
    direction = EnumProperty(items = properties.dir_items, name = "Direction")
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class ColliderBox(bpy.types.Operator):
    """Add Box Collider"""
    bl_idname = "mucollider.box"
    bl_label = "Add Box Collider"
    bl_options = {'REGISTER', 'UNDO'}

    size = FloatVectorProperty(name = "Size", size = 3, subtype = 'XYZ',
                               min = 0.0, default = (1.0,1.0,1.0))
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class ColliderWheel(bpy.types.Operator):
    """Add Wheel Collider"""
    bl_idname = "mucollider.wheel"
    bl_label = "Add Wheel Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius = FloatProperty(name = "Radius", min = 0.0, default = 0.5)
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

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

class VIEW3D_PT_tools_mu_collider(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Mu Tools"
    bl_context = "objectmode"
    bl_label = "Add Mu Collider"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Single Collider:")
        layout.operator("mucollider.mesh", text = "Mesh");
        layout.operator("mucollider.sphere", text = "Sphere");
        layout.operator("mucollider.capsule", text = "Capsule");
        layout.operator("mucollider.box", text = "Box");
        layout.operator("mucollider.wheel", text = "Wheel");

        col = layout.column(align=True)
        col.label(text="Multiple Colliders:")
        layout.operator("mucollider.from_mesh", text = "Selected Meshes");

def menu_func(self, context):
    self.layout.menu("INFO_MT_mucollider_add", icon='PLUGIN')

def register():
    bpy.types.INFO_MT_add.append(menu_func)

def unregister():
    bpy.types.INFO_MT_add.append(menu_func)
