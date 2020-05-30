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

from .quickhull import QuickHull
from .rawmesh import RawMesh

def make_hull_mesh(mesh, hull):
    vind = [None] * len(mesh.verts)
    verts = []
    faces = []
    for f in hull:
        t = [f.edges[0].a, f.edges[1].a, f.edges[2].a]
        for i in range(3):
            v = t[i]
            if vind[v] == None:
                vind[v] = len(verts)
                verts.append(mesh.verts[v])
            t[i] = vind[t[i]]
        faces.append(t)
    return verts, faces

def quickhull(mesh):
    rawmesh = RawMesh(mesh)
    hull = QuickHull(rawmesh).GetHull()
    verts, faces = make_hull_mesh (rawmesh, hull)
    import bpy
    hullmesh = bpy.data.meshes.new("ConvexHull")
    hullmesh.from_pydata(verts, [], faces)
    hullmesh.update()
    return hullmesh
