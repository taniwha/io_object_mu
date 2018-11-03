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

from .transform import scale, translate

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

def mesh_data(center, radius):
    m = translate(center) @ scale((radius,)*3)
    return (collider_sphere_ve + (m,)),
