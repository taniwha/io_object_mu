# vim:ts=4:et
# <pep8 compliant>
"""Viewport preview of part.cfg EFFECTS/AUDIO tied to .mu animation clips.

Loads WAV/OGG from GameData by filepath (no pack / no OGG conversion).
Timing lives in ``mu_sounds`` JSON on the import root and optional addon
fields ``muSoundTime`` / ``muSoundDuration`` / ``muAnimClip`` inside AUDIO
blocks (ignored by stock KSP).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import bpy

MU_SOUNDS_KEY = "mu_sounds"
SFX_STRIP_PREFIX = "mu_sfx."
MU_SFX_TOKEN_KEY = "mu_sfx_token"

# Effect name → default Unity / NLA clip + placement heuristic
_EFFECT_CLIP_HINTS = {
    "deploy": ("Deploy", "start"),
    "retract": ("Retract", "start"),
    "deployed": ("Deploy", "end"),
    "retracted": ("Retract", "end"),
    "extend": ("Deploy", "start"),
    "extended": ("Deploy", "end"),
}

_sfx_handler_registered = False
_sfx_cleanup_busy = False


def _sfx_token_for_root(root) -> str:
    """Stable per-import-root id used in VSE strip names."""
    try:
        tok = root.get(MU_SFX_TOKEN_KEY)
        if tok:
            return str(tok)
    except Exception:
        pass
    import uuid
    tok = uuid.uuid4().hex[:8]
    try:
        root[MU_SFX_TOKEN_KEY] = tok
    except Exception:
        pass
    return tok


def _strip_token(name: str) -> Optional[str]:
    """``mu_sfx.<token>.…`` → token."""
    if not name or not name.startswith(SFX_STRIP_PREFIX):
        return None
    parts = name.split(".")
    if len(parts) < 3:
        return None
    return parts[1] or None


def live_sfx_tokens(scene=None) -> set:
    out = set()
    scene = scene or getattr(bpy.context, "scene", None)
    try:
        for o in bpy.data.objects:
            try:
                if scene is not None and o.name not in scene.objects:
                    continue
                if o.get(MU_SOUNDS_KEY) and o.get(MU_SFX_TOKEN_KEY):
                    out.add(str(o.get(MU_SFX_TOKEN_KEY)))
            except Exception:
                continue
    except Exception:
        pass
    return out


def live_sfx_strip_names(scene=None) -> set:
    """Strip names still referenced by living import roots (legacy + token)."""
    out = set()
    scene = scene or getattr(bpy.context, "scene", None)
    try:
        for o in bpy.data.objects:
            try:
                if scene is not None and o.name not in scene.objects:
                    continue
                raw = o.get(MU_SOUNDS_KEY)
                if not raw:
                    continue
                data = json.loads(raw) if isinstance(raw, str) else (raw or {})
                for e in data.get("entries") or []:
                    name = e.get("strip")
                    if name:
                        out.add(str(name))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _iter_scene_strips(scene):
    se = getattr(scene, "sequence_editor", None)
    if se is None:
        return []
    strips = getattr(se, "strips", None) or getattr(se, "sequences", None)
    return list(strips) if strips is not None else []


def _remove_strip(se, strips, strip) -> None:
    try:
        strips.remove(strip)
        return
    except Exception:
        pass
    try:
        se.sequences.remove(strip)
    except Exception:
        pass


def _clear_mu_sfx_strips(scene, token: Optional[str] = None):
    """Remove addon sound strips. ``token=None`` clears all ``mu_sfx.*``."""
    se = getattr(scene, "sequence_editor", None)
    if se is None:
        return 0
    strips = getattr(se, "strips", None) or getattr(se, "sequences", None)
    if strips is None:
        return 0
    n = 0
    for s in list(strips):
        name = getattr(s, "name", "") or ""
        if not name.startswith(SFX_STRIP_PREFIX):
            continue
        if token is not None:
            if _strip_token(name) != token:
                continue
        _remove_strip(se, strips, s)
        n += 1
    return n


def cleanup_orphaned_sfx_strips(scene=None) -> int:
    """Drop VSE strips whose import root was deleted (e.g. Delete Hierarchy)."""
    global _sfx_cleanup_busy
    if _sfx_cleanup_busy:
        return 0
    _sfx_cleanup_busy = True
    try:
        scene = scene or bpy.context.scene
        if scene is None:
            return 0
        live_tok = live_sfx_tokens(scene)
        live_names = live_sfx_strip_names(scene)
        se = getattr(scene, "sequence_editor", None)
        if se is None:
            return 0
        strips = getattr(se, "strips", None) or getattr(se, "sequences", None)
        if strips is None:
            return 0
        n = 0
        for s in list(strips):
            name = getattr(s, "name", "") or ""
            if not name.startswith(SFX_STRIP_PREFIX):
                continue
            if name in live_names:
                continue
            tok = _strip_token(name)
            # New naming: mu_sfx.<token>.effect.i — keep while token lives
            if tok and tok in live_tok and name.count(".") >= 3:
                continue
            _remove_strip(se, strips, s)
            n += 1
        if n:
            print(f"INFO: KSP sound cleanup: removed {n} orphaned VSE strip(s)")
        return n
    finally:
        _sfx_cleanup_busy = False


def _on_sfx_depsgraph(scene, depsgraph):
    try:
        cleanup_orphaned_sfx_strips(scene)
    except Exception:
        pass


def register_sfx_handlers():
    global _sfx_handler_registered
    if _sfx_handler_registered:
        return
    if _on_sfx_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_sfx_depsgraph)
    _sfx_handler_registered = True


def unregister_sfx_handlers():
    global _sfx_handler_registered
    try:
        if _on_sfx_depsgraph in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_on_sfx_depsgraph)
    except Exception:
        pass
    _sfx_handler_registered = False


def focus_sequencer_on_sfx(scene=None) -> None:
    """Show strip timeline + waveforms (Preview alone is black for audio-only)."""
    scene = scene or bpy.context.scene
    if scene is None:
        return
    # Ensure waveforms on existing addon strips
    for s in _iter_scene_strips(scene):
        name = getattr(s, "name", "") or ""
        if not name.startswith(SFX_STRIP_PREFIX):
            continue
        for attr in ("show_waveform", "show_waveforms"):
            if hasattr(s, attr):
                try:
                    setattr(s, attr, True)
                except Exception:
                    pass
    try:
        wm = bpy.context.window_manager
    except Exception:
        return
    for window in getattr(wm, "windows", []) or []:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "SEQUENCE_EDITOR":
                continue
            for space in area.spaces:
                if getattr(space, "type", "") != "SEQUENCE_EDITOR":
                    continue
                # Prefer the strip editor; pure PREVIEW is empty for sound-only.
                for vt in ("SEQUENCER_PREVIEW", "SEQUENCER"):
                    try:
                        space.view_type = vt
                        break
                    except Exception:
                        continue
                try:
                    space.show_region_channels = True
                except Exception:
                    pass
                try:
                    # Blender 4+/5: draw waveforms in the strip region
                    if hasattr(space, "show_seconds"):
                        space.show_seconds = False
                except Exception:
                    pass
            region = None
            for r in area.regions:
                if r.type == "WINDOW":
                    region = r
                    break
            if region is None and area.regions:
                region = area.regions[-1]
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.sequencer.view_all()
            except Exception:
                pass


def log_sound_entries(prefix: str, mu_sounds: Optional[Dict[str, Any]]) -> None:
    """Console log for import/export of animation sounds."""
    if not mu_sounds:
        print(f"INFO: {prefix}: no animation sounds")
        return
    entries = list(mu_sounds.get("entries") or [])
    print(f"INFO: {prefix}: {len(entries)} AUDIO entr(y/ies)")
    unresolved = 0
    for e in entries:
        clip = e.get("clip") or "?"
        kind = e.get("kind") or "audio"
        effect = e.get("effect") or "?"
        t = e.get("muSoundTime")
        d = e.get("muSoundDuration")
        resolved = e.get("resolved") or ""
        miss = "" if resolved else " [UNRESOLVED]"
        if not resolved:
            unresolved += 1
        timing = ""
        if t is not None:
            timing = f" t={float(t):.3f}s"
        if d is not None:
            timing += f" dur={float(d):.3f}s"
        print(
            f"INFO: {prefix}:   EFFECTS/{effect} {kind} clip={clip}{timing}{miss}"
        )
    if unresolved:
        print(
            f"WARNING: {prefix}: {unresolved} clip(s) missing under GameData "
            f"(bare names → Squad/Sounds/<name>.wav|.ogg). "
            f"Copy stock sounds into preferences GameData."
        )


def _extract_brace_block(text: str, open_brace_index: int) -> Tuple[int, int]:
    depth = 0
    i = open_brace_index
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return open_brace_index, i + 1
        i += 1
    return open_brace_index, len(text)


def _kv_float(body: str, key: str) -> Optional[float]:
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*([-+0-9.eE]+)\s*$", body, re.M | re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _kv_str(body: str, key: str) -> Optional[str]:
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+)$", body, re.M | re.I)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def _volume_max(body: str) -> Optional[float]:
    """Best-effort max from ``volume = 1 0.7`` style lines."""
    best = None
    for m in re.finditer(r"^\s*volume\s*=\s*(.+)$", body, re.M | re.I):
        parts = m.group(1).strip().split()
        try:
            vals = [float(p) for p in parts]
        except Exception:
            continue
        if not vals:
            continue
        v = vals[-1]
        best = v if best is None else max(best, v)
    return best


def parse_part_animation_sounds(cfg_text: str) -> List[Dict[str, Any]]:
    """Parse EFFECTS { name { AUDIO / AUDIO_LOOP { … } } } into sound entries."""
    if not cfg_text or "EFFECTS" not in cfg_text:
        return []
    out: List[Dict[str, Any]] = []
    # Find EFFECTS { … }
    for em in re.finditer(r"EFFECTS\s*\{", cfg_text, re.I):
        brace = em.end() - 1
        _b0, b1 = _extract_brace_block(cfg_text, brace)
        effects_body = cfg_text[brace + 1:b1 - 1]
        # Child effect blocks: deploy { … }
        pos = 0
        while True:
            m = re.search(r"([A-Za-z_][\w]*)\s*\{", effects_body[pos:])
            if not m:
                break
            name = m.group(1)
            if name.upper() in ("AUDIO", "AUDIO_LOOP", "MODEL", "PARTICLE"):
                pos += m.end()
                continue
            open_at = pos + m.end() - 1
            e0, e1 = _extract_brace_block(effects_body, open_at)
            block = effects_body[e0 + 1:e1 - 1]
            pos = e1
            # AUDIO / AUDIO_LOOP inside effect
            apos = 0
            while True:
                am = re.search(r"(AUDIO_LOOP|AUDIO)\s*\{", block[apos:], re.I)
                if not am:
                    break
                kind = "loop" if am.group(1).upper() == "AUDIO_LOOP" else "audio"
                a_open = apos + am.end() - 1
                a0, a1 = _extract_brace_block(block, a_open)
                abody = block[a0 + 1:a1 - 1]
                apos = a1
                clip = _kv_str(abody, "clip")
                if not clip:
                    continue
                entry = {
                    "effect": name,
                    "kind": kind,
                    "clip": clip,
                    "channel": _kv_str(abody, "channel") or "Ship",
                    "pitch": _kv_float(abody, "pitch"),
                    "volume": _volume_max(abody),
                    "muSoundTime": _kv_float(abody, "muSoundTime"),
                    "muSoundDuration": _kv_float(abody, "muSoundDuration"),
                    "muAnimClip": _kv_str(abody, "muAnimClip"),
                    "user_added": False,
                }
                out.append(entry)
    return out


def _gamedata_roots(mudir: str = "", cfg_path: str = "") -> List[str]:
    roots: List[str] = []

    def _add(p):
        if not p:
            return
        ap = os.path.abspath(p)
        if os.path.isdir(ap) and ap not in roots:
            roots.append(ap)

    try:
        from ..preferences import Preferences
        gd = (Preferences().GameData or "").strip()
        _add(gd)
    except Exception:
        pass
    for start in (cfg_path, mudir):
        cur = os.path.abspath(start or "")
        if os.path.isfile(cur):
            cur = os.path.dirname(cur)
        for _ in range(16):
            if os.path.basename(cur).lower() == "gamedata":
                _add(cur)
                break
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return roots


# basename(lower) → absolute path; filled lazily per GameData root
_sounds_index_by_root: Dict[str, Dict[str, str]] = {}
_AUDIO_EXTS = (".wav", ".ogg", ".flac", ".mp3")


def _index_sounds_under(root: str) -> Dict[str, str]:
    """Map ``sound_jet_deep`` → abs path for files under any ``Sounds`` folder."""
    key = os.path.normcase(os.path.abspath(root))
    cached = _sounds_index_by_root.get(key)
    if cached is not None:
        return cached
    index: Dict[str, str] = {}
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Only scan folders named Sounds (stock + mod convention)
            base = os.path.basename(dirpath)
            if base.lower() != "sounds":
                # Prune deep non-sound trees a bit: still walk, but skip huge
                # binary caches if present
                if base.lower() in ("plugins", "plugindata", "caches", ".git"):
                    dirnames[:] = []
                continue
            for fn in filenames:
                low = fn.lower()
                if not low.endswith(_AUDIO_EXTS):
                    continue
                stem = os.path.splitext(fn)[0]
                sk = stem.lower()
                if sk not in index:
                    index[sk] = os.path.abspath(os.path.join(dirpath, fn))
    except Exception:
        pass
    _sounds_index_by_root[key] = index
    return index


def _candidate_rels(clip: str) -> List[str]:
    """Relative GameData paths to try for a cfg ``clip`` value."""
    clip = (clip or "").strip().strip('"').replace("\\", "/")
    if not clip:
        return []
    has_ext = clip.lower().endswith(_AUDIO_EXTS)
    stems = [clip] if has_ext else [clip + e for e in (".wav", ".ogg", ".flac")]
    out: List[str] = list(stems)
    # Bare KSP names (no slash) live under Squad/Sounds/ by stock convention
    if "/" not in clip:
        bare = os.path.basename(clip)
        bare_stem = os.path.splitext(bare)[0]
        for folder in ("Squad/Sounds", "SquadExpansion/Sounds"):
            if has_ext:
                out.append(f"{folder}/{bare}")
            else:
                for e in (".wav", ".ogg", ".flac"):
                    out.append(f"{folder}/{bare_stem}{e}")
    return out


def resolve_sound_path(
    clip: str,
    *,
    mudir: str = "",
    cfg_path: str = "",
) -> Optional[str]:
    """Resolve cfg clip to absolute .wav/.ogg path.

    Accepts ``Squad/Sounds/elev_start`` or bare KSP names like ``sound_jet_deep``
    (looked up under ``*/Sounds/`` in GameData).
    """
    if not clip:
        return None
    clip = clip.strip().strip('"').replace("\\", "/")
    if os.path.isfile(clip):
        return os.path.abspath(clip)

    candidates_rel = _candidate_rels(clip)
    for root in _gamedata_roots(mudir, cfg_path):
        for rel in candidates_rel:
            p = os.path.join(root, rel.replace("/", os.sep))
            if os.path.isfile(p):
                return os.path.abspath(p)
        # Indexed fallback: any Sounds/<basename> under this GameData
        stem = os.path.splitext(os.path.basename(clip))[0].lower()
        hit = _index_sounds_under(root).get(stem)
        if hit and os.path.isfile(hit):
            return hit

    # Beside cfg / mudir
    bare = os.path.basename(clip)
    bare_stem = os.path.splitext(bare)[0]
    local_names = (
        [bare]
        if bare.lower().endswith(_AUDIO_EXTS)
        else [bare_stem + e for e in (".wav", ".ogg", ".flac")]
    )
    for folder in (mudir, os.path.dirname(cfg_path) if cfg_path else ""):
        if not folder:
            continue
        for name in local_names:
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                return os.path.abspath(p)

    # Addon-bundled stock (Unity sharedassets clips not present in GameData)
    try:
        from ..stock_assets import resolve_bundled_sound
        hit = resolve_bundled_sound(clip)
        if hit:
            return hit
    except Exception:
        pass
    return None


def clip_url_for_cfg(abs_path: str, mudir: str = "", cfg_path: str = "") -> str:
    """GameData-relative URL without extension when possible."""
    if not abs_path:
        return ""
    ap = os.path.abspath(abs_path)
    for root in _gamedata_roots(mudir, cfg_path):
        try:
            rel = os.path.relpath(ap, root).replace("\\", "/")
            if not rel.startswith(".."):
                return os.path.splitext(rel)[0]
        except Exception:
            pass
    return os.path.splitext(os.path.basename(ap))[0]


def _scene_fps(scene=None) -> float:
    try:
        sc = scene or bpy.context.scene
        return float(sc.render.fps) / float(sc.render.fps_base or 1.0)
    except Exception:
        return 24.0


def _find_nla_strip_by_clip(root, clip_name: str):
    """Return (obj, nla_strip) for first NLA strip matching Unity clip name."""
    want = (clip_name or "").strip().lower()
    if not want or root is None:
        return None, None
    objs = [root]
    try:
        objs.extend(list(root.children_recursive))
    except Exception:
        pass
    best = None
    for obj in objs:
        ad = getattr(obj, "animation_data", None)
        if ad is None or not ad.nla_tracks:
            continue
        for track in ad.nla_tracks:
            for strip in track.strips:
                names = [
                    (strip.name or ""),
                    (track.name or ""),
                    (strip.action.name if strip.action else ""),
                ]
                try:
                    if strip.action and "mu_clip_name" in strip.action:
                        names.append(str(strip.action["mu_clip_name"]))
                except Exception:
                    pass
                if any(want == (n or "").strip().lower() for n in names):
                    return obj, strip
                if any(want in (n or "").strip().lower() for n in names):
                    best = (obj, strip)
    if best:
        return best
    return None, None


def _infer_anim_clip(entry: Dict[str, Any]) -> Tuple[str, str]:
    """Return (anim_clip_name, placement) placement in {start,end,span}."""
    explicit = (entry.get("muAnimClip") or "").strip()
    effect = (entry.get("effect") or "").strip()
    kind = entry.get("kind") or "audio"
    if explicit:
        placement = "span" if kind == "loop" else "start"
        low = effect.lower()
        if low in ("deployed", "retracted", "extended"):
            placement = "end"
        return explicit, placement
    hint = _EFFECT_CLIP_HINTS.get(effect.lower())
    if hint:
        clip, place = hint
        if kind == "loop" and place == "start":
            return clip, "span"
        return clip, place
    # Fallback: effect name as clip
    if kind == "loop":
        return effect or "Deploy", "span"
    return effect or "Deploy", "start"


def _ensure_sequence_editor(scene):
    if scene.sequence_editor is None:
        scene.sequence_editor_create()
    return scene.sequence_editor


def _sound_length_frames(sound, fps: float) -> float:
    """Best-effort clip length in frames from the Sound datablock."""
    if sound is None or fps <= 1e-9:
        return 0.0
    try:
        length = float(getattr(sound, "length", 0.0) or 0.0)
        if length > 0.01:
            return length * fps
    except Exception:
        pass
    return 0.0


def _add_sound_strip(se, name: str, sound, frame_start: float, frame_end: float):
    strips = getattr(se, "strips", None)
    channel = 1
    try:
        used = {int(getattr(s, "channel", 1) or 1) for s in (strips or [])}
        while channel in used and channel < 32:
            channel += 1
    except Exception:
        channel = 1
    fs = max(1, int(round(frame_start)))
    fe = max(fs + 1, int(round(frame_end)))
    strip = None
    filepath = ""
    try:
        filepath = sound.filepath if sound else ""
    except Exception:
        filepath = ""
    if strips is not None and hasattr(strips, "new_sound"):
        try:
            strip = strips.new_sound(
                name=name,
                filepath=filepath,
                channel=channel,
                frame_start=fs,
            )
        except TypeError:
            try:
                strip = strips.new_sound(name, filepath, channel, fs)
            except Exception:
                strip = None
        except Exception:
            strip = None
    if strip is None:
        seqs = getattr(se, "sequences", None)
        if seqs is not None and hasattr(seqs, "new_sound"):
            try:
                strip = seqs.new_sound(name, filepath, channel, fs)
            except Exception:
                strip = None
    if strip is None:
        return None
    try:
        if sound is not None and getattr(strip, "sound", None) is None:
            strip.sound = sound
    except Exception:
        pass
    try:
        if hasattr(strip, "frame_final_duration"):
            strip.frame_final_duration = max(1, fe - fs)
    except Exception:
        pass
    try:
        strip.name = name
    except Exception:
        pass
    # Waveforms make the Sequencer timeline readable (Preview stays black
    # for audio-only — that is normal).
    for attr in ("show_waveform", "show_waveforms"):
        if hasattr(strip, attr):
            try:
                setattr(strip, attr, True)
            except Exception:
                pass
    return strip


def attach_cfg_animation_sounds(
    root,
    mudir: str,
    muname: str = "",
    filepath_stem: str = None,
    cfg_path: str = None,
) -> int:
    """Parse sibling cfg EFFECTS and place VSE sound strips. Returns strip count."""
    if root is None:
        return 0
    cfg = cfg_path
    if not cfg:
        try:
            cfg = root.get("mu_cfg_path") or ""
        except Exception:
            cfg = ""
    if not cfg or not os.path.isfile(cfg):
        try:
            from .cfg_preview import _find_part_cfg
            cfg = _find_part_cfg(mudir, muname, filepath_stem=filepath_stem)
        except Exception:
            cfg = None
    if not cfg or not os.path.isfile(cfg):
        print("INFO: KSP sound import: no sibling part.cfg — skip")
        return 0
    try:
        text = open(cfg, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return 0
    entries = parse_part_animation_sounds(text)
    if not entries:
        print(f"INFO: KSP sound import: no EFFECTS/AUDIO in {cfg}")
        return 0

    scene = bpy.context.scene
    fps = _scene_fps(scene)
    token = _sfx_token_for_root(root)
    # Stamp early so depsgraph orphan-cleanup does not delete strips mid-attach.
    try:
        if not root.get(MU_SOUNDS_KEY):
            root[MU_SOUNDS_KEY] = json.dumps({"entries": [], "token": token})
    except Exception:
        pass
    _ensure_sequence_editor(scene)
    se = scene.sequence_editor
    _clear_mu_sfx_strips(scene, token=token)

    stored: List[Dict[str, Any]] = []
    n_strips = 0
    for i, entry in enumerate(entries):
        abs_path = resolve_sound_path(entry["clip"], mudir=mudir, cfg_path=cfg)
        if not abs_path:
            entry = dict(entry)
            entry["resolved"] = None
            entry["index"] = i
            stored.append(entry)
            continue
        try:
            sound = bpy.data.sounds.load(abs_path, check_existing=True)
        except Exception:
            entry = dict(entry)
            entry["resolved"] = abs_path
            entry["index"] = i
            stored.append(entry)
            continue

        anim_clip, placement = _infer_anim_clip(entry)
        _obj, nla = _find_nla_strip_by_clip(root, anim_clip)
        if nla is not None:
            nla_start = float(nla.frame_start)
            nla_end = float(nla.frame_end)
        else:
            nla_start = float(scene.frame_start)
            nla_end = nla_start + fps

        if entry.get("muSoundTime") is not None:
            frame_start = nla_start + float(entry["muSoundTime"]) * fps
        elif placement == "end":
            frame_start = nla_end - 1.0
        else:
            frame_start = nla_start

        snd_frames = _sound_length_frames(sound, fps)
        if entry.get("muSoundDuration") is not None:
            frame_end = frame_start + float(entry["muSoundDuration"]) * fps
        elif placement == "span" or entry.get("kind") == "loop":
            frame_end = max(nla_end, frame_start + max(snd_frames, 1.0))
        elif snd_frames > 1.0:
            frame_end = frame_start + snd_frames
        else:
            frame_end = frame_start + max(0.25 * fps, 1.0)

        effect = entry.get("effect") or "fx"
        strip_name = f"{SFX_STRIP_PREFIX}{token}.{effect}.{i}"
        strip = _add_sound_strip(se, strip_name, sound, frame_start, frame_end)
        if strip is not None:
            n_strips += 1
            try:
                if entry.get("volume") is not None and hasattr(strip, "volume"):
                    strip.volume = float(entry["volume"])
            except Exception:
                pass
            try:
                if entry.get("pitch") is not None and hasattr(strip, "pitch"):
                    strip.pitch = float(entry["pitch"])
            except Exception:
                pass

        rec = dict(entry)
        rec["index"] = i
        rec["resolved"] = abs_path
        rec["muAnimClip"] = anim_clip
        if rec.get("muSoundTime") is None:
            rec["muSoundTime"] = max(0.0, (frame_start - nla_start) / fps)
        if rec.get("muSoundDuration") is None:
            rec["muSoundDuration"] = max(0.01, (frame_end - frame_start) / fps)
        rec["strip"] = strip_name
        stored.append(rec)

    payload = {"entries": stored, "cfg": cfg, "token": token}
    try:
        root[MU_SOUNDS_KEY] = json.dumps(payload)
        root["mu_cfg_path"] = cfg
        if mudir:
            root["mu_dirname"] = mudir
    except Exception:
        pass

    # Frame range covers strips; show waveforms in Sequencer timeline.
    try:
        if n_strips:
            all_s = [
                s for s in _iter_scene_strips(scene)
                if (s.name or "").startswith(f"{SFX_STRIP_PREFIX}{token}.")
            ]
            if all_s:
                fs = min(
                    float(getattr(s, "frame_final_start", s.frame_start))
                    for s in all_s
                )
                fe = max(
                    float(
                        getattr(
                            s,
                            "frame_final_end",
                            float(s.frame_start) + 10,
                        )
                    )
                    for s in all_s
                )
                scene.frame_start = max(1, int(fs) - 2)
                scene.frame_end = max(scene.frame_start + 10, int(fe) + 5)
                scene.frame_current = scene.frame_start
            focus_sequencer_on_sfx(scene)
    except Exception:
        pass

    log_sound_entries("KSP sound import", payload)
    print(
        f"INFO: KSP sound import: attached {n_strips} VSE strip(s) "
        f"(token={token}, cfg={os.path.basename(cfg)})"
    )
    return n_strips


def flush_sounds_from_vse(root, scene=None) -> Dict[str, Any]:
    """Update ``mu_sounds`` timing from current VSE strip positions."""
    if root is None:
        return {}
    try:
        raw = root.get(MU_SOUNDS_KEY)
        data = json.loads(raw) if raw else {"entries": []}
    except Exception:
        data = {"entries": []}
    entries = list(data.get("entries") or [])
    scene = scene or bpy.context.scene
    fps = _scene_fps(scene)
    se = getattr(scene, "sequence_editor", None)
    strips = []
    if se is not None:
        strips = list(getattr(se, "strips", None) or getattr(se, "sequences", None) or [])
    by_name = {(s.name or ""): s for s in strips}

    for entry in entries:
        name = entry.get("strip") or ""
        strip = by_name.get(name)
        if strip is None:
            continue
        anim_clip = entry.get("muAnimClip") or _infer_anim_clip(entry)[0]
        _obj, nla = _find_nla_strip_by_clip(root, anim_clip)
        nla_start = float(nla.frame_start) if nla is not None else float(scene.frame_start)
        try:
            fs = float(getattr(strip, "frame_final_start", None) or strip.frame_start)
        except Exception:
            fs = float(strip.frame_start)
        try:
            fe = float(getattr(strip, "frame_final_end", None) or (fs + strip.frame_final_duration))
        except Exception:
            fe = fs + fps
        entry["muSoundTime"] = max(0.0, (fs - nla_start) / fps)
        entry["muSoundDuration"] = max(0.01, (fe - fs) / fps)
        entry["muAnimClip"] = anim_clip

    data["entries"] = entries
    try:
        root[MU_SOUNDS_KEY] = json.dumps(data)
    except Exception:
        pass
    return data


def add_sound_entry(
    root,
    abs_path: str,
    *,
    effect: str = "deploy",
    kind: str = "audio",
    mu_anim_clip: str = "",
    mu_sound_time: float = 0.0,
    mu_sound_duration: float = 1.0,
    mudir: str = "",
) -> Dict[str, Any]:
    """Append a user-added sound to ``mu_sounds`` and create a VSE strip."""
    if root is None or not abs_path or not os.path.isfile(abs_path):
        raise ValueError("missing sound file")
    cfg = ""
    try:
        cfg = root.get("mu_cfg_path") or ""
        mudir = mudir or root.get("mu_dirname") or os.path.dirname(cfg)
    except Exception:
        pass
    clip_url = clip_url_for_cfg(abs_path, mudir=mudir, cfg_path=cfg)
    token = _sfx_token_for_root(root)
    data = flush_sounds_from_vse(root)
    entries = list(data.get("entries") or [])
    idx = len(entries)
    anim = (mu_anim_clip or "").strip()
    if not anim:
        anim = _EFFECT_CLIP_HINTS.get(effect.lower(), (effect or "Deploy", "start"))[0]
    strip_name = f"{SFX_STRIP_PREFIX}{token}.{effect or 'deploy'}.{idx}"
    entry = {
        "effect": effect or "deploy",
        "kind": kind if kind in ("audio", "loop") else "audio",
        "clip": clip_url,
        "channel": "Ship",
        "pitch": None,
        "volume": None,
        "muSoundTime": float(mu_sound_time),
        "muSoundDuration": float(mu_sound_duration),
        "muAnimClip": anim,
        "user_added": True,
        "index": idx,
        "resolved": os.path.abspath(abs_path),
        "strip": strip_name,
    }
    scene = bpy.context.scene
    fps = _scene_fps(scene)
    se = _ensure_sequence_editor(scene)
    sound = bpy.data.sounds.load(abs_path, check_existing=True)
    _obj, nla = _find_nla_strip_by_clip(root, anim)
    nla_start = float(nla.frame_start) if nla is not None else float(scene.frame_start)
    fs = nla_start + float(mu_sound_time) * fps
    fe = fs + float(mu_sound_duration) * fps
    strip = _add_sound_strip(se, entry["strip"], sound, fs, fe)
    if strip is None:
        raise RuntimeError("could not create SoundStrip")
    entries.append(entry)
    data["entries"] = entries
    data["cfg"] = cfg
    data["token"] = token
    root[MU_SOUNDS_KEY] = json.dumps(data)
    print(
        f"INFO: KSP sound add: EFFECTS/{entry['effect']} {entry['kind']} "
        f"clip={entry['clip']} strip={strip_name}"
    )
    return entry
