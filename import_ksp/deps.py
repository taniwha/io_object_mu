# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>
"""Online UnityPy install for this Blender (minimal — no bundled wheels).

  pip install --target <user>/Blender/<ver>/scripts/addons/modules UnityPy Pillow

That folder is on ``sys.path``, needs no admin, and is per Blender version
(5.2 vs 4.x). Plain ``pip install`` is wrong: Blender has
``ENABLE_USER_SITE=False``, so packages land in Roaming\\Python and never import.

Official Extensions bundle wheels offline; we stay slim and fetch once online.
"""

from __future__ import annotations

import os
import subprocess
import sys


_ENSURED = False
_LAST_ERROR = ""
_LAST_SOURCE = ""  # "system" | "pip"
_LAST_TARGET = ""
_NEED_RESTART = False


def _install_target():
    """Writable dir Blender already searches for imports."""
    try:
        import bpy
        # e.g. .../Blender/5.2/scripts/addons/modules
        path = bpy.utils.user_resource("SCRIPTS", path="addons/modules")
    except Exception:
        path = os.path.join(sys.prefix, "Lib", "site-packages")
    os.makedirs(path, exist_ok=True)
    if path and path not in sys.path:
        sys.path.insert(0, path)
    return path


def _online_allowed():
    try:
        import bpy
        return bool(getattr(bpy.app, "online_access", True))
    except Exception:
        return True


def _purge_unitypy():
    for mod in list(sys.modules):
        if (
            mod == "UnityPy"
            or mod.startswith("UnityPy.")
            or mod == "texture2ddecoder"
            or mod.startswith("texture2ddecoder.")
            or mod == "etcpak"
            or mod.startswith("etcpak.")
            or mod == "PIL"
            or mod.startswith("PIL.")
        ):
            del sys.modules[mod]


def _unitypy_ok():
    """True when UnityPy exposes ``load`` (real package, not a broken stub)."""
    try:
        import UnityPy
        from PIL import Image  # noqa: F401
        if not hasattr(UnityPy, "load") or not callable(UnityPy.load):
            raise AttributeError(
                "module 'UnityPy' has no attribute 'load' "
                "(broken/partial install)"
            )
        return True
    except Exception as e:
        global _LAST_ERROR
        _LAST_ERROR = str(e)
        return False


def _pip_install(target):
    """Install UnityPy + Pillow into ``target`` (not user-site)."""
    global _LAST_ERROR, _LAST_TARGET
    _LAST_TARGET = target
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--disable-pip-version-check",
        "--no-input",
        "--no-warn-script-location",
        "--target",
        target,
        "UnityPy",
        "Pillow",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        _LAST_ERROR = "pip install timed out (300s)"
        return False
    except Exception as e:
        _LAST_ERROR = str(e)
        return False
    if proc.returncode != 0:
        out = (proc.stderr or "") + "\n" + (proc.stdout or "")
        _LAST_ERROR = out.strip()[-1200:] or "pip failed"
        return False
    return True


def ensure_unitypy(install=True):
    """Return True if ``UnityPy.load`` works.

    With ``install=True``, one online pip into this Blender version's
    ``scripts/addons/modules`` when missing/broken.
    """
    global _ENSURED, _LAST_ERROR, _LAST_SOURCE, _NEED_RESTART

    if _ENSURED:
        return True

    target = _install_target()

    _purge_unitypy()
    if _unitypy_ok():
        _ENSURED = True
        _LAST_SOURCE = "system"
        _LAST_ERROR = ""
        _NEED_RESTART = False
        return True

    if not install:
        return False

    if not _online_allowed():
        _LAST_ERROR = (
            "UnityPy missing and online access is disabled "
            "(Preferences → System → Network). Enable it, or pip install "
            "UnityPy into: %s" % target
        )
        return False

    if not _pip_install(target):
        return False

    if target in sys.path:
        sys.path.remove(target)
    sys.path.insert(0, target)

    _purge_unitypy()
    if _unitypy_ok():
        _ENSURED = True
        _LAST_SOURCE = "pip"
        _LAST_ERROR = ""
        _NEED_RESTART = False
        return True

    _NEED_RESTART = True
    _LAST_SOURCE = "pip"
    _LAST_ERROR = (
        "pip --target OK (%s), but import still fails (%s). "
        "Restart Blender once; if it persists, check that folder."
        % (target, _LAST_ERROR or "no load")
    )
    return False


def ensure_unitypy_or_prompt():
    """Return True when UnityPy is usable.

    If it is missing, ask before pip. Cancel leaves a message and installs
    nothing. Background Blender (tests) never opens a dialog.
    """
    global _LAST_ERROR
    if ensure_unitypy(False):
        return True
    try:
        import bpy
    except Exception:
        bpy = None
    if bpy is None or getattr(bpy.app, "background", False):
        _LAST_ERROR = (
            "Python modules are required (UnityPy, Pillow). "
            "Install them with Ensure UnityPy."
        )
        return False
    _LAST_ERROR = (
        "Python modules are required (UnityPy, Pillow). "
        "Confirm install in the dialog, then retry the operation."
    )
    try:
        bpy.ops.import_object.ksp_install_unitypy_prompt("INVOKE_DEFAULT")
    except Exception as exc:
        _LAST_ERROR = "Could not open the install prompt: %s" % exc
    return False


def last_error():
    return _LAST_ERROR


def last_source():
    return _LAST_SOURCE


def last_target():
    return _LAST_TARGET


def need_restart():
    return _NEED_RESTART


def vendor_dir():
    return ""


def runtime_dir():
    return ""
