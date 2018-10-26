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

from ..mu import MuCamera

# Blender points camera along local -Z, unity along local +Z
# which is Blender's +Y, so rotate -90 degrees around local X to
# go from Blender to Unity
rotation_correction = Quaternion((0.5**0.5, -0.5**0.5, 0, 0))

def make_camera(mu, camera, obj):
    mucamera = MuCamera()
    clear = obj.muproperties.clearFlags
    flags = ('SKYBOX', 'COLOR', 'DEPTH', 'NOTHING').index(clear)
    mucamera.clearFlags = flags + 1
    mucamera.backgroundColor = obj.muproperties.backgroundColor
    mucamera.cullingMask = properties.GetPropMask(obj.muproperties.cullingMask)
    mucamera.orthographic = camera.type == 'ORTHO'
    mucamera.fov = camera.angle * 180 / pi
    mucamera.near = camera.clip_start
    mucamera.far = camera.clip_end
    mucamera.depth = obj.muproperties.depth
    return mucamera

def handle_camera(obj, muobj, mu):
    muobj.camera = make_camera(mu, obj.data, obj)
    muobj.transform.localRotation @= rotation_correction
    return muobj

type_handlers = {
    bpy.types.Camera: handle_camera,
}
