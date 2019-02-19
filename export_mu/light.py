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
from math import pi
from mathutils import Quaternion

from ..mu import MuLight
from .. import properties

from . import export

# Blender points spotlights along local -Z, unity along local +Z
# which is Blender's +Y, so rotate -90 degrees around local X to
# go from Blender to Unity
rotation_correction = Quaternion((0.5**0.5, -0.5**0.5, 0, 0))

def make_light(mu, light, obj):
    mulight = MuLight()
    mulight.type = ('SPOT', 'SUN', 'POINT', 'AREA').index(light.type)
    mulight.color = tuple(light.color) + (1.0,)
    mulight.range = light.distance
    mulight.intensity = light.energy
    mulight.spotAngle = 0.0
    mulight.cullingMask = properties.GetPropMask(light.mulightprop.cullingMask)
    if light.type == 'SPOT':
        mulight.spotAngle = light.spot_size * 180 / pi
    return mulight

def handle_light(obj, muobj, mu):
    muobj.light = make_light(mu, obj.data, obj)
    muobj.transform.localRotation @= rotation_correction
    return muobj

type_handlers = {
    bpy.types.PointLight: handle_light,
    bpy.types.SunLight: handle_light,
    bpy.types.SpotLight: handle_light,
    bpy.types.AreaLight: handle_light,
}

light_types = set(type_handlers)
