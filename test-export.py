# Background export smoke test for Blender 4.2+ / 5.x.
#
# Usage (with a .blend that already has Mu hierarchies):
#   blender -noaudio --background project.blend --python test-export.py
#
# Optional filter after -- :
#   blender ... --python test-export.py -- root
# exports only roots whose stripped name equals / starts with that filter.
# Without a filter, exports the first eligible root (smoke test).
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

name_filter = None
if "--" in sys.argv:
    extra = sys.argv[sys.argv.index("--") + 1:]
    if extra:
        name_filter = extra[0]

blend_filepath = bpy.context.blend_data.filepath
if not blend_filepath:
    raise SystemExit("Save / open a .blend first (needed for export path).")
blend_dir = os.path.dirname(blend_filepath)
print("test-export dir:", blend_dir, "filter:", name_filter)

object_queue = []
textures = set()
collections = enable_collections()
exported = 0
try:
    for obj in bpy.data.objects:
        if obj.parent or not obj.children:
            continue
        if getattr(obj, "muproperties", None) and obj.muproperties.modelType == 'UTILITY':
            continue
        object_queue.append(obj)

    while object_queue:
        obj = object_queue.pop(0)
        base = strip_nnn(obj.name)
        if name_filter is not None:
            if base != name_filter and not base.startswith(name_filter):
                continue
        elif exported:
            # Smoke mode: only first root unless a filter is given
            break

        name = base + ".mu"
        filepath = os.path.join(blend_dir, name)
        print("exporting", name, "->", filepath)
        mu = export_object(obj, filepath)
        exported += 1
        if mu.internals:
            object_queue.extend(mu.internals)
        for m in mu.messages:
            print(m)
        for tex in mu.textures:
            textures.add(tex.name)
finally:
    restore_collections(collections)

if not exported:
    raise SystemExit("No eligible root objects found to export.")
print("OK: exported", exported, "model(s); textures referenced:", len(textures))
