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

import sys, traceback
from struct import unpack
from pprint import pprint

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, MuMaterial

def texture_update(self, context):
    pass

class MuTextureProperties(bpy.types.PropertyGroup):
    tex = StringProperty(name="tex", update=texture_update)
    type = BoolProperty(name="type", description="Texture is a normal map", default = False)
    scale = FloatVectorProperty(name="scale", size = 2, subtype='XYZ', default = (1.0, 1.0), update=texture_update)
    offset = FloatVectorProperty(name="offset", size = 2, subtype='XYZ', default = (0.0, 0.0), update=texture_update)

class MuMaterialTexturePropertySet(bpy.types.PropertyGroup):
    bl_label = "Textures"
    properties = CollectionProperty(type=MuTextureProperties, name="Textures")
    index = IntProperty()
    expanded = BoolProperty()

    def draw_item(self, layout):
        item = self.properties[self.index]
        row = layout.row()
        col = row.column()
        col.prop(item, "name", "Name")
        r = col.row()
        r.prop(item, "tex", "")
        r.prop(item, "type", "")
        col.prop(item, "scale", "")
        col.prop(item, "offset", "")
