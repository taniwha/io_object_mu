# vim:ts=4:et
# <pep8 compliant>
"""Patch part.cfg EFFECTS/AUDIO from ``mu_sounds`` JSON (Blender round-trip)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


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


def _format_audio_block(entry: Dict[str, Any], indent: str = "\t\t\t") -> str:
    kind = entry.get("kind") or "audio"
    header = "AUDIO_LOOP" if kind == "loop" else "AUDIO"
    lines = [f"{indent}{header}", f"{indent}{{"]
    inner = indent + "\t"
    channel = entry.get("channel") or "Ship"
    lines.append(f"{inner}channel = {channel}")
    clip = entry.get("clip") or ""
    if clip:
        lines.append(f"{inner}clip = {clip}")
    if entry.get("pitch") is not None:
        try:
            lines.append(f"{inner}pitch = {float(entry['pitch']):g}")
        except Exception:
            pass
    vol = entry.get("volume")
    if vol is not None:
        try:
            v = float(vol)
            lines.append(f"{inner}volume = 0 0")
            lines.append(f"{inner}volume = 1 {v:g}")
        except Exception:
            pass
    if entry.get("muSoundTime") is not None:
        try:
            lines.append(f"{inner}muSoundTime = {float(entry['muSoundTime']):.6g}")
        except Exception:
            pass
    if entry.get("muSoundDuration") is not None:
        try:
            lines.append(f"{inner}muSoundDuration = {float(entry['muSoundDuration']):.6g}")
        except Exception:
            pass
    if entry.get("muAnimClip"):
        lines.append(f"{inner}muAnimClip = {entry['muAnimClip']}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def _set_or_insert_kv(body: str, key: str, value: str) -> str:
    """Replace ``key = …`` in a brace body or insert before closing."""
    pat = re.compile(rf"^(\s*){re.escape(key)}\s*=\s*.*$", re.M | re.I)
    if pat.search(body):
        return pat.sub(rf"\1{key} = {value}", body, count=1)
    # Indent like sibling lines
    indent = "\t\t\t\t"
    m = re.search(r"^(\s+)\S", body, re.M)
    if m:
        indent = m.group(1)
    return body.rstrip() + f"\n{indent}{key} = {value}\n"


def _patch_existing_audio_body(abody: str, entry: Dict[str, Any]) -> str:
    body = abody
    if entry.get("clip"):
        body = _set_or_insert_kv(body, "clip", str(entry["clip"]))
    if entry.get("muSoundTime") is not None:
        body = _set_or_insert_kv(body, "muSoundTime", f"{float(entry['muSoundTime']):.6g}")
    if entry.get("muSoundDuration") is not None:
        body = _set_or_insert_kv(
            body, "muSoundDuration", f"{float(entry['muSoundDuration']):.6g}"
        )
    if entry.get("muAnimClip"):
        body = _set_or_insert_kv(body, "muAnimClip", str(entry["muAnimClip"]))
    return body


def _find_effects_span(cfg_text: str) -> Optional[Tuple[int, int, int]]:
    """Return (keyword_start, brace_open, brace_end_exclusive) for EFFECTS."""
    m = re.search(r"EFFECTS\s*\{", cfg_text, re.I)
    if not m:
        return None
    brace = m.end() - 1
    _b0, b1 = _extract_brace_block(cfg_text, brace)
    start = m.start()
    while start > 0 and cfg_text[start - 1] in (" ", "\t"):
        start -= 1
    return start, brace, b1


def patch_cfg_with_sounds(cfg_text: str, mu_sounds: Dict[str, Any]) -> str:
    """Upsert EFFECTS AUDIO blocks from ``mu_sounds`` dict.

    Existing AUDIO entries matched by (effect, clip) get muSound* fields
    updated. User-added entries without a match are appended under their
    effect (creating the effect / EFFECTS block if needed).
    """
    if not mu_sounds:
        return cfg_text or ""
    entries: List[Dict[str, Any]] = list(mu_sounds.get("entries") or [])
    if not entries:
        return cfg_text or ""
    print(f"INFO: KSP sound export: patching {len(entries)} AUDIO entr(y/ies) into part.cfg")
    for e in entries:
        effect = e.get("effect") or "?"
        kind = e.get("kind") or "audio"
        clip = e.get("clip") or "?"
        t = e.get("muSoundTime")
        d = e.get("muSoundDuration")
        timing = ""
        if t is not None:
            timing = f" t={float(t):.3f}s"
        if d is not None:
            timing += f" dur={float(d):.3f}s"
        print(f"INFO: KSP sound export:   EFFECTS/{effect} {kind} clip={clip}{timing}")
    text = cfg_text or ""

    # Match existing AUDIO blocks: walk EFFECTS and patch by order / clip
    span = _find_effects_span(text)
    if span is None:
        # Create EFFECTS at end of PART
        effects_lines = ["\tEFFECTS", "\t{"]
        by_effect: Dict[str, List[Dict[str, Any]]] = {}
        for e in entries:
            by_effect.setdefault(e.get("effect") or "deploy", []).append(e)
        for effect, elist in by_effect.items():
            effects_lines.append(f"\t\t{effect}")
            effects_lines.append("\t\t{")
            for e in elist:
                effects_lines.append(_format_audio_block(e, indent="\t\t\t"))
            effects_lines.append("\t\t}")
        effects_lines.append("\t}")
        block = "\n".join(effects_lines) + "\n"
        part_m = re.search(r"PART\s*\{", text, re.I)
        if part_m:
            brace = part_m.end() - 1
            _b0, b1 = _extract_brace_block(text, brace)
            insert_at = b1 - 1
            while insert_at > 0 and text[insert_at - 1] in (" ", "\t", "\r", "\n"):
                insert_at -= 1
            return text[:insert_at] + "\n" + block + text[insert_at:]
        return text.rstrip() + "\n" + block

    _start, brace, b1 = span
    effects_body = text[brace + 1:b1 - 1]
    # Build list of (effect_name, audio_kind, abs_start, abs_end, body) for AUDIO blocks
    # Coordinates relative to full text
    audio_spans = []  # (effect, kind, full_start, full_end, body_inner)
    pos = 0
    while True:
        m = re.search(r"([A-Za-z_][\w]*)\s*\{", effects_body[pos:])
        if not m:
            break
        name = m.group(1)
        if name.upper() in ("AUDIO", "AUDIO_LOOP"):
            pos += m.end()
            continue
        open_at = pos + m.end() - 1
        e0, e1 = _extract_brace_block(effects_body, open_at)
        block = effects_body[e0 + 1:e1 - 1]
        # Absolute offset of effect body start in full text
        effect_body_abs = brace + 1 + e0 + 1
        apos = 0
        while True:
            am = re.search(r"(AUDIO_LOOP|AUDIO)\s*\{", block[apos:], re.I)
            if not am:
                break
            kind = "loop" if am.group(1).upper() == "AUDIO_LOOP" else "audio"
            a_open = apos + am.end() - 1
            a0, a1 = _extract_brace_block(block, a_open)
            # Include AUDIO keyword
            key_start = apos + am.start()
            # Expand to line start within block
            while key_start > 0 and block[key_start - 1] in (" ", "\t"):
                key_start -= 1
            full_start = effect_body_abs + key_start
            full_end = effect_body_abs + a1
            abody = block[a0 + 1:a1 - 1]
            audio_spans.append((name, kind, full_start, full_end, abody))
            apos = a1
        pos = e1

    # Match entries to spans: prefer index order within same effect+kind+clip
    used_spans = set()
    replacements = []  # (start, end, new_text)
    unmatched = []

    def _clip_of(body: str) -> str:
        m = re.search(r"^\s*clip\s*=\s*(.+)$", body, re.M | re.I)
        return (m.group(1).strip().strip('"') if m else "").replace("\\", "/")

    for entry in entries:
        effect = (entry.get("effect") or "").strip()
        kind = entry.get("kind") or "audio"
        clip = (entry.get("clip") or "").replace("\\", "/")
        clip_base = clip
        if clip_base.lower().endswith((".wav", ".ogg", ".flac")):
            clip_base = clip_base.rsplit(".", 1)[0]
        matched = None
        for i, (ename, ekind, s, e, body) in enumerate(audio_spans):
            if i in used_spans:
                continue
            if ename.lower() != effect.lower():
                continue
            if ekind != kind:
                continue
            bclip = _clip_of(body)
            bbase = bclip.rsplit(".", 1)[0] if bclip.lower().endswith(
                (".wav", ".ogg", ".flac")
            ) else bclip
            if clip and bbase and clip_base.lower() != bbase.lower():
                # Still allow match if one is suffix of the other
                if clip_base.lower() not in bbase.lower() and bbase.lower() not in clip_base.lower():
                    continue
            matched = i
            break
        if matched is None and entry.get("user_added"):
            unmatched.append(entry)
            continue
        if matched is None:
            # Fall back: first same effect+kind
            for i, (ename, ekind, s, e, body) in enumerate(audio_spans):
                if i in used_spans:
                    continue
                if ename.lower() == effect.lower() and ekind == kind:
                    matched = i
                    break
        if matched is None:
            unmatched.append(entry)
            continue
        used_spans.add(matched)
        ename, ekind, s, e, body = audio_spans[matched]
        new_body = _patch_existing_audio_body(body, entry)
        # Rebuild full AUDIO block keeping original header/indent
        old = text[s:e]
        hm = re.match(r"(\s*)(AUDIO_LOOP|AUDIO)\s*\{", old, re.I)
        indent = hm.group(1) if hm else "\t\t\t"
        header = hm.group(2) if hm else ("AUDIO_LOOP" if kind == "loop" else "AUDIO")
        new_block = f"{indent}{header}\n{indent}{{{new_body}\n{indent}}}"
        replacements.append((s, e, new_block))

    # Apply replacements from end to start
    for s, e, new_block in sorted(replacements, key=lambda x: x[0], reverse=True):
        text = text[:s] + new_block + text[e:]

    if not unmatched:
        return text

    # Re-find EFFECTS after edits
    span2 = _find_effects_span(text)
    if span2 is None:
        return text
    _s2, brace2, b1_2 = span2
    effects_body2 = text[brace2 + 1:b1_2 - 1]

    # Group unmatched by effect; append into existing effect or create
    by_effect: Dict[str, List[Dict[str, Any]]] = {}
    for e in unmatched:
        by_effect.setdefault(e.get("effect") or "deploy", []).append(e)

    insert_chunks = []
    for effect, elist in by_effect.items():
        # Find effect block
        em = re.search(rf"(^\s*){re.escape(effect)}\s*\{{", effects_body2, re.M | re.I)
        audio_txt = "\n".join(_format_audio_block(e, indent="\t\t\t") for e in elist)
        if em:
            open_at = em.end() - 1
            e0, e1 = _extract_brace_block(effects_body2, open_at)
            # Insert before effect closing brace
            abs_close = brace2 + 1 + e1 - 1
            insert_chunks.append((abs_close, "\n" + audio_txt + "\n"))
        else:
            # New effect before EFFECTS close
            chunk = f"\n\t\t{effect}\n\t\t{{\n{audio_txt}\n\t\t}}\n"
            insert_chunks.append((b1_2 - 1, chunk))

    for pos, chunk in sorted(insert_chunks, key=lambda x: x[0], reverse=True):
        text = text[:pos] + chunk + text[pos:]
    return text
