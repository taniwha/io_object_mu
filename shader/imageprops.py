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
from mathutils import Vector
from bpy.props import BoolProperty, StringProperty
from bpy.props import CollectionProperty
from bpy.props import FloatVectorProperty, IntProperty

from .shader import call_update

def image_update_flags(self, context):
    class Context:
        pass
    if not hasattr(context, "edit_image"):
        return
    ctx = Context()
    name = context.edit_image.name
    for mat in bpy.data.materials:
        ctx.material = mat
        for tex in mat.mumatprop.texture.properties:
            if name == tex.tex:
                call_update(tex, "rgbNorm", ctx)

class MuImageProperties(bpy.types.PropertyGroup):
    invertY: BoolProperty(name="invertY", description="Invert Y-axis (for dds images). Affects only shaders, not the image editor.", default = False, update=image_update_flags)
    convertNorm: BoolProperty(name="convertNorm", description="Convert GA normal map to RGB. Affects only shaders, not the image editor.", default = False, update=image_update_flags)

class IMAGE_PT_MuImagePanel(bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_label = 'Mu Image'

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd and sd.image

    def draw(self, context):
        layout = self.layout
        imageprops = context.space_data.image.muimageprop
        row = layout.row()
        col = row.column()
        r = col.row(align=True)
        col.prop(imageprops, "invertY")
        col.prop(imageprops, "convertNorm")

classes_to_register = (
    MuImageProperties,
    IMAGE_PT_MuImagePanel
)
custom_properties_to_register = (
    (bpy.types.Image, "muimageprop", MuImageProperties),
)
