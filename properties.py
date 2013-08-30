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
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum

class MuProperties(bpy.types.PropertyGroup):
    tag = StringProperty(name = "Tag")
    layer = IntProperty(name = "Layer")

class MuPropertiesPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_label = 'Mu Properties'

    @classmethod
    def poll(cls, context):
            return True

    def draw(self, context):
        layout = self.layout
        muprops = context.active_object.muproperties
        row = layout.row()
        row.prop(muprops, "tag")
        row = layout.row()
        row.prop(muprops, "layer")

def register():
    bpy.types.Object.muproperties = PointerProperty(type=MuProperties)
