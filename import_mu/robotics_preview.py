# vim:ts=4:et
# <pep8 compliant>
"""Viewport/GIF preview motion for Breaking Ground (Serenity) robotics.

Stock hinge/piston/rotoServo/rotor .mu files have **no** Animation clips -
ModuleRobotic* drives ``servoTransformName`` (usually TopJoint) at runtime.
Synthesize a short NLA clip from part.cfg so import + ultimate_anim_test GIFs
show mechanical motion. Tagged ``mu_fx_preview`` so export skips them.

Bind pose is stashed (and mirrored to ``mu_unity_*``) so stock export keeps the
authored rest - never the hardMin GIF pose - for FILE:nodes round-trip.
"""

from __future__ import annotations

import math
import re

import bpy
from mathutils import Euler, Quaternion, Vector

from ..utils.action_compat import fcurve_new, push_action_to_nla

# Unity mainAxis -> Blender euler channel (Y-up Unity -> Z-up Blender).
# rotation_euler indices are always X,Y,Z regardless of rotation_mode.
_AXIS_EULER = {"X": 0, "Y": 2, "Z": 1}
_AXIS_LOC = {"X": 0, "Y": 2, "Z": 1}

_ROBOTIC_MODULES = (
    "ModuleRoboticServoHinge",
    "ModuleRoboticRotationServo",
    "ModuleRoboticServoPiston",
    "ModuleRoboticServoRotor",
)

_CLIP_NAME = "ServoOperate"
_CLIP_SEC = 1.0


def _strip_blender_suffix(name: str) -> str:
    if not name:
        return ""
    wedge = "\u2227"
    if wedge in name:
        name = name.split(wedge, 1)[0]
    if "." in name:
        base, _, suf = name.rpartition(".")
        if suf.isdigit():
            name = base
    return name


def _find_object_by_transform_name(name: str, root=None):
    if not name:
        return None
    want = name.lower()

    def _match(o):
        return _strip_blender_suffix(o.name or "").lower() == want

    if root is not None:
        stack = [root]
        while stack:
            o = stack.pop()
            if _match(o):
                return o
            stack.extend(list(o.children))
    for o in bpy.data.objects:
        if _match(o):
            return o
    return None


def _find_child_named(parent, name: str):
    """Depth-first under parent (e.g. Bar1 under BottomJoint)."""
    if parent is None:
        return None
    want = name.lower()
    stack = list(parent.children)
    while stack:
        o = stack.pop()
        if _strip_blender_suffix(o.name or "").lower() == want:
            return o
        stack.extend(list(o.children))
    return None


def _module_bodies(cfg_text: str):
    if not cfg_text:
        return
    for m in re.finditer(r"MODULE\s*\{", cfg_text, re.I):
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(cfg_text):
            ch = cfg_text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    body = cfg_text[start + 1:i]
                    break
            i += 1
        else:
            continue
        nm = re.search(r"^\s*name\s*=\s*(.+)$", body, re.M | re.I)
        if not nm:
            continue
        mod = nm.group(1).strip().strip('"').split("//")[0].strip()
        yield mod, body


def _cfg_field(body: str, key: str, default=None):
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+)$", body, re.M | re.I)
    if not m:
        return default
    return m.group(1).strip().strip('"').split("//")[0].strip()


def _parse_vec2(raw):
    if not raw:
        return None
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except Exception:
        return None


def parse_robotic_servos(cfg_text: str):
    out = []
    for mod, body in _module_bodies(cfg_text):
        if mod not in _ROBOTIC_MODULES:
            continue
        # KSP BaseServo.mainAxis default is Z (hinge_03/04 omit it).
        # Pistons/rotors/rotation servos ship explicit Y in stock CFG.
        if "Piston" in mod or "Rotor" in mod or "RotationServo" in mod:
            axis_default = "Y"
        else:
            axis_default = "Z"
        axis = (_cfg_field(body, "mainAxis", axis_default) or axis_default).upper()[:1]
        if axis not in "XYZ":
            axis = axis_default
        servo = _cfg_field(body, "servoTransformName", "TopJoint") or "TopJoint"
        base = _cfg_field(body, "baseTransformName", "") or ""
        limits = (
            _parse_vec2(_cfg_field(body, "hardMinMaxLimits"))
            or _parse_vec2(_cfg_field(body, "softMinMaxAngles"))
            or _parse_vec2(_cfg_field(body, "softMinMaxExtension"))
        )
        rpm = _cfg_field(body, "rpmLimit")
        try:
            rpm_f = float(rpm) if rpm is not None else None
        except Exception:
            rpm_f = None
        init_ang = _cfg_field(body, "modelInitialAngle")
        try:
            init_ang_f = float(init_ang) if init_ang is not None else 0.0
        except Exception:
            init_ang_f = 0.0
        slaves_raw = _cfg_field(body, "slaveTransformNames", "") or ""
        slaves = [
            s.strip() for s in slaves_raw.replace(";", ",").split(",") if s.strip()
        ]
        kind = "rotate"
        if "Piston" in mod:
            kind = "translate"
        elif "Rotor" in mod and "RotationServo" not in mod:
            kind = "spin"
        out.append({
            "module": mod,
            "kind": kind,
            "servo": servo,
            "base": base,
            "axis": axis,
            "limits": limits,
            "rpm": rpm_f,
            "modelInitialAngle": init_ang_f,
            "slaves": slaves,
        })
    return out


def _parent_axis_scale(obj, axis: str) -> float:
    """World meters per local unit along the keyed Blender axis."""
    try:
        idx = _AXIS_LOC.get(axis, 2)
        local = Vector((0.0, 0.0, 0.0))
        local[idx] = 1.0
        parent = obj.parent
        if parent is not None:
            w = parent.matrix_world.to_3x3() @ local
            return max(1e-6, float(w.length))
        sc = obj.matrix_world.to_scale()
        return max(1e-6, abs(float(sc[idx])))
    except Exception:
        return 1.0


def _tag_fx(id_data, *, export_skip=True):
    """Tag preview data. export_skip → mu_fx_preview (export filters actions).

    NLA tracks must NOT get mu_fx_preview - ultimate_anim_test skips those
    tracks when collecting GIF clips. Use mu_robotic_preview on tracks only.
    """
    try:
        id_data["mu_robotic_preview"] = 1
        if export_skip:
            id_data["mu_fx_preview"] = 1
    except Exception:
        pass


def _make_action(obj, clip_name):
    _tag_fx(obj, export_skip=False)
    act = bpy.data.actions.new(f"{obj.name}.{clip_name}")
    _tag_fx(act)
    try:
        act["mu_clip_name"] = clip_name
        act["mu_anim_host"] = _strip_blender_suffix(obj.name)
    except Exception:
        pass
    return act


def _key_scalar(fc, frame, value):
    kp = fc.keyframe_points
    kp.add(1)
    i = len(kp) - 1
    kp[i].co = (float(frame), float(value))
    kp[i].interpolation = "LINEAR"
    kp[i].handle_left_type = "AUTO"
    kp[i].handle_right_type = "AUTO"


def _current_quat(obj):
    if obj.rotation_mode == "QUATERNION":
        return Quaternion(obj.rotation_quaternion)
    return Euler(obj.rotation_euler, obj.rotation_mode).to_quaternion()


def _stash_bind_pose(obj):
    """Remember import TRS before ServoOperate keys (reimport-safe).

    Also mirrors into ``mu_unity_*`` so ``make_transform`` exports the authored
    rest even if the viewport sits on hardMin / GIF end.
    """
    try:
        if "mu_unity_rotation" not in obj:
            q = _current_quat(obj)
            obj["mu_unity_location"] = list(obj.location)
            obj["mu_unity_rotation"] = [q.w, q.x, q.y, q.z]
            obj["mu_unity_scale"] = list(obj.scale)
        if "mu_robotic_bind_loc" not in obj:
            obj["mu_robotic_bind_loc"] = list(obj.location)
        # Normalize to XYZ euler channels for stable axis indexing.
        if obj.rotation_mode == "QUATERNION":
            obj.rotation_mode = "XYZ"
        if "mu_robotic_bind_rot" not in obj:
            obj["mu_robotic_bind_rot"] = list(obj.rotation_euler)
        if "mu_robotic_bind_mode" not in obj:
            obj["mu_robotic_bind_mode"] = obj.rotation_mode
    except Exception:
        pass


def _bind_euler(obj):
    """Import bind euler (XYZ channels); fall back to current."""
    try:
        if "mu_robotic_bind_rot" in obj:
            return list(obj["mu_robotic_bind_rot"])
    except Exception:
        pass
    return list(obj.rotation_euler)


def _has_servo_operate(obj) -> bool:
    ad = getattr(obj, "animation_data", None)
    if not ad:
        return False
    for t in ad.nla_tracks or []:
        try:
            if t.get("mu_robotic_preview") or (t.name or "") == _CLIP_NAME:
                return True
        except Exception:
            if (t.name or "") == _CLIP_NAME:
                return True
    return False


def _attach_rotate(obj, axis, amin, amax, fps, f0, model_initial=0.0):
    """Key hardMin→hardMax as (UI angle - modelInitialAngle) from bind.

    Mesh is authored at modelInitialAngle (alligator hinges = 90). Travel is
    always hardMax-hardMin; do not bake that offset into export rest.
    """
    _stash_bind_pose(obj)
    obj.rotation_mode = "XYZ"
    idx = _AXIS_EULER.get(axis, 2)
    sign = -1.0
    init = float(model_initial or 0.0)
    rest = _bind_euler(obj)
    # Restore bind before keying so re-attach / polluted euler cannot shift rest.
    obj.rotation_euler = rest
    r0 = rest[idx] + math.radians(float(amin) - init) * sign
    r1 = rest[idx] + math.radians(float(amax) - init) * sign
    act = _make_action(obj, _CLIP_NAME)
    for i in range(3):
        fc = fcurve_new(act, obj, "rotation_euler", index=i)
        v0 = r0 if i == idx else rest[i]
        v1 = r1 if i == idx else rest[i]
        _key_scalar(fc, f0, v0)
        _key_scalar(fc, f0 + fps * _CLIP_SEC, v1)
    e = list(rest)
    e[idx] = r0
    obj.rotation_euler = e
    track, _strip = push_action_to_nla(obj, act, _CLIP_NAME)
    _tag_fx(track, export_skip=False)
    return act


def _attach_translate(obj, axis, amin, amax, fps, f0, scale=1.0):
    _stash_bind_pose(obj)
    # Always key from import bind, not polluted post-GIF location
    bind = list(obj.get("mu_robotic_bind_loc", list(obj.location)))
    obj.location = bind
    idx = _AXIS_LOC.get(axis, 2)
    loc = list(bind)
    rest_u = loc[idx]
    # hardMinMaxLimits are world meters; divide by parent axis scale (local keys)
    s = max(1e-6, float(scale) if scale else 1.0)
    v0 = rest_u + float(amin) / s
    v1 = rest_u + float(amax) / s
    act = _make_action(obj, _CLIP_NAME)
    for i in range(3):
        fc = fcurve_new(act, obj, "location", index=i)
        a = v0 if i == idx else loc[i]
        b = v1 if i == idx else loc[i]
        _key_scalar(fc, f0, a)
        _key_scalar(fc, f0 + fps * _CLIP_SEC, b)
    loc[idx] = v0
    obj.location = loc
    track, _strip = push_action_to_nla(obj, act, _CLIP_NAME)
    _tag_fx(track, export_skip=False)
    return act


def _attach_spin(obj, axis, rpm, fps, f0):
    _stash_bind_pose(obj)
    obj.rotation_mode = "XYZ"
    idx = _AXIS_EULER.get(axis, 2)
    rest = _bind_euler(obj)
    obj.rotation_euler = rest
    turns = 1.0
    if rpm and rpm > 0:
        turns = max(1.0, min(3.0, float(rpm) / 60.0 * _CLIP_SEC))
    sign = -1.0
    r0 = rest[idx]
    r1 = r0 + sign * turns * 2.0 * math.pi
    act = _make_action(obj, _CLIP_NAME)
    for i in range(3):
        fc = fcurve_new(act, obj, "rotation_euler", index=i)
        v0 = r0 if i == idx else rest[i]
        v1 = r1 if i == idx else rest[i]
        _key_scalar(fc, f0, v0)
        _key_scalar(fc, f0 + fps * _CLIP_SEC, v1)
    track, _strip = push_action_to_nla(obj, act, _CLIP_NAME)
    _tag_fx(track, export_skip=False)
    return act


def _mesh_vertex_islands(mesh, *, weld_eps=1e-5):
    """Connected vertex components (faces+edges).

    MU export writes unique verts per loop, so a reimported mesh is a triangle
    soup (each tri its own island). Weld coincident positions before walking
    faces so hinge Bar1/Bar2 mesh-align still sees real rod islands after an
    export→import cycle (without this, align is skipped and the upper piston
    looks ~90° twisted).
    """
    n = len(mesh.vertices)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Position weld: reconnect loop-split corners that share a point.
    inv = 1.0 / max(float(weld_eps), 1e-9)
    buckets = {}
    for i, v in enumerate(mesh.vertices):
        key = (
            int(round(v.co.x * inv)),
            int(round(v.co.y * inv)),
            int(round(v.co.z * inv)),
        )
        prev = buckets.get(key)
        if prev is None:
            buckets[key] = i
        else:
            uni(prev, i)

    for poly in mesh.polygons:
        vs = list(poly.vertices)
        for v in vs[1:]:
            uni(vs[0], v)
    for e in mesh.edges:
        uni(e.vertices[0], e.vertices[1])
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _aabb_longest_axis(coords) -> int:
    if not coords:
        return 1
    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]
    extents = (
        max(xs) - min(xs),
        max(ys) - min(ys),
        max(zs) - min(zs),
    )
    return int(max(range(3), key=lambda i: extents[i]))


def _mesh_longest_local_axis(obj) -> int:
    """Longest local AABB axis (0/1/2 = X/Y/Z).

    hinge_04 Bar1/Bar2 are multi-island (3 rod pairs): whole-mesh AABB is long
    on the *spacing* axis (X), not the rod axis (Y). Use the largest island.
    """
    try:
        if obj.type != "MESH" or not obj.data or not obj.data.vertices:
            return 1
        mesh = obj.data
        islands = _mesh_vertex_islands(mesh)
        if len(islands) > 1:
            # Equal vert counts (hinge_04 rods): pick island with largest extent
            def _extent(idxs):
                cs = [mesh.vertices[i].co for i in idxs]
                return max(
                    max(c.x for c in cs) - min(c.x for c in cs),
                    max(c.y for c in cs) - min(c.y for c in cs),
                    max(c.z for c in cs) - min(c.z for c in cs),
                )
            big = max(islands, key=_extent)
            coords = [mesh.vertices[i].co for i in big]
            return _aabb_longest_axis(coords)
        coords = [v.co for v in mesh.vertices]
        return _aabb_longest_axis(coords)
    except Exception:
        return 1


def _bar_damped_track_axis(bar, target) -> str:
    """DAMPED_TRACK axis on mesh long AABB.

    hinge_03_s: Bar1 long Z → TRACK_NEGATIVE_Z (rod down). Bar2 long Y →
    TRACK_Y (user-confirmed; local-target sign picked NEGATIVE_Y wrongly).
    """
    names = (
        ("TRACK_X", "TRACK_NEGATIVE_X"),
        ("TRACK_Y", "TRACK_NEGATIVE_Y"),
        ("TRACK_Z", "TRACK_NEGATIVE_Z"),
    )
    ax = _mesh_longest_local_axis(bar)
    # Prefer positive track for Y-long rods (Bar2); negative Z for Z-long (Bar1).
    if ax == 1:
        return "TRACK_Y"
    if ax == 2:
        return "TRACK_NEGATIVE_Z"
    # X-long: sign from target
    try:
        to_tgt = target.matrix_world.translation - bar.matrix_world.translation
        local = bar.matrix_world.to_3x3().inverted() @ to_tgt
        if float(local[ax]) < 0.0:
            return names[ax][1]
        return names[ax][0]
    except Exception:
        return names[ax][0]




def _mesh_principal_long_axis(obj):
    """Unit local-space vector along the mesh's longest principal axis."""
    try:
        import numpy as np
        co = np.array([tuple(v.co) for v in obj.data.vertices], dtype=float)
        if len(co) < 3:
            return None
        cc = co - co.mean(axis=0)
        _u, _s, vh = np.linalg.svd(cc, full_matrices=False)
        axis = Vector((float(vh[0, 0]), float(vh[0, 1]), float(vh[0, 2])))
        if axis.length < 1e-9:
            return None
        return axis.normalized()
    except Exception:
        # Fallback: AABB longest axis
        ax = _mesh_longest_local_axis(obj)
        v = Vector((0.0, 0.0, 0.0))
        v[ax] = 1.0
        return v


def _track_axis_local_vector(track_name: str) -> Vector:
    """Local unit vector matching a DAMPED_TRACK track_axis enum."""
    m = {
        "TRACK_X": Vector((1, 0, 0)),
        "TRACK_NEGATIVE_X": Vector((-1, 0, 0)),
        "TRACK_Y": Vector((0, 1, 0)),
        "TRACK_NEGATIVE_Y": Vector((0, -1, 0)),
        "TRACK_Z": Vector((0, 0, 1)),
        "TRACK_NEGATIVE_Z": Vector((0, 0, -1)),
    }
    return m.get(track_name, Vector((0, 0, -1)))


def _align_bar_mesh_to_track(bar, track_name: str) -> bool:
    """Rotate mesh data so its visual rod axis matches the DAMPED_TRACK axis.

    Object rotation is overridden by DAMPED_TRACK; only mesh data persists.
    hinge_03_s Bar1 mesh is ~18 deg off +Z — without this the rod looks cocked.
    Rotate the whole mesh about the *shaft* (dominant island) centroid: pivoting
    on the rod line keeps the shaft in place, while the flared caps swing into
    line. Meshes with several *separate* long rods (hinge_04's rod pairs) are
    skipped — a global rotation would tilt them.
    """
    if bar is None or bar.type != "MESH" or not bar.data or not bar.data.vertices:
        return False
    if bar.get("mu_robotic_mesh_aligned"):
        return False
    mesh = bar.data
    try:
        islands = _mesh_vertex_islands(mesh)
    except Exception:
        islands = []
    if not islands:
        return False

    def _extent(idxs):
        cs = [mesh.vertices[i].co for i in idxs]
        return max(
            max(c.x for c in cs) - min(c.x for c in cs),
            max(c.y for c in cs) - min(c.y for c in cs),
            max(c.z for c in cs) - min(c.z for c in cs),
        )

    def _centroid(idxs):
        n = float(len(idxs))
        return Vector(
            (
                sum(mesh.vertices[i].co.x for i in idxs) / n,
                sum(mesh.vertices[i].co.y for i in idxs) / n,
                sum(mesh.vertices[i].co.z for i in idxs) / n,
            )
        )

    big = max(islands, key=_extent)
    big_dir = _mesh_principal_long_axis(_MeshView(mesh, big))
    if big_dir is None:
        return False
    big_cen = _centroid(big)
    big_r = 0.0
    for i in big:
        w = mesh.vertices[i].co - big_cen
        perp = w - w.dot(big_dir) * big_dir
        big_r = max(big_r, perp.length)
    if len(islands) > 1:
        # A second long island whose centroid sits off the big rod line means
        # this mesh is several distinct rods (hinge_04) — do not touch it.
        for other in islands:
            if other is big or len(other) < 3:
                continue
            if _extent(other) < 0.5 * _extent(big):
                continue
            oc = _centroid(other)
            w = oc - big_cen
            perp = w - w.dot(big_dir) * big_dir
            if perp.length > max(big_r * 2.0, 1e-4):
                return False
    want = _track_axis_local_vector(track_name)
    shaft = big_dir
    if shaft.angle(want) > (-shaft).angle(want):
        shaft = -shaft
    try:
        if float(shaft.angle(want)) < math.radians(1.0):
            bar["mu_robotic_mesh_aligned"] = 1
            return False
    except Exception:
        pass
    try:
        rot3 = shaft.rotation_difference(want).to_matrix()
        # Backup stock verts for export restore (constraint cannot rotate mesh)
        if "mu_robotic_mesh_backup" not in bar:
            flat = []
            for v in mesh.vertices:
                flat.extend((float(v.co.x), float(v.co.y), float(v.co.z)))
            bar["mu_robotic_mesh_backup"] = flat
        # The ~18deg mesh tilt is authored so the rod's attachment end lands on
        # the object origin. Pivot on that end (shaft extreme nearest origin):
        # the end stays put and the rod swings straight onto the track axis,
        # keeping Bar1/Bar2 collinear instead of shifted off to one side.
        pmin = None
        pmax = None
        tmin = None
        tmax = None
        for i in big:
            co = mesh.vertices[i].co
            t = co.dot(shaft)
            if tmin is None or t < tmin:
                tmin = t
                pmin = co.copy()
            if tmax is None or t > tmax:
                tmax = t
                pmax = co.copy()
        pivot = pmin if pmin.length <= pmax.length else pmax
        for v in mesh.vertices:
            p = v.co - pivot
            v.co = rot3 @ p + pivot
        mesh.update()
        bar["mu_robotic_mesh_aligned"] = 1
        print(
            f"INFO: robotics preview mesh-align {bar.name} "
            f"-> {track_name} ({math.degrees(shaft.angle(want)):.1f} deg)"
        )
        return True
    except Exception as e:
        print(f"WARNING: robotics preview mesh-align {bar.name}: {e}")
        return False


class _MeshView:
    """Slim stand-in exposing ``data.vertices`` for one island."""

    __slots__ = ("_mesh", "_idxs")

    def __init__(self, mesh, idxs):
        self._mesh = mesh
        self._idxs = idxs

    @property
    def type(self):
        return "MESH"

    @property
    def data(self):
        class _D:
            __slots__ = ("_vs",)

            def __init__(self, vs):
                self._vs = vs

            @property
            def vertices(self):
                return self._vs

        return _D([self._mesh.vertices[i] for i in self._idxs])


def _make_bar_aim_empty(name, parent, world_loc, collection):
    """Empty parented to joint (not the bar) — aim target without depsgraph cycle."""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.02
    try:
        collection.objects.link(obj)
    except Exception:
        bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    try:
        inv = parent.matrix_world.inverted()
        obj.location = inv @ world_loc
    except Exception:
        obj.location = (0.0, 0.0, 0.0)
    try:
        obj["mu_robotic_preview"] = 1
        obj["mu_fx_preview"] = 1
    except Exception:
        pass
    _tag_fx(obj, export_skip=True)
    return obj


def _attach_hinge_linkage_bars(servo_obj, base_obj, root):
    """Preview-only: alligator Bar1/Bar2 aim via joint empties (no deps cycle).

    Stock hinge_03/04 rod is two meshes (Bar1 under base, Bar2 under TopPlate).
    Mutual DAMPED_TRACK cycles depsgraph; Bar1-only left Bar2 static. Aim
    empties parented to joints give both rods motion. Track axis from mesh AABB.
    """
    bar1 = _find_child_named(base_obj, "Bar1") or _find_object_by_transform_name(
        "Bar1", root
    )
    bar2 = _find_child_named(servo_obj, "Bar2") or _find_object_by_transform_name(
        "Bar2", root
    )
    if bar1 is None or bar2 is None:
        return 0
    for bar in (bar1, bar2):
        try:
            _stash_bind_pose(bar)
            for c in list(bar.constraints):
                try:
                    if c.get("mu_robotic_preview") or (
                        c.name or ""
                    ).startswith("ServoBar"):
                        bar.constraints.remove(c)
                except Exception:
                    pass
        except Exception:
            pass
    for obj in list(bpy.data.objects):
        try:
            if obj.get("mu_robotic_preview") and obj.name.startswith("ServoBarAim."):
                bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    col = None
    try:
        if root is not None and root.users_collection:
            col = root.users_collection[0]
    except Exception:
        col = None
    if col is None:
        col = bpy.context.scene.collection

    parent1 = bar1.parent if bar1.parent is not None else base_obj
    parent2 = bar2.parent if bar2.parent is not None else servo_obj
    try:
        w1 = bar1.matrix_world.translation.copy()
        w2 = bar2.matrix_world.translation.copy()
    except Exception:
        return 0

    aim_for_bar1 = _make_bar_aim_empty("ServoBarAim.Bar2", parent2, w2, col)
    aim_for_bar2 = _make_bar_aim_empty("ServoBarAim.Bar1", parent1, w1, col)

    tax1 = _bar_damped_track_axis(bar1, aim_for_bar1)
    tax2 = _bar_damped_track_axis(bar2, aim_for_bar2)
    made = 0
    for bar, aim, tax, label in (
        (bar1, aim_for_bar1, tax1, "Bar1"),
        (bar2, aim_for_bar2, tax2, "Bar2"),
    ):
        try:
            _align_bar_mesh_to_track(bar, tax)
            c = bar.constraints.new("DAMPED_TRACK")
            c.name = "ServoBarTrack"
            c.target = aim
            c.track_axis = tax
            try:
                c["mu_robotic_preview"] = 1
            except Exception:
                pass
            _tag_fx(bar, export_skip=False)
            made += 1
        except Exception as e:
            print(f"WARNING: robotics preview bar track on {label}: {e}")
    if made:
        print(
            f"INFO: robotics preview hinge bars "
            f"{bar1.name}[{tax1}]<->{bar2.name}[{tax2}] via aim empties"
        )
    return made



def _first_key_value(fc, default):
    try:
        kps = fc.keyframe_points
        if kps:
            return float(kps[0].co[1])
    except Exception:
        pass
    return float(default)


def reset_robotics_preview_to_start(scene=None):
    """Force ServoOperate hosts to hardMin / frame start (GIF scrub start).

    Call before each GIF panel. Do **not** use this before stock export - that
    would bake hardMin into transforms without ``mu_unity_*``. Prefer
    ``restore_robotics_bind_pose`` before export.
    """
    scene = scene or bpy.context.scene
    try:
        f0 = int(scene.frame_start)
        scene.frame_set(f0)
    except Exception:
        f0 = 1
    for obj in bpy.data.objects:
        try:
            if not obj.get("mu_robotic_preview") and not (
                obj.animation_data and any(
                    t.get("mu_robotic_preview")
                    for t in (obj.animation_data.nla_tracks or [])
                )
            ):
                ad0 = getattr(obj, "animation_data", None)
                if not ad0 or not any(
                    (t.name or "") == _CLIP_NAME for t in ad0.nla_tracks
                ):
                    continue
        except Exception:
            continue
        ad = getattr(obj, "animation_data", None)
        if not ad:
            continue
        try:
            ad.action = None
        except Exception:
            pass
        act = None
        for track in ad.nla_tracks:
            try:
                if track.get("mu_robotic_preview") or (track.name or "") == _CLIP_NAME:
                    for strip in track.strips:
                        if strip.action:
                            act = strip.action
                            break
            except Exception:
                pass
            if act:
                break
        if act is None:
            continue
        from ..utils.action_compat import iter_action_fcurves
        loc = list(obj.location)
        rot = list(obj.rotation_euler)
        for fc in iter_action_fcurves(act):
            dp = getattr(fc, "data_path", "") or ""
            idx = int(getattr(fc, "array_index", 0) or 0)
            if dp == "location" and 0 <= idx < 3:
                loc[idx] = _first_key_value(fc, loc[idx])
            elif dp == "rotation_euler" and 0 <= idx < 3:
                rot[idx] = _first_key_value(fc, rot[idx])
        obj.location = loc
        try:
            obj.rotation_mode = "XYZ"
        except Exception:
            pass
        obj.rotation_euler = rot
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    try:
        scene.frame_set(f0)
        bpy.context.view_layer.update()
    except Exception:
        pass


def restore_robotics_bind_pose(scene=None):
    """Restore authored import TRS on robotics hosts (safe for stock export).

    Clears active action evaluation leftover and applies ``mu_robotic_bind_*``
    / ``mu_unity_*``. Call before export so reimport rest matches stock MU.
    """
    scene = scene or bpy.context.scene
    for obj in bpy.data.objects:
        try:
            if "mu_robotic_bind_loc" not in obj and "mu_robotic_bind_rot" not in obj:
                if not obj.get("mu_robotic_preview"):
                    continue
        except Exception:
            continue
        ad = getattr(obj, "animation_data", None)
        if ad is not None:
            try:
                ad.action = None
            except Exception:
                pass
        try:
            if "mu_robotic_bind_loc" in obj:
                obj.location = list(obj["mu_robotic_bind_loc"])
            elif "mu_unity_location" in obj:
                obj.location = list(obj["mu_unity_location"])
        except Exception:
            pass
        try:
            if "mu_unity_rotation" in obj:
                obj.rotation_mode = "QUATERNION"
                obj.rotation_quaternion = Quaternion(obj["mu_unity_rotation"])
            elif "mu_robotic_bind_rot" in obj:
                mode = obj.get("mu_robotic_bind_mode") or "XYZ"
                try:
                    obj.rotation_mode = mode
                except Exception:
                    obj.rotation_mode = "XYZ"
                obj.rotation_euler = list(obj["mu_robotic_bind_rot"])
        except Exception:
            pass
        try:
            if "mu_unity_scale" in obj:
                obj.scale = list(obj["mu_unity_scale"])
        except Exception:
            pass
        try:
            if (
                obj.type == "MESH"
                and obj.data
                and "mu_robotic_mesh_backup" in obj
            ):
                flat = list(obj["mu_robotic_mesh_backup"])
                verts = obj.data.vertices
                n = min(len(verts), len(flat) // 3)
                for i in range(n):
                    verts[i].co = (
                        float(flat[3 * i]),
                        float(flat[3 * i + 1]),
                        float(flat[3 * i + 2]),
                    )
                obj.data.update()
                if "mu_robotic_mesh_aligned" in obj:
                    del obj["mu_robotic_mesh_aligned"]
        except Exception:
            pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    try:
        scene.frame_set(int(scene.frame_start))
        bpy.context.view_layer.update()
    except Exception:
        pass


def attach_robotics_preview(root, cfg_text: str) -> int:
    servos = parse_robotic_servos(cfg_text)
    if not servos:
        return 0
    scene = bpy.context.scene
    try:
        fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)
    except Exception:
        fps = 24.0
    fps = max(1.0, fps)
    f0 = float(scene.frame_start)
    made = 0
    for servo in servos:
        obj = _find_object_by_transform_name(servo["servo"], root)
        if obj is None:
            print("WARNING: robotics preview: missing servo "
                  f"{servo['servo']!r} ({servo['module']})")
            continue
        base_obj = None
        if servo.get("base"):
            base_obj = _find_object_by_transform_name(servo["base"], root)
        if _has_servo_operate(obj):
            continue
        ad = getattr(obj, "animation_data", None)
        if ad and ad.nla_tracks:
            has_real = False
            for t in ad.nla_tracks:
                try:
                    if t.get("mu_fx_preview") or t.get("mu_robotic_preview"):
                        continue
                except Exception:
                    pass
                if t.name and t.name != _CLIP_NAME:
                    has_real = True
                    break
            if has_real:
                continue

        kind = servo["kind"]
        axis = servo["axis"]
        limits = servo["limits"]
        try:
            if kind == "translate":
                amin, amax = limits if limits else (0.0, 1.0)
                if abs(amax - amin) < 1e-6:
                    amax = amin + 1.0
                axis_scale = _parent_axis_scale(obj, axis)
                _attach_translate(obj, axis, amin, amax, fps, f0, scale=axis_scale)
                # Telescoping sleeves: interpolate between base (0) and servo
                slaves = servo.get("slaves") or []
                n_sl = len(slaves)
                for si, sname in enumerate(slaves):
                    sobj = _find_object_by_transform_name(sname, root)
                    if sobj is None:
                        print(f"WARNING: robotics preview: missing slave "
                              f"{sname!r}")
                        continue
                    if _has_servo_operate(sobj):
                        continue
                    # first listed = closest to servo → highest fraction
                    frac = float(n_sl - si) / float(n_sl + 1)
                    s_amin = float(amin) * frac
                    s_amax = float(amax) * frac
                    s_scale = _parent_axis_scale(sobj, axis)
                    _attach_translate(
                        sobj, axis, s_amin, s_amax, fps, f0, scale=s_scale
                    )
                    made += 1
            elif kind == "spin":
                _attach_spin(obj, axis, servo.get("rpm"), fps, f0)
            else:
                amin, amax = limits if limits else (-90.0, 90.0)
                if abs(amax - amin) < 1e-3:
                    amax = amin + 90.0
                init = float(servo.get("modelInitialAngle") or 0.0)
                _attach_rotate(
                    obj, axis, amin, amax, fps, f0,
                    model_initial=init,
                )
                # Alligator hydraulic bars (no CFG slaves)
                if "Hinge" in (servo.get("module") or ""):
                    _attach_hinge_linkage_bars(obj, base_obj, root)
            made += 1
            init_s = servo.get("modelInitialAngle") or 0.0
            extra = f", init={init_s}" if init_s else ""
            print(f"INFO: robotics preview {servo['module']} -> "
                  f"{obj.name} ({kind} {axis}{extra})")
        except Exception as e:
            print(f"WARNING: robotics preview failed on {obj.name}: {e}")
    if made:
        try:
            end = int(round(f0 + fps * _CLIP_SEC))
            if scene.frame_end < end:
                scene.frame_end = end
        except Exception:
            pass
        try:
            from .animation import finalize_animation_preview
            finalize_animation_preview()
        except Exception:
            pass
        try:
            reset_robotics_preview_to_start(scene)
        except Exception:
            pass
    return made
