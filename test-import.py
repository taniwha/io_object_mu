# Background import smoke test for Blender 4.2+ / 5.x.
#
# Usage:
#   blender --background --python test-import.py -- path\to\model.mu
#
# Optional flags after -- :
#   --no-colliders   --force-armature   --force-mesh
import bpy
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _addon_bootstrap import ensure_addon_enabled, import_addon_module

ensure_addon_enabled()
import_mu = import_addon_module("import_mu").import_mu


def _parse_args():
    if "--" not in sys.argv:
        raise SystemExit("Usage: blender --background --python test-import.py -- <file.mu>")
    argv = sys.argv[sys.argv.index("--") + 1:]
    if not argv:
        raise SystemExit("Missing .mu path after --")
    path = None
    create_colliders = True
    force_armature = False
    force_mesh = False
    for a in argv:
        if a == "--no-colliders":
            create_colliders = False
        elif a == "--force-armature":
            force_armature = True
        elif a == "--force-mesh":
            force_mesh = True
        elif not a.startswith("-"):
            path = a
    if not path:
        raise SystemExit("Missing .mu path after --")
    path = str(Path(path).resolve())
    if not Path(path).is_file():
        raise SystemExit(f"File not found: {path}")
    return path, create_colliders, force_armature, force_mesh


filepath, create_colliders, force_armature, force_mesh = _parse_args()
print("test-import:", filepath)
print("  colliders=", create_colliders,
      "force_armature=", force_armature,
      "force_mesh=", force_mesh)

# Clean default cube so the import is easy to inspect
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

collection = bpy.context.scene.collection
result = import_mu(collection, filepath, create_colliders, force_armature, force_mesh)
print("OK: import finished ->", result)
print("objects:", len(bpy.data.objects),
      "materials:", len(bpy.data.materials),
      "actions:", len(bpy.data.actions))
