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

from ..mu import MuColliderMesh, MuColliderSphere, MuColliderCapsule
from ..mu import MuColliderBox, MuColliderWheel
from .. import collider, properties

from .mesh import create_mesh

def copy_spring(dst, src):
    dst.spring = src.spring
    dst.damper = src.damper
    dst.targetPosition = src.targetPosition

def copy_friction(dst, src):
    dst.extremumSlip = src.extremumSlip
    dst.extremumValue = src.extremumValue
    dst.asymptoteSlip = src.asymptoteSlip
    dst.extremumValue = src.extremumValue
    dst.stiffness = src.stiffness

def create_collider(mu, muobj, col, name):
    if not mu.create_colliders:
        return None
    mesh = None
    if type(col) == MuColliderMesh:
        name = name + "∧collider"
        mesh = create_mesh(mu, col.mesh, name)
    obj, cobj = collider.create_collider_object(name, mesh)

    obj.muproperties.isTrigger = False
    # if the collider is the only component on the game object, then make
    # sure it is kept separate when exporting
    # FIXME animated colliders? (does anybody do that?)
    obj.muproperties.separate = len(muobj.components) == 1
    if type(col) != MuColliderWheel:
        obj.muproperties.isTrigger = col.isTrigger
    if type(col) == MuColliderMesh:
        obj.muproperties.collider = 'MU_COL_MESH'
        obj.muproperties.isConvex = col.convex
    elif type(col) == MuColliderSphere:
        obj.muproperties.radius = col.radius
        obj.muproperties.center = col.center
        obj.muproperties.collider = 'MU_COL_SPHERE'
    elif type(col) == MuColliderCapsule:
        obj.muproperties.radius = col.radius
        obj.muproperties.height = col.height
        obj.muproperties.direction = properties.dir_map[col.direction]
        obj.muproperties.center = col.center
        obj.muproperties.collider = 'MU_COL_CAPSULE'
    elif type(col) == MuColliderBox:
        obj.muproperties.size = col.size
        obj.muproperties.center = col.center
        obj.muproperties.collider = 'MU_COL_BOX'
    elif type(col) == MuColliderWheel:
        obj.muproperties.radius = col.radius
        obj.muproperties.suspensionDistance = col.suspensionDistance
        obj.muproperties.center = col.center
        obj.muproperties.mass = col.mass
        copy_spring(obj.muproperties.suspensionSpring, col.suspensionSpring)
        copy_friction(obj.muproperties.forwardFriction, col.forwardFriction)
        copy_friction(obj.muproperties.sideFriction, col.sidewaysFriction)
        obj.muproperties.collider = 'MU_COL_WHEEL'
    if type(col) != MuColliderMesh:
        collider.build_collider(cobj, obj.muproperties)
    return "collider", obj, None

type_handlers = {
    MuColliderWheel: create_collider,
    MuColliderMesh: create_collider,
    MuColliderBox: create_collider,
    MuColliderCapsule: create_collider,
    MuColliderSphere: create_collider,
}
