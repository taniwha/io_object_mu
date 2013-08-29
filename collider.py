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
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum

collider_sphere_ve = (
    [(-1.000, 0.000, 0.000), (-0.866, 0.000, 0.500), (-0.500, 0.000, 0.866),
     ( 0.000, 0.000, 1.000),
     ( 0.500, 0.000, 0.866), ( 0.866, 0.000, 0.500), ( 1.000, 0.000, 0.000),
     ( 0.000,-1.000, 0.000), ( 0.000,-0.866, 0.500), ( 0.000,-0.500, 0.866),
     ( 0.000, 0.000, 1.000),
     ( 0.000, 0.500, 0.866), ( 0.000, 0.866, 0.500), ( 0.000, 1.000, 0.000),

     (-0.866, 0.000,-0.500), (-0.500, 0.000,-0.866), ( 0.000, 0.000, 1.000),
     ( 0.500, 0.000,-0.866), ( 0.866, 0.000,-0.500),
     ( 0.000,-0.866,-0.500), ( 0.000,-0.500,-0.866), ( 0.000, 0.000, 1.000),
     ( 0.000, 0.500,-0.866), ( 0.000, 0.866,-0.500)],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11,12), (12,13),
     ( 0,14), (14,15), (15,16), (16,17), (17,18), (18, 6),
     ( 7,19), (19,20), (20,21), (21,22), (22,23), (23,13)])
collider_capsule_cyl_ve = (
    [(-1.000, 0.000,-1.000), (-0.866, 0.500,-1.000), (-0.500, 0.866,-1.000),
     ( 0.000, 1.000,-1.000), ( 0.500, 0.866,-1.000), ( 0.866, 0.500,-1.000),
     ( 1.000, 0.000,-1.000), ( 0.866,-0.500,-1.000), ( 0.500,-0.866,-1.000),
     ( 0.000,-1.000,-1.000), (-0.500,-0.866,-1.000), (-0.866, 0.500,-1.000),
     (-1.000, 0.000, 1.000), (-0.866, 0.500, 1.000), (-0.500, 0.866, 1.000),
     ( 0.000, 1.000, 1.000), ( 0.500, 0.866, 1.000), ( 0.866, 0.500, 1.000),
     ( 1.000, 0.000, 1.000), ( 0.866,-0.500, 1.000), ( 0.500,-0.866, 1.000),
     ( 0.000,-1.000, 1.000), (-0.500,-0.866, 1.000), (-0.866, 0.500, 1.000),],
    [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4), ( 4, 5), ( 5, 6),
     ( 6, 7), ( 7, 8), ( 8, 9), ( 9,10), (10,11), (11, 0),
     (12,13), (13,14), (14,15), (15,16), (16,17), (17,18),
     (18,19), (19,20), (20,21), (21,21), (22,21), (23,12),
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

def sphere(name, radius):
    col = (collider_sphere_ve + (Matrix.Scale(radius, 4),)),
    return make_collider(name, col)

def capsule(name, radius, height, direction):
    m = (Matrix.Translation(Vector(0, 0, height/2))
         * Matrix.Matrix.Scale(radius, 4))
    col = (collider_capsule_end_ve + (m,)),
    m = Matrix.Scale(-1,4) * m
    col = col + (collider_capsule_end_ve + (m,)),
    m = Matrix(((radius,      0,        0, 0),
                (     0, radius,        0, 0),
                (     0,      0, height/2, 0),
                (     0,      0,        0, 1)))
    return make_collider(name, collider_capsule_arm)

def box(name, size):
    s = Vector(size)
    m = Matrix(((s.x,  0,  0, 0),
                (  0,s.y,  0, 0),
                (  0,  0,s.z, 0),
                (  0,  0,  0, 1)))
    col = (collider_box_ve + (m,)),
    return make_collider(name, col)

def wheel(name, radius):
    col = (collider_sphere_ve + (Matrix.Scale(radius, 4),)),
    return make_collider(name, col)
