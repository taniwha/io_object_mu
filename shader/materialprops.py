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
from bpy.props import StringProperty
from bpy.props import PointerProperty

from .colorprops import  MuMaterialColorPropertySet
from .float2props import MuMaterialFloat2PropertySet
from .float3props import MuMaterialFloat3PropertySet
from .textureprops import MuMaterialTexturePropertySet
from .vectorprops import MuMaterialVectorPropertySet

class MuMaterialProperties(bpy.types.PropertyGroup):
    name: StringProperty(name="Name")
    shaderName: StringProperty(name="Shader")
    color: PointerProperty(type = MuMaterialColorPropertySet)
    vector: PointerProperty(type = MuMaterialVectorPropertySet)
    float2: PointerProperty(type = MuMaterialFloat2PropertySet)
    float3: PointerProperty(type = MuMaterialFloat3PropertySet)
    texture: PointerProperty(type = MuMaterialTexturePropertySet)

classes = (
    MuMaterialProperties,
)
custom_properties = (
    (bpy.types.Material, "mumatprop", MuMaterialProperties),
)
