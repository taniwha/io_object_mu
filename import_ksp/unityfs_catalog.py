# vim:ts=4:et
# <pep8 compliant>
"""Inspect UnityFS KSPedia packs: containers, bundle.xml Assets, UrlName."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple


def _norm_path(p: str) -> str:
    p = (p or "").replace("\\", "/").strip()
    return p.lower()


def pack_url_name(kb, *, filepath: str = "") -> str:
    """UrlName / AssetBundle identity from the source UnityFS (.ksp)."""
    path = (filepath or "").strip()
    if not path and kb is not None:
        path = (
            str(getattr(kb, "source_path", "") or "").strip()
            or str(getattr(kb, "template_path", "") or "").strip()
        )
    if not path:
        return ""
    try:
        info = inspect_ksp_unityfs(path)
    except Exception:
        info = None
    if not info:
        return ""
    return (
        str(info.get("url_name") or "").strip()
        or str(info.get("ab_name") or "").strip()
    )


def host_bundle_stem(kb) -> str:
    """UnityFS pack identity (UrlName), not filesystem / localization filename.

    ``locale_base`` may be ``gep`` while Screens / UrlName stay ``jnsq``.

    Prefer ``kb.bundle_name`` (set at import / heal). Only open the .ksp when
    that is empty — never call this from UIList.draw_item.
    """
    try:
        b = str(getattr(kb, "bundle_name", None) or "").strip()
        if b:
            return b
    except Exception:
        pass
    try:
        url = pack_url_name(kb)
        if url:
            return url
    except Exception:
        pass
    try:
        return str(getattr(kb, "locale_base", None) or "").strip()
    except Exception:
        return ""


def heal_pack_identity(kb, *, filepath: str = "") -> str:
    """Set ``kb.bundle_name`` from UrlName; leave ``locale_base`` as file stem."""
    if kb is None:
        return ""
    url = ""
    try:
        url = pack_url_name(kb, filepath=filepath)
    except Exception:
        url = ""
    if url:
        try:
            kb.bundle_name = url
        except Exception:
            pass
    # Refresh stock/DLC override flags for TOC (GEP/jnsq etc.)
    try:
        from . import kspedia_index as _ki
        host = url or host_bundle_stem(kb)
        nodes = list(getattr(kb, "toc_nodes", []) or [])
        for node in nodes:
            try:
                # Pack UrlName/host — not Screen catalog BundleName.
                node.overrides_stock = _ki.screen_overrides_base(
                    (getattr(node, "screen", "") or "").strip(),
                    host,
                    title=(getattr(node, "title", "") or "").strip(),
                )
            except Exception:
                pass
        try:
            _ki.apply_toc_folder_override_inherit(nodes)
        except Exception:
            pass
    except Exception:
        pass
    return url or host_bundle_stem(kb)


def node_bundle_name(node) -> str:
    try:
        return str(getattr(node, "bundle_name", None) or "").strip()
    except Exception:
        return ""


def node_asset_path(node) -> str:
    try:
        return str(getattr(node, "asset_path", None) or "").strip()
    except Exception:
        return ""


def node_screen_id(node) -> str:
    try:
        return str(getattr(node, "screen", None) or getattr(node, "name", None) or "").strip()
    except Exception:
        return ""


def is_local_toc_node(
    node, host_stem: str, *, previous_stem: str = "", kb=None,
) -> bool:
    """True when Screen belongs to this pack (not intentional foreign/DLC).

    ``kb`` is accepted for callers in prefab_clone/export (sample templates,
    grafted packs). Sample New-menu bundles treat every TOC row as local so
    missing page prefabs can be cloned into the export shell.
    """
    if kb is not None:
        try:
            if bool(getattr(kb, "is_sample_template", False)):
                return True
        except Exception:
            pass
    b = node_bundle_name(node).lower()
    host = (host_stem or "").strip().lower()
    prev = (previous_stem or "").strip().lower()
    if not b:
        return True
    if host and b == host:
        return True
    if prev and b == prev:
        return True
    return False


def inspect_ksp_unityfs(filepath: str) -> Optional[dict]:
    """Return catalog info from a .ksp UnityFS, or None on failure.

    Keys: containers (set lower), bundle_assets (set lower), url_name, ab_name,
    preload_ok (bool).
    """
    path = os.path.abspath(filepath or "")
    if not path or not os.path.isfile(path):
        return None
    try:
        from .deps import ensure_unitypy_or_prompt
        if not ensure_unitypy_or_prompt():
            return None
        import UnityPy
        env = UnityPy.load(path)
    except Exception:
        return None

    containers: Set[str] = set()
    try:
        for cpath in (getattr(env, "container", None) or {}):
            containers.add(_norm_path(str(cpath)))
    except Exception:
        containers = set()

    bundle_assets: Set[str] = set()
    url_name = ""
    ab_name = ""
    try:
        for obj in env.objects:
            if getattr(getattr(obj, "type", None), "name", "") != "TextAsset":
                continue
            data = obj.read()
            name = str(getattr(data, "name", None) or getattr(data, "m_Name", "") or "")
            raw = getattr(data, "script", None) or getattr(data, "m_Script", b"")
            if isinstance(raw, bytes):
                try:
                    raw = raw.decode("utf-8", "replace")
                except Exception:
                    raw = ""
            lname = name.lower()
            if "bundle" not in lname:
                continue
            if "kspedia" in lname and not lname.endswith("_bundle") and "_bundle" not in lname:
                # skip kspedia TOC xml accidentally matching
                if "bundle" not in lname.split("_"):
                    continue
            try:
                root = ET.fromstring(raw or "")
            except Exception:
                continue
            tag = (root.tag or "").split("}")[-1]
            if tag != "KSPBundleDefinition":
                continue
            url_name = (root.get("UrlName") or root.get("Name") or "").strip() or url_name
            for el in root.iter("Asset"):
                ap = (el.get("Path") or "").strip()
                if ap:
                    bundle_assets.add(_norm_path(ap))
    except Exception:
        pass

    # Also AssetBundle.m_AssetBundleName
    try:
        for obj in env.objects:
            if getattr(getattr(obj, "type", None), "name", "") != "AssetBundle":
                continue
            data = obj.read()
            ab_name = str(
                getattr(data, "m_AssetBundleName", None)
                or getattr(data, "m_Name", None)
                or getattr(data, "name", "")
                or ""
            ).strip()
            break
    except Exception:
        pass

    return {
        "containers": containers,
        "bundle_assets": bundle_assets,
        "url_name": url_name,
        "ab_name": ab_name,
        "path": path,
    }


def asset_path_in_pack(asset_path: str, info: Optional[dict]) -> bool:
    if not info or not (asset_path or "").strip():
        return False
    key = _norm_path(asset_path)
    cont = info.get("containers") or set()
    assets = info.get("bundle_assets") or set()
    return key in cont or key in assets


def sync_local_nodes_to_stem(
    kb,
    new_stem: str,
    *,
    previous_stem: str = "",
    update_locale_base: bool = False,
) -> int:
    """Rewrite local TOC BundleName to pack identity ``new_stem``.

    Does not force AssetPath into Assets/KSPedia/ when a local Assets/...
    prefab already exists (GEP uses Assets/Wiki*.prefab). By default leaves
    locale_base alone (file / localization stem).
    """
    from .kspedia_index import default_asset_path_for_screen

    new_stem = (new_stem or "").strip()
    if not new_stem or kb is None:
        return 0
    prev = (previous_stem or "").strip()
    n = 0
    for node in list(getattr(kb, "toc_nodes", []) or []):
        sid = node_screen_id(node)
        if not sid:
            continue
        kind = str(getattr(node, "kind", "") or "")
        if kind not in {"page", "category", "subcategory"}:
            continue
        if not is_local_toc_node(node, new_stem, previous_stem=prev):
            b = node_bundle_name(node).lower()
            if prev and b == prev.lower():
                pass
            elif not b:
                pass
            else:
                continue
        try:
            if node_bundle_name(node) != new_stem:
                node.bundle_name = new_stem
                n += 1
            elif not node_bundle_name(node):
                node.bundle_name = new_stem
                n += 1
        except Exception:
            pass
        try:
            ap = node_asset_path(node)
            want = default_asset_path_for_screen(sid)
            ap_n = (ap or "").replace("\\", "/").lower()
            if not ap:
                node.asset_path = want
                n += 1
            elif (
                "/squad/" in ap_n
                or "/makinghistory/" in ap_n
                or "/serenity/" in ap_n
            ):
                if ap != want:
                    node.asset_path = want
                    n += 1
            elif ap_n.startswith("assets/") and ap_n.endswith(".prefab"):
                base = os.path.splitext(os.path.basename(ap.replace("\\", "/")))[0]
                if base.lower() != sid.lower() and ap_n.startswith("assets/kspedia/"):
                    node.asset_path = want
                    n += 1
            elif not ap_n.startswith("assets/"):
                if ap != want:
                    node.asset_path = want
                    n += 1
        except Exception:
            pass
    try:
        kb.bundle_name = new_stem
    except Exception:
        pass
    if update_locale_base:
        try:
            kb.locale_base = new_stem
        except Exception:
            pass
    return n
