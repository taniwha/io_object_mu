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

from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuColliderBox, MuColliderWheel

def create_uvs(mu, uvs, mesh, name):
    uvlay = mesh.uv_textures.new(name)
    uvloop = mesh.uv_layers[name]
    for i, uvl in enumerate(uvloop.data):
        v = mesh.loops[i].vertex_index
        uvl.uv = uvs[v]

def create_mesh(mu, mumesh, name):
    mesh = bpy.data.meshes.new(name)
    faces = []
    for sm in mumesh.submeshes:
        faces.extend(sm)
    mesh.from_pydata(mumesh.verts, [], faces)
    if mumesh.uvs:
        create_uvs(mu, mumesh.uvs, mesh, name + ".UV")
    if mumesh.uv2s:
        create_uvs(mu, mumesh.uv2s, mesh, name + ".UV2")
    return mesh

def create_mesh_object(name, mesh, transform):
    obj = bpy.data.objects.new(name, mesh)
    obj.rotation_mode = 'QUATERNION'
    obj.location = Vector(transform.localPosition)
    obj.rotation_quaternion = Quaternion(transform.localRotation)
    obj.scale = Vector(transform.localScale)
    bpy.context.scene.objects.link(obj)
    bpy.context.scene.objects.active = obj
    obj.select = True
    return obj

def create_object(mu, muobj, parent):
    obj = None
    if hasattr(muobj, "collider"):
        if type(muobj.collider) == MuColliderMesh:
            name = muobj.transform.name + ".collider"
            mesh = create_mesh(mu, muobj.collider.mesh, name)
            obj = create_mesh_object(name, mesh, muobj.transform)
            obj.parent = parent
        elif type(muobj.collider) == MuColliderSphere:
            print("sphere")
        elif type(muobj.collider) == MuColliderCapsule:
            print("capsule")
        elif type(muobj.collider) == MuColliderBox:
            print("box")
        elif type(muobj.collider) == MuColliderWheel:
            print("wheel")
    if hasattr(muobj, "renderer"):
        #FIXME renderer settings
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
