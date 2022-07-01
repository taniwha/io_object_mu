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

import math
import bpy
from mathutils import Vector
from bpy.utils import register_class, unregister_class
from bpy.types import PropertyGroup
from bpy.props import BoolProperty, BoolVectorProperty
from bpy.props import CollectionProperty
from bpy.props import EnumProperty
from bpy.props import FloatProperty, FloatVectorProperty
from bpy.props import IntProperty, IntVectorProperty
from bpy.props import PointerProperty
from bpy.props import StringProperty

from .module import available_modules_map

module_active_field = {}

class KSPProperty(PropertyGroup):
    bl_label = "ksp_property"
    module: StringProperty()
    property: StringProperty()
    type: StringProperty()
    description: StringProperty()

class KSPPropertyRef(PropertyGroup):
    bl_label = "ksp_property_ref"
    module_index: IntProperty()
    field: StringProperty()

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

field_type_map = {
    "bool": BoolProperty,
    "float": FloatProperty,
    "enum": EnumProperty,
    "int": IntProperty,
    "Vector3": FloatVectorProperty,
    "string": StringProperty,
    "transform": PointerProperty,
    "FloatCurve": PointerProperty,
}

def generate_property(field):
    print(field.module, field.name)
    basefield = available_modules_map[field.module].field_map[field.name]
    prop_type = field_type_map[field.type]
    params = {}
    params["name"] = basefield.name
    if field.type == "enum":
        params["items"] = basefield.items
    elif field.type == "float":
        if basefield.min != None:
            params["min"] = basefield.min
        else:
            params["min"] = -math.inf
        if basefield.max != None:
            params["max"] = basefield.max
        else:
            params["max"] = math.inf
    elif field.type == "Vector3":
        params["size"] = 3
    elif field.type in ["transform", "FloatCurve"]:
        params["type"] = bpy.types.Object
    return prop_type, params

def update_field(self, context):
    ref = self.propref
    kspmodules = context.active_object.kspmodules
    module = None
    field = None
    if len(kspmodules.modules) > ref.module_index >= 0:
        module = kspmodules.modules[ref.module_index]
        if ref.field in module.fields:
            field = module.fields[ref.field]
    if module and field:
        prop = getattr(module, field.property)[field.name]
        prop.value = self.value

class KSPActiveField:
    def __init__(self, module, field, mod_index, fld_index):
        self.module = module
        self.prop_type = None
        self.name = f"{module.name}.KSPActiveField.PropType"
        self.set_field(field, mod_index, fld_index)
    def __del__(self):
        print("KSPActiveField __del__")
        if self.prop_type:
            delattr(KSPModuleProps, self.af_name)
            unregister_class(self.prop_type)
    def set_field(self, field, module_index, field_index):
        self.af_name = f"active_field{module_index}"
        if self.prop_type:
            delattr(KSPModuleProps, self.af_name)
            unregister_class(self.prop_type)
        if not field:
            return
        self.field_index = field_index
        proptype, params = generate_property(field)
        params["update"] = update_field
        refptr = PointerProperty(type=KSPPropertyRef)
        annotations = {"value": proptype(**params), "propref":refptr}
        propdict = {"__annotations__": annotations, "bl_label": self.name}
        self.prop_type = type(self.name, (PropertyGroup,), propdict)
        register_class(self.prop_type)
        ptr = PointerProperty(type=self.prop_type)
        setattr(KSPModuleProps, self.af_name, ptr)
        prop = getattr(self.module, field.property)[field.name]
        active_field = getattr(self.module, self.af_name)
        active_field.propref.module_index = module_index
        active_field.propref.field = field.name
        active_field.value = prop.value

class KSPModuleProps(PropertyGroup):
    bl_label = "Module"
    module_index:IntProperty()
    name: StringProperty()
    fields: CollectionProperty(type=KSPProperty)
    index:IntProperty(update=lambda self, ctx: self.update_active_field(ctx))
    expanded: BoolProperty(default=True)
    boolProperties: CollectionProperty(type=KSPBool)
    floatProperties: CollectionProperty(type=KSPFloat)
    intProperties: CollectionProperty(type=KSPInt)
    stringProperties: CollectionProperty(type=KSPString)
    vectorProperties: CollectionProperty(type=KSPVector)
    pointerProperties: CollectionProperty(type=KSPPointer)

    def initialize(self, module, module_index):
        self.module_index = module_index
        self.name = module.name
        for f in module.fields:
            field = self.fields.add()
            field.name = f.name
            field.module = module.name
            field.property = f.property()
            field.description = f.description
            field.type = f.type
            prop = getattr(self, f.property()).add()
            prop.name = f.name
            prop.value = f.default
            prop.type = f.type
            prop.description = f.description
        self.update_active_field(bpy.context)

    def update_active_field(self, context):
        active_object = bpy.context.active_object
        #FIXME this is a horrible way of keeping track of the active object
        if ("active_object" in module_active_field
            and module_active_field["active_object"] != active_object.name):
            module_active_field.clear()
        module_active_field["active_object"] = active_object.name
        field = self.fields[self.index]
        if self.module_index not in module_active_field:
            af = KSPActiveField(self, field, self.module_index, self.index)
            module_active_field[self.module_index] = af
        elif module_active_field[self.module_index].field_index != self.index:
            af = module_active_field[self.module_index]
            af.set_field(field, self.module_index, self.index)

    def draw_item(self, layout):
        field = self.fields[self.index]
        row = layout.row()
        col = row.column()
        active_field = getattr(self, f"active_field{self.module_index}")
        col.prop(active_field, "value", text=field.name)

class KSPModuleSet(PropertyGroup):
    bl_label = "Modules"
    modules: CollectionProperty(type=KSPModuleProps, name="Modules")
    index: IntProperty()
    expanded: BoolProperty()

classes_to_register = (
    KSPProperty,
    KSPPropertyRef,
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
