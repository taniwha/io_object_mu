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
import sys

def dump_thing(thing, mu, level, exclude, dump_funcs):
	for a in dir(thing):
		if a[0] == "_" or a in ["read", "write"] or a in exclude:
			continue
		attr = getattr(thing, a)
		n = attr.__class__.__name__
		if n in dump_funcs:
			dump_funcs[n](a, mu, attr, level)
		else:
			print(("%s %s = " % ("    " * level, a)) + str(attr))

def dump_textures(mu):
	print("Textures")
	for i, tex in enumerate(mu.textures):
		print (i, tex.name, tex.type)

def dump_mattex(name, mu, mt, level):
	print("    %s %d %s %s" %
		  (name, mt.index, str(mt.scale), str(mt.offset)))

mat_dump_funcs = {
	'MuMatTex': dump_mattex
}

def dump_materials(mu):
	print("Materials")
	for i, mat in enumerate(mu.materials):
		print(i, mat.name)
		dump_thing(mat, mu, 1, [], mat_dump_funcs);

def dump_renderer(name, mu, rend, level):
	print("%s Renderer: %s = " % ("    " * level, name))
	dump_thing(rend, mu, level, [], {})

def dump_list(name, mu, lst, level):
	print("%s  %s[%d]" % ("    " * level, name, len(lst)))

mesh_dump_funcs = {
	"list": dump_list
}

def dump_mesh(name, mu, mesh, level):
	print("%s Mesh: %s = %s" % ("    " * level, name, str(mesh)))
	dump_thing(mesh, mu, level, [], mesh_dump_funcs)

def dump_skinnedmeshrenderer(name, mu, mesh, level):
	print("%s SkinnedMeshRenderer: %s = %s" % ("    " * level, name, str(mesh)))
	dump_thing(mesh, mu, level + 1, [], {})

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
