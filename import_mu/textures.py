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

# <pep8 compliant>

from struct import unpack
import os.path

import bpy

# Absolute-path → image name cache across primary + secondary MODEL imports.
# Avoids re-decoding the same DDS when a part has multiple MODEL blocks /
# shared skins. Cleared only when Blender session ends (images may persist).
_PATH_IMAGE_CACHE = {}


def load_mbm(mbmpath):
    mbmfile = open(mbmpath, "rb")
    header = mbmfile.read(20)
    magic, width, height, bump, bpp = unpack("<5i", header)
    if magic != 0x50534b03:  # "\x03KSP" as little endian
        return 0, 0, []
    if bpp == 32:
        pixels = mbmfile.read(width * height * 4)
    elif bpp == 24:
        raw = mbmfile.read(width * height * 3)
        # Build RGBA bytearray once (faster than per-pixel Python lists)
        out = bytearray(width * height * 4)
        ri = 0
        oi = 0
        for _ in range(width * height):
            out[oi] = raw[ri]
            out[oi + 1] = raw[ri + 1]
            out[oi + 2] = raw[ri + 2]
            out[oi + 3] = 255
            ri += 3
            oi += 4
        pixels = out
    else:
        return 0, 0, []
    return width, height, pixels


def _bump_type_from_name(base, type):
    # Squad often uses "..._Normal" / "..._Bump"; mu type flag is frequently 0.
    bl = base.lower()
    if (bl.endswith("_n") or bl.endswith("nrm") or bl.endswith("_normal")
            or bl.endswith("normal") or bl.endswith("_bump") or bl.endswith("bump")):
        return 1
    return type


def _normpath_key(full):
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(full)))
    except Exception:
        return os.path.normcase(os.path.normpath(full or ""))


def _find_cached_image(full):
    """Reuse image already loaded from the same absolute path (any datablock name)."""
    key = _normpath_key(full)
    name = _PATH_IMAGE_CACHE.get(key)
    if name and name in bpy.data.images:
        return bpy.data.images[name]
    # Fallback scan (first import after cache miss / rename)
    for img in bpy.data.images:
        try:
            fp = bpy.path.abspath(img.filepath) if img.filepath else ""
        except Exception:
            fp = ""
        if fp and _normpath_key(fp) == key:
            _PATH_IMAGE_CACHE[key] = img.name
            return img
    return None


def _register_cached_image(full, img):
    if img is None:
        return
    try:
        _PATH_IMAGE_CACHE[_normpath_key(full)] = img.name
    except Exception:
        pass


def load_image(base, ext, path, type):
    """Load image; return resolved type (0/1) on success, False if missing/failed."""
    name = base + ext
    full = os.path.join(path, name)
    if not os.path.isfile(full):
        return False

    want = _normpath_key(full)

    # 1) Path-keyed cache (shared skins across MODEL / secondary imports)
    cached = _find_cached_image(full)
    if cached is not None:
        # Do NOT rename datablocks — materials may still reference the old
        # name (bluedog_Helios_Mesh) while cache holds .001 after a second load.
        # cfg_preview._find_image_datablock resolves both forms on restore.
        return _bump_type_from_name(base, type)

    # 2) Same base name already pointing at this file
    if base in bpy.data.images:
        img = bpy.data.images[base]
        try:
            existing = bpy.path.abspath(img.filepath) if img.filepath else ""
        except Exception:
            existing = ""
        have = _normpath_key(existing) if existing else ""
        if have and have == want:
            _register_cached_image(full, img)
            return _bump_type_from_name(base, type)
        # Different file occupies the name — free the slot
        try:
            img.name = base + ".stale"
        except Exception:
            pass

    if ext.lower() in [".dds", ".png", ".tga"]:
        img = bpy.data.images.load(full)
        img.name = base
        # NOTE: do NOT touch img.pixels here — that forces a full CPU decode
        # of DDS/PNG (often the majority of import time). Type comes from name.
        type = _bump_type_from_name(base, type)
    elif ext.lower() == ".mbm":
        w, h, pixels = load_mbm(full)
        if not pixels:
            return False
        img = bpy.data.images.new(base, w, h, alpha=True)
        # bytearray/bytes → floats without intermediate map() list
        if isinstance(pixels, (bytes, bytearray)):
            img.pixels = [p / 255.0 for p in pixels]
        else:
            img.pixels[:] = map(lambda x: x / 255.0, pixels)
        img.pack()
        type = _bump_type_from_name(base, type)
    else:
        return False

    # CHANNEL_PACKED: keep gloss/GA in alpha without premultiplying RGB to ~0
    # (Squad diffuse DDS often has near-zero alpha; STRAIGHT/premul looks black in EEVEE Next)
    img.alpha_mode = "CHANNEL_PACKED"
    img.muimageprop.invertY = (ext.lower() == ".dds")
    img.muimageprop.convertNorm = False
    img.colorspace_settings.is_data = False
    if type == 1:
        img.colorspace_settings.is_data = True
        # NEVER read img.pixels during import — that forces full DDS decode
        # (often 90% of load time). GA vs RGB normals from name only.
        img.muimageprop.convertNorm = _ga_normal_from_name(base)
    _register_cached_image(full, img)
    return type


def _ga_normal_from_name(base):
    """Heuristic DXT5nm (GA) flag without touching image pixels.

    Prefer False (RGB tangent) — modern mods. Opt-in True for common GA
    naming patterns used by Squad / older packs. User can still toggle
    convertNorm on the image if a specific map is wrong.
    """
    bl = (base or "").lower()
    if "dxt5nm" in bl or bl.endswith("_nm") or bl.endswith("-nm"):
        return True
    # Explicit "ga" token in the name
    if "_ga" in bl or bl.endswith("ga"):
        return True
    return False


# Keep old name for any external callers
def _detect_ga_normal(pixels, n=512):
    tot = min(int(len(pixels) / 4), n)
    if tot <= 0:
        return False
    rgb_unit = 0
    b_high = 0
    r_high = 0
    b_mid = 0
    for i in range(tot):
        r, g, b = pixels[i * 4], pixels[i * 4 + 1], pixels[i * 4 + 2]
        nx, ny, nz = 2 * r - 1, 2 * g - 1, 2 * b - 1
        if abs(nx * nx + ny * ny + nz * nz - 1.0) <= 0.15:
            rgb_unit += 1
        if b > 0.85:
            b_high += 1
        if r > 0.85:
            r_high += 1
        if 0.35 <= b <= 0.65:
            b_mid += 1
    if (r_high / tot) >= 0.55 and (b_mid / tot) >= 0.40 and (b_high / tot) < 0.25:
        return True
    if rgb_unit / tot >= 0.65 and b_high / tot >= 0.45:
        return False
    return (rgb_unit / tot) < 0.45


def create_textures(mu, path):
    extensions = [".dds", ".mbm", ".tga", ".png"]
    try:
        from .progress_util import mu_tick_items
    except Exception:
        mu_tick_items = None
    texes = list(getattr(mu, "textures", None) or [])
    n = max(len(texes), 1)
    for i, tex in enumerate(texes):
        if mu_tick_items is not None:
            try:
                mu_tick_items(i, n, 15, 38, text="Loading textures…")
            except Exception:
                pass
        base, ext = os.path.splitext(tex.name)
        ind = 0
        if ext in extensions:
            ind = extensions.index(ext)
        lst = extensions[ind:] + extensions[:ind]
        for e in lst:
            resolved = load_image(base, e, path, tex.type)
            if resolved is not False:
                tex.type = resolved
                break
