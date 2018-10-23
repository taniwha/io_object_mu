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

from .importerror import MuImportError
from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuColliderBox, MuColliderWheel
from .shader import make_shader
from . import collider, properties

def create_uvs(mu, uvs, bm, name):
    layer = bm.loops.layers.uv.new(name)
    for face in bm.faces:
        for loop in face.loops:
            loop[layer].uv = uvs[loop.vert.index]

def create_mesh(mu, mumesh, name):
    mesh = bpy.data.meshes.new(name)
    faces = []
    for sm in mumesh.submeshes:
        faces.extend(sm)
    bm = bmesh.new()
    bv = [None] * len(mumesh.verts)
    for i, v in enumerate(mumesh.verts):
        bv[i] = bm.verts.new(v)
    if mumesh.normals:
        for i, n in enumerate(mumesh.normals):
            bv[i].normal = n
    #FIXME how to set tangents?
    #if mumesh.tangents:
    #    for i, t in enumerate(mumesh.tangents):
    #        bv[i].tangent = t
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    for f in faces:
        bm.faces.new([bv[i] for i in f])
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    if mumesh.uvs:
        create_uvs(mu, mumesh.uvs, bm, "UV")
    if mumesh.uv2s:
        create_uvs(mu, mumesh.uv2s, bm, "UV2")
    bm.to_mesh(mesh)
    return mesh

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
    light = bpy.data.lights.new(transform.name, ltype)
    light.color = mulight.color[:3]
    light.distance = mulight.range
    light.energy = mulight.intensity
    if ltype == 'SPOT' and hasattr(mulight, "spotAngle"):
        light.spot_size = mulight.spotAngle * pi / 180
    obj = bpy.data.objects.new(transform.name, light)
    bpy.context.view_layer.objects.active = obj
    obj.rotation_mode = 'QUATERNION'
    obj.location = Vector(transform.localPosition)
    # Blender points spotlights along local -Z, unity along local +Z
    # which is Blender's +Y, so rotate 90 degrees around local X to
    # go from Unity to Blender
    rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
    obj.rotation_quaternion = Quaternion(transform.localRotation) @ rot
    obj.scale = Vector(transform.localScale)
    properties.SetPropMask(obj.muproperties.cullingMask, mulight.cullingMask)
    return obj

def create_camera(mu, mucamera, transform):
    camera = bpy.data.cameras.new(transform.name)
    #mucamera.clearFlags
    camera.type = ['PERSP', 'ORTHO'][mucamera.orthographic]
    camera.lens_unit = 'FOV'
    # blender's fov is in radians, unity's in degrees
    camera.angle = mucamera.fov * pi / 180
    camera.clip_start = mucamera.near
    camera.clip_end = mucamera.far
    obj = bpy.data.objects.new(transform.name, camera)
    bpy.context.view_layer.objects.active = obj
    obj.rotation_mode = 'QUATERNION'
    obj.location = Vector(transform.localPosition)
    # Blender points cameras along local -Z, unity along local +Z
    # which is Blender's +Y, so rotate 90 degrees around local X to
    # go from Unity to Blender
    rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
    obj.rotation_quaternion = Quaternion(transform.localRotation) @ rot
    obj.scale = Vector(transform.localScale)
    properties.SetPropMask(obj.muproperties.cullingMask, mucamera.cullingMask)
    obj.muproperties.backgroundColor = mucamera.backgroundColor
    obj.muproperties.depth = mucamera.depth
    if mucamera.clearFlags > 0:
        flags = mucamera.clearFlags - 1
        obj.muproperties.clearFlags = properties.clearflag_items[flags][0]
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
    "m_Color.r": ("data", "color", 0, 1),
    "m_Color.g": ("data", "color", 1, 1),
    "m_Color.b": ("data", "color", 2, 1),
    "m_Color.a": ("data", "color", 3, 1),
}

vector_map = {
    "r": 0, "g": 1, "b": 2, "a":3,
    "x": 0, "y": 1, "z": 2, "w":3,  # shader props not read as quaternions
}

def property_index(properties, prop):
    for i, p in enumerate(properties):
        if p.name == prop:
            return i
    return None

def shader_property(obj, prop):
    prop = prop.split(".")
    if not obj or type(obj.data) != bpy.types.Mesh:
        return None
    if not obj.data.materials:
        return None
    for mat in obj.data.materials:
        mumat = mat.mumatprop
        for subpath in ["color", "vector", "float2", "float3", "texture"]:
            propset = getattr(mumat, subpath)
            if prop[0] in propset.properties:
                if subpath == "texture":
                    print("animated texture properties not yet supported")
                    print(prop)
                    return None
                if subpath[:5] == "float":
                    rnaIndex = 0
                else:
                    rnaIndex = vector_map[prop[1]]
                propIndex = property_index(propset.properties, prop[0])
                path = "mumatprop.%s.properties[%d].value" % (subpath, propIndex)
                return mat, path, rnaIndex
    return None

def create_fcurve(action, curve, propmap):
    dp, ind, mult = propmap
    fps = bpy.context.scene.render.fps
    fc = action.fcurves.new(data_path = dp, index = ind)
    fc.keyframe_points.add(len(curve.keys))
    for i, key in enumerate(curve.keys):
        x,y = key.time * fps + bpy.context.scene.frame_start, key.value * mult
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
        if (mu_path not in mu.object_paths
            or not hasattr(mu.object_paths[mu_path], "bobj")):
            print("Unknown path: %s" % (mu_path))
            continue
        obj = mu.object_paths[mu_path].bobj

        if curve.property not in property_map:
            sp = shader_property(obj, curve.property)
            if not sp:
                print("%s: Unknown property: %s" % (mu_path, curve.property))
                continue
            obj, dp, rnaIndex = sp
            propmap = dp, rnaIndex, 1
            subpath = "obj"
        else:
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
    mesh = None
    if type(col) == MuColliderMesh:
        name = name + ".collider"
        mesh = create_mesh(mu, col.mesh, name)
    obj, cobj = collider.create_collider_object(name, mesh)

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
        collider.build_collider(cobj, obj.muproperties)
    return obj

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
        and not (hasattr(muobj, "shared_mesh") and hasattr(muobj, "renderer"))
        and not hasattr(muobj, "skinned_mesh_renderer")):
        return None
    xform = None if hasattr(muobj, "bone") else muobj.transform
    if hasattr(muobj, "shared_mesh") and hasattr(muobj, "renderer"):
        mesh = create_mesh(mu, muobj.shared_mesh, muobj.transform.name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_data_object(muobj.transform.name, mesh, xform)
        attach_material(mesh, muobj.renderer, mu)
    elif hasattr(muobj, "skinned_mesh_renderer"):
        smr = muobj.skinned_mesh_renderer
        mesh = create_mesh(mu, smr.mesh, muobj.transform.name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_data_object(muobj.transform.name, mesh, xform)
        attach_material(mesh, smr, mu)
    if not obj:
        if hasattr(muobj, "light"):
            obj = create_light(mu, muobj.light, muobj.transform)
        if hasattr(muobj, "camera"):
            obj = create_camera(mu, muobj.camera, muobj.transform)
    if hasattr(muobj, "bone"):
        #FIXME skinned_mesh_renderer attach to armature
        if obj:
            obj.parent = mu.armature_obj
            obj.parent_type = 'BONE'
            obj.parent_bone = muobj.bone
    else:
        if not obj:
            obj = create_data_object(muobj.transform.name, None, xform)
        obj.parent = parent
    if obj:
        #FIXME will lose properties from any empty objects that have properties
        #set when using an armature
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
    return obj if not hasattr(mu, "armature_obj") else mu.armature_obj

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
            if type == 1 or base[-2:].lower() == "_n" or base[-3:].lower() == "nrm":
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

def create_bone(bone_obj, edit_bones):
    xform = bone_obj.transform
    bone_obj.bone = bone = edit_bones.new(xform.name)
    # actual positions and orientations will be sorted out when building
    # the hierarchy
    bone.head = Vector((0, -0.1, 0))
    bone.tail = bone.head + Vector((0, 0, 0))
    bone.use_connect = False
    bone.use_relative_parent = False
    return bone

def psgn(x):
    return x >= 0 and 1 or -1

def process_armature(mu):
    def process_bone(mu, obj, position, rotation):
        xform = obj.transform
        obj.bone.tail = rotation @ Vector(xform.localPosition) + position
        rot = Quaternion(xform.localRotation)
        lrot = rotation @ rot
        y = 0.1
        obj.bone.head = obj.bone.tail - lrot @ Vector((0, y, 0))
        obj.bone.align_roll(lrot @ Vector((0, 0, 1)))
        for child in obj.children:
            process_bone(mu, child, obj.bone.tail, lrot)
        # must not keep references to bones when the armature leaves edit mode,
        # so keep the bone's name instead (which is what's needed for bone
        # parenting anway)
        obj.bone = obj.bone.name

    pos = Vector((0, 0, 0))
    rot = Quaternion((1, 0, 0, 0))
    #the root object has no bone
    for child in mu.obj.children:
        process_bone(mu, child, pos, rot)

def create_armature(mu):
    def create_bone_hierarchy(mu, obj, parent):
        bone = create_bone(obj, mu.armature.edit_bones)
        bone.parent = parent
        for child in obj.children:
            create_bone_hierarchy(mu, child, bone)

    name = mu.obj.transform.name
    mu.armature = bpy.data.armatures.new(name)
    mu.armature.show_axes = True
    mu.armature_obj = create_data_object(name, mu.armature, mu.obj.transform)
    ctx = bpy.context
    ctx.layer_collection.collection.objects.link(mu.armature_obj)
    #need to set the active object so edit mode can be entered
    ctx.view_layer.objects.active = mu.armature_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)

    # the armature itself is the root object
    #FIXME any properties on the root object are lost
    for child in mu.obj.children:
        create_bone_hierarchy (mu, child, None)

    process_armature(mu)
    bpy.ops.object.mode_set(mode='OBJECT')

def needs_armature(mu):
    def has_skinned_mesh(obj):
        if hasattr(obj, "skinned_mesh_renderer"):
            return True
        for child in obj.children:
            if has_skinned_mesh(child):
                return True
        return False
    return has_skinned_mesh(mu.obj)

def create_object_paths(mu, obj=None, parents=None):
    if obj == None:
        mu.objects = {}
        mu.object_paths = {}
        create_object_paths(mu, mu.obj, [])
        return
    name = obj.transform.name
    parents.append(name)
    obj.path = "/".join(parents)
    mu.objects[name] = obj
    mu.object_paths[obj.path] = obj
    for child in obj.children:
        create_object_paths(mu, child, parents)
    parents.pop()

def process_mu(mu, mudir):
    create_textures(mu, mudir)
    create_materials(mu)
    create_object_paths(mu)
    if mu.force_armature or needs_armature(mu):
        create_armature(mu)
    return create_object(mu, mu.obj, None)

def import_mu(collection, filepath, create_colliders, force_armature):
    mu = Mu()
    mu.create_colliders = create_colliders
    mu.force_armature = force_armature
    mu.collection = collection
    if not mu.read(filepath):
        raise MuImportError("Mu", "Unrecognized format: magic %x version %d"
                                  % (mu.magic, mu.version))

    return process_mu(mu, os.path.dirname(filepath))

def import_mu_op(self, context, filepath, create_colliders, force_armature):
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    collection = bpy.context.layer_collection.collection
    try:
        obj = import_mu(collection, filepath, create_colliders, force_armature)
    except MuImportError as e:
        operator.report({'ERROR'}, e.message)
        return {'CANCELLED'}
    else:
        for o in bpy.context.scene.objects:
            o.select_set('DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set('SELECT')
        return {'FINISHED'}
    finally:
        bpy.context.user_preferences.edit.use_global_undo = undo

class KSPMU_OT_ImportMu(bpy.types.Operator, ImportHelper):
    '''Load a KSP Mu (.mu) File'''
    bl_idname = "import_object.ksp_mu"
    bl_label = "Import Mu"
    bl_description = """Import a KSP .mu model."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    create_colliders: BoolProperty(name="Create Colliders",
            description="Disable to import only visual and hierarchy elements",
                                    default=True)
    force_armature: BoolProperty(name="Force Armature",
            description="Enable to force use of an armature to hold the model"
                        " hierarchy", default=True)

    def execute(self, context):
        keywords = self.as_keywords (ignore=("filter_glob",))
        return import_mu_op(self, context, **keywords)

def import_mu_menu_func(self, context):
    self.layout.operator(KSPMU_OT_ImportMu.bl_idname, text="KSP Mu (.mu)")

classes = (
    KSPMU_OT_ImportMu,
)

menus = (
    (bpy.types.TOPBAR_MT_file_import, import_mu_menu_func),
)
