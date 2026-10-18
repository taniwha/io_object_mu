# vim:ts=4:et
# <pep8 compliant>
"""Embed the source UnityFS (.ksp) into the .blend for portable export.

Stores zlib-compressed base64 in a Text datablock (saved with the .blend).
Export can patch from the embed when the external ``source_path`` file is missing.

Hot paths (panel ``draw``) must only use cheap flag/name/header peeks —
never ``Text.as_string()`` on multi-MB payloads.
"""

from __future__ import annotations

import base64
import os
import tempfile
import zlib
from typing import Optional, Tuple

import bpy

# Marker stored on kb.source_path when only the embed is available.
INTERNAL_SOURCE = "<internal>"

_HEADER_V1 = "io_object_mu_ksp_source_v1"
_HEADER_V2 = "io_object_mu_ksp_source_v2"
_HEADERS = (_HEADER_V1, _HEADER_V2)
# One giant TextLine (old chunked write without newlines) freezes Blender,
# especially on an unsaved .blend where undo snapshots the whole line.
_LINE = 1024


def _sanitize_name(s: str) -> str:
    out = []
    for ch in (s or ""):
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:56] or "anon"


def embed_text_name_for(kb, root=None) -> str:
    try:
        existing = (getattr(kb, "embedded_source_text", "") or "").strip()
        if existing:
            return existing
    except Exception:
        pass
    base = ""
    try:
        if root is not None and getattr(root, "name", ""):
            base = "io_object_mu_ksp_embed__%s" % _sanitize_name(root.name)
    except Exception:
        base = ""
    if not base:
        try:
            scope = ""
            try:
                scope = str(kb.get("import_scope", "") or "")
            except Exception:
                scope = ""
            bn = scope or getattr(kb, "bundle_name", "") or ""
            if bn:
                base = "io_object_mu_ksp_embed__%s" % _sanitize_name(bn)
        except Exception:
            base = ""
    if not base:
        base = "io_object_mu_ksp_embed__anon"
    # Second import of the same stem must not share / overwrite the first
    # PACKAGE Text datablock.
    if base not in bpy.data.texts:
        return base
    # Reuse only when this kb already owns it (re-embed / update).
    try:
        if (getattr(kb, "embedded_source_text", "") or "").strip() == base:
            return base
    except Exception:
        pass
    n = 1
    while ("%s.%03d" % (base, n)) in bpy.data.texts:
        n += 1
    return "%s.%03d" % (base, n)


def _text_header_line(text) -> str:
    """First line body only — cheap, no full datablock string."""
    try:
        lines = text.lines
        if not lines:
            return ""
        return (lines[0].body or "").strip()
    except Exception:
        return ""


def _header_ok(first_line: str) -> bool:
    if not first_line:
        return False
    for h in _HEADERS:
        if first_line.startswith(h):
            return True
    return False


def has_embedded_source(kb) -> bool:
    """Cheap presence check — safe for panel draw (no full Text read)."""
    if kb is None:
        return False
    try:
        if not getattr(kb, "source_embedded", False):
            return False
    except Exception:
        return False
    tname = ""
    try:
        tname = (getattr(kb, "embedded_source_text", "") or "").strip()
    except Exception:
        tname = ""
    if not tname or tname not in bpy.data.texts:
        return False
    try:
        return _header_ok(_text_header_line(bpy.data.texts[tname]))
    except Exception:
        return False


def source_is_internal(kb) -> bool:
    """True when export must use the embed (no usable external file)."""
    if not has_embedded_source(kb):
        return False
    src = ""
    try:
        src = (getattr(kb, "source_path", "") or "").strip()
    except Exception:
        src = ""
    if not src or src == INTERNAL_SOURCE:
        return True
    try:
        return not os.path.isfile(src)
    except Exception:
        return True


def source_display_label(kb) -> str:
    if source_is_internal(kb):
        return "Internal (embedded)"
    try:
        src = (getattr(kb, "source_path", "") or "").strip()
    except Exception:
        src = ""
    if src and src != INTERNAL_SOURCE:
        if has_embedded_source(kb):
            return "%s (+ embedded)" % os.path.basename(src)
        return src
    if has_embedded_source(kb):
        return "Internal (embedded)"
    return "(none)"


def _iter_payload_b64(text):
    """Yield base64 payload lines without building one giant string first."""
    try:
        lines = text.lines
    except Exception:
        return
    # Skip header (line 0) and comment / blank lines.
    for i in range(1, len(lines)):
        try:
            s = (lines[i].body or "").strip()
        except Exception:
            continue
        if not s or s.startswith("#"):
            continue
        yield s


def _peek_meta(text) -> Tuple[str, bool]:
    """Return (original_name, use_zlib) from comment lines near the header."""
    name = ""
    use_zlib = False
    first = _text_header_line(text)
    if first.startswith(_HEADER_V2):
        use_zlib = True
    try:
        lines = text.lines
        for i in range(1, min(8, len(lines))):
            line = (lines[i].body or "").strip()
            if line.startswith("# original_name:"):
                raw = line.split(":", 1)[1].strip()
                if raw:
                    name = os.path.basename(raw)
            elif line.startswith("# encoding:"):
                enc = line.split(":", 1)[1].strip().lower()
                if "zlib" in enc:
                    use_zlib = True
    except Exception:
        pass
    return name, use_zlib


def read_embedded_bytes(kb) -> Optional[bytes]:
    """Decode embed for export/materialize only — not for draw()."""
    if not has_embedded_source(kb):
        return None
    tname = (getattr(kb, "embedded_source_text", "") or "").strip()
    try:
        text = bpy.data.texts[tname]
    except Exception:
        return None
    _name, use_zlib = _peek_meta(text)
    parts = list(_iter_payload_b64(text))
    if not parts:
        return None
    try:
        raw = base64.b64decode("".join(parts), validate=False)
    except Exception:
        return None
    if use_zlib:
        try:
            raw = zlib.decompress(raw)
        except Exception:
            return None
    return raw


def embed_source_bytes(kb, data: bytes, *, root=None, original_name: str = "") -> bool:
    """Write UnityFS bytes into a Text datablock linked from kb (zlib+base64).

    Payload is many short lines (not one multi-MB line) so Blender does not
    freeze on Text RNA / undo.  The datablock lives in RAM until the .blend
    is saved — no on-disk .blend is required to embed.
    """
    if kb is None or not data:
        return False
    if not data.startswith(b"UnityFS"):
        return False
    tname = embed_text_name_for(kb, root)
    name = original_name or os.path.basename(
        (getattr(kb, "source_path", "") or "").strip()
    ) or "bundle.ksp"
    try:
        compressed = zlib.compress(data, 6)
    except Exception:
        return False
    header = (
        "%s\n"
        "# encoding: zlib+base64\n"
        "# original_name: %s\n"
        "# size: %d\n"
        "# compressed: %d\n"
        % (_HEADER_V2, name.replace("\n", " "), len(data), len(compressed))
    )
    b64 = base64.b64encode(compressed).decode("ascii")
    chunks = [header]
    for i in range(0, len(b64), _LINE):
        chunks.append(b64[i : i + _LINE])
        chunks.append("\n")
    payload = "".join(chunks)
    try:
        if tname in bpy.data.texts:
            block = bpy.data.texts[tname]
        else:
            block = bpy.data.texts.new(tname)
        if hasattr(block, "from_string"):
            block.from_string(payload)
        else:
            block.clear()
            block.write(payload)
        kb.embedded_source_text = tname
        kb.source_embedded = True
        return True
    except Exception:
        return False


def embed_source_from_path(kb, filepath: str, *, root=None) -> bool:
    path = (filepath or "").strip()
    if not path or path == INTERNAL_SOURCE:
        return False
    try:
        path = os.path.abspath(path)
    except Exception:
        return False
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return False
    ok = embed_source_bytes(
        kb, data, root=root, original_name=os.path.basename(path)
    )
    if ok:
        try:
            # Keep real path while the file exists; UI falls back to Internal
            # when the path is later missing.
            if (getattr(kb, "source_path", "") or "").strip() in ("", INTERNAL_SOURCE):
                kb.source_path = path
        except Exception:
            pass
    return ok


def clear_embedded_source(kb) -> None:
    if kb is None:
        return
    tname = ""
    try:
        tname = (getattr(kb, "embedded_source_text", "") or "").strip()
    except Exception:
        tname = ""
    try:
        kb.source_embedded = False
        kb.embedded_source_text = ""
    except Exception:
        pass
    if tname and tname in bpy.data.texts:
        try:
            bpy.data.texts.remove(bpy.data.texts[tname])
        except Exception:
            pass


def materialize_to_temp(kb) -> Optional[str]:
    """Write embed to a temp .ksp file. Caller should delete the path."""
    data = read_embedded_bytes(kb)
    if not data:
        return None
    name = "ksp_embed_template.ksp"
    try:
        tname = (getattr(kb, "embedded_source_text", "") or "").strip()
        if tname and tname in bpy.data.texts:
            peeked, _ = _peek_meta(bpy.data.texts[tname])
            if peeked:
                name = peeked or name
    except Exception:
        pass
    try:
        fd, tmp = tempfile.mkstemp(suffix=".ksp", prefix="ksp_embed_")
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        # Prefer a basename closer to the original for UnityFS tooling.
        dest = os.path.join(os.path.dirname(tmp), name)
        if dest != tmp:
            try:
                if os.path.isfile(dest):
                    os.remove(dest)
                os.replace(tmp, dest)
                return dest
            except Exception:
                return tmp
        return tmp
    except Exception:
        return None


def resolve_export_source(
    kb, template_path: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], bool]:
    """Pick template path for export.

    Returns (path, temp_to_cleanup_or_None, from_embed).
    """
    src = template_path or None
    if not src:
        try:
            src = (getattr(kb, "template_path", "") or "").strip() or None
        except Exception:
            src = None
    if not src:
        try:
            src = (getattr(kb, "source_path", "") or "").strip() or None
        except Exception:
            src = None
    if src == INTERNAL_SOURCE:
        src = None
    if src and os.path.isfile(src):
        return src, None, False
    if getattr(kb, "is_sample_template", False):
        try:
            from .fonts_util import template_ksp_path
            sample = template_ksp_path()
            if sample and os.path.isfile(sample):
                return sample, None, False
        except Exception:
            pass
    if has_embedded_source(kb):
        tmp = materialize_to_temp(kb)
        if tmp and os.path.isfile(tmp):
            return tmp, tmp, True
    return None, None, False
