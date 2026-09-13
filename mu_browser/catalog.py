# vim:ts=4:et
# <pep8 compliant>
"""Lightweight GameData PART / INTERNAL / FX / Assets scanner for MU browser."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import bpy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..cfgnode import ConfigNode, ConfigNodeError
from .thumbnails import THUMB_EXTENSION

# Disk catalog cache limits
DISK_CACHE_MAX_FILES = 10          # max .pkl files; oldest overwritten
DISK_CACHE_MAX_BYTES = 100 * 1024 * 1024  # 100 MB per file


STOCK_CATEGORY_ORDER = (
    "Pods",
    "FuelTank",
    "Engine",
    "Control",
    "Structural",
    "Coupling",
    "Payload",
    "Aero",
    "Ground",
    "Thermal",
    "Electrical",
    "Communication",
    "Science",
    "Cargo",
    "Utility",
    "Robotics",
    "Props",
    "Assets",
    "FX",
    "Internal",
)

OTHER_CATEGORY = "Other"

_cleanup_state = None
_cleanup_scheduled = False
_catalog_worker_active = False
_catalog_executor = None
_catalog_future = None
_catalog_scan_scheduled = False

# Live progress while scan_gamedata runs in the worker thread.
# Read from the main thread only (poll timer / panel).
_scan_progress = {
    "current": 0,
    "total": 0,
    "title": "",
    "active": False,
}


def catalog_scan_progress():
    """Return a snapshot: (current, total, title, active)."""
    return (
        int(_scan_progress.get("current") or 0),
        int(_scan_progress.get("total") or 0),
        str(_scan_progress.get("title") or ""),
        bool(_scan_progress.get("active")),
    )


def _scan_progress_set(current=None, total=None, title=None, active=None):
    if current is not None:
        _scan_progress["current"] = int(current)
    if total is not None:
        _scan_progress["total"] = int(total)
    if title is not None:
        _scan_progress["title"] = str(title)
    if active is not None:
        _scan_progress["active"] = bool(active)


_cache = {
    "root": "",
    "mtime": 0.0,
    "parts": [],
    "by_category": {},
}


@dataclass
class PartEntry:
    name: str
    title: str
    category: str
    cfg_path: str
    mu_path: str
    attach_rules: Tuple[int, ...] = field(default_factory=tuple)
    manufacturer: str = ""
    description: str = ""


def _prefs_gamedata() -> str:
    """Return configured KSP GameData path."""
    try:
        from ..preferences.preferences import Preferences
        return (Preferences().GameData or "").strip()
    except Exception:
        return ""


def _resolve_loc(text: str, locs: Dict[str, str]) -> str:
    """Resolve KSP localization keys; prefer English from locs / inline comments."""
    if not text:
        return ""
    t = text.strip()
    comment = ""
    if "//" in t:
        t, comment = t.split("//", 1)
        t = t.strip()
        comment = comment.strip()
    # Prefer explicit English comment (Squad style: #LOC_xxx // English Title)
    if comment:
        if "=" in comment:
            eng = comment.rsplit("=", 1)[-1].strip()
            if eng:
                return eng
        if not comment.startswith("#"):
            return comment
    if t.startswith("#"):
        resolved = locs.get(t) or locs.get(t.lstrip("#"))
        if resolved:
            return resolved
    return t


def _parse_attach_rules(cfg) -> Tuple[int, ...]:
    """Parse KSP attachRules into a tuple of integers."""
    if not cfg.HasValue("attachRules"):
        return ()
    raw = cfg.GetValue("attachRules") or ""
    out = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            out.append(0)
    return tuple(out)


def _norm(path: str) -> str:
    """Normalize a filesystem path for comparisons."""
    return os.path.normcase(os.path.normpath(path.replace("\\", "/")))


def _model_path_from_url(gamedata_root: str, url: str) -> str:
    """Resolve a KSP model URL to an existing .mu file."""
    if not url:
        return ""
    url = url.replace("\\", "/").strip()
    if url.lower().endswith(".mu"):
        candidate = os.path.join(gamedata_root, url)
    else:
        candidate = os.path.join(gamedata_root, url + ".mu")
    candidate = os.path.normpath(candidate)
    if os.path.isfile(candidate):
        return candidate.replace("\\", "/")
    return ""


def _first_model_from_node(node, gamedata_root: str) -> str:
    """Return the first MODEL or mesh referenced by a config node."""
    try:
        for model_node in node.GetNodes("MODEL") or []:
            if not model_node.HasValue("model"):
                continue
            url = (model_node.GetValue("model") or "").replace("\\", "/").strip()
            path = _model_path_from_url(gamedata_root, url)
            if path:
                return path
    except Exception:
        pass
    try:
        if node.HasValue("mesh"):
            mesh = (node.GetValue("mesh") or "").replace("\\", "/").strip()
            if mesh:
                if not mesh.lower().endswith(".mu"):
                    mesh += ".mu"
                return mesh
    except Exception:
        pass
    return ""


def _mu_from_part_cfg(cfg_path: str, cfg, gamedata_root: str) -> str:
    """Resolve the .mu model used by a PART config."""
    folder = os.path.dirname(cfg_path).replace("\\", "/")
    try:
        for node in cfg.GetNodes("MODEL") or []:
            url = (node.GetValue("model") or "").replace("\\", "/").strip()
            if not url:
                continue
            cand = _model_path_from_url(gamedata_root, url)
            if cand:
                return cand
    except Exception:
        pass
    try:
        if cfg.HasValue("mesh"):
            mesh = (cfg.GetValue("mesh") or "").replace("\\", "/").strip()
            if mesh:
                if not mesh.lower().endswith(".mu"):
                    mesh += ".mu"
                cand = os.path.join(folder, mesh).replace("\\", "/")
                if os.path.isfile(cand):
                    return cand
    except Exception:
        pass
    try:
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith(".mu"):
                return os.path.join(folder, fn).replace("\\", "/")
    except Exception:
        pass
    return ""


def _walk_cfgs(root: str):
    """Yield all .cfg files below GameData (skip hidden / @thumbs)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d and d[0] not in "._" and d != "@thumbs"
        ]
        for fn in filenames:
            if fn.lower().endswith(".cfg"):
                yield os.path.join(dirpath, fn)


def _cfg_needs_full_parse(path: str) -> bool:
    """Cheap pre-filter: skip configs without PART / INTERNAL / Localization."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(49152)
    except Exception:
        return True
    low = head.lower()
    return b"part" in low or b"internal" in low or b"localization" in low


def _load_cfg_safe(cfg_path: str):
    """Worker-safe ConfigNode load → (path, node|None).

    Single disk read: pre-filter on the same buffer, then parse in-memory.
    Avoids the old 2× I/O (pre-filter open + loadfile open).
    """
    p = cfg_path.replace(chr(92), "/")
    try:
        with open(p, "rb") as fh:
            data = fh.read()
    except Exception:
        return p, None
    head = data[:49152].lower()
    if (
        b"part" not in head
        and b"internal" not in head
        and b"localization" not in head
    ):
        return p, None
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        text = data.decode("utf-8", errors="replace")
        # Prefer string load to skip a second disk read
        if hasattr(ConfigNode, "load"):
            node = ConfigNode.load(text)
        else:
            node = ConfigNode.loadfile(p)
        # load() may return list of nodes — normalize to a root-like object
        if isinstance(node, list):
            root = ConfigNode("")
            root.nodes = node
            return p, root
        return p, node
    except Exception:
        try:
            return p, ConfigNode.loadfile(p)
        except Exception:
            return p, None


def _disk_cache_dir() -> str:
    """Stable cache dir (NOT bpy.app.tempdir — that changes every Blender session)."""
    # Prefer addon-local cache/ so it travels with the install
    try:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cache",
        )
        os.makedirs(base, exist_ok=True)
        if os.path.isdir(base):
            return base
    except Exception:
        pass
    base = os.path.join(os.path.expanduser("~"), ".cache", "io_object_mu")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = os.path.expanduser("~")
    return base


def _disk_cache_path(root: str) -> str:
    # NEVER use built-in hash() — PYTHONHASHSEED changes every process.
    import hashlib
    key = os.path.normcase(os.path.normpath(root)).encode("utf-8", "replace")
    h = hashlib.md5(key).hexdigest()[:16]
    return os.path.join(_disk_cache_dir(), "mu_catalog_%s.pkl" % h)


def _fingerprint_gamedata(root: str) -> tuple:
    """Fast invalidation key: cfg count + max mtime of top-level entries.

    os.walk counting .cfg is ~10–50× cheaper than ConfigNode-parsing them.
    Top-level mtimes catch added/removed mod folders under GameData.
    """
    n_cfg = 0
    max_mt = 0.0
    try:
        for name in os.listdir(root):
            try:
                max_mt = max(max_mt, float(os.path.getmtime(os.path.join(root, name))))
            except Exception:
                pass
    except Exception:
        pass
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d and d[0] not in "._" and d != "@thumbs"
            ]
            for fn in filenames:
                if fn.lower().endswith(".cfg"):
                    n_cfg += 1
    except Exception:
        pass
    return (int(n_cfg), float(max_mt))


def _disk_cache_load(root: str, mtime: float, fingerprint=None):
    try:
        import pickle
        path = _disk_cache_path(root)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            blob = pickle.load(fh)
        if not isinstance(blob, dict):
            return None
        if blob.get("root") != root:
            return None
        if not blob.get("parts"):
            return None
        # Prefer fingerprint (cfg count + top-level mtimes) over single root mtime
        fp = fingerprint
        if fp is None:
            fp = _fingerprint_gamedata(root)
        if blob.get("fingerprint") is not None and tuple(blob.get("fingerprint")) != tuple(fp):
            return None
        # Legacy caches without fingerprint: fall back to root mtime
        if blob.get("fingerprint") is None:
            if abs(float(blob.get("mtime") or 0) - float(mtime)) > 1e-3:
                return None
        return blob
    except Exception:
        return None


def _disk_cache_enforce_file_limit(cache_dir: str, keep_path: str = ""):
    """Keep at most DISK_CACHE_MAX_FILES catalog .pkl files; drop oldest."""
    try:
        files = []
        for fn in os.listdir(cache_dir):
            if not fn.startswith("mu_catalog_") or not fn.endswith(".pkl"):
                continue
            fp = os.path.join(cache_dir, fn)
            if not os.path.isfile(fp):
                continue
            try:
                mt = os.path.getmtime(fp)
            except Exception:
                mt = 0.0
            files.append((mt, fp))
        files.sort(key=lambda x: x[0])  # oldest first
        # Always keep the file we just wrote if provided
        keep_norm = os.path.normcase(os.path.normpath(keep_path)) if keep_path else ""
        while len(files) > DISK_CACHE_MAX_FILES:
            mt, fp = files.pop(0)
            if keep_norm and os.path.normcase(os.path.normpath(fp)) == keep_norm:
                files.append((mt, fp))  # rotate to end, try another
                if len(files) <= DISK_CACHE_MAX_FILES:
                    break
                # if all are keep, stop
                if all(
                    os.path.normcase(os.path.normpath(p)) == keep_norm
                    for _, p in files
                ):
                    break
                continue
            try:
                os.remove(fp)
                print("[mu_catalog] disk cache pruned oldest:", os.path.basename(fp), flush=True)
            except Exception:
                pass
    except Exception as e:
        print("[mu_catalog] disk cache prune failed:", type(e).__name__, e, flush=True)


def _disk_cache_save(cache_dict: dict):
    """Save catalog pickle; enforce 100MB size + 10-file limit."""
    try:
        import pickle
        root = cache_dict.get("root") or ""
        path = _disk_cache_path(root)
        # Build payload; if too large, truncate parts list until under limit
        parts = list(cache_dict.get("parts") or [])
        by_cat = dict(cache_dict.get("by_category") or {})
        n_full = len(parts)
        payload = dict(cache_dict)
        payload["parts"] = parts
        payload["by_category"] = by_cat
        payload["truncated"] = False
        blob = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
        if len(blob) > DISK_CACHE_MAX_BYTES:
            # Binary search how many parts fit
            lo, hi = 0, n_full
            best = 0
            best_blob = None
            while lo <= hi:
                mid = (lo + hi) // 2
                sub = parts[:mid]
                sub_cat = {}
                for p in sub:
                    sub_cat.setdefault(p.category, []).append(p)
                trial = dict(cache_dict)
                trial["parts"] = sub
                trial["by_category"] = sub_cat
                trial["truncated"] = True
                trial["full_part_count"] = n_full
                b = pickle.dumps(trial, protocol=pickle.HIGHEST_PROTOCOL)
                if len(b) <= DISK_CACHE_MAX_BYTES:
                    best = mid
                    best_blob = b
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best_blob is None or best <= 0:
                print(
                    "[mu_catalog] WARNING: disk cache exceeds %d MB even for 0 parts — skip save"
                    % (DISK_CACHE_MAX_BYTES // (1024 * 1024)),
                    flush=True,
                )
                return
            blob = best_blob
            print(
                "[mu_catalog] WARNING: disk cache truncated %d → %d parts "
                "(limit %d MB); remainder loads via full scan when needed"
                % (n_full, best, DISK_CACHE_MAX_BYTES // (1024 * 1024)),
                flush=True,
            )
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
        _disk_cache_enforce_file_limit(_disk_cache_dir(), keep_path=path)
    except Exception as e:
        print("[mu_catalog] disk cache save failed:", type(e).__name__, e, flush=True)


def _scan_internal_node(node, cfg_path: str, gamedata_root: str, parts: List[PartEntry], seen_internal: set, claimed_mu: set, locs: Dict[str, str]):
    """Scan an INTERNAL node and add its IVA model to the Internal category."""
    if not node.HasValue("name"):
        return
    name = (node.GetValue("name") or "").strip()
    if not name:
        return
    mu_path = _first_model_from_node(node, gamedata_root)
    if mu_path and not os.path.isabs(mu_path):
        mu_path = os.path.join(os.path.dirname(cfg_path), mu_path).replace("\\", "/")
        if not os.path.isfile(mu_path):
            mu_path = ""
    if not mu_path:
        return
    mu_key = _norm(mu_path)
    key = (name.lower(), mu_key)
    if key in seen_internal:
        return
    seen_internal.add(key)
    claimed_mu.add(mu_key)
    title = name
    try:
        if node.HasValue("title"):
            title = _resolve_loc(node.GetValue("title"), locs) or name
    except Exception:
        pass
    parts.append(
        PartEntry(
            name=name,
            title=title,
            category="Internal",
            cfg_path=cfg_path,
            mu_path=mu_path,
            attach_rules=(),
            manufacturer="",
            description="",
        )
    )


def _scan_fx_folder(root: str, parts: List[PartEntry], seen: set, claimed_mu: set):
    """Add all .mu files from Squad/FX as virtual FX entries."""
    fx_root = os.path.join(root, "Squad", "FX").replace("\\", "/")
    if not os.path.isdir(fx_root):
        return
    for dirpath, dirnames, filenames in os.walk(fx_root):
        dirnames[:] = [d for d in dirnames if d and d[0] not in "._"]
        for fn in filenames:
            if not fn.lower().endswith(".mu"):
                continue
            mu_path = os.path.join(dirpath, fn).replace("\\", "/")
            key_path = _norm(mu_path)
            key = "FX::" + key_path
            if key in seen:
                continue
            seen.add(key)
            claimed_mu.add(key_path)
            name = os.path.splitext(fn)[0]
            parts.append(
                PartEntry(
                    name=name,
                    title=name,
                    category="FX",
                    cfg_path="",
                    mu_path=mu_path,
                    attach_rules=(),
                    manufacturer="",
                    description="",
                )
            )


def _scan_assets(root: str, parts: List[PartEntry], claimed_mu: set, fx_paths: set):
    """Add standalone .mu files not belonging to PART, INTERNAL or FX."""
    seen_assets = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d and d[0] not in "._" and d != "@thumbs"
        ]
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == "Squad/FX" or rel_dir.startswith("Squad/FX/"):
            continue
        for fn in filenames:
            if not fn.lower().endswith(".mu"):
                continue
            mu_path = os.path.join(dirpath, fn).replace("\\", "/")
            key_path = _norm(mu_path)
            if key_path in claimed_mu or key_path in fx_paths:
                continue
            if key_path in seen_assets:
                continue
            seen_assets.add(key_path)
            base = os.path.splitext(fn)[0]
            rel = os.path.relpath(mu_path, root).replace("\\", "/")
            name = os.path.splitext(rel)[0]
            parts.append(
                PartEntry(
                    name=name,
                    title=base,
                    category="Props" if "props" in [p.lower() for p in mu_path.replace("\\", "/").split("/")] else "Assets",
                    cfg_path="",
                    mu_path=mu_path,
                    attach_rules=(),
                    manufacturer="",
                    description=rel,
                )
            )


def scan_gamedata(root: Optional[str] = None, *, force: bool = False) -> List[PartEntry]:
    """Scan GameData for PARTs, INTERNALs, FX and standalone Assets."""
    global _cache
    root = (root or _prefs_gamedata()).replace("\\", "/").rstrip("/")
    if not root or not os.path.isdir(root):
        _cache = {"root": root or "", "mtime": 0.0, "parts": [], "by_category": {}}
        return []
    try:
        mtime = os.path.getmtime(root)
    except Exception:
        mtime = 0.0
    if (
        not force
        and _cache.get("root") == root
        and abs(float(_cache.get("mtime") or 0) - mtime) < 1e-6
        and _cache.get("parts") is not None
    ):
        return list(_cache["parts"])
    locs: Dict[str, str] = {}
    parts: List[PartEntry] = []
    seen_parts = set()
    seen_internal = set()
    claimed_mu = set()
    import time as _time
    t0 = _time.perf_counter()
    _scan_progress_set(current=0, total=1, title="Loading categories", active=True)

    fp = None
    if not force:
        fp = _fingerprint_gamedata(root)
        disk = _disk_cache_load(root, mtime, fingerprint=fp)
        if disk is not None:
            _cache.clear()
            _cache.update(disk)
            n_parts = len(_cache.get("parts") or [])
            dt = _time.perf_counter() - t0
            print(
                "[mu_catalog] disk cache HIT (%d parts, %.2fs)"
                % (n_parts, dt),
                flush=True,
            )
            _scan_progress_set(
                current=n_parts,
                total=max(n_parts, 1),
                title="Categories ready %d/%d in %.1f s from cache"
                % (n_parts, n_parts, dt),
                active=False,
            )
            return list(_cache.get("parts") or [])
        print("[mu_catalog] disk cache MISS → full scan", flush=True)

    cfg_files = list(_walk_cfgs(root))
    # Fingerprint from this walk (no second os.walk) for save
    try:
        top_mt = 0.0
        for name in os.listdir(root):
            try:
                top_mt = max(top_mt, float(os.path.getmtime(os.path.join(root, name))))
            except Exception:
                pass
        fp = (len(cfg_files), float(top_mt))
    except Exception:
        fp = (len(cfg_files), 0.0)
    n_cfg = max(1, len(cfg_files))
    parsed_cfgs = []
    workers = min(8, max(2, (os.cpu_count() or 4)))
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for cfg_path, cfg in pool.map(_load_cfg_safe, cfg_files, chunksize=32):
                done += 1
                if cfg is not None:
                    parsed_cfgs.append((cfg_path, cfg))
                if (done & 63) == 0 or done == n_cfg:
                    _scan_progress_set(
                        current=min(done, max(n_cfg - 1, 1)),
                        total=n_cfg,
                        title="Loading categories",
                    )
    except Exception as e:
        print("[mu_catalog] parallel parse fallback:", type(e).__name__, e)
        for i, cfg_path in enumerate(cfg_files):
            p = cfg_path.replace(chr(92), "/")
            try:
                if not _cfg_needs_full_parse(p):
                    cfg = None
                else:
                    cfg = ConfigNode.loadfile(p)
            except Exception:
                cfg = None
            if cfg:
                parsed_cfgs.append((p, cfg))
            if (i & 31) == 0 or i + 1 == n_cfg:
                _scan_progress_set(
                    current=min(i + 1, max(n_cfg - 1, 1)),
                    total=n_cfg,
                    title="Loading categories",
                )

    # Localization: prefer English; never overwrite English with another language.
    _EN_LANG = {"en-us", "en", "en_us", "english", "en-gb", "en_gb"}

    def _is_en_lang(name: str) -> bool:
        n = (name or "").lower().replace("_", "-")
        return n in _EN_LANG or n.startswith("en-") or n.startswith("en_")

    def _ingest_loc_node(ln, *, is_english: bool):
        for loc in getattr(ln, "values", []) or []:
            key = getattr(loc, "name", None)
            val = getattr(loc, "value", None)
            if not key or val is None:
                continue
            if isinstance(val, str) and "//" in val:
                val = val.split("//", 1)[0].strip()
            if not val:
                continue
            if is_english:
                locs[key] = val
            elif key not in locs:
                locs[key] = val

    for cfg_path, cfg in parsed_cfgs:
        for node in cfg.nodes:
            try:
                nname = node.name
            except Exception:
                continue
            if nname != "Localization":
                continue
            try:
                lang_nodes = list(getattr(node, "nodes", []) or [])
                en_nodes = [ln for ln in lang_nodes if _is_en_lang(getattr(ln, "name", ""))]
                other_nodes = [ln for ln in lang_nodes if ln not in en_nodes]
                for ln in en_nodes:
                    _ingest_loc_node(ln, is_english=True)
                for ln in other_nodes:
                    _ingest_loc_node(ln, is_english=False)
            except Exception:
                pass

    # Process the already parsed CFG objects.
    n_parsed = max(1, len(parsed_cfgs))
    for i, (cfg_path, cfg) in enumerate(parsed_cfgs):
        if (i & 31) == 0 or i + 1 == n_parsed:
            _scan_progress_set(
                current=max(n_cfg - 1, 1),
                total=n_cfg,
                title="Loading categories",
            )
        for node in cfg.nodes:
            try:
                nname = node.name
            except Exception:
                continue
            if nname == "INTERNAL":
                try:
                    _scan_internal_node(
                        node, cfg_path, root, parts,
                        seen_internal, claimed_mu, locs,
                    )
                except Exception as e:
                    print(
                        "[mu_catalog] INTERNAL scan warning:",
                        cfg_path, type(e).__name__, e,
                    )
                continue
            if nname != "PART":
                continue
            try:
                if not node.HasValue("name"):
                    continue
                name = (node.GetValue("name") or "").replace("_", ".")
                if not name or name in seen_parts:
                    continue
                seen_parts.add(name)
                title_raw = node.GetValue("title") if node.HasValue("title") else name
                title = _resolve_loc(title_raw, locs) or name
                cat_raw = (node.GetValue("category") or "").strip() if node.HasValue("category") else ""
                path_parts = [p.lower() for p in cfg_path.replace("\\", "/").split("/")]
                if "internal" in path_parts:
                    category = "Internal"
                elif "props" in path_parts:
                    category = "Props"
                elif "assets" in path_parts:
                    category = "Assets"
                else:
                    category = cat_raw if cat_raw else OTHER_CATEGORY
                    if category.lower() in {"none", "n/a", ""}:
                        category = OTHER_CATEGORY
                mu_path = _mu_from_part_cfg(cfg_path, node, root)
                if not mu_path:
                    continue
                claimed_mu.add(_norm(mu_path))
                manu = _resolve_loc(node.GetValue("manufacturer"), locs) if node.HasValue("manufacturer") else ""
                desc = _resolve_loc(node.GetValue("description"), locs) if node.HasValue("description") else ""
                parts.append(
                    PartEntry(
                        name=name, title=title, category=category,
                        cfg_path=cfg_path, mu_path=mu_path,
                        attach_rules=_parse_attach_rules(node),
                        manufacturer=manu, description=desc,
                    )
                )
            except Exception as e:
                print(
                    "[mu_catalog] PART scan warning:",
                    cfg_path, type(e).__name__, e,
                )
    # FX models are claimed before scanning generic Assets.
    _scan_progress_set(current=max(n_cfg - 1, 1), total=n_cfg, title="Loading categories")
    before_fx = set(claimed_mu)
    _scan_fx_folder(root, parts, set(), claimed_mu)
    fx_paths = claimed_mu - before_fx
    # Anything left over is a standalone asset.
    _scan_assets(root, parts, claimed_mu, fx_paths)
    parts.sort(key=lambda p: ((p.title or p.name).lower(), p.name.lower()))
    by_cat: Dict[str, List[PartEntry]] = {}
    for p in parts:
        by_cat.setdefault(p.category, []).append(p)
    _cache = {
        "root": root,
        "mtime": mtime,
        "fingerprint": fp,
        "parts": parts,
        "by_category": by_cat,
    }
    n_parts = len(parts)
    dt = _time.perf_counter() - t0
    ready_msg = "Categories ready %d/%d in %.1f s" % (n_parts, n_parts, dt)
    _scan_progress_set(
        current=n_parts,
        total=max(n_parts, 1),
        title=ready_msg,
        active=False,
    )
    print(ready_msg, flush=True)
    if not _catalog_worker_active:
        schedule_thumbnail_cleanup(root, parts, mtime)
    try:
        _disk_cache_save(_cache)
        print(
            "[mu_catalog] disk cache SAVED (%d parts)" % n_parts,
            flush=True,
        )
    except Exception as e:
        print("[mu_catalog] disk cache save failed:", type(e).__name__, e, flush=True)
    return list(parts)



def schedule_thumbnail_cleanup(root: str, parts: List[PartEntry], mtime: float):
    """Validate/remove orphan thumbnails asynchronously in small chunks.

    The old implementation did a second complete GameData walk and then
    scanned/deleted the thumbnail cache synchronously while opening MU.
    This keeps the same cleanup and diagnostic line, but spreads the work
    across Blender timer ticks so the viewport remains responsive.
    """
    global _cleanup_state, _cleanup_scheduled
    thumb_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cache", "thumbnails"
    )
    if _cleanup_scheduled and _cleanup_state and _cleanup_state.get("root") == root and _cleanup_state.get("mtime") == mtime:
        return
    _cleanup_scheduled = True
    _cleanup_state = {
        "root": root,
        "mtime": mtime,
        "parts": parts,
        "thumb_dir": thumb_dir,
        "walk": os.walk(root),
        "all_mu": set(),
        "files": None,
        "used": None,
        "phase": "mu",
    }
    def tick():
        global _cleanup_scheduled, _cleanup_state
        st = _cleanup_state
        if not st:
            _cleanup_scheduled = False
            return None
        try:
            if st["phase"] == "mu":
                count = 0
                while count < 250:
                    try:
                        dirpath, _dirs, filenames = next(st["walk"])
                    except StopIteration:
                        st["phase"] = "thumbs"
                        break
                    for fn in filenames:
                        if fn.lower().endswith('.mu'):
                            st["all_mu"].add(_norm(os.path.join(dirpath, fn)))
                    count += 1
                return 0.01
            if st["phase"] == "thumbs":
                d = st["thumb_dir"]
                st["files"] = {f for f in os.listdir(d) if f.lower().endswith(('.png', '.webp', '.avif', '.exr'))} if os.path.isdir(d) else set()
                def thumb_name(p):
                    mu = os.path.splitext(os.path.basename(p.mu_path))[0]
                    mu = "".join(c if c.isalnum() or c in "-_." else "_" for c in mu).strip("_.")[:40] or "unknown"
                    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in (p.name or "part")).strip("_.")[:40] or "unknown"
                    return "%s_%s%s" % (mu, name, THUMB_EXTENSION) #return "%s_%s.png" % (mu, name)
                used_thumbs = {thumb_name(p) for p in st["parts"] if p.mu_path}
                used_thumbs.add("_default_thumbnail" + THUMB_EXTENSION) #used_thumbs.add("_default_thumbnail.png")
                st["used"] = used_thumbs
                catalogued_mu = {_norm(p.mu_path) for p in st["parts"] if p.mu_path}
                all_mu = st["all_mu"]
                print(
                    "\n[mu_catalog] MU: %d/%d THUMBS: %d/%d junk=%d"
                    % (
                        len(catalogued_mu),
                        len(all_mu),
                        len(st["files"] & used_thumbs),
                        len(st["files"]),
                        len(st["files"] - used_thumbs),
                    ),
                    flush=True,
                )
                st["delete"] = iter(st["files"] - used_thumbs)
                st["phase"] = "delete"
                return 0.01
            if st["phase"] == "delete":
                n = 0
                while n < 50:
                    try:
                        fn = next(st["delete"])
                    except StopIteration:
                        print("[mu_catalog] thumbnail cleanup complete", flush=True)
                        _cleanup_state = None
                        _cleanup_scheduled = False
                        return None
                    try:
                        os.remove(os.path.join(st["thumb_dir"], fn))
                    except Exception as e:
                        print("[mu_catalog] thumbnail delete failed:", fn, e)
                    n += 1
                return 0.01
        except Exception as e:
            print("[mu_catalog] thumbnail cleanup failed:", type(e).__name__, e)
            _cleanup_state = None
            _cleanup_scheduled = False
            return None
    try:
        bpy.app.timers.register(tick, first_interval=0.05)
    except Exception:
        _cleanup_scheduled = False
        _cleanup_state = None


def catalog_scan_running() -> bool:
    return _catalog_future is not None and not _catalog_future.done()


def schedule_catalog_scan(root: Optional[str] = None, *, force: bool = False):
    """Start GameData scanning in a worker; never block the MU panel."""
    global _catalog_executor, _catalog_future, _catalog_scan_scheduled
    global _catalog_worker_active

    root = (root or _prefs_gamedata()).replace("\\", "/").rstrip("/")
    if not root or not os.path.isdir(root):
        return False
    if catalog_scan_running():
        return True

    if _catalog_executor is None:
        _catalog_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="MU-Catalog"
        )

    def worker():
        global _catalog_worker_active
        _catalog_worker_active = True
        try:
            # This function only performs filesystem/config parsing. The
            # cleanup timer is explicitly disabled in worker mode.
            return scan_gamedata(root, force=force)
        finally:
            _catalog_worker_active = False

    _catalog_future = _catalog_executor.submit(worker)

    # Always attach the blue MU progress bar (operators job) if not already.
    # parts_in_category() used to call schedule_catalog_scan() alone, which
    # scanned with no visible progress — that was the "first load" bug.
    try:
        import bpy
        from . import operators as _ops
        if not _ops.job_is_active("catalog"):
            _ops._job_start(
                "catalog", "Loading categories", 100, context=bpy.context
            )
            _ops._ensure_job_timer()
    except Exception as e:
        print("[mu_catalog] progress attach:", type(e).__name__, e)

    if _catalog_scan_scheduled:
        return True
    _catalog_scan_scheduled = True

    def poll():
        global _catalog_future, _catalog_scan_scheduled
        fut = _catalog_future
        if fut is None:
            _catalog_scan_scheduled = False
            return None
        if not fut.done():
            # UI progress is driven by operators._job_timer_tick — keep this light
            return 0.2
        try:
            fut.result()
            # The worker has already atomically published _cache. Start the
            # thumbnail cleanup only on Blender's main thread.
            result = dict(_cache)
            schedule_thumbnail_cleanup(
                result["root"], result["parts"], result["mtime"]
            )
            try:
                from . import operators as _ops
                _ops.refresh_part_list_from_cached_catalog(bpy.context)
            except Exception:
                pass
        except Exception as e:
            print("[mu_catalog] background scan failed:", type(e).__name__, e)
        _catalog_future = None
        _catalog_scan_scheduled = False
        return None

    try:
        bpy.app.timers.register(poll, first_interval=0.05)
    except Exception:
        _catalog_scan_scheduled = False
    return True


def category_part_count(category: str) -> int:
    """Number of parts in a category from the in-memory cache only.

    Safe for EnumProperty callbacks: never starts a scan, never blocks.
    """
    try:
        return len((_cache.get("by_category") or {}).get(category, []) or [])
    except Exception:
        return 0


def categories() -> List[str]:

    """Return categories from the ready in-memory catalog.

    Called by Blender EnumProperty callbacks, so this must never perform
    filesystem work.
    """
    keys = set((_cache.get("by_category") or {}).keys())
    ordered = [c for c in STOCK_CATEGORY_ORDER if c in keys]
    rest = sorted(
        k for k in keys
        if k not in STOCK_CATEGORY_ORDER and k != OTHER_CATEGORY
    )
    if OTHER_CATEGORY in keys:
        rest.append(OTHER_CATEGORY)
    return ordered + rest

def all_parts() -> List[PartEntry]:
    """All catalog entries from the in-memory cache (never blocks)."""
    return list(_cache.get("parts") or [])


def parts_in_category(category: str) -> List[PartEntry]:
    """Return all entries belonging to a category.

    Never blocks the UI: if a background scan is in progress or the cache is
    still empty, return whatever is already published (often []).
    """
    if catalog_scan_running() or _catalog_worker_active:
        return list((_cache.get("by_category") or {}).get(category, []))
    # Cache miss with no worker → kick a background scan, do not block.
    root = (_prefs_gamedata() or "").replace("\\", "/").rstrip("/")
    if root and os.path.isdir(root):
        if _cache.get("root") != root or not _cache.get("parts"):
            schedule_catalog_scan(root, force=False)
            return list((_cache.get("by_category") or {}).get(category, []))
    return list((_cache.get("by_category") or {}).get(category, []))


def find_part(name: str) -> Optional[PartEntry]:
    """Find a catalog entry by its internal name."""
    if not catalog_scan_running() and not _catalog_worker_active:
        if not _cache.get("parts"):
            schedule_catalog_scan(force=False)
    for p in _cache.get("parts") or []:
        if p.name == name:
            return p
    return None


def invalidate_cache():
    """Clear the GameData catalog cache."""
    global _cache
    _cache = {"root": "", "mtime": 0.0, "parts": [], "by_category": {}}