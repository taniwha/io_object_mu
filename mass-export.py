# either load into blender's text editor and run via alt-p, or:
#   blender -noaudio --background project.blend -P mass-export.py
# All objects that look like a model (no parent, has children) and is enabled
# for render will be exported as objectname.mu (without blender's numeric
# suffix (eg, foo.001 -> foo.mu), and any blender images referenced by the
# exported mu files will be exported with ".png" appended to their names
# (note that they must be packed in the blend, and they will be exported as
# png). foo.cfg.in -> foo.cfg is handled as if exported manually.
import bpy
import os
from io_object_mu.export_mu import export_object, strip_nnn

textures = set()

blend_filepath = bpy.context.blend_data.filepath
blend_filepath = os.path.dirname(blend_filepath)
print(blend_filepath)
for obj in bpy.data.objects:
    if not obj.hide_render and not obj.parent and obj.children:
        name = strip_nnn(obj.name)+".mu"
        filepath = os.path.join(blend_filepath, name)
        print(name, filepath)

        mu = export_object (obj, filepath)
        for m in mu.messages:
            print(m)
        for tex in mu.textures:
            textures.add(tex.name)

for tex in textures:
    if tex not in bpy.data.images:
        continue
    image = bpy.data.images[tex]
    name = tex + ".png"
    path = os.path.join(blend_filepath, name)
    print(tex, image.type, path)
    image.filepath_raw = "//" + name
    image.packed_files[0].filepath = path
    image.save()
