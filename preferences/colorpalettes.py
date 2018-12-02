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

def bada55_generate (data):
    colors = []
    for inds in value_indices:
        col = tuple(map(lambda c: color_values[c]/255.0, inds))
        colors.append(col)
    return colors

def html_generate (data):
    colors = []
    for htmlcolor in data:
        r = int(htmlcolor[0:2], 16)
        g = int(htmlcolor[2:4], 16)
        b = int(htmlcolor[4:6], 16)
        colvals = r, g, b
        col = tuple(map(lambda c: c/255.0, colvals))
        colors.append(col)
    return colors

porkjet_data = [
    "b8b9b8", "919191", "c5c5c5", "333333",
    "5b5b5b", "666666", "979897", "161616",
    "5d7682", "ececec",
]

stock_data = [
    "c19915", "745b22", "9b5726", "8b582b",
    "7f461b", "3c464f", "2f4251", "b1c272",
]

bdb_data = [
    "8c8c8c",
]

cormorant_data = [
    "b07b3c", "bca26e", "8b7f67",
]

tantares_data = [
    "bf774e", "a6673a", "bf9e60", "a68953",
    "8c7446", "a68074", "95a67c", "7e8c69",
    "5c9994", "4d807b",
    "404040", "595959", "737373", "8c8c8c",
    "a6a6a6", "bfbfbf", "d9d9d9",
]

general_data = [
    "ffffff", "f2f2f2", "e5e5e5", "d8d8d8",
    "cccccc", "bfbfbf", "b2b2b2", "a5a5a5",
    "999999", "8c8c8c", "7f7f7f", "727272",
    "666666", "595959", "4c4c4c", "3f3f3f",
    "333333", "262626", "191919", "0c0c0c",
]

palette_presets = [
    ("Porkjet", html_generate, porkjet_data),
    ("Stock", html_generate, stock_data),
    ("BDB", html_generate,  bdb_data),
    ("Cormorant", html_generate, cormorant_data),
    ("Tantares", html_generate, tantares_data),
    ("bada55", bada55_generate, None),
    ("General", html_generate, general_data),
]

def install():
    for palette in palette_presets:
        name, generate, data = palette
        colors = generate(data)
        if name in bpy.data.palettes:
            pal = bpy.data.palettes[name]
        else:
            pal = bpy.data.palettes.new(name)
        for c in colors:
            col = pal.colors.new().color
            col.r, col.g, col.b = c
