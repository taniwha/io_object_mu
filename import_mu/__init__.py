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
from math import pi, sqrt

import bpy
import bmesh
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import BoolProperty, StringProperty

from ..mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from ..mu import MuColliderBox, MuColliderWheel
from ..shader import make_shader
from .. import collider, properties, cameraprops

from .importerror import MuImportError
from .animation import create_action, create_object_paths
from .armature import create_armature, create_armature_modifier
from .armature import needs_armature, BONE_LENGTH
from .collider import create_collider
from .light import create_light
from .mesh import create_mesh
from .operators import KSPMU_OT_ImportMu

def create_data_object(name, data, transform):
    obj = bpy.data.objects.new(name, data)
    bpy.context.view_layer.objects.active = obj
    obj.rotation_mode = 'QUATERNION'
    if transform:
        obj.location = Vector(transform.localPosition)
        obj.rotation_quaternion = Quaternion(transform.localRotation)
        obj.scale = Vector(transform.localScale)
    else:
        obj.location = Vector((0, 0, 0))
        obj.rotation_quaternion = Quaternion((1,0,0,0))
        obj.scale = Vector((1,1,1))
    return obj

def create_camera(mu, mucamera, name):
    camera = bpy.data.cameras.new(name)
    #mucamera.clearFlags
    camera.type = ['PERSP', 'ORTHO'][mucamera.orthographic]
    camera.lens_unit = 'FOV'
    # blender's fov is in radians, unity's in degrees
    camera.angle = mucamera.fov * pi / 180
    camera.clip_start = mucamera.near
    camera.clip_end = mucamera.far
    muprops = camera.mucameraprop
    properties.SetPropMask(muprops.cullingMask, mucamera.cullingMask)
    muprops.backgroundColor = mucamera.backgroundColor
    muprops.depth = mucamera.depth
    if mucamera.clearFlags > 0:
        flags = mucamera.clearFlags - 1
        muprops.clearFlags = cameraprops.clearflag_items[flags][0]
    return camera

def attach_material(mesh, renderer, mu):
    if mu.materials and renderer.materials:
        #KSP supports only the first submesh and thus only the first
        #material
        mumat = mu.materials[renderer.materials[0]]
        mesh.materials.append(mumat.material)

def create_object(mu, muobj, parent):
    obj = None
    mesh = None
    if (not mu.create_colliders
        and (hasattr(muobj, "shared_mesh")
             and not hasattr(muobj, "renderer"))):
        return None
    name = muobj.transform.name
    xform = None if hasattr(muobj, "bone") else muobj.transform
    if hasattr(muobj, "shared_mesh") and hasattr(muobj, "renderer"):
        mesh = create_mesh(mu, muobj.shared_mesh, name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_data_object(name, mesh, xform)
        attach_material(mesh, muobj.renderer, mu)
    elif hasattr(muobj, "skinned_mesh_renderer"):
        smr = muobj.skinned_mesh_renderer
        mesh = create_mesh(mu, smr.mesh, name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_data_object(name, mesh, xform)
        create_vertex_groups(obj, smr.bones, smr.mesh.boneWeights)
        create_armature_modifier(obj, mu)
        attach_material(mesh, smr, mu)
    if not obj:
        data = None
        if hasattr(muobj, "light"):
            data = create_light(mu, muobj.light, name)
        elif hasattr(muobj, "camera"):
            data = create_camera(mu, muobj.camera, name)
        if data:
            obj = create_data_object(name, data, xform)
            # Blender points spotlights along local -Z, unity along local +Z
            # which is Blender's +Y, so rotate 90 degrees around local X to
            # go from Unity to Blender
            rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
            obj.rotation_quaternion @= rot
    if hasattr(muobj, "bone"):
        #FIXME skinned_mesh_renderer double transforms? Not yet sure this is a
        #problem, but if so will need to not import the whole hierarchy as one
        #armature.
        if obj:
            obj.parent = mu.armature_obj
            obj.parent_type = 'BONE'
            obj.parent_bone = muobj.bone
            obj.matrix_parent_inverse[1][3] = -BONE_LENGTH
        pbone = mu.armature_obj.pose.bones[muobj.bone]
        pbone.scale = muobj.transform.localScale
    else:
        if not obj:
            obj = create_data_object(name, None, xform)
        obj.parent = parent
    if obj:
        #FIXME will lose properties from any empty objects that have properties
        #set when using an armature. Maybe create an empty? Put properties on
        #bones?
        mu.collection.objects.link(obj)
        if hasattr(muobj, "tag_and_layer"):
            obj.muproperties.tag = muobj.tag_and_layer.tag
            obj.muproperties.layer = muobj.tag_and_layer.layer
        if mu.create_colliders and hasattr(muobj, "collider"):
            cobj = create_collider(mu, muobj)
            cobj.parent = obj
        muobj.bobj = obj
    for child in muobj.children:
        create_object(mu, child, obj)
    if hasattr(muobj, "animation"):
        for clip in muobj.animation.clips:
            create_action(mu, muobj.path, clip)
    return obj

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
    return width, height, pixels

def load_image(base, ext, path, type):
    name = base + ext
    if ext.lower() in [".dds", ".png", ".tga"]:
        img = bpy.data.images.load(os.path.join(path, name))
        img.name = base
        img.muimageprop.invertY = False
        if ext.lower() == ".dds":
            img.muimageprop.invertY = True
        pixels = img.pixels[:1024]#256 pixels
        if base[-2:].lower() == "_n" or base[-3:].lower() == "nrm":
            type = 1
    elif ext.lower() == ".mbm":
        w,h, pixels = load_mbm(os.path.join(path, name))
        img = bpy.data.images.new(base, w, h)
        img.pixels[:] = map(lambda x: x / 255.0, pixels)
        img.pack(as_png=True)
    img.alpha_mode = 'STRAIGHT'
    img.muimageprop.invertY = (ext.lower() == ".dds")
    img.muimageprop.convertNorm = False
    if type == 1:
        img.colorspace_settings.name = 'Non-Color'
        for i in range(256):
            c = 2*Vector(pixels[i*4:i*4+4])-Vector((1, 1, 1, 1))
            if abs(c.x*c.x + c.y*c.y + c.z*c.z - 1) > 0.05:
                img.muimageprop.convertNorm = True

def create_textures(mu, path):
    extensions = [".dds", ".mbm", ".tga", ".png"]
    #texture info is in the top level object
    for tex in mu.textures:
        base, ext = os.path.splitext(tex.name)
        ind = 0
        if ext in extensions:
            ind = extensions.index(ext)
        lst = extensions[ind:] + extensions[:ind]
        for e in lst:
            try:
                load_image(base, e, path, tex.type)
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
        mumat.material = make_shader(mumat, mu)

def process_mu(mu, mudir):
    create_textures(mu, mudir)
    create_materials(mu)
    create_object_paths(mu)
    if mu.force_armature or needs_armature(mu):
        create_armature(mu)
        # The root object is the armature itself
        for child in mu.obj.children:
            create_object(mu, child, None)
        obj = mu.armature_obj
    else:
        obj = create_object(mu, mu.obj, None)
    return obj

def import_mu(collection, filepath, create_colliders, force_armature):
    mu = Mu()
    mu.create_colliders = create_colliders
    mu.force_armature = force_armature
    mu.collection = collection
    if not mu.read(filepath):
        raise MuImportError("Mu", "Unrecognized format: magic %x version %d"
                                  % (mu.magic, mu.version))

    return process_mu(mu, os.path.dirname(filepath))

def import_mu_menu_func(self, context):
    self.layout.operator(KSPMU_OT_ImportMu.bl_idname, text="KSP Mu (.mu)")

classes = (
    KSPMU_OT_ImportMu,
)

menus = (
    (bpy.types.TOPBAR_MT_file_import, import_mu_menu_func),
)
