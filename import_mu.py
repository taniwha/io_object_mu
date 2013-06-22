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

from struct import unpack

import bpy
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuColliderBox, MuColliderWheel
from .shader import make_shader

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

def convert_bump(pixels, width, height):
    outp = list(pixels)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = ((y * width + x) * 4,
                 (y * width + x - 1) * 4,
                 (y * width + x + 1) * 4,
                 ((y - 1) * width + x) * 4,
                 ((y + 1) * width + x) * 4)
            dx = Vector((1, 0, (pixels[i[2]] - pixels[i[1]]) / 2.0))
            dy = Vector((0, 1, (pixels[i[4]] - pixels[i[3]]) / 2.0))
            n = dx.cross(dy)
            n.normalize()
            outp[i[0]:i[0]+3] = map(lambda x: int(x * 127) + 128, list(n))
    return outp


def load_mbm(mbmpath):
    mbmfile = open(mbmpath, "rb")
    header = mbmfile.read(20)
    magic, width, height, bump, bpp = unpack("<5i", header)
    if magic != 0x50534b03: # "\x03KSP" as little endian
        raise
    if bpp == 32:
        pixels = mbmfile.read(width * height * 4)
    elif bpp == 24:
        pixels = [0, 0, 0, 255] * width * height
        for i in range(width * height):
            p = mbmfile.read(3)
            l = i * 4
            pixels[l:l+3] = list(p)
    else:
        raise
    if bump:
        pixels = convert_bump(pixels, width, height)
    return width, height, pixels

def create_textures(mu):
    #texture info is in the top level object
    for tex in mu.obj.textures:
        if tex.name[-4:].lower() in [".png", ".tga"]:
            bpy.data.images.load(tex.name)
        elif tex.name[-4:].lower() == ".mbm":
            w,h, pixels = load_mbm(tex.name)
            img = bpy.data.images.new(tex.name, w, h)
            img.pixels[:] = map(lambda x: x / 255.0, pixels)
            img.pack(True)
        tx = bpy.data.textures.new(tex.name, 'IMAGE')
        tx.use_preview_alpha = True
        tx.image = bpy.data.images[tex.name]

def add_texture(mu, mat, mattex):
    i, s, o = mattex.index, mattex.scale, mattex.offset
    mat.texture_slots.add()
    ts = mat.texture_slots[0]
    ts.texture = bpy.data.textures[mu.obj.textures[i].name]
    ts.use_map_alpha = True
    ts.texture_coords = 'UV'
    ts.scale = s + (1,)
    ts.offset = o + (0,)

def create_materials(mu):
    #material info is in the top level object
    for mumat in mu.obj.materials:
        mat = make_shader(MuEnum.ShaderNames[mumat.type], mumat, mu)

def import_mu(operator, context, filepath):
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    mu = Mu()
    if not mu.read(filepath):
        operator.report({'ERROR'},
            "Unrecognized format: %s %d" % (mu.magic, mu.version))
        return {'CANCELLED'}

    create_textures(mu)
    create_materials(mu)
    create_object(mu, mu.obj, None)

    bpy.context.user_preferences.edit.use_global_undo = True
    return {'FINISHED'}
