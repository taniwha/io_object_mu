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

try:
    from .edge import Edge
    from .triangle import Triangle
    from .faceset import FaceSet
    from .connectivity import Connectivity
    from .binary import BinaryWriter
except ImportError:
    from edge import Edge
    from triangle import Triangle
    from faceset import FaceSet
    from connectivity import Connectivity
    from binary import BinaryWriter

class QuickHull:
    dump_faces = False

    def __init__(self, mesh):
        self.mesh = mesh
        self.error = False

    def find_extreme_points(self):
        points = [0] * 6
        for i, v in enumerate(self.mesh.verts):
            if v[0] < self.mesh.verts[points[0]][0]:
                points[0] = i
            if v[1] < self.mesh.verts[points[1]][1]:
                points[1] = i
            if v[2] < self.mesh.verts[points[2]][2]:
                points[2] = i
            if v[0] > self.mesh.verts[points[3]][0]:
                points[0] = i
            if v[1] > self.mesh.verts[points[4]][1]:
                points[1] = i
            if v[2] > self.mesh.verts[points[5]][2]:
                points[5] = i
        self.points = points

    def find_simplex(self):
        a = 0
        b = 1
        tEdge = Edge(self.mesh, a, b)
        bestd = dot(tEdge.vect, tEdge.vect)
        for i in range(6):
            p = self.points[i]
            for j in range(6):
                q = self.points[j]
                if q == p or (a, b == p, q) or (a, b == q, p):
                    continue
                tEdge.a = p
                tEdge.b = q
                r = dot(tEdge.vect, tEdge.vect)
                if r > bestd:
                    a, b = p, q
                    bestd = r
        tEdge.a = a
        tEdge.b = b
        bestd = 0
        c = 0
        for i in range(6):
            p = self.points[i]
            if a == p or b == p:
                continue
            r = tEdge.distance(p)
            if r > bestd:
                c = p
                bestd = r

        tri = Triangle(self.mesh, a, b, c)
        d = 0
        bestd = 0
        for p in range(len(self.mesh.verts)):
            if a == p or b == p or c == p:
                continue
            r = tri.dist(p)
            if r*r > bestd * bestd:
                d = p
                bestd = r
        if bestd > 0:
            b, c = c, b
        faces = FaceSet(self.mesh)
        faces.add(Triangle(self.mesh, a, b, c))
        faces.add(Triangle(self.mesh, a, d, b))
        faces.add(Triangle(self.mesh, a, c, d))
        faces.add(Triangle(self.mesh, c, b, d))
        return faces

    def split_triangle(self, t, splitEdge, point, connectivity):
        a = t.edges[splitEdge].a;
        b = t.edges[splitEdge].b;
        c = t.edges[(splitEdge + 1) % 3].b
        faceset = t.faceset
        t.pull()
        connectivity.remove(t)
        nt1 = Triangle(self.mesh, a, point, c)
        nt2 = Triangle(self.mesh, point, b, c)
        nt1.vispoints = t.vispoints
        nt1.height = t.height
        nt1.highest = t.highest
        nt2.vispoints = list(t.vispoints)
        nt2.height = t.height
        nt2.highest = t.highest

        faceset.add(nt1)
        faceset.add(nt2)
        connectivity.add(nt1)
        connectivity.add(nt2)

    def GetHull(self):
        self.find_extreme_points()
        faces = self.find_simplex()
        connectivity = Connectivity(faces)
        dupPoints = set()
        for i in range(len(self.mesh.verts)):
            for f in faces:
                if f.is_dup(i):
                    dupPoints.add(i)
                    break;
            if i in dupPoints:
                continue
            for f in faces:
                f.add_point(i)

        finalFaces = FaceSet(self.mesh)
        donePoints = set()

        iter = 0
        bw = None

        while len(faces):
            if self.dump_faces:
                bw = BinaryWriter(open(f"/tmp/quickhull-{iter:05d}.bin", "wb"))
                self.mesh.write(bw)
                faces.write(bw)
                finalFaces.write(bw)
            iter += 1
            f = faces.pop()
            if not f.vispoints:
                finalFaces.add(f)
                continue
            point = f.vispoints[f.highest]
            litFaces = connectivity.light_faces(f, point)
            if bw:
                bw.write_int(point)
                litFaces.write(bw)
            connectivity.remove(litFaces)
            horizonEdges = litFaces.find_outer_edges()
            newFaces = FaceSet(self.mesh)
            for e in horizonEdges:
                if e.touches_point(point):
                    re = e.reverse
                    t = connectivity[re]
                    splitEdge = t.find_edge(re)
                    if splitEdge >= 0:
                        self.split_triangle(t, splitEdge, point, connectivity)
                else:
                    tri = Triangle(self.mesh, e.a, e.b, point)
                    newFaces.add(tri)
                    connectivity.add(tri)
            donePoints.clear()
            for lf in litFaces:
                for p in lf.vispoints:
                    if p in donePoints:
                        continue
                    donePoints.add(p)
                    for nf in newFaces:
                        if nf.is_dup(p):
                            dupPoints.add(p)
                            p = -1
                            break;
                    if p < 0:
                        continue
                    for nf in newFaces:
                        nf.add_point(p)
            if bw:
                newFaces.write(bw)
            for nf in set(newFaces.faces):
                if nf.vispoints:
                    faces.add(nf)
                else:
                    finalFaces.add(nf)
            if bw:
                bw.close()
                bw = None
            if connectivity.error:
                vis = set()
                for lf in litFaces:
                    for vp in lf.vispoints:
                        vis.add(vp)
                print(f"[Quickhull] {len(litFaces)} {len(vis)}")
                for lf in litFaces:
                    dist1 = 1e38
                    dist2 = 1e38
                    for i in range(3):
                        d = lf.edges[i].distance(point)
                        if d < dist1:
                            dist1 = d
                        v = self.mesh.verts[point]
                        v = sub(v, self.mesh.verts[lf.edges[i].a])
                        d = sqrt(dot(v, v))
                        if d < dist2:
                            dist2 = d
                    print(f"    h:{lf.dist(point)} d1:{dist1} d2:{dist2} {lf.edges[0].touches_point(point)} {lf.edges[1].touches_point(point)} {lf.edges[2].touches_point(point)}")
                break
        if self.dump_faces and not connectivity.error:
            bw = BinaryWriter(open(f"/tmp/quickhull-{iter:05d}.bin", "wb"))
            self.mesh.write(bw)
            faces.write(bw)
            finalFaces.write(bw)
            bw.write_int(-1)
            bw.write_int(0)
            bw.write_int(0)
            bw.close()
        self.error = connectivity.error
        return finalFaces
