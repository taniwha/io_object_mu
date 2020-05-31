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
    sys.path.insert(0, sys.path[0] + "/../utils")
    from vect import *

try:
    from .edge import Edge
except ImportError:
    from edge import Edge

id = 0
epsilon = 1e-5

class Triangle:
    def __init__(self, mesh, a, b, c):
        global id
        self.id = id
        id += 1
        self.edges = [Edge(mesh, a, b), Edge(mesh, b, c), Edge(mesh, c, a)]
        self.redges = [Edge(mesh, b, a), Edge(mesh, c, b), Edge(mesh, a, c)]
        self.mesh = mesh
        self.a = mesh.verts[a]
        self.b = mesh.verts[b]
        self.c = mesh.verts[c]
        self.n = cross(self.edges[0].vect, self.edges[1].vect)
        self.n = div(self.n, sqrt(dot(self.n, self.n)))
        self.vispoints = []
        self.highest = 0
        self.height = -1
        self.faceset = None
        self.light_run = 0

    def __hash__(self):
        a, b, c = self.edges[0].a, self.edges[1].a, self.edges[2].a
        return (a * a + a + b + c) if a > b else (a + b * b + c)

    def __eq__(self, other):
        sa, sb, sc = self.edges[0].a, self.edges[1].a, self.edges[2].a
        oa, ob, oc = other.edges[0].a, other.edges[1].a, other.edges[2].a
        return sa == oa and sb == ob and sc == oc

    def pull(self):
        if self.faceset:
            self.faceset.faces.remove(self)
            self.faceset = None

    def push(self, faceset):
        self.faceset = faceset

    def find_edge(self, edge):
        for i, e in enumerate(self.edges):
            if e == edge:
                return i
        return -1

    def dist(self, point):
        p = self.mesh.verts[point]
        return dot(sub(p, self.a), self.n)

    def is_dup(self, point):
        p = self.mesh.verts[point]
        e = 1e-6
        d = sub(p, self.a)
        if dot(d, d) < e:
            return True
        d = sub(p, self.b)
        if dot(d, d) < e:
            return True
        d = sub(p, self.c)
        if dot(d, d) < e:
            return True
        return False

    def can_see(self, point):
        edges = self.edges
        if point == edges[0].a or point == edges[1].a or point == edges[2].a:
            return True
        return self.dist (point) >= 0

    def add_point(self, point):
        edges = self.edges
        if point == edges[0].a or point == edges[1].a or point == edges[2].a:
            return False
        # can_see is not used here because can_see includes points on the
        # triangle's plane (not a propblem, but subotptimal) and the height
        # is needed anyway as in the end, the highest point is desired.
        d = self.dist(point)
        if d > epsilon:
            if d > self.height:
                self.height = d
                self.highest = len(self.vispoints)
            self.vispoints.append(point)
            return True
        return False

    def write(self, bw):
        bw.write_int(self.edges[0].a)
        bw.write_int(self.edges[1].a)
        bw.write_int(self.edges[2].a)
        bw.write_int(self.highest)
        bw.write_int(len(self.vispoints))
        bw.write_int(self.vispoints)

    def __str__(self):
        return f"Triangle[{self.edges[0]}, {self.edges[1]}, {self.edges[2]}]"
