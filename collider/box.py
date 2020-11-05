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

from ..utils import scale, translate

collider_box_ve = (
    [(-0.5,-0.5,-0.5), (-0.5,-0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5,-0.5),
     ( 0.5, 0.5,-0.5), ( 0.5, 0.5, 0.5), ( 0.5,-0.5, 0.5), ( 0.5,-0.5,-0.5)],
     [( 0, 1), ( 1, 2), ( 2, 3), ( 3, 4),
      ( 4, 5), ( 5, 6), ( 6, 7), ( 7, 0),
      ( 6, 1), ( 5, 2), ( 7, 4), ( 3, 0)])

def mesh_data(center, size):
    """
    Return a mesh data.

    Args:
        center: (float): write your description
        size: (int): write your description
    """
    m = translate(center) @ scale(size)
    return (collider_box_ve + (m,)),
