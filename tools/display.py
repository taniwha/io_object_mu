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

"""Viewport display helpers: collider / shroud-fairing visibility, bump, FX."""

import json
import os

import bpy

# ---------------------------------------------------------------------------
# Undo/redo guard — RNA update on Scene.mu_*_variant fires during undo and
# must not re-run apply_variant on half-restored / deleted Object IDs (crash).
# ---------------------------------------------------------------------------
_UNDO_REDO_DEPTH = 0


def _in_undo_redo():
    return _UNDO_REDO_DEPTH > 0


def _undo_pre(_scene=None):
    global _UNDO_REDO_DEPTH
    _UNDO_REDO_DEPTH += 1


def _undo_post(_scene=None):
    global _UNDO_REDO_DEPTH
    _UNDO_REDO_DEPTH = max(0, _UNDO_REDO_DEPTH - 1)


def _object_alive(obj):
    """False if Object was removed (undo) or is None."""
    if obj is None:
        return False
    try:
        # Touch a basic RNA property — raises ReferenceError on freed IDs
        _ = obj.name
        return True
    except ReferenceError:
        return False
    except Exception:
        return False




def _apply_variant_name(context, name):
    """Apply a variant name on the selected import root."""
    if not name or name == "NONE":
        return
    if _in_undo_redo():
        return
    try:
        from ..import_mu import cfg_preview as _cp
        if getattr(_cp, "_VARIANT_APPLY_DEPTH", 0) > 0:
            return
        apply_variant = _cp.apply_variant
        find_variant_root = _cp.find_variant_root
    except Exception:
        return
    try:
        active = getattr(context, "active_object", None)
        if not _object_alive(active):
            active = None
        root = find_variant_root(active, context=context)
    except ReferenceError:
        return
    except Exception:
        return
    if root is None or not _object_alive(root):
        return
    try:
        apply_variant(root, name)
    except ReferenceError:
        return
    except Exception:
        return
    try:
        br = getattr(context.window_manager, "ksp_mu_browser", None)
        show = bool(getattr(br, "show_attach_points", False)) if br else False
        if show:
            from ..mu_browser.operators import update_attach_point_markers
            update_attach_point_markers(context, True)
    except ReferenceError:
        pass
    except Exception:
        pass


def _update_part_variant(self, context):
    """Legacy single enum (MPV / combined)."""
    if _in_undo_redo():
        return
    _apply_variant_name(context, getattr(self, "mu_active_variant", "") or "")


def _update_mesh_variant(self, context):
    """B9 / MPV mesh switch — independent of paint (slot 1 / Dome)."""
    if _in_undo_redo():
        return
    _apply_variant_name(context, getattr(self, "mu_mesh_variant", "") or "")
    _sync_mesh_paint_enums_from_id(context)


def _update_mesh_variant_2(self, context):
    if _in_undo_redo():
        return
    _apply_variant_name(context, getattr(self, "mu_mesh_variant_2", "") or "")
    _sync_mesh_paint_enums_from_id(context)


def _update_mesh_variant_3(self, context):
    if _in_undo_redo():
        return
    _apply_variant_name(context, getattr(self, "mu_mesh_variant_3", "") or "")
    _sync_mesh_paint_enums_from_id(context)


def _update_mesh_variant_4(self, context):
    if _in_undo_redo():
        return
    _apply_variant_name(context, getattr(self, "mu_mesh_variant_4", "") or "")
    _sync_mesh_paint_enums_from_id(context)


def _update_paint_variant(self, context):
    """B9 texture/paint switch — independent of mesh."""
    if _in_undo_redo():
        return
    _apply_variant_name(context, getattr(self, "mu_paint_variant", "") or "")


def _sync_mesh_paint_enums_from_id(context):
    """Align Mesh/Paint dropdowns with last apply without re-running apply.

    Source of truth: ID props written by apply_variant, then paint_by_model
    on the selected import root. RNA assignment runs under the depth guard.
    """
    if _in_undo_redo():
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        from ..import_mu import cfg_preview as _cp
    except Exception:
        return
    if getattr(_cp, "_VARIANT_APPLY_DEPTH", 0) > 0:
        return

    want_mesh = None
    want_paint = None
    try:
        want_mesh = scene.get("mu_mesh_variant_sync")
    except Exception:
        want_mesh = None
    try:
        want_paint = scene.get("mu_paint_variant_sync")
    except Exception:
        want_paint = None

    # Fallback from JSON only when sync ID props are empty.  Never overwrite
    # mu_mesh_variant_sync with the *first* active_modules mesh entry — parts
    # with multiple independent mesh modules (Delta IV upper/lower endcaps)
    # would always snap the dropdown back to meshSwitchEndsUpper/*.
    try:
        root = _cp.find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is not None and _cp.MU_VARIANTS_KEY in root:
            import json
            data = json.loads(root[_cp.MU_VARIANTS_KEY])
            leaf = data.get("active_mesh_leaf") or "__primary__"
            pbm = data.get("paint_by_model") or {}
            if not want_paint:
                want_paint = pbm.get(leaf) or _cp._default_paint_variant_name(
                    data
                )
            if not want_mesh:
                # Prefer last-applied mesh subtype stored as active
                active_mesh = data.get("active") or ""
                if active_mesh:
                    for v in data.get("variants") or []:
                        if v.get("name") == active_mesh and _cp._variant_is_mesh_switch(
                            v, data.get("variants") or []
                        ):
                            want_mesh = active_mesh
                            break
                if not want_mesh:
                    # Last resort: any active_modules mesh entry (stable order
                    # by moduleID so UI is deterministic, not "first in list")
                    am = data.get("active_modules") or {}
                    mesh_hits = []
                    for v in data.get("variants") or []:
                        if not _cp._variant_is_mesh_switch(
                            v, data.get("variants") or []
                        ):
                            continue
                        mid = v.get("b9_moduleID") or ""
                        bare = am.get(mid)
                        if bare and (
                            v.get("name", "").endswith("/" + bare)
                            or v.get("name") == bare
                        ):
                            mesh_hits.append(v.get("name"))
                    if mesh_hits:
                        want_mesh = mesh_hits[-1]
    except Exception:
        pass

    slot_wants = [("mu_mesh_variant", want_mesh), ("mu_paint_variant", want_paint)]
    try:
        root = _cp.find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is not None and _cp.MU_VARIANTS_KEY in root:
            import json
            data = json.loads(root[_cp.MU_VARIANTS_KEY])
            groups = _cp.get_mesh_switch_groups(root=root, data=data)
            am = data.get("active_modules") or {}
            rna_slots = (
                "mu_mesh_variant",
                "mu_mesh_variant_2",
                "mu_mesh_variant_3",
                "mu_mesh_variant_4",
            )
            for i, g in enumerate(groups[:4]):
                mid = g.get("module_id") or ""
                if mid and mid != "_mesh":
                    bare = am.get(mid)
                    if bare:
                        full = "%s/%s" % (mid, bare)
                        ids = {it[0] for it in (g.get("items") or [])}
                        if full in ids:
                            slot_wants.append((rna_slots[i], full))
                        elif bare in ids:
                            slot_wants.append((rna_slots[i], bare))
    except Exception:
        pass

    for rna_name, want in slot_wants:
        if not want or not hasattr(scene, rna_name):
            continue
        try:
            cur = getattr(scene, rna_name, None)
        except Exception:
            continue
        if cur == want:
            continue
        _cp._VARIANT_APPLY_DEPTH += 1
        try:
            setattr(scene, rna_name, want)
        except Exception:
            # Invalid enum id — try bare subtype name
            try:
                bare = want.split("/")[-1]
                for item in (getattr(scene, rna_name + "_items", None) or []):
                    pass
                setattr(scene, rna_name, bare)
            except Exception:
                pass
        finally:
            _cp._VARIANT_APPLY_DEPTH = max(0, getattr(_cp, "_VARIANT_APPLY_DEPTH", 1) - 1)

    # Ensure redraw so the dropdown shows the new value immediately
    try:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    except Exception:
        pass


def _update_active_flag(self, context):
    """Scene enum → swap FlagDecal quad _MainTex (viewport only)."""
    name = getattr(self, "mu_active_flag", "") or ""
    try:
        from ..import_mu.flag_preview import (
            NO_FLAG,
            apply_flag_texture,
            find_flag_root,
        )
    except Exception:
        return
    root = find_flag_root(
        getattr(context, "active_object", None), context=context
    )
    if root is None:
        return
    apply_flag_texture(root, name or NO_FLAG)


def _sync_variant_enum_to_selection(context):
    """Refresh Options dropdown to the selected model's active variant."""
    try:
        from ..import_mu.cfg_preview import find_variant_root, MU_VARIANTS_KEY
        import json
    except Exception:
        return
    root = find_variant_root(
        getattr(context, "active_object", None), context=context
    )
    if root is None or MU_VARIANTS_KEY not in root:
        return
    try:
        data = json.loads(root[MU_VARIANTS_KEY])
    except Exception:
        return
    active = data.get("active") or data.get("base") or ""
    if not active:
        return
    scene = context.scene
    if not hasattr(scene, "mu_active_variant"):
        return
    # Avoid recursive update when already matching
    if getattr(scene, "mu_active_variant", None) == active:
        return
    try:
        scene["mu_active_variant"] = active
    except Exception:
        try:
            scene.mu_active_variant = active
        except Exception:
            pass


def _sync_flag_enum_to_selection(context):
    try:
        from ..import_mu.flag_preview import NO_FLAG, find_flag_root, MU_FLAG_KEY
        import json
    except Exception:
        return
    root = find_flag_root(
        getattr(context, "active_object", None), context=context
    )
    scene = context.scene
    if not hasattr(scene, "mu_active_flag"):
        return
    if root is None:
        return
    active = root.get("mu_active_flag") or NO_FLAG
    try:
        raw = root.get(MU_FLAG_KEY)
        if raw:
            data = json.loads(raw)
            active = data.get("active") or active
    except Exception:
        pass
    if getattr(scene, "mu_active_flag", None) == active:
        return
    try:
        scene["mu_active_flag"] = active
    except Exception:
        try:
            scene.mu_active_flag = active
        except Exception:
            pass


def _variant_enum_items(self, context):
    try:
        from ..import_mu.cfg_preview import get_variant_items
        return get_variant_items(self, context)
    except Exception:
        return [("NONE", "(no variants)", "")]


def _mesh_variant_enum_items(self, context):
    try:
        from ..import_mu.cfg_preview import get_mesh_variant_items
        return get_mesh_variant_items(self, context)
    except Exception:
        return [("NONE", "(no mesh variants)", "")]


def _mesh_variant_2_enum_items(self, context):
    try:
        from ..import_mu.cfg_preview import get_mesh_variant_2_items
        return get_mesh_variant_2_items(self, context)
    except Exception:
        return [("NONE", "(none)", "")]


def _mesh_variant_3_enum_items(self, context):
    try:
        from ..import_mu.cfg_preview import get_mesh_variant_3_items
        return get_mesh_variant_3_items(self, context)
    except Exception:
        return [("NONE", "(none)", "")]


def _mesh_variant_4_enum_items(self, context):
    try:
        from ..import_mu.cfg_preview import get_mesh_variant_4_items
        return get_mesh_variant_4_items(self, context)
    except Exception:
        return [("NONE", "(none)", "")]


def _paint_variant_enum_items(self, context):
    try:
        from ..import_mu.cfg_preview import get_paint_variant_items
        return get_paint_variant_items(self, context)
    except Exception:
        return [("NONE", "(no paint variants)", "")]


def _flag_enum_items(self, context):
    try:
        from ..import_mu.flag_preview import get_flag_enum_items
        return get_flag_enum_items(self, context)
    except Exception:
        return [("NONE", "No Flag", "")]


def _preview_clip_hierarchy_roots(context):
    """Top-level import roots for the current selection (or active object)."""
    if context is None:
        return []
    sel = list(getattr(context, "selected_objects", None) or [])
    active = getattr(context, "active_object", None)
    if not sel and active is not None:
        sel = [active]
    if not sel:
        # Active collection: any object therein → its hierarchy root(s)
        col = getattr(context, "collection", None)
        if col is not None:
            sel = list(getattr(col, "all_objects", []) or [])[:32]
    roots = []
    seen = set()
    for obj in sel:
        if obj is None:
            continue
        root = obj
        while root.parent is not None:
            root = root.parent
        key = root.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _preview_clip_scope_ids(context):
    """Objects + materials for the whole selected part hierarchy.

    Walks up to each selection's import root so sibling branches (Armature
    clips + Dust/Rocks particles + light GOs) are all visible to Preview Clip.
    """
    if context is None:
        return []
    roots = _preview_clip_hierarchy_roots(context)
    objs = []
    seen_obj = set()
    for root in roots:
        stack = [root]
        while stack:
            obj = stack.pop()
            if obj is None:
                continue
            key = obj.as_pointer()
            if key in seen_obj:
                continue
            seen_obj.add(key)
            objs.append(obj)
            stack.extend(list(obj.children))
    mats = []
    seen_mat = set()
    for obj in objs:
        for slot in getattr(obj, "material_slots", []) or []:
            mat = slot.material
            if mat is None:
                continue
            key = mat.as_pointer()
            if key in seen_mat:
                continue
            seen_mat.add(key)
            mats.append(mat)
        # Particle host materials may be unassigned stock mats (DrillDust)
        if obj.get("mu_particles"):
            try:
                from ..import_mu.particles_preview import _particle_material
                mat = _particle_material(obj, None)
            except Exception:
                mat = None
            if mat is not None:
                key = mat.as_pointer()
                if key not in seen_mat:
                    seen_mat.add(key)
                    mats.append(mat)
    return objs + mats


def _strip_preview_name(name):
    try:
        from ..utils import strip_nnn
        return strip_nnn(name) or ""
    except Exception:
        raw = name or ""
        ind = raw.rfind("\u2227")
        if ind >= 0:
            raw = raw[:ind]
        return raw


def _particle_fx_hosts_in_scope(objs):
    """MuParticles hosts (Dust/Rocks) → (label, object)."""
    out = []
    seen = set()
    for obj in objs:
        if not getattr(obj, "get", lambda *_: None)("mu_particles"):
            continue
        if obj.get("mu_fx_preview"):
            continue
        label = _strip_preview_name(obj.name)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append((label, obj))
    return out


def _is_fx_nla_source(id_data, track):
    """True for particle / FX preview tracks that stay unmuted during clip scrub."""
    try:
        if getattr(id_data, "get", lambda *_: None)("mu_fx_preview"):
            return True
    except Exception:
        pass
    oname = getattr(id_data, "name", "") or ""
    if ".fx_anim" in oname or ".fx_preview" in oname:
        return True
    tn = (track.name or "") if track else ""
    if tn.lower() in ("muparticles", "mu_particles") or tn.startswith("MuParticles"):
        return True
    try:
        if track is not None and track.get("mu_fx_preview"):
            return True
    except Exception:
        pass
    # Material colorAnimation baked for particle preview
    try:
        if track is not None:
            for strip in track.strips:
                act = strip.action
                if act is not None and act.get("mu_fx_preview"):
                    return True
    except Exception:
        pass
    return False


def animations_are_off(scene=None):
    """Scene toggle from Options: mute Mu clips and do not auto-play."""
    try:
        if scene is None:
            scene = bpy.context.scene
        return bool(getattr(scene, "mu_animations_off", False))
    except Exception:
        return False


def _stop_timeline_playback():
    try:
        wm = bpy.context.window_manager
    except Exception:
        return
    for window in getattr(wm, "windows", []) or []:
        screen = getattr(window, "screen", None)
        if screen is None or not getattr(screen, "is_animation_playing", False):
            continue
        try:
            with bpy.context.temp_override(window=window, screen=screen):
                bpy.ops.screen.animation_play()
        except Exception:
            pass


# Saved NLA mute flags. Blender 5 NlaTrack does not support ID properties.
_SAVED_NLA_MUTE = {}


def _nla_mute_key(id_data, index):
    try:
        ptr = id_data.as_pointer()
    except Exception:
        ptr = getattr(id_data, "name", "")
    return (ptr, int(index))


def apply_animations_off(scene, off):
    """Mute or restore non-FX NLA. FX preview tracks stay as they were."""
    off = bool(off)
    if off:
        _stop_timeline_playback()
        try:
            scene.frame_set(int(scene.frame_start))
        except Exception:
            pass
    ids = list(getattr(bpy.data, "objects", []) or [])
    ids.extend(list(getattr(bpy.data, "materials", []) or []))
    for id_data in ids:
        ad = getattr(id_data, "animation_data", None)
        if ad is None:
            continue
        tracks = list(getattr(ad, "nla_tracks", []) or [])
        for index, track in enumerate(tracks):
            if _is_fx_nla_source(id_data, track):
                continue
            key = _nla_mute_key(id_data, index)
            if off:
                if key not in _SAVED_NLA_MUTE:
                    try:
                        _SAVED_NLA_MUTE[key] = bool(track.mute)
                    except Exception:
                        _SAVED_NLA_MUTE[key] = False
                track.mute = True
            elif key in _SAVED_NLA_MUTE:
                track.mute = bool(_SAVED_NLA_MUTE.pop(key))
        if off:
            try:
                ad.action = None
            except Exception:
                pass
        else:
            try:
                ad.action = None
            except Exception:
                pass
            try:
                if hasattr(ad, "use_nla"):
                    ad.use_nla = True
            except Exception:
                pass
            _unmute_fallback_clip(id_data)
    if not off and _any_autoplay_audible():
        _start_timeline_playback()


def _unmute_fallback_clip(id_data):
    """If every Mu clip stayed muted, unmute the Auto Play clip or the first one."""
    ad = getattr(id_data, "animation_data", None)
    if ad is None:
        return
    tracks = [
        track for track in list(getattr(ad, "nla_tracks", []) or [])
        if not _is_fx_nla_source(id_data, track)
    ]
    if not tracks or any(not track.mute for track in tracks):
        return
    keep = None
    for track in tracks:
        for strip in getattr(track, "strips", []) or []:
            act = getattr(strip, "action", None)
            try:
                if act is not None and (
                    int(act.get("mu_auto_play") or 0)
                    or _host_autoplay_flag(act)
                ):
                    keep = track.name
                    break
            except Exception:
                pass
        if keep:
            break
    if not keep:
        keep = tracks[0].name
    for track in tracks:
        track.mute = track.name != keep


def _host_autoplay_flag(act):
    try:
        bname = act.get("mu_anim_bobj")
        if not bname:
            return False
        bobj = bpy.data.objects.get(str(bname))
        return bool(bobj is not None and int(bobj.get("mu_animation_autoplay") or 0))
    except Exception:
        return False


def _any_autoplay_audible():
    ids = list(getattr(bpy.data, "objects", []) or [])
    ids.extend(list(getattr(bpy.data, "materials", []) or []))
    for id_data in ids:
        ad = getattr(id_data, "animation_data", None)
        if ad is None:
            continue
        for track in getattr(ad, "nla_tracks", []) or []:
            if track.mute or _is_fx_nla_source(id_data, track):
                continue
            for strip in getattr(track, "strips", []) or []:
                act = getattr(strip, "action", None)
                try:
                    if act is not None and (
                        int(act.get("mu_auto_play") or 0)
                        or _host_autoplay_flag(act)
                    ):
                        return True
                except Exception:
                    pass
    return False


def _start_timeline_playback():
    try:
        scene = bpy.context.scene
        scene.frame_set(int(scene.frame_start))
    except Exception:
        pass

    def _play():
        try:
            for window in bpy.context.window_manager.windows:
                screen = window.screen
                if screen is None:
                    continue
                with bpy.context.temp_override(window=window, screen=screen):
                    if not screen.is_animation_playing:
                        bpy.ops.screen.animation_play()
                    return None
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_play, first_interval=0.05)
    except Exception:
        _play()


def _update_animations_off(self, context):
    scene = getattr(context, "scene", None) or self
    apply_animations_off(scene, bool(getattr(scene, "mu_animations_off", False)))


def _collect_preview_clip_names(context):
    """NLA track names + MuParticles host labels for Preview Clip enum."""
    names = []
    seen = set()
    scope = _preview_clip_scope_ids(context)
    objs = [x for x in scope if isinstance(x, bpy.types.Object)]
    for id_data in scope:
        ad = getattr(id_data, "animation_data", None)
        if not ad or not ad.nla_tracks:
            # Blender 5 may leave FX color anim as ad.action only
            act = getattr(ad, "action", None) if ad else None
            if act is not None and act.get("mu_fx_preview"):
                continue
            continue
        try:
            if getattr(id_data, "get", lambda *_: None)("mu_fx_preview"):
                continue
        except Exception:
            pass
        oname = getattr(id_data, "name", "") or ""
        if ".fx_anim" in oname or ".fx_preview" in oname:
            continue
        for track in ad.nla_tracks:
            tn = track.name or ""
            if not tn:
                continue
            if tn.lower() in ("muparticles", "mu_particles") or tn.startswith("MuParticles"):
                continue
            try:
                if track.get("mu_fx_preview") and not track.get("mu_robotic_preview"):
                    continue
            except Exception:
                pass
            if tn.startswith("ColorChangerLights"):
                label = "ColorChangerLights"
                if label not in seen:
                    seen.add(label)
                    names.append(label)
                continue
            if tn not in seen:
                seen.add(tn)
                names.append(tn)
    # Synthetic entries for hidden particle FX hosts (Dust, Rocks, …)
    for label, _host in _particle_fx_hosts_in_scope(objs):
        if label not in seen:
            seen.add(label)
            names.append(label)
    try:
        from ..import_mu.animation import ordered_clip_names
        # Keep FX host labels after real Mu clips but still ordered
        fx_labels = {lab for lab, _ in _particle_fx_hosts_in_scope(objs)}
        real = [n for n in names if n not in fx_labels]
        fx = [n for n in names if n in fx_labels]
        return ordered_clip_names(real) + fx
    except Exception:
        return names


def _refresh_preview_clip_frame(context, force_rest):
    """Force depsgraph update after NLA mute changes.

    Muting alone leaves the last evaluated mid-strip pose frozen in the
    viewport; scrubbing to frame_start (or re-setting the current frame)
    clears that hold so objects return to rest / default keys.
    """
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        if force_rest:
            target = int(scene.frame_start)
        else:
            target = int(scene.frame_current)
        scene.frame_set(target)
    except Exception:
        try:
            scene.frame_set(1)
        except Exception:
            pass


def _track_action_clip_names(track):
    """Clip names carried by strips on this NLA track (mu_clip_name / strip action)."""
    names = set()
    try:
        for strip in getattr(track, "strips", []) or []:
            act = getattr(strip, "action", None)
            if act is None:
                continue
            try:
                cn = act.get("mu_clip_name")
                if cn:
                    names.add(str(cn))
            except Exception:
                pass
            try:
                an = getattr(act, "name", "") or ""
                if an:
                    names.add(an)
            except Exception:
                pass
    except Exception:
        pass
    return names


def _collect_related_preview_clip_names(scope, mode):
    """Tracks that should play together with *mode*.

    Suspension / deploy animations are often split across several Mu clips and
    NLA tracks (wheel mesh on one track, axle + damper on others). Exact name
    match alone leaves sibling transforms frozen. Collect:

    1. Exact track name == mode
    2. Actions tagged mu_clip_name == mode
    3. Any other non-FX track that co-exists on the same Object (or its
       direct children/parents in scope) that also hosts *mode* — so selecting
       the wheel fold clip also drives the axle/strut tracks on the same branch.
    """
    related = {mode}
    if not mode or mode in ("NONE", "ALL"):
        return related

    # Keyword groups: suspension travel + deploy often need simultaneous play
    mode_l = mode.lower()
    keyword_groups = [
        ("suspension", "suspensiontravel", "travel", "amort"),
        ("deploy", "retract", "stow", "extend", "fold"),
    ]
    active_groups = []
    for group in keyword_groups:
        if any(k in mode_l for k in group):
            active_groups.append(group)

    # Pass 1: expand via mu_clip_name / action name
    objs_with_mode = []
    for id_data in scope:
        ad = getattr(id_data, "animation_data", None)
        if not ad or not ad.nla_tracks:
            continue
        has_mode = False
        for track in ad.nla_tracks:
            tn = track.name or ""
            if _is_fx_nla_source(id_data, track):
                continue
            clip_names = _track_action_clip_names(track)
            if tn == mode or mode in clip_names:
                related.add(tn)
                related.update(clip_names)
                has_mode = True
        if has_mode and isinstance(id_data, bpy.types.Object):
            objs_with_mode.append(id_data)

    if not objs_with_mode:
        return related

    # Pass 2: sibling tracks on the same animated objects / close hierarchy
    obj_set = set()
    for o in objs_with_mode:
        obj_set.add(o.as_pointer())
        try:
            if o.parent is not None:
                obj_set.add(o.parent.as_pointer())
            for ch in list(getattr(o, "children", []) or []):
                obj_set.add(ch.as_pointer())
        except Exception:
            pass

    for id_data in scope:
        if not isinstance(id_data, bpy.types.Object):
            continue
        try:
            if id_data.as_pointer() not in obj_set:
                # Also include objects that share a common parent with mode hosts
                p = id_data.parent
                share = False
                while p is not None:
                    if p.as_pointer() in obj_set:
                        share = True
                        break
                    p = p.parent
                if not share:
                    continue
        except Exception:
            continue
        ad = getattr(id_data, "animation_data", None)
        if not ad or not ad.nla_tracks:
            continue
        for track in ad.nla_tracks:
            if _is_fx_nla_source(id_data, track):
                continue
            tn = track.name or ""
            if not tn:
                continue
            related.add(tn)
            related.update(_track_action_clip_names(track))

    # Pass 3: keyword group expansion across entire scope
    if active_groups:
        for id_data in scope:
            ad = getattr(id_data, "animation_data", None)
            if not ad or not ad.nla_tracks:
                continue
            for track in ad.nla_tracks:
                if _is_fx_nla_source(id_data, track):
                    # still include SuspensionTravel synthetic tracks by name
                    tn = track.name or ""
                    tnl = tn.lower()
                    if any(any(k in tnl for k in g) for g in active_groups):
                        related.add(tn)
                    continue
                tn = track.name or ""
                tnl = tn.lower()
                if any(any(k in tnl for k in g) for g in active_groups):
                    related.add(tn)
                    related.update(_track_action_clip_names(track))
    return related


def _set_preview_clip_active(context, clip_name):
    """Apply Preview Clip selection to NLA tracks in scope.

    NONE — mute all non-FX clips and reset to rest at frame_start (not frozen).
    ALL  — unmute all non-FX clips (import-style default visibility) at frame_start.
    Dust/Rocks (MuParticles host) — force-show that FX group; mute Mu clips.
    else — unmute the chosen clip *and* related tracks that share the same
    animated branch (suspension fold: wheel + axle + damper), via mu_clip_name
    and co-hosted NLA on the hierarchy; FX preview stays frame-gated.
    """
    mode = clip_name or "NONE"
    mute_all = mode == "NONE"
    unmute_all = mode == "ALL"
    scope = _preview_clip_scope_ids(context)
    objs = [x for x in scope if isinstance(x, bpy.types.Object)]
    fx_hosts = dict(_particle_fx_hosts_in_scope(objs))
    fx_mode = mode in fx_hosts
    related = set()
    if not mute_all and not unmute_all and not fx_mode and mode != "ColorChangerLights":
        related = _collect_related_preview_clip_names(scope, mode)

    for id_data in scope:
        ad = getattr(id_data, "animation_data", None)
        if not ad or not ad.nla_tracks:
            continue
        for track in ad.nla_tracks:
            tn = track.name or ""
            is_fx = _is_fx_nla_source(id_data, track)
            if is_fx:
                if tn.startswith("ColorChangerLights"):
                    if mute_all or fx_mode:
                        track.mute = True
                    elif unmute_all:
                        track.mute = False
                    else:
                        track.mute = not (
                            mode == "ColorChangerLights"
                            or mode.startswith("ColorChangerLights")
                        )
                else:
                    # SuspensionTravel: gated by Options checkbox (off by default)
                    is_susp = tn.startswith("Suspension") or (
                        track.get("mu_suspension_preview")
                        if hasattr(track, "get")
                        else False
                    )
                    if is_susp:
                        try:
                            susp_on = bool(
                                getattr(
                                    context.scene, "mu_suspension_preview", False
                                )
                            )
                        except Exception:
                            susp_on = False
                        # Also on when user picks SuspensionTravel in Preview Clip
                        if mode.startswith("Suspension"):
                            susp_on = True
                        track.mute = not susp_on
                    # MuParticles swarm tracks: unmute only for selected host
                    elif mute_all:
                        track.mute = True
                    elif fx_mode:
                        host = fx_hosts.get(mode)
                        oname = getattr(id_data, "name", "") or ""
                        belong = bool(
                            host is not None and (
                                oname.startswith(host.name or "")
                                or (host.name or "") in oname
                            )
                        )
                        track.mute = not belong
                    else:
                        track.mute = False
            else:
                if mute_all or fx_mode:
                    track.mute = True
                elif unmute_all:
                    track.mute = False
                elif mode == "ColorChangerLights":
                    track.mute = not tn.startswith("ColorChangerLights")
                else:
                    clip_names = _track_action_clip_names(track)
                    match = (
                        tn == mode
                        or tn in related
                        or mode in clip_names
                        or bool(clip_names & related)
                    )
                    track.mute = not match
        try:
            ad.action = None
        except Exception:
            pass

    # Particle FX host visibility (Dust / Rocks are hide_viewport until deploy)
    scene = getattr(context, "scene", None)
    try:
        if scene is not None:
            scene["mu_preview_fx_force"] = mode if fx_mode else ""
    except Exception:
        pass

    _refresh_preview_clip_frame(
        context, force_rest=(mute_all or unmute_all or fx_mode)
    )

    try:
        from ..import_mu.particles_preview import (
            set_particles_preview_for_host,
            sync_particles_preview_for_frame,
        )
        if mute_all:
            for _lab, host in fx_hosts.items():
                set_particles_preview_for_host(host, False, force=True)
        elif fx_mode:
            for lab, host in fx_hosts.items():
                set_particles_preview_for_host(
                    host, visible=(lab == mode), force=True
                )
        else:
            # Regular Mu clip / ALL — restore deploy-gated FX visibility
            sync_particles_preview_for_frame(
                getattr(context.scene, "frame_current", 1)
            )
    except Exception:
        pass


def _update_preview_clip(self, context):
    name = getattr(self, "mu_preview_clip", "") or "NONE"
    _set_preview_clip_active(context, name)


def _preview_clip_enum_items(self, context):
    names = _collect_preview_clip_names(context)
    items = [
        (
            "NONE",
            "(none / muted)",
            "Mute all non-FX clips and reset pose to rest (frame start)",
        ),
        (
            "ALL",
            "(all / import default)",
            "Unmute all non-FX clips and reset to frame start (import default pose)",
        ),
    ]
    if not names:
        return [
            ("NONE", "(no clips)", "No NLA clips on selected hierarchy"),
            items[1],
        ]
    fx_labels = set()
    try:
        objs = [
            x for x in _preview_clip_scope_ids(context)
            if isinstance(x, bpy.types.Object)
        ]
        fx_labels = {lab for lab, _ in _particle_fx_hosts_in_scope(objs)}
    except Exception:
        pass
    for n in names:
        if n in fx_labels:
            items.append((n, f"{n} (FX)", f"Show particle FX host '{n}'"))
        else:
            items.append((n, n, f"Activate NLA clip '{n}'"))
    return items


def _is_collider_object(obj):
    if not obj:
        return False
    if obj.name.startswith("mesh:"):
        return True
    muprops = getattr(obj, "muproperties", None)
    if muprops and muprops.collider and muprops.collider != 'MU_COL_NONE':
        return True
    for col in obj.users_collection:
        if col.name.endswith(".collider") or ".collider." in col.name:
            return True
    if "collider" in obj.name.lower():
        return True
    return False


def _iter_scope_objects(context, scope):
    if scope == 'SELECTED':
        sel = list(context.selected_objects)
        if not sel and context.active_object:
            sel = [context.active_object]
        out = []
        for o in sel:
            out.append(o)
            out.extend(o.children_recursive)
        return out
    if scope == 'COLLECTION':
        col = context.collection
        if not col:
            return list(context.scene.objects)
        return list(col.all_objects)
    return list(context.scene.objects)


def _set_collider_hide(objects, hide):
    n = 0
    for obj in objects:
        if not _is_collider_object(obj):
            continue
        obj.hide_viewport = hide
        n += 1
    return n


def _is_shroud_or_fairing_object(obj):
    """Engine ModuleJettison covers: fairing, Shroud, ShortShroud, nShroud…

    Variant-only GAMEOBJECTS (LV-1 chamber named Shroud) are skipped. Names
    that are also ModuleJettison ``jettisonName`` (Poodle Shroud1, Terrier
    ShortShroud) still count as covers.
    """
    if not obj:
        return False
    name = (obj.name or "").lower()
    if not name:
        return False
    wedge = "\u2227"
    key = name.split(wedge, 1)[0].strip()
    jettison = set()
    variant_keys = set()
    try:
        cur = obj
        while cur is not None:
            raw_j = cur.get("mu_jettison_names")
            if raw_j:
                try:
                    jettison.update(
                        str(n).lower() for n in json.loads(raw_j) if n
                    )
                except Exception:
                    pass
            raw = cur.get("mu_variants")
            if raw:
                data = json.loads(raw)
                for v in data.get("variants") or []:
                    variant_keys.update(
                        str(k).lower() for k in (v.get("objects") or {}) if k
                    )
                for n in data.get("jettisonNames") or []:
                    if n:
                        jettison.add(str(n).lower())
                break
            cur = cur.parent
    except Exception:
        pass
    if key in jettison:
        return True
    if key in variant_keys and key not in jettison:
        return False
    return ("fairing" in name) or ("shroud" in name)


def _set_shroud_fairing_hide(objects, hide):
    n = 0
    for obj in objects:
        if not _is_shroud_or_fairing_object(obj):
            continue
        obj.hide_viewport = hide
        n += 1
    return n


def _cfg_broken_names_for(obj):
    """Broken transform names stored on the import root (from .cfg)."""
    names = set()
    try:
        cur = obj
        while cur is not None:
            raw = cur.get("mu_broken_names")
            if raw:
                try:
                    for n in json.loads(raw):
                        if n:
                            names.add(str(n).lower())
                except Exception:
                    pass
                break
            cur = cur.parent
    except Exception:
        pass
    return names


def _is_broken_object(obj):
    """Damaged visual: .broken / busted / cfg damagedTransformName, etc."""
    if not obj:
        return False
    name = obj.name or ""
    if not name:
        return False
    n = name.lower()
    wedge = "\u2227"
    key = n.split("\u2227", 1)[0].strip()
    cfg_names = _cfg_broken_names_for(obj)
    for bn in cfg_names:
        if key == bn or key.startswith(bn + ".") or bn in key:
            return True
    if ".broken" in n or n.endswith("broken") or "_broken" in n:
        return True
    if "busted" in n or n.startswith("damaged") or ".damaged" in n:
        return True
    return False


def _set_broken_hide(objects, hide):
    """Hide each broken root and its full child hierarchy (meshes + colliders)."""
    n = 0
    seen = set()
    for obj in objects:
        if not _is_broken_object(obj):
            continue
        # Skip if an ancestor is already being hidden as broken
        try:
            p = obj.parent
            skip = False
            while p is not None:
                if _is_broken_object(p):
                    skip = True
                    break
                p = p.parent
            if skip:
                continue
        except Exception:
            pass
        try:
            branch = [obj] + list(getattr(obj, "children_recursive", []) or [])
        except Exception:
            branch = [obj]
        for o in branch:
            try:
                k = o.as_pointer()
                if k in seen:
                    continue
                seen.add(k)
                o.hide_viewport = hide
                try:
                    o.hide_render = hide
                except Exception:
                    pass
                n += 1
            except Exception:
                pass
    return n


def _mute_normal_nodes(node_tree, mute):
    if not node_tree:
        return 0
    n = 0
    for node in node_tree.nodes:
        if node.type in {'NORMAL_MAP', 'BUMP'}:
            node.mute = mute
            n += 1
        if node.type == 'GROUP' and getattr(node, "node_tree", None):
            n += _mute_normal_nodes(node.node_tree, mute)
        if node.type == 'TEX_IMAGE':
            lname = node.name.lower()
            if (lname.startswith('_bump') or 'bump' in lname
                    or 'normalmap' in lname or lname == '_normalmap'):
                if node.name not in {'_MainTex', '_Emissive', '_Emission'}:
                    node.mute = mute
                    n += 1
    return n


class KSPMU_OT_ToggleColliders(bpy.types.Operator):
    bl_idname = "object.mu_toggle_colliders"
    bl_label = "Toggle Colliders"
    bl_description = "Show or hide Mu colliders in the viewport"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=(
            ('ALL', "All in Scene", "All collider objects in the scene"),
            ('SELECTED', "Selected Hierarchy",
             "Active/selected object and children"),
            ('COLLECTION', "Active Collection",
             "Objects in the active collection"),
        ),
        default='ALL',
    )
    force: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ('TOGGLE', "Toggle", "Invert current visibility"),
            ('HIDE', "Hide", "Hide colliders"),
            ('SHOW', "Show", "Show colliders"),
        ),
        default='TOGGLE',
    )

    def execute(self, context):
        objs = [o for o in _iter_scope_objects(context, self.scope)
                if _is_collider_object(o)]
        if not objs:
            self.report({'INFO'}, "No colliders in scope")
            return {'CANCELLED'}
        if self.force == 'HIDE':
            hide = True
        elif self.force == 'SHOW':
            hide = False
        else:
            hidden = sum(1 for o in objs if o.hide_viewport)
            hide = hidden < len(objs) / 2
        n = _set_collider_hide(objs, hide)
        try:
            context.scene["mu_colliders_hidden"] = bool(hide)
        except Exception:
            pass
        self.report({'INFO'},
                    f"{'Hidden' if hide else 'Shown'} {n} collider(s)")
        return {'FINISHED'}


class KSPMU_OT_ToggleShroudFairing(bpy.types.Operator):
    bl_idname = "object.mu_toggle_shroud_fairing"
    bl_label = "Toggle Shroud/Fairing"
    bl_description = (
        "Show or hide engine shroud / fairing meshes in the viewport "
        "(names containing shroud or fairing)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=(
            ('ALL', "All in Scene", "All shroud/fairing objects in the scene"),
            ('SELECTED', "Selected Hierarchy",
             "Active/selected object and children"),
            ('COLLECTION', "Active Collection",
             "Objects in the active collection"),
        ),
        default='ALL',
    )
    force: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ('TOGGLE', "Toggle", "Invert current visibility"),
            ('HIDE', "Hide", "Hide shrouds/fairings"),
            ('SHOW', "Show", "Show shrouds/fairings"),
        ),
        default='TOGGLE',
    )

    def execute(self, context):
        objs = [o for o in _iter_scope_objects(context, self.scope)
                if _is_shroud_or_fairing_object(o)]
        if not objs:
            self.report({'INFO'}, "No shroud/fairing objects in scope")
            return {'CANCELLED'}
        if self.force == 'HIDE':
            hide = True
        elif self.force == 'SHOW':
            hide = False
        else:
            hidden = sum(1 for o in objs if o.hide_viewport)
            hide = hidden < len(objs) / 2
        n = _set_shroud_fairing_hide(objs, hide)
        try:
            context.scene["mu_shrouds_hidden"] = bool(hide)
        except Exception:
            pass
        self.report(
            {'INFO'},
            f"{'Hidden' if hide else 'Shown'} {n} shroud/fairing object(s)",
        )
        return {'FINISHED'}



class KSPMU_OT_ToggleBroken(bpy.types.Operator):
    bl_idname = "object.mu_toggle_broken"
    bl_label = "Toggle Broken / Damaged"
    bl_description = (
        "Show or hide damaged meshes (.broken, busted wheel, "
        "ModuleWheelDamage damagedTransformName). Default: hidden"
    )
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=(
            ('ALL', "All in Scene", "All broken/damaged objects in the scene"),
            ('SELECTED', "Selected Hierarchy",
             "Active/selected object and children"),
            ('COLLECTION', "Active Collection",
             "Objects in the active collection"),
        ),
        default='ALL',
    )
    force: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ('TOGGLE', "Toggle", "Invert current visibility"),
            ('HIDE', "Hide", "Hide broken/damaged meshes"),
            ('SHOW', "Show", "Show broken/damaged meshes"),
        ),
        default='TOGGLE',
    )

    def execute(self, context):
        objs = [o for o in _iter_scope_objects(context, self.scope)
                if _is_broken_object(o)]
        if not objs:
            self.report({'INFO'}, "No broken/damaged objects in scope")
            return {'CANCELLED'}
        if self.force == 'HIDE':
            hide = True
        elif self.force == 'SHOW':
            hide = False
        else:
            hidden = sum(1 for o in objs if o.hide_viewport)
            hide = hidden < len(objs) / 2
        n = _set_broken_hide(objs, hide)
        self.report(
            {'INFO'},
            f"{'Hidden' if hide else 'Shown'} {n} broken/damaged object(s)",
        )
        return {'FINISHED'}


class KSPMU_OT_ToggleBumpPreview(bpy.types.Operator):
    bl_idname = "object.mu_toggle_bump_preview"
    bl_label = "Toggle Bump/Normal Preview"
    bl_description = (
        "Mute or unmute Normal Map / Bump nodes in materials "
        "(viewport only; export unchanged)")
    bl_options = {'REGISTER', 'UNDO'}

    force: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ('TOGGLE', "Toggle", "Invert mute state"),
            ('HIDE', "Hide", "Mute bump/normal nodes"),
            ('SHOW', "Show", "Unmute bump/normal nodes"),
        ),
        default='TOGGLE',
    )

    def execute(self, context):
        mats = [m for m in bpy.data.materials
                if m.node_tree and hasattr(m, "mumatprop")
                and m.mumatprop.shaderName]
        if not mats:
            self.report({'INFO'}, "No Mu materials")
            return {'CANCELLED'}
        muted = 0
        total = 0
        for m in mats:
            for n in m.node_tree.nodes:
                if n.type in {'NORMAL_MAP', 'BUMP'}:
                    total += 1
                    if n.mute:
                        muted += 1
                if n.type == 'GROUP' and n.node_tree:
                    for gn in n.node_tree.nodes:
                        if gn.type in {'NORMAL_MAP', 'BUMP'}:
                            total += 1
                            if gn.mute:
                                muted += 1
        if self.force == 'HIDE':
            mute = True
        elif self.force == 'SHOW':
            mute = False
        else:
            mute = muted < max(1, total) / 2
        n = 0
        for m in mats:
            n += _mute_normal_nodes(m.node_tree, mute)
        self.report({'INFO'},
                    f"{'Muted' if mute else 'Unmuted'} {n} bump/normal node(s)")
        return {'FINISHED'}


def _is_particle_preview_object(obj):
    """Viewport-only FX children (.fx_preview / .fx_anim / .fx_emitter)."""
    if not obj:
        return False
    name = obj.name or ""
    if (
        ".fx_preview" in name
        or ".fx_anim" in name
        or ".fx_emitter" in name
    ):
        return True
    if obj.get("mu_fx_preview"):
        return True
    if getattr(obj, "particle_systems", None) and len(obj.particle_systems):
        # Only treat as FX if tagged or named like our import preview
        if obj.get("mu_fx_preview") or "fx_" in name.lower():
            return True
    return False


def _set_particle_preview_hide(objects, hide):
    n = 0
    for obj in objects:
        if not _is_particle_preview_object(obj):
            continue
        obj.hide_viewport = hide
        try:
            obj.hide_render = hide
        except Exception:
            pass
        n += 1
    # Also mute Particle Systems (OBJECT instances ignore billboard hide alone)
    try:
        from ..import_mu.particles_preview import set_particles_preview_visible
        set_particles_preview_visible(not hide)
    except Exception:
        pass
    return n


class KSPMU_OT_ToggleParticlesPreview(bpy.types.Operator):
    bl_idname = "object.mu_toggle_particles_preview"
    bl_label = "Toggle Particles Preview"
    bl_description = (
        "Show or hide Mu particle FX preview (dust, rocks, plumes). "
        "Viewport only; export unchanged")
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=(
            ('ALL', "All in Scene", "All FX preview objects in the scene"),
            ('SELECTED', "Selected Hierarchy",
             "Active/selected object and children"),
            ('COLLECTION', "Active Collection",
             "Objects in the active collection"),
        ),
        default='ALL',
    )
    force: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ('TOGGLE', "Toggle", "Invert current visibility"),
            ('HIDE', "Hide", "Hide particle FX preview"),
            ('SHOW', "Show", "Show particle FX preview"),
        ),
        default='TOGGLE',
    )

    def execute(self, context):
        objs = [o for o in _iter_scope_objects(context, self.scope)
                if _is_particle_preview_object(o)]
        if not objs:
            self.report({'INFO'}, "No particle FX preview in scope")
            return {'CANCELLED'}
        if self.force == 'HIDE':
            hide = True
        elif self.force == 'SHOW':
            hide = False
        else:
            hidden = sum(1 for o in objs if o.hide_viewport)
            hide = hidden < len(objs) / 2
        n = _set_particle_preview_hide(objs, hide)
        self.report(
            {'INFO'},
            f"{'Hidden' if hide else 'Shown'} {n} particle FX object(s)",
        )
        return {'FINISHED'}


def _set_scene_active_variant(scene, name):
    """Sync Options enum after Add/Remove (ID prop + EnumProperty)."""
    if not name or scene is None:
        return
    try:
        scene["mu_active_variant"] = name
    except Exception:
        pass
    try:
        if hasattr(scene, "mu_active_variant"):
            scene.mu_active_variant = name
    except Exception:
        pass


class KSPMU_OT_AddPartVariant(bpy.types.Operator):
    bl_idname = "object.mu_add_part_variant"
    bl_label = "Add Variant"
    bl_description = (
        "Duplicate the active ModulePartVariants cfg entry "
        "(mu_variants JSON only — not an Outliner collection)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            from ..import_mu.cfg_preview import (
                MU_VARIANTS_KEY,
                STOCK_VARIANT_NAME,
                add_variant_duplicate,
                find_variant_root,
            )
            import json
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        root = find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is None:
            # Seed empty variants from selection root
            obj = context.active_object
            if obj is None:
                self.report({'WARNING'}, "No active object")
                return {'CANCELLED'}
            while obj.parent:
                obj = obj.parent
            root = obj
            data = {
                "base": STOCK_VARIANT_NAME,
                "active": STOCK_VARIANT_NAME,
                "kind": "texture",
                "variants": [{
                    "name": STOCK_VARIANT_NAME,
                    "objects": {},
                    "textures": {},
                    "disabledAnimations": [],
                    "stock": True,
                    "displayName": "Stock",
                }],
            }
            root[MU_VARIANTS_KEY] = json.dumps(data)
        # JSON-only duplicate + apply_variant; never creates Outliner collections.
        name = add_variant_duplicate(root)
        if not name:
            self.report({'WARNING'}, "Could not add variant")
            return {'CANCELLED'}
        _set_scene_active_variant(context.scene, name)
        self.report(
            {'INFO'},
            f"Added cfg variant '{name}' (not an Outliner collection)",
        )
        return {'FINISHED'}


class KSPMU_OT_RemovePartVariant(bpy.types.Operator):
    bl_idname = "object.mu_remove_part_variant"
    bl_label = "Remove Variant"
    bl_description = (
        "Remove the active ModulePartVariants cfg entry from mu_variants "
        "(does not delete .mu meshes / Outliner collections)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            from ..import_mu.cfg_preview import (
                find_variant_root,
                get_active_variant_name,
                remove_active_variant,
            )
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        root = find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is None:
            self.report({'WARNING'}, "No variants on selection")
            return {'CANCELLED'}
        prev = get_active_variant_name(root)
        # JSON-only remove + apply_variant; never deletes imported meshes.
        if not remove_active_variant(root):
            self.report(
                {'WARNING'},
                "Cannot remove Stock / B9-from-cfg / last / base-only variant",
            )
            return {'CANCELLED'}
        active = get_active_variant_name(root)
        if active:
            _set_scene_active_variant(context.scene, active)
        self.report(
            {'INFO'},
            f"Removed cfg variant '{prev}' (meshes/collections kept)",
        )
        return {'FINISHED'}


class KSPMU_OT_SavePartCfg(bpy.types.Operator):
    bl_idname = "export_object.ksp_mu_save_part_cfg"
    bl_label = "Save Part Cfg…"
    bl_description = (
        "Write ModulePartVariants and animation EFFECTS/AUDIO into the "
        "active/selected part .cfg (confirms before overwriting the original; "
        "Save As for another path)"
    )
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filename_ext = ".cfg"
    filter_glob: bpy.props.StringProperty(default="*.cfg", options={'HIDDEN'})
    overwrite_confirmed: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    force_file_browser: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        try:
            from ..preferences import Preferences
            if not Preferences().WritePartCfg:
                self.report({'WARNING'}, "Write / Update Part Cfg is disabled")
                return {'CANCELLED'}
        except Exception:
            pass
        root = self._root(context)
        if root is None:
            self.report({'WARNING'}, "No part root with cfg / variants / sounds")
            return {'CANCELLED'}
        cfg = root.get("mu_cfg_path") or ""
        if self.force_file_browser:
            # Suggest a non-destructive default next to the original
            if cfg:
                stem, ext = os.path.splitext(cfg)
                self.filepath = stem + "_edited" + (ext or ".cfg")
            elif not self.filepath:
                mudir = root.get("mu_dirname") or ""
                self.filepath = os.path.join(mudir or "", "part_edited.cfg")
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        if cfg and not self.filepath:
            self.filepath = cfg
        # Always confirm when targeting the original mu_cfg_path
        if cfg and os.path.normpath(self.filepath or cfg) == os.path.normpath(cfg):
            return context.window_manager.invoke_props_dialog(self, width=420)
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        path = self.filepath or "(unknown)"
        layout.label(text="Overwrite original part.cfg?")
        layout.label(text=path)
        layout.label(text="OK = overwrite · Cancel = abort")
        layout.label(text="Variants + animation sounds will be patched.")
        layout.separator()
        # Third choice (dialog footer is only OK / Cancel)
        layout.operator_context = 'INVOKE_DEFAULT'
        op = layout.operator(
            "export_object.ksp_mu_save_part_cfg",
            text="Save As…",
            icon='FILE_NEW',
        )
        op.force_file_browser = True
        op.overwrite_confirmed = True
        op.filepath = ""

    def _root(self, context):
        try:
            from ..import_mu.cfg_preview import find_variant_root
        except Exception:
            return None
        root = find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is not None:
            return root
        obj = context.active_object
        if obj is None:
            return None
        while obj.parent:
            obj = obj.parent
        return obj

    def execute(self, context):
        try:
            from ..preferences import Preferences
            if not Preferences().WritePartCfg:
                self.report({'WARNING'}, "Write / Update Part Cfg is disabled")
                return {'CANCELLED'}
        except Exception:
            pass
        try:
            from ..export_mu.variants_cfg import write_part_cfg
            from ..import_mu.cfg_preview import MU_VARIANTS_KEY
            from ..import_mu.sound_preview import (
                MU_SOUNDS_KEY,
                flush_sounds_from_vse,
            )
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        root = self._root(context)
        if root is None:
            self.report({'WARNING'}, "No part root")
            return {'CANCELLED'}
        data = None
        raw = root.get(MU_VARIANTS_KEY)
        if raw:
            try:
                data = json.loads(raw)
            except Exception as e:
                self.report({'ERROR'}, f"Bad mu_variants: {e}")
                return {'CANCELLED'}
        flush_sounds_from_vse(root)
        mu_sounds = None
        sraw = root.get(MU_SOUNDS_KEY)
        if sraw:
            try:
                mu_sounds = json.loads(sraw)
            except Exception as e:
                self.report({'ERROR'}, f"Bad mu_sounds: {e}")
                return {'CANCELLED'}
        if not data and not mu_sounds:
            self.report({'WARNING'}, "No mu_variants or mu_sounds on part")
            return {'CANCELLED'}
        orig = root.get("mu_cfg_path") or ""
        path = self.filepath or orig
        if not path:
            self.report({'WARNING'}, "No cfg path")
            return {'CANCELLED'}
        # Confirm overwrite of original when dialog was used
        if orig and os.path.normpath(path) == os.path.normpath(orig):
            if not self.overwrite_confirmed:
                # Dialog OK → proceed
                self.overwrite_confirmed = True
        source = None
        if orig and os.path.isfile(orig):
            try:
                with open(orig, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except Exception:
                source = None
        mudir = root.get("mu_dirname") or os.path.dirname(path)
        mu_basename = None
        try:
            # Prefer .mu next to cfg
            for fn in os.listdir(mudir):
                if fn.lower().endswith(".mu"):
                    mu_basename = fn
                    break
        except Exception:
            pass
        try:
            from ..import_mu.sound_preview import log_sound_entries
            log_sound_entries("KSP sound export", mu_sounds)
        except Exception:
            pass
        try:
            write_part_cfg(
                path, data or {}, source_text=source,
                mudir=mudir, mu_basename=mu_basename,
                mu_sounds=mu_sounds,
            )
        except Exception as e:
            self.report({'ERROR'}, f"Write failed: {e}")
            return {'CANCELLED'}
        n_sfx = len((mu_sounds or {}).get("entries") or []) if mu_sounds else 0
        if n_sfx:
            self.report({'INFO'}, f"Saved {path} (+ {n_sfx} sound entr(y/ies))")
        else:
            self.report({'INFO'}, f"Saved {path}")
        return {'FINISHED'}


class KSPMU_OT_SyncAnimSounds(bpy.types.Operator):
    bl_idname = "object.ksp_mu_sync_anim_sounds"
    bl_label = "Apply Sound Timing"
    bl_description = (
        "Read VSE sound strip positions into mu_sounds (muSoundTime). "
        "Use Save Part Cfg to write them into the .cfg"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            from ..import_mu.sound_preview import flush_sounds_from_vse
            from ..import_mu.cfg_preview import find_variant_root
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        root = find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is None:
            obj = context.active_object
            if obj is not None:
                while obj.parent:
                    obj = obj.parent
                root = obj
        if root is None:
            self.report({'WARNING'}, "No part root")
            return {'CANCELLED'}
        data = flush_sounds_from_vse(root)
        n = len((data or {}).get("entries") or [])
        self.report({'INFO'}, f"Updated timing for {n} sound entr(y/ies)")
        return {'FINISHED'}


class KSPMU_OT_AddAnimSound(bpy.types.Operator):
    bl_idname = "object.ksp_mu_add_anim_sound"
    bl_label = "Add Animation Sound…"
    bl_description = (
        "Add a WAV/OGG under an EFFECTS name (deploy/retract/…) and create "
        "a VSE strip; Save Part Cfg writes a new AUDIO block"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(
        default="*.wav;*.ogg;*.flac", options={'HIDDEN'}
    )
    effect: bpy.props.StringProperty(name="Effect", default="deploy")
    kind: bpy.props.EnumProperty(
        name="Kind",
        items=(
            ('audio', "AUDIO", "One-shot"),
            ('loop', "AUDIO_LOOP", "Loop for clip length"),
        ),
        default='audio',
    )
    anim_clip: bpy.props.StringProperty(name="Anim clip", default="Deploy")
    sound_time: bpy.props.FloatProperty(name="Time (s)", default=0.0, min=0.0)
    sound_duration: bpy.props.FloatProperty(
        name="Duration (s)", default=1.0, min=0.05
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            from ..import_mu.sound_preview import add_sound_entry
            from ..import_mu.cfg_preview import find_variant_root
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        root = find_variant_root(
            getattr(context, "active_object", None), context=context
        )
        if root is None:
            obj = context.active_object
            if obj is not None:
                while obj.parent:
                    obj = obj.parent
                root = obj
        if root is None:
            self.report({'WARNING'}, "No part root")
            return {'CANCELLED'}
        path = self.filepath or ""
        if not path or not os.path.isfile(path):
            self.report({'WARNING'}, "No sound file")
            return {'CANCELLED'}
        try:
            add_sound_entry(
                root,
                path,
                effect=self.effect or "deploy",
                kind=self.kind,
                mu_anim_clip=self.anim_clip or "Deploy",
                mu_sound_time=float(self.sound_time),
                mu_sound_duration=float(self.sound_duration),
            )
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Added sound under EFFECTS/{self.effect}")
        return {'FINISHED'}



def _iter_suspension_preview_tracks(context):
    """Yield (obj, track) for SuspensionTravel / mu_suspension_preview NLA tracks."""
    roots = _preview_clip_hierarchy_roots(context) if context else []
    if not roots:
        # Fallback: scan scene
        try:
            roots = [
                o for o in bpy.context.scene.objects
                if o.parent is None
            ]
        except Exception:
            roots = []
    seen = set()
    for root in roots:
        try:
            stack = [root] + list(getattr(root, "children_recursive", []) or [])
        except Exception:
            stack = [root]
        for obj in stack:
            if obj is None:
                continue
            try:
                key = obj.as_pointer()
            except Exception:
                key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            ad = getattr(obj, "animation_data", None)
            if not ad or not ad.nla_tracks:
                continue
            for track in ad.nla_tracks:
                tn = track.name or ""
                is_susp = False
                try:
                    if track.get("mu_suspension_preview"):
                        is_susp = True
                except Exception:
                    pass
                if not is_susp and tn.startswith("Suspension"):
                    is_susp = True
                if not is_susp:
                    # action tag
                    try:
                        for strip in track.strips:
                            act = strip.action
                            if act is not None and (
                                act.get("mu_fx_preview")
                                and "suspension" in (act.name or "").lower()
                            ):
                                is_susp = True
                                break
                    except Exception:
                        pass
                if is_susp:
                    yield obj, track


def _set_suspension_preview_enabled(context, enabled):
    """Mute/unmute SuspensionTravel tracks and optionally drive active action."""
    enabled = bool(enabled)
    for obj, track in _iter_suspension_preview_tracks(context):
        try:
            track.mute = not enabled
        except Exception:
            pass
        if enabled:
            # Assign first strip action so scrubbing works without NLA solo
            try:
                act = None
                for strip in track.strips:
                    if strip.action is not None:
                        act = strip.action
                        break
                if act is not None:
                    if not obj.animation_data:
                        obj.animation_data_create()
                    # Keep NLA evaluation; clear exclusive action if it blocks NLA
                    # Blender uses NLA when action is None
                    obj.animation_data.action = None
            except Exception:
                pass
        else:
            try:
                if obj.animation_data and obj.animation_data.action:
                    act = obj.animation_data.action
                    if act and (
                        act.get("mu_fx_preview")
                        or "suspension" in (act.name or "").lower()
                    ):
                        obj.animation_data.action = None
            except Exception:
                pass
    # Force eval so mute takes effect immediately
    try:
        scene = context.scene if context else bpy.context.scene
        if scene is not None:
            scene.frame_set(int(scene.frame_current))
    except Exception:
        pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _update_suspension_preview(self, context):
    _set_suspension_preview_enabled(
        context, bool(getattr(self, "mu_suspension_preview", False))
    )


class WORKSPACE_PT_mu_options(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_context = ".objectmode"
    bl_label = "Options"
    # Before Prop Tools / Mu Hierarchy / Export Mu
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        # RNA props can be missing after partial reload — re-register on the fly
        try:
            ensure_scene_props()
        except Exception as e:
            col.label(text="Props register error: %s" % e)
            return
        # Keep dropdown in sync with the selected import root's active variant
        _sync_variant_enum_to_selection(context)
        _sync_flag_enum_to_selection(context)
        _sync_mesh_paint_enums_from_id(context)
        col.label(text="Part Variant")
        # Always prefer split Mesh / Paint when both exist on the part
        has_mesh = has_paint = False
        try:
            from ..import_mu.cfg_preview import (
                get_mesh_variant_items,
                get_paint_variant_items,
            )
            mi = get_mesh_variant_items(context.scene, context)
            pi = get_paint_variant_items(context.scene, context)
            has_mesh = bool(mi) and mi[0][0] != "NONE"
            has_paint = bool(pi) and pi[0][0] != "NONE"
        except Exception as e:
            print("WARNING: variant UI split:", e)
        # B9 multi-module → split Mesh / Paint.  Stock ModulePartVariants
        # (and single-list parts) → one combined dropdown so no variants vanish.
        # Independent B9 mesh modules → one dropdown each (Dome, Rim, …)
        mesh_groups = []
        try:
            from ..import_mu.cfg_preview import get_mesh_switch_groups
            mesh_groups = get_mesh_switch_groups(context=context) or []
        except Exception:
            mesh_groups = []
        rna_slots = (
            "mu_mesh_variant",
            "mu_mesh_variant_2",
            "mu_mesh_variant_3",
            "mu_mesh_variant_4",
        )
        if mesh_groups:
            for i, g in enumerate(mesh_groups[:4]):
                col.label(text=g.get("label") or "Mesh")
                col.prop(context.scene, rna_slots[i], text="")
            if has_paint:
                col.label(text="Paint")
                col.prop(context.scene, "mu_paint_variant", text="")
        elif has_mesh and has_paint:
            col.label(text="Mesh")
            col.prop(context.scene, "mu_mesh_variant", text="")
            col.label(text="Paint")
            col.prop(context.scene, "mu_paint_variant", text="")
        elif has_mesh:
            col.label(text="Mesh")
            col.prop(context.scene, "mu_mesh_variant", text="")
        elif has_paint:
            col.label(text="Paint")
            col.prop(context.scene, "mu_paint_variant", text="")
        else:
            col.prop(context.scene, "mu_active_variant", text="")
        try:
            from ..preferences import Preferences
            prefs = Preferences()
            col.prop(prefs, "WritePartCfg")
            save_row = col.row()
            save_row.enabled = bool(prefs.WritePartCfg)
            save_row.operator(
                "export_object.ksp_mu_save_part_cfg", text="Save Part Cfg…"
            )
        except Exception:
            col.operator(
                "export_object.ksp_mu_save_part_cfg", text="Save Part Cfg…"
            )
        col.separator()
        col.label(text="Animation Sounds")
        col.operator("object.ksp_mu_sync_anim_sounds", text="Apply Sound Timing")
        col.operator("object.ksp_mu_add_anim_sound", text="Add Animation Sound…")
        col.separator()
        col.label(text="Flag Decal")
        if hasattr(context.scene, "mu_active_flag"):
            col.prop(context.scene, "mu_active_flag", text="")
        col.separator()
        col.label(text="Preview Clip")
        if hasattr(context.scene, "mu_preview_clip"):
            col.prop(context.scene, "mu_preview_clip", text="")
        if hasattr(context.scene, "mu_animations_off"):
            col.prop(context.scene, "mu_animations_off", text="Animations Off")
        # SuspensionTravel is synthetic FX (viewport) — off by default
        row = col.row(align=True)
        row.prop(
            context.scene,
            "mu_suspension_preview",
            text="SuspensionTravel",
        )
        # Hint: multi-MODEL secondaries live in part.variants (read-only FX)
        try:
            from ..import_mu.cfg_preview import find_variant_root, MU_VARIANTS_KEY
            import json as _json
            _r = find_variant_root(getattr(context, "active_object", None), context=context)
            if _r is not None and int(_r.get("mu_secondary_models") or 0) > 0:
                col.label(text="Extra MODEL variants in .variants (viewport only)")
            if _r is not None and _r.get("mu_secondary_model"):
                col.label(text="Secondary MODEL — edit its .mu separately")
        except Exception:
            pass
        col.separator()
        col.label(text="CFG Parameters")
        col.prop(context.scene, "mu_cfg_filter", text="Filter")
        col.prop(context.scene, "mu_cfg_param", text="")
        try:
            from ..import_mu.cfg_store import get_cfg_tree
        except Exception:
            get_cfg_tree = None
        try:
            from ..import_mu.cfg_preview import find_variant_root as _fvr
            _root = _fvr(getattr(context, "active_object", None), context=context)
            data = get_cfg_tree(_root) if get_cfg_tree and _root else None
            if data:
                col.label(text=f"{data.get('count', 0)} keys stored from part.cfg")
        except Exception:
            pass
        col.separator()
        col.label(text="Colliders")
        try:
            from ..preferences import Preferences
            prefs = Preferences()
            col.prop(prefs, "AutohideColliders")
        except Exception:
            pass
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_colliders", text="Toggle All")
        op.scope = 'ALL'
        op.force = 'TOGGLE'
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_colliders", text="Selected")
        op.scope = 'SELECTED'
        op.force = 'TOGGLE'
        op = row.operator("object.mu_toggle_colliders", text="Collection")
        op.scope = 'COLLECTION'
        op.force = 'TOGGLE'
        col.separator()
        col.label(text="Shroud / Fairing")
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_shroud_fairing", text="Toggle All")
        op.scope = 'ALL'
        op.force = 'TOGGLE'
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_shroud_fairing", text="Selected")
        op.scope = 'SELECTED'
        op.force = 'TOGGLE'
        op = row.operator("object.mu_toggle_shroud_fairing", text="Collection")
        op.scope = 'COLLECTION'
        op.force = 'TOGGLE'
        col.separator()
        col.label(text="Broken / Damaged")
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_broken", text="Toggle All")
        op.scope = 'ALL'
        op.force = 'TOGGLE'
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_broken", text="Selected")
        op.scope = 'SELECTED'
        op.force = 'TOGGLE'
        op = row.operator("object.mu_toggle_broken", text="Collection")
        op.scope = 'COLLECTION'
        op.force = 'TOGGLE'
        col.separator()
        col.label(text="KSP - Game Path")
        try:
            from ..preferences import Preferences
            prefs = Preferences()
            col.prop(prefs, "GameData", text="")
        except Exception:
            pass
        col.separator()
        col.label(text="Materials (preview)")
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_bump_preview",
                          text="Toggle Bump/Normal")
        op.force = 'TOGGLE'
        col.operator(
            "io_object_mu.shader_preset_selection",
            text="Apply Shader Preset…",
        )
        col.separator()
        col.label(text="Particles (preview)")
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_particles_preview",
                          text="Toggle Particles")
        op.scope = 'ALL'
        op.force = 'TOGGLE'
        row = col.row(align=True)
        op = row.operator("object.mu_toggle_particles_preview", text="Selected")
        op.scope = 'SELECTED'
        op.force = 'TOGGLE'
        op = row.operator("object.mu_toggle_particles_preview",
                          text="Collection")
        op.scope = 'COLLECTION'
        op.force = 'TOGGLE'


def ensure_scene_props():
    """Register Scene RNA props if missing (safe after partial addon reload)."""
    S = bpy.types.Scene
    def _add(name, prop):
        if hasattr(S, name):
            return
        try:
            setattr(S, name, prop)
        except Exception as e:
            print("WARNING: register Scene.%s: %s" % (name, e))

    _add(
        "mu_active_variant",
        bpy.props.EnumProperty(
            name="Part Variant",
            description="Active ModulePartVariants / B9PartSwitch preview (viewport only)",
            items=_variant_enum_items,
            update=_update_part_variant,
        ),
    )
    _add(
        "mu_mesh_variant",
        bpy.props.EnumProperty(
            name="Mesh Variant",
            description="First mesh switch module (e.g. Dome)",
            items=_mesh_variant_enum_items,
            update=_update_mesh_variant,
        ),
    )
    _add(
        "mu_mesh_variant_2",
        bpy.props.EnumProperty(
            name="Mesh Variant 2",
            description="Second mesh switch module (e.g. Rim)",
            items=_mesh_variant_2_enum_items,
            update=_update_mesh_variant_2,
        ),
    )
    _add(
        "mu_mesh_variant_3",
        bpy.props.EnumProperty(
            name="Mesh Variant 3",
            description="Third mesh switch module",
            items=_mesh_variant_3_enum_items,
            update=_update_mesh_variant_3,
        ),
    )
    _add(
        "mu_mesh_variant_4",
        bpy.props.EnumProperty(
            name="Mesh Variant 4",
            description="Fourth mesh switch module",
            items=_mesh_variant_4_enum_items,
            update=_update_mesh_variant_4,
        ),
    )
    _add(
        "mu_paint_variant",
        bpy.props.EnumProperty(
            name="Paint Variant",
            description="Texture / paint switch (independent of mesh)",
            items=_paint_variant_enum_items,
            update=_update_paint_variant,
        ),
    )
    _add(
        "mu_active_flag",
        bpy.props.EnumProperty(
            name="Flag Decal",
            description="Active FlagDecal preview texture (viewport only)",
            items=_flag_enum_items,
            update=_update_active_flag,
        ),
    )
    _add(
        "mu_preview_clip",
        bpy.props.EnumProperty(
            name="Preview Clip",
            description=(
                "NLA preview on selected hierarchy: none=mute+rest, "
                "all=unmute+rest, or a single clip (FX stays unmuted)"
            ),
            items=_preview_clip_enum_items,
            update=_update_preview_clip,
        ),
    )
    _add(
        "mu_anim_variant_filter",
        bpy.props.BoolProperty(
            name="All / variant",
            description=(
                "On: Animation list shows only clips for the active part variant. "
                "Off: show every clip"
            ),
            default=False,
        ),
    )
    _add(
        "mu_animations_off",
        bpy.props.BoolProperty(
            name="Animations Off",
            description=(
                "Mute Mu animation clips and stop timeline playback. "
                "Clips stay in the file. FX preview tracks are left alone"
            ),
            default=False,
            update=_update_animations_off,
        ),
    )
    _add(
        "mu_suspension_preview",
        bpy.props.BoolProperty(
            name="SuspensionTravel",
            description=(
                "Enable synthetic SuspensionTravel NLA (viewport FX). "
                "Off by default — not a real MuAnimation, skipped on export"
            ),
            default=False,
            update=_update_suspension_preview,
        ),
    )
    try:
        from ..import_mu.cfg_store import register_cfg_ui
        register_cfg_ui()
    except Exception as e:
        print("WARNING: cfg UI register:", e)


def register():
    ensure_scene_props()
    try:
        from ..import_mu.flag_preview import (
            register_flag_previews,
            sync_flags_from_gamedata,
        )
        register_flag_previews()
        sync_flags_from_gamedata()
    except Exception:
        pass
    try:
        from ..import_mu.sound_preview import register_sfx_handlers
        register_sfx_handlers()
    except Exception:
        pass
    # Undo/redo: suppress variant RNA updates that crash on freed IDs
    for hlist, fn in (
        (bpy.app.handlers.undo_pre, _undo_pre),
        (bpy.app.handlers.undo_post, _undo_post),
        (bpy.app.handlers.redo_pre, _undo_pre),
        (bpy.app.handlers.redo_post, _undo_post),
    ):
        try:
            if fn not in hlist:
                hlist.append(fn)
        except Exception:
            pass


def unregister():
    for hlist, fn in (
        (bpy.app.handlers.undo_pre, _undo_pre),
        (bpy.app.handlers.undo_post, _undo_post),
        (bpy.app.handlers.redo_pre, _undo_pre),
        (bpy.app.handlers.redo_post, _undo_post),
    ):
        try:
            while fn in hlist:
                hlist.remove(fn)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "mu_preview_clip"):
        del bpy.types.Scene.mu_preview_clip
    if hasattr(bpy.types.Scene, "mu_animations_off"):
        del bpy.types.Scene.mu_animations_off
    if hasattr(bpy.types.Scene, "mu_anim_variant_filter"):
        del bpy.types.Scene.mu_anim_variant_filter
    if hasattr(bpy.types.Scene, "mu_suspension_preview"):
        del bpy.types.Scene.mu_suspension_preview
    try:
        from ..import_mu.cfg_store import unregister_cfg_ui
        unregister_cfg_ui()
    except Exception:
        pass
    if hasattr(bpy.types.Scene, "mu_active_variant"):
        del bpy.types.Scene.mu_active_variant
    if hasattr(bpy.types.Scene, "mu_mesh_variant"):
        del bpy.types.Scene.mu_mesh_variant
    for _slot in ("mu_mesh_variant_2", "mu_mesh_variant_3", "mu_mesh_variant_4"):
        if hasattr(bpy.types.Scene, _slot):
            delattr(bpy.types.Scene, _slot)
    if hasattr(bpy.types.Scene, "mu_paint_variant"):
        del bpy.types.Scene.mu_paint_variant
    if hasattr(bpy.types.Scene, "mu_active_flag"):
        del bpy.types.Scene.mu_active_flag
    try:
        from ..import_mu.flag_preview import unregister_flag_previews
        unregister_flag_previews()
    except Exception:
        pass
    try:
        from ..import_mu.sound_preview import unregister_sfx_handlers
        unregister_sfx_handlers()
    except Exception:
        pass


classes_to_register = (
    KSPMU_OT_ToggleColliders,
    KSPMU_OT_ToggleShroudFairing,
    KSPMU_OT_ToggleBroken,
    KSPMU_OT_ToggleBumpPreview,
    KSPMU_OT_ToggleParticlesPreview,
    KSPMU_OT_AddPartVariant,
    KSPMU_OT_RemovePartVariant,
    KSPMU_OT_SavePartCfg,
    KSPMU_OT_SyncAnimSounds,
    KSPMU_OT_AddAnimSound,
    WORKSPACE_PT_mu_options,
)
