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
from .shaderprops import mu_shader_prop_add, mu_shader_prop_remove

class MuShaderVectorPropAdd(bpy.types.Operator):
    '''Add a mu shader vector property name/value pair'''
    bl_idname = "object.mushaderprop_add_vector"
    bl_label = "Mu shader vector prop Add"
    def execute(self, context):
        matprops = context.material.mumatprop
        return mu_shader_prop_add(self, context, matprops.vectorProps)

class MuShaderVectorPropRemove(bpy.types.Operator):
    '''Remove a mu shader vector property name/value pair'''
    bl_idname = "object.mushaderprop_remove_vector"
    bl_label = "Mu shader vector prop Remove"
    def execute(self, context):
        matprops = context.material.mumatprop
        return mu_shader_prop_remove(self, context, matprops.vectorProps, matprops.vectorProp_idx)
