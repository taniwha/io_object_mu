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
        else:
            node.AddValue(a, str(attr))

def add_thing(thing, mu, node, exclude, add_funcs):
    for a in dir(thing):
        if a[0] == "_" or a in ["read", "write"] or a in exclude:
            continue
        attr = getattr(thing, a)
        n = attr.__class__.__name__
        if type(attr) is dict:
            if attr:
                dn = node.AddNode(a)
                add_dict(attr, mu, dn, add_funcs)
        else:
            if a in add_funcs:
                add_funcs[a](a, mu, attr, node)
            elif n in add_funcs:
                add_funcs[n](a, mu, attr, node)
            else:
                node.AddValue(a, str(attr))

def add_textures(mu, node):
    texnode = node.AddNode("Textures")
    for tex in mu.textures:
        texnode.AddValue("tex.name", tex.type)

def add_mattex(name, mu, mt, node):
    node.AddValue("name", name);
    node.AddValue("index", mt.index)
    add_tuple("scale", mu, mt.scale, node);
    add_tuple("offset", mu, mt.offset, node);

def add_tuple(name, mu, val, node):
    s = ""
    for v in val:
        s = s + (", %.9g" % v)
    node.AddValue(name, s[2:])

mat_add_funcs = {
    'tuple': add_tuple,
    'MuMatTex': add_mattex
}

def add_materials(mu, cfg):
    mat_node = cfg.AddNode("Materials")
    for mat in enumerate(mu.materials):
        add_thing(mat[1], mu, mat_node, [], mat_add_funcs);

def dump_renderer(name, mu, rend, level):
    print("%s Renderer: %s = " % ("    " * level, name))
    dump_thing(rend, mu, level, [], {})

def add_list(name, mu, lst, node):
    pass
    print("%s[%d]" % (name, len(lst)))
    #for l in lst:
    #    print("%s  %s" % ("    " * (level + 1), str(l)))

def add_bone_weight(name, mu, weight, node):
    weights = ""
    for i in range(4):
        iw = weight.indices[i], weight.weights[i]
        weights = weights + (", %d, %.9g" % iw)
    node.AddValue("weights", weights[2:])

def add_bone_weights(name, mu, weights, node):
    weights_node = node.AddNode(name)
    for weight in weights:
        add_bone_weight(name, mu, weight, weights_node)

def add_bind_poses(name, mu, poses, node):
    poses_node = node.AddNode(name)
    for pose in poses:
        add_tuple("pose", mu, pose, poses_node)

def add_uvs(name, mu, uvs, node):
    uvs_node = node.AddNode(name)
    for uv in uvs:
        add_tuple("uv", mu, uv, uvs_node)

def add_normals(name, mu, normals, node):
    normals_node = node.AddNode(name)
    for normal in normals:
        add_tuple("norm", mu, normal, normals_node)

def add_tangents(name, mu, tangents, node):
    tangents_node = node.AddNode(name)
    for tangent in tangents:
        add_tuple("tan", mu, tangent, tangents_node)

def add_verts(name, mu, verts, node):
    verts_node = node.AddNode(name)
    for vert in verts:
        add_tuple("vert", mu, vert, verts_node)

def add_tris(name, mu, tris, node):
    tris_node = node.AddNode("tris")
    for tri in tris:
        tris_node.AddValue("tri", "%d %d %d" % tri)

def add_submeshes(name, mu, submeshes, node):
    submeshes_node = node.AddNode(name)
    for tris in submeshes:
        add_tris("submesh", mu, tris, submeshes_node)

mesh_dump_funcs = {
    "list": add_list,
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
    mesh_node = node.AddNode("Mesh")
    add_thing(mesh, mu, mesh_node, [], mesh_dump_funcs)

def add_bones(name, mu, bones, node):
    for b in bones:
        node.AddValue("bone", b)

def add_materials_sub(name, mu, materials, node):
    for m in materials:
        node.AddValue("material", m)

def add_vector(name, mu, vec, node):
    node.AddValue(name, "%.9g, %.9g, %.9g" % vec)

def add_quaternion(name, mu, vec, node):
    node.AddValue(name, "%.9g, %.9g, %.9g, %.9g" % vec)

sharedmesh_add_funcs = {
    "center": add_vector,
    "size": add_vector,
    "bones": add_bones,
    "materials": add_materials_sub,
    "MuMesh": add_mesh,
}

def add_skinnedmeshrenderer(name, mu, mesh, node):
    smr_node = node.AddNode("SkinnedMeshRenderer")
    add_thing(mesh, mu, smr_node, [], sharedmesh_add_funcs)

def dump_light(name, mu, mesh, level):
    print("%s Light: %s" % ("    " * level, name))
    dump_thing(mesh, mu, level, [], mesh_dump_funcs)

def dump_friction(name, mu, col, level):
    print("%s Friction: %s = " % ("    " * level, name))
    dump_thing(col, mu, level + 1, [], {})

def dump_spring(name, mu, col, level):
    print("%s Spring: %s = " % ("    " * level, name))
    dump_thing(col, mu, level + 1, [], {})

collider_dump_funcs = {
    "MuFriction": dump_friction,
    "MuSpring": dump_spring,
}

def dump_collider(name, mu, col, level):
    print("%s Collider: %s = " % ("    " * level, name))
    dump_thing(col, mu, level + 1, [], collider_dump_funcs)

def dump_key(name, mu, key, level):
    print("%s Key: %s = " % ("    " * level, name))
    dump_thing(key, mu, level, [], {})

def dump_curve(name, mu, curve, level):
    print("%s Curve: %s = " % ("    " * level, name))
    dump_thing(curve, mu, level, ["keys"], {})
    for i, key in enumerate(curve.keys):
        dump_key("key", mu, key, level + 1)

def dump_clip(name, mu, clip, level):
    print("%s Clip: %s = " % ("    " * level, name))
    dump_thing(clip, mu, level, ["curves", "name"], {})
    for i, curve in enumerate(clip.curves):
        dump_curve("curve", mu, curve, level + 1)

def dump_animation(name, mu, ani, level):
    print("%s Animation: %s = " % ("    " * level, name))
    dump_thing(ani, mu, level, ["clips", "name"], {})
    for i, clip in enumerate(ani.clips):
        dump_clip(clip.name, mu, clip, level + 1)

def add_transform(name, mu, xform, node):
    node = node.AddNode("Transform")
    node.AddValue("name", xform.name)
    add_vector("localPosition", mu, xform.localPosition, node);
    add_quaternion("localRotation", mu, xform.localRotation, node);
    add_vector("localScale", mu, xform.localScale, node);

def add_taglayer(name, mu, taglayer, node):
    node = node.AddNode("TagLayer")
    node.AddValue("tag", taglayer.tag)
    node.AddValue("layer", str(taglayer.layer))

object_add_funcs={
    "MuTransform": add_transform,
    "MuTagLayer": add_taglayer,
#    "MuRenderer": add_renderer,
#    "MuMesh": add_mesh,
    "MuSkinnedMeshRenderer": add_skinnedmeshrenderer,
#    "MuLight": add_light,
#    "MuColliderMesh": add_collider,
#    "MuColliderSphere": add_collider,
#    "MuColliderCapsule": add_collider,
#    "MuColliderBox": add_collider,
#    "MuColliderWheel": add_collider,
#    "MuAnimation": add_animation,
}

def add_object(mu, obj, node):
    obj_node = node.AddNode("Object")
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
