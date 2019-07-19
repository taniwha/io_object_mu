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
from mathutils import Vector, Quaternion

def set_transform(obj, transform):
    obj.rotation_mode = 'QUATERNION'
    if transform:
        obj.location = Vector(transform.localPosition)
        obj.rotation_quaternion = Quaternion(transform.localRotation)
        obj.scale = Vector(transform.localScale)
    else:
        obj.location = Vector((0, 0, 0))
        obj.rotation_quaternion = Quaternion((1,0,0,0))
        obj.scale = Vector((1,1,1))

def create_data_object(name, data, transform):
    obj = bpy.data.objects.new(name, data)
    bpy.context.view_layer.objects.active = obj
    set_transform(obj, transform)
    return obj

