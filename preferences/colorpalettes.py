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

def bada55_generate(data):
    """
    Generate a list of colors.

    Args:
        data: (todo): write your description
    """
    colors = []
    for inds in value_indices:
        col = tuple(map(lambda c: color_values[c]/255.0, inds))
        colors.append(col)
    return colors

def parse_color(htmlcolor):
    """
    Parse a rgb color string.

    Args:
        htmlcolor: (str): write your description
    """
    r = int(htmlcolor[0:2], 16)
    g = int(htmlcolor[2:4], 16)
    b = int(htmlcolor[4:6], 16)
    a = 255
    colvals = r, g, b, a
    color = tuple(map(lambda c: c/255.0, colvals))
    return color

def html_generate(data):
    """
    Generate a list.

    Args:
        data: (str): write your description
    """
    colors = []
    for htmlcolor in data:
        col = parse_color (htmlcolor)[:3]
        colors.append(col)
    return colors


def from_srgb(color):
    """
    Convert from rgb color to rgb.

    Args:
        color: (str): write your description
    """
    def convert(c):
        """
        Convert c - b. 0.

        Args:
            c: (todo): write your description
        """
        return ((c + 0.055) / 1.055) ** 2.4
    return tuple(map(lambda c: convert(c), color))

def material_generate(prefix, data):
    """
    Generate material

    Args:
        prefix: (str): write your description
        data: (todo): write your description
    """
    for name, color in data:
        color = from_srgb(parse_color(color))
        name = f"{prefix}:{name}"
        if name in bpy.data.materials:
            mat = bpy.data.materials[name]
            #bpy.data.materials.remove(mat)
        else:
            mat = bpy.data.materials.new(name)
        mat.use_fake_user = True
        mat.diffuse_color = color
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs[0].default_value = color


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

nertea_data = [
	("Antenna Copper", "8C7753"),
	("Argon Blue", "475E74"),
	("Battery Black", "171717"),
	("Battery Yellow", "D9B358"),
	("Capacitor Blue", "5F88AF"),
	("Copper Base", "5D4934"),
	("Cryogenic Blue", "53686F"),
	("Cryogenic Detail Red", "583232"),
	("Gold Foil Base", "856226"),
	("Gold Foil Spec Base", "C7974A"),
	("HS Black Base", "242424"),
	("HS Brown", "856C44"),
	("HS Inner", "9A7054"),
	("HS Red", "8F5949"),
	("Jeb's Yellow", "B18B1B"),
	("KADB red", "784139"),
	("LH2 Albedo Base", "856226"),
	("LH2 Spec Base", "C7974A"),
	("Lithium Red", "AB4032"),
	("Lithium Spec Base", "8C8C8C"),
	("Metal Grey Paint", "424242"),
	("Methane Green", "586F53"),
	("Monoprop Engine Yellow", "B89F54"),
	("Nosecone Tip Grey", "A1A1A1"),
	("Nozzle Ablative", "222222"),
	("Nozzle Metal", "666666"),
	("Nuclear Yellow", "C78C40"),
	("Parachute Orange", "FF4F00"),
	("Payload Stripes", "A9A9A9"),
	("PJ Black", "2D2D2D"),
	("PJ EndTank", "C66F32"),
	("PJ Engine Grey", "5A5A5A"),
	("PJ Grey", "707070"),
	("PJ Light Grey", "787878"),
	("PJ Pipe Grey", "4F4F4F"),
	("PJ Spec Metal Average", "DDDDDD"),
	("PJ Spec Painted", "404040"),
	("PJ White", "C7C7C7"),
	("Probe Core Circuits", "5E8438"),
	("Probe Core Mainboard", "435D28"),
	("Probe Tag Blue", "567987"),
	("Reaction Wheel Control Cable", "B08D43"),
	("Rockomax Orange", "D88342"),
	("Science Blue", "63869A"),
	("Silver Foil Base", "262626"),
	("Silver Foil Spec", "B8B8B8"),
	("SOFI Highlights", "FBC189"),
	("SOFI Orange", "AB6432"),
	("SOFI Yellow", "B1773C"),
	("Solar Cell Adv Base", "272E32"),
	("Solar Cell Adv Spec", "4F565A"),
	("Solar Cell Basic Base", "212C33"),
	("Solar Cell Basic Spec", "505B63"),
	("Solar Cell Blanket Adv Base", "151718"),
	("Solar Cell Conc Base", "2B1515"),
	("Soviet Grey", "494D49"),
	("Soviet Grey Highlight", "AECBAE"),
	("Spec Metal Base", "A6A6A6"),
	("Windows", "496268"),
	("Wire Blue", "333C72"),
	("Wire Red", "723333"),
	("Xenon Tank", "464646"),
	("Xenon Yellow", "CEAC5C"),
]

palette_presets = [
    ("Porkjet", html_generate, porkjet_data),
    ("Stock", html_generate, stock_data),
    ("BDB", html_generate,  bdb_data),
    ("Cormorant", html_generate, cormorant_data),
    ("Tantares", html_generate, tantares_data),
    ("bada55", bada55_generate, None),
    ("General", html_generate, general_data),
    ("Nertea", html_generate, list(zip(*nertea_data))[1]),
]

def install():
    """
    Install a palette. palette.

    Args:
    """
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
    material_generate("Nertea", nertea_data)
