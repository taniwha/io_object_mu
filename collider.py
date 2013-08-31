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
    [(-1.000, 0.000,-1.000), (-0.866, 0.500,-1.000), (-0.500, 0.866,-1.000),
     ( 0.000, 1.000,-1.000), ( 0.500, 0.866,-1.000), ( 0.866, 0.500,-1.000),
     ( 1.000, 0.000,-1.000), ( 0.866,-0.500,-1.000), ( 0.500,-0.866,-1.000),
     ( 0.000,-1.000,-1.000), (-0.500,-0.866,-1.000), (-0.866, 0.500,-1.000)],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 6, 7), ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11, 0)])

def make_collider(name, vex_list):
    verts = []
    edges = []
    for vex in vex_list:
        v, e, m = vex
        base = len(verts)
        verts.extend(list(map(lambda x: m * Vector(x), v)))
        edges.extend(list(map(lambda x: (x[0] + base, x[1] + base), e)))
    mesh = bpy.data.meshes.new(name)
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

def sphere(name, center, radius):
    m = translate(center) * scale((radius,)*3)
    col = (collider_sphere_ve + (m,)),
    return make_collider(name, col)

def capsule(name, center, radius, height, direction):
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
    return make_collider(name, col)

def box(name, center, size):
    m = translate(center) * scale(size)
    col = (collider_box_ve + (m,)),
    return make_collider(name, col)

def wheel(name, center, radius):
    m = translate(center) * scale((radius,)*3)
    col = (collider_sphere_ve + (m,)),
    return make_collider(name, col)

def add_collider(self, context):
    context.user_preferences.edit.use_global_undo = False
    name = "collider"
    if type(self) == ColliderMesh:
        mesh = box(name, (0, 0, 0), (1, 1, 1))
    elif type(self) == ColliderSphere:
        mesh = sphere(name, self.center, self.radius)
    elif type(self) == ColliderCapsule:
        mesh = capsule(name, self.center, self.radius, self.height,
                       self.direction)
    elif type(self) == ColliderBox:
        mesh = box(name, self.center, self.size)
    elif type(self) == ColliderWheel:
        mesh = wheel(name, self.center, self.radius)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = context.scene.cursor_location
    obj.select = True
    context.scene.objects.link(obj)
    bpy.context.scene.objects.active=obj
    context.user_preferences.edit.use_global_undo = True
    return {'FINISHED'}


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

    radius = FloatProperty(name = "Radius")
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class ColliderCapsule(bpy.types.Operator):
    """Add Capsule Collider"""
    bl_idname = "mucollider.capsule"
    bl_label = "Add Capsule Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius = FloatProperty(name = "Radius")
    height = FloatProperty(name = "Height")
    direction = EnumProperty(items = properties.dir_items, name = "Direction")
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class ColliderBox(bpy.types.Operator):
    """Add Box Collider"""
    bl_idname = "mucollider.box"
    bl_label = "Add Box Collider"
    bl_options = {'REGISTER', 'UNDO'}

    size = FloatVectorProperty(name = "Size", subtype = 'XYZ')
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ')

    def execute(self, context):
        return add_collider(self, context)

class ColliderWheel(bpy.types.Operator):
    """Add Wheel Collider"""
    bl_idname = "mucollider.wheel"
    bl_label = "Add Wheel Collider"
    bl_options = {'REGISTER', 'UNDO'}

    radius = FloatProperty(name = "Radius")
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

def menu_func(self, context):
    self.layout.menu("INFO_MT_mucollider_add", icon='PLUGIN')
