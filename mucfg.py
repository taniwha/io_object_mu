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
from mu import Mu, MuEnum, MuMatTex
from cfgnode import ConfigNode
import sys

def add_dict(thing, mu, node, add_funcs):
    for a in thing:
        attr = thing[a]
        n = attr.__class__.__name__
        if n in add_funcs:
            add_funcs[n](a, mu, attr, node)
        elif type(attr) is float:
            node.AddValue(a, "%.9g" % attr)
        else:
            node.AddValue(a, str(attr))

def add_vector(name, mu, vec, node):
    if len(vec) == 2:
        node.AddValue(name, "%.9g, %.9g" % vec)
    elif len(vec) == 3:
        node.AddValue(name, "%.9g, %.9g, %.9g" % vec)
    elif len(vec) == 4:
        node.AddValue(name, "%.9g %.9g, %.9g, %.9g" % vec)

def add_thing(thing, mu, node, exclude, add_funcs):
    for a in dir(thing):
        if a[0] == "_" or a in ["read", "write"] or a in exclude:
            continue
        attr = getattr(thing, a)
        n = attr.__class__.__name__
        if type(attr) is dict:
            if attr:
                dn = node.AddNewNode(a)
                add_dict(attr, mu, dn, add_funcs)
        elif type(attr) is float:
            node.AddValue(a, "%.9g" % attr)
        else:
            if a in add_funcs:
                add_funcs[a](a, mu, attr, node)
            elif n in add_funcs:
                add_funcs[n](a, mu, attr, node)
            else:
                node.AddValue(a, str(attr))

def add_textures(mu, node):
    texnode = node.AddNewNode("Textures")
    for tex in mu.textures:
        texnode.AddValue(tex.name, tex.type)

def add_mattex(name, mu, mt, node):
    node.AddValue("name", name);
    node.AddValue("index", mt.index)
    add_vector("scale", mu, mt.scale, node);
    add_vector("offset", mu, mt.offset, node);

mat_add_funcs = {
    'tuple': add_vector,
    'MuMatTex': add_mattex
}

def add_materials(mu, cfg):
    mat_node = cfg.AddNewNode("Materials")
    for mat in enumerate(mu.materials):
        add_thing(mat[1], mu, mat_node, [], mat_add_funcs);

def add_bone_weight(name, mu, weight, node):
    weights = ""
    for i in range(4):
        iw = weight.indices[i], weight.weights[i]
        weights = weights + (", %d, %.9g" % iw)
    node.AddValue("weights", weights[2:])

def add_bone_weights(name, mu, weights, node):
    weights_node = node.AddNewNode(name)
    for weight in weights:
        add_bone_weight(name, mu, weight, weights_node)

def add_bind_poses(name, mu, poses, node):
    poses_node = node.AddNewNode(name)
    for pose in poses:
        add_vector("pose", mu, pose, poses_node)

def add_uvs(name, mu, uvs, node):
    uvs_node = node.AddNewNode(name)
    for uv in uvs:
        add_vector("uv", mu, uv, uvs_node)

def add_normals(name, mu, normals, node):
    normals_node = node.AddNewNode(name)
    for normal in normals:
        add_vector("norm", mu, normal, normals_node)

def add_tangents(name, mu, tangents, node):
    tangents_node = node.AddNewNode(name)
    for tangent in tangents:
        add_vector("tan", mu, tangent, tangents_node)

def add_verts(name, mu, verts, node):
    verts_node = node.AddNewNode(name)
    for vert in verts:
        add_vector("vert", mu, vert, verts_node)

def add_colors(name, mu, colors, node):
    colors_node = node.AddNewNode(name)
    for color in colors:
        add_vector("color", mu, color, colors_node)

def add_tris(name, mu, tris, node):
    tris_node = node.AddNewNode("tris")
    for tri in tris:
        tris_node.AddValue("tri", "%d %d %d" % tri)

def add_submeshes(name, mu, submeshes, node):
    submeshes_node = node.AddNewNode(name)
    for tris in submeshes:
        add_tris("submesh", mu, tris, submeshes_node)

mesh_add_funcs = {
    "colors": add_colors,
    "uvs": add_uvs,
    "uv2s": add_uvs,
    "normals": add_normals,
    "verts": add_verts,
    "tangents": add_tangents,
    "submeshes": add_submeshes,
    "boneWeights": add_bone_weights,
    "bindPoses": add_bind_poses,
}

def add_mesh(name, mu, mesh, node):
    mesh_node = node.AddNewNode("Mesh")
    add_thing(mesh, mu, mesh_node, [], mesh_add_funcs)

def add_bones(name, mu, bones, node):
    for b in bones:
        node.AddValue("bone", b)

def add_materials_sub(name, mu, materials, node):
    for m in materials:
        node.AddValue("material", m)

sharedmesh_add_funcs = {
    "center": add_vector,
    "size": add_vector,
    "bones": add_bones,
    "materials": add_materials_sub,
    "MuMesh": add_mesh,
}

renderer_add_funcs = {
    "materials": add_materials_sub,
}

def add_renderer(name, mu, mesh, node):
    r_node = node.AddNewNode("Renderer")
    add_thing(mesh, mu, r_node, [], renderer_add_funcs)

def add_skinnedmeshrenderer(name, mu, mesh, node):
    smr_node = node.AddNewNode("SkinnedMeshRenderer")
    add_thing(mesh, mu, smr_node, [], sharedmesh_add_funcs)

def add_transform(name, mu, xform, node):
    xform_node = node.AddNewNode("Transform")
    xform_node.AddValue("name", xform.name)
    add_vector("localPosition", mu, xform.localPosition, xform_node);
    add_vector("localRotation", mu, xform.localRotation, xform_node);
    add_vector("localScale", mu, xform.localScale, xform_node);

def add_taglayer(name, mu, taglayer, node):
    tag_node = node.AddNewNode("TagLayer")
    tag_node.AddValue("tag", taglayer.tag)
    tag_node.AddValue("layer", str(taglayer.layer))

def add_friction(name, mu, friction, node):
    friction_node = node.AddNewNode("Friction")
    add_thing(friction, mu, friction_node, [], {})

def add_spring(name, mu, spring, node):
    sprint_node = node.AddNewNode("Spring")
    add_thing(spring, mu, sprint_node, [], {})

collider_add_funcs = {
    "center": add_vector,
    "size": add_vector,
    "MuMesh": add_mesh,
    "MuFriction": add_friction,
    "MuSpring": add_spring,
}

def add_collider(name, mu, collider, node):
    n = collider.__class__.__name__
    collider_node = node.AddNewNode("Collider")
    collider_node.AddValue ("type", n[10:]) #strip leading "MuCollider"
    add_thing(collider, mu, collider_node, ["has_trigger"], collider_add_funcs)

light_add_funcs = {
    "color": add_vector,
}

def add_light(name, mu, light, node):
    light_node = node.AddNewNode("Light")
    add_thing(light, mu, light_node, [], light_add_funcs)

key_add_funcs = {
    "tuple": add_vector,
}

def add_key(name, mu, key, node):
    key_node = node.AddNewNode("Key")
    add_thing(key, mu, key_node, [], key_add_funcs)

def add_keys(name, mu, keys, node):
    keys_node = node.AddNewNode ("Keys")
    for key in keys:
        add_key ("", mu, key, keys_node)

curve_add_funcs = {
    "tuple": add_vector,
    "keys": add_keys,
}

def add_curve(name, mu, curve, node):
    curve_node = node.AddNewNode("Curve")
    add_thing(curve, mu, curve_node, [], curve_add_funcs)

def add_curves(name, mu, curves, node):
    curves_node = node.AddNewNode ("Curves")
    for curve in curves:
        add_curve ("", mu, curve, curves_node)

clip_add_funcs = {
    "tuple": add_vector,
    "curves": add_curves,
}

def add_clip(name, mu, clip, node):
    clip_node = node.AddNewNode("Clip")
    add_thing(clip, mu, clip_node, [], clip_add_funcs)

def add_clips(name, mu, clips, node):
    clips_node = node.AddNewNode("Clips")
    for clip in clips:
        add_clip ("", mu, clip, clips_node)

animation_add_funcs = {
    "clips": add_clips,
}

def add_animation(name, mu, anim, node):
    anim_node = node.AddNewNode("Animation")
    add_thing(anim, mu, anim_node, [], animation_add_funcs)

object_add_funcs={
    "MuTransform": add_transform,
    "MuTagLayer": add_taglayer,
    "MuRenderer": add_renderer,
    "MuMesh": add_mesh,
    "MuSkinnedMeshRenderer": add_skinnedmeshrenderer,
    "MuLight": add_light,
    "MuColliderMesh": add_collider,
    "MuColliderSphere": add_collider,
    "MuColliderCapsule": add_collider,
    "MuColliderBox": add_collider,
    "MuColliderWheel": add_collider,
    "MuAnimation": add_animation,
}

def add_object(mu, obj, node):
    obj_node = node.AddNewNode("Object")
    add_thing(obj, mu, obj_node, ["children"], object_add_funcs)

    for child in obj.children:
        add_object(mu, child, obj_node)

def makecfg(fname):
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    cfg = ConfigNode()
    add_textures(mu, cfg)
    add_materials(mu, cfg)
    add_object(mu, mu.obj, cfg)
    print(cfg.ToString())

for f in sys.argv[1:]:
    makecfg(f)
