# Mass-export all Mu model roots from the current .blend.
#
# Usage:
#   blender -noaudio --background project.blend --python mass-export.py
#
# All objects that look like a model (no parent, has children) and are not
# UTILITY will be exported as objectname.mu (without blender's numeric
# suffix, e.g. foo.001 -> foo.mu). Packed blender images referenced by the
# exported mu files are written as name.png next to the blend.
# foo.cfg.in -> foo.cfg is handled as if exported manually.
import bpy
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _addon_bootstrap import ensure_addon_enabled, import_addon_module

ensure_addon_enabled()
export_mu = import_addon_module("export_mu")
export_object = export_mu.export_object
strip_nnn = export_mu.strip_nnn
enable_collections = export_mu.enable_collections
restore_collections = export_mu.restore_collections

object_queue = []
textures = set()

blend_filepath = bpy.context.blend_data.filepath
if not blend_filepath:
    raise SystemExit("Save / open a .blend first (needed for export path).")
blend_filepath = os.path.dirname(blend_filepath)
print("mass-export dir:", blend_filepath)

collections = enable_collections()
try:
    for obj in bpy.data.objects:
        if obj.parent or not obj.children:
            continue
        if getattr(obj, "muproperties", None) and obj.muproperties.modelType == 'UTILITY':
            continue
        object_queue.append(obj)
    while object_queue:
        obj = object_queue.pop(0)
        name = strip_nnn(obj.name) + ".mu"
        filepath = os.path.join(blend_filepath, name)
        print(name, filepath)

        mu = export_object(obj, filepath)
        if mu.internals:
            object_queue.extend(mu.internals)
        for m in mu.messages:
            print(m)
        for tex in mu.textures:
            textures.add(tex.name)
finally:
    restore_collections(collections)

for tex in textures:
    if tex not in bpy.data.images:
        continue
    image = bpy.data.images[tex]
    if image.packed_files:
        name = tex + ".png"
        path = os.path.join(blend_filepath, name)
        print(tex, image.type, path)
        image.filepath_raw = "//" + name
        image.packed_files[0].filepath = path
        image.save()

print("OK: mass-export finished;", len(textures), "texture name(s)")
