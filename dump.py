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
			print(("%s %s = " % ("	  " * level, a)) + `attr`)

def dump_textures(mu):
	print("Textures")
	for i, tex in enumerate(mu.textures):
		print (i, tex.name, tex.type)

def dump_mattex(name, mu, mt, level):
	print("    %s %d %s %s" %
		  (name, mt.index, `mt.scale`, `mt.offset`))

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
	print("%s Mesh: %s = %s" % ("	 " * level, name, `mesh`))
	dump_thing(mesh, mu, level, [], mesh_dump_funcs)

def dump_collider(name, mu, col, level):
	print("%s Collider: %s = " % ("    " * level, name))
	dump_thing(col, mu, level, [], {})

def dump_key(name, mu, key, level):
	print("%s Key: %s = " % ("	" * level, name))
        dump_thing(key, mu, level, [], {})

def dump_curve(name, mu, curve, level):
	print("%s Curve: %s = " % ("	" * level, name))
        dump_thing(curve, mu, level, ["keys"], {})
	for i, key in enumerate(curve.keys):
            dump_key("key", mu, key, level + 1)

def dump_clip(name, mu, clip, level):
	print("%s Clip: %s = " % ("	" * level, name))
        dump_thing(clip, mu, level, ["curves", "name"], {})
	for i, curve in enumerate(clip.curves):
            dump_curve("curve", mu, curve, level + 1)

def dump_animation(name, mu, ani, level):
	print("%s Animation: %s = " % ("	" * level, name))
	dump_thing(ani, mu, level, ["clips", "name"], {})
	for i, clip in enumerate(ani.clips):
            dump_clip(clip.name, mu, clip, level + 1)

object_dump_funcs={
	"MuRenderer": dump_renderer,
	"MuMesh": dump_mesh,
	"MuColliderMesh": dump_collider,
	"MuColliderCapsule": dump_collider,
	"MuAnimation": dump_animation,
}

def dump_object(mu, obj, level=0):
	trans = obj.transform
	print("%s%s" % ("    " * level, trans.name))
	print("%s  %s" % ("    " * level, `trans.localPosition`))
	print("%s  %s" % ("    " * level, `trans.localRotation`))
	print("%s  %s" % ("    " * level, `trans.localScale`))
	tl = obj.tag_and_layer
	print("%s  %s %d" % ("	  " * level, tl.tag, tl.layer))
	dump_thing(obj, mu, level, ["transform", "tag_and_layer", "children"],
				object_dump_funcs)

	for child in obj.children:
		dump_object(mu, child, level + 1)

def dump(fname):
	mu = Mu()
	if not mu.read(fname):
		print("could not read: " + fname)
		return
	dump_textures(mu)
	dump_materials(mu)
	dump_object(mu, mu.obj)

for f in sys.argv[1:]:
	dump(f)
