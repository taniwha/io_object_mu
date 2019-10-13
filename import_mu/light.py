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

from math import pi

import bpy
from mathutils import Quaternion

from .. import properties
from ..mu import MuLight

def create_light(mu, muobj, mulight, name):
    ltype = ('SPOT', 'SUN', 'POINT', 'AREA')[mulight.type]
    light = bpy.data.lights.new(name, ltype)
    light.color = mulight.color[:3]
    light.use_custom_distance = True
    light.cutoff_distance = mulight.range
    light.energy = mulight.intensity
    if ltype == 'SPOT' and hasattr(mulight, "spotAngle"):
        light.spot_size = mulight.spotAngle * pi / 180
    muprops = light.mulightprop
    properties.SetPropMask(muprops.cullingMask, mulight.cullingMask)
    return "light", light, Quaternion((0.5**0.5, 0.5**0.5, 0, 0))

type_handlers = {
    MuLight: create_light,
}
