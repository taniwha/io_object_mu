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

class RawMesh:
    def __init__(self, mesh=None):
        """
        Initialize a mesh.

        Args:
            self: (todo): write your description
            mesh: (todo): write your description
        """
        if mesh:
            if hasattr(mesh, "vertices"):
                self.verts = [v.co for v in mesh.vertices]
            else:
                self.verts = [v for v in mesh.verts]
        else:
            self.verts = []

    def write(self, bw):
        """
        Writes a bw to the screen.

        Args:
            self: (todo): write your description
            bw: (todo): write your description
        """
        bw.write_int(len(self.verts))
        for v in self.verts:
            bw.write_float(v)

    def read(self, br):
        """
        Reads the number of bits.

        Args:
            self: (todo): write your description
            br: (todo): write your description
        """
        count = br.read_int()
        self.verts = [None] * count
        for i in range(count):
            self.verts[i] = br.read_float(3)
