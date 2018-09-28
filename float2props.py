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
from bpy.props import BoolProperty, FloatProperty
from bpy.props import CollectionProperty
from bpy.props import IntProperty

def float2_update(self, context):
    pass

class MuFloat2Prop(bpy.types.PropertyGroup):
    value: FloatProperty(name="", update=float2_update)

class MuMaterialFloat2PropertySet(bpy.types.PropertyGroup):
    bl_label: "Float2"
    properties: CollectionProperty(type=MuFloat2Prop, name="Float2")
    index: IntProperty()
    expanded: BoolProperty()

    def draw_item(self, layout):
        item = self.properties[self.index]
        row = layout.row()
        col = row.column()
        col.prop(item, "name", "Name")
        col.prop(item, "value", "")

classes = (
    MuFloat2Prop,
    MuMaterialFloat2PropertySet,
)
