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

import bpy, bmesh
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuObject, MuTransform, MuMesh
from .mu import MuColliderBox, MuColliderWheel
from .shader import make_shader

def make_transform(obj):
    transform = MuTransform()
    transform.name = obj.name
    transform.localPosition = obj.location
    transform.localRotation = obj.rotation_quaternion
    transform.localScale = obj.scale
    return transform

def split_face(mesh, index):
    face = mesh.polygons[index]
    s, e = face.loop_start, face.loop_start + face.loop_total
    uv = mesh.uv_layers.active.data[s:e]
    uv = list(map(lambda a: a.uv, uv))
    fv = list(face.vertices)
    tris = []
    for i in range(1, len(fv) - 1):
        tri = ((fv[0], tuple(uv[0])),
               (fv[i], tuple(uv[i])),
               (fv[i+1], tuple(uv[i+1])))
        tris.append(tri)
    return tris

def build_submeshes(mesh):
    bmsh = bmesh.new ()
    bmsh.from_mesh(mesh)
    submeshes = []
    face_set = set(bmsh.faces)
    while face_set:
        face_queue = [face_set.pop()]
        submesh = []
        while face_queue:
            face = face_queue.pop()
            submesh.append(face.index)
            for edge in face.edges:
                for link_face in edge.link_faces:
                    if link_face in face_set:
                        face_set.remove(link_face)
                        face_queue.append(link_face)
        submeshes.append(submesh)
    return submeshes

def make_tris(mesh, submeshes):
    for sm in submeshes:
        i = 0
        while i < len(sm):
            tris = split_face(mesh, sm[i])
            sm[i:i+1] = tris
            i += len(tris)

def make_verts(mesh, submeshes):
    verts = []
    normals = []
    uvs = []
    for sm in submeshes:
        for ft in sm:
            tv = []
            for vuv in ft:
                if vuv not in vuvdict:
                    vuvdict[vuv] = len(verts)
                    mv = mesh.vertices[vuv[0]]
                    verts.append(tuple(mv.co))
                    normals.append(tuple(mv.normal))
                    uvs.append(vuv[1])
                tv.append(vuvdict[vuv])
    return verts, uvs, normals

def make_mesh(mu, obj):
    submeshes = build_submeshes(obj.data)
    mesh = obj.to_mesh(bpy.context.scene, True, 'PREVIEW')
    submeshes = make_tris(mesh, submeshes)
    mumesh = MuMesh()
    vun = make_verts(mesh, submeshes)
    mumesh.verts, mumesh.uvs, umesh.normals = vun
    mumesh.submeshes = submeshes

def make_obj(mu, obj):
    muobj = MuObject()
    muobj.transform = make_transform (obj)
    if obj.data:
        muobj.shared_mesh = make_mesh(mu, obj)
    for o in obj.children:
        if (o.data and type(o.data) != bpy.types.Mesh):
            continue
        make_obj(mu, o)

def export_mu(operator, context, filepath):
    obj = context.active_object
    mu = Mu()
    mu.obj = make_obj(mu, obj)
    return {'FINISHED'}
