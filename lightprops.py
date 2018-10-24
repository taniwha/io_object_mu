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
from bpy.props import BoolVectorProperty, FloatProperty
from bpy.props import FloatVectorProperty, IntProperty

clearflag_items = (
    ('SKYBOX', "Skybox", ""),
    ('COLOR', "Solid Color", ""),
    ('DEPTH', "Depth", ""),
    ('NOTHING', "Nothing", ""),
)

class MuLightProperties(bpy.types.PropertyGroup):
    cullingMask: BoolVectorProperty(size=32, name = "Culling Mask", subtype = 'LAYER')

class OBJECT_PT_MuLightPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_label = 'Mu Properties'

    @classmethod
    def poll(cls, context):
        if type(context.active_object.data) in [bpy.types.PointLight,
                                                bpy.types.SunLight,
                                                bpy.types.SpotLight,
                                                bpy.types.HemiLight,
                                                bpy.types.AreaLight]:
            return True
        return False

    def draw(self, context):
        layout = self.layout
        muprops = context.active_object.data.mulightprop
        row = layout.row()
        col = row.column()
        col.prop(muprops, "cullingMask")

classes = (
    MuLightProperties,
    OBJECT_PT_MuLightPanel
)
custom_properties = (
    (bpy.types.PointLight, "mulightprop", MuLightProperties),
    (bpy.types.SunLight, "mulightprop", MuLightProperties),
    (bpy.types.SpotLight, "mulightprop", MuLightProperties),
    (bpy.types.HemiLight, "mulightprop", MuLightProperties),
    (bpy.types.AreaLight, "mulightprop", MuLightProperties),
)
