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

try:
    from ..utils.vect import *
except ImportError:
    import sys
    sys.path.insert(0, sys.path[0] + "/../utils")
    from vect import *
except ValueError:
    import sys
    sys.path.insert(0, sys.path[0] + "/utils")
    from vect import *

class Edge:
    def __init__(self, mesh, a, b):
        self.mesh = mesh
        self.a = a
        self.b = b

    def __hash__(self):
        a, b = self.a, self.b
        return (a * a + a + b) if a > b else (a + b * b)

    def __eq__(self, other):
        return self.a == other.a and self.b == other.b

    @property
    def reverse(self):
        return Edge(self.mesh, self.b, self.a)

    @property
    def vect(self):
        return sub(self.mesh.verts[self.b], self.mesh.verts[self.a])

    @property
    def rvect(self):
        return sub(self.mesh.verts[self.a], self.mesh.verts[self.b])

    def distance(self, point):
        p = self.mesh.verts[self.a]
        v = sub(self.mesh.verts[self.b], p)
        x = sub(self.mesh.verts[point], p)
        #FIXME bad for catastrophic loss of precision
        #better would be the expansion of:
        # Vx Xy (Vx Xy - Vy Xx)
        # Vx Xz (Vx Xz - Vz Xx)
        # Vy Xx (Vy Xx - Vx Xy)
        # Vy Xz (Vy Xz - Vz Xy)
        # Vz Xx (Vz Xx - Vx Xz)
        # Vz Xy (Vz Xy - Vy Xz)
        # ie, the full expansion of (V x X).(V x X)
        vv = dot(v, v)
        xv = dot(x, v)
        xx = dot(x, x)
        return (vv * xx - xv * xv) / vv

    def touches_point(self, point):
        if point == self.a or point == self.b:
            return True
        p = self.mesh.verts[self.a]
        v = sub(self.mesh.verts[self.b], p)
        x = sub(self.mesh.verts[point], p)
        vv = dot(v, v)
        xv = dot(x, v)
        if xv > vv or xv < 0:
            return False
        #FIXME see distance
        xx = dot(x, x)
        d = (vv * xx - xv * xv) / vv
        return d < 1e-5
