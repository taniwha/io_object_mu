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

import sys
import os
import getopt
import gzip
import time

from binary import BinaryReader
from rawmesh import RawMesh
from quickhull import QuickHull

shortopts = ''
longopts = [
    'dump',
]

options, datafiles = getopt.getopt(sys.argv[1:], shortopts, longopts)

for opt, arg in options:
    if opt == "--dump":
        QuickHull.dump_faces = True

error = False
for df in datafiles:
    if df[-3:] == ".gz":
        f = gzip.open(df, "rb")
    else:
        f = open(df, "rb")
    br= BinaryReader(f)
    mesh = RawMesh()
    mesh.read(br)
    print(f"{df} - {len(mesh.verts)} points")
    br.close()
    qh = QuickHull(mesh)
    start = time.perf_counter()
    hull = qh.GetHull()
    error |= qh.error
    end = time.perf_counter()
    print(f"    - {len(hull)} faces {(end - start) * 1000}ms")
sys.exit(1 if error else 0)
