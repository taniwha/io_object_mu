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

from struct import unpack
import os.path

import bpy
from mathutils import Vector

def load_mbm(mbmpath):
    mbmfile = open(mbmpath, "rb")
    header = mbmfile.read(20)
    magic, width, height, bump, bpp = unpack("<5i", header)
    if magic != 0x50534b03: # "\x03KSP" as little endian
        raise
    if bpp == 32:
        pixels = mbmfile.read(width * height * 4)
    elif bpp == 24:
        pixels = [0, 0, 0, 255] * width * height
        for i in range(width * height):
            p = mbmfile.read(3)
            l = i * 4
            pixels[l:l+3] = list(p)
    else:
        raise
    return width, height, pixels

def load_image(base, ext, path, type):
    name = base + ext
    if ext.lower() in [".dds", ".png", ".tga"]:
        img = bpy.data.images.load(os.path.join(path, name))
        img.name = base
        img.muimageprop.invertY = False
        if ext.lower() == ".dds":
            img.muimageprop.invertY = True
        pixels = img.pixels[:1024]#256 pixels
        if base[-2:].lower() == "_n" or base[-3:].lower() == "nrm":
            type = 1
    elif ext.lower() == ".mbm":
        w,h, pixels = load_mbm(os.path.join(path, name))
        img = bpy.data.images.new(base, w, h)
        img.pixels[:] = map(lambda x: x / 255.0, pixels)
        img.pack(as_png=True)
    img.alpha_mode = 'STRAIGHT'
    img.muimageprop.invertY = (ext.lower() == ".dds")
    img.muimageprop.convertNorm = False
    if type == 1:
        img.colorspace_settings.name = 'Non-Color'
        for i in range(256):
            c = 2*Vector(pixels[i*4:i*4+4])-Vector((1, 1, 1, 1))
            if abs(c.x*c.x + c.y*c.y + c.z*c.z - 1) > 0.05:
                img.muimageprop.convertNorm = True

def create_textures(mu, path):
    extensions = [".dds", ".mbm", ".tga", ".png"]
    #texture info is in the top level object
    for tex in mu.textures:
        base, ext = os.path.splitext(tex.name)
        ind = 0
        if ext in extensions:
            ind = extensions.index(ext)
        lst = extensions[ind:] + extensions[:ind]
        for e in lst:
            try:
                load_image(base, e, path, tex.type)
                break
            except FileNotFoundError:
                continue
            except RuntimeError:
                continue
    pass
