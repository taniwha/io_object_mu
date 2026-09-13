# vim:ts=4:et
# <pep8 compliant>
"""Lazy OpenGL thumbnails for MU browser parts (disk-cached).

Priority when resolving an icon:
  1. Official KSP @thumbs PNG
  2. Our generated cache
  3. Generate thumbnail when ensure=True
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import json
from pathlib import Path
from typing import Dict, Optional

import bpy
from bpy.utils import previews


_CACHE_CLEARED = True # Clear not used thumbs cache, every Blender run

_pcoll = None
_ICON_SIZE = 128
THUMB_FORMAT = "WEBP" # PNG / WEBP / AVIF
THUMB_QUALITY = 90   # -1 = lossless or 0 to 100 to get compression
THUMB_EXTENSION = "." + THUMB_FORMAT.lower()
_DEFAULT_THUMB_NAME = "_default_thumbnail" + THUMB_EXTENSION
_DEFAULT_PREVIEW_KEY = "__MU_DEFAULT_THUMB__"

THUMB_FRAME_MARGIN = 1.72 # Extra padding around the fitted orthographic frame
THUMB_BRIGHTNESS_FACTOR = 1.2 # Scene lighting multiplier (Brightness)
THUMB_SOLID_BRIGHTNESS_FACTOR = 2.0 # Workbench/solid recovery shading brightness
THUMB_SHARPNESS = 20.0 # Shadow / sun-disk sharpness

# FX-only tunables.
FX_FRAME_MARGIN = 1.5 # padding when framing FX objects only (not full mesh)
FX_BRIGHTNESS_FACTOR = 0.35 # FX object emission only (not scene lights/world)

# KSP-like attach point marker tunables.
ATTACH_POINT_RADIUS = 0.06
ATTACH_POINT_ALPHA = 0.45
ATTACH_POINT_COLOR = (0.05, 1.0, 0.10, 1.0)

THUMB_CAM_DIR = (0.9, -1.1, 0.7) # Fixed isometric-ish camera direction (normalized later)

# Render validation / retry thresholds. A file existing on disk is NOT enough
THUMB_MIN_CONTENT_PIXELS = 180
THUMB_MIN_CONTENT_BBOX_AREA = 40
THUMB_EDGE_TOLERANCE = 1
THUMB_ALPHA_THRESHOLD = 0.02
THUMB_MAX_RETRIES = 2
THUMB_RETRY_MARGIN = 1.60

# --- Border / tight-frame detection (tweak these; leave THUMB_FRAME_MARGIN alone) ---
THUMB_BORDER_PX = 3 # floor (px) at any resolution (eg. 64→3  128→4  192→6  256→8  512→15, when set to 3)
THUMB_BORDER_FRAC = 0.03 # 3% of icon edge
THUMB_BORDER_ALPHA = 0.005 # Soft alpha for edge scan (catches AA fringes under THUMB_ALPHA_THRESHOLD).
THUMB_SPAN_TIGHT = 0.94 # Reject if content bbox spans this fraction of image H or W (extreme only).
THUMB_BORDER_FILL_MIN = 0.18 # Min fill to reject on border-touch alone (tall tanks have fill~0.3–0.4).
THUMB_EDGE_MIN_PIXELS = 3 # Min soft-opaque pixels on one edge band (scales with ICON/128).
THUMB_SPAN_SOFT = 0.80 # After a "valid" render, still widen once if span exceeds this (~5% margin).
THUMB_WIDER_ORTHO = 1.90 # Ortho widen factor on touches_border / soft-span retry.

# Developer diagnostics: render framing guides directly into generated thumbnails.
DEV_OVERLAY = 0 # Overlay, 0 = normal thumbnails, 1 = draw AABB/sphere/camera guides into PNG / WEBP / AVIF.
DEV_LOG_LEVEL = 0 # Console logs for thumbnail generation, 0 = quiet (errors only), 1 = full log.

# Last thumbnail-generation log lines (for ZIP_BUTTON mode 4 debug packs).
_CURRENT_THUMB_PART = None
_THUMB_LOG_BY_PART = {}  # part_name -> list[str]
_THUMB_LOG_MAX = 80


def _thumb_log_capture(line: str) -> None:
    """Store a line under the active part name for later zip export."""
    global _THUMB_LOG_BY_PART
    key = _CURRENT_THUMB_PART or "_last"
    buf = _THUMB_LOG_BY_PART.setdefault(key, [])
    buf.append(line)
    if len(buf) > _THUMB_LOG_MAX:
        del buf[: len(buf) - _THUMB_LOG_MAX]


def _dev_info(*args, **kwargs):
    """Console log when DEV_LOG_LEVEL=1 — independent of DEV_OVERLAY."""
    msg = " ".join(str(a) for a in args)
    line = "[mu_thumb][DEV] " + msg
    _thumb_log_capture(line)
    if DEV_LOG_LEVEL:
        print(line, flush=True)


def _info(*args, **kwargs):
    """Normal informational log; always available (not gated by overlay)."""
    msg = " ".join(str(a) for a in args)
    if msg.startswith("[mu_thumb]") or msg.startswith("plane-fit") or "ortho=" in msg:
        _thumb_log_capture(msg if msg.startswith("[") else "[mu_thumb] " + msg)
    print(*args, **kwargs)


def get_thumb_debug_log(part_name: str = None):
    """Return captured [mu_thumb] lines for part (or last run)."""
    if part_name and part_name in _THUMB_LOG_BY_PART:
        return list(_THUMB_LOG_BY_PART[part_name])
    if _CURRENT_THUMB_PART and _CURRENT_THUMB_PART in _THUMB_LOG_BY_PART:
        return list(_THUMB_LOG_BY_PART[_CURRENT_THUMB_PART])
    if "_last" in _THUMB_LOG_BY_PART:
        return list(_THUMB_LOG_BY_PART["_last"])
    # any most recent
    if _THUMB_LOG_BY_PART:
        return list(next(reversed(_THUMB_LOG_BY_PART.values())))
    return []


def _apply_thumb_format_settings(scene):
    settings = scene.render.image_settings
    settings.file_format = THUMB_FORMAT
    settings.color_mode = "RGBA"
    if THUMB_FORMAT == "PNG":
        settings.compression = 15 # PNG is always lossless.
    elif THUMB_FORMAT == "WEBP":
        settings.quality = 100 if THUMB_QUALITY < 0 else THUMB_QUALITY # quality 0..100; -1 = lossless.
    elif THUMB_FORMAT == "AVIF":
        settings.quality = 100 if THUMB_QUALITY < 0 else THUMB_QUALITY # Blender exposes quality, but no AVIF lossless flag.


# Persistent browser thumbnail preferences. Stored in Blender's user config,
_THUMB_PREFS_FILE = Path(bpy.utils.user_resource("CONFIG", path="io_object_mu", create=True)) / "thumbnail_prefs.json"
_INCLUDE_STOCK_THUMBS_DEFAULT = True


def _read_thumb_prefs():
    try:
        data = json.loads(_THUMB_PREFS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def include_stock_thumbs() -> bool:
    return bool(_read_thumb_prefs().get("include_stock_thumbs", _INCLUDE_STOCK_THUMBS_DEFAULT))


def set_include_stock_thumbs(value: bool):
    data = _read_thumb_prefs()
    data["include_stock_thumbs"] = bool(value)
    try:
        _THUMB_PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _THUMB_PREFS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, _THUMB_PREFS_FILE)
    except Exception as e:
        print("[mu_thumb] preference write failed:", type(e).__name__, e)


# Official KSP @thumbs index
_ksp_thumbs: Dict[str, str] = {}
_ksp_thumbs_root: str = ""
_ksp_thumbs_built: bool = False

_KSP_ICON_RE = re.compile(
    r"^(?P<name>.+)_icon(?P<var>0?)\.png$",
    re.IGNORECASE,
)

def _cache_dir() -> str:
    global _CACHE_CLEARED

    addon_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    cache_dir = os.path.join(
        addon_dir,
        "cache",
        "thumbnails",
    )
    if not _CACHE_CLEARED:
        if os.path.isdir(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)

        os.makedirs(cache_dir, exist_ok=True)
        _CACHE_CLEARED = True
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _safe_filename(s: str, max_len: int = 60) -> str:
    if not s:
        return "unknown"
    safe = "".join(
        c if c.isalnum() or c in "-_." else "_"
        for c in s
    )
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_.")[:max_len] or "unknown"


def _new_cache_basename(mu_path: str, part_name: str = "") -> str:
    base = os.path.splitext(
        os.path.basename(mu_path or "")
    )[0]
    mu_safe = _safe_filename(base, 40)
    part_safe = _safe_filename(
        part_name or "part",
        40,
    )
    return "%s_%s" % (mu_safe, part_safe)


def _cache_path(mu_path: str, part_name: str = "") -> str:
    return os.path.join(
        _cache_dir(),
        _new_cache_basename(
            mu_path,
            part_name,
        ) + THUMB_EXTENSION,
    )


def _unique_write_path(mu_path: str, part_name: str = "") -> str:
    base = _new_cache_basename(
        mu_path,
        part_name,
    )
    primary = os.path.join(
        _cache_dir(),
        base + THUMB_EXTENSION,
    )
    if not os.path.isfile(primary):
        return primary
    for i in range(1, 1000):
        cand = os.path.join(
            _cache_dir(),
            "%s_%d%s" % (base, i, THUMB_EXTENSION),
        )
        if not os.path.isfile(cand):
            return cand
    return primary

def _part_name_keys(part_name: str):
    """Yield lookup keys for a part name."""
    n = (part_name or "").strip()
    if not n:
        return
    seen = set()
    for k in (
        n,
        n.replace("_", "."),
        n.replace(".", "_"),
        n.lower(),
        n.replace("_", ".").lower(),
        n.replace(".", "_").lower(),
    ):
        if k and k not in seen:
            seen.add(k)
            yield k


def _gamedata_root() -> str:
    try:
        from ..preferences.preferences import Preferences
        return (
            Preferences().GameData
            or ""
        ).strip().replace(
            "\\",
            "/",
        ).rstrip("/")
    except Exception:
        return ""


def invalidate_ksp_thumbs_index():
    global _ksp_thumbs
    global _ksp_thumbs_root
    global _ksp_thumbs_built

    _ksp_thumbs = {}
    _ksp_thumbs_root = ""
    _ksp_thumbs_built = False


_ksp_index_job = None
_ksp_index_timer_active = False

def schedule_ksp_thumbs_index_build(gamedata_root: Optional[str] = None, *, force: bool = False):
    """Build the official @thumbs index incrementally."""
    global _ksp_index_job, _ksp_index_timer_active
    root = (gamedata_root or _gamedata_root()).replace("\\", "/").rstrip("/")
    if not root or not os.path.isdir(root):
        invalidate_ksp_thumbs_index()
        return
    if not force and _ksp_thumbs_built and _ksp_thumbs_root == root:
        return
    invalidate_ksp_thumbs_index()
    _ksp_index_job = {"root": root, "walk": os.walk(root), "index": {}}
    if _ksp_index_timer_active:
        return
    _ksp_index_timer_active = True
    def tick():
        global _ksp_index_job, _ksp_index_timer_active, _ksp_thumbs, _ksp_thumbs_root, _ksp_thumbs_built
        job = _ksp_index_job
        if not job:
            _ksp_index_timer_active = False
            return None
        try:
            for _ in range(80):
                try:
                    dirpath, dirnames, filenames = next(job["walk"])
                except StopIteration:
                    _ksp_thumbs = job["index"]
                    _ksp_thumbs_root = job["root"]
                    _ksp_thumbs_built = True
                    _ksp_index_job = None
                    _ksp_index_timer_active = False
                    return None
                dirnames[:] = [d for d in dirnames if d and (d[0] not in "._" or d == "@thumbs")]
                if os.path.basename(dirpath) != "@thumbs":
                    continue
                for fn in filenames:
                    if not fn.lower().endswith('.png'):
                        continue
                    m = _KSP_ICON_RE.match(fn)
                    if not m:
                        continue
                    path = os.path.join(dirpath, fn).replace('\\','/')
                    try:
                        if os.path.getsize(path) <= 64:
                            continue
                    except OSError:
                        continue
                    for key in _part_name_keys(m.group('name')):
                        job["index"].setdefault(key, path)
            return 0.01
        except Exception as e:
            print('[mu_thumb] @thumbs index failed:', type(e).__name__, e)
            _ksp_index_job = None
            _ksp_index_timer_active = False
            return None
    try:
        bpy.app.timers.register(tick, first_interval=0.15)
    except Exception:
        _ksp_index_timer_active = False

def build_ksp_thumbs_index(gamedata_root: Optional[str] = None, *, force: bool = False) -> int:
    global _ksp_thumbs
    global _ksp_thumbs_root
    global _ksp_thumbs_built
    root = (
        gamedata_root or _gamedata_root()
    ).replace(
        "\\",
        "/",
    ).rstrip("/")
    if not root or not os.path.isdir(root):
        _ksp_thumbs = {}
        _ksp_thumbs_root = root or ""
        _ksp_thumbs_built = True
        return 0
    if (
        not force
        and _ksp_thumbs_built
        and _ksp_thumbs_root == root
        and _ksp_thumbs
    ):
        return len(_ksp_thumbs)
    index: Dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d
            and (
                d[0] not in "._"
                or d == "@thumbs"
            )
        ]
        if os.path.basename(dirpath) != "@thumbs":
            continue
        for fn in filenames:
            if not fn.lower().endswith(".png"):
                continue
            m = _KSP_ICON_RE.match(fn)
            if not m:
                continue
            part = m.group("name")
            path = os.path.join(
                dirpath,
                fn,
            ).replace(
                "\\",
                "/",
            )
            if (
                not os.path.isfile(path)
                or os.path.getsize(path) <= 64
            ):
                continue
            for key in _part_name_keys(part):

                if key not in index:
                    index[key] = path

    _ksp_thumbs = index
    _ksp_thumbs_root = root
    _ksp_thumbs_built = True

    #print("[mu_thumb] KSP @thumbs index: %d icons under %s" % (len(index), root))
    return len(index)


def _dev_log(*args):
    if DEV_OVERLAY:
        print("[mu_thumb][DEV]", *args, flush=True)


def _dev_part_label(mu_path: str, part_name: str) -> str:
    return "%s | part=%s" % (os.path.basename(mu_path or "?"), part_name or "?")


def find_ksp_thumb(part_name: str) -> Optional[str]:
    if not include_stock_thumbs():
        return None
    if not part_name:
        _dev_log("@thumb MISS: empty part name")
        return None
    if not _ksp_thumbs_built:
        # The async index may not have finished yet. For correctness, build it
        # synchronously on first lookup so stock @thumb icons are never treated
        # as missing merely because the timer has not completed.
        root = _gamedata_root()
        if root and os.path.isdir(root):
            try:
                build_ksp_thumbs_index(root, force=False)
                _dev_log("@thumb index was not ready -> synchronous build, entries=", len(_ksp_thumbs))
            except Exception as e:
                _dev_log("@thumb synchronous index FAILED:", type(e).__name__, e)
    for key in _part_name_keys(part_name):
        path = _ksp_thumbs.get(key)
        if path and os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size > 64:
                return path
    return None


def _resolve_cache_path(mu_path: str, part_name: str = "") -> Optional[str]:
    ksp = find_ksp_thumb(part_name)
    if ksp:
        return ksp
    path = _cache_path(mu_path, part_name)
    if os.path.isfile(path):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size > 64:
            return path
    return None


def cached_icon_id_for_part(mu_path: str, part_name: str = "") -> int:
    """Return a registered preview icon, falling back to the default icon."""
    if not mu_path:
        return 0
    pcoll = _pcoll
    if pcoll is None:
        return 0
    key_src = "%s|%s" % (mu_path or "", part_name or "")
    key = hashlib.sha1(key_src.encode("utf-8", errors="replace")).hexdigest()[:20]
    try:
        item = pcoll.get(key)
        if item:
            return int(item.icon_id)

        # Preserve the original placeholder while background warmup has
        # not registered this part's real thumbnail yet.
        default = pcoll.get(_DEFAULT_PREVIEW_KEY)
        if default:
            return int(default.icon_id)
        default_path = _ensure_default_thumbnail()
        pcoll.load(_DEFAULT_PREVIEW_KEY, default_path, "IMAGE")
        return int(pcoll[_DEFAULT_PREVIEW_KEY].icon_id)
    except Exception:
        return 0


_preview_warmup_active = False
_preview_warmup_queue = []
_preview_warmup_pos = 0


def peek_icon_id(mu_path: str, part_name: str = "") -> int:
    """O(1) in-memory lookup only — never loads images or hits disk.

    Returns the real thumbnail if already registered, otherwise the default
    placeholder icon (so the grid is never empty/blank).
    """
    pcoll = _pcoll
    if pcoll is None:
        return 0
    if mu_path:
        key_src = "%s|%s" % (mu_path or "", part_name or "")
        key = hashlib.sha1(key_src.encode("utf-8", errors="replace")).hexdigest()[:20]
        try:
            item = pcoll.get(key)
            if item:
                return int(item.icon_id)
        except Exception:
            pass
    # Default placeholder (must already be in pcoll — ensure_previews loads it)
    try:
        default = pcoll.get(_DEFAULT_PREVIEW_KEY)
        if default:
            return int(default.icon_id)
    except Exception:
        pass
    return 0


def schedule_preview_warmup(br=None, *, chunk_size=8):
    """Warm cached thumbnails top→bottom, left→right without blocking the UI.

    template_icon_view opens instantly (icons may be 0); this fills them in
    place so the open popup populates row by row.
    """
    global _preview_warmup_active, _preview_warmup_queue, _preview_warmup_pos
    try:
        parts = list(br.parts)
        items = [(x.mu_path, x.name) for x in parts if x.mu_path]
    except Exception:
        return
    if not items:
        return
    # Prioritize currently exposed icons (preview_limit) so the open grid fills first
    try:
        lim = int(getattr(br, "preview_limit", 64) or 64)
        lim = max(64, min(lim, len(items)))
        head = items[:lim]
        tail = items[lim:]
        items = head + tail
    except Exception:
        pass
    sig = (getattr(br, "preview_limit", 64),) + tuple(items)
    current_sig = getattr(schedule_preview_warmup, "_sig", None)
    if sig != current_sig:
        schedule_preview_warmup._sig = sig
        _preview_warmup_queue = items
        _preview_warmup_pos = 0
    if _preview_warmup_active:
        return
    _preview_warmup_active = True

    def tick():
        global _preview_warmup_active, _preview_warmup_pos
        # First chunks a bit larger so the top rows of the 8x8 popup fill fast
        cs = int(chunk_size)
        if _preview_warmup_pos < 24:
            cs = max(cs, 12)
        end = min(_preview_warmup_pos + cs, len(_preview_warmup_queue))
        for path, name in _preview_warmup_queue[_preview_warmup_pos:end]:
            try:
                icon_id_for_part(path, name, ensure=False)
            except Exception:
                pass
        _preview_warmup_pos = end
        try:
            from .properties import bump_preview_enum_icons
            bump_preview_enum_icons()
        except Exception:
            pass
        try:
            br2 = bpy.context.window_manager.ksp_mu_browser
            cur = str(getattr(br2, "part_preview", "") or "")
            if cur.startswith("PART_"):
                br2.part_preview = cur
        except Exception:
            pass
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "VIEW_3D":
                        area.tag_redraw()
        except Exception:
            pass
        if _preview_warmup_pos >= len(_preview_warmup_queue):
            _preview_warmup_active = False
            return None
        return 0.02

    try:
        bpy.app.timers.register(tick, first_interval=0.01)
    except Exception:
        _preview_warmup_active = False


_preview_expand_active = False


def reset_preview_stream(br=None):
    """Call on category/filter change so the stream restarts from 64."""
    global _preview_expand_active, _preview_warmup_active
    _preview_expand_active = False
    # Allow warmup to rebuild for the new set
    try:
        schedule_preview_warmup._sig = None
    except Exception:
        pass
    if br is not None:
        try:
            from .properties import PREVIEW_INITIAL
            br.preview_limit = int(PREVIEW_INITIAL)
        except Exception:
            try:
                br.preview_limit = 64
            except Exception:
                pass


def schedule_preview_expand(br=None):

    """Grow preview_limit so the icon grid streams in like infinite scroll.

    Starts at 64; every tick adds PREVIEW_GROW_STEP until all parts are exposed.
    template_icon_view re-queries the enum on redraw, so the open popup gains
    rows as the limit rises — user can scroll through content as it arrives.
    """
    global _preview_expand_active
    if br is None:
        return
    try:
        from .properties import PREVIEW_INITIAL, PREVIEW_GROW_STEP
    except Exception:
        PREVIEW_INITIAL, PREVIEW_GROW_STEP = 64, 32
    try:
        n = len(br.parts)
    except Exception:
        return
    if n <= int(PREVIEW_INITIAL):
        try:
            br.preview_limit = n
        except Exception:
            pass
        return
    try:
        cur = int(getattr(br, "preview_limit", PREVIEW_INITIAL) or PREVIEW_INITIAL)
    except Exception:
        cur = int(PREVIEW_INITIAL)
    if cur >= n:
        return
    if _preview_expand_active:
        return
    _preview_expand_active = True

    def tick():
        global _preview_expand_active
        try:
            br2 = bpy.context.window_manager.ksp_mu_browser
            n2 = len(br2.parts)
            lim = int(getattr(br2, "preview_limit", PREVIEW_INITIAL) or PREVIEW_INITIAL)
            if lim >= n2 or n2 <= 0:
                _preview_expand_active = False
                return None
            # Grow in steps; first steps a bit larger so scroll gets content fast
            step = int(PREVIEW_GROW_STEP)  # default 32
            br2.preview_limit = min(n2, lim + step)
            # Warm icons for the newly exposed range and refresh open popup
            try:
                schedule_preview_warmup(br2, chunk_size=16)
            except Exception:
                pass
            try:
                cur_prev = str(getattr(br2, "part_preview", "") or "")
                if cur_prev.startswith("PART_"):
                    br2.part_preview = cur_prev
            except Exception:
                pass
            try:
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "VIEW_3D":
                            area.tag_redraw()
            except Exception:
                pass
            return 0.08
        except Exception as e:
            print("[mu_browser] preview expand:", type(e).__name__, e)
            _preview_expand_active = False
            return None

    try:
        bpy.app.timers.register(tick, first_interval=0.15)
    except Exception:
        _preview_expand_active = False



def reload_browser_icons(br=None, *, force: bool = True):
    """Drop cached preview entries and reload icons from disk.

    Required after background Thumbs/Regen: ImagePreview keeps the old
    pixels for the same key even when the PNG / WEBP / AVIF on disk was overwritten.
    """
    global _preview_warmup_active, _preview_warmup_queue, _preview_warmup_pos
    pcoll = ensure_previews()
    items = []
    try:
        if br is not None:
            items = [(x.mu_path, x.name) for x in br.parts if x.mu_path]
    except Exception:
        items = []
    for mu_path, part_name in items:
        key_src = "%s|%s" % (mu_path or "", part_name or "")
        key = hashlib.sha1(
            key_src.encode("utf-8", errors="replace")
        ).hexdigest()[:20]
        if key in pcoll:
            try:
                del pcoll[key]
            except Exception:
                try:
                    pcoll.pop(key, None)
                except Exception:
                    pass
        # Also drop any bpy image that may keep stale pixels for the cache path
        try:
            path = _resolve_cache_path(mu_path, part_name)
            if path:
                img = bpy.data.images.get(os.path.basename(path))
                if img is not None:
                    bpy.data.images.remove(img)
        except Exception:
            pass
    # Force warmup queue rebuild
    try:
        schedule_preview_warmup._sig = None
    except Exception:
        pass
    _preview_warmup_active = False
    _preview_warmup_queue = []
    _preview_warmup_pos = 0
    if br is not None:
        schedule_preview_warmup(br, chunk_size=12)
        # Nudge EnumProperty so template_icon_view picks up new icon_ids
        try:
            idx = int(getattr(br, "parts_index", 0) or 0)
            cur = str(getattr(br, "part_preview", "") or "")
            want = "PART_%d" % max(0, idx)
            br.part_preview = ""
            br.part_preview = cur if cur.startswith("PART_") else want
        except Exception:
            pass
    try:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()
                area.tag_redraw()
    except Exception:
        pass


def ensure_previews():
    global _pcoll
    if _pcoll is None:
        _pcoll = previews.new()
    # Always make sure the default placeholder is registered
    try:
        if _DEFAULT_PREVIEW_KEY not in _pcoll:
            path = _ensure_default_thumbnail()
            if path:
                _pcoll.load(_DEFAULT_PREVIEW_KEY, path, "IMAGE")
    except Exception as e:
        print("[mu_thumb] default preview load:", type(e).__name__, e)
    return _pcoll


def clear_previews():
    global _pcoll
    if _pcoll is not None:
        try:
            previews.remove(_pcoll)
        except Exception:
            pass
        _pcoll = None


def invalidate_preview_icons():
    """Drop cached per-part preview images without touching the default icon.

    A stock @thumb and our generated cache intentionally share the same
    in-memory preview key. Therefore changing Include stock thumbs must clear
    every per-part preview; otherwise Blender keeps displaying the old image
    until a later cache reload.
    """
    global _preview_warmup_active, _preview_warmup_queue, _preview_warmup_pos
    pcoll = ensure_previews()
    try:
        for key in list(pcoll.keys()):
            if key == _DEFAULT_PREVIEW_KEY:
                continue
            try:
                del pcoll[key]
            except Exception:
                try:
                    pcoll.pop(key, None)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        schedule_preview_warmup._sig = None
    except Exception:
        pass
    _preview_warmup_active = False
    _preview_warmup_queue = []
    _preview_warmup_pos = 0


def _is_cfg_marker_not_fx(name: str) -> bool:
    """Anything that is NOT a particle FX host (CoM, endcaps, clones, colliders)."""
    n = (name or "").lower()
    if not n:
        return False
    markers = (
        "coloffset", "comoffset", "copoffset",
        "co_l", "co_m", "co_p",
        "attach_point", "attachpoint",
        "node_stack", "node_attach", "node_collider",
        "endcap", "(clone)", "mirrored", "flipper",
        "endcapdummy", "endcapfoil", "commonhatch",
        "_collider", "boxcollider", "spherecollider",
        "collider",
    )
    return any(m in n for m in markers)


def _is_fx_preview_obj(o):
    """Thumbnail FX mode: ONLY real Blender particle systems or explicit .fx_* names.

    Secondary MODEL endcaps used to trip FX mode via mu_particles/mu_fx_preview
    custom properties and forced FX autozoom → transparent/edge-biased thumbs.
    """
    if o is None:
        return False
    try:
        name = o.name or ""
    except Exception:
        name = ""
    if _is_cfg_marker_not_fx(name):
        return False
    lname = name.lower()
    if ".cfg_preview" in lname:
        return False
    # Real particle systems only
    try:
        psys = getattr(o, "particle_systems", None)
        if psys is not None and len(psys) > 0:
            return True
    except Exception:
        pass
    if ".fx_preview" in lname or ".fx_emitter" in lname:
        return True
    if (lname.endswith("emitter") or ".emitter" in lname or "_emitter" in lname):
        return True
    # Do NOT trust mu_particles / mu_fx_preview alone — endcaps/clones often
    # inherit truthy flags without being particle FX.
    return False


def _collect_fx_objects(root=None):
    """
    Returns the FX belonging to the currently imported root.
    We don't search the entire user scene unnecessarily.
    """
    if root is not None:

        objs = [
            root
        ] + list(
            getattr(
                root,
                "children_recursive",
                [],
            ) or []
        )

    else:
        objs = list(
            bpy.context.scene.objects
        )

    result = []

    for obj in objs:

        try:
            if _is_fx_preview_obj(obj):
                result.append(obj)
        except Exception:
            pass
    return result


def _call_particle_show_operator(scene, root):
    """
    Attempts to execute EXACTLY the same operator that the user activates with the button:
    object.mu_toggle_particles_preview
    scope=ALL
    force=SHOW
    """

    fx_objects = _collect_fx_objects(root)

    if not fx_objects:
        _dev_info("particle operator: no FX")
        return []

    _dev_info("particle targets=", len(fx_objects))

    temporary_props = []

    for obj in fx_objects:

        try:
            had_prop = "mu_fx_preview" in obj
        except Exception:
            had_prop = False

        try:
            old_value = obj.get("mu_fx_preview")
        except Exception:
            old_value = None

        temporary_props.append(
            (
                obj,
                had_prop,
                old_value,
            )
        )

        try:
            obj["mu_fx_preview"] = True
        except Exception:
            pass

    result = None

    try:

        win = bpy.context.window

        if win is not None:
            try:
                win.scene = scene
            except Exception:
                pass

        try:
            bpy.context.view_layer.update()
        except Exception:
            pass

        _dev_info("particle SHOW")

        try:
            result = bpy.ops.object.mu_toggle_particles_preview(
                scope="ALL",
                force="SHOW",
            )

            _dev_info("particle result=", result)

        except Exception as e:

            print(
                "[mu_thumb] particle operator failed:",
                type(e).__name__,
                e,
            )

    finally:
        for (
            obj,
            had_prop,
            old_value,
        ) in temporary_props:

            try:

                if had_prop:
                    obj["mu_fx_preview"] = old_value

                else:
                    if "mu_fx_preview" in obj:
                        del obj["mu_fx_preview"]

            except Exception:
                pass
    shown = []
    hidden = []
    for obj in fx_objects:
        try:
            hidden_state = bool(
                obj.hide_viewport
            )

            try:
                hidden_state = hidden_state or bool(
                    obj.hide_get()
                )
            except Exception:
                pass

            if hidden_state:
                hidden.append(obj.name)
            else:
                shown.append(obj.name)

        except Exception:
            pass

    _dev_info("FX shown=", len(shown))

    _dev_info("FX hidden=", len(hidden))
    return fx_objects


def _show_fx_for_thumbnail(root):
    objs = _collect_fx_objects(root)
    shown = []
    for obj in objs:
        try:
            obj.hide_set(False)
        except Exception:
            pass
        try:
            obj.hide_viewport = False
        except Exception:
            pass
        try:
            obj.hide_render = False
        except Exception:
            pass
        shown.append(obj.name)
    print(
        "[mu_thumb] FX fallback SHOW:",
        len(shown),
        shown,
    )
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return shown


def _should_exclude_from_thumbnail(
    name: str, *, keep_shroud: bool = False, keep_fairing: bool = False
) -> bool:
    """Objects excluded from thumbnails and from camera framing.

    colliders, nodes, fairings (unless the part *is* a fairing), shrouds
    (unless the part is a shroud), higher LODs, .broken meshes, cfg/fx previews.
    """
    n = (name or "").lower()
    if not n:
        return False
    if n.startswith("node_") or n.startswith("node.") or ".node" in n:
        return True
    # Fairing *parts* must keep their fairing meshes; only exclude fairing
    # sub-objects on non-fairing parts (e.g. engine fairing base helpers).
    if "fairing" in n and not keep_fairing:
        return True
    if "shroud" in n and not keep_shroud:
        return True
    if ".broken" in n or n.endswith("broken") or "_broken" in n:
        return True
    for tag in ("lod1", "lod2", "lod3", "lod4", "lod 1", "lod 2", "lod 3"):
        if tag in n:
            return True
    if "cfg_preview" in n or "fx_preview" in n:
        return True
    # Do NOT exclude cloud/fog/smoke/billboard meshes — those ARE the visible
    # geometry for many FX-only or atmosphere parts. Wrongly treating them as
    # helpers produced "NO MESH" placeholders in the thumbnail grid.
    # Collider patterns — keep precise (do NOT use bare startswith "col",
    # that false-positives colony/collector/color/etc.).
    if (
        ".collider" in n
        or n.startswith("col_")
        or n.startswith("col1")
        or n.startswith("col2")
        or n.startswith("col3")
        or n.startswith("col4")
        or n.startswith("col5")
        or n.startswith("col6")
        or "collision" in n
        or "collider" in n
    ):
        return True
    try:
        from ..utils.utils import is_hideable_collider_name
        if is_hideable_collider_name(name or ""):
            return True
    except Exception:
        pass
    return False


def _hide_for_thumbnail(root, keep_shroud=False, keep_fairing=False):
    stack = [root] + list(getattr(root, "children_recursive", []) or [])
    for obj in stack:
        if _is_fx_preview_obj(obj):
            continue
        try:
            name = obj.name or ""
        except Exception:
            continue
        if not _should_exclude_from_thumbnail(
            name, keep_shroud=keep_shroud, keep_fairing=keep_fairing
        ):
            continue
        try:
            obj.hide_set(True)
        except Exception:
            pass
        try:
            obj.hide_render = True
        except Exception:
            pass


def _collect_frame_points(objs, *, keep_shroud: bool = False,
                          keep_fairing: bool = False,
                          include_evaluated: bool = True,
                          include_raw: bool = True,
                          include_helpers: bool = False,
                          ignore_hide: bool = False):
    """Collect conservative world-space bounds for rendered MU geometry.

    IMPORTANT: evaluated and raw bounds are collected independently. The old
    implementation stopped after the first successful evaluated bound-box,
    which meant a pathological/deferred evaluated bound could completely hide
    a perfectly valid raw mesh bound. For thumbnail framing we prefer the
    union of both representations.

    include_helpers=True is a last-resort path used when normal (visible)
    collection returns empty: it ignores collider/helper exclusion and hide
    flags so pure-collider, FreeIVA shell, transform-only or empty-mesh
    assets still produce a framed thumbnail instead of hard-failing.

    ignore_hide=True (preferred for *camera framing*): include meshes that are
    currently hide_viewport / hide_render because of B9 exclusive transforms.
    Framing the full structural AABB prevents 2–3× over-zoom when only a small
    transform is active; the *render* still uses the default variant visibility.
    """
    from mathutils import Vector

    points = []
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    except Exception:
        depsgraph = None

    for o in objs:
        try:
            otype = getattr(o, "type", "") or ""
            oname = o.name or ""
        except Exception:
            continue
        # Always skip B9 exclusive / variant-hidden meshes (alternative shells).
        # ignore_hide only re-includes viewport-hidden colliders helpers, NOT
        # mu_variant_hidden alternatives (those inflate AABB → too-small thumbs).
        try:
            if o.get("mu_variant_hidden") and not include_helpers:
                continue
        except Exception:
            pass
        if not ignore_hide and not include_helpers:
            try:
                if getattr(o, "hide_viewport", False) or getattr(o, "hide_render", False):
                    continue
                if hasattr(o, "visible_get") and not o.visible_get():
                    continue
            except Exception:
                pass

        # Last-resort: also use EMPTY / ARMATURE origins so transform-only
        # hierarchies still yield a non-empty point set (then may still fall
        # through to the labeled placeholder if bounds are degenerate).
        if include_helpers and otype in ("EMPTY", "ARMATURE"):
            try:
                points.append(o.matrix_world.translation.copy())
            except Exception:
                pass
            continue

        if otype != "MESH":
            continue
        if not include_helpers:
            if _should_exclude_from_thumbnail(
                oname, keep_shroud=keep_shroud, keep_fairing=keep_fairing
            ):
                continue
            nl = (oname or "").lower().split("∧")[0].split(".")[0].strip()
            if nl in ("plane", "node_bot", "node_top", "node_stack"):
                continue
            if not ignore_hide:
                try:
                    if bool(getattr(o, "hide_render", False)):
                        continue
                except Exception:
                    pass
                try:
                    if bool(o.hide_get()):
                        continue
                except Exception:
                    pass

        if include_evaluated and depsgraph is not None:
            try:
                eo = o.evaluated_get(depsgraph)
                eb = getattr(eo, "bound_box", None)
                emw = eo.matrix_world
                if eb and len(eb) == 8:
                    for corner in eb:
                        points.append(emw @ Vector(corner))
            except Exception:
                pass

        if include_raw:
            try:
                me = getattr(o, "data", None)
                mw = o.matrix_world.copy()
                if me is not None and len(me.vertices) > 0:
                    # Mesh.bound_box is the exact local AABB and gives all 8
                    # extrema without sampling vertices.
                    rb = getattr(me, "bound_box", None)
                    if rb and len(rb) == 8:
                        for corner in rb:
                            points.append(mw @ Vector(corner))
                    else:
                        # Last-resort vertex scan if bound_box is unavailable.
                        for v in me.vertices:
                            points.append(mw @ v.co)
            except Exception:
                pass

        # Object bound_box is only a final fallback when both requested sources
        # failed. It is intentionally not used as a substitute for raw mesh
        # geometry when raw data is available.
        if not points:
            try:
                for corner in o.bound_box:
                    points.append(o.matrix_world @ Vector(corner))
            except Exception:
                pass

    return points


def _filter_outlier_frame_points(points, *, keep_ratio=0.88):
    """Drop spatial outliers that blow up the thumbnail AABB.

    Distant helper Plane / node meshes (ReStock hemisphere) or a single
    mis-parented shell can expand extents 5–10× and leave the real part
    looking tiny. Keep the densest central cloud (~keep_ratio of points).
    """
    if not points or len(points) < 12:
        return points
    try:
        from mathutils import Vector
        xs = sorted(float(p.x) for p in points)
        ys = sorted(float(p.y) for p in points)
        zs = sorted(float(p.z) for p in points)
        mid = len(xs) // 2
        cx, cy, cz = xs[mid], ys[mid], zs[mid]
        dists = []
        for p in points:
            dx = float(p.x) - cx
            dy = float(p.y) - cy
            dz = float(p.z) - cz
            dists.append((dx * dx + dy * dy + dz * dz, p))
        dists.sort(key=lambda t: t[0])
        n_keep = max(8, int(len(dists) * float(keep_ratio)))
        n_keep = min(n_keep, len(dists))
        # Also reject anything beyond 4× the median distance among kept set
        med_d = dists[n_keep // 2][0] ** 0.5 if n_keep else 0.0
        limit = (med_d * 4.0) ** 2 if med_d > 1e-8 else dists[n_keep - 1][0]
        kept = [p for d2, p in dists[:n_keep] if d2 <= limit * 1.01]
        if len(kept) < 8:
            kept = [p for d2, p in dists[:n_keep]]
        if len(kept) < len(points) * 0.5:
            # Too aggressive — fall back
            return points
        return kept
    except Exception:
        return points


def _frame_extent(points):
    """Max axis-aligned half-extent (for comparing visible vs full AABB)."""
    if not points:
        return 0.0
    try:
        xs = [float(p.x) for p in points]
        ys = [float(p.y) for p in points]
        zs = [float(p.z) for p in points]
        return 0.5 * max(
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
            1e-9,
        )
    except Exception:
        return 0.0


def _frame_stats(points):
    """Return finite 3D AABB stats used to detect pathological bounds."""
    if not points:
        return None
    try:
        xs = [float(p.x) for p in points]
        ys = [float(p.y) for p in points]
        zs = [float(p.z) for p in points]
        vals = xs + ys + zs
        if not all(__import__('math').isfinite(v) for v in vals):
            return None
        mn = (min(xs), min(ys), min(zs))
        mx = (max(xs), max(ys), max(zs))
        size = max(mx[i] - mn[i] for i in range(3))
        return mn, mx, size
    except Exception:
        return None


def _load_render_metrics(path: str):
    """Validate rendered PNG / WEBP / AVIF dimensions and detect fully black / fully transparent frames.

    Crop/tiny geometric detection stays in the framing stage. Here we only reject
    pathological outputs that are 100% transparent (empty render / out-of-frame /
    camera too far) or 100% black (lighting/crash/zero emission). Those cases
    trigger a repair retry upstream.
    """
    img = None
    try:
        img = bpy.data.images.load(path, check_existing=False)
        w, h = int(img.size[0]), int(img.size[1])
        if w != int(_ICON_SIZE) or h != int(_ICON_SIZE):
            return {
                "valid": False,
                "reason": "wrong_dimensions",
                "size": (w, h),
                "expected": (int(_ICON_SIZE), int(_ICON_SIZE)),
            }

        # Fast content probe: count non-transparent and non-black pixels.
        # Fully empty (alpha~0) or fully black (RGB~0 with any alpha) frames
        # are treated as invalid so the caller can attempt a repair.
        try:
            px = list(img.pixels)  # flat RGBA float sequence
            n = len(px) // 4
            if n <= 0:
                return {
                    "valid": False,
                    "reason": "empty_pixels",
                    "size": (w, h),
                }
            alpha_thr = float(THUMB_ALPHA_THRESHOLD)
            black_thr = 0.02
            opaque = 0
            non_black = 0
            # Sample every 4th pixel for speed on large icons; full scan for 128.
            step = 1 if n <= 128 * 128 else 4
            for i in range(0, n, step):
                base = i * 4
                a = px[base + 3]
                if a > alpha_thr:
                    opaque += 1
                    r, g, b = px[base], px[base + 1], px[base + 2]
                    if r > black_thr or g > black_thr or b > black_thr:
                        non_black += 1
            # Scale counts when we subsampled.
            if step > 1:
                opaque *= step
                non_black *= step
            if opaque < int(THUMB_MIN_CONTENT_PIXELS):
                return {
                    "valid": False,
                    "reason": "fully_transparent",
                    "size": (w, h),
                    "opaque_pixels": opaque,
                    "non_black_pixels": non_black,
                }
            if non_black < int(THUMB_MIN_CONTENT_PIXELS):
                return {
                    "valid": False,
                    "reason": "fully_black",
                    "size": (w, h),
                    "opaque_pixels": opaque,
                    "non_black_pixels": non_black,
                }
            # Reject frames where content is glued to a border (classic
            # full-AABB / visible-subset mismatch).  COM of opaque pixels
            # must sit near the icon centre.
            try:
                step2 = step
                sx = sy = sn = 0
                minx = miny = 10**9
                maxx = maxy = -1
                for i in range(0, n, step2):
                    base = i * 4
                    if px[base + 3] <= alpha_thr:
                        continue
                    x = i % w
                    y = i // w
                    sx += x; sy += y; sn += 1
                    if x < minx: minx = x
                    if y < miny: miny = y
                    if x > maxx: maxx = x
                    if y > maxy: maxy = y
                if sn > 0:
                    com_x = sx / sn
                    com_y = sy / sn
                    # distance from centre in pixels
                    dist = ((com_x - w * 0.5) ** 2 + (com_y - h * 0.5) ** 2) ** 0.5
                    # content bbox fill of the icon
                    bw = max(1, maxx - minx + 1)
                    bh = max(1, maxy - miny + 1)
                    fill = (bw * bh) / float(w * h)
                    # edge glue: COM far from centre AND content small
                    if dist > min(w, h) * 0.28 and fill < 0.35:
                        return {
                            "valid": False,
                            "reason": "edge_biased",
                            "size": (w, h),
                            "opaque_pixels": opaque,
                            "com": (com_x, com_y),
                            "dist": dist,
                            "fill": fill,
                        }
                    # Border / tight-frame check (tunables: THUMB_BORDER_*).
                    border = max(
                        int(THUMB_BORDER_PX),
                        int(round(float(w) * float(THUMB_BORDER_FRAC))),
                    )
                    edge_a = float(THUMB_BORDER_ALPHA)
                    min_edge = max(
                        int(THUMB_EDGE_MIN_PIXELS),
                        int(round(float(w) / 128.0 * float(THUMB_EDGE_MIN_PIXELS))),
                    )
                    # Count soft-opaque pixels in each edge band (catches AA).
                    left = right = top = bottom = 0
                    for i in range(0, n, step2):
                        base = i * 4
                        if px[base + 3] <= edge_a:
                            continue
                        x = i % w
                        y = i // w
                        if x <= border:
                            left += 1
                        if x >= (w - 1 - border):
                            right += 1
                        if y <= border:
                            top += 1
                        if y >= (h - 1 - border):
                            bottom += 1
                    if step2 > 1:
                        left *= step2; right *= step2
                        top *= step2; bottom *= step2
                    edge_hit = {
                        "left": left, "right": right,
                        "top": top, "bottom": bottom,
                    }
                    touches = (
                        left >= min_edge or right >= min_edge
                        or top >= min_edge or bottom >= min_edge
                        or minx <= border or miny <= border
                        or maxx >= (w - 1 - border) or maxy >= (h - 1 - border)
                    )
                    span_h = (maxy - miny + 1) / float(h)
                    span_w = (maxx - minx + 1) / float(w)
                    tight_axis = (
                        span_h >= float(THUMB_SPAN_TIGHT)
                        or span_w >= float(THUMB_SPAN_TIGHT)
                    )
                    # Asymmetric pad: e.g. Oscar top≈31px bottom=0 while span<SOFT
                    # → soft pullback never fired. Reject when one side is flush
                    # and the opposite has large empty margin.
                    m_left = minx
                    m_right = (w - 1 - maxx)
                    m_bottom = miny   # Blender pixels: y=0 is bottom
                    m_top = (h - 1 - maxy)
                    side_margins = (m_left, m_right, m_bottom, m_top)
                    min_m = min(side_margins)
                    max_m = max(side_margins)
                    asymmetric = (
                        min_m <= border
                        and max_m >= max(border * 4, int(h * 0.12))
                    )
                    if asymmetric:
                        touches = True
                    if (touches or tight_axis) and (
                        fill > float(THUMB_BORDER_FILL_MIN) or tight_axis or asymmetric
                    ):
                        line = (
                            "[mu_thumb][DEV] border edges L=%d R=%d T=%d B=%d "
                            "margins LTRB=%s bbox=%s span=(%.3f,%.3f) fill=%.3f asym=%s"
                            % (left, right, top, bottom,
                               (m_left, m_top, m_right, m_bottom),
                               (minx, miny, maxx, maxy), span_w, span_h, fill,
                               asymmetric)
                        )
                        _thumb_log_capture(line)
                        if DEV_LOG_LEVEL:
                            print(line, flush=True)
                        return {
                            "valid": False,
                            "reason": "touches_border",
                            "size": (w, h),
                            "opaque_pixels": opaque,
                            "fill": fill,
                            "bbox": (minx, miny, maxx, maxy),
                            "span": (span_w, span_h),
                            "edges": edge_hit,
                            "margins": {
                                "left": m_left, "right": m_right,
                                "bottom": m_bottom, "top": m_top,
                            },
                            "asymmetric": asymmetric,
                        }
            except Exception:
                pass
            # Include span/bbox on success so soft-span pullback can react.
            ok = {
                "valid": True,
                "reason": "ok",
                "size": (w, h),
                "opaque_pixels": opaque,
                "non_black_pixels": non_black,
            }
            try:
                if sn > 0:
                    ok["bbox"] = (minx, miny, maxx, maxy)
                    ok["span"] = (
                        (maxx - minx + 1) / float(w),
                        (maxy - miny + 1) / float(h),
                    )
                    if DEV_LOG_LEVEL and max(ok["span"]) >= float(THUMB_SPAN_SOFT) * 0.95:
                        print(
                            "[mu_thumb][DEV] ok but tight span=%s bbox=%s"
                            % (ok["span"], ok["bbox"]),
                            flush=True,
                        )
            except Exception:
                pass
            return ok
        except Exception as e:
            # If pixel inspect fails, still accept on dimensions alone.
            return {
                "valid": True,
                "reason": "ok_dim_only:%s" % e,
                "size": (w, h),
            }
    except Exception as e:
        return {"valid": False, "reason": "image_inspect_error:%s" % e}
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass

def _fit_ortho_camera(cam_obj, cam_data, world_coords, margin=1.30, center_coords=None):
    """Fit an orthographic camera to the actual camera-plane extents.

    The old sphere fit is guaranteed not to crop only if *all rendered
    geometry* is represented by the supplied points. MU parts can have
    modifier/deformed bounds that are not present in the raw mesh AABB, so
    this function deliberately fits the supplied bounds conservatively and
    uses the exact same camera basis for measuring and rendering.
    """
    from mathutils import Vector

    if not world_coords:
        return False

    # Scale bounds from world_coords; look-at centre preferably from
    # *visible* content (center_coords). Using full AABB centre while the
    # rendered mesh is a small off-centre subset is what stuck station cores
    # / Ranger on the frame edge.
    mn = Vector((
        min(p.x for p in world_coords),
        min(p.y for p in world_coords),
        min(p.z for p in world_coords),
    ))
    mx = Vector((
        max(p.x for p in world_coords),
        max(p.y for p in world_coords),
        max(p.z for p in world_coords),
    ))
    c_src = center_coords if center_coords else world_coords
    c_mn = Vector((
        min(p.x for p in c_src),
        min(p.y for p in c_src),
        min(p.z for p in c_src),
    ))
    c_mx = Vector((
        max(p.x for p in c_src),
        max(p.y for p in c_src),
        max(p.z for p in c_src),
    ))
    center = (c_mn + c_mx) * 0.5

    view_dir = Vector(tuple(float(v) for v in THUMB_CAM_DIR))
    if view_dir.length < 1e-8:
        view_dir = Vector((1.0, -1.0, 0.8))
    view_dir.normalize()

    # Blender's Track -Z / Y camera basis, constructed explicitly so the
    # fitting math cannot disagree with the camera transform.
    forward = -view_dir
    up_ref = Vector((0.0, 0.0, 1.0))
    right = forward.cross(up_ref)
    if right.length < 1e-8:
        up_ref = Vector((0.0, 1.0, 0.0))
        right = forward.cross(up_ref)
    right.normalize()
    up = right.cross(forward)
    up.normalize()

    distance = max((mx - mn).length * 2.0, 2.0)
    cam_obj.location = center + view_dir * distance
    cam_obj.rotation_euler = (
        center - cam_obj.location
    ).to_track_quat("-Z", "Y").to_euler()
    try:
        cam_obj.rotation_mode = "XYZ"
    except Exception:
        pass

    # Plane extents for ORTHO scale: always from world_coords (may be full AABB).
    # 2D look-at centre: from center_src only (visible mesh). Mixing these is
    # required when scale uses full bounds but the rendered mesh is a subset.
    center_src = c_src  # already set above from center_coords or world_coords

    def _plane_minmax(pts, origin):
        lo_x = lo_y = float("inf")
        hi_x = hi_y = float("-inf")
        for p in pts:
            q = p - origin
            x = q.dot(right)
            y = q.dot(up)
            lo_x = min(lo_x, x); hi_x = max(hi_x, x)
            lo_y = min(lo_y, y); hi_y = max(hi_y, y)
        return lo_x, hi_x, lo_y, hi_y

    # Shift look-at so the *visible* content is centred in the camera plane
    c_min_x, c_max_x, c_min_y, c_max_y = _plane_minmax(center_src, center)
    cx2 = 0.5 * (c_min_x + c_max_x)
    cy2 = 0.5 * (c_min_y + c_max_y)
    if abs(cx2) > 1e-8 or abs(cy2) > 1e-8:
        center = center + right * cx2 + up * cy2
        cam_obj.location = center + view_dir * distance
        cam_obj.rotation_euler = (
            center - cam_obj.location
        ).to_track_quat("-Z", "Y").to_euler()

    # Scale from full world_coords relative to the (possibly shifted) centre
    min_x, max_x, min_y, max_y = _plane_minmax(world_coords, center)
    width = max(max_x - min_x, 0.05)
    height = max(max_y - min_y, 0.05)
    half_extent = max(width, height) * 0.5
    # Tall/thin parts (fuel tanks): projected aspect is high; a uniform margin
    # still clips AA soft edges on the long axis. Bump scale by aspect.
    aspect = max(width, height) / max(min(width, height), 1e-6)
    elong = 1.0 + 0.10 * min(max(aspect - 1.2, 0.0), 2.5)  # up to +25%
    ortho = max(2.0 * half_extent * float(margin) * elong, 0.1)

    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho
    try:
        cam_data.shift_x = 0.0
        cam_data.shift_y = 0.0
        cam_data.clip_start = 0.01
        cam_data.clip_end = max(distance * 4.0, (mx - mn).length * 10.0, 50.0)
    except Exception:
        pass

    print(
        "[mu_thumb] plane-fit center=%s extents=(%.4f, %.4f) ortho=%.4f margin=%.2f pts=%d"
        % (
            tuple(round(c, 4) for c in center),
            width,
            height,
            float(cam_data.ortho_scale),
            float(margin),
            len(world_coords),
        )
    )
    return True


def _dev_overlay_framing(scene, world_coords, center, view_dir, right, up, ortho_scale):
    """Render diagnostic framing guides when DEV_OVERLAY is enabled.

    Guides intentionally show several competing fitting ideas at once:
      - cyan-ish AABB wire box
      - magenta bounding sphere
      - yellow camera-plane rectangle
      - white centre cross
      - small camera-axis cross
    Everything is created in the temporary thumbnail scene and is therefore
    removed by the normal thumbnail cleanup pass.
    """
    if not DEV_OVERLAY or not world_coords:
        return

    from mathutils import Vector

    # Simple emission materials so guides remain visible on transparent PNG / WEBP / AVIFs.
    def mat(name, rgba):
        m = bpy.data.materials.new(name)
        m.diffuse_color = (*rgba, 1.0)
        m.use_nodes = True
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (*rgba, 1.0)
            bsdf.inputs["Emission Color"].default_value = (*rgba, 1.0)
            bsdf.inputs["Emission Strength"].default_value = 3.0
            bsdf.inputs["Roughness"].default_value = 0.35
        return m

    mats = {
        "box": mat("_mu_dbg_box", (0.1, 1.0, 1.0)),
        "sphere": mat("_mu_dbg_sphere", (1.0, 0.1, 1.0)),
        "frame": mat("_mu_dbg_frame", (1.0, 0.75, 0.05)),
        "cross": mat("_mu_dbg_cross", (1.0, 1.0, 1.0)),
        "axis": mat("_mu_dbg_axis", (1.0, 0.2, 0.1)),
    }

    def line_obj(name, pts, material, bevel=0.012):
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = bevel
        cu.bevel_resolution = 0
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for cp, p in zip(sp.points, pts):
            cp.co = (p.x, p.y, p.z, 1.0)
        ob = bpy.data.objects.new(name, cu)
        # Link into the same temporary collection as the camera.
        for c in scene.collection.children:
            if c.name.startswith("_mu_thumb"):
                c.objects.link(ob)
                break
        else:
            scene.collection.objects.link(ob)
        ob.data.materials.append(material)
        return ob

    mn = Vector((min(p.x for p in world_coords), min(p.y for p in world_coords), min(p.z for p in world_coords)))
    mx = Vector((max(p.x for p in world_coords), max(p.y for p in world_coords), max(p.z for p in world_coords)))

    # 1) World AABB (the exact box used to derive the centre).
    corners = [
        Vector((x, y, z))
        for x in (mn.x, mx.x)
        for y in (mn.y, mx.y)
        for z in (mn.z, mx.z)
    ]
    edges = ((0,1),(0,2),(0,4),(3,2),(3,1),(3,7),(5,1),(5,4),(5,7),(6,2),(6,4),(6,7))
    for a, b in edges:
        line_obj("_mu_dbg_aabb", (corners[a], corners[b]), mats["box"], 0.01)

    # 2) Bounding sphere around the same AABB centre.
    radius = max((mx - mn).length * 0.5, 0.05)
    # Two great circles are enough to make the sphere diagnostic obvious.
    for basis_a, basis_b in ((right, up), (right, view_dir), (up, view_dir)):
        pts = []
        for i in range(49):
            a = 6.283185307179586 * i / 48.0
            pts.append(center + radius * (basis_a * __import__('math').cos(a) + basis_b * __import__('math').sin(a)))
        line_obj("_mu_dbg_sphere", pts, mats["sphere"], 0.007)

    # 3) Actual camera-plane fit rectangle: ortho frame at the chosen scale.
    h = float(ortho_scale) * 0.5
    rect = [
        center + right * -h + up * -h,
        center + right *  h + up * -h,
        center + right *  h + up *  h,
        center + right * -h + up *  h,
    ]
    for i in range(4):
        line_obj("_mu_dbg_frame", (rect[i], rect[(i + 1) % 4]), mats["frame"], 0.012)

    # 4) Centre cross in the camera plane.
    cross = max(ortho_scale * 0.035, 0.03)
    line_obj("_mu_dbg_center", (center - right * cross, center + right * cross), mats["cross"], 0.012)
    line_obj("_mu_dbg_center", (center - up * cross, center + up * cross), mats["cross"], 0.012)

    # 5) Camera direction marker, just in front of the target.
    axis_len = max(ortho_scale * 0.12, 0.08)
    line_obj("_mu_dbg_axis", (center, center + view_dir * axis_len), mats["axis"], 0.014)

    _dev_info("DEV_OVERLAY: AABB+sphere+camera-frame+crosses")


def _autozoom_fx_camera(cam_obj, cam_data, fx_objects, margin=float(FX_FRAME_MARGIN)):
    from mathutils import Vector
    points = []
    for obj in fx_objects:
        try:
            if obj.hide_get() or obj.hide_viewport or obj.hide_render:
                continue
            # Bounding box object in world space
            for corner in obj.bound_box:
                points.append(obj.matrix_world @ Vector(corner))

        except Exception:
            continue

    if not points:
        return False

    mn = Vector((
        min(p.x for p in points),
        min(p.y for p in points),
        min(p.z for p in points),
    ))

    mx = Vector((
        max(p.x for p in points),
        max(p.y for p in points),
        max(p.z for p in points),
    ))

    size = (mx - mn).length

    if size <= 0.001:
        return False

    center = (mn + mx) * 0.5

    direction = cam_obj.location - center

    if direction.length < 0.001:
        direction = Vector((1.0, -1.0, 0.5))

    direction.normalize()

    cam_obj.location = center + direction * 3.5

    cam_obj.rotation_euler = (
        center - cam_obj.location
    ).to_track_quat("-Z", "Y").to_euler()

    # Autozoom.
    FX_ZOOM = 0.5
    cam_data.ortho_scale = max(size * margin * FX_ZOOM, 0.15)
    print(
        "[mu_thumb] FX AUTOZOOM:",
        "center=", tuple(center),
        "size=", round(size, 4),
        "ortho=", round(cam_data.ortho_scale, 4),
    )
    return True


def _setup_fx_camera(scene, root):
    from mathutils import Vector
    objs = [
        root
    ] + list(
        getattr(
            root,
            "children_recursive",
            [],
        ) or []
    )

    hosts = []

    for obj in objs:

        try:
            if obj.get("mu_particles"):
                hosts.append(obj)
                continue
        except Exception:
            pass

        try:
            if obj.get("mu_fx_preview"):
                hosts.append(obj)
        except Exception:
            pass

    # fallback
    if not hosts:
        hosts = [
            obj
            for obj in objs
            if _is_fx_preview_obj(obj)
        ]

    if not hosts:

        print(
            "[mu_thumb] FX camera: "
            "no particle hosts found"
        )

        return False

    points = []

    for obj in hosts:

        try:
            points.append(
                obj.matrix_world.translation.copy()
            )
        except Exception:
            pass

    if not points:

        print(
            "[mu_thumb] FX camera: "
            "no valid host positions"
        )

        return False

    center = (
        sum(
            points,
            Vector(
                (0.0, 0.0, 0.0)
            ),
        )
        / float(len(points))
    )

    cam = scene.camera

    if cam is None:
        return False

    distance = 3.5

    cam.location = (
        center
        + Vector(
            (
                distance * 0.7,
                -distance,
                distance * 0.35,
            )
        )
    )

    cam.rotation_euler = (
        center - cam.location
    ).to_track_quat(
        "-Z",
        "Y",
    ).to_euler()

    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 0.8
    print(
        "[mu_thumb] FX camera:",
        "hosts=", len(hosts),
        "center=", tuple(center),
        "distance=", distance,
        "ortho=", cam.data.ortho_scale,
    )
    return True


def _add_sun(col, name, location, target, energy, color=(1.0, 1.0, 1.0)):
    from mathutils import Vector
    data = bpy.data.lights.new(
        name,
        "SUN",
    )
    data.energy = float(energy) * float(THUMB_BRIGHTNESS_FACTOR)
    data.color = color
    try:
        # Higher THUMB_SHARPNESS → smaller sun disk → harder shadows
        base_angle = 0.15
        data.angle = max(0.02, base_angle / max(float(THUMB_SHARPNESS), 0.25))
    except Exception:
        pass

    obj = bpy.data.objects.new(
        name,
        data,
    )

    obj.location = location

    direction = (
        Vector(target)
        - Vector(location)
    )

    if direction.length > 1e-8:

        obj.rotation_euler = (
            direction
            .to_track_quat(
                "-Z",
                "Y",
            )
            .to_euler()
        )

    col.objects.link(obj)

    return obj


def _attach_nodes_under(root):
    """Return KSP attachment-node empties from the imported part."""
    if root is None:
        return []
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    out = []
    for obj in objs:
        try:
            if not str(obj.name or "").lower().startswith("node_"):
                continue
            if getattr(obj, "type", None) != "EMPTY":
                continue
            out.append(obj)
        except Exception:
            pass
    return out


def _add_attach_point_markers(scene, col, root):
    """Draw translucent green spheres at KSP attachment nodes."""
    nodes = _attach_nodes_under(root)
    if not nodes:
        return 0
    mat = bpy.data.materials.new("_mu_attach_point")
    mat.diffuse_color = (*ATTACH_POINT_COLOR[:3], ATTACH_POINT_ALPHA)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = ATTACH_POINT_COLOR
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = float(ATTACH_POINT_ALPHA)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.25
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = ATTACH_POINT_COLOR
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 0.35
    try:
        mat.surface_render_method = "DITHERED"
    except Exception:
        try:
            mat.surface_render_method = "BLENDED"
        except Exception:
            try:
                mat.blend_method = "BLEND"
            except Exception:
                pass
    count = 0
    for node in nodes:
        try:
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=16, ring_count=8,
                radius=float(ATTACH_POINT_RADIUS),
                location=node.matrix_world.translation,
            )
            marker = bpy.context.object
            marker.name = "_mu_attach_point_%03d" % count
            marker.data.materials.append(mat)
            for c in list(marker.users_collection):
                try:
                    c.objects.unlink(marker)
                except Exception:
                    pass
            col.objects.link(marker)
            count += 1
        except Exception:
            pass
    return count


def _scale_fx_object_brightness(fx_objects, factor):
    """Dim only FX objects' emission/materials — never scene lights or world.

    FX_BRIGHTNESS_FACTOR must not darken the rest of the part mesh. We walk
    materials used by *fx_objects* and scale Emission Strength (Principled /
    Emission nodes) and, as a fallback, any BACKGROUND-like strength sockets.
    """
    f = max(0.0, float(factor))
    if f == 1.0 or not fx_objects:
        return
    seen_mats = set()
    for obj in fx_objects:
        try:
            slots = getattr(obj, "material_slots", None) or []
        except Exception:
            slots = []
        for slot in slots:
            mat = getattr(slot, "material", None)
            if mat is None:
                continue
            mat_key = mat.as_pointer() if hasattr(mat, "as_pointer") else id(mat)
            if mat_key in seen_mats:
                continue
            seen_mats.add(mat_key)
            try:
                if not mat.use_nodes or mat.node_tree is None:
                    # Viewport diffuse fallback
                    try:
                        mat.diffuse_color = (
                            mat.diffuse_color[0] * f,
                            mat.diffuse_color[1] * f,
                            mat.diffuse_color[2] * f,
                            mat.diffuse_color[3],
                        )
                    except Exception:
                        pass
                    continue
                for node in mat.node_tree.nodes:
                    ntype = getattr(node, "type", "")
                    # Principled BSDF: Emission Strength
                    if ntype in ("BSDF_PRINCIPLED",):
                        for key in ("Emission Strength", "Emission"):
                            if key in node.inputs:
                                try:
                                    sock = node.inputs[key]
                                    # Strength is float; Emission color is rgba — only scale floats
                                    if hasattr(sock, "default_value") and isinstance(sock.default_value, (int, float)):
                                        sock.default_value = float(sock.default_value) * f
                                except Exception:
                                    pass
                    # Pure Emission shader
                    if ntype in ("EMISSION",):
                        if "Strength" in node.inputs:
                            try:
                                node.inputs["Strength"].default_value = (
                                    float(node.inputs["Strength"].default_value) * f
                                )
                            except Exception:
                                pass
            except Exception:
                pass


def _setup_world(scene):
    world = bpy.data.worlds.new(
        "_mu_thumb_world"
    )
    scene.world = world
    world.use_nodes = True

    nt = world.node_tree

    bg = None

    for n in nt.nodes:

        if n.type == "BACKGROUND":
            bg = n
            break

    if bg is None:

        bg = nt.nodes.new(
            "ShaderNodeBackground"
        )

        out = None

        for n in nt.nodes:

            if n.type == "OUTPUT_WORLD":
                out = n
                break

        if out is not None:
            nt.links.new(
                bg.outputs[0],
                out.inputs[0],
            )

    bg.inputs[0].default_value = (
        0.75,
        0.80,
        0.88,
        1.0,
    )

    bg.inputs[1].default_value = 0.8
    return world


def _camera_basis(cam_obj):
    from mathutils import Vector
    m = cam_obj.rotation_euler.to_matrix()
    right = (m @ Vector((1.0, 0.0, 0.0))).normalized()
    up = (m @ Vector((0.0, 1.0, 0.0))).normalized()
    view = (m @ Vector((0.0, 0.0, -1.0))).normalized()
    return right, up, view


def _overlay_for_points(scene, points, cam_obj, cam_data):
    if not DEV_OVERLAY or not points:
        return
    from mathutils import Vector
    mn = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    mx = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    center = (mn + mx) * 0.5
    right, up, view = _camera_basis(cam_obj)
    _dev_overlay_framing(scene, points, center, -view, right, up, cam_data.ortho_scale)


def _render_to_path(scene, path):
    """Render one thumbnail to a temporary PNG / WEBP / AVIF and validate it."""
    # Do not inherit resolution/border settings from the imported MU scene.
    # Blender's RenderSettings resolution_percentage and render-region flags directly
    # affect the actual output size.
    try:
        scene.render.resolution_x = int(_ICON_SIZE)
        scene.render.resolution_y = int(_ICON_SIZE)
        scene.render.resolution_percentage = 100
        scene.render.use_border = False
        scene.render.use_crop_to_border = False
        try:
            scene.render.film_transparent = True
            scene.render.overscan = 0.0
        except Exception:
            pass
        scene.render.pixel_aspect_x = 1.0
        scene.render.pixel_aspect_y = 1.0
        scene.render.border_min_x = 0.0
        scene.render.border_max_x = 1.0
        scene.render.border_min_y = 0.0
        scene.render.border_max_y = 1.0
    except Exception as e:
        print("[mu_thumb] render settings reset failed:", type(e).__name__, e)
    if DEV_OVERLAY:
        _dev_info("render", os.path.basename(path), "size=%dx%d" % (scene.render.resolution_x, scene.render.resolution_y))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    scene.render.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:
        _dev_info("render failed:", type(e).__name__, e)
        print("[mu_thumb] render failed:", type(e).__name__, e)
        return False, {"valid": False, "reason": "render_error:%s" % e}
    if not os.path.isfile(path) or os.path.getsize(path) <= 64:
        _dev_info("render missing_or_tiny_file", os.path.basename(path))
        return False, {"valid": False, "reason": "missing_or_tiny_file"}
    metrics = _load_render_metrics(path)
    _dev_info("validation", os.path.basename(path), metrics)
    return bool(metrics.get("valid")), metrics


def _commit_render(tmp_path, out_path):
    try:
        os.replace(tmp_path, out_path)
        return True
    except Exception as e:
        print("[mu_thumb] commit failed:", type(e).__name__, e)
        return False


_GPU_PROBE_DONE = False

def probe_eevee_gpu():
    """Report the active Blender GPU backend once, after a render initialized it."""
    global _GPU_PROBE_DONE
    if _GPU_PROBE_DONE or not DEV_OVERLAY:
        return
    try:
        import gpu
        p = gpu.platform
        print("[mu_thumb][DEV] GPU:", p.device_type_get(), "|", p.vendor_get(), "|", p.renderer_get(), "| backend=", p.backend_type_get(), flush=True)
        _GPU_PROBE_DONE = True
    except Exception:
        # Background Blender may not have an initialized GPU context until the
        # first EEVEE render. Never spam the console or affect thumbnail output.
        pass


def generate_thumbnail(
    mu_path: str,
    part_name: str = "",
    *,
    force: bool = False,
    show_attach_points: bool = False,
    progress_cb=None,
) -> Optional[str]:
    """Generate one thumbnail. Optional *progress_cb(frac, msg)* with frac in [0, 1).

    Stages (a few writes only — no measurable cost vs. import/render):
      0.05 prepare, 0.15 import, 0.40 objects, 0.55 frame, 0.70 render, 0.90 commit
    """
    def _p(frac, msg=""):
        if progress_cb is None:
            return
        try:
            progress_cb(float(frac), msg)
        except Exception:
            pass

    global _CURRENT_THUMB_PART
    _CURRENT_THUMB_PART = part_name or Path(mu_path).stem or "_last"
    _THUMB_LOG_BY_PART[_CURRENT_THUMB_PART] = []
    _dev_info("generate", os.path.basename(mu_path), part_name or "?")
    _p(0.05, "prepare")

    if (
        not mu_path
        or not os.path.isfile(mu_path)
    ):

        print(
            "[mu_thumb] FAIL: "
            "path missing or not a file"
        )

        return None

    if not force:
        existing = _resolve_cache_path(mu_path, part_name)
        if existing:
            if DEV_OVERLAY:
                if find_ksp_thumb(part_name) == existing:
                    _dev_log("SKIP GENERATION (official @thumb):", _dev_part_label(mu_path, part_name), "->", existing)
                else:
                    _dev_log("SKIP GENERATION (cache exists):", _dev_part_label(mu_path, part_name), "->", existing)
            _dev_info("cache hit", os.path.basename(existing))
            return existing
        if DEV_OVERLAY:
            _dev_log("NO EXISTING THUMB -> GENERATE:", _dev_part_label(mu_path, part_name))
    elif DEV_OVERLAY:
        _dev_log("FORCE REGEN -> ignore existing @thumb/cache:", _dev_part_label(mu_path, part_name))

    if force:
        out = _cache_path(
            mu_path,
            part_name,
        )
    else:
        out = _unique_write_path(
            mu_path,
            part_name,
        )

    print(
        "[mu_thumb] cache write:",
        os.path.basename(out),
    )
    _p(0.15, "import")

    from ..import_mu import import_mu
    from mathutils import Vector
    import contextlib

    prog_mod = None
    orig_bar = None

    try:

        from ..import_mu import progress_util as prog_mod

        orig_bar = getattr(
            prog_mod,
            "mu_progress_bar",
            None,
        )

        if orig_bar is not None:

            def _silent_bar(
                *_a,
                **_k,
            ):
                return contextlib.nullcontext()

            prog_mod.mu_progress_bar = (
                _silent_bar
            )

    except Exception:

        prog_mod = None
        orig_bar = None

    before = {
        "objects": set(
            bpy.data.objects.keys()
        ),
        "meshes": set(
            bpy.data.meshes.keys()
        ),
        "materials": set(
            bpy.data.materials.keys()
        ),
        "images": set(
            bpy.data.images.keys()
        ),
        "armatures": set(
            bpy.data.armatures.keys()
        ),
        "actions": set(
            bpy.data.actions.keys()
        ),
        "collections": set(
            bpy.data.collections.keys()
        ),
        "cameras": set(
            bpy.data.cameras.keys()
        ),
        "lights": set(
            bpy.data.lights.keys()
        ),
        "worlds": set(
            bpy.data.worlds.keys()
        ),
        "node_groups": set(
            bpy.data.node_groups.keys()
        ),
    }

    def _purge_new():
        for name in list(
            bpy.data.objects.keys()
        ):
            if name not in before["objects"]:

                o = bpy.data.objects.get(name)

                if o is not None:

                    try:
                        bpy.data.objects.remove(
                            o,
                            do_unlink=True,
                        )
                    except Exception:
                        pass

        for name in list(
            bpy.data.collections.keys()
        ):

            if name not in before["collections"]:

                c = bpy.data.collections.get(name)

                if c is not None:

                    try:
                        bpy.data.collections.remove(
                            c
                        )
                    except Exception:
                        pass

        for key, coll in (
            (
                "meshes",
                bpy.data.meshes,
            ),
            (
                "materials",
                bpy.data.materials,
            ),
            (
                "images",
                bpy.data.images,
            ),
            (
                "armatures",
                bpy.data.armatures,
            ),
            (
                "actions",
                bpy.data.actions,
            ),
            (
                "cameras",
                bpy.data.cameras,
            ),
            (
                "lights",
                bpy.data.lights,
            ),
            (
                "worlds",
                bpy.data.worlds,
            ),
            (
                "node_groups",
                bpy.data.node_groups,
            ),
        ):

            for name in list(coll.keys()):

                if name not in before[key]:

                    block = coll.get(name)

                    if block is not None:

                        try:
                            coll.remove(block)
                        except Exception:
                            pass

    win = bpy.context.window

    orig_scene = (
        win.scene
        if win
        else None
    )

    scene = bpy.data.scenes.new(
        "_mu_thumb_tmp"
    )

    try:

        if win is not None:
            win.scene = scene

        col = bpy.data.collections.new(
            "_mu_thumb_col"
        )

        scene.collection.children.link(col)

        root = None

        try:

            ret = import_mu(
                col,
                mu_path,
                False,
                False,
            )

            root = (
                ret[0]
                if isinstance(
                    ret,
                    (tuple, list),
                )
                else ret
            )

            print(
                "[mu_thumb] import_mu returned "
                "type=%s root=%s"
                % (
                    type(ret).__name__,
                    root,
                )
            )
            _p(0.40, "objects")

        except Exception as e:

            print(
                "[mu_thumb] FAIL import_mu:",
                type(e).__name__,
                e,
            )

            import traceback
            traceback.print_exc()

            return None

        finally:

            if (
                prog_mod is not None
                and orig_bar is not None
            ):

                try:
                    prog_mod.mu_progress_bar = (
                        orig_bar
                    )
                except Exception:
                    pass

        if root is None:

            print(
                "[mu_thumb] FAIL: "
                "import returned None"
            )

            return None

        try:

            if scene.view_layers:

                scene.view_layers[
                    0
                ].objects.active = None

        except Exception:
            pass

        # Default ModulePartVariants / B9: apply base subtype and wait for
        # depsgraph so GAMEOBJECTS visibility + textures match the in-game
        # default before framing/render (avoids mixed White+Metal meshes).
        _p(0.35, "variant")
        try:
            from ..import_mu.cfg_preview import (
                ensure_default_variant_for_preview,
                find_variant_root,
            )
            vroot = find_variant_root(root) or root
            if ensure_default_variant_for_preview(vroot, scene=scene):
                print("[mu_thumb] default variant applied")
            # Extra settle for secondary MODEL visibility / materials
            try:
                scene.frame_set(int(getattr(scene, "frame_current", 1) or 1))
            except Exception:
                pass
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass
            try:
                dg = bpy.context.evaluated_depsgraph_get()
                if dg is not None:
                    dg.update()
            except Exception:
                pass
        except Exception as e:
            print("[mu_thumb] variant setup:", type(e).__name__, e)

        fx_objects = _collect_fx_objects(
            root
        )
        # Drop non-particle objects (endcaps, clones, CoM, colliders)
        raw_fx = list(fx_objects or [])
        fx_objects = [o for o in raw_fx if _is_fx_preview_obj(o)]
        if raw_fx and not fx_objects:
            print(
                "[mu_thumb][DEV] FX candidates dropped (not real particles):",
                len(raw_fx),
                [getattr(o, "name", "?") for o in raw_fx[:8]],
                flush=True,
            )
        is_fx = bool(fx_objects)
        if is_fx:
            print(
                "[mu_thumb] FX detected:",
                len(fx_objects),
                [
                    o.name
                    for o in fx_objects
                ],
            )
            _call_particle_show_operator(scene, root)
            still_hidden = []
            for obj in fx_objects:
                try:
                    hidden = bool(
                        obj.hide_viewport
                    )
                    try:
                        hidden = hidden or bool(
                            obj.hide_get()
                        )
                    except Exception:
                        pass
                    if hidden:
                        still_hidden.append(
                            obj.name
                        )
                except Exception:
                    pass
            if still_hidden:
                print(
                    "[mu_thumb] WARNING: "
                    "operator left FX hidden:",
                    still_hidden,
                )
                _show_fx_for_thumbnail(root)
            try:
                scene.frame_set(1)
            except Exception:
                pass
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass
            _dev_info("FX mode")
            keep_shroud = False
            keep_fairing = False
        else:
            _dev_info("normal mode")
            keep_shroud = False
            keep_fairing = False
            try:
                pn = (part_name or "").lower()
                keep_shroud = "shroud" in pn
                # Part *is* a fairing / fairing-base → keep fairing meshes visible
                keep_fairing = "fairing" in pn
            except Exception:
                pass

        cam_data = bpy.data.cameras.new(
            "_mu_thumb_cam"
        )
        cam_data.type = "ORTHO"
        cam_obj = bpy.data.objects.new(
            "_mu_thumb_cam",
            cam_data,
        )

        col.objects.link(cam_obj)
        scene.camera = cam_obj

        objs = [
            root
        ] + list(
            getattr(
                root,
                "children_recursive",
                [],
            ) or []
        )

        _p(0.50, "frame")
        print(
            "[mu_thumb] objects under root:",
            len(objs),
            [
                getattr(
                    o,
                    "name",
                    "?",
                )
                for o in objs[:8]
            ],
        )
        if is_fx:
            # FX mode: frame FX objects with FX_FRAME_MARGIN so the constant
            # actually controls FX thumb padding. Do NOT apply FX_FRAME_MARGIN
            # to the full part mesh (that was the "scales other elements" bug).
            fx_fit_points = _collect_frame_points(
                fx_objects, keep_shroud=False, include_evaluated=True, include_raw=True
            )
            if fx_fit_points:
                _dev_info("FX fit points (fx objs)=", len(fx_fit_points))
                if not _fit_ortho_camera(
                    cam_obj, cam_data, fx_fit_points, margin=float(FX_FRAME_MARGIN)
                ):
                    print("[mu_thumb] FX object fit FAILED")
                    fx_fit_points = None
            if not fx_fit_points:
                # Bounds from bound_box / autozoom on FX hosts
                print("[mu_thumb] FX: framing via FX object autozoom")
                if not _autozoom_fx_camera(
                    cam_obj, cam_data, fx_objects, margin=float(FX_FRAME_MARGIN)
                ):
                    # Last resort: whole part mesh with normal margin
                    print("[mu_thumb] FX autozoom FAILED, mesh fallback")
                    fx_fit_points = _collect_frame_points(
                        objs, keep_shroud=False, include_evaluated=True, include_raw=True
                    )
                    if fx_fit_points:
                        _fit_ortho_camera(
                            cam_obj, cam_data, fx_fit_points,
                            margin=float(THUMB_FRAME_MARGIN),
                        )
                else:
                    fx_fit_points = _collect_frame_points(
                        fx_objects, keep_shroud=False,
                        include_evaluated=True, include_raw=True,
                    )
        else:
            # Rest pose for animated parts (frame 0), then depsgraph update
            try:
                scene.frame_set(0)
            except Exception:
                try:
                    scene.frame_set(1)
                except Exception:
                    pass
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass

            # Mute actions so animated parents (heatshields etc.) don't
            # collapse matrix_world to ~zero at frame 0 during framing.
            _saved_actions = []
            for o in objs:
                try:
                    ad = o.animation_data
                    if ad is not None and ad.action is not None:
                        _saved_actions.append((o, ad.action))
                        ad.action = None
                except Exception:
                    pass
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass

            # IMPORTANT: hide the same helper/collider objects BEFORE collecting
            # framing points. Previously framing was calculated first and only
            # then _hide_for_thumbnail() was called. That meant a hidden helper
            # could define a gigantic AABB while the actual render contained only
            # a tiny visible mesh (the exact symptom seen with restock-wheel-1-T).
            try:
                _hide_for_thumbnail(
                    root, keep_shroud=keep_shroud, keep_fairing=keep_fairing
                )
            except Exception as e:
                print("[mu_thumb] hide_for_thumbnail before fit:", e)
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass

            # Framing strategy:
            #  1) visible meshes (what will actually render after default variant)
            #  2) full structural AABB (ignore_hide) for when exclusive B9 left
            #     only a tiny shell visible (over-zoom case)
            #  3) drop spatial outliers (distant Plane / mis-parented mesh)
            # Prefer visible when extents are similar; use full only when
            # visible is << full (ratio < 0.4).
            center_coords = None
            vis_coords = _collect_frame_points(
                objs, keep_shroud=keep_shroud, keep_fairing=keep_fairing,
            )
            full_coords = _collect_frame_points(
                objs, keep_shroud=keep_shroud, keep_fairing=keep_fairing,
                ignore_hide=True,
            )
            vis_coords = _filter_outlier_frame_points(vis_coords)
            full_coords = _filter_outlier_frame_points(full_coords)
            use_coords = None
            ve = _frame_extent(vis_coords)
            fe = _frame_extent(full_coords)
            center_coords = None
            if vis_coords and full_coords:
                # Prefer VISIBLE bounds for scale. full AABB (ignore_hide) used to
                # include B9-hidden alternatives (AIMP Flat vs Points) → ~2× small.
                # Only use full when visible is pathologically tiny.
                if ve > 1e-6 and len(vis_coords) >= 24 and ve >= max(0.08, 0.15 * fe):
                    use_coords = vis_coords
                    if fe > 1e-6 and (ve / fe) < 0.55:
                        print(
                            "[mu_thumb] frame=vis (skip full inflate ve=%.3f fe=%.3f ratio=%.2f)"
                            % (ve, fe, ve / fe),
                            flush=True,
                        )
                elif ve > 1e-6 and fe > 1e-6 and (ve / fe) < 0.15 and len(vis_coords) < 24:
                    use_coords = full_coords
                    center_coords = vis_coords
                    print(
                        "[mu_thumb] frame=full+vis_center emergency (ve=%.3f fe=%.3f)"
                        % (ve, fe),
                        flush=True,
                    )
                else:
                    use_coords = vis_coords if vis_coords else full_coords
            elif vis_coords:
                use_coords = vis_coords
            elif full_coords:
                use_coords = full_coords
            if not use_coords:
                # Last-resort: include helpers/colliders (and ignore hide flags)
                # so pure-collider, FreeIVA shell, transform-only or empty-mesh
                # assets still get a framed thumbnail instead of hard-failing.
                use_coords = _collect_frame_points(
                    objs, keep_shroud=keep_shroud, keep_fairing=keep_fairing,
                    include_evaluated=True, include_raw=True,
                    include_helpers=True,
                )
                use_coords = _filter_outlier_frame_points(use_coords)
                if use_coords:
                    print(
                        "[mu_thumb][DEV] no visible frame points -> "
                        "last-resort framing with helpers/colliders, pts=",
                        len(use_coords),
                        flush=True,
                    )
                    # Unhide helpers so the render actually contains geometry.
                    for o in objs:
                        try:
                            if getattr(o, "type", "") != "MESH":
                                continue
                            o.hide_set(False)
                            o.hide_render = False
                        except Exception:
                            pass
                    try:
                        bpy.context.view_layer.update()
                    except Exception:
                        pass
                else:
                    # Nothing renderable (pure collider / depth mask / empty root /
                    # transform-only). Write a transparent labeled placeholder so
                    # the grid is never blank and the user sees *why*.
                    label = _classify_empty_geometry(objs, root)
                    # Detailed dump so "NO MESH" on parts that look like they
                    # have geometry is debuggable (nested IVA, excluded fairing,
                    # 0-vert mesh, etc.).
                    try:
                        dump = []
                        for o in (objs or [])[:12]:
                            try:
                                t = getattr(o, "type", "?")
                                n = o.name or "?"
                                nv = 0
                                if t == "MESH" and getattr(o, "data", None) is not None:
                                    nv = len(o.data.vertices)
                                dump.append("%s:%s:v%d" % (t, n, nv))
                            except Exception:
                                pass
                        print(
                            "[mu_thumb][DEV] no visible frame points -> "
                            "empty-geometry placeholder label=%s objs=%s"
                            % (label, dump),
                            flush=True,
                        )
                    except Exception:
                        print(
                            "[mu_thumb][DEV] no visible frame points -> "
                            "empty-geometry placeholder label=%s"
                            % label,
                            flush=True,
                        )
                    if _write_empty_geometry_placeholder(out, label):
                        return out
                    print("[mu_thumb] FAIL: no visible frame points")
                    return None

            ok = _fit_ortho_camera(
                cam_obj, cam_data, use_coords,
                margin=float(THUMB_FRAME_MARGIN),
                center_coords=center_coords,
            )
            if not ok:
                label = _classify_empty_geometry(objs, root)
                print(
                    "[mu_thumb][DEV] camera fit failed -> "
                    "empty-geometry placeholder label=%s"
                    % label,
                    flush=True,
                )
                if _write_empty_geometry_placeholder(out, label):
                    return out
                print("[mu_thumb] FAIL: camera fit")
                return None

            if DEV_OVERLAY:
                from mathutils import Vector
                _mn = Vector((min(p.x for p in use_coords), min(p.y for p in use_coords), min(p.z for p in use_coords)))
                _mx = Vector((max(p.x for p in use_coords), max(p.y for p in use_coords), max(p.z for p in use_coords)))
                _center = (_mn + _mx) * 0.5
                _view = Vector(tuple(float(v) for v in THUMB_CAM_DIR)).normalized()
                _forward = -_view
                _up_ref = Vector((0.0, 0.0, 1.0))
                _right = _forward.cross(_up_ref)
                if _right.length < 1e-8:
                    _up_ref = Vector((0.0, 1.0, 0.0))
                    _right = _forward.cross(_up_ref)
                _right.normalize()
                _up = _right.cross(_forward).normalized()
                _dev_overlay_framing(scene, use_coords, _center, _view, _right, _up, cam_data.ortho_scale)

        _setup_world(scene)
        if is_fx:
            from mathutils import Vector
            hosts = [
                o
                for o in fx_objects
                if o.get("mu_particles")
            ]
            if hosts:
                pts = [
                    o.matrix_world.translation.copy()
                    for o in hosts
                ]
                center = (
                    sum(
                        pts,
                        Vector(),
                    )
                    / float(len(pts))
                )
            else:
                center = (
                    cam_obj.location
                    + cam_obj.rotation_euler.to_matrix()
                    @ Vector(
                        (
                            0.0,
                            0.0,
                            -3.5,
                        )
                    )
                )
            light_size = 4.0
        else:
            light_size = max(
                cam_data.ortho_scale,
                0.05,
            )
            # Look-at point in front of the camera (same centre used for fit)
            center = (
                cam_obj.location
                + cam_obj.rotation_euler.to_matrix()
                @ Vector((0.0, 0.0, -max(light_size, 0.5)))
            )
        key_loc = (
            cam_obj.location.copy()
        )
        _add_sun(
            col,
            "_mu_thumb_key",
            key_loc,
            center,
            energy=2.0,
            color=(
                1.0,
                0.98,
                0.94,
            ),
        )
        fill_loc = Vector(
            (
                center.x - light_size * 1.1,
                center.y + light_size * 0.8,
                center.z + light_size * 0.4,
            )
        )
        _add_sun(
            col,
            "_mu_thumb_fill",
            fill_loc,
            center,
            energy=0.8,
            color=(
                0.75,
                0.82,
                1.0,
            ),
        )
        rim_loc = Vector(
            (
                center.x - light_size * 0.4,
                center.y + light_size * 1.2,
                center.z + light_size * 1.0,
            )
        )
        _add_sun(
            col,
            "_mu_thumb_rim",
            rim_loc,
            center,
            energy=1.0,
            color=(
                1.0,
                1.0,
                1.0,
            ),
        )
        if is_fx:
            _scale_fx_object_brightness(fx_objects, FX_BRIGHTNESS_FACTOR)
        if show_attach_points:
            marker_count = _add_attach_point_markers(scene, col, root)
            if marker_count:
                _dev_info("attach points:", marker_count)
        _dev_info("lights+world set")
        scene.render.resolution_x = _ICON_SIZE
        scene.render.resolution_y = _ICON_SIZE
        scene.render.resolution_percentage = 100
        scene.render.filepath = out
        _apply_thumb_format_settings(scene)
        scene.render.film_transparent = True
        try:
            scene.render.engine = ("BLENDER_EEVEE_NEXT")
        except Exception:
            try:
                scene.render.engine = ("BLENDER_EEVEE")
            except Exception:
                pass
        try:
            scene.view_settings.view_transform = (
                "Standard"
            )
            scene.view_settings.look = (
                "None"
            )
            scene.view_settings.exposure = 0.0
            scene.view_settings.gamma = 1.0
        except Exception:
            pass
        if is_fx:
            hidden_before_render = []
            for obj in fx_objects:
                try:
                    hidden = bool(
                        obj.hide_viewport
                    )
                    try:
                        hidden = hidden or bool(
                            obj.hide_get()
                        )
                    except Exception:
                        pass
                    if hidden:
                        hidden_before_render.append(
                            obj.name
                        )
                except Exception:
                    pass
            _dev_info("FX hidden before render:", hidden_before_render)
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass
        # Render into a temporary file first. In DEV mode the overlay is added
        # BEFORE the render because it is now guaranteed to use the exact same
        # point set/camera framing. This removes the old second render pass and
        # makes large DEV batches roughly 2x faster on the rendering portion.
        tmp_out = out + ".tmp" + THUMB_EXTENSION
        if os.path.isfile(tmp_out):
            try:
                os.remove(tmp_out)
            except OSError:
                pass

        valid = False
        metrics = None
        chosen_points = None
        if not is_fx:
            fit_sets = [
                (use_coords, float(THUMB_FRAME_MARGIN), "combined"),
                (_collect_frame_points(objs, keep_shroud=keep_shroud,
                                       keep_fairing=keep_fairing,
                                       include_evaluated=False, include_raw=True,
                                       ignore_hide=True),
                 float(THUMB_RETRY_MARGIN), "raw-only-full"),
                (_collect_frame_points(objs, keep_shroud=keep_shroud,
                                       keep_fairing=keep_fairing,
                                       include_evaluated=False, include_raw=True),
                 float(THUMB_RETRY_MARGIN), "raw-only"),
                # Repair path for fully black / fully transparent results:
                # include helpers/colliders and use a generous margin
                # (camera too far / out-of-frame / empty FreeIVA shell cases).
                (_collect_frame_points(objs, keep_shroud=keep_shroud,
                                       keep_fairing=keep_fairing,
                                       include_evaluated=True, include_raw=True,
                                       include_helpers=True),
                 max(float(THUMB_RETRY_MARGIN), 2.2), "helpers+wide"),
            ]
            for attempt, (fit_points, margin, label) in enumerate(fit_sets):
                if not fit_points:
                    continue
                _dev_info("fit", attempt + 1, label)
                if not _fit_ortho_camera(cam_obj, cam_data, fit_points, margin=margin):
                    continue
                # For the helpers repair path, make sure geometry is actually visible.
                if label == "helpers+wide":
                    for o in objs:
                        try:
                            if getattr(o, "type", "") != "MESH":
                                continue
                            o.hide_set(False)
                            o.hide_render = False
                        except Exception:
                            pass
                    try:
                        bpy.context.view_layer.update()
                    except Exception:
                        pass
                chosen_points = fit_points
                if DEV_OVERLAY:
                    _overlay_for_points(scene, chosen_points, cam_obj, cam_data)
                _p(0.70, "render")
                valid, metrics = _render_to_path(scene, tmp_out)
                if valid:
                    # Soft pullback: still too tight on long axis even if
                    # border pixels stayed under alpha threshold (AA).
                    span = (metrics or {}).get("span")
                    if not span:
                        try:
                            bbox = (metrics or {}).get("bbox")
                            if bbox and len(bbox) == 4:
                                bw = bbox[2] - bbox[0] + 1
                                bh = bbox[3] - bbox[1] + 1
                                span = (bw / float(_ICON_SIZE), bh / float(_ICON_SIZE))
                        except Exception:
                            span = None
                    if span and max(span) >= float(THUMB_SPAN_SOFT):
                        try:
                            cam_data.ortho_scale = (
                                float(cam_data.ortho_scale) * float(THUMB_WIDER_ORTHO)
                            )
                            print(
                                "[mu_thumb] soft-span pullback ortho=%.3f span=%s"
                                % (cam_data.ortho_scale, span),
                                flush=True,
                            )
                            valid2, metrics2 = _render_to_path(scene, tmp_out)
                            if valid2:
                                valid, metrics = valid2, metrics2
                        except Exception as e:
                            print("[mu_thumb] soft-span pullback failed:", e)
                    break
                reason = (metrics or {}).get("reason", "")
                if reason in ("fully_transparent", "fully_black"):
                    print(
                        "[mu_thumb][DEV] empty/black/transparent detect -> "
                        "attempt repair (%s) reason=%s metrics=%s"
                        % (label, reason, metrics),
                        flush=True,
                    )
                try:
                    os.remove(tmp_out)
                except OSError:
                    pass
                chosen_points = None
        else:
            chosen_points = fx_fit_points if fx_fit_points else None
            valid, metrics = _render_to_path(scene, tmp_out)
            if not valid:
                # FX camera has its own framing logic; retry with a more generous
                # scale if the first render is suspicious.
                if DEV_OVERLAY and chosen_points:
                    _overlay_for_points(scene, chosen_points, cam_obj, cam_data)
                valid, metrics = _render_to_path(scene, tmp_out)
            if not valid:
                reason = (metrics or {}).get("reason", "")
                if reason in ("fully_transparent", "fully_black"):
                    print(
                        "[mu_thumb][DEV] FX empty/black/transparent detect -> "
                        "scale repair reason=%s metrics=%s"
                        % (reason, metrics),
                        flush=True,
                    )
                try:
                    cam_data.ortho_scale *= 1.75
                except Exception:
                    pass
                if DEV_OVERLAY and chosen_points:
                    _overlay_for_points(scene, chosen_points, cam_obj, cam_data)
                valid, metrics = _render_to_path(scene, tmp_out)

        if valid:
            probe_eevee_gpu()

        if not valid:
            reason = (metrics or {}).get("reason", "")
            # Too zoomed / edge-biased: pull camera back (larger ortho) and retry
            if reason in ("touches_border", "edge_biased"):
                try:
                    cam_data.ortho_scale = float(cam_data.ortho_scale) * float(THUMB_WIDER_ORTHO)
                    print(
                        "[mu_thumb] retry wider ortho=%.3f after %s"
                        % (cam_data.ortho_scale, reason),
                        flush=True,
                    )
                    valid, metrics = _render_to_path(scene, tmp_out)
                    reason = (metrics or {}).get("reason", "") if not valid else ""
                except Exception as e:
                    print("[mu_thumb] wider-ortho retry failed:", e)
            # Recovery ladder before any labeled text placeholder:
            #  1) unhide all non-colliders  → EEVEE
            #  2) same                       → Workbench solid (transparent bg)
            #  3) unhide everything incl. colliders → EEVEE
            #  4) same                       → Workbench solid (transparent bg)
            # Only if all four fail do we write ODD MESH / ONLY COLLIDER / etc.
            if not valid:
                try:
                    print(
                        "[mu_thumb] recovery ladder after reason=%s"
                        % ((metrics or {}).get("reason", "")),
                        flush=True,
                    )
                    valid, metrics = _try_recovery_renders(
                        scene,
                        cam_obj,
                        cam_data,
                        objs,
                        tmp_out,
                        keep_shroud=keep_shroud,
                        keep_fairing=keep_fairing,
                    )
                except Exception as e:
                    print("[mu_thumb] recovery ladder failed:", type(e).__name__, e)
            if not valid:
                reason = (metrics or {}).get("reason", "")
                label = _classify_empty_geometry(objs, root)
                print(
                    "[mu_thumb][DEV] render failed after recovery -> "
                    "empty-geometry placeholder label=%s reason=%s metrics=%s"
                    % (label, reason, metrics),
                    flush=True,
                )
                try:
                    if os.path.isfile(tmp_out):
                        os.remove(tmp_out)
                except OSError:
                    pass
                if _write_empty_geometry_placeholder(out, label):
                    return out
                print("[mu_thumb] FAIL: rendered PNG / WEBP / AVIF validation failed:", metrics)
                try:
                    if os.path.isfile(tmp_out):
                        os.remove(tmp_out)
                except OSError:
                    pass
                return None
            # valid became True after retry/recovery — fall through to commit

        _p(0.90, "commit")
        if not _commit_render(tmp_out, out):
            print(
                "[mu_thumb] FAIL: commit_render failed tmp=%s out=%s exists_tmp=%s"
                % (tmp_out, out, os.path.isfile(tmp_out) if tmp_out else False),
                flush=True,
            )
            try:
                if os.path.isfile(tmp_out):
                    os.remove(tmp_out)
            except OSError:
                pass
            return None

        print(
            "[mu_thumb][DEV] OK", os.path.basename(out),
            "bytes=", os.path.getsize(out), flush=True,
        )
        return out

    finally:
        try:
            if (
                scene
                and scene.view_layers
            ):
                scene.view_layers[
                    0
                ].objects.active = None
        except Exception:
            pass
        try:
            if (
                win is not None
                and orig_scene is not None
            ):
                win.scene = orig_scene
        except Exception:
            pass
        try:
            if (
                win is not None
                and win.view_layer
            ):
                win.view_layer.objects.active = None
            for o in list(
                getattr(
                    bpy.context,
                    "selected_objects",
                    [],
                )
                or []
            ):
                try:
                    o.select_set(False)
                except Exception:
                    pass
        except Exception:
            pass
        if (
            prog_mod is not None
            and orig_bar is not None
        ):
            try:
                prog_mod.mu_progress_bar = (
                    orig_bar
                )
            except Exception:
                pass
        try:
            _purge_new()
        except Exception as e:

            print(
                "[mu_thumb] purge warning:",
                type(e).__name__,
                e,
            )
        try:
            if (
                scene
                and scene.name
                in bpy.data.scenes
            ):
                bpy.data.scenes.remove(
                    scene,
                    do_unlink=True,
                )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Recovery before labeled placeholders (unhide → solid → text)
# ---------------------------------------------------------------------------

def _name_looks_like_collider(name: str) -> bool:
    """True for KSP collider meshes — kept hidden in the first recovery pass."""
    n = (name or "").lower()
    if not n:
        return False
    return (
        "collider" in n
        or ".collider" in n
        or "collision" in n
        or n.startswith("col_")
        or n.startswith("col1")
        or n.startswith("col2")
        or n.startswith("col3")
        or n.startswith("col4")
        or n.startswith("col5")
        or n.startswith("col6")
    )


def _recovery_unhide(objs, *, include_colliders: bool = False) -> int:
    """Unhide meshes for recovery renders. Returns how many objects were touched."""
    n = 0
    for o in objs or []:
        try:
            if getattr(o, "type", "") != "MESH":
                continue
            name = o.name or ""
            if not include_colliders and _name_looks_like_collider(name):
                continue
            o.hide_set(False)
            o.hide_viewport = False
            o.hide_render = False
            try:
                o["mu_variant_hidden"] = False
            except Exception:
                pass
            n += 1
        except Exception:
            pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return n


def _push_solid_shading(scene):
    """Switch to Workbench solid shading; always keep film transparent.

    Returns a state dict for _pop_solid_shading. Used when material/EEVEE
    renders are empty (shader-only FX, broken alpha, etc.).
    """
    state = {
        "engine": getattr(scene.render, "engine", None),
        "film_transparent": bool(getattr(scene.render, "film_transparent", True)),
    }
    try:
        sh = scene.display.shading
        state["light"] = getattr(sh, "light", None)
        state["color_type"] = getattr(sh, "color_type", None)
        try:
            state["single_color"] = tuple(sh.single_color)
        except Exception:
            state["single_color"] = None
        try:
            state["show_shadows"] = bool(getattr(sh, "show_shadows", False))
        except Exception:
            state["show_shadows"] = None
    except Exception:
        pass
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except Exception:
        pass
    # Transparent background is mandatory for thumbnails (solid or not).
    try:
        scene.render.film_transparent = True
    except Exception:
        pass
    try:
        sh = scene.display.shading
        try:
            sh.light = "STUDIO"
        except Exception:
            try:
                sh.light = "FLAT"
            except Exception:
                pass
        try:
            sh.color_type = "SINGLE"
        except Exception:
            pass
        try:
            f = max(0.15, float(THUMB_SOLID_BRIGHTNESS_FACTOR))
            c = min(1.0, 0.70 * f)
            sh.single_color = (c, min(1.0, c * 1.02), min(1.0, c * 1.05))
        except Exception:
            pass
        try:
            sh.show_shadows = True
        except Exception:
            pass
    except Exception:
        pass
    return state


def _pop_solid_shading(scene, state):
    """Restore engine / shading after a solid recovery render."""
    if not state:
        return
    eng = state.get("engine")
    if eng:
        try:
            scene.render.engine = eng
        except Exception:
            try:
                scene.render.engine = "BLENDER_EEVEE_NEXT"
            except Exception:
                try:
                    scene.render.engine = "BLENDER_EEVEE"
                except Exception:
                    pass
    try:
        scene.render.film_transparent = bool(state.get("film_transparent", True))
    except Exception:
        pass
    try:
        sh = scene.display.shading
        if state.get("light") is not None:
            try:
                sh.light = state["light"]
            except Exception:
                pass
        if state.get("color_type") is not None:
            try:
                sh.color_type = state["color_type"]
            except Exception:
                pass
        if state.get("single_color") is not None:
            try:
                sh.single_color = state["single_color"]
            except Exception:
                pass
        if state.get("show_shadows") is not None:
            try:
                sh.show_shadows = state["show_shadows"]
            except Exception:
                pass
    except Exception:
        pass


def _try_recovery_renders(
    scene,
    cam_obj,
    cam_data,
    objs,
    tmp_out,
    *,
    keep_shroud: bool = False,
    keep_fairing: bool = False,
):
    """Before labeled placeholder: unhide → solid, then all (incl. colliders) → solid.

    Returns (valid, metrics) of the first successful recovery render, or the
    last failed metrics.
    """
    steps = (
        (False, False, "unhide_non_collider"),
        (False, True, "unhide_non_collider+solid"),
        (True, False, "unhide_all"),
        (True, True, "unhide_all+solid"),
    )
    last_metrics = {"valid": False, "reason": "recovery_exhausted"}
    for include_colliders, solid, label in steps:
        solid_state = None
        try:
            n = _recovery_unhide(objs, include_colliders=include_colliders)
            _dev_info(
                "recovery",
                label,
                "unhid=%d" % n,
                "solid=%s" % bool(solid),
            )
            # Reframe from whatever is now visible (helpers/colliders when full).
            pts = _collect_frame_points(
                objs,
                keep_shroud=keep_shroud if not include_colliders else True,
                keep_fairing=keep_fairing if not include_colliders else True,
                include_evaluated=True,
                include_raw=True,
                include_helpers=include_colliders,
                ignore_hide=True,
            )
            pts = _filter_outlier_frame_points(pts)
            if pts:
                _fit_ortho_camera(
                    cam_obj,
                    cam_data,
                    pts,
                    margin=float(THUMB_FRAME_MARGIN),
                )
            if solid:
                solid_state = _push_solid_shading(scene)
            valid, metrics = _render_to_path(scene, tmp_out)
            last_metrics = metrics or last_metrics
            if valid:
                _dev_info("recovery OK", label)
                return True, metrics
            reason = (metrics or {}).get("reason", "")
            _dev_info("recovery miss", label, reason)
        except Exception as e:
            _dev_info("recovery error", label, type(e).__name__, e)
            last_metrics = {
                "valid": False,
                "reason": "recovery_error:%s" % e,
            }
        finally:
            if solid_state is not None:
                try:
                    _pop_solid_shading(scene, solid_state)
                except Exception:
                    pass
            # Always re-assert transparent film after solid attempts.
            try:
                scene.render.film_transparent = True
            except Exception:
                pass
    return False, last_metrics


# ---------------------------------------------------------------------------
# Empty-geometry classification + labeled transparent placeholders
# ---------------------------------------------------------------------------
# When a .mu has no renderable mesh (pure collider, depth mask, empty root,
# transform-only, etc.) we still write a valid cache PNG / WEBP / AVIF: transparent background
# with a short white label (1px black outline) so the browser grid is never blank
# and the user sees *why* there is no model preview.

_LABEL_FONT_5X7 = {
    # 5 columns x 7 rows, MSB = left. Space is empty.
    " ": [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    "A": [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "B": [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
    "C": [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E],
    "D": [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
    "E": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F],
    "F": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
    "G": [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E],
    "H": [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "I": [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "K": [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
    "L": [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
    "M": [0x11, 0x1B, 0x15, 0x11, 0x11, 0x11, 0x11],
    "N": [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
    "O": [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "P": [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
    "R": [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
    "S": [0x0E, 0x11, 0x10, 0x0E, 0x01, 0x11, 0x0E],
    "T": [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    "U": [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "Y": [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04],
    "-": [0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00],
    "/": [0x01, 0x02, 0x04, 0x04, 0x08, 0x10, 0x10],
    ".": [0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C],
}


def _classify_empty_geometry(objs, root) -> str:
    """Return a short label explaining why there is no visible mesh to render."""
    names = []
    mesh_names = []
    mesh_with_verts = 0
    empties = 0
    for o in objs or []:
        try:
            n = (o.name or "").lower()
            names.append(n)
            t = getattr(o, "type", "") or ""
            if t == "MESH":
                mesh_names.append(n)
                me = getattr(o, "data", None)
                if me is not None and len(getattr(me, "vertices", []) or []) > 0:
                    mesh_with_verts += 1
            elif t in ("EMPTY", "ARMATURE"):
                empties += 1
        except Exception:
            continue

    def _is_collider(n: str) -> bool:
        return (
            "collider" in n
            or n.startswith("col_")
            or ".collider" in n
            or "collision" in n
            or n.startswith("col1")
            or n.startswith("col2")
            or n.startswith("col3")
            or n.startswith("col4")
            or n.startswith("col5")
            or n.startswith("col6")
        )

    def _is_mask(n: str) -> bool:
        return (
            "depthmask" in n
            or "depth_mask" in n
            or "overlaymask" in n
            or "overlay_mask" in n
            or n.endswith("mask")
            or "mask" in n and ("window" in n or "cabin" in n or "inline" in n or "hitch" in n)
        )

    if mesh_names and all(_is_collider(n) for n in mesh_names) and mesh_with_verts == 0:
        return "ONLY COLLIDER"
    if mesh_names and all(_is_collider(n) for n in mesh_names):
        return "ONLY COLLIDER"
    if names and all(_is_collider(n) or not n for n in names if n):
        # all named objects look like colliders (even if type != MESH)
        non_empty = [n for n in names if n]
        if non_empty and all(_is_collider(n) for n in non_empty):
            return "ONLY COLLIDER"
    if mesh_names and all(_is_mask(n) for n in mesh_names):
        return "ONLY DEPTH MASK"
    if names and any(_is_mask(n) for n in names) and mesh_with_verts == 0:
        if all(_is_mask(n) or _is_collider(n) or not n for n in names):
            return "ONLY DEPTH MASK"
    if mesh_with_verts == 0 and not mesh_names and empties > 0:
        return "ONLY ROOT"
    if mesh_with_verts == 0 and mesh_names:
        return "EMPTY MESH"
    if mesh_with_verts == 0:
        return "NO MESH"
    # Has real mesh vertices — should not have reached the empty path.
    # Flat billboards / cloud cards / fog planes / shader-only FX still count
    # as geometry; label them distinctly when the empty/placeholder path runs.
    return "ODD MESH" if mesh_with_verts > 0 else "NO MESH"


def _draw_label_pixels(size: int, lines) -> list:
    """Build flat RGBA float pixels: transparent bg, white glyphs with 1px black outline.

    Two-pass draw is required: first all outline pixels, then all fill pixels.
    A single-pass "outline then fill per pixel" lets a neighbour's outline
    overwrite the previous pixel's white fill, leaving the whole glyph black.
    """
    # scale so multi-line labels fit inside the icon with padding
    scale = round(2 * size / 128)
    glyph_w, glyph_h = 5 * scale, 7 * scale
    gap = 1 * scale
    line_gap = 3 * scale
    # measure
    max_cols = max((len(ln) for ln in lines), default=1)
    text_w = max_cols * (glyph_w + gap) - gap
    text_h = len(lines) * glyph_h + max(0, len(lines) - 1) * line_gap
    # shrink scale if needed
    while scale > 1 and (text_w + 8 > size or text_h + 8 > size):
        scale -= 1
        glyph_w, glyph_h = 5 * scale, 7 * scale
        gap = 1 * scale
        line_gap = 3 * scale
        text_w = max_cols * (glyph_w + gap) - gap
        text_h = len(lines) * glyph_h + max(0, len(lines) - 1) * line_gap

    ox = max(0, (size - text_w) // 2)
    oy = max(0, (size - text_h) // 2)

    # Collect every filled pixel first (Blender image y=0 is bottom).
    fills = set()
    for li, line in enumerate(lines):
        ly = oy + li * (glyph_h + line_gap)
        for ci, ch in enumerate(line.upper()):
            bits = _LABEL_FONT_5X7.get(ch, _LABEL_FONT_5X7[" "])
            lx = ox + ci * (glyph_w + gap)
            for row in range(7):
                row_bits = bits[row]
                for col in range(5):
                    if row_bits & (1 << (4 - col)):
                        for sy in range(scale):
                            for sx in range(scale):
                                py = size - 1 - (ly + row * scale + sy)
                                px = lx + col * scale + sx
                                if 0 <= px < size and 0 <= py < size:
                                    fills.add((px, py))

    # Expand fills by 1px for the black outline (8-neighbourhood).
    outlines = set()
    for px, py in fills:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                oxp, oyp = px + dx, py + dy
                if 0 <= oxp < size and 0 <= oyp < size and (oxp, oyp) not in fills:
                    outlines.add((oxp, oyp))

    # Flat RGBA buffer, transparent background.
    pixels = [0.0] * (size * size * 4)
    black = (0.0, 0.0, 0.0, 1.0)
    white = (1.0, 1.0, 1.0, 1.0)

    def put(x, y, rgba):
        i = (y * size + x) * 4
        pixels[i] = rgba[0]
        pixels[i + 1] = rgba[1]
        pixels[i + 2] = rgba[2]
        pixels[i + 3] = rgba[3]

    # Pass 1: black outline
    for px, py in outlines:
        put(px, py, black)
    # Pass 2: white fill (always on top — never overwritten)
    for px, py in fills:
        put(px, py, white)

    return pixels


def _write_empty_geometry_placeholder(out_path: str, label: str) -> bool:
    """Write a transparent PNG / WEBP / AVIF with a white outlined label. Returns True on success."""
    try:
        # Split long labels into up to 3 lines for readability
        words = (label or "NO MESH").upper().split()
        if len(words) <= 2:
            lines = [" ".join(words)]
        else:
            # prefer 2 lines
            mid = (len(words) + 1) // 2
            lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        size = int(_ICON_SIZE)
        pixels = _draw_label_pixels(size, lines)
        img = bpy.data.images.new(
            "_mu_empty_geom_thumb",
            width=size,
            height=size,
            alpha=True,
        )
        try:
            # Keep written RGB values as-is (no linear/sRGB round-trip that
            # can crush near-white or make outlines look wrong in the browser).
            img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
        img.pixels = pixels
        # Force Blender to commit the buffer before save.
        try:
            img.update()
        except Exception:
            pass
        img.filepath_raw = out_path
        img.file_format = THUMB_FORMAT
        try:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        except Exception:
            pass
        img.save()
        bpy.data.images.remove(img)
        print(
            "[mu_thumb][DEV] empty-geometry placeholder written:",
            os.path.basename(out_path),
            "label=",
            label,
            flush=True,
        )
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 32
    except Exception as e:
        print("[mu_thumb][DEV] placeholder write failed:", type(e).__name__, e, flush=True)
        return False


def _default_thumb_path() -> str:
    return os.path.join(_cache_dir(), _DEFAULT_THUMB_NAME)


def _ensure_default_thumbnail() -> str:
    path = _default_thumb_path()

    if (
        os.path.isfile(path)
        and os.path.getsize(path) > 64
    ):
        return path

    img = bpy.data.images.new(
        "_mu_default_thumbnail",
        width=_ICON_SIZE,
        height=_ICON_SIZE,
        alpha=True,
    )

    pixels = []

    for y in range(_ICON_SIZE):

        for x in range(_ICON_SIZE):

            pixels.extend(
                (
                    0.30,
                    0.30,
                    0.30,
                    1.0,
                )
            )

    img.pixels = pixels

    img.filepath_raw = path
    img.file_format = THUMB_FORMAT

    img.save()

    bpy.data.images.remove(img)

    return path


def icon_id_for_part(mu_path: str, part_name: str = "", *, ensure: bool = True) -> int:
    pcoll = ensure_previews()
    key_src = "%s|%s" % (
        mu_path or "",
        part_name or "",
    )
    key = hashlib.sha1(
        key_src.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()[:20]
    if key in pcoll:
        return pcoll[key].icon_id
    path = _resolve_cache_path(
        mu_path,
        part_name,
    )
    if (
        path is None
        and ensure
    ):
        path = generate_thumbnail(
            mu_path,
            part_name,
        )
    if (
        not path
        or not os.path.isfile(path)
    ):
        try:
            if (
                _DEFAULT_PREVIEW_KEY
                not in pcoll
            ):
                default_path = (
                    _ensure_default_thumbnail()
                )
                pcoll.load(
                    _DEFAULT_PREVIEW_KEY,
                    default_path,
                    "IMAGE",
                )

            return pcoll[
                _DEFAULT_PREVIEW_KEY
            ].icon_id

        except Exception:
            return 0
    try:
        pcoll.load(
            key,
            path,
            "IMAGE",
        )
        return pcoll[key].icon_id
    except Exception:
        return 0
