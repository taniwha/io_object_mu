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

from ..mu import MuMesh, MuSkinnedMeshRenderer
from ..utils import create_data_object

from .armature import create_vertex_groups, create_armature_modifier

def attach_material(mesh, renderer, mu):
    if mu.materials and renderer.materials:
        #KSP supports only the first submesh and thus only the first
        #material
        mumat = mu.materials[renderer.materials[0]]
        mesh.materials.append(mumat.material)

def create_uvs(mu, uvs, mesh, name):
    uv_layer = mesh.uv_layers.new(name=name).data
    for i, loop in enumerate(mesh.loops):
        uv_layer[i].uv = uvs[loop.vertex_index]

def create_normals(mu, normals, mesh):
    custom_normals = [None] * len(mesh.loops)
    for i, loop in enumerate(mesh.loops):
        custom_normals[i] = normals[loop.vertex_index]
    mesh.normals_split_custom_set(custom_normals)
    mesh.use_auto_smooth = True

def create_mesh(mu, mumesh, name):
    mesh = bpy.data.meshes.new(name)
    faces = []
    for sm in mumesh.submeshes:
        faces.extend(sm)
    mesh.from_pydata(mumesh.verts, [], faces)
    if mumesh.uvs:
        create_uvs(mu, mumesh.uvs, mesh, "UV")
    if mumesh.uv2s:
        create_uvs(mu, mumesh.uv2s, mesh, "UV2")
    if mumesh.normals:
        create_normals(mu, mumesh.normals, mesh)
    #FIXME how to set tangents?
    #if mumesh.tangents:
    #    for i, t in enumerate(mumesh.tangents):
    #        bv[i].tangent = t
    return mesh

def mesh_post(obj, renderer):
    obj.muproperties.castShadows = renderer.castShadows
    obj.muproperties.receiveShadows = renderer.receiveShadows

def create_mesh_component(mu, muobj, mumesh, name):
    if not mu.force_mesh and not hasattr(muobj, "renderer"):
        return None
    mesh = create_mesh (mu, mumesh, name)
    for poly in mesh.polygons:
        poly.use_smooth = True
    if hasattr(muobj, "renderer"):
        attach_material(mesh, muobj.renderer, mu)
    return "mesh", mesh, None, (mesh_post, muobj.renderer)

def create_skinned_mesh_component(mu, muobj, skin, name):
    mesh = create_mesh(mu, skin.mesh, name)
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = create_data_object(mu.collection, name + ".skin", mesh, None)
    create_vertex_groups(obj, skin.bones, skin.mesh.boneWeights)
    attach_material(mesh, skin, mu)
    obj.parent = muobj.armature_obj
    create_armature_modifier(obj, muobj)
    return "armature", muobj.armature_obj, None

type_handlers = {
    MuMesh: create_mesh_component,
    MuSkinnedMeshRenderer: create_skinned_mesh_component
}
