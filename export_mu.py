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
from pprint import pprint

from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuObject, MuTransform, MuMesh, MuTagLayer, MuRenderer
from .mu import MuColliderBox, MuColliderWheel, MuMaterial, MuTexture, MuMatTex
from .shader import make_shader
from . import properties

def strip_nnn(name):
    ind = name.rfind(".")
    if ind < 0 or len(name) - ind != 4:
        return name
    if not name[ind+1:].isdigit():
        return name
    return name[:ind]

def make_transform(obj):
    transform = MuTransform()
    transform.name = strip_nnn(obj.name)
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
    return submeshes

def make_verts(mesh, submeshes):
    verts = []
    normals = []
    uvs = []
    for sm in submeshes:
        vuvdict = {}
        for i, ft in enumerate(sm):
            tv = []
            for vuv in ft:
                if vuv not in vuvdict:
                    vuvdict[vuv] = len(verts)
                    mv = mesh.vertices[vuv[0]]
                    verts.append(tuple(mv.co))
                    normals.append(tuple(mv.normal))
                    uvs.append(vuv[1])
                tv.append(vuvdict[vuv])
            sm[i] = tv
    return verts, uvs, normals

def make_tangents(verts, uvs, normals, submeshes):
    sdir = [Vector()] * len(verts)
    tdir = [Vector()] * len(verts)
    tangents = []
    for sm in submeshes:
        for tri in sm:
            v1 = Vector(verts[tri[0]])
            v2 = Vector(verts[tri[1]])
            v3 = Vector(verts[tri[2]])

            w1 = uvs[tri[0]]
            w2 = uvs[tri[1]]
            w3 = uvs[tri[2]]

            u1 = v2 - v1
            u2 = v3 - v1

            s1 = w2[0] - w1[0]
            s2 = w3[0] - w1[0]
            t1 = w2[1] - w1[1]
            t2 = w3[1] - w1[1]

            r = s1 * t2 - s2 * t1

            if r * r < 1e-6:
                continue
            sd = (t2 * u1 - t1 * u2) / r
            td = (s1 * u2 - s2 * u1) / r

            sdir[tri[0]] += sd
            sdir[tri[1]] += sd
            sdir[tri[2]] += sd
            tdir[tri[0]] += td
            tdir[tri[1]] += td
            tdir[tri[2]] += td
    for i, n in enumerate(normals):
        t = sdir[i]
        t -= t.dot(n) * Vector(n)
        t.normalize()
        hand = t.dot(tdir[i]) < 0 and -1.0 or 1.0
        tangents.append(tuple(t) + (hand,))
    return tangents

def make_mesh(mu, obj):
    submeshes = build_submeshes(obj.data)
    mesh = obj.to_mesh(bpy.context.scene, True, 'PREVIEW')
    submeshes = make_tris(mesh, submeshes)
    mumesh = MuMesh()
    vun = make_verts(mesh, submeshes)
    mumesh.verts, mumesh.uvs, mumesh.normals = vun
    mumesh.submeshes = submeshes
    mumesh.tangents = make_tangents(mumesh.verts, mumesh.uvs,
                                    mumesh.normals, mumesh.submeshes)
    return mumesh

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
        col = MuColliderWheel(True)
        col.isTrigger = obj.muproperties.isTrigger
        col.mass = obj.muproperties.mass
        col.radius = obj.muproperties.radius
        col.suspensionDistance = obj.muproperties.suspensionDistance
        col.center = obj.muproperties.center
        col.suspensionSpring = make_spring(obj.muproperties.suspensionSpring)
        col.forwardFriction = make_friction(obj.muproperties.forwardFriction)
        col.sidewaysFriction = make_friction(obj.muproperties.sideFriction)
    return col

def make_tag_and_layer(obj):
    tl = MuTagLayer()
    tl.tag = obj.muproperties.tag
    tl.layer = obj.muproperties.layer
    return tl

def make_texture(mu, tex, type):
    if tex.tex not in mu.textures:
        mutex = MuTexture()
        mutex.name = tex.tex
        mutex.type = type
        mutex.index = len(mu.textures)
        mu.textures[tex.tex] = mutex
    mattex = MuMatTex()
    mattex.index = mu.textures[tex.tex].index
    mattex.scale = tex.scale
    mattex.offset = tex.offset
    return mattex

def make_material(mu, mat):
    material = MuMaterial()
    material.name = mat.name
    material.index = len(mu.materials)
    matprops = mat.mumatprop
    material.type = MuEnum.ShaderNames.index(matprops.shader)
    if matprops.shader == 'KSP/Specular':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.specColor = matprops.specColor
        material.shininess = matprops.shininess
    elif matprops.shader == 'KSP/Bumped':
        matprops.mainTex = make_texture(mu, matprops.mainTex, 0)
        matprops.bumpMap = make_texture(mu, matprops.bumpMap, 1)
    elif matprops.shader == 'KSP/Bumped Specular':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.bumpMap = make_texture(mu, matprops.bumpMap, 1)
        material.specColor = matprops.specColor
        material.shininess = matprops.shininess
    elif matprops.shader == 'KSP/Emissive/Diffuse':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.emissive = make_texture(mu, matprops.emissive, 0)
        material.emissiveColor = matprops.emissiveColor
    elif matprops.shader == 'KSP/Emissive/Specular':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.specColor = matprops.specColor
        material.shininess = matprops.shininess
        material.emissive = make_texture(mu, matprops.emissive, 0)
        material.emissiveColor = matprops.emissiveColor
    elif matprops.shader == 'KSP/Emissive/Bumped Specular':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.bumpMap = make_texture(mu, matprops.bumpMap, 1)
        material.specColor = matprops.specColor
        material.shininess = matprops.shininess
        material.emissive = make_texture(mu, matprops.emissive, 0)
        material.emissiveColor = matprops.emissiveColor
    elif matprops.shader == 'KSP/Alpha/Cutoff':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.cutoff = matprops.cutoff
    elif matprops.shader == 'KSP/Alpha/Cutoff Bumped':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.bumpMap = make_texture(mu, matprops.bumpMap, 1)
        material.cutoff = matprops.cutoff
    elif matprops.shader == 'KSP/Alpha/Translucent':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
    elif matprops.shader == 'KSP/Alpha/Translucent Specular':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.gloss = matprops.gloss
        material.specColor = matprops.specColor
        material.shininess = matprops.shininess
    elif matprops.shader == 'KSP/Alpha/Unlit Transparent':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.color = matprops.color
    elif matprops.shader == 'KSP/Unlit':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
        material.color = matprops.color
    elif matprops.shader == 'KSP/Diffuse':
        material.mainTex = make_texture(mu, matprops.mainTex, 0)
    return material

def make_renderer(mu, mesh):
    rend = MuRenderer()
    #FIXME shadows
    rend.materials = []
    for mat in mesh.materials:
        if mat.mumatprop.shader:
            if mat.name not in mu.materials:
                mu.materials[mat.name] = make_material(mu, mat)
            rend.materials.append(mu.materials[mat.name].index)
    return rend

def make_obj(mu, obj):
    muobj = MuObject()
    muobj.transform = make_transform (obj)
    muobj.tag_and_layer = make_tag_and_layer(obj)
    if obj.muproperties.collider != 'MU_COL_NONE':
        muobj.collider = make_collider(mu, obj)
    elif obj.data:
        muobj.shared_mesh = make_mesh(mu, obj)
        muobj.renderer = make_renderer(mu, obj.data)
    for o in obj.children:
        if (o.data and type(o.data) != bpy.types.Mesh):
            continue
        muobj.children.append(make_obj(mu, o))
    return muobj

def export_mu(operator, context, filepath):
    obj = context.active_object
    mu = Mu()
    mu.materials = {}
    mu.textures = {}
    mu.obj = make_obj(mu, obj)
    mu.materials = list(mu.materials.values())
    mu.materials.sort(key=lambda x: x.index)
    mu.textures = list(mu.textures.values())
    mu.textures.sort(key=lambda x: x.index)
    mu.write(filepath)
    return {'FINISHED'}
