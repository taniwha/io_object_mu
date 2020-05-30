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
    from .faceset import FaceSet
except ImportError:
    from faceset import FaceSet

class Connectivity:
    def __init__(self, faces):
        self.error = False
        self.edgeFaces = {}
        self.light_run = 0
        for f in faces:
            self.add(f)

    def __len__(self):
        return len(self.edgeFaces)

    def __getitem__(self, e):
        if e in self.edgeFaces:
            return self.edgeFaces[e]
        return None

    def add(self, face):
        for i in range(3):
            e = face.edges[i]
            if e in self.edgeFaces:
                print(f"[Connectivity] duplicate edge")
                self.error = True
            else:
                self.edgeFaces[e] = face

    def remove(self, face):
        if type(face) == FaceSet:
            for f in face:
                self.remove(f)
        else:
            for i in range(3):
                del self.edgeFaces[face.edges[i]]

    def light_faces_int(self, face, point, lit_faces):
        if face.light_run == self.light_run:
            return
        face.light_run = self.light_run
        if face.can_see(point):
            lit_faces.add(face)
            for i in range(3):
                conface = self[face.redges[i]]
                if not conface:
                    print(f"[Connectivity] incompletely connected face")
                    continue
                self.light_faces_int(conface, point, lit_faces)

    def light_faces(self, first_face, point):
        lit_faces = FaceSet(first_face.mesh)
        lit_faces.add(first_face)
        self.light_run += 1
        self.light_faces_int(first_face, point, lit_faces)
        return lit_faces
