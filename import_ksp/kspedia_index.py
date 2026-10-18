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
"""Parse KSPedia TextAsset XML + KSPediaLocalization.cfg helpers.

KSP loads every ``*.ksp`` under GameData and merges Categories into one TOC.
Screen prefab names (TitleScreen / Screen) are the lookup keys — a mod that
ships the same Screen id as Squad effectively replaces that page's content
when its AssetBundle provides that prefab.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_BASE_SCREENS_CACHE: Optional[Set[str]] = None
_BASE_TITLE_KEYS_CACHE: Optional[Set[str]] = None  # rebuilt when category keys change
_STOCK_SCREENS_CACHE: Optional[Set[str]] = None

# Stock/DLC celestial display names (GEP Wiki03Eve / Wiki04Gilly style ids).
_STOCK_BODY_TITLE_KEYS = frozenset({
    "kerbol", "sun", "moho", "eve", "gilly", "kerbin", "mun", "minmus",
    "duna", "ike", "dres", "jool", "laythe", "vall", "tylo", "bop", "pol",
    "eeloo",
})
# Stock TOC category titles that third-party packs replace (Planet Wiki, etc.).
_STOCK_CATEGORY_TITLE_KEYS = frozenset({
    "planet wiki", "celestial bodies", "planets", "planetwiki",
    "delta-v map", "delta v map", "orbital maneuvers",
})
_WIKI_SCREEN_RE = re.compile(
    r"^(?:Wiki(?:GEP)?\d+|Planets-|DV\d+)(.+)$", re.IGNORECASE
)

from . import ksp_loc


_LOCALE_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)_(?P<locale>[a-z]{2}(?:-[a-z]{2})?)$",
    re.IGNORECASE,
)

# Common Squad KSPedia prefab / Screen ids (subset). Used only as an
# override *hint* when a mod ships the same Screen name.
_STOCK_SCREENS_FALLBACK = {
    "BasicOrbit",
    "BasicRocketry",
    "BasicConstruction",
    "AircraftBasicsControl",
    "AircraftBasicsParts",
    "ScienceArchives",
    "KerbalAcademy",
    "CommNet",
    "MapUI",
    "Controls",
    "Settings",
}


@dataclass
class TocEntry:
    """One row in the flattened TOC (category / subcategory / page)."""

    kind: str  # 'category' | 'subcategory' | 'page'
    depth: int
    name: str  # internal Category/@Name or Screen id
    title: str  # KSPedia display title (LOC resolved when possible)
    title_raw: str = ""  # original <Title> (#autoLOC_… or literal)
    screen: str = ""  # Screen / TitleScreen id (pages only)
    title_screen: str = ""  # Category/Subcategory TitleScreen id
    parent_path: Tuple[str, ...] = ()


@dataclass
class KspediaIndex:
    name: str = ""
    entries: List[TocEntry] = field(default_factory=list)
    screen_titles: Dict[str, str] = field(default_factory=dict)
    screen_titles_raw: Dict[str, str] = field(default_factory=dict)
    screen_paths: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    screen_bundles: Dict[str, str] = field(default_factory=dict)
    screen_assets: Dict[str, str] = field(default_factory=dict)
    # Screen Name -> BundleName / AssetPath (from <Screen Name> catalog)


@dataclass
class LocalizationInfo:
    path: str = ""
    filename: str = ""
    default: str = ""
    locale: str = ""
    cfg_path: str = ""


def _data_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "data")


def load_stock_screens() -> Set[str]:
    """Load optional stock Screen ids shipped with the addon."""
    global _STOCK_SCREENS_CACHE
    if _STOCK_SCREENS_CACHE is not None:
        return set(_STOCK_SCREENS_CACHE)
    out = set(_STOCK_SCREENS_FALLBACK)
    path = os.path.join(_data_dir(), "stock_screens.txt")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    out.add(s)
        except Exception:
            pass
    _STOCK_SCREENS_CACHE = set(out)
    return set(out)


def detect_locale_from_filename(filepath: str) -> Tuple[str, str]:
    """Return (base_name, locale) from ``name_en-us.ksp`` pattern."""
    stem = os.path.splitext(os.path.basename(filepath or ""))[0]
    m = _LOCALE_SUFFIX_RE.match(stem)
    if not m:
        return stem, ""
    return m.group("base"), m.group("locale").lower()


def parse_localization_cfg(cfg_path: str) -> Optional[LocalizationInfo]:
    """Parse a KSPediaLocalization { ... } ModuleManager-style cfg."""
    if not cfg_path or not os.path.isfile(cfg_path):
        return None
    try:
        text = open(cfg_path, "r", encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    if "KSPediaLocalization" not in text:
        return None
    info = LocalizationInfo(cfg_path=os.path.abspath(cfg_path))

    def _grab(key):
        m = re.search(
            r"(?im)^\s*%s\s*=\s*(.+?)\s*$" % re.escape(key),
            text,
        )
        return (m.group(1).strip() if m else "")

    info.path = _grab("path")
    info.filename = _grab("filename")
    info.default = _grab("default").lower()
    return info


def find_localization_near_ksp(filepath: str) -> Optional[LocalizationInfo]:
    """Look for localization.cfg next to the .ksp (parent only if filename matches).

    Parent-folder cfgs without a matching ``filename=`` used to steal
    ``default=de-de`` from another pack and force German on English imports.
    """
    if not filepath:
        return None
    folder = os.path.dirname(os.path.abspath(filepath))
    base, locale = detect_locale_from_filename(filepath)
    stem = os.path.splitext(os.path.basename(filepath))[0]
    same_dir = [
        os.path.join(folder, "localization.cfg"),
        os.path.join(folder, "KSPediaLocalization.cfg"),
    ]
    parent_dir = [
        os.path.join(os.path.dirname(folder), "localization.cfg"),
        os.path.join(os.path.dirname(folder), "KSPediaLocalization.cfg"),
    ]

    def _filename_matches(info) -> bool:
        fn = (getattr(info, "filename", "") or "").strip().lower()
        if not fn:
            return True  # same-folder only callers gate this
        return fn in (base.lower(), stem.lower())

    for c in same_dir:
        info = parse_localization_cfg(c)
        if info is None:
            continue
        if info.filename and not _filename_matches(info):
            continue
        info.locale = locale or (info.default or "")
        return info
    for c in parent_dir:
        info = parse_localization_cfg(c)
        if info is None:
            continue
        # Parent cfg must explicitly name this bundle — never inherit a bare default=
        if not info.filename or not _filename_matches(info):
            continue
        info.locale = locale or (info.default or "")
        return info
    if locale:
        return LocalizationInfo(filename=base, locale=locale, default=locale)
    return None


def find_kspedia_xml_text(text_assets) -> Tuple[str, str]:
    """Pick the KSPedia hierarchy TextAsset (not *_bundle).

    Returns (asset_name, xml_text).
    """
    best = ("", "")
    for ta in text_assets or []:
        name = (getattr(ta, "name", None) or getattr(ta, "Name", None) or "")
        if hasattr(ta, "text"):
            script = ta.text or ""
        else:
            script = ""
        lname = name.lower()
        if "kspedia" not in lname and "<KSPedia" not in (script[:200] or ""):
            continue
        if "bundle" in lname:
            continue
        if "<Categories>" in script or "<Category" in script:
            return name, script
        if not best[1] and script:
            best = (name, script)
    return best


def _child_text(el, tag, default=""):
    t = el.findtext(tag)
    return (t if t is not None else default).strip()


def _walk_category(el, depth: int, parent_path: Tuple[str, ...], out: List[TocEntry],
                   screen_titles: Dict[str, str], screen_paths: Dict[str, Tuple[str, ...]]):
    name = (el.get("Name") or "").strip() or ("Cat_%d" % depth)
    title = _child_text(el, "Title", name)
    path = parent_path + (name,)
    kind = "category" if depth == 0 else "subcategory"
    title_screen = _child_text(el, "TitleScreen")
    out.append(
        TocEntry(
            kind=kind,
            depth=depth,
            name=name,
            title=title,
            title_raw=title,
            title_screen=title_screen,
            parent_path=parent_path,
        )
    )
    if title_screen:
        # TitleScreen keeps category Title; catalog may refine later.
        screen_titles.setdefault(title_screen, title)
        screen_paths[title_screen] = path
        out.append(
            TocEntry(
                kind="page",
                depth=depth + 1,
                name=title_screen,
                title=screen_titles.get(title_screen, title),
                title_raw=screen_titles.get(title_screen, title),
                screen=title_screen,
                parent_path=path,
            )
        )

    screens_el = el.find("Screens")
    if screens_el is not None:
        for s in screens_el.findall("Screen"):
            sid = (s.text or "").strip()
            if not sid:
                continue
            # Prefer catalog/tooltip title if already known; else screen id.
            screen_titles.setdefault(sid, sid)
            screen_paths[sid] = path
            st = screen_titles.get(sid, sid)
            out.append(
                TocEntry(
                    kind="page",
                    depth=depth + 1,
                    name=sid,
                    title=st,
                    title_raw=st,
                    screen=sid,
                    parent_path=path,
                )
            )

    subs = el.find("Subcategories")
    if subs is not None:
        for sub in list(subs):
            if sub.tag in ("Subcategory", "Category"):
                _walk_category(
                    sub, depth + 1, path, out, screen_titles, screen_paths
                )


def _apply_tooltips(root, screen_titles: Dict[str, str]):
    for tips in root.iter("Tooltips"):
        for tip in list(tips):
            screen = tip.get("Screen") or _child_text(tip, "Screen")
            tip_text = _child_text(tip, "Text") or (tip.text or "").strip()
            if screen and tip_text:
                screen_titles[screen] = tip_text


def _apply_screen_catalog(root, idx: KspediaIndex):
    """Parse flat <Screen Name="Id"> catalog (Squad + GEP/JNSQ).

    KSP merges every KSPedia XML; for a given Screen Name the *last* loaded
    AssetBundle that provides that prefab wins — that is how GEP replaces
    JNSQ/stock pages with the same Screen id.
    """
    # Direct children under <KSPedia> or nested; match elements with Name attr
    # that also have BundleName / Title (catalog entries), not <Screens><Screen>text.
    for el in root.iter("Screen"):
        name = (el.get("Name") or "").strip()
        if not name:
            continue
        title = _child_text(el, "Title")
        bundle = _child_text(el, "BundleName")
        asset = _child_text(el, "AssetPath")
        if bundle:
            idx.screen_bundles[name] = bundle
        if asset:
            idx.screen_assets[name] = asset
        # Always keep raw catalog Title (including "." placeholders).
        if title:
            idx.screen_titles_raw[name] = title
        if title and title != ".":
            # Display: catalog wins over screen-id placeholders
            idx.screen_titles[name] = title


def _localize_index(idx: KspediaIndex, filepath: str = ""):
    dictionary = {}
    try:
        dictionary = ksp_loc.load_merged_dictionary(filepath) if filepath else {}
    except Exception:
        path = ksp_loc.find_dictionary_near(filepath) if filepath else ""
        dictionary = ksp_loc.load_dictionary_file(path) if path else {}
    for key, raw in list(idx.screen_titles.items()):
        idx.screen_titles_raw.setdefault(key, raw)
        idx.screen_titles[key] = ksp_loc.resolve_loc(
            raw, dictionary, filepath=filepath
        )
    for e in idx.entries:
        raw = e.title_raw or e.title or ""
        if not e.title_raw:
            e.title_raw = raw
        e.title = ksp_loc.resolve_loc(raw, dictionary, filepath=filepath)
        if e.kind == "page" and e.screen in idx.screen_titles:
            e.title = idx.screen_titles[e.screen]
            if e.screen in idx.screen_titles_raw:
                e.title_raw = idx.screen_titles_raw[e.screen]


def parse_kspedia_xml(xml_text: str, filepath: str = "") -> KspediaIndex:
    idx = KspediaIndex()
    if not xml_text or not xml_text.strip():
        return idx
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return idx
    idx.name = root.get("Name") or ""
    cats = root.find("Categories")
    # Catalog first so Screens under categories inherit titles
    _apply_screen_catalog(root, idx)
    _apply_tooltips(root, idx.screen_titles)
    if cats is not None:
        for cat in cats.findall("Category"):
            _walk_category(
                cat, 0, (), idx.entries, idx.screen_titles, idx.screen_paths
            )
    # Refresh page titles from catalog / tooltip map
    for e in idx.entries:
        if e.kind == "page" and e.screen in idx.screen_titles:
            e.title = idx.screen_titles[e.screen]
        if not e.title_raw:
            e.title_raw = e.title
    _localize_index(idx, filepath=filepath)
    return idx


def parse_kspedia_from_bundle_text_assets(
    text_assets, filepath: str = ""
) -> KspediaIndex:
    _name, xml_text = find_kspedia_xml_text(text_assets)
    return parse_kspedia_xml(xml_text, filepath=filepath)


def screens_in_index(idx: KspediaIndex) -> List[str]:
    return [e.screen for e in idx.entries if e.kind == "page" and e.screen]


def toc_keep_screen_ids(idx: KspediaIndex) -> Set[str]:
    """Screen ids still listed in ``<Categories>`` (pages + TitleScreens)."""
    keep: Set[str] = set()
    if idx is None:
        return keep
    for e in idx.entries or []:
        sid = (getattr(e, "screen", None) or "").strip()
        if sid:
            keep.add(sid)
        ts = (getattr(e, "title_screen", None) or "").strip()
        if ts:
            keep.add(ts)
    return keep


def catalog_screen_ids(idx: KspediaIndex) -> Set[str]:
    """Flat ``<Screen Name>`` catalog ids (prefab + translations may outlive TOC)."""
    ids: Set[str] = set()
    if idx is None:
        return ids
    for src in (
        getattr(idx, "screen_titles", None),
        getattr(idx, "screen_titles_raw", None),
        getattr(idx, "screen_bundles", None),
        getattr(idx, "screen_assets", None),
        getattr(idx, "screen_paths", None),
    ):
        try:
            ids.update(str(k).strip() for k in (src or {}) if str(k).strip())
        except Exception:
            pass
    return ids


def _screen_id_keys(name: str) -> Set[str]:
    """Unity GO / Blender empty names that still mean the same Screen id."""
    n = (name or "").strip()
    if not n:
        return set()
    keys = {n}
    if n.lower().endswith("_page"):
        keys.add(n[: -len("_page")])
    # Blender uniquify: Foo.001
    if "." in n:
        stem, suf = n.rsplit(".", 1)
        if stem and suf.isdigit():
            keys.add(stem)
            if stem.lower().endswith("_page"):
                keys.add(stem[: -len("_page")])
    return {k.strip() for k in keys if k.strip()}


def _ids_hit(name: str, ids: Set[str]) -> bool:
    if not name or not ids:
        return False
    want = {k.lower() for k in ids if k}
    return any(k.lower() in want for k in _screen_id_keys(name))


def is_deleted_toc_screen(tab_name: str, idx: KspediaIndex) -> bool:
    """True when this UnityFS page was removed from the TOC of *this* pack.

    Any Screen id works (not a specific page name). After Del Page, export
    rebuilds ``<Categories>`` without that id but usually leaves the prefab
    and ``<Screens Name>`` catalog / translations. Reimport must not rebuild
    that ghost. Prefab roots that were never in this pack's catalog (extra
    GEP/JNSQ canvases) still import.
    """
    name = (tab_name or "").strip()
    if not name or idx is None:
        return False
    keep = toc_keep_screen_ids(idx)
    catalog = catalog_screen_ids(idx)
    if not keep or not catalog:
        return False
    if _ids_hit(name, keep):
        return False
    return _ids_hit(name, catalog)


def mark_overrides(screen_ids: Iterable[str], stock: Optional[Set[str]] = None) -> Set[str]:
    stock = stock if stock is not None else load_stock_screens()
    return {s for s in screen_ids if s in stock}



def find_stock_kspedia_xml(filepath: str) -> str:
    """Locate Squad KSPedia/kspedia.ksp TextAsset XML near filepath."""
    if not filepath:
        return ""
    gd = ksp_loc.find_gamedata_root(filepath)
    candidates = []
    if gd:
        candidates.append(os.path.join(gd, "Squad", "KSPedia", "kspedia.ksp"))
    folder = os.path.dirname(os.path.abspath(filepath))
    for _ in range(8):
        candidates.append(
            os.path.join(folder, "GameData", "Squad", "KSPedia", "kspedia.ksp")
        )
        candidates.append(os.path.join(folder, "Squad", "KSPedia", "kspedia.ksp"))
        candidates.append(os.path.join(folder, "kspedia.ksp"))
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return ""


# Official DLC KSPedia master indexes (Making History / Breaking Ground).
_DLC_INDEX_REL = (
    ("makinghistory", ("SquadExpansion", "MakingHistory", "KSPedia", "makinghistory.ksp")),
    ("serenity", ("SquadExpansion", "Serenity", "KSPedia", "serenity.ksp")),
)


def find_dlc_kspedia_indexes(filepath: str = "") -> List[Tuple[str, str]]:
    """Return ``[(source_id, abs_path), ...]`` for DLC master indexes near filepath."""
    found: List[Tuple[str, str]] = []
    seen = set()
    gd = ksp_loc.find_gamedata_root(filepath) if filepath else ""
    candidates_roots = []
    if gd:
        candidates_roots.append(gd)
    if filepath:
        folder = os.path.dirname(os.path.abspath(filepath))
        for _ in range(8):
            candidates_roots.append(os.path.join(folder, "GameData"))
            candidates_roots.append(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
    for root in candidates_roots:
        if not root:
            continue
        for source_id, parts in _DLC_INDEX_REL:
            path = os.path.join(root, *parts)
            if not os.path.isfile(path):
                continue
            ap = os.path.abspath(path)
            key = os.path.normcase(ap)
            if key in seen:
                continue
            seen.add(key)
            found.append((source_id, ap))
    return found


def _load_index_from_ksp_file(path: str) -> KspediaIndex:
    """Parse Categories + Screen catalog from a KSPedia master ``.ksp``."""
    if not path or not os.path.isfile(path):
        return KspediaIndex()
    try:
        from .deps import ensure_unitypy
        if not ensure_unitypy(False):
            return KspediaIndex()
        import UnityPy
        env = UnityPy.load(path)

        class _TA:
            def __init__(self, name, text):
                self.name = name
                self.text = text

        assets = []
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            script = data.m_Script
            if isinstance(script, bytes):
                script = script.decode("utf-8", "replace")
            assets.append(_TA(data.m_Name, script))
        return parse_kspedia_from_bundle_text_assets(assets, filepath=path)
    except Exception:
        return KspediaIndex()


def load_stock_index(filepath: str = "") -> KspediaIndex:
    """Parse stock kspedia.ksp index (Categories + Screen catalog + LOC)."""
    path = find_stock_kspedia_xml(filepath)
    if not path:
        return KspediaIndex()
    return _load_index_from_ksp_file(path)


def index_from_fingerprint(fp: dict, *, localize_filepath: str = "") -> KspediaIndex:
    """Rebuild a catalog index from a shipped fingerprint JSON."""
    idx = KspediaIndex()
    if not fp:
        return idx
    for s in fp.get("screens") or []:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        bundle = (s.get("bundle") or "").strip()
        title = (s.get("title") or "").strip()
        asset = (s.get("asset") or "").strip()
        if bundle:
            idx.screen_bundles[name] = bundle
        if asset:
            idx.screen_assets[name] = asset
        if title:
            idx.screen_titles_raw[name] = title
            if title != ".":
                idx.screen_titles[name] = title
    for c in fp.get("categories") or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        title = (c.get("title") or name).strip()
        idx.entries.append(
            TocEntry(
                kind="category",
                depth=0,
                name=name,
                title=title,
                title_raw=title,
            )
        )
    if localize_filepath:
        try:
            _localize_index(idx, filepath=localize_filepath)
        except Exception:
            pass
    return idx


def merge_indexes(*indexes: Optional[KspediaIndex]) -> KspediaIndex:
    """Union catalogs; later indexes overwrite earlier keys for the same Screen."""
    out = KspediaIndex()
    for idx in indexes:
        if idx is None:
            continue
        if getattr(idx, "name", "") and not out.name:
            out.name = idx.name
        out.screen_titles.update(idx.screen_titles or {})
        out.screen_titles_raw.update(idx.screen_titles_raw or {})
        out.screen_paths.update(idx.screen_paths or {})
        out.screen_bundles.update(idx.screen_bundles or {})
        out.screen_assets.update(getattr(idx, "screen_assets", None) or {})
        # Keep category entries (dedupe by name+kind)
        seen = {(e.kind, e.name) for e in out.entries}
        for e in idx.entries or []:
            key = (e.kind, e.name)
            if key in seen:
                continue
            seen.add(key)
            out.entries.append(e)
    return out


def load_dlc_fingerprint(source_id: str) -> dict:
    path = os.path.join(_data_dir(), "%s_kspedia_fingerprint.json" % source_id)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_dlc_screens() -> Set[str]:
    """Screen ids shipped with Making History + Serenity fingerprints / txt."""
    out: Set[str] = set()
    path = os.path.join(_data_dir(), "dlc_screens.txt")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    out.add(s)
        except Exception:
            pass
    for source_id in ("makinghistory", "serenity"):
        fp = load_dlc_fingerprint(source_id)
        for s in fp.get("screens") or []:
            name = (s.get("name") or "").strip()
            if name:
                out.add(name)
    return out


def load_base_screens() -> Set[str]:
    """Stock + official DLC Screen ids (override detection baseline)."""
    return set(load_stock_screens()) | set(load_dlc_screens())


def load_catalog_index(filepath: str = "") -> KspediaIndex:
    """Merged Screen catalog: shipped fingerprints, then live GameData if present.

    Used to fill Title / BundleName / AssetPath for single-page ``.ksp`` imports
    (stock Squad pages and Making History / Breaking Ground DLC pages).
    """
    parts: List[KspediaIndex] = []
    # 1) Shipped offline catalogs
    try:
        stock_fp = load_stock_fingerprint()
        if stock_fp:
            parts.append(index_from_fingerprint(stock_fp, localize_filepath=filepath))
    except Exception:
        pass
    for source_id in ("makinghistory", "serenity"):
        try:
            fp = load_dlc_fingerprint(source_id)
            if fp:
                parts.append(index_from_fingerprint(fp, localize_filepath=filepath))
        except Exception:
            pass
    # 2) Live GameData overlays (preferred — LOC + AssetPath from disk)
    try:
        live_stock = load_stock_index(filepath)
        if live_stock.screen_bundles or live_stock.screen_titles:
            parts.append(live_stock)
    except Exception:
        pass
    for _source_id, path in find_dlc_kspedia_indexes(filepath):
        try:
            live = _load_index_from_ksp_file(path)
            if live.screen_bundles or live.screen_titles:
                parts.append(live)
        except Exception:
            pass
    return merge_indexes(*parts)


def lookup_screen_for_bundle(
    idx: KspediaIndex, bundle_stem: str
) -> Tuple[str, str]:
    """Return (screen_id, display_title) for a .ksp stem / BundleName."""
    if not idx or not bundle_stem:
        return "", ""
    stem = bundle_stem.lower()
    # Exact BundleName match
    for sid, bname in (idx.screen_bundles or {}).items():
        if (bname or "").lower() == stem:
            title = idx.screen_titles.get(sid, sid)
            return sid, title
    # Screen id equals stem-ish (AircraftBasicsCoL)
    for sid, title in (idx.screen_titles or {}).items():
        if sid.lower() == stem:
            return sid, title
        compact = sid.lower().replace("-", "").replace("_", "")
        if compact == stem.replace("-", "").replace("_", "").replace("kspedia", ""):
            return sid, title
    # BundleName contained
    for sid, bname in (idx.screen_bundles or {}).items():
        bl = (bname or "").lower()
        if bl and (bl in stem or stem in bl):
            return sid, idx.screen_titles.get(sid, sid)
    return "", ""



def cached_base_screens() -> Set[str]:
    """Stock ∪ DLC Screen ids (cached — safe for UI draw / Add Page)."""
    global _BASE_SCREENS_CACHE
    if _BASE_SCREENS_CACHE is not None:
        return _BASE_SCREENS_CACHE
    try:
        _BASE_SCREENS_CACHE = set(load_base_screens())
    except Exception:
        _BASE_SCREENS_CACHE = set(load_stock_screens())
    return _BASE_SCREENS_CACHE


def _override_title_key(text: str) -> str:
    """Normalize a Screen id or display title for stock-body override matching."""
    s = (text or "").strip().lower()
    if not s:
        return ""
    m = _WIKI_SCREEN_RE.match(s)
    if m:
        s = (m.group(1) or "").strip().lower()
    if s in ("sun", "the sun"):
        return "kerbol"
    return s


def cached_base_title_keys() -> Set[str]:
    """Lowercased stock/DLC titles + body aliases (cached for UI)."""
    global _BASE_TITLE_KEYS_CACHE
    if _BASE_TITLE_KEYS_CACHE is not None:
        return _BASE_TITLE_KEYS_CACHE
    out = set(_STOCK_BODY_TITLE_KEYS) | set(_STOCK_CATEGORY_TITLE_KEYS)
    try:
        for sid in cached_base_screens():
            key = _override_title_key(sid)
            if key:
                out.add(key)
            if "-" in sid:
                out.add(sid.rsplit("-", 1)[-1].strip().lower())
    except Exception:
        pass
    # Localized titles from shipped fingerprints (best-effort, no GameData).
    try:
        for source in ("stock", "makinghistory", "serenity"):
            try:
                if source == "stock":
                    fp = load_stock_fingerprint()
                else:
                    fp = load_dlc_fingerprint(source)
            except Exception:
                fp = {}
            for s in fp.get("screens") or []:
                title = (s.get("title") or "").strip()
                if not title or title == "." or title.startswith("#"):
                    continue
                key = _override_title_key(title)
                if key:
                    out.add(key)
                out.add(title.strip().lower())
    except Exception:
        pass
    _BASE_TITLE_KEYS_CACHE = out
    return _BASE_TITLE_KEYS_CACHE


def screen_overrides_base(
    screen: str,
    bundle_name: str,
    *,
    title: str = "",
    catalog_index: Optional["KspediaIndex"] = None,
) -> bool:
    """True when this pack replaces stock/DLC content (not an official host).

    ``bundle_name`` must be the **pack** identity (UnityFS UrlName /
    ``host_bundle_stem``), **not** the Screen catalog ``BundleName``. Stock
    Screen rows often keep BundleName ``kspedia`` even inside a mod pack; using
    that here falsely clears the override flag and kills blue TOC icons.

    Official hosts: kspedia / squad / makinghistory / serenity.
    Matches exact stock/DLC Screen ids **or** GEP-style Wiki##Body ids / titles
    (Wiki03Eve, Wiki04Gilly, title \"Eve\") against stock body names.
    Does not call load_catalog_index (too slow for UI / Add Page).
    """
    sid = (screen or "").strip()
    own = (bundle_name or "").strip().lower()
    if not own:
        return False
    official_hosts = {
        "squad", "kspedia", "makinghistory", "serenity",
        "breakingground", "expansion",
    }
    if own in official_hosts or own.startswith("kspedia"):
        return False
    base = cached_base_screens()
    if sid and sid in base:
        return True
    keys = cached_base_title_keys()
    for cand in (title, sid):
        key = _override_title_key(cand)
        if key and key in keys:
            return True
        raw = (cand or "").strip().lower()
        if raw and raw in keys:
            return True
    return False




def apply_toc_folder_override_inherit(toc_nodes) -> None:
    """Mark category rows overrides_stock if any nested page already is.

    Call once after filling TOC flags — not from UIList.draw_item.
    """
    try:
        nodes = list(toc_nodes or [])
    except Exception:
        return
    n = len(nodes)
    for i, node in enumerate(nodes):
        try:
            if getattr(node, "kind", "") not in ("category", "subcategory"):
                continue
            if getattr(node, "overrides_stock", False):
                continue
            depth = int(getattr(node, "depth", 0) or 0)
        except Exception:
            continue
        for j in range(i + 1, n):
            try:
                child = nodes[j]
                d = int(getattr(child, "depth", 0) or 0)
            except Exception:
                break
            if d <= depth:
                break
            try:
                if getattr(child, "kind", "") == "page" and getattr(
                    child, "overrides_stock", False
                ):
                    node.overrides_stock = True
                    break
            except Exception:
                pass


def mark_overrides_against_stock(
    screen_ids: Iterable[str], stock_idx: Optional[KspediaIndex] = None,
    filepath: str = "",
    pack_bundle: str = "",
    titles: Optional[Dict[str, str]] = None,
) -> Set[str]:
    """Screens that replace stock/DLC (exact id or GEP-style title/body)."""
    out = set()
    title_map = titles or {}
    if stock_idx is not None:
        for k, v in (stock_idx.screen_titles or {}).items():
            title_map.setdefault(k, v)
    for s in screen_ids:
        if not s:
            continue
        title = (title_map.get(s) or "").strip()
        if pack_bundle:
            if screen_overrides_base(
                s, pack_bundle, title=title, catalog_index=stock_idx,
            ):
                out.add(s)
        elif s in cached_base_screens() or _override_title_key(s) in cached_base_title_keys() or _override_title_key(title) in cached_base_title_keys():
            out.add(s)
    return out


def toc_xml_title(node) -> str:
    """Title written to KSPedia XML for this TOC row.

    Stock/DLC keep ``#autoLOC_*`` keys. User pages use the live (locale) title
    so export can stamp EN vs DE after ``apply_locale_toc_titles``.
    """
    try:
        raw = (getattr(node, "title_raw", "") or "").strip()
    except Exception:
        raw = ""
    try:
        title = (getattr(node, "title", None) or "").strip()
    except Exception:
        title = ""
    try:
        screen = (
            getattr(node, "screen", None) or getattr(node, "name", "") or ""
        ).strip()
    except Exception:
        screen = ""
    if raw.startswith("#"):
        return raw
    return title or raw or screen


def apply_toc_order_to_xml(xml_text: str, toc_nodes) -> str:
    """Rebuild ``<Categories>`` from flat TOC order (game TOC order).

    Preserves the rest of the document (Screen catalog, Tooltips, …).
    ``toc_nodes`` is a Blender CollectionProperty of KSPMU_PG_KspTocNode
    or any sequence with ``kind``, ``depth``, ``name``, ``title``, ``screen``.
    """
    if not xml_text or not toc_nodes:
        return xml_text
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text

    cats = root.find("Categories")
    if cats is None:
        cats = ET.SubElement(root, "Categories")
    else:
        for child in list(cats):
            cats.remove(child)

    # Stack of (depth, element) for open Category/Subcategory nodes
    stack: List[Tuple[int, Any]] = [(-1, cats)]

    def _ensure_child(parent_el, tag):
        el = parent_el.find(tag)
        if el is None:
            el = ET.SubElement(parent_el, tag)
        return el

    for node in toc_nodes:
        try:
            kind = str(node.kind)
            depth = int(node.depth)
            title = toc_xml_title(node)
            name = (node.name or title or "Node").strip()
            screen = (getattr(node, "screen", None) or "").strip()
        except Exception:
            continue

        while len(stack) > 1 and stack[-1][0] >= depth:
            stack.pop()
        parent_el = stack[-1][1]

        if kind in ("category", "subcategory"):
            tag = "Category" if depth == 0 or kind == "category" else "Subcategory"
            # Nested under Subcategories (except root Categories)
            if depth == 0:
                attach = parent_el  # Categories
            else:
                # parent should be Category/Subcategory — use its Subcategories
                if parent_el.tag == "Categories":
                    attach = parent_el
                    tag = "Category"
                else:
                    attach = _ensure_child(parent_el, "Subcategories")
                    tag = "Subcategory"
            el = ET.SubElement(attach, tag)
            el.set("Name", name)
            t_el = ET.SubElement(el, "Title")
            t_el.text = title or name
            ts_el = ET.SubElement(el, "TitleScreen")
            ts_el.text = screen or ""
            ET.SubElement(el, "Screens")
            ET.SubElement(el, "Subcategories")
            stack.append((depth, el))
        elif kind == "page":
            # Skip TitleScreen duplicate (already on parent TitleScreen)
            if parent_el.tag in ("Category", "Subcategory"):
                parent_ts = _child_text(parent_el, "TitleScreen")
                if screen and parent_ts and screen == parent_ts:
                    continue
                screens_el = _ensure_child(parent_el, "Screens")
                s_el = ET.SubElement(screens_el, "Screen")
                s_el.text = screen or name

    try:
        return ET.tostring(root, encoding="unicode")
    except Exception:
        return xml_text


def default_bundle_name_for_kb(kb) -> str:
    """BundleName for Screen catalog entries (UnityFS UrlName / pack identity)."""
    try:
        from .unityfs_catalog import host_bundle_stem
        h = host_bundle_stem(kb)
        if h:
            return h
    except Exception:
        pass
    b = (
        getattr(kb, "bundle_name", None)
        or getattr(kb, "locale_base", None)
        or "kspedia"
    )
    b = str(b or "").strip()
    return b or "kspedia"


def default_asset_path_for_screen(screen_id: str) -> str:
    """Unity prefab path used when a Screen has no AssetPath yet.

    KSP drops screens without AssetPath from the in-game TOC. Match stock /
    PBS style: ``Assets/KSPedia/<Screen>.prefab``.
    """
    sid = str(screen_id or "Screen").strip() or "Screen"
    return "Assets/KSPedia/%s.prefab" % sid


def ensure_node_catalog_meta(node, kb) -> None:
    """Fill empty BundleName / AssetPath on a TOC node in place."""
    if node is None:
        return
    screen = str(getattr(node, "screen", None) or "").strip()
    if not screen:
        return
    try:
        if not str(getattr(node, "bundle_name", None) or "").strip():
            node.bundle_name = default_bundle_name_for_kb(kb)
    except Exception:
        pass
    try:
        if not str(getattr(node, "asset_path", None) or "").strip():
            node.asset_path = default_asset_path_for_screen(screen)
    except Exception:
        pass


def sync_bundle_toc_xml(kb) -> bool:
    """Write current TOC order into the bundle's KSPedia XML TextAsset."""
    if kb is None:
        return False
    xml_name = getattr(kb, "kspedia_xml_asset", "") or ""
    target = None
    for ta in getattr(kb, "text_assets", None) or []:
        if xml_name and ta.name == xml_name:
            target = ta
            break
        if target is None:
            lname = (ta.name or "").lower()
            if "kspedia" in lname and "bundle" not in lname:
                target = ta
    if target is None:
        return False
    src = ""
    if target.text_block:
        try:
            src = target.text_block.as_string()
        except Exception:
            src = ""
    if not src:
        src = target.text or ""
    if not src.strip():
        # Minimal skeleton so order can be stored
        src = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<KSPedia Name="%s">\n  <Categories/>\n  <Screens/>\n</KSPedia>\n'
            % (getattr(kb, "bundle_name", None) or "kspedia")
        )
    new_xml = apply_toc_order_to_xml(src, kb.toc_nodes)
    # Every TitleScreen / page must have a flat Screen catalog entry or the
    # game drops it from the TOC (nested <Screens> refs alone are not enough).
    catalog_by_screen = {}
    try:
        root0 = ET.fromstring(new_xml or src)
        for el in root0.iter("Screen"):
            nm = (el.get("Name") or "").strip()
            if not nm:
                continue
            catalog_by_screen[nm] = {
                "title": _child_text(el, "Title") or "",
                "bundle_name": _child_text(el, "BundleName") or "",
                "asset_path": _child_text(el, "AssetPath") or "",
            }
    except Exception:
        catalog_by_screen = {}

    def _inherit_asset(screen_id: str, prefer: str = "") -> str:
        if (prefer or "").strip():
            return prefer.strip()
        hit = catalog_by_screen.get(screen_id) or {}
        if (hit.get("asset_path") or "").strip():
            return hit["asset_path"].strip()
        # Fall back to any other catalog prefab in this bundle.
        for meta in catalog_by_screen.values():
            ap = (meta.get("asset_path") or "").strip()
            if ap:
                return ap
        # Last resort: generate a valid prefab path (empty AssetPath = invisible in game)
        return default_asset_path_for_screen(screen_id)

    def _inherit_bundle(screen_id: str, prefer: str = "") -> str:
        if (prefer or "").strip():
            return prefer.strip()
        hit = catalog_by_screen.get(screen_id) or {}
        if (hit.get("bundle_name") or "").strip():
            return hit["bundle_name"].strip()
        b = (getattr(kb, "bundle_name", None) or getattr(kb, "locale_base", None) or "").strip()
        return b

    for node in getattr(kb, "toc_nodes", None) or []:
        try:
            kind = str(getattr(node, "kind", "") or "")
            screen = (getattr(node, "screen", None) or "").strip()
            if not screen:
                continue
            if kind not in ("page", "category", "subcategory"):
                continue
            title = toc_xml_title(node) or screen
            bname = _inherit_bundle(
                screen, getattr(node, "bundle_name", None) or "",
            )
            apath = _inherit_asset(
                screen, getattr(node, "asset_path", None) or "",
            )
            # Prefer source-page asset when this row still has none.
            if not apath and kind == "page":
                # Walk up for a sibling TitleScreen with a known prefab.
                for other in kb.toc_nodes:
                    try:
                        if str(other.kind) not in ("page", "subcategory", "category"):
                            continue
                        oscreen = (other.screen or "").strip()
                        if not oscreen or oscreen == screen:
                            continue
                        oap = (getattr(other, "asset_path", None) or "").strip()
                        if not oap:
                            oap = (catalog_by_screen.get(oscreen) or {}).get(
                                "asset_path", ""
                            )
                        if oap:
                            # Same folder / nearby: reuse that prefab path so
                            # the game can at least resolve the Screen id.
                            apath = str(oap).strip()
                            break
                    except Exception:
                        continue
            new_xml = ensure_screen_catalog_entry(
                new_xml,
                screen,
                title=title,
                bundle_name=bname or None,
                asset_path=apath or None,
            )
            try:
                if bname and not (getattr(node, "bundle_name", None) or "").strip():
                    node.bundle_name = bname
                if apath and not (getattr(node, "asset_path", None) or "").strip():
                    node.asset_path = apath
            except Exception:
                pass
        except Exception:
            continue

    try:
        new_xml = prune_orphan_screen_catalog(new_xml, kb.toc_nodes)
    except Exception:
        pass

    if new_xml == src:
        # Still write — order may have changed with identical string edge cases
        pass
    target.text = new_xml
    if target.text_block:
        try:
            target.text_block.clear()
            target.text_block.write(new_xml)
        except Exception:
            pass
    return True


def set_screen_title_in_xml(xml_text: str, screen_id: str, new_title: str) -> str:
    """Update Title for the category whose TitleScreen matches, or a tooltip.

    Best-effort string/XML edit for round-trip via TextAsset.
    """
    if not xml_text or not screen_id:
        return xml_text
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text

    changed = False
    for el in root.iter():
        if el.tag not in ("Category", "Subcategory"):
            continue
        if _child_text(el, "TitleScreen") == screen_id:
            title_el = el.find("Title")
            if title_el is None:
                title_el = ET.SubElement(el, "Title")
            title_el.text = new_title
            changed = True
    # Flat Screen catalog: <Screen Name="Id"><Title>
    for el in root.iter("Screen"):
        name = (el.get("Name") or "").strip()
        if name != screen_id:
            continue
        title_el = el.find("Title")
        if title_el is None:
            title_el = ET.SubElement(el, "Title")
        title_el.text = new_title
        changed = True
    for tips in root.iter("Tooltips"):
        for tip in list(tips):
            sc = tip.get("Screen") or _child_text(tip, "Screen")
            if sc != screen_id:
                continue
            text_el = tip.find("Text")
            if text_el is None:
                tip.set("Screen", screen_id)
                if tip.text and not list(tip):
                    tip.text = new_title
                else:
                    text_el = ET.SubElement(tip, "Text")
                    text_el.text = new_title
            else:
                text_el.text = new_title
            changed = True

    if not changed:
        return xml_text
    try:
        return ET.tostring(root, encoding="unicode")
    except Exception:
        return xml_text


def toc_nodes_screen_ids(toc_nodes) -> Set[str]:
    """Live Screen ids on a Blender TOC collection (pages + folder TitleScreens)."""
    keep: Set[str] = set()
    for node in toc_nodes or []:
        try:
            kind = str(getattr(node, "kind", "") or "")
            if kind not in ("page", "category", "subcategory"):
                continue
            sid = (getattr(node, "screen", None) or "").strip()
            if sid:
                keep.add(sid)
        except Exception:
            continue
    return keep


def prune_orphan_screen_catalog(xml_text: str, toc_nodes) -> str:
    """Strip translations for Screens no longer in the TOC.

    Any deleted page/screen: keep a catalog stub (Name / BundleName / AssetPath)
    so reimport can skip the leftover UnityFS prefab, but drop ``<Text>`` and
    matching Tooltips so they do not come back as content.
    """
    if not xml_text:
        return xml_text
    keep = toc_nodes_screen_ids(toc_nodes)
    if not keep:
        return xml_text
    keep_l = {k.lower() for k in keep}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text

    def _is_kept(sid: str) -> bool:
        s = (sid or "").strip()
        return bool(s) and s.lower() in keep_l

    for el in list(root.iter("Screen")):
        sid = (el.get("Name") or "").strip()
        if not sid or _is_kept(sid):
            continue
        for child in list(el):
            if child.tag == "Text":
                el.remove(child)
        ET.SubElement(el, "Text")

    for tips in list(root.iter("Tooltips")):
        for tip in list(tips):
            screen = (tip.get("Screen") or _child_text(tip, "Screen") or "").strip()
            if screen and not _is_kept(screen):
                tips.remove(tip)

    try:
        return ET.tostring(root, encoding="unicode")
    except Exception:
        return xml_text


def lookup_screen_catalog(xml_text: str, screen_id: str) -> Dict[str, str]:
    """Return Title / BundleName / AssetPath for a catalog ``Screen Name=``."""
    out = {"title": "", "bundle_name": "", "asset_path": ""}
    if not xml_text or not screen_id:
        return out
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for el in root.iter("Screen"):
        name = (el.get("Name") or "").strip()
        if name != screen_id:
            continue
        out["title"] = _child_text(el, "Title") or ""
        out["bundle_name"] = _child_text(el, "BundleName") or ""
        out["asset_path"] = _child_text(el, "AssetPath") or ""
        return out
    return out


def ensure_screen_catalog_entry(
    xml_text: str,
    screen_id: str,
    *,
    title: Optional[str] = None,
    bundle_name: Optional[str] = None,
    asset_path: Optional[str] = None,
) -> str:
    """Create or update a flat ``<Screen Name>`` catalog entry.

    Nested ``<Screens><Screen>id</Screen></Screens>`` TOC refs are useless in
    KSP unless this catalog entry exists (BundleName + AssetPath). Duplicated
    / grafted pages were missing it, so the game never listed or loaded them.
    """
    if not xml_text or not (screen_id or "").strip():
        return xml_text
    screen_id = screen_id.strip()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text

    screens_root = root.find("Screens")
    if screens_root is None:
        screens_root = ET.SubElement(root, "Screens")

    target = None
    for el in list(screens_root):
        if el.tag != "Screen":
            continue
        if (el.get("Name") or "").strip() == screen_id:
            target = el
            break
    if target is None:
        # Also accept a misplaced catalog entry elsewhere in the doc.
        for el in root.iter("Screen"):
            if (el.get("Name") or "").strip() == screen_id:
                target = el
                break
    if target is None:
        target = ET.SubElement(screens_root, "Screen")
        target.set("Name", screen_id)

    def _set_child(tag: str, value: Optional[str], *, create: bool) -> None:
        if value is None:
            return
        value = str(value).strip()
        child = target.find(tag)
        if child is None:
            if not create and not value:
                return
            child = ET.SubElement(target, tag)
        if value or create:
            child.text = value

    _set_child("BundleName", bundle_name, create=True)
    _set_child("AssetPath", asset_path, create=True)
    if title is not None:
        _set_child("Title", title, create=True)
    elif target.find("Title") is None:
        _set_child("Title", screen_id, create=True)
    if target.find("Background") is None:
        ET.SubElement(target, "Background")
    if target.find("Text") is None:
        ET.SubElement(target, "Text")

    try:
        return ET.tostring(root, encoding="unicode")
    except Exception:
        return xml_text


def set_screen_meta_in_xml(
    xml_text: str,
    screen_id: str,
    *,
    title: Optional[str] = None,
    bundle_name: Optional[str] = None,
    asset_path: Optional[str] = None,
) -> str:
    """Patch Screen catalog BundleName / AssetPath / Title for screen_id."""
    if not xml_text or not screen_id:
        return xml_text
    # Create missing catalog rows — patching alone left duplicates invisible.
    return ensure_screen_catalog_entry(
        xml_text,
        screen_id,
        title=title,
        bundle_name=bundle_name,
        asset_path=asset_path,
    )


def load_stock_fingerprint() -> dict:
    path = os.path.join(_data_dir(), "stock_kspedia_fingerprint.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fingerprint_from_index(idx: KspediaIndex) -> dict:
    screens = []
    keys = (
        set(idx.screen_titles_raw or {})
        | set(idx.screen_bundles or {})
        | set(getattr(idx, "screen_assets", None) or {})
    )
    for sid in sorted(keys):
        screens.append({
            "name": sid,
            "bundle": (idx.screen_bundles or {}).get(sid, ""),
            "title": (idx.screen_titles_raw or {}).get(sid, ""),
            "asset": (getattr(idx, "screen_assets", None) or {}).get(sid, ""),
        })
    cats = [
        {"name": e.name, "title": e.title_raw or e.title}
        for e in idx.entries
        if e.kind == "category"
    ]
    blob = json.dumps({"screens": screens, "categories": cats}, sort_keys=True)
    return {
        "xml_sha1": hashlib.sha1(blob.encode("utf-8")).hexdigest(),
        "n_screens": len(screens),
        "n_categories": len(cats),
        "screens": screens,
        "categories": cats,
    }


def diff_against_stock_fingerprint(
    idx: KspediaIndex, stock_fp: Optional[dict] = None
) -> List[str]:
    """Diff current index vs shipped stock fingerprint (or provided fp)."""
    stock_fp = stock_fp if stock_fp is not None else load_stock_fingerprint()
    if not stock_fp:
        return []
    ours = fingerprint_from_index(idx)
    lines: List[str] = []
    stock_map = {s["name"]: s for s in (stock_fp.get("screens") or [])}
    our_map = {s["name"]: s for s in (ours.get("screens") or [])}
    if stock_fp.get("n_screens") != ours.get("n_screens"):
        lines.append(
            "Screen count %s -> %s"
            % (stock_fp.get("n_screens"), ours.get("n_screens"))
        )
    for name in sorted(set(stock_map) | set(our_map)):
        a = stock_map.get(name)
        b = our_map.get(name)
        if a is None:
            lines.append("+ Screen %s (new)" % name)
            continue
        if b is None:
            lines.append("- Screen %s (missing)" % name)
            continue
        if (a.get("title") or "") != (b.get("title") or ""):
            lines.append(
                "~ %s Title: %r -> %r" % (name, a.get("title"), b.get("title"))
            )
        if (a.get("bundle") or "") != (b.get("bundle") or ""):
            lines.append(
                "~ %s BundleName: %r -> %r"
                % (name, a.get("bundle"), b.get("bundle"))
            )
    return lines


def diff_against_gamedata_stock(filepath: str, idx: KspediaIndex) -> List[str]:
    """Compare imported index to live GameData stock or shipped fingerprint."""
    stock_path = find_stock_kspedia_xml(filepath or "")
    if not stock_path:
        return diff_against_stock_fingerprint(idx)
    try:
        if os.path.normcase(os.path.abspath(filepath or "")) == os.path.normcase(
            stock_path
        ):
            return diff_against_stock_fingerprint(idx)
    except Exception:
        pass
    live = load_stock_index(filepath)
    if not live.screen_titles and not live.entries:
        return diff_against_stock_fingerprint(idx)
    return diff_against_stock_fingerprint(idx, fingerprint_from_index(live))


def _xml_text_leaf(name: str) -> str:
    n = (name or "").strip()
    if "/" in n:
        return n.rsplit("/", 1)[-1].strip()
    return n


def _set_named_text_body(named_el, body: str) -> None:
    """Set inner ``<Text>…</Text>`` of a named KSPedia text node."""
    body = body if body is not None else ""
    inner = None
    for child in list(named_el):
        if child.tag == "Text" and child.get("Name") is None:
            inner = child
            break
    if inner is None:
        inner = ET.SubElement(named_el, "Text")
    inner.text = body
    for child in list(named_el):
        if child is inner:
            continue
        if child.tag == "Text" and child.get("Name") is None:
            named_el.remove(child)


def apply_ui_texts_to_kspedia_xml(
    xml_text: str,
    entries: Iterable[Dict[str, Any]],
    *,
    drop_unmatched: bool = True,
) -> Tuple[str, int]:
    """Push Blender UI texts into Screen catalog ``<Text Name>`` nodes.

    ``entries`` items::
        page_screen: str   # Screen Name (prefab / catalog id)
        name: str          # GO / ui_elements name (leaf or full XML path)
        text: str          # authoritative body (may include <color>/<b>)
        alive: bool        # False → remove matching XML node(s)

    Returns ``(new_xml, n_changes)``.
    Only drops unmatched XML nodes on screens that appear in ``entries``.
    """
    if not xml_text:
        return xml_text or "", 0
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text, 0

    by_screen_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    by_name_only: Dict[str, List[Dict[str, Any]]] = {}
    screens_wanted: Set[str] = set()
    for raw in entries or []:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        screen = (raw.get("page_screen") or "").strip()
        ent = {
            "page_screen": screen,
            "name": name,
            "text": raw.get("text") if raw.get("text") is not None else "",
            "alive": bool(raw.get("alive", True)),
        }
        leaf = _xml_text_leaf(name)
        if screen:
            screens_wanted.add(screen.lower())
            by_screen_key[(screen.lower(), name.lower())] = ent
            by_screen_key[(screen.lower(), leaf.lower())] = ent
        by_name_only.setdefault(leaf.lower(), []).append(ent)
        if name.lower() != leaf.lower():
            by_name_only.setdefault(name.lower(), []).append(ent)

    def _lookup(screen_id: str, xml_name: str):
        sid = (screen_id or "").strip()
        xn = (xml_name or "").strip()
        leaf = _xml_text_leaf(xn)
        if sid:
            hit = by_screen_key.get((sid.lower(), xn.lower()))
            if hit is not None:
                return hit
            hit = by_screen_key.get((sid.lower(), leaf.lower()))
            if hit is not None:
                return hit
        for key in (xn.lower(), leaf.lower()):
            cands = by_name_only.get(key) or []
            if len(cands) == 1:
                return cands[0]
            if sid:
                scoped = [
                    c for c in cands
                    if (c.get("page_screen") or "").strip().lower() == sid.lower()
                ]
                if len(scoped) == 1:
                    return scoped[0]
                if len(scoped) > 1:
                    for c in scoped:
                        if (c.get("name") or "").strip().lower() == xn.lower():
                            return c
                    return scoped[0]
        return None

    screens_root = root.find("Screens")
    if screens_root is None:
        screens_root = ET.SubElement(root, "Screens")

    n_changes = 0
    claimed: Set[int] = set()

    for screen_el in list(screens_root):
        if screen_el.tag != "Screen":
            continue
        screen_id = (screen_el.get("Name") or "").strip()
        if not screen_id:
            continue
        screen_in_entries = screen_id.lower() in screens_wanted
        text_root = screen_el.find("Text")
        if text_root is not None and text_root.get("Name"):
            text_root = None
            for ch in list(screen_el):
                if ch.tag == "Text" and ch.get("Name") is None:
                    text_root = ch
                    break
        if text_root is None:
            if not screen_in_entries:
                continue
            need = False
            for lst in by_name_only.values():
                for e in lst:
                    if (
                        (e.get("page_screen") or "").strip().lower()
                        == screen_id.lower()
                        and e.get("alive", True)
                    ):
                        need = True
                        break
                if need:
                    break
            if not need:
                continue
            text_root = ET.SubElement(screen_el, "Text")
            n_changes += 1

        for named in list(text_root):
            if named.tag != "Text":
                continue
            xml_name = (named.get("Name") or "").strip()
            if not xml_name:
                continue
            ent = _lookup(screen_id, xml_name)
            if ent is None:
                # Only drop orphans on screens we are actively syncing.
                if drop_unmatched and screen_in_entries:
                    text_root.remove(named)
                    n_changes += 1
                continue
            if not ent.get("alive", True):
                text_root.remove(named)
                n_changes += 1
                claimed.add(id(ent))
                continue
            new_body = ent.get("text") if ent.get("text") is not None else ""
            cur = ""
            for child in list(named):
                if child.tag == "Text" and child.get("Name") is None:
                    cur = child.text if child.text is not None else ""
                    break
            if cur != new_body:
                _set_named_text_body(named, new_body)
                n_changes += 1
            claimed.add(id(ent))

        if not screen_in_entries:
            continue

        seen_names = set()
        for named in list(text_root):
            if named.tag == "Text" and named.get("Name"):
                seen_names.add((named.get("Name") or "").strip().lower())
                seen_names.add(_xml_text_leaf(named.get("Name") or "").lower())

        added_ids = set()
        for lst in list(by_name_only.values()):
            for ent in lst:
                if id(ent) in claimed or id(ent) in added_ids:
                    continue
                if not ent.get("alive", True):
                    continue
                esc = (ent.get("page_screen") or "").strip()
                if esc and esc.lower() != screen_id.lower():
                    continue
                if not esc:
                    continue
                nm = (ent.get("name") or "").strip()
                leaf = _xml_text_leaf(nm)
                if nm.lower() in seen_names or leaf.lower() in seen_names:
                    continue
                node = ET.SubElement(text_root, "Text")
                node.set("Name", nm)
                _set_named_text_body(node, ent.get("text") or "")
                seen_names.add(nm.lower())
                seen_names.add(leaf.lower())
                added_ids.add(id(ent))
                claimed.add(id(ent))
                n_changes += 1

    try:
        new_xml = ET.tostring(root, encoding="unicode")
    except Exception:
        return xml_text, 0
    return new_xml, n_changes


def sync_ui_texts_into_kspedia_xml(kb, entries: Iterable[Dict[str, Any]]) -> int:
    """Apply ``entries`` to the bundle's KSPedia TextAsset in ``kb.text_assets``.

    Source of truth after Blender edit: MonoBehaviour / ui_elements text.
    Returns number of logical XML changes (0 if nothing to do / no asset).
    """
    if kb is None:
        return 0
    xml_name = (getattr(kb, "kspedia_xml_asset", "") or "").strip()
    target = None
    for ta in getattr(kb, "text_assets", None) or []:
        name = (getattr(ta, "name", "") or "").strip()
        lname = name.lower()
        if xml_name and name == xml_name:
            target = ta
            break
        if target is None and "kspedia" in lname and "bundle" not in lname:
            target = ta
    if target is None:
        return 0
    src = ""
    if getattr(target, "text_block", None):
        try:
            src = target.text_block.as_string()
        except Exception:
            src = ""
    if not src:
        src = getattr(target, "text", None) or ""
    if not (src or "").strip():
        return 0
    new_xml, n = apply_ui_texts_to_kspedia_xml(src, entries, drop_unmatched=True)
    if n <= 0 and new_xml == src:
        return 0
    try:
        target.text = new_xml
    except Exception:
        pass
    if getattr(target, "text_block", None):
        try:
            target.text_block.clear()
            target.text_block.write(new_xml)
        except Exception:
            pass
    return int(n)

