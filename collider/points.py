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
from mathutils import Vector

from ..quickhull.convex_hull import quickhull
from .seb import smalest_enclosing_ball

class Points:
    def __init__(self):
        self.verts = []

    @property
    def valid(self):
        return len(self.verts) > 0

    def add_verts(self, verts, xform, selected=False):
        if selected:
            verts = [v for v in verts if v.select]
        print(selected, len(verts))
        base = len(self.verts)
        self.verts = self.verts + [None] * len(verts)
        for i, v in enumerate(verts):
            self.verts[base + i] = (xform @ v.co).freeze()

    def calc_box(self):
        if not self.verts:
            return Vector((0, 0, 0)), Vector((0, 0, 0))
        mins = Vector(self.verts[0])
        maxs = Vector(self.verts[0])
        for v in self.verts:
            mins.x = min(mins.x, v.x)
            mins.y = min(mins.y, v.y)
            mins.z = min(mins.z, v.z)
            maxs.x = max(maxs.x, v.x)
            maxs.y = max(maxs.y, v.y)
            maxs.z = max(maxs.z, v.z)
        size = (maxs - mins)
        center = (maxs + mins) / 2
        return size, center

    def calc_sphere(self):
        return smalest_enclosing_ball(self.verts)

    def calc_hull(self):
        return quickhull(self)
