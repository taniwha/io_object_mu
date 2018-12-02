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

from mu import Mu, MuColliderMesh, MuMesh
from quickhull import get_convex_hull
import sys

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

if __name__ == "__main__":
    main()
