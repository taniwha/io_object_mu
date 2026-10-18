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
"""Blender 4.x / 5.x Action FCurve compatibility helpers.

Blender 5.0 removed legacy ``action.fcurves``; FCurves live in layered
channelbags. Prefer ``fcurve_ensure_for_datablock`` when creating keys.

Also stores MuClip / MuCurve wrap modes and MuAnimation.autoPlay as
IDProperties on Actions so import → edit → export is non-destructive.
"""

import hashlib

import bpy

try:
    from bpy_extras import anim_utils
except ImportError:
    anim_utils = None

# Blender caps every IDProperty *name* at 63 chars — long FCurve data_paths
# cannot be used as flat keys. Store per-curve data in nested bags instead.
_MU_CWRAP_BAG = "mu_cwrap"
_MU_PP_BAK_BAG = "mu_pp_bak"
_IDPROP_NAME_MAX = 63


def iter_action_fcurves(action):
    """Yield all FCurves on an Action (legacy or layered)."""
    if action is None:
        return
    if hasattr(action, "fcurves"):
        for fc in action.fcurves:
            yield fc
        return
    # Blender 5.x layered actions
    if anim_utils is not None:
        for slot in getattr(action, "slots", []):
            bag = anim_utils.action_get_channelbag_for_slot(action, slot)
            if bag is not None:
                for fc in bag.fcurves:
                    yield fc
        return
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for slot in getattr(action, "slots", []):
                bag = strip.channelbag(slot) if hasattr(strip, "channelbag") else None
                if bag is not None:
                    for fc in bag.fcurves:
                        yield fc


def count_action_fcurves(action):
    return sum(1 for _ in iter_action_fcurves(action))


def ensure_action_assigned(datablock, action):
    """Assign action to datablock so fcurve_ensure_for_datablock can work."""
    if not hasattr(datablock, "animation_data"):
        return
    if not datablock.animation_data:
        datablock.animation_data_create()
    ad = datablock.animation_data
    if ad.action != action:
        ad.action = action
    # Blender 5: ensure a slot is selected when available
    if hasattr(ad, "action_slot") and hasattr(action, "slots"):
        if action.slots and getattr(ad, "action_slot", None) is None:
            try:
                ad.action_slot = action.slots[0]
            except Exception:
                pass


def fcurve_new(action, datablock, data_path, index=0):
    """Create (or ensure) an FCurve on action for datablock."""
    if datablock is None:
        raise ValueError("fcurve_new: datablock is None "
                         f"(data_path={data_path!r})")
    if hasattr(action, "fcurves"):
        return action.fcurves.new(data_path=data_path, index=index)
    # Blender 5.x
    ensure_action_assigned(datablock, action)
    return action.fcurve_ensure_for_datablock(datablock, data_path, index=index)


def push_action_to_nla(obj, action, track_name):
    """Create an NLA track/strip for action on obj (Blender 4/5 safe)."""
    try:
        _ = obj.name
        if not hasattr(obj, "animation_data"):
            print("WARNING: push_action_to_nla: not an Object (%r)" % (type(obj),))
            return None, None
    except ReferenceError:
        print("WARNING: push_action_to_nla skipped — Object already removed")
        return None, None
    if not obj.animation_data:
        obj.animation_data_create()
    ad = obj.animation_data
    # Ensure action is known to the ID before NLA push
    ensure_action_assigned(obj, action)
    track = ad.nla_tracks.new()
    track.name = track_name
    start = int(bpy.context.scene.frame_start)
    strip = None
    try:
        strip = track.strips.new(action.name, start, action)
    except TypeError:
        try:
            strip = track.strips.new(action.name, float(start), action)
        except Exception as e:
            print(f"WARNING: NLA strip create failed on {obj.name}: {e}")
    except Exception as e:
        print(f"WARNING: NLA strip create failed on {obj.name}: {e}")
    if strip is None:
        # Keep the action assigned so export can still find it
        ad.action = action
        return track, None
    try:
        if getattr(strip, "action", None) is None:
            strip.action = action
    except Exception:
        pass
    # Blender 5 slotted actions: clearing ad.action can drop the strip.
    # Only clear on older Blender where NLA-only playback was the norm.
    if bpy.app.version < (5, 0, 0):
        try:
            ad.action = None
        except Exception:
            pass
    return track, strip


# Unity WrapMode values used by MuClip / MuCurve
MU_WRAP_DEFAULT = 0
MU_WRAP_ONCE = 1
MU_WRAP_LOOP = 2
MU_WRAP_PINGPONG = 4
MU_WRAP_CLAMP = 8

MU_WRAP_NAMES = {
    0: "Default",
    1: "Once",
    2: "Loop",
    4: "Ping-Pong",
    8: "Clamp",
}


def mu_wrap_name(mode):
    try:
        return MU_WRAP_NAMES.get(int(mode), f"Unknown({mode})")
    except Exception:
        return "Unknown"


def _curve_key(data_path, index):
    safe = str(data_path).replace("\\", "\\\\").replace("|", "\\|")
    return f"mu_curve_wrap|{safe}|{int(index)}"


def _curve_key_old(data_path, index):
    safe = str(data_path).replace("\\", "\\\\").replace("|", "\\|")
    return f"mu_curve_wrap:{safe}:{int(index)}"


def _fcurve_bag_key(data_path, index):
    """Stable short key for nested IDProperty bags (always well under 63 chars)."""
    idx = int(index)
    path = str(data_path or "")
    digest = hashlib.blake2s(
        path.encode("utf-8", "surrogatepass") + b"\0" + str(idx).encode("ascii"),
        digest_size=10,
    ).hexdigest()
    return f"{digest}|{idx}"


def _ensure_idprop_bag(action, bag_name):
    bag = action.get(bag_name)
    if bag is None:
        action[bag_name] = {}
        bag = action[bag_name]
    return bag


def _parse_wrap_pair(value):
    try:
        if isinstance(value, str):
            a, b = value.split(",", 1)
            return int(a), int(b)
        if isinstance(value, (tuple, list)):
            return int(value[0]), int(value[1])
    except Exception:
        pass
    return None


def _legacy_idprop_get(action, keys):
    for key in keys:
        if len(key) > _IDPROP_NAME_MAX:
            continue
        try:
            value = action.get(key)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def _drop_legacy_idprop_keys(action, keys):
    for key in keys:
        if len(key) > _IDPROP_NAME_MAX:
            continue
        try:
            if key in action:
                del action[key]
        except Exception:
            pass


def set_mu_curve_wrap(action, fcurve, pre_mode, post_mode):
    """Store MuCurve.wrapMode (pre, post) on the Action as an IDProperty."""
    if action is None or fcurve is None:
        return
    try:
        pre_mode = int(pre_mode)
        post_mode = int(post_mode)
    except Exception:
        pre_mode = MU_WRAP_CLAMP
        post_mode = MU_WRAP_CLAMP
    bag = _ensure_idprop_bag(action, _MU_CWRAP_BAG)
    bag[_fcurve_bag_key(fcurve.data_path, fcurve.array_index)] = (
        f"{pre_mode},{post_mode}")
    _drop_legacy_idprop_keys(action, (
        _curve_key(fcurve.data_path, fcurve.array_index),
        _curve_key_old(fcurve.data_path, fcurve.array_index),
    ))


def get_mu_curve_wrap(action, fcurve):
    """Return (pre, post) wrap modes stored on Action for this FCurve."""
    if action is None or fcurve is None:
        return MU_WRAP_CLAMP, MU_WRAP_CLAMP
    bag = action.get(_MU_CWRAP_BAG)
    if bag is not None:
        value = bag.get(_fcurve_bag_key(fcurve.data_path, fcurve.array_index))
        parsed = _parse_wrap_pair(value)
        if parsed is not None:
            return parsed
    value = _legacy_idprop_get(action, (
        _curve_key(fcurve.data_path, fcurve.array_index),
        _curve_key_old(fcurve.data_path, fcurve.array_index),
    ))
    parsed = _parse_wrap_pair(value)
    if parsed is not None:
        return parsed
    return MU_WRAP_CLAMP, MU_WRAP_CLAMP


def _remove_mu_curve_modifiers(fcurve):
    for modifier in list(fcurve.modifiers):
        try:
            if modifier.get("mu_curve_wrap_modifier"):
                fcurve.modifiers.remove(modifier)
        except Exception:
            pass


def apply_mu_curve_wrap(action, fcurve, pre_mode, post_mode):
    """Store MuCurve.wrapMode and mirror Loop/PingPong with a Cycles modifier."""
    try:
        pre_mode = int(pre_mode)
        post_mode = int(post_mode)
    except Exception:
        pre_mode = MU_WRAP_CLAMP
        post_mode = MU_WRAP_CLAMP

    set_mu_curve_wrap(action, fcurve, pre_mode, post_mode)
    _remove_mu_curve_modifiers(fcurve)
    fcurve.extrapolation = 'CONSTANT'

    before = 'NONE'
    after = 'NONE'
    if pre_mode == MU_WRAP_LOOP:
        before = 'REPEAT'
    elif pre_mode == MU_WRAP_PINGPONG:
        before = 'MIRROR'
    if post_mode == MU_WRAP_LOOP:
        after = 'REPEAT'
    elif post_mode == MU_WRAP_PINGPONG:
        after = 'MIRROR'
    if before == 'NONE' and after == 'NONE':
        return
    modifier = fcurve.modifiers.new(type='CYCLES')
    modifier.mode_before = before
    modifier.mode_after = after
    try:
        modifier["mu_curve_wrap_modifier"] = 1
    except Exception:
        pass


def iter_export_keyframes(action, fcurve):
    """Yield keyframe-like objects for .mu export (original keys if Ping-Pong baked).

    Always prefer a stored backup when present — even if mu_pp_baked was
    already cleared — so viewport bake can never reach the .mu file.
    """
    class _K:
        __slots__ = ("co", "handle_left", "handle_right")
    if action is not None:
        raw = _read_pp_backup(action, fcurve)
        if raw:
            try:
                import json
                pts = json.loads(raw) if isinstance(raw, str) else list(raw)
                for pt in pts:
                    k = _K()
                    k.co = (float(pt[0]), float(pt[1]))
                    if len(pt) >= 6:
                        k.handle_left = (float(pt[2]), float(pt[3]))
                        k.handle_right = (float(pt[4]), float(pt[5]))
                    else:
                        k.handle_left = (k.co[0] - 1.0, k.co[1])
                        k.handle_right = (k.co[0] + 1.0, k.co[1])
                    yield k
                return
            except Exception:
                pass
    for kp in fcurve.keyframe_points:
        yield kp



def read_mu_clip_wrap(action):
    """Read MuClip.wrapMode from Action; only 1/2/4/8. Default Once(1)."""
    if action is None:
        return MU_WRAP_ONCE
    try:
        v = action.get("mu_clip_wrap_mode", MU_WRAP_ONCE)
    except Exception:
        v = MU_WRAP_ONCE
    try:
        v = int(v)
    except Exception:
        v = MU_WRAP_ONCE
    if v == MU_WRAP_DEFAULT:
        v = MU_WRAP_ONCE
    if v not in (MU_WRAP_ONCE, MU_WRAP_LOOP, MU_WRAP_PINGPONG, MU_WRAP_CLAMP):
        v = MU_WRAP_ONCE
    return v


def restore_all_pingpong_for_export():
    """Restore original keys on every Ping-Pong-baked Action (export safety).

    Viewport bake must never reach the .mu file. wrapMode stays on the Action.
    Backups are cleared only when every FCurve restored successfully — otherwise
    keep them so iter_export_keyframes can still emit the original keys.
    """
    for action in bpy.data.actions:
        try:
            if not action.get("mu_pp_baked"):
                continue
        except Exception:
            continue
        all_ok = True
        for fc in iter_action_fcurves(action):
            if not _restore_fcurve_from_backup(action, fc):
                # No backup or restore failed for this curve — keep going but
                # do not drop remaining backups for the whole Action.
                all_ok = False
        try:
            if "mu_pp_baked" in action:
                del action["mu_pp_baked"]
        except Exception:
            pass
        if not all_ok:
            continue
        # Clear backups so a later Ping-Pong click re-bakes cleanly
        _clear_pp_backups(action)


def _pp_backup_legacy_key(fcurve):
    return "mu_pp_backup|%s|%d" % (fcurve.data_path, fcurve.array_index)


def _read_pp_backup(action, fcurve):
    if action is None or fcurve is None:
        return None
    bag = action.get(_MU_PP_BAK_BAG)
    if bag is not None:
        raw = bag.get(_fcurve_bag_key(fcurve.data_path, fcurve.array_index))
        if raw:
            return raw
    legacy = _pp_backup_legacy_key(fcurve)
    if len(legacy) <= _IDPROP_NAME_MAX:
        try:
            return action.get(legacy)
        except Exception:
            pass
    return None


def _strip_clip_helpers(fcurve):
    """Remove clip-level CYCLES helpers (Loop / Ping-Pong)."""
    for modifier in list(fcurve.modifiers):
        try:
            if modifier.get("mu_clip_pingpong") or modifier.get("mu_clip_loop"):
                fcurve.modifiers.remove(modifier)
        except Exception:
            pass


def _restore_fcurve_from_backup(action, fcurve):
    """Restore keyframes saved before Ping-Pong bake (if any)."""
    raw = _read_pp_backup(action, fcurve)
    if not raw:
        return False
    try:
        import json
        pts = json.loads(raw) if isinstance(raw, str) else raw
        fcurve.keyframe_points.clear()
        if not pts:
            return True
        fcurve.keyframe_points.add(len(pts))
        for i, pt in enumerate(pts):
            kp = fcurve.keyframe_points[i]
            kp.co = (float(pt[0]), float(pt[1]))
            if len(pt) >= 6:
                kp.handle_left = (float(pt[2]), float(pt[3]))
                kp.handle_right = (float(pt[4]), float(pt[5]))
            else:
                t, v = float(pt[0]), float(pt[1])
                kp.handle_left = (t - 1.0, v)
                kp.handle_right = (t + 1.0, v)
            kp.handle_left_type = 'FREE'
            kp.handle_right_type = 'FREE'
        fcurve.update()
        return True
    except Exception:
        return False


def _backup_fcurve_keys(action, fcurve):
    if action is None or fcurve is None:
        return
    bag_key = _fcurve_bag_key(fcurve.data_path, fcurve.array_index)
    bag = action.get(_MU_PP_BAK_BAG)
    if bag is not None and bag_key in bag:
        return
    legacy = _pp_backup_legacy_key(fcurve)
    if len(legacy) <= _IDPROP_NAME_MAX:
        try:
            if legacy in action:
                return
        except Exception:
            pass
    try:
        import json
        pts = []
        for kp in fcurve.keyframe_points:
            pts.append([
                float(kp.co[0]), float(kp.co[1]),
                float(kp.handle_left[0]), float(kp.handle_left[1]),
                float(kp.handle_right[0]), float(kp.handle_right[1]),
            ])
        payload = json.dumps(pts)
        _ensure_idprop_bag(action, _MU_PP_BAK_BAG)[bag_key] = payload
        if len(legacy) <= _IDPROP_NAME_MAX:
            _drop_legacy_idprop_keys(action, (legacy,))
    except Exception:
        pass


def _action_key_range(action):
    """Return (fmin, fmax) over all keyframes on action, or (None, None)."""
    fmin = fmax = None
    for fc in iter_action_fcurves(action):
        for kp in fc.keyframe_points:
            f = float(kp.co[0])
            fmin = f if fmin is None else min(fmin, f)
            fmax = f if fmax is None else max(fmax, f)
    return fmin, fmax


def actions_clip_length(actions):
    """Shared Unity clip length in frames (max key span among sibling Actions)."""
    gmin = gmax = None
    for action in actions or []:
        fmin, fmax = _action_key_range(action)
        if fmin is None or fmax is None:
            continue
        gmin = fmin if gmin is None else min(gmin, fmin)
        gmax = fmax if gmax is None else max(gmax, fmax)
    if gmin is None:
        return 0.0
    return float(gmax - gmin)


def _sync_strip_to_action_range(strip, action):
    """Make NLA strip play the full Action range (needed after Ping-Pong bake)."""
    if strip is None or action is None:
        return
    fmin, fmax = _action_key_range(action)
    if fmin is None or fmax is None or fmax <= fmin:
        return
    try:
        strip.action_frame_start = fmin
        strip.action_frame_end = fmax
    except Exception:
        pass
    try:
        start = float(strip.frame_start)
        strip.frame_end = start + (fmax - fmin)
    except Exception:
        pass


def _sync_strip_to_clip_length(strip, action, clip_len):
    """Pad NLA strip to Unity clip length so Loop repeats the whole clip."""
    if strip is None or action is None:
        return
    try:
        clip_len = float(clip_len or 0)
    except Exception:
        clip_len = 0.0
    if clip_len <= 0:
        _sync_strip_to_action_range(strip, action)
        return
    fmin, fmax = _action_key_range(action)
    if fmin is None:
        fmin = 0.0
    try:
        strip.action_frame_start = fmin
        strip.action_frame_end = fmin + clip_len
    except Exception:
        pass
    try:
        start = float(strip.frame_start)
        strip.frame_end = start + clip_len
    except Exception:
        pass


def _bake_pingpong_keys(action, fcurve, clip_len=0.0):
    """Bake one Unity PingPong period: forward clip.length, then reverse.

    Unity WrapMode.PingPong ping-pongs **clip time** (never stops). Short
    curves Clamp-hold until clip.length, then the whole clip runs backward.
    NLA strip.repeat only plays forward, so the reverse half is keys.
    """
    kps = list(fcurve.keyframe_points)
    if len(kps) < 1:
        return
    _backup_fcurve_keys(action, fcurve)
    pts = [(float(kp.co[0]), float(kp.co[1])) for kp in kps]
    t0, t1 = pts[0][0], pts[-1][0]
    try:
        clip_len = float(clip_len or 0)
    except Exception:
        clip_len = 0.0
    period_end = t1
    if clip_len > 1e-6:
        period_end = t0 + clip_len
    if (period_end - t0) <= 1e-6:
        return
    out = list(pts)
    if period_end > t1 + 1e-6:
        out.append((period_end, pts[-1][1]))
    peak_t = out[-1][0]
    for t, v in reversed(out[:-1]):
        out.append((peak_t + (peak_t - t), v))
    fcurve.keyframe_points.clear()
    fcurve.keyframe_points.add(len(out))
    for i, (t, v) in enumerate(out):
        kp = fcurve.keyframe_points[i]
        kp.co = (t, v)
        kp.handle_left_type = 'AUTO_CLAMPED'
        kp.handle_right_type = 'AUTO_CLAMPED'
    try:
        fcurve.update()
    except Exception:
        pass


def _clear_pp_backups(action):
    """Remove all Ping-Pong backup IDProperties from action."""
    if action is None:
        return
    try:
        if _MU_PP_BAK_BAG in action:
            del action[_MU_PP_BAK_BAG]
    except Exception:
        pass
    try:
        for k in list(action.keys()):
            if isinstance(k, str) and k.startswith("mu_pp_backup|"):
                del action[k]
    except Exception:
        pass


def _apply_strip_repeat(strip, wrap_mode):
    """Set NLA strip repeat / cyclic flags for the given Unity wrap mode."""
    if strip is None:
        return
    if wrap_mode in (MU_WRAP_LOOP, MU_WRAP_PINGPONG):
        strip.repeat = 1000.0
    else:
        strip.repeat = 1.0
    strip.use_animated_time = False
    try:
        strip.use_animated_time_cyclic = False
    except Exception:
        pass


def _apply_loop_curve_modifiers(action):
    """Clip Loop uses NLA strip repeat. Only Curve Wrap=Loop gets CYCLES.

    Unity: Clip Loop wraps time at clip.length; Curve Clamp holds the last
    key until then. CYCLES on Clamp curves made short actions loop on their
    own period and desync from longer siblings.
    """
    if action is None:
        return
    for fc in iter_action_fcurves(action):
        pre, post = get_mu_curve_wrap(action, fc)
        if pre == MU_WRAP_LOOP or post == MU_WRAP_LOOP:
            fc.extrapolation = 'CONSTANT'
            mod = fc.modifiers.new(type='CYCLES')
            mod.mode_before = 'REPEAT'
            mod.mode_after = 'REPEAT'
            try:
                mod["mu_clip_loop"] = 1
            except Exception:
                pass
        else:
            fc.extrapolation = 'CONSTANT'


def apply_mu_clip_wrap_to_strip(strip, wrap_mode):
    """Apply MuClip.wrapMode to an NLA strip and store it on the Action.

    Loop: pad NLA strips to clip.length, then long repeat (infinite).
    Ping-Pong: same clip.length clock — hold short curves, bake
               forward+back (2× clip.length), then long repeat (infinite;
               Unity: never automatically stops).
    Once / Clamp / Default: single play, natural Action length.

    Switching AWAY from Ping-Pong fully restores original keys, clears the
    bake flag + backups, and resyncs the NLA strip to the short range so the
    cloned reverse half does not remain visible in the Graph/NLA editors.

    Strip repeat and Loop CYCLES modifiers are always applied LAST so that
    Ping-Pong → Loop does not leave the strip looking like Once.
    """
    try:
        wrap_mode = int(wrap_mode)
    except Exception:
        wrap_mode = MU_WRAP_ONCE
    if wrap_mode == MU_WRAP_DEFAULT:
        wrap_mode = MU_WRAP_ONCE

    action = getattr(strip, "action", None)
    if action is not None:
        try:
            if wrap_mode == MU_WRAP_DEFAULT:
                wrap_mode = MU_WRAP_ONCE
            if wrap_mode not in (MU_WRAP_ONCE, MU_WRAP_LOOP, MU_WRAP_PINGPONG, MU_WRAP_CLAMP):
                wrap_mode = MU_WRAP_ONCE
            action["mu_clip_wrap_mode"] = int(wrap_mode)
        except Exception:
            pass

    if action is None:
        _apply_strip_repeat(strip, wrap_mode)
        return

    was_baked = bool(action.get("mu_pp_baked"))
    clip_len = 0.0
    try:
        clip_len = float(action.get("mu_clip_length") or 0)
    except Exception:
        clip_len = 0.0
    for fc in iter_action_fcurves(action):
        _strip_clip_helpers(fc)
        if was_baked and wrap_mode != MU_WRAP_PINGPONG:
            _restore_fcurve_from_backup(action, fc)

    if wrap_mode == MU_WRAP_PINGPONG:
        for fc in iter_action_fcurves(action):
            if not was_baked:
                _bake_pingpong_keys(action, fc, clip_len=clip_len)
        try:
            action["mu_pp_baked"] = 1
        except Exception:
            pass
        if clip_len > 0:
            _sync_strip_to_clip_length(strip, action, 2.0 * clip_len)
        else:
            _sync_strip_to_action_range(strip, action)
    elif was_baked and wrap_mode != MU_WRAP_PINGPONG:
        try:
            if "mu_pp_baked" in action:
                del action["mu_pp_baked"]
        except Exception:
            pass
        _clear_pp_backups(action)
        _sync_strip_to_action_range(strip, action)

    # Length first, then repeat. Changing strip.frame_end resets NLA
    # strip.repeat back to 1 in Blender — Loop/PingPong would play one cycle.
    if wrap_mode == MU_WRAP_LOOP:
        if clip_len > 0:
            _sync_strip_to_clip_length(strip, action, clip_len)
        _apply_loop_curve_modifiers(action)
    elif wrap_mode != MU_WRAP_PINGPONG:
        # Loop only pads NLA strips for preview. Once/Clamp must shrink
        # back to this Action's own keys (Unity does not rewrite curve length).
        _sync_strip_to_action_range(strip, action)
    _apply_strip_repeat(strip, wrap_mode)


def apply_mu_clip_wrap_to_action(action, wrap_mode):
    """Store MuClip.wrapMode on Action and update every NLA strip using it."""
    try:
        wrap_mode = int(wrap_mode)
    except Exception:
        wrap_mode = MU_WRAP_ONCE
    if wrap_mode == MU_WRAP_DEFAULT:
        wrap_mode = MU_WRAP_ONCE

    if wrap_mode == MU_WRAP_DEFAULT:
        wrap_mode = MU_WRAP_ONCE
    if wrap_mode not in (MU_WRAP_ONCE, MU_WRAP_LOOP, MU_WRAP_PINGPONG, MU_WRAP_CLAMP):
        wrap_mode = MU_WRAP_ONCE
    try:
        action["mu_clip_wrap_mode"] = int(wrap_mode)
    except Exception:
        pass

    for id_data in list(bpy.data.objects) + list(bpy.data.materials):
        ad = getattr(id_data, "animation_data", None)
        if not ad:
            continue
        for track in ad.nla_tracks:
            for strip in track.strips:
                if strip.action == action:
                    apply_mu_clip_wrap_to_strip(strip, wrap_mode)
