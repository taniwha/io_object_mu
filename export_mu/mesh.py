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
from mathutils import Vector, Matrix

from ..mu import MuMesh, MuRenderer, MuSkinnedMeshRenderer, MuBoneWeight
from ..utils import collect_modifiers

from .material import make_material

from .export_util import is_collider

from pprint import pprint

#matrix for converting between LHS and RHS (works either direction)
Matrix_YZ = Matrix(((1,0,0,0),
                    (0,0,1,0),
                    (0,1,0,0),
                    (0,0,0,1)))

MU_MAX_VERTS = 65534

def build_submeshes(mesh):
    submeshes = []
    submesh = []
    for i in range(len(mesh.loop_triangles)):
        submesh.append(i)
    submeshes.append(submesh)
    return submeshes

def make_tris(mesh, submeshes, vertex_map):
    for sm in submeshes:
        i = 0
        while i < len(sm):
            tri = mesh.loop_triangles[sm[i]].loops
            sm[i] = vertex_map[tri[0]], vertex_map[tri[1]], vertex_map[tri[2]]
            i += 1
    return submeshes

def get_mesh(obj):
    modifiers = collect_modifiers(obj)
    for mod in modifiers:
        mod.show_viewport = False
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(obj_eval)
    for mod in modifiers:
        mod.show_viewport = True
    return mesh

def get_vertex_data(mu, mesh, obj):
    full_data = not is_collider(obj)
    vertdata = [None] * len(mesh.loops)
    if not vertdata:
        return vertdata
    if mesh.loops[0].normal == Vector():
        mesh.calc_normals()
    tangentsOk = True
    if full_data and mesh.uv_layers:
        uv_layers = mesh.uv_layers
        #FIXME active UV layer?
        uvs = list(map(lambda a: Vector(a.uv).freeze(), uv_layers[0].data))
        if len(uv_layers) > 1:
            uv2s = list(map(lambda a: Vector(a.uv).freeze(), uv_layers[1].data))
        else:
            uv2s = [None] * len(mesh.loops)
        try:
            mesh.calc_tangents(uvmap = mesh.uv_layers[0].name)
        except RuntimeError:
            tangentsOk = False
            mu.messages.append(({'WARNING'}, "tangents not exported due to N-gons in the mesh: " + obj.name))
    else:
        uvs = [None] * len(mesh.loops)
        uv2s = [None] * len(mesh.loops)
    if full_data and mesh.vertex_colors:
        #FIXME active colors?
        colors = list(map(lambda a: Vector(a.color).freeze(), mesh.vertex_colors[0].data))
    else:
        colors = [None] * len(mesh.loops)
    for i in range(len(mesh.loops)):
        v = mesh.loops[i].vertex_index
        if full_data:
            n = Vector(mesh.loops[i].normal).freeze()
        else:
            n = None
        uv = uvs[i]
        uv2 = uv2s[i]
        col = colors[i]
        if uv != None and tangentsOk:
            t = Vector(mesh.loops[i].tangent).freeze()
            bts = mesh.loops[i].bitangent_sign
        else:
            t = None
            bts = None
        vertdata[i] = (v, n, uv, uv2, t, bts, col)
    return vertdata

def make_vertex_map(vertex_data):
    vdict = {}
    vmap = []
    for i, v in enumerate(vertex_data):
        #print(i, v in vdict)
        if v not in vdict:
            vdict[v] = len(vdict)
        vmap.append(vdict[v])
    return vmap, len(vdict)

def get_key_normals(shape_key):
    normals = shape_key.normals_split_get()
    normals = zip(normals[0:-2:3], normals[1:-1:3], normals[2::3])
    normals = list(map(lambda n: Vector(n), normals))
    return normals

def get_key_verts(shape_key):
    verts = list(map(lambda data: data.co, shape_key.data))
    return verts

def process_shape_keys(mesh, mumesh, vertex_map, vertex_data):
    num_shapes = len(mesh.shape_keys.key_blocks)
    num_verts = len(mumesh.verts)
    new_verts = (num_shapes - 1) * num_verts
    # UVs and vertex colors can't be keyed, but the arrays need to be the
    # same length. Extended with 0s for better compressibility in zip files
    if (hasattr(mumesh, "uvs")):
        mumesh.uvs.extend([Vector((0, 0))] * new_verts)
    if (hasattr(mumesh, "uv2s")):
        mumesh.uv2s.extend([Vector((0, 0))] * new_verts)
    if (hasattr(mumesh, "colors")):
        mumesh.colors.extend([Vector((1, 1, 1, 1))] * new_verts)

    if (hasattr(mumesh, "tangents")):
        #unfornately, don't know how to do tangents properly, so set
        #deltas to 0 FIXME
        mumesh.tangents.extend([(0, 0, 0, 0)] * new_verts)
    mumesh.verts = mumesh.verts * num_shapes
    if (hasattr(mumesh, "normals")):
        mumesh.normals = mumesh.normals * num_shapes
    basis = mesh.shape_keys.reference_key
    basis_verts = get_key_verts(basis)
    basis_normals = get_key_normals(basis)
    #ensure base mesh data reflects the basis key
    for i, vind in enumerate(vertex_map):
        v = vertex_data[i][0]
        mumesh.verts[vind] = basis_verts[v]
        mumesh.normals[vind] = basis_normals[i]
    base_ind = num_verts
    for key in mesh.shape_keys.key_blocks:
        if key.name == basis.name:
            continue
        print(key.name)
        ref_verts = get_key_verts(key.relative_key)
        ref_normals = get_key_normals(key.relative_key)
        verts = get_key_verts(key)
        normals = get_key_normals(key)
        for i, vind in enumerate(vertex_map):
            v = vertex_data[i][0]
            vert = verts[v] - ref_verts[v]
            norm = normals[i] - ref_normals[i]
            mumesh.verts[base_ind + vind] = vert
            mumesh.normals[base_ind + vind] = norm
        base_ind += num_verts


def make_mumesh(mesh, submeshes, vertex_data, vertex_map, num_verts):
    verts = [None] * num_verts
    groups = [None] * num_verts
    uvs = [None] * num_verts
    uv2s = [None] * num_verts
    normals = [None] * num_verts
    tangents = [None] * num_verts
    bitangents = [None] * num_verts
    colors = [None] * num_verts
    for i, vind in enumerate(vertex_map):
        v, n, uv, uv2, t, bts, col = vertex_data[i]
        verts[vind] = v
        normals[vind] = n
        uvs[vind] = uv
        uv2s[vind] = uv2
        tangents[vind] = t
        bitangents[vind] = bts
        colors[vind] = col
    for i, v in enumerate(verts):
        verts[i] = mesh.vertices[v].co
        groups[i] = mesh.vertices[v].groups
    if tangents[0] != None:
        for i, t in enumerate(tangents):
            tangents[i] = tuple(t) + (bitangents[i],)
    mumesh = MuMesh()
    mumesh.submeshes = submeshes
    mumesh.verts = verts
    mumesh.groups = groups
    if normals[0] != None:
        mumesh.normals = normals
    if uvs[0] != None:
        mumesh.uvs = uvs
    if uv2s[0] != None:
        mumesh.uv2s = uv2s
    if tangents[0] != None:
        mumesh.tangents = tangents
    if colors[0] != None:
        mumesh.colors = colors
    return mumesh

def make_mesh(mu, obj):
    mesh = get_mesh(obj)
    if not len(mesh.loops):
        mu.messages.append(({'WARNING'}, f"Mesh has more ZERO vertices "
                            + obj.name))
        return None
    #mesh is always a copy of the object mesh data, but this is non-destructive
    #anyway
    if not mesh.loop_triangles:
        mesh.calc_loop_triangles()
    vertex_data = get_vertex_data(mu, mesh, obj)
    vertex_map, num_verts = make_vertex_map(vertex_data)
    submeshes = build_submeshes(mesh)
    submeshes = make_tris(mesh, submeshes, vertex_map)
    #pprint(submeshes)
    mumesh = make_mumesh(mesh, submeshes, vertex_data, vertex_map, num_verts)
    mesh = obj.data
    if not is_collider(obj) and mesh.shape_keys:
        process_shape_keys(mesh, mumesh, vertex_map, vertex_data)
    if len(mumesh.verts) > MU_MAX_VERTS:
        mu.messages.append(({'WARNING'}, f"Mesh has more than {MU_MAX_VERTS} "
                            "vertices: KSP will not import it properly "
                            + obj.name))
    return mumesh

def mesh_materials(mu, mesh):
    materials = []
    for mat in mesh.materials:
        if not mat:
            mu.messages.append(({'WARNING'}, f"{mesh.name} has empty material "
                                "slot"))
            continue
        if mat.mumatprop.shaderName:
            if mat.name not in mu.materials:
                mu.materials[mat.name] = make_material(mu, mat)
            materials.append(mu.materials[mat.name].index)
    return materials

def make_renderer(mu, obj, mesh):
    rend = MuRenderer()
    #FIXME shadows
    rend.materials = mesh_materials(mu, mesh)
    rend.castShadows = obj.muproperties.castShadows
    rend.receiveShadows = obj.muproperties.receiveShadows
    if not rend.materials:
        return None
    return rend

def mesh_bones(obj, mumesh, armature):
    boneset = set()
    for bone in armature.bones:
        boneset.add(bone.name)
    bones = []
    boneindices = {}
    mumesh.boneWeights = [None] * len(mumesh.verts)
    for grp in obj.vertex_groups:
        if grp.name in boneset:
            boneindices[grp.name] = len(bones)
            bones.append(grp.name)
    maxlen = 0
    for i, vertex_group in enumerate(mumesh.groups):
        weights = []
        for vgrp in vertex_group:
            gname = obj.vertex_groups[vgrp.group].name
            if gname in boneindices:
                weights.append((boneindices[gname], vgrp.weight))
        weights.sort(key=lambda w: w[1])
        weights.reverse()
        weights = weights[:4]
        if len(weights) > maxlen:
            maxlen = len(weights)
        if len(weights) < 4:
            weights += [(0,0)]*(4 - len(weights))
        bw = MuBoneWeight()
        bw.indices = list(map(lambda w: w[0], weights))
        bw.weights = list(map(lambda w: w[1], weights))
        mumesh.boneWeights[i] = bw
    return bones, maxlen

def make_bindPoses(smr, armature, arm_mat):
    smr.mesh.bindPoses = [None] * len(smr.bones)
    for i, bone in enumerate(smr.bones):
        poseBone = armature.bones[bone]
        mat = poseBone.matrix_local.inverted() @ arm_mat
        mat = Matrix_YZ @ mat @ Matrix_YZ
        mat = tuple(mat)
        mat = tuple(map(lambda v: tuple(v), mat))
        mat = mat[0] + mat[1] + mat[2] + mat[3]
        smr.mesh.bindPoses[i] = mat

def handle_mesh(obj, muobj, mu):
    muobj.shared_mesh = make_mesh(mu, obj)
    muobj.renderer = make_renderer(mu, obj, obj.data)
    return muobj

def create_skinned_mesh(obj, mu, armature):
    smr = MuSkinnedMeshRenderer()
    smr.mesh = make_mesh(mu, obj)
    smr.bones, smr.quality = mesh_bones(obj, smr.mesh, armature)
    #armature-relative transform between armature and mesh
    arm_mat = obj.matrix_local
    if arm_mat != Matrix():
        mu.messages.append(({'WARNING'}, f"{obj.name}: non-identity armature-mesh matrix"))
    make_bindPoses (smr, armature, arm_mat)
    smr.materials = mesh_materials(mu, obj.data)
    #FIXME center, size, updateWhenOffscreen
    #however, with updateWhenOffscreen = 1, Unity will recaculate the mesh
    #bounds every frame, so take the easy way for now
    mins = Vector(smr.mesh.verts[0])
    maxs = Vector(smr.mesh.verts[0])
    for v in smr.mesh.verts:
        for i in range(3):
            mins[i] = min(v[i], mins[i])
            maxs[i] = max(v[i], maxs[i])
    smr.center = (maxs + mins) / 2
    smr.size = (maxs - mins) / 2
    smr.updateWhenOffscreen = 1
    return smr

type_handlers = {
    bpy.types.Mesh: handle_mesh,
}
