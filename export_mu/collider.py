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

import os

import bpy, bmesh
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion
from pprint import pprint
from math import pi
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty

from ..mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from ..mu import MuObject, MuTransform, MuMesh, MuTagLayer, MuRenderer, MuLight
from ..mu import MuCamera
from ..mu import MuColliderBox, MuColliderWheel, MuMaterial, MuTexture, MuMatTex
from ..mu import MuSpring, MuFriction
from ..mu import MuAnimation, MuClip, MuCurve, MuKey
from ..shader import make_shader
from .. import properties
from ..cfgnode import ConfigNode, ConfigNodeError
from ..parser import parse_node
from ..attachnode import AttachNode
from ..utils import strip_nnn, swapyz, swizzleq, vector_str

from .mesh import make_mesh

def make_spring(spr):
    spring = MuSpring()
    spring.spring = spr.spring
    spring.damper = spr.damper
    spring.targetPosition = spr.targetPosition
    return spring

def make_friction(fric):
    friction = MuFriction()
    friction.extremumSlip = fric.extremumSlip
    friction.extremumValue = fric.extremumValue
    friction.asymptoteSlip = fric.asymptoteSlip
    friction.asymptoteValue = fric.asymptoteValue
    friction.stiffness = fric.stiffness
    return friction

def make_collider(mu, obj):
    if (obj.muproperties.collider == 'MU_COL_MESH' and obj.data
        and type (obj.data) == bpy.types.Mesh):
        col = MuColliderMesh(True)
        col.isTrigger = obj.muproperties.isTrigger
        col.convex = True #FIXME calculate
        col.mesh = make_mesh (mu, obj)
    elif obj.muproperties.collider == 'MU_COL_SPHERE':
        col = MuColliderSphere(True)
        col.isTrigger = obj.muproperties.isTrigger
        col.radius = obj.muproperties.radius
        col.center = obj.muproperties.center
    elif obj.muproperties.collider == 'MU_COL_CAPSULE':
        col = MuColliderCapsule(True)
        col.isTrigger = obj.muproperties.isTrigger
        col.radius = obj.muproperties.radius
        col.height = obj.muproperties.height
        col.direction = obj.muproperties.direction
        if type(col.direction) is not int:
            col.direction = properties.dir_map[col.direction]
        col.center = obj.muproperties.center
    elif obj.muproperties.collider == 'MU_COL_BOX':
        col = MuColliderBox(True)
        col.isTrigger = obj.muproperties.isTrigger
        col.size = obj.muproperties.size
        col.center = obj.muproperties.center
    elif obj.muproperties.collider == 'MU_COL_WHEEL':
        col = MuColliderWheel()
        col.isTrigger = obj.muproperties.isTrigger
        col.mass = obj.muproperties.mass
        col.radius = obj.muproperties.radius
        col.suspensionDistance = obj.muproperties.suspensionDistance
        col.center = obj.muproperties.center
        col.suspensionSpring = make_spring(obj.muproperties.suspensionSpring)
        col.forwardFriction = make_friction(obj.muproperties.forwardFriction)
        col.sidewaysFriction = make_friction(obj.muproperties.sideFriction)
    return col
