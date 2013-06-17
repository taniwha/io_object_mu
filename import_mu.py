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
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, Mu

def create_mesh(mu, mumesh, name):
    mesh = bpy.data.meshes.new(name)
    faces = []
    for sm in mumesh.submeshes:
        faces.extend(sm)
    mesh.from_pydata(mumesh.verts, [], faces)
    return mesh

def create_mesh_object(name, mesh, transform):
    obj = bpy.data.objects.new(name, mesh)
    obj.rotation_mode = 'QUATERNION'
    obj.location = Vector(transform.localPosition)
    #obj.rotation_quaternion = Quaternion(transform.localRotation)
    obj.rotation_quaternion = Quaternion(((transform.localRotation[3],) + transform.localRotation[0:3]))
    obj.scale = Vector(transform.localScale)
    bpy.context.scene.objects.link(obj)
    bpy.context.scene.objects.active = obj
    obj.select = True
    return obj

def create_object(mu, muobj, parent):
    obj = None
    if hasattr(muobj, "collider"):
        pass
    if hasattr(muobj, "renderer"):
        pass
    if hasattr(muobj, "shared_mesh"):
        mesh = create_mesh(mu, muobj.shared_mesh, muobj.transform.name)
        obj = create_mesh_object(muobj.transform.name, mesh, muobj.transform)
    if not obj:
        obj = create_mesh_object(muobj.transform.name, None, muobj.transform)
    obj.parent = parent
    for child in muobj.children:
        create_object(mu, child, obj)

def import_mu(operator, context, filepath):
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    mu = Mu()
    if not mu.read(filepath):
        operator.report({'ERROR'},
            "Unrecognized format: %s %d" % (mu.magic, mu.version))
        return {'CANCELLED'}

    create_object(mu, mu.obj, None)

    bpy.context.user_preferences.edit.use_global_undo = True
    return {'FINISHED'}
