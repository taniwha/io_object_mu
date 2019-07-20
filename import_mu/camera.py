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

from math import pi, sqrt

import bpy
from mathutils import Quaternion

from ..mu import MuCamera
from .. import properties

def create_camera(mu, muobj, mucamera, name):
    camera = bpy.data.cameras.new(name)
    #mucamera.clearFlags
    camera.type = ['PERSP', 'ORTHO'][mucamera.orthographic]
    camera.lens_unit = 'FOV'
    # blender's fov is in radians, unity's in degrees
    camera.angle = mucamera.fov * pi / 180
    camera.clip_start = mucamera.near
    camera.clip_end = mucamera.far
    muprops = camera.mucameraprop
    properties.SetPropMask(muprops.cullingMask, mucamera.cullingMask)
    muprops.backgroundColor = mucamera.backgroundColor
    muprops.depth = mucamera.depth
    if mucamera.clearFlags > 0:
        flags = mucamera.clearFlags - 1
        muprops.clearFlags = properties.clearflag_items[flags][0]
    return "camera", camera, Quaternion((0.5**0.5, 0.5**0.5, 0, 0))

type_handlers = {
    MuCamera: create_camera,
}
