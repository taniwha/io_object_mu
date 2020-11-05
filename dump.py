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
from mu import Mu
import sys

def dump_dict(thing, mu, level, dump_funcs):
    """
    Dump a dictionary of attributes to fp.

    Args:
        thing: (todo): write your description
        mu: (todo): write your description
        level: (int): write your description
        dump_funcs: (todo): write your description
    """
    for a in thing:
        attr = thing[a]
        n = attr.__class__.__name__
        if n in dump_funcs:
            dump_funcs[n](a, mu, attr, level)
        else:
            print(("%s%s = " % ("    " * level, a)) + str(attr))

def dump_thing(thing, mu, level, exclude, dump_funcs):
    """
    Dump thing toml file.

    Args:
        thing: (todo): write your description
        mu: (todo): write your description
        level: (int): write your description
        exclude: (list): write your description
        dump_funcs: (todo): write your description
    """
    for a in dir(thing):
        if a[0] == "_" or a in ["read", "write"] or a in exclude:
            continue
        attr = getattr(thing, a)
        n = attr.__class__.__name__
        if type(attr) is dict and attr:
            print(("%s%s = {" % ("    " * level, a)))
            dump_dict(attr, mu, level + 1, dump_funcs)
            print(("%s}" % ("    " * level,)))
        else:
            if n in dump_funcs:
                dump_funcs[n](a, mu, attr, level)
            else:
                print(("%s%s = " % ("    " * level, a)) + str(attr))

def dump_textures(mu):
    """
    Dump textures all texts in a list

    Args:
        mu: (todo): write your description
    """
    print("Textures")
    for i, tex in enumerate(mu.textures):
        print (i, tex.name, tex.type)

def dump_mattex(name, mu, mt, level):
    """
    Dump matlab matrix

    Args:
        name: (str): write your description
        mu: (todo): write your description
        mt: (todo): write your description
        level: (int): write your description
    """
    print("%s%s %d %s %s" %
          ("    " * level, name, mt.index, str(mt.scale), str(mt.offset)))

mat_dump_funcs = {
    'MuMatTex': dump_mattex
}

def dump_materials(mu):
    """
    Dump material matrix of states.

    Args:
        mu: (array): write your description
    """
    print("Materials")
    for i, mat in enumerate(mu.materials):
        print(i, mat.name)
        dump_thing(mat, mu, 1, [], mat_dump_funcs);

def dump_renderer(name, mu, rend, level):
    """
    Dump renderer

    Args:
        name: (str): write your description
        mu: (todo): write your description
        rend: (todo): write your description
        level: (todo): write your description
    """
    print("%s Renderer: %s = " % ("    " * level, name))
    dump_thing(rend, mu, level, [], {})

def dump_list(name, mu, lst, level):
    """
    Dump a list of values.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        lst: (list): write your description
        level: (int): write your description
    """
    print("%s  %s[%d]" % ("    " * level, name, len(lst)))
    for l in lst:
        print("%s  %s" % ("    " * (level + 1), str(l)))

mesh_dump_funcs = {
    "list": dump_list,
}

def dump_mesh(name, mu, mesh, level):
    """
    Dump mesh to a mesh.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        mesh: (todo): write your description
        level: (int): write your description
    """
    print("%s Mesh: %s = %s" % ("    " * level, name, str(mesh)))
    #dump_thing(mesh, mu, level, [], mesh_dump_funcs)

sharedmesh_dump_funcs = {
    "list": dump_list,
    "MuMesh": dump_mesh,
}

def dump_skinnedmeshrenderer(name, mu, mesh, level):
    """
    Dump a meshmeshrendmesh object.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        mesh: (todo): write your description
        level: (int): write your description
    """
    print("%s SkinnedMeshRenderer: %s = %s" % ("    " * level, name, str(mesh)))
    #dump_thing(mesh, mu, level + 1, [], sharedmesh_dump_funcs)

def dump_light(name, mu, mesh, level):
    """
    Dump a geojson - formatted structure.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        mesh: (todo): write your description
        level: (int): write your description
    """
    print("%s Light: %s" % ("    " * level, name))
    dump_thing(mesh, mu, level, [], mesh_dump_funcs)

def dump_friction(name, mu, col, level):
    """
    Dump a variable as a text file.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        col: (todo): write your description
        level: (int): write your description
    """
    print("%s Friction: %s = " % ("    " * level, name))
    dump_thing(col, mu, level + 1, [], {})

def dump_spring(name, mu, col, level):
    """
    Dump a nested list of dictionaries.

    Args:
        name: (str): write your description
        mu: (int): write your description
        col: (int): write your description
        level: (int): write your description
    """
    print("%s Spring: %s = " % ("    " * level, name))
    dump_thing(col, mu, level + 1, [], {})

collider_dump_funcs = {
    "MuFriction": dump_friction,
    "MuSpring": dump_spring,
}

def dump_collider(name, mu, col, level):
    """
    Dump data structure of the given variable

    Args:
        name: (str): write your description
        mu: (array): write your description
        col: (int): write your description
        level: (int): write your description
    """
    print("%s Collider: %s = " % ("    " * level, name))
    dump_thing(col, mu, level + 1, [], collider_dump_funcs)

def dump_key(name, mu, key, level):
    """
    Dump a key.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        key: (str): write your description
        level: (int): write your description
    """
    print("%s Key: %s = " % ("    " * level, name))
    dump_thing(key, mu, level, [], {})

def dump_curve(name, mu, curve, level):
    """
    Dump curve ascii.

    Args:
        name: (str): write your description
        mu: (array): write your description
        curve: (todo): write your description
        level: (int): write your description
    """
    print("%s Curve: %s = " % ("    " * level, name))
    dump_thing(curve, mu, level, ["keys"], {})
    for i, key in enumerate(curve.keys):
        dump_key("key", mu, key, level + 1)

def dump_clip(name, mu, clip, level):
    """
    Dump clip curves.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        clip: (bool): write your description
        level: (int): write your description
    """
    print("%s Clip: %s = " % ("    " * level, name))
    dump_thing(clip, mu, level, ["curves", "name"], {})
    for i, curve in enumerate(clip.curves):
        dump_curve("curve", mu, curve, level + 1)

def dump_animation(name, mu, ani, level):
    """
    Dump animation dataframe.

    Args:
        name: (str): write your description
        mu: (todo): write your description
        ani: (todo): write your description
        level: (int): write your description
    """
    print("%s Animation: %s = " % ("    " * level, name))
    dump_thing(ani, mu, level, ["clips", "name"], {})
    for i, clip in enumerate(ani.clips):
        dump_clip(clip.name, mu, clip, level + 1)

object_dump_funcs={
    "MuRenderer": dump_renderer,
    "MuMesh": dump_mesh,
    "MuSkinnedMeshRenderer": dump_skinnedmeshrenderer,
    "MuLight": dump_light,
    "MuColliderMesh": dump_collider,
    "MuColliderSphere": dump_collider,
    "MuColliderCapsule": dump_collider,
    "MuColliderBox": dump_collider,
    "MuColliderWheel": dump_collider,
    "MuAnimation": dump_animation,
}

def dump_object(mu, obj, level=0):
    """
    Dump a python object to stdout.

    Args:
        mu: (todo): write your description
        obj: (todo): write your description
        level: (int): write your description
    """
    trans = obj.transform
    print("%s%s" % ("    " * level, trans.name))
    print("%s  lp %s" % ("    " * level, str(trans.localPosition)))
    print("%s  lr %s" % ("    " * level, str(trans.localRotation)))
    print("%s  ls %s" % ("    " * level, str(trans.localScale)))
    if hasattr(obj, "tag_and_layer"):
        tl = obj.tag_and_layer
        print("%s  %s %d" % ("    " * level, tl.tag, tl.layer))
    dump_thing(obj, mu, level, ["transform", "tag_and_layer", "children"],
                object_dump_funcs)

    for child in obj.children:
        dump_object(mu, child, level + 1)

def dump(fname):
    """
    Dump a genotype object to a file.

    Args:
        fname: (str): write your description
    """
    mu = Mu()
    if not mu.read(fname):
        print("could not read: " + fname)
        raise
    print(mu.version)
    dump_textures(mu)
    dump_materials(mu)
    dump_object(mu, mu.obj)

for f in sys.argv[1:]:
    print(f)
    dump(f)
