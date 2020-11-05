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
        """
        Initialize the mesh.

        Args:
            self: (todo): write your description
            mesh: (todo): write your description
            a: (int): write your description
            b: (int): write your description
            c: (int): write your description
        """
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
        self.vispoints = set()
        self.highest_point = -1
        self.height = -1
        self.faceset = None
        self.light_run = 0

    def __hash__(self):
        """
        Compute hash of the hashs.

        Args:
            self: (todo): write your description
        """
        a, b, c = self.edges[0].a, self.edges[1].a, self.edges[2].a
        return (a * a + a + b + c) if a > b else (a + b * b + c)

    def __eq__(self, other):
        """
        Determine if two edges are equal.

        Args:
            self: (todo): write your description
            other: (todo): write your description
        """
        sa, sb, sc = self.edges[0].a, self.edges[1].a, self.edges[2].a
        oa, ob, oc = other.edges[0].a, other.edges[1].a, other.edges[2].a
        return sa == oa and sb == ob and sc == oc

    def pull(self):
        """
        Pulls all faces from the mesh.

        Args:
            self: (todo): write your description
        """
        if self.faceset:
            self.faceset.faces.remove(self)
            self.faceset = None

    def push(self, faceset):
        """
        Push a list of faces to the network.

        Args:
            self: (todo): write your description
            faceset: (todo): write your description
        """
        self.faceset = faceset

    def find_edge(self, edge):
        """
        Finds an edge from the graph.

        Args:
            self: (todo): write your description
            edge: (todo): write your description
        """
        for i, e in enumerate(self.edges):
            if e == edge:
                return i
        return -1

    def dist(self, point):
        """
        Return the distance between the given point.

        Args:
            self: (todo): write your description
            point: (int): write your description
        """
        p = self.mesh.verts[point]
        return dot(sub(p, self.a), self.n)

    def is_dup(self, point):
        """
        Determine if point is duplicate point.

        Args:
            self: (todo): write your description
            point: (int): write your description
        """
        p = self.mesh.verts[point]
        e = 1e-6
        d = sub(p, self.a)
        h = dot(d, self.n)
        if h * h > e:
            return False
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
        """
        Determine if a point on point.

        Args:
            self: (todo): write your description
            point: (int): write your description
        """
        edges = self.edges
        if point == edges[0].a or point == edges[1].a or point == edges[2].a:
            return True
        return self.dist (point) >= 0

    def add_point(self, point):
        """
        Add a point to the map.

        Args:
            self: (todo): write your description
            point: (int): write your description
        """
        # can_see is not used here because can_see includes points on the
        # triangle's plane (not a propblem, but subotptimal) and the height
        # is needed anyway as in the end, the highest point is desired.
        d = self.dist(point)
        if d <= 0:
            return False
        elif d > self.height:
            self.height = d
            self.highest_point = point
        self.vispoints.add(point)
        return True

    def write(self, bw):
        """
        Writes a bw file

        Args:
            self: (todo): write your description
            bw: (todo): write your description
        """
        bw.write_int(self.edges[0].a)
        bw.write_int(self.edges[1].a)
        bw.write_int(self.edges[2].a)
        bw.write_int(self.highest_point)
        bw.write_int(len(self.vispoints))
        bw.write_int(self.vispoints)

    def __str__(self):
        """
        Return a string representation of this object.

        Args:
            self: (todo): write your description
        """
        return f"Triangle({self.id})[{self.edges[0]}, {self.edges[1]}, {self.edges[2]}]"
