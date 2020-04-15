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
from mathutils import Vector
from bpy.types import PropertyGroup
from bpy.props import BoolProperty, BoolVectorProperty
from bpy.props import CollectionProperty
from bpy.props import EnumProperty
from bpy.props import FloatProperty, FloatVectorProperty
from bpy.props import IntProperty, IntVectorProperty
from bpy.props import PointerProperty
from bpy.props import StringProperty

class KSPProperty(PropertyGroup):
    bl_label = "ksp_property"
    property: StringProperty()
    type: StringProperty()
    description: StringProperty()

class KSPBool(PropertyGroup):
    bl_label = "bool"
    value: BoolProperty()

class KSPFloat(PropertyGroup):
    bl_label = "float"
    value: FloatProperty()

class KSPInt(PropertyGroup):
    bl_label = "int"
    value: IntProperty()

class KSPString(PropertyGroup):
    bl_label = "string"
    value: StringProperty()

class KSPVector(PropertyGroup):
    bl_label = "vector"
    value: FloatVectorProperty(subtype = 'XYZ')

class KSPPointer(PropertyGroup):
    bl_label = "pointer"
    value: PointerProperty(type=bpy.types.Object)

class KSPModuleProps(PropertyGroup):
    bl_label = "Module"
    name: StringProperty()
    fields: CollectionProperty(type=KSPProperty)
    index:IntProperty()
    expanded: BoolProperty(default=True)
    boolProperties: CollectionProperty(type=KSPBool)
    floatProperties: CollectionProperty(type=KSPFloat)
    intProperties: CollectionProperty(type=KSPInt)
    stringProperties: CollectionProperty(type=KSPString)
    vectorProperties: CollectionProperty(type=KSPVector)
    pointerProperties: CollectionProperty(type=KSPPointer)

    def initialize(self, module):
        self.module = module
        self.name = module.name
        for f in module.fields:
            field = self.fields.add()
            field.name = f.name
            field.property = f.property()
            field.description = f.description
            field.type = f.type
            prop = getattr(self, f.property()).add()
            prop.name = f.name
            prop.value = f.default
            prop.type = f.type
            prop.description = f.description

    def draw_item(self, layout):
        field = self.fields[self.index]
        row = layout.row()
        col = row.column()
        prop = getattr(self, field.property)[field.name]
        col.prop(prop, "value", text=field.name)

class KSPModuleSet(PropertyGroup):
    bl_label = "Modules"
    modules: CollectionProperty(type=KSPModuleProps, name="Modules")
    index: IntProperty()
    expanded: BoolProperty()

classes_to_register = (
    KSPProperty,
    KSPBool,
    KSPFloat,
    KSPInt,
    KSPString,
    KSPVector,
    KSPPointer,
    KSPModuleProps,
    KSPModuleSet,
)
custom_properties_to_register = (
    (bpy.types.Object, "kspmodules", KSPModuleSet),
)
