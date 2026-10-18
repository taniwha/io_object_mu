# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

"""UnityFS (.ksp / .lang) snapshot unpack + compare (disk or RAM).

Used by import/export verification and SMOKE_KSP_IMPORT_EXPORT.
"""
from __future__ import annotations

import hashlib
import html as _html
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _ensure_unitypy():
    try:
        import UnityPy  # noqa: F401
        return
    except ImportError:
        pass
    here = Path(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        here.parent.parent / "modules",
    ]
    for p in candidates:
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import UnityPy  # noqa: F401


def _safe_name(name: str, fallback: str = "unnamed") -> str:
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = s.strip(" .") or fallback
    return s[:180]


def _textasset_bytes(data) -> Tuple[str, bytes]:
    name = getattr(data, "m_Name", None) or getattr(data, "name", "") or "TextAsset"
    raw = getattr(data, "m_Script", None)
    if raw is None:
        raw = getattr(data, "script", None)
    if raw is None:
        raw = b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    elif not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
    return str(name), bytes(raw)


def _go_names(env) -> Dict[int, str]:
    out = {}
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            d = obj.read()
            out[int(obj.path_id)] = str(
                getattr(d, "m_Name", None) or getattr(d, "name", "") or ""
            )
        except Exception:
            continue
    return out


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()



def _norm_xml_mb_text(s: str) -> str:
    """Compare XML Text nodes vs MonoBehaviour m_Text loosely.

    Cosmetic-safe: strip rich-text color/size markup, unwrap whole-string
    ``<b>``/``<i>``, and collapse whitespace/newlines so ST1 space-after-period
    or CO1 linebreak-only diffs do not count as corruption.
    """
    import re
    t = (s or "").strip()
    try:
        for _ in range(2):
            m = re.fullmatch(r"(?is)<(b|i)>(.*)</\1>", t)
            if not m:
                break
            t = (m.group(2) or "").strip()
    except Exception:
        pass
    try:
        # One side may keep TMP/color markup while the other is plain.
        t = re.sub(r"(?is)</?color(?:\s*=\s*[^>]*)?>", "", t)
        t = re.sub(r"(?is)</?size(?:\s*=\s*[^>]*)?>", "", t)
        t = re.sub(r"(?is)</?[bi]>", "", t)
    except Exception:
        pass
    try:
        # Collapse all whitespace runs (spaces, tabs, CR/LF) to a single space.
        t = re.sub(r"\s+", " ", t).strip()
    except Exception:
        pass
    return t


def classify_xml_mb_mismatch(diff: Dict[str, Any]) -> str:
    """Return ``cosmetic`` or ``content`` for an xml_vs_mb mismatch row."""
    if not isinstance(diff, dict):
        return "content"
    if (diff.get("reason") or "") == "missing_mb":
        # Orphan XML node with no MB — usually leftover after delete; soft.
        return "cosmetic"
    a = _norm_xml_mb_text(diff.get("xml_preview") or "")
    b = _norm_xml_mb_text(diff.get("mb_preview") or "")
    if a == b:
        return "cosmetic"
    return "content"


def unpack_env(env, *, source: str = "") -> Dict[str, Any]:
    """Build an in-memory snapshot from a loaded UnityPy env."""
    gos = _go_names(env)
    images: List[Dict[str, Any]] = []
    text_assets: List[Dict[str, Any]] = []
    texts: List[Dict[str, Any]] = []
    xml_texts: List[Dict[str, Any]] = []
    index: List[Dict[str, Any]] = []

    for obj in env.objects:
        tname = obj.type.name
        if tname not in ("Texture2D", "Sprite"):
            continue
        try:
            data = obj.read()
        except Exception as ex:
            index.append(
                {"path_id": int(obj.path_id), "type": tname, "error": str(ex)}
            )
            continue
        name = getattr(data, "m_Name", None) or getattr(data, "name", "") or tname
        try:
            img = data.image
        except Exception:
            img = None
        if img is None:
            index.append(
                {
                    "path_id": int(obj.path_id),
                    "type": tname,
                    "name": name,
                    "exported": False,
                    "reason": "no image",
                }
            )
            continue
        buf = io.BytesIO()
        try:
            img.save(buf, format="PNG")
            png = buf.getvalue()
        except Exception as ex:
            index.append(
                {
                    "path_id": int(obj.path_id),
                    "type": tname,
                    "name": name,
                    "error": str(ex),
                }
            )
            continue
        entry = {
            "path_id": int(obj.path_id),
            "type": tname,
            "name": name,
            "sha1": _sha1(png),
            "bytes": len(png),
            "png": png,
        }
        images.append(entry)
        index.append(
            {
                "path_id": entry["path_id"],
                "type": tname,
                "name": name,
                "sha1": entry["sha1"],
                "bytes": entry["bytes"],
            }
        )

    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        try:
            data = obj.read()
            name, raw = _textasset_bytes(data)
        except Exception as ex:
            index.append(
                {
                    "path_id": int(obj.path_id),
                    "type": "TextAsset",
                    "error": str(ex),
                }
            )
            continue
        text_assets.append(
            {
                "path_id": int(obj.path_id),
                "name": name,
                "sha1": _sha1(raw),
                "bytes": len(raw),
                "raw": raw,
            }
        )
        index.append(
            {
                "path_id": int(obj.path_id),
                "type": "TextAsset",
                "name": name,
                "sha1": _sha1(raw),
                "bytes": len(raw),
            }
        )
        try:
            body = raw.decode("utf-8", "replace")
        except Exception:
            continue
        if "<Text Name=" not in body:
            continue
        for sm in re.finditer(
            r'<Screen Name="([^"]+)">(?P<body>.*?)</Screen>',
            body,
            flags=re.S,
        ):
            screen = sm.group(1)
            chunk = sm.group("body")
            for m in re.finditer(
                r'<Text Name="([^"]+)">\s*<Text(?:[^>]*)>'
                r'(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Text>',
                chunk,
                flags=re.S,
            ):
                raw_tx = (
                    m.group(2) if m.group(2) is not None else (m.group(3) or "")
                )
                xml_texts.append(
                    {
                        "screen": screen,
                        "name": m.group(1),
                        "text": _html.unescape(raw_tx),
                    }
                )

    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        text = tree.get("m_Text")
        if not isinstance(text, str):
            continue
        go = tree.get("m_GameObject") or {}
        try:
            gpid = int(go.get("m_PathID") or 0)
        except Exception:
            gpid = 0
        go_name = (
            gos.get(gpid, "")
            or str(tree.get("m_Name") or "")
            or ("mb_%s" % int(obj.path_id))
        )
        kind = (
            "UI.Text"
            if "m_FontData" in tree
            else (
                "TMP"
                if "m_sharedMaterial" in tree or "m_fontAsset" in tree
                else "Text"
            )
        )
        texts.append(
            {
                "path_id": int(obj.path_id),
                "game_object_path_id": gpid,
                "name": go_name,
                "kind": kind,
                "text": text,
                "sha1": _sha1(text.encode("utf-8", "replace")),
            }
        )

    mb_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for e in texts:
        mb_by_name.setdefault(e["name"], []).append(e)
    diffs: List[Dict[str, Any]] = []
    for xt in xml_texts:
        nm = xt["name"]
        leaf = nm.split("/")[-1]
        cands = mb_by_name.get(nm) or mb_by_name.get(leaf) or []
        xt_n = _norm_xml_mb_text(xt.get("text") or "")
        if any(_norm_xml_mb_text(mb.get("text") or "") == xt_n for mb in cands):
            continue
        if not cands:
            diffs.append(
                {
                    "xml_name": nm,
                    "xml_screen": xt.get("screen"),
                    "mb_name": None,
                    "reason": "missing_mb",
                    "xml_preview": (xt.get("text") or "")[:200],
                }
            )
            continue
        chosen = cands[0]
        diffs.append(
            {
                "xml_name": nm,
                "xml_screen": xt.get("screen"),
                "mb_name": chosen.get("name"),
                "mb_path_id": chosen.get("path_id"),
                "xml_preview": (xt.get("text") or "")[:200],
                "mb_preview": (chosen.get("text") or "")[:200],
            }
        )

    return {
        "source": source,
        "images": images,
        "text_assets": text_assets,
        "texts": texts,
        "xml_texts": xml_texts,
        "index": index,
        "gameobjects": {str(k): v for k, v in gos.items()},
        "xml_vs_mb_mismatches": diffs,
        "summary": {
            "source": source,
            "images": len(images),
            "text_assets": len(text_assets),
            "ui_texts": len(texts),
            "xml_text_nodes": len(xml_texts),
            "xml_vs_mb_mismatches": len(diffs),
        },
    }


def unpack_path(path: Union[str, Path], *, keep_blob: bool = True) -> Dict[str, Any]:
    _ensure_unitypy()
    import UnityPy

    path = Path(path)
    env = UnityPy.load(str(path))
    snap = unpack_env(env, source=str(path))
    if not keep_blob:
        for im in snap["images"]:
            im.pop("png", None)
        for ta in snap["text_assets"]:
            ta.pop("raw", None)
    return snap


def unpack_bytes(data: bytes, *, source: str = "<memory>") -> Dict[str, Any]:
    _ensure_unitypy()
    import UnityPy

    env = UnityPy.load(data)
    return unpack_env(env, source=source)


def write_snapshot_to_disk(
    snap: Dict[str, Any], out_dir: Union[str, Path]
) -> Dict[str, Any]:
    """Materialize a snapshot to the classic unpack layout."""
    import shutil

    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    images_dir = out_dir / "images"
    xml_dir = out_dir / "xml"
    texts_dir = out_dir / "texts"
    meta_dir = out_dir / "meta"
    for d in (images_dir, xml_dir, texts_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    for im in snap.get("images") or []:
        png = im.get("png")
        if not png:
            continue
        fname = "%s_%s.png" % (
            _safe_name(im.get("name") or "tex"),
            im.get("path_id"),
        )
        (images_dir / fname).write_bytes(png)

    for ta in snap.get("text_assets") or []:
        raw = ta.get("raw") or b""
        name = _safe_name(ta.get("name") or "TextAsset")
        ext = (
            ".xml"
            if (b"<" in raw[:200] or b"KSPedia" in raw[:400])
            else ".txt"
        )
        if not Path(name).suffix:
            name = name + ext
        dest = xml_dir / name
        if dest.exists():
            dest = xml_dir / (
                "%s_%s%s" % (dest.stem, ta.get("path_id"), dest.suffix)
            )
        dest.write_bytes(raw)

    for tx in snap.get("texts") or []:
        fname = "%s__%s.txt" % (
            _safe_name(tx.get("name") or "text"),
            tx.get("path_id"),
        )
        (texts_dir / fname).write_text(
            tx.get("text") or "", encoding="utf-8", newline="\n"
        )

    meta_dir.joinpath("index.json").write_text(
        json.dumps(snap.get("index") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_dir.joinpath("texts.json").write_text(
        json.dumps(snap.get("texts") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_dir.joinpath("xml_text_nodes.json").write_text(
        json.dumps(snap.get("xml_texts") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_dir.joinpath("gameobjects.json").write_text(
        json.dumps(snap.get("gameobjects") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_dir.joinpath("text_mismatches_xml_vs_mb.json").write_text(
        json.dumps(
            snap.get("xml_vs_mb_mismatches") or [],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = dict(snap.get("summary") or {})
    summary["out"] = str(out_dir)
    meta_dir.joinpath("summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def compare_snapshots(
    a: Dict[str, Any],
    b: Dict[str, Any],
    *,
    normalize_text: bool = True,
) -> Dict[str, Any]:
    """Semantic compare (texts / xml nodes / image sha by name).

    ``normalize_text``: strip rich-text tags and collapse whitespace so
    stock plain headers vs Blender ``<b>`` / soft-wrap newlines still match.
    """
    issues: List[Dict[str, Any]] = []

    def _norm_txt(s: str) -> str:
        if not normalize_text:
            return s or ""
        try:
            import re as _re
            t = _re.sub(r"<[^>]+>", "", s or "")
            # Stock often has "factors.The" — Blender soft-wrap inserts "factors. The"
            t = _re.sub(r"\.(\S)", r". \1", t)
            t = _re.sub(r"\s+", " ", t).strip()
            return t
        except Exception:
            return (s or "").strip()

    def by_name_body(items, key_name="name", key_body="text"):
        out: Dict[str, List[str]] = {}
        for it in items or []:
            nm = (it.get(key_name) or "").strip()
            if not nm:
                continue
            body = it.get(key_body)
            if body is None and key_body == "text":
                body = ""
            if key_body == "sha1" and not normalize_text:
                out.setdefault(nm, []).append(it.get("sha1") or "")
            else:
                out.setdefault(nm, []).append(_norm_txt(str(body or "")))
        return out

    ta = by_name_body(a.get("texts"))
    tb = by_name_body(b.get("texts"))
    for nm in sorted(set(ta) | set(tb)):
        if nm not in ta:
            issues.append({"kind": "text_missing_in_a", "name": nm})
        elif nm not in tb:
            issues.append({"kind": "text_missing_in_b", "name": nm})
        elif set(ta[nm]) != set(tb[nm]):
            issues.append(
                {
                    "kind": "text_changed",
                    "name": nm,
                    "a": ta[nm][:1],
                    "b": tb[nm][:1],
                }
            )

    def xml_map(items):
        out = {}
        for it in items or []:
            key = "%s||%s" % (it.get("screen") or "", it.get("name") or "")
            out[key] = _norm_txt(it.get("text") or "")
        return out

    xa, xb = xml_map(a.get("xml_texts")), xml_map(b.get("xml_texts"))
    for key in sorted(set(xa) | set(xb)):
        if key not in xa:
            issues.append({"kind": "xml_missing_in_a", "key": key})
        elif key not in xb:
            issues.append({"kind": "xml_missing_in_b", "key": key})
        elif xa[key] != xb[key]:
            issues.append(
                {
                    "kind": "xml_changed",
                    "key": key,
                    "a": xa[key][:120],
                    "b": xb[key][:120],
                }
            )

    def by_name_sha(items):
        out: Dict[str, List[str]] = {}
        for it in items or []:
            nm = (it.get("name") or "").strip()
            if not nm:
                continue
            out.setdefault(nm, []).append(it.get("sha1") or "")
        return out

    ia, ib = by_name_sha(a.get("images")), by_name_sha(b.get("images"))
    for nm in sorted(set(ia) | set(ib)):
        if nm.lower() == "font texture":
            continue
        if nm not in ia:
            issues.append({"kind": "image_missing_in_a", "name": nm})
        elif nm not in ib:
            issues.append({"kind": "image_missing_in_b", "name": nm})
        elif set(ia[nm]) != set(ib[nm]):
            issues.append({"kind": "image_changed", "name": nm})

    b_mis = b.get("xml_vs_mb_mismatches") or []
    if b_mis:
        issues.append(
            {
                "kind": "export_xml_mb_mismatch",
                "count": len(b_mis),
                "sample": b_mis[:3],
            }
        )

    return {"ok": len(issues) == 0, "issues": issues, "n_issues": len(issues)}


def critical_report(message: str, details: str = "") -> None:
    """Surface a critical error even when the system console is hidden."""
    full = message if not details else "%s\n\n%s" % (message, details)
    print("CRITICAL: %s" % full, flush=True)
    try:
        import bpy

        try:
            bpy.ops.wm.report({"ERROR"}, message[:255])
        except Exception:
            pass
        # Popup crashes Blender in --background; UI only.
        try:
            if not bool(getattr(bpy.app, "background", False)):

                def _draw(self, _ctx):
                    for line in (full.splitlines() or [message])[:12]:
                        self.layout.label(text=line[:90])

                bpy.context.window_manager.popup_menu(
                    _draw, title="KSP Critical Error", icon="ERROR"
                )
        except Exception:
            pass
    except Exception:
        pass
    raise RuntimeError("KSP Critical: %s" % message)
