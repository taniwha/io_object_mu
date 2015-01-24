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
from mu import Mu, MuEnum, MuColliderMesh, MuMesh
from vect import *
import sys

id = 0

class Triangle:
    def __init__(self, mesh, a, b, c):
        global id
        self.id = id
        id += 1
        self.edges = [(a, b), (b, c), (c, a)]
        self.redges = [(b, a), (c, b), (a, c)]
        self.mesh = mesh
        a = self.a = mesh.verts[a]
        b = self.b = mesh.verts[b]
        c = self.c = mesh.verts[c]
        self.n = cross(sub(b,a), sub(c,a))
        self.vispoints = []
        self.highest = None
        self.height = -1
    def dist(self, point):
        p = self.mesh.verts[point]
        return dot(sub(p, self.a), self.n)
    def can_see(self, point):
        p = self.mesh.verts[point]
        return dot(sub(p, self.a), self.n) > -1e-6
    def add_point(self, point):
        d = self.dist(point)
        # use an epsilon of 1um. Even 1mm is pretty small in KSP.
        if d > 1e-6:
            if d > self.height:
                self.height = d
                self.highest = len(self.vispoints)
            self.vispoints.append(point)
            return True
        return False

def dist2(mesh, a, b):
    a = mesh.verts[a]
    b = mesh.verts[b]
    r = sub(b, a)
    return dot(r, r)

def light_faces(faces, first_face, v):
    lit_faces = []
    if first_face:
        lit_faces.append(first_face)
    i = 0
    while i < len(faces):
        lf = faces[i]
        if lf.can_see(v):
            lit_faces.append(lf)
            del faces[i]
            continue
        i += 1
    return lit_faces

def find_outer_edges(faces):
    edges = set()
    for f in faces:
        for i in range(3):
            if f.redges[i] in edges:
                edges.remove(f.redges[i])
            else:
                edges.add(f.edges[i])
    return edges

def get_convex_hull(mesh):
    # min x, y, z and max x, y, z
    points = [0,] * 6
    for i in range(len(mesh.verts)):
        if mesh.verts[i][0] < mesh.verts[points[0]][0]:
            points[0] = i
        if mesh.verts[i][1] < mesh.verts[points[1]][1]:
            points[1] = i
        if mesh.verts[i][2] < mesh.verts[points[2]][2]:
            points[2] = i
        if mesh.verts[i][0] > mesh.verts[points[3]][0]:
            points[3] = i
        if mesh.verts[i][1] > mesh.verts[points[4]][1]:
            points[4] = i
        if mesh.verts[i][2] > mesh.verts[points[5]][2]:
            points[5] = i
    best = (points[0], points[1])
    bestd = dist2(mesh, best[0], best[1])
    for p in points:
        for q in points:
            if q in best:
                continue
            r = dist2(mesh, p, q)
            if r > bestd:
                best = (p, q)
                bestd = r
    a, b = best
    c = None
    bestd = 0
    for p in points:
        if p in (a, b):
            continue
        r = dist2(mesh, a, p) + dist2(mesh, b, p)
        if r > bestd:
            c = p
            bestd = r
    if c in (a, b) or c == None:
        raise
    bestd = 0
    d = None
    tri = Triangle(mesh,a,b,c)
    for p in range(len(mesh.verts)):
        if p in (a, b, c):
            continue
        r = tri.dist(p)
        if r**2 > bestd**2:
            d = p
            bestd = r
    if d in (a, b, c) or d == None:
        raise
    if bestd > 0:
        b,c = c, b
    faces = [Triangle(mesh, a, b, c),
             Triangle(mesh, a, d, b),
             Triangle(mesh, a, c, d),
             Triangle(mesh, c, b, d)]
    for p in range(len(mesh.verts)):
        for f in faces:
            if f.add_point(p):
                break
    final_faces = []
    itter = 0
    while faces:
        f = faces.pop(0)
        if not f.vispoints:
            final_faces.append(f)
            continue
        point = f.vispoints[f.highest]
        lit_faces = light_faces(faces, f, point)
        #light final faces as well so that face merging can be done.
        lit_faces += light_faces(final_faces, None, point)
        horizon_edges = find_outer_edges(lit_faces)
        new_faces = []
        for e in horizon_edges:
            new_faces.append(Triangle(mesh, e[0], e[1], point))
        for lf in lit_faces:
            for p in lf.vispoints:
                for nf in new_faces:
                    if nf.add_point(p):
                        break
        faces.extend(new_faces)
        itter+=1
    return final_faces

def make_mesh(mesh, hull):
    vind = [None] * len(mesh.verts)
    verts = []
    uvs = []
    normals = []
    tris = []
    for f in hull:
        t = [f.edges[0][0], f.edges[1][0], f.edges[2][0]]
        for i in range(3):
            v = t[i]
            if vind[v] == None:
                vind[v] = len(verts)
                verts.append(mesh.verts[v])
                uvs.append(mesh.uvs[v])
                normals.append(mesh.normals[v])
            t[i] = vind[t[i]]
        tris.append(t)
    mumesh = MuMesh()
    mumesh.verts = verts
    mumesh.uvs = uvs
    mumesh.normals = normals
    mumesh.uv2s = uvs
    mumesh.submeshes = [tris]
    return mumesh

def find_colliders(obj, level=0):
    if hasattr(obj, "collider") and isinstance(obj.collider, MuColliderMesh):
        m=obj.collider.mesh
        hull = get_convex_hull (obj.collider.mesh)
        obj.collider.mesh = make_mesh(obj.collider.mesh, hull)
        m=obj.collider.mesh
    for child in obj.children:
        find_colliders(child, level+1)

def main():
    if len(sys.argv) != 3:
        print("hull.py <in-name> <out-name>")
        sys.exit(1)
    fname = sys.argv[1]
    oname = sys.argv[2]
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        sys.exit(1)
    find_colliders(mu.obj)
    mu.write(oname)

main()
