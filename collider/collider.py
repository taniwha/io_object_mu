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
import bmesh
from bpy.props import BoolProperty, FloatProperty, EnumProperty
from bpy.props import FloatVectorProperty
from mathutils import Vector

from .. import properties
from ..utils import strip_nnn, util_collection
from . import box, capsule, sphere, wheel

def collider_collection(name):
    gizmos = util_collection("collider_gizmos")
    cc = bpy.data.collections.new("collider:"+name)
    gizmos.children.link(cc)
    return cc

def make_collider_mesh(mesh, vex_list):
    verts = []
    edges = []
    for vex in vex_list:
        v, e, m = vex
        base = len(verts)
        verts.extend(list(map(lambda x: m @ Vector(x), v)))
        edges.extend(list(map(lambda x: (x[0] + base, x[1] + base), e)))
    bm = bmesh.new()
    bv = [None] * len(verts)
    for i, v in enumerate(verts):
        bv[i] = bm.verts.new (v)
    for e in edges:
        bm.edges.new((bv[e[0]], bv[e[1]]))
    bm.to_mesh(mesh)
    return mesh

def build_collider(obj, muprops):
    mesh = obj.data
    mesh_data = None
    if muprops.collider == "MU_COL_MESH":
        if not len(mesh.vertices):
            mesh_data = box.mesh_data((0, 0, 0), (1, 1, 1))
    elif muprops.collider == "MU_COL_SPHERE":
        mesh_data = sphere.mesh_data(muprops.center, muprops.radius)
    elif muprops.collider == "MU_COL_CAPSULE":
        mesh_data = capsule.mesh_data(muprops.center, muprops.radius, muprops.height, muprops.direction)
    elif muprops.collider == "MU_COL_BOX":
        mesh_data = box.mesh_data(muprops.center, muprops.size)
    elif muprops.collider == "MU_COL_WHEEL":
        mesh_data = wheel.mesh_data(muprops.center, muprops.radius)
    if mesh_data:
        make_collider_mesh (mesh, mesh_data)

def update_collider(obj):
    if not obj:
        return
    muprops = obj.muproperties
    if not muprops.collider or muprops.collider == 'MU_COL_MESH':
        return
    if obj.instance_collection:
        collection = obj.instance_collection
        if collection.users > len(collection.objects) + 1:
            name = strip_nnn(collection.name)
            gizmo, cobj = create_collider_gizmo(name)
            obj.instance_collection = gizmo
        else:
            cobj = obj.instance_collection.objects[0]
        build_collider(cobj, obj.muproperties)

def create_collider_gizmo(name):
    mesh = bpy.data.meshes.new(name)
    cobj = bpy.data.objects.new("mesh:" + name, mesh)
    gizmo = collider_collection (name)
    gizmo.objects.link(cobj)
    return gizmo, cobj

def create_collider_object(name, mesh):
    if mesh:
        cobj = obj = bpy.data.objects.new(name, mesh)
    else:
        gizmo, cobj = create_collider_gizmo(name)
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_size = 0.3
        obj.empty_display_type = 'ARROWS'
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = gizmo
    return obj, cobj
