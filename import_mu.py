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
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import FloatVectorProperty, PointerProperty

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
    if transform:
        obj.location = Vector(transform.localPosition)
        obj.rotation_quaternion = Quaternion(transform.localRotation)
        obj.scale = Vector(transform.localScale)
    else:
        obj.location = Vector((0, 0, 0))
        obj.rotation_quaternion = Quaternion((1,0,0,0))
        obj.scale = Vector((1,1,1))
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
    # Blender points spotlights along local -Z, unity along local +Z
    # which is Blender's +Y, so rotate 90 degrees around local X to
    # go from Unity to Blender
    rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
    obj.rotation_quaternion = rot * Quaternion(transform.localRotation)
    obj.scale = Vector(transform.localScale)
    properties.SetPropMask(obj.muproperties.cullingMask, mulight.cullingMask)
    bpy.context.scene.objects.link(obj)
    return obj

property_map = {
    "m_LocalPosition.x": ("obj", "location", 0, 1),
    "m_LocalPosition.y": ("obj", "location", 2, 1),
    "m_LocalPosition.z": ("obj", "location", 1, 1),
    "m_LocalRotation.x": ("obj", "rotation_quaternion", 1, -1),
    "m_LocalRotation.y": ("obj", "rotation_quaternion", 3, -1),
    "m_LocalRotation.z": ("obj", "rotation_quaternion", 2, -1),
    "m_LocalRotation.w": ("obj", "rotation_quaternion", 0, 1),
    "m_LocalScale.x": ("obj", "scale", 0, 1),
    "m_LocalScale.y": ("obj", "scale", 2, 1),
    "m_LocalScale.z": ("obj", "scale", 1, 1),
    "m_Intensity": ("data", "energy", 0, 1),
}

def create_fcurve(action, curve, propmap):
    dp, ind, mult = propmap
    fps = bpy.context.scene.render.fps
    fc = action.fcurves.new(data_path = dp, index = ind)
    fc.keyframe_points.add(len(curve.keys))
    for i, key in enumerate(curve.keys):
        x,y = key.time * fps, key.value * mult
        fc.keyframe_points[i].co = x, y
        fc.keyframe_points[i].handle_left_type = 'FREE'
        fc.keyframe_points[i].handle_right_type = 'FREE'
        if i > 0:
            dist = (key.time - curve.keys[i - 1].time) / 3
            dx, dy = dist * fps, key.tangent[0] * dist * mult
        else:
            dx, dy = 10, 0.0
        fc.keyframe_points[i].handle_left = x - dx, y - dy
        if i < len(curve.keys) - 1:
            dist = (curve.keys[i + 1].time - key.time) / 3
            dx, dy = dist * fps, key.tangent[1] * dist * mult
        else:
            dx, dy = 10, 0.0
        fc.keyframe_points[i].handle_right = x + dx, y + dy
    return True

def create_action(mu, path, clip):
    #print(clip.name)
    actions = {}
    for curve in clip.curves:
        if not curve.path:
            mu_path = path
        else:
            mu_path = "/".join([path, curve.path])
        if mu_path not in mu.objects:
            print("Unknown path: %s" % (mu_path))
            continue
        obj = mu.objects[mu_path]

        if curve.property not in property_map:
            print("%s: Unknown property: %s" % (mu_path, curve.property))
            continue
        propmap = property_map[curve.property]
        subpath, propmap = propmap[0], propmap[1:]

        if subpath != "obj":
            obj = getattr (obj, subpath)

        name = ".".join([clip.name, curve.path, subpath])
        if name not in actions:
            actions[name] = bpy.data.actions.new(name), obj
        act, obj = actions[name]
        if not create_fcurve(act, curve, propmap):
            continue
    for name in actions:
        act, obj = actions[name]
        if not obj.animation_data:
            obj.animation_data_create()
        track = obj.animation_data.nla_tracks.new()
        track.name = clip.name
        track.strips.new(act.name, 1.0, act)

def create_collider(mu, muobj):
    col = muobj.collider
    name = muobj.transform.name
    if type(col) == MuColliderMesh:
        name = name + ".collider"
        mesh = create_mesh(mu, col.mesh, name)
    else:
        mesh = bpy.data.meshes.new(name)
    obj = create_mesh_object(name, mesh, None)

    obj.muproperties.isTrigger = False
    if type(col) != MuColliderWheel:
        obj.muproperties.isTrigger = col.isTrigger
    if type(col) == MuColliderMesh:
        obj.muproperties.collider = 'MU_COL_MESH'
    elif type(col) == MuColliderSphere:
        obj.muproperties.radius = col.radius
        obj.muproperties.center = col.center
        obj.muproperties.collider = 'MU_COL_SPHERE'
    elif type(col) == MuColliderCapsule:
        obj.muproperties.radius = col.radius
        obj.muproperties.height = col.height
        obj.muproperties.direction = properties.dir_map[col.direction]
        obj.muproperties.center = col.center
        obj.muproperties.collider = 'MU_COL_CAPSULE'
    elif type(col) == MuColliderBox:
        obj.muproperties.size = col.size
        obj.muproperties.center = col.center
        obj.muproperties.collider = 'MU_COL_BOX'
    elif type(col) == MuColliderWheel:
        obj.muproperties.radius = col.radius
        obj.muproperties.suspensionDistance = col.suspensionDistance
        obj.muproperties.center = col.center
        obj.muproperties.mass = col.mass
        copy_spring(obj.muproperties.suspensionSpring, col.suspensionSpring)
        copy_friction(obj.muproperties.forwardFriction, col.forwardFriction)
        copy_friction(obj.muproperties.sideFriction, col.sidewaysFriction)
        obj.muproperties.collider = 'MU_COL_WHEEL'
    if type(col) != MuColliderMesh:
        collider.build_collider(obj)
    return obj

def create_object(mu, muobj, parent, create_colliders, parents):
    obj = None
    mesh = None
    if hasattr(muobj, "shared_mesh"):
        mesh = create_mesh(mu, muobj.shared_mesh, muobj.transform.name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_mesh_object(muobj.transform.name, mesh, muobj.transform)
    elif hasattr(muobj, "skinned_mesh_renderer"):
        smr = muobj.skinned_mesh_renderer
        mesh = create_mesh(mu, smr.mesh, muobj.transform.name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_mesh_object(muobj.transform.name, mesh, muobj.transform)
        mumat = mu.materials[smr.materials[0]]
        mesh.materials.append(mumat.material)
    if hasattr(muobj, "renderer"):
        if mesh:
            mumat = mu.materials[muobj.renderer.materials[0]]
            mesh.materials.append(mumat.material)
    if not obj:
        if hasattr(muobj, "light"):
            obj = create_light(mu, muobj.light, muobj.transform)
    if not obj:
        obj = create_mesh_object(muobj.transform.name, None, muobj.transform)
    parents.append(muobj.transform.name)
    path = "/".join(parents)
    mu.objects[path] = obj
    if hasattr(muobj, "tag_and_layer"):
        obj.muproperties.tag = muobj.tag_and_layer.tag
        obj.muproperties.layer = muobj.tag_and_layer.layer
    if create_colliders and hasattr(muobj, "collider"):
        cobj = create_collider(mu, muobj)
        cobj.parent = obj
    obj.parent = parent
    for child in muobj.children:
        create_object(mu, child, obj, create_colliders, parents)
    if hasattr(muobj, "animation"):
        for clip in muobj.animation.clips:
            create_action(mu, path, clip)
    parents.remove(muobj.transform.name)
    return obj

def convert_bump(pixels, width, height):
    outp = list(pixels)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            index = (y * width + x) * 4
            p = pixels[index:index + 4]
            nx = (p[3]-128) / 127.
            nz = (p[2]-128) / 127.
            #n = [p[3],p[2],int(sqrt(1-nx**2-nz**2)*127 + 128),255]
            n = [p[3],p[2],255,255]
            outp[index:index + 4] = n
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
    if name[-4:].lower() in [".dds", ".png", ".tga"]:
        img = bpy.data.images.load(os.path.join(path, name))
        if name[-4:].lower() == ".dds":
            pixels = list(img.pixels[:])
            rowlen = img.size[0] * 4
            height = img.size[1]
            for y in range(int(height/2)):
                ind1 = y * rowlen
                ind2 = (height - 1 - y) * rowlen
                t = pixels[ind1 : ind1 + rowlen]
                pixels[ind1:ind1+rowlen] = pixels[ind2:ind2+rowlen]
                pixels[ind2:ind2+rowlen] = t
            if name[-6:-4] == "_n":
                pixels = convert_bump(pixels, img.size[0], height)
            img.pixels = pixels[:]
            img.pack(True)
    elif name[-4:].lower() == ".mbm":
        w,h, pixels = load_mbm(os.path.join(path, name))
        img = bpy.data.images.new(name, w, h)
        img.pixels[:] = map(lambda x: x / 255.0, pixels)
        img.pack(True)

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
                name = base+e
                load_image(name, path)
                tx = bpy.data.textures.new(tex.name, 'IMAGE')
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
        mumat.material = make_shader(mumat, mu)

def import_mu(self, context, filepath, create_colliders):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    mu = Mu()
    if not mu.read(filepath):
        bpy.context.user_preferences.edit.use_global_undo = undo
        operator.report({'ERROR'},
            "Unrecognized format: %s %d" % (mu.magic, mu.version))
        return {'CANCELLED'}

    create_textures(mu, os.path.dirname(filepath))
    create_materials(mu)
    mu.objects = {}
    obj = create_object(mu, mu.obj, None, create_colliders, [])
    bpy.context.scene.objects.active = obj
    obj.select = True

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class ImportMu(bpy.types.Operator, ImportHelper):
    '''Load a KSP Mu (.mu) File'''
    bl_idname = "import_object.ksp_mu"
    bl_label = "Import Mu"
    bl_description = """Import a KSP .mu model."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".mu"
    filter_glob = StringProperty(default="*.mu", options={'HIDDEN'})

    create_colliders = BoolProperty(name="Create Colliders",
            description="Disable to import only visual and hierarchy elements",
                                    default=True)

    def execute(self, context):
        keywords = self.as_keywords (ignore=("filter_glob",))
        return import_mu(self, context, **keywords)
