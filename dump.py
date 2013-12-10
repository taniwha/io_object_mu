from mu import Mu, MuEnum, MuMatTex
import sys

def dump_textures(mu):
	print("Textures")
	for i, tex in enumerate(mu.textures):
		print (i, tex.name, tex.type)

def dump_materials(mu):
	print("Materials")
	for i, mat in enumerate(mu.materials):
		print(i, mat.name)
		for a in dir(mat):
			if a[0] == "_" or a in ["read", "write"]:
				continue
			attr = getattr(mat, a)
			if attr.__class__.__name__ == 'MuMatTex':
				print("    %s %d %s %s" %
					  (a, attr.index, `attr.scale`, `attr.offset`))
			else:
				print(("    %s = " % a) + `attr`)

def dump_renderer(name, mu, rend, level):
	print("%s Renderer: %s = " % ("    " * level, name))
	for a in dir(rend):
		if a[0] == "_" or a in ["read", "write"]:
			continue
		attr = getattr(rend, a)
		print(("%s  %s = " % ("    " * level, a)) + `attr`)

def dump_mesh(name, mu, mesh, level):
	print("%s Mesh: %s = %s" % ("    " * level, name, `mesh`))
	for a in dir(mesh):
		if a[0] == "_" or a in ["read", "write"]:
			continue
		attr = getattr(mesh, a)
		if type(attr) is list:
			print("%s  %s[%d]" % ("    " * level, a, len(attr)))
		else:
			print(("%s  %s = " % ("    " * level, a)) + `attr`)

def dump_collider(name, mu, col, level):
	print("%s Collider: %s = " % ("    " * level, name))
	for a in dir(col):
		if a[0] == "_" or a in ["read", "write"]:
			continue
		attr = getattr(col, a)
		print(("%s  %s = " % ("    " * level, a)) + `attr`)

dump_funcs={
	"MuRenderer": dump_renderer,
	"MuMesh": dump_mesh,
	"MuColliderMesh": dump_collider,
	"MuColliderCapsule": dump_collider,
}

def dump_object(mu, obj, level=0):
	trans = obj.transform
	print("%s%s" % ("    " * level, trans.name))
	print("%s  %s" % ("    " * level, `trans.localPosition`))
	print("%s  %s" % ("    " * level, `trans.localRotation`))
	print("%s  %s" % ("    " * level, `trans.localScale`))
	tl = obj.tag_and_layer
	print("%s  %s %d" % ("    " * level, tl.tag, tl.layer))
	for a in dir(obj):
		if a[0] == "_" or a in ["read", "write", "transform", "tag_and_layer",
								"children"]:
			continue
		attr = getattr(obj, a)
		n = attr.__class__.__name__
		if n in dump_funcs:
			dump_funcs[n](a, mu, attr, level)
		else:
			print(("%s %s = " % ("    " * level, a)) + `attr`)

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
