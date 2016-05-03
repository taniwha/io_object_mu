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

class MuShaderPropExpand(bpy.types.Operator):
    '''Expand/collapse mu shader property set'''
    bl_idname = "object.mushaderprop_expand"
    bl_label = "Mu shader prop expand"
    propertyset = StringProperty()
    def execute(self, context):
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        propset.expanded = not propset.expanded
        return {'FINISHED'}


class MuShaderPropAdd(bpy.types.Operator):
    '''Add a mu shader property'''
    bl_idname = "object.mushaderprop_add"
    bl_label = "Mu shader prop Add"
    propertyset = StringProperty()
    def execute(self, context):
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        propset.properties.add()
        return {'FINISHED'}

class MuShaderPropRemove(bpy.types.Operator):
    '''Remove a mu shader property'''
    bl_idname = "object.mushaderprop_remove"
    bl_label = "Mu shader prop Remove"
    propertyset = StringProperty()
    def execute(self, context):
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        if propset.index >= 0:
            propset.properties.remove(propset.index)
        return {'FINISHED'}
