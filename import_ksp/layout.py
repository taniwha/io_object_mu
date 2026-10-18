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
"""Unity UGUI RectTransform layout → Blender local XY.

Object origins match Unity pivots. Parent space is parent-pivot-relative
(same as Unity). Stretch uses anchorMin/Max + sizeDelta (+ optional
offsetMin/Max when present in the asset).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math


@dataclass
class ComputedRect:
    """Axis-aligned rect in parent-local space (Unity UI units / pixels)."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float
    pivot_x: float
    pivot_y: float
    width: float
    height: float
    # Parent size used for this computation (0 if root)
    parent_width: float = 0.0
    parent_height: float = 0.0


def _f2(v, default=(0.0, 0.0)):
    if v is None:
        return float(default[0]), float(default[1])
    try:
        return float(v[0]), float(v[1])
    except Exception:
        return float(default[0]), float(default[1])


def quat_identity(q, eps=1e-5):
    """True when Unity (x,y,z,w) is identity."""
    try:
        x, y, z, w = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    except Exception:
        return True
    return (
        abs(x) <= eps
        and abs(y) <= eps
        and abs(z) <= eps
        and abs(abs(w) - 1.0) <= eps
    )


def scale_identity(s, eps=1e-5):
    try:
        x, y, z = float(s[0]), float(s[1]), float(s[2] if len(s) > 2 else 1.0)
    except Exception:
        return True
    return abs(x - 1.0) <= eps and abs(y - 1.0) <= eps and abs(z - 1.0) <= eps


def unity_quat_to_euler_deg(q):
    """Unity quaternion (x,y,z,w) → Euler XYZ degrees (Unity convention)."""
    try:
        x, y, z, w = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    except Exception:
        return (0.0, 0.0, 0.0)
    # roll (x)
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.degrees(math.atan2(sinr_cosp, cosr_cosp))
    # pitch (y)
    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.degrees(math.asin(sinp))
    # yaw (z) — UI plane rotation
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.degrees(math.atan2(siny_cosp, cosy_cosp))
    return (roll, pitch, yaw)


def unity_euler_deg_to_quat(euler_xyz_deg):
    """Unity Euler XYZ degrees → quaternion (x,y,z,w)."""
    try:
        rx, ry, rz = (
            math.radians(float(euler_xyz_deg[0])),
            math.radians(float(euler_xyz_deg[1])),
            math.radians(float(euler_xyz_deg[2])),
        )
    except Exception:
        return (0.0, 0.0, 0.0, 1.0)
    cx, sx = math.cos(rx * 0.5), math.sin(rx * 0.5)
    cy, sy = math.cos(ry * 0.5), math.sin(ry * 0.5)
    cz, sz = math.cos(rz * 0.5), math.sin(rz * 0.5)
    # Unity ZXY? Actually Unity uses ZXY applied as yaw-pitch-roll order on
    # Transform; for UI we almost always have pure Z. Use standard XYZ:
    w = cx * cy * cz + sx * sy * sz
    x = sx * cy * cz - cx * sy * sz
    y = cx * sy * cz + sx * cy * sz
    z = cx * cy * sz - sx * sy * cz
    return (x, y, z, w)


def unity_ui_quat_to_blender_euler(q):
    """Map Unity UI localRotation → Blender Euler radians (XYZ).

    KSPedia viewport keeps Unity XY as Blender XY (Y up). Pure Z rotations
    (Craft Pitches ±90°) map 1:1 onto Blender ``rotation_euler.z``.
    """
    ex, ey, ez = unity_quat_to_euler_deg(q)
    return (
        math.radians(ex),
        math.radians(ey),
        math.radians(ez),
    )


def blender_euler_to_unity_ui_quat(euler_xyz_rad):
    """Inverse of :func:`unity_ui_quat_to_blender_euler`."""
    try:
        ex = math.degrees(float(euler_xyz_rad[0]))
        ey = math.degrees(float(euler_xyz_rad[1]))
        ez = math.degrees(float(euler_xyz_rad[2]))
    except Exception:
        return (0.0, 0.0, 0.0, 1.0)
    return unity_euler_deg_to_quat((ex, ey, ez))


def apply_ui_local_trs(obj, element, *, pixel_scale=0.001, base_z=None):
    """Apply RectTransform localRotation / localScale / Z onto a Blender object.

    Location XY is expected to already be set (pivot in parent space).
    ``base_z`` overrides Z when provided (images use a small draw-order bias).
    """
    if obj is None or element is None:
        return
    q = getattr(element, "local_rotation", (0.0, 0.0, 0.0, 1.0))
    sc = getattr(element, "local_scale", (1.0, 1.0, 1.0))
    z_u = float(getattr(element, "local_position_z", 0.0) or 0.0)
    try:
        sx = float(pixel_scale)
    except Exception:
        sx = 0.001
    try:
        obj.rotation_mode = "XYZ"
        if not quat_identity(q):
            obj.rotation_euler = unity_ui_quat_to_blender_euler(q)
        else:
            obj.rotation_euler = (0.0, 0.0, 0.0)
    except Exception:
        pass
    try:
        if not scale_identity(sc):
            obj.scale = (float(sc[0]), float(sc[1]), float(sc[2]))
        else:
            obj.scale = (1.0, 1.0, 1.0)
    except Exception:
        pass
    try:
        z = float(base_z) if base_z is not None else (z_u * sx)
        # Keep explicit image draw-order bias when caller passes base_z; still
        # bake Unity localPosition.z on top when non-zero.
        if base_z is not None and abs(z_u) > 1e-9:
            z = float(base_z) + z_u * sx
        obj.location = (float(obj.location.x), float(obj.location.y), z)
    except Exception:
        pass
    try:
        obj["ksp_local_rotation"] = tuple(float(v) for v in q)
        obj["ksp_local_scale"] = tuple(float(v) for v in sc[:3])
        obj["ksp_local_position_z"] = float(z_u)
        # Blender-only draw-order bias. Without it a capture reads back
        # location.z (0.02) as localPosition.z = 20 and exports that.
        obj["ksp_base_z"] = float(obj.location.z) - z_u * sx
    except Exception:
        pass


def parent_local_rect(parent_width, parent_height, parent_pivot):
    """Parent's own rect in parent-local space (pivot at origin)."""
    pw = float(parent_width)
    ph = float(parent_height)
    ppx, ppy = _f2(parent_pivot, (0.5, 0.5))
    return (-ppx * pw, -ppy * ph, (1.0 - ppx) * pw, (1.0 - ppy) * ph)


def compute_rect(
    anchored_position,
    size_delta,
    anchor_min,
    anchor_max,
    pivot,
    parent_width,
    parent_height,
    parent_pivot=(0.5, 0.5),
    offset_min=None,
    offset_max=None,
) -> ComputedRect:
    """Compute child rect in parent-local space (Unity RectTransform rules)."""
    ax, ay = _f2(anchored_position)
    sdx, sdy = _f2(size_delta)
    aminx, aminy = _f2(anchor_min, (0.5, 0.5))
    amaxx, amaxy = _f2(anchor_max, (0.5, 0.5))
    px, py = _f2(pivot, (0.5, 0.5))
    pw = float(parent_width)
    ph = float(parent_height)
    pr_xmin, pr_ymin, pr_xmax, pr_ymax = parent_local_rect(
        pw, ph, parent_pivot
    )
    # Prefer explicit offsetMin/Max when provided; otherwise derive from
    # anchoredPosition / sizeDelta (Unity's standard conversion).
    if offset_min is not None and offset_max is not None:
        ominx, ominy = _f2(offset_min)
        omaxx, omaxy = _f2(offset_max)
    else:
        ominx = ax - sdx * px
        ominy = ay - sdy * py
        omaxx = ax + sdx * (1.0 - px)
        omaxy = ay + sdy * (1.0 - py)

    xmin = pr_xmin + pw * aminx + ominx
    xmax = pr_xmin + pw * amaxx + omaxx
    ymin = pr_ymin + ph * aminy + ominy
    ymax = pr_ymin + ph * amaxy + omaxy

    width = xmax - xmin
    height = ymax - ymin
    pivot_x = xmin + width * px
    pivot_y = ymin + height * py
    return ComputedRect(
        xmin=xmin,
        ymin=ymin,
        xmax=xmax,
        ymax=ymax,
        pivot_x=pivot_x,
        pivot_y=pivot_y,
        width=width,
        height=height,
        parent_width=pw,
        parent_height=ph,
    )


def topological_ui_elements(elements: List) -> List:
    """Parents before children (stable). Orphans after known parents."""
    by_rect: Dict[int, object] = {}
    for el in elements:
        rid = int(getattr(el, "rect_path_id", 0) or 0)
        if rid:
            by_rect[rid] = el

    depth_cache: Dict[int, int] = {}

    def depth(el) -> int:
        rid = int(getattr(el, "rect_path_id", 0) or 0)
        if rid in depth_cache:
            return depth_cache[rid]
        seen = set()
        d = 0
        cur = el
        while True:
            pid = int(getattr(cur, "parent_rect_path_id", 0) or 0)
            if not pid or pid not in by_rect or pid in seen:
                break
            seen.add(pid)
            d += 1
            cur = by_rect[pid]
            if d > 256:
                break
        depth_cache[rid] = d
        return d

    return sorted(
        elements,
        key=lambda e: (
            depth(e),
            # Unity m_Children order — name-sort put "Craft Pitches" before
            # "Image" and EEVEE alpha then covered the label.
            int(getattr(e, "sibling_index", 10**9) or 10**9),
            str(getattr(e, "name", "") or ""),
            int(getattr(e, "rect_path_id", 0) or 0),
        ),
    )


def compute_all_rects(
    elements: List,
    root_fallback_size: Optional[Tuple[float, float]] = None,
) -> Dict[int, ComputedRect]:
    """Compute rects for every element with a rect_path_id.

    Root elements (no known parent) use their own sizeDelta when non-zero,
    else ``root_fallback_size`` (typically main texture WxH).
    """
    ordered = topological_ui_elements(elements)
    by_rect: Dict[int, object] = {
        int(el.rect_path_id): el
        for el in elements
        if int(getattr(el, "rect_path_id", 0) or 0)
    }
    out: Dict[int, ComputedRect] = {}
    fb_w, fb_h = (0.0, 0.0)
    if root_fallback_size:
        fb_w, fb_h = float(root_fallback_size[0]), float(root_fallback_size[1])

    for el in ordered:
        rid = int(el.rect_path_id)
        pid = int(getattr(el, "parent_rect_path_id", 0) or 0)
        parent_el = by_rect.get(pid)
        parent_rect = out.get(pid)

        if parent_rect is not None:
            pw, ph = parent_rect.width, parent_rect.height
            pp = getattr(parent_el, "pivot", (0.5, 0.5))
        elif parent_el is not None:
            # Parent not computed yet (should not happen after topo sort)
            sdx, sdy = _f2(getattr(parent_el, "size_delta", (0, 0)))
            pw = abs(sdx) if abs(sdx) > 0.01 else fb_w
            ph = abs(sdy) if abs(sdy) > 0.01 else fb_h
            pp = getattr(parent_el, "pivot", (0.5, 0.5))
        else:
            # Root: parent canvas is identity — treat parent size as this
            # element's sizeDelta / fallback so stretch children work.
            sdx, sdy = _f2(getattr(el, "size_delta", (0, 0)))
            # For root layout, parent rect is zero-size at origin with
            # pivot 0.5 — then non-stretch root uses sizeDelta alone.
            # Better: invent a parent the size of the root content.
            pw = abs(sdx) if abs(sdx) > 0.01 else fb_w
            ph = abs(sdy) if abs(sdy) > 0.01 else fb_h
            # Place root as if parent were the same size with matching
            # anchors — for CareerUI anchors (0,1) + size 2048x1536 +
            # pivot 0.5, we need parent = canvas. Use size as parent so
            # anchoredPosition is relative to top-left of a virtual canvas.
            # Virtual canvas: pivot top-left (0,1), size = content size.
            # Simpler approach used by many tools: root parent size equals
            # root sizeDelta, parent pivot = root pivot, so local pivot
            # lands near anchoredPosition. For CareerUI that gives pivot
            # at (0,0) which is wrong for children.
            #
            # Correct for KSPedia: root Rect is the canvas. Children are
            # parented to it. Root itself sits at world origin with its
            # pivot at object origin; its width/height come from sizeDelta.
            # So for the root element we force:
            #   parent_w/h = 0, parent_pivot = (0,0) → rect from offsets only
            #   width/height = sizeDelta (non-stretch)
            pw, ph = 0.0, 0.0
            pp = (0.0, 0.0)

        omin = getattr(el, "offset_min", None)
        omax = getattr(el, "offset_max", None)
        ap = normalize_stretch_offsets(
            el.anchored_position,
            el.size_delta,
            el.anchor_min,
            el.anchor_max,
        )
        sd = normalize_stretch_size_delta(
            el.size_delta,
            el.anchor_min,
            el.anchor_max,
            pw,
            ph,
        )
        if sd != _f2(el.size_delta):
            try:
                el.size_delta = (float(sd[0]), float(sd[1])) + tuple(
                    el.size_delta[2:]
                )
            except Exception:
                try:
                    el.size_delta = (float(sd[0]), float(sd[1]))
                except Exception:
                    pass
        rect = compute_rect(
            ap,
            sd,
            el.anchor_min,
            el.anchor_max,
            el.pivot,
            pw,
            ph,
            pp,
            offset_min=omin,
            offset_max=omax,
        )

        # Root with explicit sizeDelta and zero parent: size may collapse
        # if anchors are point anchors — ensure width/height from sizeDelta.
        if parent_el is None and parent_rect is None:
            sdx, sdy = _f2(el.size_delta)
            aminx, aminy = _f2(el.anchor_min, (0.5, 0.5))
            amaxx, amaxy = _f2(el.anchor_max, (0.5, 0.5))
            px, py = _f2(el.pivot, (0.5, 0.5))
            ax, ay = _f2(el.anchored_position)
            if abs(amaxx - aminx) < 1e-6 and abs(amaxy - aminy) < 1e-6:
                # Point anchor on empty parent → size = sizeDelta
                w = abs(sdx) if abs(sdx) > 0.01 else fb_w
                h = abs(sdy) if abs(sdy) > 0.01 else fb_h
                # Put pivot at origin for the root canvas object so children
                # use this element's pivot as their parent origin.
                rect = ComputedRect(
                    xmin=-px * w,
                    ymin=-py * h,
                    xmax=(1.0 - px) * w,
                    ymax=(1.0 - py) * h,
                    pivot_x=0.0,
                    pivot_y=0.0,
                    width=w,
                    height=h,
                    parent_width=0.0,
                    parent_height=0.0,
                )
            elif abs(sdx) < 0.01 and abs(sdy) < 0.01 and fb_w > 0 and fb_h > 0:
                w, h = fb_w, fb_h
                rect = ComputedRect(
                    xmin=-px * w,
                    ymin=-py * h,
                    xmax=(1.0 - px) * w,
                    ymax=(1.0 - py) * h,
                    pivot_x=0.0,
                    pivot_y=0.0,
                    width=w,
                    height=h,
                )

        # Stretch with near-zero computed size → fall back to texture size
        if abs(rect.width) < 0.01 and fb_w > 0:
            # Recompute keeping pivot, expand to fallback
            px, py = _f2(el.pivot, (0.5, 0.5))
            rect = ComputedRect(
                xmin=rect.pivot_x - px * fb_w,
                ymin=rect.pivot_y - py * fb_h,
                xmax=rect.pivot_x + (1.0 - px) * fb_w,
                ymax=rect.pivot_y + (1.0 - py) * fb_h,
                pivot_x=rect.pivot_x,
                pivot_y=rect.pivot_y,
                width=fb_w,
                height=fb_h,
                parent_width=rect.parent_width,
                parent_height=rect.parent_height,
            )
        if abs(rect.height) < 0.01 and fb_h > 0 and abs(rect.width) >= 0.01:
            px, py = _f2(el.pivot, (0.5, 0.5))
            rect = ComputedRect(
                xmin=rect.xmin,
                ymin=rect.pivot_y - py * fb_h,
                xmax=rect.xmax,
                ymax=rect.pivot_y + (1.0 - py) * fb_h,
                pivot_x=rect.pivot_x,
                pivot_y=rect.pivot_y,
                width=rect.width,
                height=fb_h,
                parent_width=rect.parent_width,
                parent_height=rect.parent_height,
            )

        out[rid] = rect
    return out




def normalize_stretch_offsets(anchored_position, size_delta, anchor_min, anchor_max):
    """KSPedia quirk: full-stretch Image with sizeDelta=0 and large AP.

    That slides the whole 2048x1536 art plane while TMP stays on the root,
    so frames ghost vs JPG. Treat as fill-parent (ap=0) like other pages.
    """
    ax, ay = _f2(anchored_position)
    sdx, sdy = _f2(size_delta)
    aminx, aminy = _f2(anchor_min, (0.5, 0.5))
    amaxx, amaxy = _f2(anchor_max, (0.5, 0.5))
    stretch = abs(amaxx - aminx) > 0.99 and abs(amaxy - aminy) > 0.99
    if (
        stretch
        and abs(sdx) < 0.01
        and abs(sdy) < 0.01
        and (abs(ax) > 32.0 or abs(ay) > 32.0)
    ):
        return (0.0, 0.0)
    return (ax, ay)


def normalize_stretch_size_delta(
    size_delta, anchor_min, anchor_max, parent_width, parent_height
):
    """Undo bad export: stretch + sizeDelta≈parent → fill-parent (0,0).

    Unity size = parentSpan + sizeDelta. Healing 0×0 stretch Images with
    texture WH wrote (2048,1536) on a 2048×1536 parent → 2× page Image.
    """
    sdx, sdy = _f2(size_delta)
    aminx, aminy = _f2(anchor_min, (0.5, 0.5))
    amaxx, amaxy = _f2(anchor_max, (0.5, 0.5))
    stretch = abs(amaxx - aminx) > 0.99 and abs(amaxy - aminy) > 0.99
    pw, ph = float(parent_width), float(parent_height)
    if (
        stretch
        and pw > 32.0
        and ph > 32.0
        and abs(sdx) > 32.0
        and abs(sdy) > 32.0
        and abs(abs(sdx) - pw) < 1.5
        and abs(abs(sdy) - ph) < 1.5
    ):
        return (0.0, 0.0)
    return (sdx, sdy)


def classify_ui_layout_mode(elements) -> str:
    """Classify UI graph: single page, locale duplicates, or multi-page wiki.

    JNSQ/GEP-style .ksp packs dozens of independent prefab roots (each a
    full-bleed Image page). Stock Squad pages usually have 1 root, or 2
    locale roots with lots of TMP text.
    """
    if not elements:
        return "single"
    roots = [
        el for el in elements
        if not int(getattr(el, "parent_rect_path_id", 0) or 0)
    ]
    n_roots = len(roots)
    if n_roots <= 1:
        return "single"
    n_text = sum(
        1
        for el in elements
        if getattr(el, "kind", "") == "text"
        and (getattr(el, "text", "") or "").strip()
    )
    # Many image-only (or near-empty TMP) roots → multipage wiki bundle.
    if n_roots >= 3 and n_text < max(4, n_roots // 2):
        return "multipage"
    if n_roots >= 8:
        return "multipage"
    # 2–4 roots with substantial text → EN/CJK locale duplicates.
    return "locale"


def group_ui_elements_by_root(elements):
    """Return [(root_el, [el, ...subtree including root]), ...] sorted by name."""
    from collections import defaultdict

    kids = defaultdict(list)
    roots = []
    by_id = {}
    for el in elements:
        rid = int(getattr(el, "rect_path_id", 0) or 0)
        if rid:
            by_id[rid] = el
        pid = int(getattr(el, "parent_rect_path_id", 0) or 0)
        if pid:
            kids[pid].append(el)
        else:
            roots.append(el)

    def walk(rid, acc):
        for el in kids.get(int(rid), []):
            acc.append(el)
            walk(int(el.rect_path_id), acc)

    groups = []
    for root in roots:
        acc = [root]
        walk(int(root.rect_path_id), acc)
        groups.append((root, acc))
    groups.sort(key=lambda t: (str(getattr(t[0], "name", "") or "").lower(),
                               int(getattr(t[0], "rect_path_id", 0) or 0)))
    return groups


def prefer_locale_ui_elements(elements, prefer="en"):
    """Keep one root canvas when a .ksp ships multiple locale trees.

    Some KSPedia bundles embed EN + CJK page roots that are both m_IsActive.
    Rendering both stacks double Image/Background planes and mixed text.
    Prefer Latin/EN by default; set prefer to 'cjk' for CJK trees.

    Multi-page wiki bundles (JNSQ/GEP: dozens of Image-only prefabs) must
    keep every root — collapsing them left a single visible texture.
    """
    import re
    from collections import defaultdict

    if not elements:
        return list(elements or [])

    mode = classify_ui_layout_mode(elements)
    if mode == "multipage":
        return list(elements)
    if mode == "single":
        return list(elements)

    kids = defaultdict(list)
    roots = []
    for el in elements:
        pid = int(getattr(el, "parent_rect_path_id", 0) or 0)
        if pid:
            kids[pid].append(el)
        else:
            roots.append(el)
    if len(roots) <= 1:
        return list(elements)

    cjk_re = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
    lat_re = re.compile(r"[A-Za-z]")

    def walk(rid, acc):
        for el in kids.get(int(rid), []):
            acc.append(el)
            walk(int(el.rect_path_id), acc)

    scored = []
    for root in roots:
        acc = [root]
        walk(int(root.rect_path_id), acc)
        blob = "\n".join(
            (el.text or "")
            for el in acc
            if getattr(el, "kind", "") == "text"
        )
        lat = len(lat_re.findall(blob))
        cjk = len(cjk_re.findall(blob))
        scored.append((root, acc, lat, cjk, len(blob)))

    prefer = (prefer or "en").strip().lower()
    if prefer in ("cjk", "zh", "ja", "jp", "ko", "cn"):
        scored.sort(key=lambda t: (t[3], t[2], t[4]), reverse=True)
    else:
        scored.sort(key=lambda t: (t[2], -t[3], t[4]), reverse=True)
    keep = {int(el.rect_path_id) for el in scored[0][1]}
    return [el for el in elements if int(el.rect_path_id) in keep]


def pivot_align(pivot) -> Tuple[str, str]:
    """Map Unity pivot to Blender FONT align_x / align_y."""
    px, py = _f2(pivot, (0.5, 0.5))
    if px < 0.25:
        ax = "LEFT"
    elif px > 0.75:
        ax = "RIGHT"
    else:
        ax = "CENTER"
    if py > 0.75:
        ay = "TOP"
    elif py < 0.25:
        ay = "BOTTOM"
    else:
        ay = "CENTER"
    return ax, ay


# TMP TextAlignmentOptions
# New bitfield (TMP 1.4+): H Left=0x1 Center=0x2 Right=0x4; V Top=0x100 Middle=0x200 Bottom=0x400
# Legacy small ints (KSP often still serializes these): 0=TopLeft 1=Top 2=TopRight ...
_LEGACY_TMP_ALIGN = {
    0: ("LEFT", "TOP"),
    1: ("CENTER", "TOP"),
    2: ("RIGHT", "TOP"),
    3: ("JUSTIFY", "TOP"),
    4: ("LEFT", "CENTER"),
    5: ("CENTER", "CENTER"),
    6: ("RIGHT", "CENTER"),
    7: ("JUSTIFY", "CENTER"),
    8: ("LEFT", "BOTTOM"),
    9: ("CENTER", "BOTTOM"),
    10: ("RIGHT", "BOTTOM"),
    11: ("JUSTIFY", "BOTTOM"),
    12: ("LEFT", "TOP"),
    13: ("CENTER", "TOP"),
    14: ("RIGHT", "TOP"),
    15: ("JUSTIFY", "TOP"),
    16: ("LEFT", "CENTER"),
    17: ("CENTER", "CENTER"),
    18: ("RIGHT", "CENTER"),
    19: ("JUSTIFY", "CENTER"),
    20: ("LEFT", "TOP"),
    21: ("CENTER", "TOP"),
    22: ("RIGHT", "TOP"),
    23: ("JUSTIFY", "TOP"),
}


def tmp_text_align(alignment, pivot=(0.0, 1.0)) -> Tuple[str, str]:
    """Map TMP m_textAlignment to Blender FONT align_x / align_y.

    Prefers the serialized alignment enum (legacy or bitfield). Falls back
    to pivot when alignment is missing/unknown.
    """
    try:
        a = int(alignment or 0)
    except Exception:
        a = 0

    # New bitfield: vertical bits in high byte
    if a & 0xFF00:
        h = a & 0xFF
        v = a & 0xFF00
        if h & 0x4:
            ax = "RIGHT"
        elif h & 0x2:
            ax = "CENTER"
        elif h & 0x8 or h & 0x10:
            ax = "JUSTIFY"
        else:
            ax = "LEFT"
        if v & 0x400:
            ay = "BOTTOM"
        elif v & 0x200:
            # Midline / Middle — vertical center of the rect (tables, badges)
            ay = "CENTER"
        elif v & 0x800:
            # Baseline — treat as bottom-ish for single-line UI labels
            ay = "BOTTOM"
        elif v & 0x1000:
            # Capline ≈ top of capitals
            ay = "TOP"
        else:
            ay = "TOP"
        if ax == "JUSTIFY":
            ax = "LEFT"
        return ax, ay

    if a in _LEGACY_TMP_ALIGN:
        ax, ay = _LEGACY_TMP_ALIGN[a]
        if ax == "JUSTIFY":
            ax = "LEFT"
        return ax, ay

    return pivot_align(pivot)


def tmp_line_spacing_factor(line_spacing) -> float:
    """TMP m_lineSpacing is a %% adjustment of default line height.

    Blender curve.space_line is a multiplier (1.0 = default).
    """
    try:
        ls = float(line_spacing)
    except Exception:
        ls = 0.0
    factor = 1.0 + (ls / 100.0)
    if factor < 0.5:
        factor = 0.5
    if factor > 3.0:
        factor = 3.0
    return factor


def tmp_char_word_spacing_factor(spacing_pct) -> float:
    """TMP m_characterSpacing / m_wordSpacing (%%) → Blender FONT multiplier.

    Stock KSPedia uses 0 → Blender space_character / space_word = 1.0.
    """
    try:
        pct = float(spacing_pct)
    except Exception:
        pct = 0.0
    factor = 1.0 + (pct / 100.0)
    if factor < 0.05:
        factor = 0.05
    if factor > 5.0:
        factor = 5.0
    return factor


def estimate_sibling_row_pitch_px(el, crect, elements, rects):
    """Table row pitch (px) for a tall multi-line TMP column.

    Prefer ``box_h / max_lines`` across tall text siblings under the same
    parent (e.g. Level ``0..5`` → 6 rows even when Pilots has only 4 lines).
    That keeps sparse skill columns on the baked grid instead of
    ``box_h / n_lines`` compressing them across the full height.

    Fallback: median height of short overlapping siblings; else None
    (caller uses ``box_h / n_lines``).
    """
    if crect is None or el is None:
        return None
    try:
        tall_h = abs(float(crect.height))
        tall_left = float(crect.xmin)
        tall_right = float(crect.xmax)
    except Exception:
        return None
    if tall_h < 1.0:
        return None
    parent = getattr(el, "parent_rect_path_id", None)
    self_id = getattr(el, "rect_path_id", None)
    heights = []
    # (n_lines, pitch_px) for self + peer tall text columns
    tall_line_counts = []
    self_text = getattr(el, "text", "") or ""
    if "\n" in self_text or "\\n" in self_text:
        pl = self_text.replace("\\n", "\n")
        nln = max(pl.count("\n") + 1, 1)
        tall_line_counts.append((nln, float(tall_h) / float(nln)))
    for other in elements or ():
        if other is el:
            continue
        if self_id is not None and getattr(other, "rect_path_id", None) == self_id:
            continue
        if parent is not None and getattr(other, "parent_rect_path_id", None) != parent:
            continue
        kind = getattr(other, "kind", "") or ""
        if kind not in ("text", "image"):
            continue
        try:
            oid = int(other.rect_path_id)
        except Exception:
            continue
        orect = rects.get(oid) if rects else None
        if orect is None:
            continue
        try:
            oh = abs(float(orect.height))
            ol = float(orect.xmin)
            oright = float(orect.xmax)
        except Exception:
            continue
        # Peer tall text columns (same table body band).
        if kind == "text" and oh >= tall_h * 0.7:
            ot = getattr(other, "text", "") or ""
            if "\n" in ot or "\\n" in ot:
                pl = ot.replace("\\n", "\n")
                nln = max(pl.count("\n") + 1, 1)
                tall_line_counts.append((nln, float(oh) / float(nln)))
            continue
        # Short cells (header / digit) with overlapping X.
        if oh < 4.0 or oh >= tall_h * 0.45:
            continue
        if oright <= tall_left + 1.0 or ol >= tall_right - 1.0:
            continue
        heights.append(oh)
    pitch_from_tall = None
    n_from_tall = 0
    if tall_line_counts:
        # Prefer pitch from the sibling with the most lines (Level 0..5),
        # not tall_h/max_lines on a shorter skill column (that compresses).
        tall_line_counts.sort(key=lambda t: (t[0], t[1]))
        n_from_tall, pitch_from_tall = tall_line_counts[-1]
        if n_from_tall < 2 or pitch_from_tall <= 1e-6:
            pitch_from_tall = None
            n_from_tall = 0

    pitch_from_short = None
    n_from_short = 0
    if heights:
        heights.sort()
        n = len(heights)
        mid = n // 2
        if n % 2:
            med_h = float(heights[mid])
        else:
            med_h = 0.5 * (float(heights[mid - 1]) + float(heights[mid]))
        if med_h > 1.0:
            # Estimate row count from short header/digit stack across the band.
            n_from_short = max(2, int(round(float(tall_h) / med_h)))
            pitch_from_short = float(tall_h) / float(n_from_short)

    # Prefer max-lines tall peer pitch. Short-sibling denser estimate used to
    # crush Career Limits / body prose when image "Level N" labels leaked in.
    if pitch_from_tall is not None:
        return float(pitch_from_tall)
    if pitch_from_short is not None:
        return float(pitch_from_short)
    return None


def tmp_content_box_local(width, height, pivot, margin=(0.0, 0.0, 0.0, 0.0)):
    """Content box in pivot-local units for Blender FONT text_boxes.

    Returns ``(x, y, w, h)`` where ``(x, y)`` is the lower-left corner of the
    TMP content rectangle relative to the Unity pivot (object origin), and
    ``w``/``h`` are the box size.  Matches Unity's rect-around-pivot plus
    TMP ``m_margin`` (left, top, right, bottom).

    Callers pass this lower-left tuple into ``viewport.create_ui_text``,
    which maps it onto Blender FONT ``text_boxes`` (TOP uses y=top with
    height=0 so glyphs hang down; Midline/Bottom keep a real height and
    shift manually — Blender rises glyphs above y when height>0).
    """
    try:
        W = float(width)
        H = float(height)
    except Exception:
        W, H = 0.0, 0.0
    px, py = _f2(pivot, (0.0, 1.0))
    try:
        ml, mt, mr, mb = [float(v) for v in margin]
    except Exception:
        ml = mt = mr = mb = 0.0
    left = -px * W + ml
    right = (1.0 - px) * W - mr
    top = (1.0 - py) * H - mt
    bottom = -py * H + mb
    w = max(right - left, 1e-6)
    h = max(top - bottom, 1e-6)
    return left, bottom, w, h
