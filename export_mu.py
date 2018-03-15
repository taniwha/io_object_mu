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

import os

import bpy, bmesh
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion
from pprint import pprint
from math import pi
from bpy_extras.io_utils import ExportHelper
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import FloatVectorProperty, PointerProperty

from .mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from .mu import MuObject, MuTransform, MuMesh, MuTagLayer, MuRenderer, MuLight
from .mu import MuColliderBox, MuColliderWheel, MuMaterial, MuTexture, MuMatTex
from .mu import MuSpring, MuFriction
from .mu import MuAnimation, MuClip, MuCurve, MuKey
from .shader import make_shader
from . import properties
from .cfgnode import ConfigNode, ConfigNodeError
from .parser import parse_node

def calcVolume(mesh):
    terms=[]
    for face in mesh.tessfaces:
        a = mesh.vertices[face.vertices[0]].co
        b = mesh.vertices[face.vertices[1]].co
        for i in range(2, len(face.vertices)):
            c = mesh.vertices[face.vertices[i]].co
            vp =  a.y*b.z*c.x + a.z*b.x*c.y + a.x*b.y*c.z
            vm = -a.z*b.y*c.x - a.x*b.z*c.y - a.y*b.x*c.z
            terms.extend([vp, vm])
            b = c
    vol = 0
    for t in sorted(terms, key=abs):
        vol += t
    return vol / 6

def obj_volume(obj):
    if type(obj.data) != bpy.types.Mesh:
        return 0, 0
    if obj.muproperties.collider and obj.muproperties.collider != 'MU_COL_NONE':
        return 0, 0
    skin_mesh = obj.to_mesh(bpy.context.scene, True, 'PREVIEW')
    ext_mesh = obj.to_mesh(bpy.context.scene, True, 'RENDER')
    return calcVolume(skin_mesh), calcVolume(ext_mesh)

def model_volume(obj):
    svols = []
    evols = []
    def recurse(o):
        v = obj_volume(o)
        svols.append(v[0])
        evols.append(v[1])
        for c in o.children:
            recurse(c)
    recurse(obj)
    skinvol = 0
    extvol = 0
    for s in sorted(svols, key=abs):
        skinvol += s
    for e in sorted(evols, key=abs):
        extvol += e
    return skinvol, extvol

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
    if obj.rotation_mode != 'QUATERNION':
      transform.localRotation = obj.rotation_euler.to_quaternion()
    else:
      transform.localRotation = obj.rotation_quaternion
    transform.localScale = obj.scale
    return transform

def split_face(mesh, index):
    face = mesh.polygons[index]
    s, e = face.loop_start, face.loop_start + face.loop_total
    # extract up to two uv layers from the mesh
    uv = list(map(lambda layer:
                  list(map(lambda a:
                           a.uv,
                           layer.data[s:e])),
                  mesh.uv_layers[:2]))
    fv = list(face.vertices)
    tris = []
    for i in range(1, len(fv) - 1):
        tri = ((fv[0], tuple(map(lambda l: tuple(l[0]), uv))),
               (fv[i], tuple(map(lambda l: tuple(l[i]), uv))),
               (fv[i+1], tuple(map(lambda l: tuple(l[i+1]), uv))))
        tris.append(tri)
    return tris

def build_submeshes(mesh):
    submeshes = []
    submesh = []
    for i in range(len(mesh.polygons)):
        submesh.append(i)
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
    mesh = obj.to_mesh(bpy.context.scene, True, 'RENDER')
    submeshes = build_submeshes(mesh)
    submeshes = make_tris(mesh, submeshes)
    mumesh = MuMesh()
    vun = make_verts(mesh, submeshes)
    mumesh.verts, uvs, mumesh.normals = vun
    if uvs:
        if len(uvs[0]) > 0:
            mumesh.uvs = list(map(lambda uv: uv[0], uvs))
        if len(uvs[0]) > 1:
            mumesh.uv2s = list(map(lambda uv: uv[1], uvs))
    mumesh.submeshes = submeshes
    if mumesh.uvs:
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
        col = MuColliderWheel()
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

def make_texture(mu, tex):
    if tex.tex not in mu.textures:
        mutex = MuTexture()
        mutex.name = tex.tex
        mutex.type = tex.type
        mutex.index = len(mu.textures)
        mu.textures[tex.tex] = mutex
    mattex = MuMatTex()
    mattex.index = mu.textures[tex.tex].index
    mattex.scale = list(tex.scale)
    mattex.offset = list(tex.offset)
    return mattex

def make_property(blendprop):
    muprop = {}
    for item in blendprop:
        if type(item.value) is float:
            muprop[item.name] = item.value
        else:
            muprop[item.name] = list(item.value)
    return muprop

def make_tex_property(mu, blendprop):
    muprop = {}
    for item in blendprop:
        muprop[item.name] = make_texture(mu, item)
    return muprop

def make_material(mu, mat):
    material = MuMaterial()
    material.name = mat.name
    material.index = len(mu.materials)
    matprops = mat.mumatprop
    material.shaderName = matprops.shaderName
    material.colorProperties = make_property(matprops.color.properties)
    material.vectorProperties = make_property(matprops.vector.properties)
    material.floatProperties2 = make_property(matprops.float2.properties)
    material.floatProperties3 = make_property(matprops.float3.properties)
    material.textureProperties = make_tex_property(mu, matprops.texture.properties)
    return material

def make_renderer(mu, mesh):
    rend = MuRenderer()
    #FIXME shadows
    rend.materials = []
    for mat in mesh.materials:
        if mat.mumatprop.shaderName:
            if mat.name not in mu.materials:
                mu.materials[mat.name] = make_material(mu, mat)
            rend.materials.append(mu.materials[mat.name].index)
    if not rend.materials:
        return None
    return rend

def make_light(mu, light, obj):
    mulight = MuLight()
    mulight.type = ('SPOT', 'SUN', 'POINT', 'AREA').index(light.type)
    mulight.color = tuple(light.color) + (1.0,)
    mulight.range = light.distance
    mulight.intensity = light.energy
    mulight.spotAngle = 0.0
    mulight.cullingMask = properties.GetPropMask(obj.muproperties.cullingMask)
    if light.type == 'SPOT':
        mulight.spotAngle = light.spot_size * 180 / pi
    return mulight

light_types = {
    bpy.types.PointLamp,
    bpy.types.SunLamp,
    bpy.types.SpotLamp,
    bpy.types.HemiLamp,
    bpy.types.AreaLamp
}

exportable_types = {bpy.types.Mesh} | light_types

def make_obj(mu, obj, path = ""):
    muobj = MuObject()
    muobj.transform = make_transform (obj)
    if path:
        path += "/"
    path += muobj.transform.name
    mu.object_paths[path] = muobj
    muobj.tag_and_layer = make_tag_and_layer(obj)
    if not obj.data and obj.name[:4] == "node":
        n = AttachNode(obj, mu.inverse)
        mu.nodes.append(n)
        if not n.keep_transform():
            return None
        # Blender's empties use the +Z axis for single-arrow display, so that
        # is the most natural orientation for nodes in blender. However, KSP
        # uses the transform's +Z (Unity) axis which is Blender's +Y, so
        # rotate 90 degrees around local X to go from Blender to KSP
        rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
        muobj.transform.localRotation = muobj.transform.localRotation * rot
    elif obj.muproperties.collider and obj.muproperties.collider != 'MU_COL_NONE':
        # colliders are children of the object representing the transform so
        # they are never exported directly.
        pass
    elif obj.data:
        if type(obj.data) == bpy.types.Mesh:
            muobj.shared_mesh = make_mesh(mu, obj)
            muobj.renderer = make_renderer(mu, obj.data)
        elif type(obj.data) in light_types:
            muobj.light = make_light(mu, obj.data, obj)
            # Blender points spotlights along local -Z, unity along local +Z
            # which is Blender's +Y, so rotate -90 degrees around local X to
            # go from Blender to Unity
            rot = Quaternion((0.5**0.5,-0.5**0.5,0,0))
            muobj.transform.localRotation = rot * muobj.transform.localRotation
    for o in obj.children:
        muprops = o.muproperties
        if muprops.collider and muprops.collider != 'MU_COL_NONE':
            muobj.collider = make_collider(mu, o)
            continue
        if (o.data and type(o.data) not in exportable_types):
            continue
        child = make_obj(mu, o, path)
        if child:
            muobj.children.append(child)
    return muobj

def shader_animations(mat, path):
    animations = {}
    if not mat.animation_data:
        return animations
    for track in mat.animation_data.nla_tracks:
        if not track.strips:
            continue
        anims = []
        strip = track.strips[0]
        for curve in strip.action.fcurves:
            dp = curve.data_path.split(".")
            if dp[0] == "mumatprop" and dp[1] in ["color", "vector", "float2", "float3"]:
                anims.append((track, path, mat))
                break
            elif dp[0] == "mumatprop" and dp[1] == "texture":
                print("don't know how to export texture anims")
        if anims:
            animations[track.name] = anims
    return animations

def object_animations(obj, path):
    animations = {}
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:
            if track.strips:
                animations[track.name] = [(track, path, "obj")]
    return animations

def extend_animations(animations, anims):
    for a in anims:
        if a not in animations:
            animations[a] = []
        animations[a].extend(anims[a])

def collect_animations(obj, path=""):
    animations = {}
    if path:
        path += "/"
    path += strip_nnn(obj.name)
    extend_animations(animations, object_animations (obj, path))
    if type(obj.data) == bpy.types.Mesh:
        for mat in obj.data.materials:
            extend_animations(animations, shader_animations(mat, path))
    if type(obj.data) in light_types:
        extend_animations(animations, object_animations (obj.data, path))
    for o in obj.children:
        extend_animations(animations, collect_animations(o, path))
    return animations

def find_path_root(animations):
    paths = {}
    for clip in animations:
        for data in animations[clip]:
            objects = data[1].split("/")
            p = paths
            for o in objects:
                if not o in p:
                    p[o] = {}
                p = p[o]
    path_root = ""
    p = paths
    while len(p) == 1:
        if path_root:
            path_root += "/"
        o = list(p)[0]
        path_root += o
        p = p[o]
    return path_root

def make_key(key, mult):
    fps = bpy.context.scene.render.fps
    mukey = MuKey()
    x, y = key.co
    x -= bpy.context.scene.frame_start
    mukey.time = x / fps
    mukey.value = y * mult
    dx, dy = key.handle_left
    dx = (x - dx) / fps
    dy = (y - dy) * mult
    t1 = dy / dx
    dx, dy = key.handle_right
    dx = (dx - x) / fps
    dy = (dy - y) * mult
    t2 = dy / dx
    mukey.tangent = t1, t2
    mukey.tangentMode = 0
    return mukey

property_map = {
    "location":(
        ("m_LocalPosition.x", 1),
        ("m_LocalPosition.z", 1),
        ("m_LocalPosition.y", 1),
    ),
    "rotation_quaternion":(
        ("m_LocalRotation.w", 1),
        ("m_LocalRotation.x", -1),
        ("m_LocalRotation.z", -1),
        ("m_LocalRotation.y", -1),
    ),
    "scale":(
        ("m_LocalScale.x", 1),
        ("m_LocalScale.z", 1),
        ("m_LocalScale.y", 1),
    ),
    "color":(
        ("m_Color.r", 1),
        ("m_Color.g", 1),
        ("m_Color.b", 1),
        ("m_Color.a", 1),#probably not used
    ),
    "energy":(
        ("m_Intensity", 1),
    ),
}

vector_map={
    "color": (".r", ".g", ".b", ".a"),
    "vector": (".x", ".y", ".z", ".w"),
}

def make_curve(mu, curve, path, typ):
    mucurve = MuCurve()
    mucurve.path = path
    if typ == "obj":
        property, mult = property_map[curve.data_path][curve.array_index]
    elif type(typ) == bpy.types.Material:
        dp = curve.data_path.split(".")
        v = {}
        str = "v['property'] = typ.%s.name" % (".".join(dp[:-1]))
        exec (str, {}, locals())
        property = v["property"]
        mult = 1
        if dp[1] in ["color", "vector"]:
            property += vector_map[dp[1]][curve.array_index]
    mucurve.property = property
    mucurve.type = 0
    mucurve.wrapMode = (8, 8)
    mucurve.keys = []
    for key in curve.keyframe_points:
        mucurve.keys.append(make_key(key, mult))
    return mucurve

def make_animations(mu, animations, anim_root):
    anim = MuAnimation()
    anim.clip = ""
    anim.autoPlay = False
    for clip_name in animations:
        clip = MuClip()
        clip.name = clip_name
        clip.lbCenter = (0, 0, 0)
        clip.lbSize = (0, 0, 0)
        clip.wrapMode = 0   #FIXME
        for data in animations[clip_name]:
            track, path, typ = data
            path = path[len(anim_root) + 1:]
            strip = track.strips[0]
            for curve in strip.action.fcurves:
                clip.curves.append(make_curve(mu, curve, path, typ))
        anim.clips.append(clip)
    return anim

def find_template(mu, filepath):
    base = os.path.splitext(filepath)
    cfg = base[0] + ".cfg"

    cfgin = mu.name + ".cfg.in"
    if cfgin in bpy.data.texts:
        return cfg, bpy.data.texts[cfgin].as_string()

    cfgin = base[0] + ".cfg.in"
    if os.path.isfile (cfgin):
        return cfg, open(cfgin, "rt").read()

    return None, None

def generate_cfg(mu, filepath):
    cfg, template = find_template(mu, filepath)
    if not template:
        return
    try:
        node = ConfigNode.load(template)
    except ConfigNodeError as e:
        return
    part = node.GetNode("PART")
    if not part:
        return
    parse_node(mu, node)
    mu.nodes.sort()
    for n in mu.nodes:
        n.save(part)
    of = open(cfg, "wt")
    for n in node.nodes:
        of.write(n[0] + " " + n[1].ToString())

def export_object(obj, filepath):
    animations = collect_animations(obj)
    anim_root = find_path_root(animations)
    mu = Mu()
    mu.name = strip_nnn(obj.name)
    mu.object_paths = {}
    mu.materials = {}
    mu.textures = {}
    mu.nodes = []
    mu.inverse = obj.matrix_world.inverted()
    mu.obj = make_obj(mu, obj)
    mu.materials = list(mu.materials.values())
    mu.materials.sort(key=lambda x: x.index)
    mu.textures = list(mu.textures.values())
    mu.textures.sort(key=lambda x: x.index)
    if anim_root:
        anim_root_obj = mu.object_paths[anim_root]
        anim_root_obj.animation = make_animations(mu, animations, anim_root)
    mu.write(filepath)
    mu.skin_volume, mu.ext_volume = model_volume(obj)
    generate_cfg(mu, filepath)
    return mu

def export_mu(operator, context, filepath):
    export_object (context.active_object, filepath)
    return {'FINISHED'}

class ExportMu(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File'''
    bl_idname = "export_object.ksp_mu"
    bl_label = "Export Mu"

    filename_ext = ".mu"
    filter_glob = StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (context.active_object != None
                and (not context.active_object.data
                     or type(context.active_object.data) == bpy.types.Mesh))

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob"))
        return export_mu(self, context, **keywords)

class ExportMu_quick(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File, defaulting name to selected object'''
    bl_idname = "export_object.ksp_mu_quick"
    bl_label = "Export Mu (quick)"

    filename_ext = ".mu"
    filter_glob = StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (context.active_object != None
                and (not context.active_object.data
                     or type(context.active_object.data) == bpy.types.Mesh))

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob"))
        return export_mu(self, context, **keywords)

    def invoke(self, context, event):
        if context.active_object != None:
            self.filepath = strip_nnn(context.active_object.name) + self.filename_ext
        return ExportHelper.invoke(self, context, event)

class MuVolume(bpy.types.Operator):
    bl_idname = 'object.mu_volume'
    bl_label = 'Mu Volume'

    @classmethod
    def poll(cls, context):
        return (context.active_object != None
                and (not context.active_object.data
                     or type(context.active_object.data) == bpy.types.Mesh))

    def execute(self, context):
        obj = context.active_object
        if obj.data and type(obj.data) == bpy.types.Mesh:
            vol = obj_volume(obj)
        else:
            vol = model_volume(obj)
        self.report({'INFO'}, 'Skin Volume = %g m^3, Ext Volume = %g m^3' % vol)
        return {'FINISHED'}

class VIEW3D_PT_tools_mu_export(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Mu Tools"
    bl_context = "objectmode"
    bl_label = "Export Mu"

    def draw(self, context):
        layout = self.layout
        #col = layout.column(align=True)
        layout.operator("export_object.ksp_mu_quick", text = "Export Mu Model");
        layout.operator("object.mu_volume", text = "Calc Mu Volume");

def swapyz(vec):
    return vec[0], vec[2], vec[1]

class AttachNode:
    node_types = ["stack", "attach"]
    def __init__(self, obj, inv):
        self.name = strip_nnn(obj.name)
        self.parts = self.name.split("_", 2)
        ind = self.parts[1] == "stack" and 2 or 1
        self.id = "_".join(self.parts[ind:])
        self.pos = swapyz((inv*obj.matrix_world.col[3])[:3])
        self.dir = swapyz((inv*obj.matrix_world.col[2])[:3])
        self.size = obj.muproperties.nodeSize
        self.method = obj.muproperties.nodeMethod
        self.crossfeed = obj.muproperties.nodeCrossfeed
        self.rigid = obj.muproperties.nodeRigid
    def __lt__(self, other):
        return self.cmp(other) < 0
    def __eq__(self, other):
        return self.cmp(other) == 0
    def __gt__(self, other):
        return self.cmp(other) > 0
    def cmp(self, other):
        # parts[0] will always be "node"
        if self.parts[1] == other.parts[1]:
            x = len(self.parts) - len(other.parts)
            if x != 0:
                return x
            if len(self.parts) < 3:
                return 0
            if self.parts[2] == other.parts[2]:
                return 0
            if self.parts[2] == "bottom":
                return 1
            if self.parts[2] == "top":
                if other.parts[2] == "bottom":
                    return -1
                else:
                    return 1
            if other.parts[2] == "bottom":
                return -1
            if other.parts[2] == "top":
                if self.parts[2] == "bottom":
                    return 1
                else:
                    return -1
            return self.parts[2] > other.parts[2] and 1 or -1
        elif (self.parts[1] in self.node_types
              and other.parts[1] in self.node_types):
            return ord(other.parts[1][0]) - ord(self.parts[1][0])
        else:
            return self.parts[1] > other.parts[1] and 1 or -1
    def __repr__(self):
        return self.name + self.pos.__repr__() + self.dir.__repr__()
    def methodval(self):
        for i, enum in enumerate(properties.method_items):
            if enum[0] == self.method:
                return i
        return 0
    def cfgstring(self):
        pos = tuple(map (lambda x: x * x > 1e-11 and x or 0, self.pos))
        dir = tuple(map (lambda x: x * x > 1e-11 and x or 0, self.dir))
        return "%g, %g, %g, %g, %g, %g, %d, %d, %d, %d" % (pos + dir + (self.size,self.methodval(), int(self.crossfeed), int(self.rigid)))
    def cfgnode(self):
        node = ConfigNode ()
        node.AddValue ("name", self.id)
        node.AddValue ("transform", self.name)
        node.AddValue ("size", self.size)
        node.AddValue ("method", self.method)
        node.AddValue ("crossfeed", self.crossfeed)
        node.AddValue ("rigid", self.rigid)
        return node
    def keep_transform(self):
        return self.parts[1] not in ["attach"]
    def save(self, cfg):
        if self.parts[1] in ["attach"]:
            # currently, KSP fails to check for attach NODEs so must use the
            # old format
            cfg.AddValue (self.name, self.cfgstring())
        else:
            cfg.AddNode("NODE", self.cfgnode())
