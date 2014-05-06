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
import os.path
from math import pi

import bpy
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuColliderBox, MuColliderWheel
from .shader import make_shader
from . import collider, properties

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
    return obj

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

def create_light(mu, mulight, transform):
    ltype = ('SPOT', 'SUN', 'POINT', 'AREA')[mulight.type]
    light = bpy.data.lamps.new(transform.name, ltype)
    light.color = mulight.color[:3]
    light.distance = mulight.range
    light.energy = mulight.intensity
    if ltype == 'SPOT' and hasattr(mulight, "spotAngle"):
        light.spot_size = mulight.spotAngle * pi / 180
    obj = bpy.data.objects.new(transform.name, light)
    obj.rotation_mode = 'QUATERNION'
    obj.location = Vector(transform.localPosition)
    obj.rotation_quaternion = Quaternion(transform.localRotation)
    obj.scale = Vector(transform.localScale)
    properties.SetPropMask(obj.muproperties.cullingMask, mulight.cullingMask)
    bpy.context.scene.objects.link(obj)
    return obj

def create_object(mu, muobj, parent):
    obj = None
    mesh = None
    if hasattr(muobj, "collider"):
        col = muobj.collider
        name = muobj.transform.name
        if type(col) == MuColliderMesh:
            mesh = create_mesh(mu, col.mesh, name)
        elif type(col) == MuColliderSphere:
            mesh = collider.sphere(name, col.center, col.radius)
        elif type(col) == MuColliderCapsule:
            mesh = collider.capsule(name, col.center, col.radius, col.height,
                                    col.direction)
        elif type(col) == MuColliderBox:
            mesh = collider.box(name, col.center, col.size)
        elif type(col) == MuColliderWheel:
            mesh = collider.wheel(name, col.center, col.radius)
        obj = create_mesh_object(name, mesh, muobj.transform)
        obj.parent = parent

        obj.muproperties.isTrigger = False
        if type(col) != MuColliderWheel:
            obj.muproperties.isTrigger = col.isTrigger
        if type(col) == MuColliderMesh:
            obj.muproperties.collider = 'MU_COL_MESH'
        elif type(col) == MuColliderSphere:
            obj.muproperties.collider = 'MU_COL_SPHERE'
            obj.muproperties.radius = col.radius
            obj.muproperties.center = col.center
        elif type(col) == MuColliderCapsule:
            obj.muproperties.collider = 'MU_COL_CAPSULE'
            obj.muproperties.radius = col.radius
            obj.muproperties.height = col.height
            obj.muproperties.direction = properties.dir_map[col.direction]
            obj.muproperties.center = col.center
        elif type(col) == MuColliderBox:
            obj.muproperties.collider = 'MU_COL_BOX'
            obj.muproperties.size = col.size
            obj.muproperties.center = col.center
        elif type(col) == MuColliderWheel:
            obj.muproperties.collider = 'MU_COL_WHEEL'
            obj.muproperties.radius = col.radius
            obj.muproperties.suspensionDistance = col.suspensionDistance
            obj.muproperties.center = col.center
            copy_spring(obj.muproperties.suspensionSpring, col.suspensionSpring)
            copy_friction(obj.muproperties.forwardFriction, col.forwardFriction)
            copy_friction(obj.muproperties.sideFriction, col.sidewaysFriction)
    if hasattr(muobj, "shared_mesh"):
        mesh = create_mesh(mu, muobj.shared_mesh, muobj.transform.name)
        obj = create_mesh_object(muobj.transform.name, mesh, muobj.transform)
    if hasattr(muobj, "renderer"):
        if mesh:
            mat = mu.materials[muobj.renderer.materials[0]]
            mesh.materials.append(bpy.data.materials[mat.name])
    if not obj:
        if hasattr(muobj, "light"):
            obj = create_light(mu, muobj.light, muobj.transform)
    if not obj:
        obj = create_mesh_object(muobj.transform.name, None, muobj.transform)
    if hasattr(muobj, "tag_and_layer"):
        obj.muproperties.tag = muobj.tag_and_layer.tag
        obj.muproperties.layer = muobj.tag_and_layer.layer
    obj.parent = parent
    for child in muobj.children:
        create_object(mu, child, obj)
    return obj

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

def load_image(name, path):
    if name[-4:].lower() in [".png", ".tga"]:
        bpy.data.images.load(os.path.join(path, name))
    elif name[-4:].lower() == ".mbm":
        w,h, pixels = load_mbm(os.path.join(path, name))
        img = bpy.data.images.new(name, w, h)
        img.pixels[:] = map(lambda x: x / 255.0, pixels)
        img.pack(True)

def create_textures(mu, path):
    extensions = [".mbm", ".tga", ".png"]
    #texture info is in the top level object
    for tex in mu.textures:
        ext = tex.name[-4:]
        base = tex.name[:-4]
        ind = extensions.index(ext)
        lst = extensions[ind:] + extensions[:ind]
        for e in lst:
            try:
                name = base+e
                load_image(name, path)
                tx = bpy.data.textures.new(name, 'IMAGE')
                tx.use_preview_alpha = True
                tx.image = bpy.data.images[name]
                break
            except FileNotFoundError:
                continue
            except RuntimeError:
                continue
    pass

def add_texture(mu, mat, mattex):
    i, s, o = mattex.index, mattex.scale, mattex.offset
    mat.texture_slots.add()
    ts = mat.texture_slots[0]
    ts.texture = bpy.data.textures[mu.textures[i].name]
    ts.use_map_alpha = True
    ts.texture_coords = 'UV'
    ts.scale = s + (1,)
    ts.offset = o + (0,)

def create_materials(mu):
    #material info is in the top level object
    for mumat in mu.materials:
        mat = make_shader(mumat, mu)

def import_mu(operator, context, filepath):
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    mu = Mu()
    if not mu.read(filepath):
        operator.report({'ERROR'},
            "Unrecognized format: %s %d" % (mu.magic, mu.version))
        return {'CANCELLED'}

    create_textures(mu, os.path.dirname(filepath))
    create_materials(mu)
    obj = create_object(mu, mu.obj, None)
    bpy.context.scene.objects.active = obj
    obj.select = True

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}
