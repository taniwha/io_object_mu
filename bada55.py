# vim:ts=4:et
#  Copyright (C) 2015 Bill Currie <bill@taniwha.org>
#  Date: 2015/12/12
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

import bpy

color_values = (0x55, 0xba, 0xda)
value_indices = (
    (0,0,0), (1,1,1), (2,2,2),

    (1,0,0), (2,0,0),
    (0,1,0), (0,2,0),
    (0,0,1), (0,0,2),

    (2,1,1),
    (1,2,1),
    (1,1,2),

    (0,1,1), (0,2,2),
    (1,0,1), (2,0,2),
    (1,1,0), (2,2,0),

    (1,2,2),
    (2,1,2),
    (2,2,1),

    (0,1,2),
    (0,2,1),
    (1,0,2),
    (2,0,1),
    (2,1,0),
    (1,2,0),
)

pal = bpy.data.palettes.new("bada55")
for i in range(27):
    col = pal.colors.new().color
    inds = value_indices[i]
    cols = tuple(map(lambda c: color_values[c]/255.0, inds))
    col.r, col.g, col.b = cols
