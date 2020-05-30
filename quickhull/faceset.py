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

class FaceSet:
    def __init__(self, mesh):
        self.mesh = mesh
        self.faces = set()

    def __len__(self):
        return len(self.faces)

    def __iter__(self):
        return self.faces.__iter__()

    def __contains__(self, face):
        return face in faces

    def add(self, face):
        face.pull()
        face.push(self)
        self.faces.add(face)

    def update(self, newFaces):
        for face in newFaces:
            face.pull()
            self.faces.add(face)

    def pop(self):
        face = self.faces.pop()
        face.faceset = None
        return face

    def find_outer_edges(self):
        edges = set()
        for f in self.faces:
            for i in range(3):
                if f.redges[i] in edges:
                    edges.remove(f.redges[i])
                else:
                    edges.add(f.edges[i])
        return edges

    def write(self, bw):
        bw.write_int(len(self.faces))
        for f in self.faces:
            f.write(bw)
