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
from .armature import create_bindPose

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
    if hasattr(mesh, "use_auto_smooth"):
        # From blender 4.1 release notes:
        #  use_auto_smooth is removed. Face corner normals are now used
        #  automatically if there are mixed smooth vs. not smooth tags.
        #  Meshes now always use custom normals if they exist.
        mesh.use_auto_smooth = True

def create_colors(mu, colors, mesh):
    if not mesh.color_attributes:
        name = "colors" if colors else "∧default"
        mesh.color_attributes.new(name, 'FLOAT_COLOR', 'POINT')
    color_layer = mesh.color_attributes.active_color
    if colors:
        for i, c in enumerate(colors):
            color_layer.data[i].color = c
    else:
        for i in range(len(color_layer.data)):
            color_layer.data[i].color = (1,1,1,1)

def create_mesh(mu, mumesh, name):
    mesh = bpy.data.meshes.new(name)
    faces = []
    for sm in mumesh.submeshes:
        faces.extend(sm)
    mesh.from_pydata(mumesh.verts, [], faces)
    if mumesh.uvs:
        create_uvs(mu, mumesh.uvs, mesh, "UVMap")
    if mumesh.uv2s:
        create_uvs(mu, mumesh.uv2s, mesh, "UVMap2")
    if mumesh.normals:
        create_normals(mu, mumesh.normals, mesh)
    create_colors(mu, mumesh.colors, mesh)
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
    if hasattr(muobj, "renderer"):
        attach_material(mesh, muobj.renderer, mu)
        return "mesh", mesh, None, (mesh_post, muobj.renderer)
    else:
        return "mesh", mesh, None

def create_skinned_mesh_component(mu, muobj, skin, name):
    create_bindPose(mu, muobj, skin)
    mesh = create_mesh(mu, skin.mesh, name)
    obj = create_data_object(mu.collection, name + ".skin", mesh, None)
    create_vertex_groups(obj, skin.bones, skin.mesh.boneWeights)
    attach_material(mesh, skin, mu)
    obj.parent = skin.bindPose_obj
    create_armature_modifier(obj, "BindPose", skin.bindPose_obj)
    return "armature", skin.bindPose_obj, None
    #return None

type_handlers = {
    MuMesh: create_mesh_component,
    MuSkinnedMeshRenderer: create_skinned_mesh_component
}
