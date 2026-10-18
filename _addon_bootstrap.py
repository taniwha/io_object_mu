# Shared bootstrap for standalone test / mass-export scripts.
# Resolves the installed addon package name (folder may be io_object_mu-master).
import importlib
import sys
from pathlib import Path

_ADDON_DIR = Path(__file__).resolve().parent
_ADDONS_PARENT = str(_ADDON_DIR.parent)
if _ADDONS_PARENT not in sys.path:
    sys.path.insert(0, _ADDONS_PARENT)

PACKAGE_NAME = _ADDON_DIR.name


def import_addon_module(subpath):
    """Import ``PACKAGE_NAME.subpath`` (e.g. ``export_mu``)."""
    return importlib.import_module(f"{PACKAGE_NAME}.{subpath}")


def ensure_addon_enabled():
    """Enable the addon if Blender has not loaded it yet (background scripts)."""
    import addon_utils
    import bpy

    module = PACKAGE_NAME
    if module in bpy.context.preferences.addons:
        return module
    # Try common alternate names
    for name in (module, "io_object_mu", "io_object_mu-master"):
        try:
            addon_utils.enable(name, default_set=True, persistent=True)
            if name in bpy.context.preferences.addons:
                return name
        except Exception:
            pass
    return module
