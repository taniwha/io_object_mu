# vim:ts=4:et
# <pep8 compliant>
"""Helpers for KSP .craft import/export (ShipConstruct fields + TweakScale)."""
from __future__ import annotations

from typing import Optional, Tuple

from mathutils import Quaternion, Vector

from ..cfgnode import ConfigNode, parse_float


def split_part_id(part_val: str) -> Tuple[str, str]:
    """``mk1pod_4290485324`` / ``solidBooster.sm_4290`` -> (name, uid)."""
    raw = (part_val or "").strip()
    if not raw:
        return "", ""
    if "_" not in raw:
        return raw, ""
    name, uid = raw.rsplit("_", 1)
    if uid.isdigit():
        return name, uid
    return raw, ""


def format_vector(v: Vector) -> str:
    """Blender XYZ -> KSP left-handed string (inverse of parse_vector)."""
    return "%g,%g,%g" % (float(v.x), float(v.z), float(v.y))


def format_quaternion(q: Quaternion) -> str:
    """Blender quaternion -> KSP string (inverse of parse_quaternion)."""
    # Import: kx,ky,kz,kw -> Quaternion((kw, -kx, -kz, -ky))
    return "%g,%g,%g,%g" % (-float(q.x), -float(q.z), -float(q.y), float(q.w))


def tweakscale_factor(part_node: ConfigNode) -> Optional[float]:
    """Linear scale multiplier from MODULE[TweakScale], or None."""
    if part_node is None:
        return None
    for mod in part_node.GetNodes("MODULE"):
        name = (mod.GetValue("name") or "").strip()
        if name.lower() != "tweakscale":
            continue
        cur = None
        default = None
        if mod.HasValue("currentScale"):
            try:
                cur = parse_float(mod.GetValue("currentScale"))
            except Exception:
                cur = None
        if mod.HasValue("defaultScale"):
            try:
                default = parse_float(mod.GetValue("defaultScale"))
            except Exception:
                default = None
        if cur is not None and default is not None and abs(default) > 1e-9:
            return float(cur) / float(default)
        if mod.HasValue("ScaleFactor"):
            try:
                return parse_float(mod.GetValue("ScaleFactor"))
            except Exception:
                pass
        if cur is not None and default is None:
            return float(cur)
    return None


def set_tweakscale_current(part_node: ConfigNode, absolute_scale: float) -> bool:
    """Write TweakScale currentScale from Blender linear scale (vs default)."""
    if part_node is None:
        return False
    for mod in part_node.GetNodes("MODULE"):
        name = (mod.GetValue("name") or "").strip()
        if name.lower() != "tweakscale":
            continue
        default = 1.0
        if mod.HasValue("defaultScale"):
            try:
                default = parse_float(mod.GetValue("defaultScale"))
            except Exception:
                default = 1.0
        if abs(default) < 1e-9:
            default = 1.0
        current = float(absolute_scale) * float(default)
        mod.SetValue("currentScale", "%g" % current)
        if mod.HasValue("ScaleFactor"):
            mod.SetValue("ScaleFactor", "%g" % float(absolute_scale))
        return True
    return False
