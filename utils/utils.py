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

def swapyz(vec):
    return vec[0], vec[2], vec[1]

def swizzleq(quaternion):
    # this works only for blender to unity
    return quaternion[1], quaternion[3], quaternion[2], -quaternion[0]

def strip_nnn(name):
    """Strip Blender-only protection marks; keep legitimate Unity wedge names.

    Stock parts (e.g. bluedog_Surveyor_Omnis) use real transform names like
    Omni1 wedge. Import then appends a trailing protection mark:

    - Omni1 wedge + wedge -> Blender double-wedge -> export Omni1 wedge
    - Name + wedge -> Name wedge -> export Name
    - Name.001 wedge -> Name
    - Name wedge .001 -> Name
    - Parent wedge collider / Omni1 wedge wedge collider -> strip only the
      wedge-collider import tag

    Never cut at the first wedge as if it were always a protection mark --
    that destroyed Surveyor Omni1 wedge nodes whose Unity name contains wedge.
    """
    import re
    name = str(name or "")
    if not name:
        return name
    wedge = "∧"

    # 1) Import mesh-collider tag at the end: ... wedge collider[.NNN]
    m = re.match(
        r"^(.*)" + re.escape(wedge) + r"collider(\.\d{3})?$",
        name,
        re.IGNORECASE,
    )
    if m:
        return m.group(1) if m.group(1) else name

    # 2) Trailing protection mark only: UnityName wedge or UnityName.001 wedge
    if name.endswith(wedge):
        base = name[:-1]
        dot = base.rfind(".")
        if dot >= 0 and len(base) - dot == 4 and base[dot + 1:].isdigit():
            base = base[:dot]
        return base

    # 3) Protection mark then Blender uniquifier: UnityName wedge .001
    m = re.match(r"^(.*)" + re.escape(wedge) + r"(\.\d{3})$", name)
    if m:
        return m.group(1)

    # 4) Legacy Blender duplicate without mark: Name.001
    ind = name.rfind(".")
    if ind >= 0 and len(name) - ind == 4 and name[ind + 1:].isdigit():
        return name[:ind]
    return name


def normalize_mu_curve_path(path):
    """Strip Blender uniquifier segments (.001) from each Mu curve path part."""
    path = str(path or "").strip()
    if not path:
        return path
    return "/".join(strip_nnn(seg) for seg in path.split("/") if seg)


def unity_export_name(obj):
    """Unity transform.name for .mu export (exact stock name when stored).

    mu_unity_transform_name is written on import from the .mu and may
    legitimately contain wedge (Surveyor Omni1 wedge). Never run strip_nnn on it.
    """
    if obj is None:
        return ""
    try:
        stored = obj.get("mu_unity_transform_name")
        if stored is not None and str(stored):
            return str(stored)
    except Exception:
        pass
    try:
        return strip_nnn(obj.name)
    except Exception:
        return str(getattr(obj, "name", "") or "")


def is_hideable_collider_name(name):
    """True for dedicated collider GOs; False for visuals named ``Collider``.

    Stock telescopicLadderBay uses a MeshRenderer GO literally named
    ``Collider`` for the bay housing — a naive ``\"collider\" in name`` hide
    removes it from GIF/thumbnail renders. Importer children use
    ``…∧collider``; pure hitboxes use names like ``ladderCollider``.
    """
    if not name:
        return False
    n = name.lower()
    if n.startswith("mesh:"):
        return True
    wedge = "\u2227"
    if (wedge + "collider") in n:
        return True
    base = n.split(wedge, 1)[0].strip()
    if base == "collider":
        return False
    return "collider" in base


def vector_str(vec):
    if len(vec) == 2:
        return "%.9g, %.9g" % vec
    elif len(vec) == 3:
        return "%.9g, %.9g, %.9g" % vec
    elif len(vec) == 4:
        return "%.9g, %.9g, %.9g, %.9g" % vec
