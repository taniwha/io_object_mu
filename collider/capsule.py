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

from .transform import rotate, scale, translate

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

direction_map = {
    # rotate will normalize the quaternion
    0:(1, 0, 1, 0),
    'MU_X':(1, 0, 1, 0),

    # rotate will normalize the quaternion
    2:(1,-1, 0, 0),
    'MU_Y':(1,-1, 0, 0),

    # the mesh is setup for running along Z (Unity Y), so don't rotate
    1:(1, 0, 0, 0),
    'MU_Z':(1, 0, 0, 0),
}

def mesh_data(center, radius, height, direction):
    height -= 2 * radius
    r = rotate(direction_map[direction])
    r = translate(center) @ r
    m = translate((0, 0, height/2)) @ scale((radius,) * 3)
    col = (collider_capsule_end_ve + (r @ m,)),
    m = scale((-1,) * 3) @ m
    col = col + ((collider_capsule_end_ve + (r @ m,)),)
    m = scale ((radius, radius, height/2))
    col = col + ((collider_capsule_cyl_ve + (r @ m,)),)
    return col
