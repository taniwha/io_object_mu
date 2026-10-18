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
"""Status-bar + KSP-panel progress for long import / export.

Cursor ring, workspace status text, and the N-panel bar update live (page
N/M and percent).

Blender's Info editor does not honor ``\\r`` (each ``print()`` is a new
report).  Same-phase ticks rewrite the previous Info line when possible,
and the Windows/system console still uses carriage-return overwrite.

``wm.redraw_timer`` benchmark warnings are filtered from stdout and
deleted from the Info editor for the duration of the session.
"""

from __future__ import annotations

import re
import sys
import time
from contextlib import contextmanager

import bpy

_active = None  # type: ignore

# ``Building page 12/52…`` / ``Writing .lang fr (2/4)…`` → same console phase.
_COUNTER_RE = re.compile(
    r"(?:\s+\d+\s*/\s*\d+|\s*\(\s*\d+\s*/\s*\d+\s*\))",
    re.UNICODE,
)

_SWAP_NEEDLE = "Draw window and swap"

_saved_streams = None  # type: ignore
_filter_depth = 0


def _phase_key(label: str) -> str:
    s = (label or "").strip()
    if not s:
        return ""
    s = _COUNTER_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_info_prefix(line: str) -> str:
    s = (line or "").strip()
    for pfx in ("Info: ", "INFO: ", "Warning: ", "WARNING: ", "Error: ", "ERROR: "):
        if s.startswith(pfx):
            return s[len(pfx):].strip()
    return s


class _SwapWarningFilter:
    """Drop redraw_timer benchmark lines that leak through Python stdio."""

    def __init__(self, wrapped):
        self._w = wrapped

    def write(self, data):
        s = str(data)
        if _SWAP_NEEDLE in s:
            keep = []
            for line in s.splitlines(keepends=True):
                if _SWAP_NEEDLE in line:
                    continue
                keep.append(line)
            s = "".join(keep)
            if not s:
                return len(data)
        try:
            return self._w.write(s)
        except Exception:
            return len(data)

    def flush(self):
        try:
            self._w.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._w, name)


def _install_swap_filter():
    global _saved_streams, _filter_depth
    _filter_depth += 1
    if _filter_depth != 1:
        return
    _saved_streams = (
        sys.stdout,
        sys.stderr,
        getattr(sys, "__stdout__", None),
        getattr(sys, "__stderr__", None),
    )
    sys.stdout = _SwapWarningFilter(sys.stdout)
    sys.stderr = _SwapWarningFilter(sys.stderr)
    try:
        if sys.__stdout__ is not None:
            sys.__stdout__ = _SwapWarningFilter(sys.__stdout__)
    except Exception:
        pass
    try:
        if sys.__stderr__ is not None:
            sys.__stderr__ = _SwapWarningFilter(sys.__stderr__)
    except Exception:
        pass


def _restore_swap_filter():
    global _saved_streams, _filter_depth
    if _filter_depth <= 0:
        return
    _filter_depth -= 1
    if _filter_depth != 0 or _saved_streams is None:
        return
    so, se, dso, dse = _saved_streams
    _saved_streams = None
    try:
        sys.stdout = so
    except Exception:
        pass
    try:
        sys.stderr = se
    except Exception:
        pass
    try:
        if dso is not None:
            sys.__stdout__ = dso
    except Exception:
        pass
    try:
        if dse is not None:
            sys.__stderr__ = dse
    except Exception:
        pass


def _iter_info_overrides():
    try:
        wm = bpy.context.window_manager
        windows = wm.windows
    except Exception:
        return
    for win in windows:
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "INFO":
                continue
            region = None
            for r in area.regions:
                if r.type == "WINDOW":
                    region = r
                    break
            if region is None:
                continue
            yield {
                "window": win,
                "screen": screen,
                "area": area,
                "region": region,
            }


def _info_copy_lines():
    try:
        wm = bpy.context.window_manager
        saved_clip = wm.clipboard
    except Exception:
        wm = None
        saved_clip = None
    try:
        for ov in _iter_info_overrides():
            try:
                with bpy.context.temp_override(**ov):
                    bpy.ops.info.select_all(action="SELECT")
                    bpy.ops.info.report_copy()
                    bpy.ops.info.select_all(action="DESELECT")
                text = bpy.context.window_manager.clipboard or ""
                return text.splitlines()
            except Exception:
                continue
        return None
    finally:
        if wm is not None and saved_clip is not None:
            try:
                wm.clipboard = saved_clip
            except Exception:
                pass


def _info_delete_indices(indices):
    if not indices:
        return False
    deleted = False
    for ov in _iter_info_overrides():
        try:
            with bpy.context.temp_override(**ov):
                for i in sorted(set(indices), reverse=True):
                    if i < 0:
                        continue
                    try:
                        bpy.ops.info.select_all(action="DESELECT")
                        bpy.ops.info.select_pick(report_index=int(i))
                        bpy.ops.info.report_delete()
                        deleted = True
                    except Exception:
                        pass
        except Exception:
            continue
        break
    return deleted


def _rewrite_wm_report(old: str, new: str) -> bool:
    """In-place Info overwrite when Report.message is writable."""
    try:
        reports = bpy.context.window_manager.reports
    except Exception:
        return False
    old_s = (old or "").strip()
    if not old_s:
        return False
    try:
        for rep in reports:
            msg = _strip_info_prefix(getattr(rep, "message", "") or "")
            if msg != old_s:
                continue
            try:
                rep.message = new
                return True
            except Exception:
                return False
    except Exception:
        return False
    return False


def _info_delete_exact(text: str) -> bool:
    needle = (text or "").strip()
    if not needle:
        return False
    lines = _info_copy_lines()
    if not lines:
        return False
    idxs = []
    for i, line in enumerate(lines):
        if _strip_info_prefix(line) == needle:
            idxs.append(i)
    if not idxs:
        # Keep only the latest matching progress line.
        return False
    return _info_delete_indices([idxs[-1]])


def _scrub_swap_warnings():
    """Remove redraw_timer benchmark reports from the Info editor."""
    try:
        reports = bpy.context.window_manager.reports
        idxs = [
            i for i, rep in enumerate(reports)
            if _SWAP_NEEDLE in (getattr(rep, "message", "") or "")
        ]
        if idxs and _info_delete_indices(idxs):
            return
    except Exception:
        pass
    lines = _info_copy_lines()
    if not lines:
        return
    start = max(0, len(lines) - 24)
    idxs = [
        i for i in range(start, len(lines))
        if _SWAP_NEEDLE in lines[i]
    ]
    if idxs:
        _info_delete_indices(idxs)


def _tty_stream():
    for cand in (
        getattr(sys, "__stdout__", None),
        sys.stdout,
    ):
        if cand is None:
            continue
        inner = getattr(cand, "_w", cand)
        return inner
    return None


class ProgressSession:
    """Window-manager progress bar + workspace status text + throttled redraw."""

    def __init__(self, context, total=100, title="KSP"):
        self.context = context
        self.total = max(int(total), 1)
        self.title = (title or "KSP").strip() or "KSP"
        self.value = 0
        self._last_draw = 0.0
        self._last_status = ""
        self._last_label = None
        self._printed_phases = set()
        self._info_line = ""
        self._tty_width = 0
        self._tty_dirty = False
        self._wm = None
        self._window = None
        self._opened = False
        self._cursor = False

    @property
    def fraction(self):
        return max(0.0, min(1.0, float(self.value) / float(self.total)))

    @property
    def status(self):
        return self._last_status

    def begin(self):
        global _active
        ctx = self.context
        try:
            self._wm = ctx.window_manager
            self._window = getattr(ctx, "window", None)
        except Exception:
            self._wm = None
            self._window = None
        _install_swap_filter()
        if self._wm is not None:
            try:
                self._wm.progress_begin(0, self.total)
                self._opened = True
            except Exception:
                self._opened = False
        if self._window is not None:
            try:
                self._window.cursor_set("WAIT")
                self._cursor = True
            except Exception:
                pass
        _active = self
        self.update(0, text="Starting…", force=True)
        return self

    def close(self):
        global _active
        self._tty_finalize()
        if _active is self:
            _active = None
        self._set_status_text(None)
        if self._opened and self._wm is not None:
            try:
                self._wm.progress_end()
            except Exception:
                pass
        self._opened = False
        if self._cursor and self._window is not None:
            try:
                self._window.cursor_set("DEFAULT")
            except Exception:
                pass
        self._cursor = False
        _restore_swap_filter()

    def _set_status_text(self, text):
        """Original workspace status-bar text (left of the bottom bar)."""
        seen = set()
        try:
            ws = getattr(self.context, "workspace", None)
            if ws is not None:
                ws.status_text_set(text)
                seen.add(ws)
        except Exception:
            pass
        try:
            wm = bpy.context.window_manager
            for win in wm.windows:
                ws = getattr(win, "workspace", None)
                if ws is None or ws in seen:
                    continue
                try:
                    ws.status_text_set(text)
                except Exception:
                    pass
                seen.add(ws)
        except Exception:
            pass

    def _tty_overwrite(self, status):
        out = _tty_stream()
        if out is None:
            return
        try:
            pad = max(0, self._tty_width - len(status))
            out.write("\r" + status + (" " * pad))
            out.flush()
            self._tty_width = max(self._tty_width, len(status))
            self._tty_dirty = True
        except Exception:
            pass

    def _tty_finalize(self):
        if not self._tty_dirty:
            return
        out = _tty_stream()
        if out is None:
            return
        try:
            out.write("\n")
            out.flush()
        except Exception:
            pass
        self._tty_dirty = False
        self._tty_width = 0

    def _print_info(self, status):
        try:
            print(status)
        except Exception:
            try:
                stdout = getattr(sys, "stdout", None)
                if stdout is not None:
                    stdout.write(str(status) + "\n")
            except Exception:
                pass
        self._info_line = status

    def update(self, value=None, *, fraction=None, text=None, force=False):
        if fraction is not None:
            try:
                value = int(round(float(fraction) * float(self.total)))
            except Exception:
                value = self.value
        if value is None:
            value = self.value
        try:
            value = int(value)
        except Exception:
            value = self.value
        value = max(0, min(value, self.total))
        self.value = value
        if self._opened and self._wm is not None:
            try:
                self._wm.progress_update(value)
            except Exception:
                pass
        label = (text or "").strip() or "Working…"
        pct = int(round(100.0 * value / float(self.total)))
        status = "%s — %s (%d%%)" % (self.title, label, pct)
        if status != self._last_status or force:
            prev = self._last_status
            self._last_status = status
            self._last_label = label
            self._set_status_text(status)
            self._emit_console(status, label=label, previous=prev)
        self._maybe_redraw(force=force)

    def _emit_console(self, status, *, label, previous=""):
        key = _phase_key(label)
        first = key not in self._printed_phases
        if first:
            self._printed_phases.add(key)
            if self._tty_dirty:
                self._tty_finalize()
            self._print_info(status)
            return

        # Same phase: refresh TTY in place (\r). Info editor ignores \r, so
        # rewrite the previous report or replace it with a new print().
        self._tty_overwrite(status)
        old = self._info_line or previous
        if old and _rewrite_wm_report(old, status):
            self._info_line = status
            return
        if old and _info_delete_exact(old):
            self._print_info(status)

    def items(self, index, count, start, end, text=None, every=None, force=False):
        """Map item index/count into absolute [start, end] of the bar."""
        n = max(int(count), 1)
        i = max(0, min(int(index) + 1, n))
        if every is None:
            every = max(1, n // 40)
        if (not force) and (i % every) != 0 and i < n:
            return
        lo = int(start)
        hi = int(end)
        if hi < lo:
            hi = lo
        value = lo + int(round((hi - lo) * (float(i) / float(n))))
        self.update(value, text=text, force=force or i >= n)

    def _maybe_redraw(self, force=False):
        now = time.monotonic()
        if (not force) and (now - self._last_draw) < 0.12:
            return
        self._last_draw = now
        # DRAW_WIN_SWAP paints status bar + KSP panel during a blocking
        # operator.  It always emits a benchmark warning — hide it.
        try:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except Exception:
            try:
                for win in bpy.context.window_manager.windows:
                    screen = getattr(win, "screen", None)
                    if screen is None:
                        continue
                    for area in screen.areas:
                        if area.type in {"STATUSBAR", "VIEW_3D", "PROPERTIES", "INFO"}:
                            area.tag_redraw()
            except Exception:
                pass
        try:
            _scrub_swap_warnings()
        except Exception:
            pass


def draw_panel_progress(layout):
    """Native Blender progress bar for the KSP N-panel. True if drawn."""
    s = _active
    if s is None:
        return False
    text = s.status or s.title
    factor = s.fraction
    col = layout.column(align=True)
    try:
        col.scale_y = 1.15
    except Exception:
        pass
    if hasattr(col, "progress"):
        try:
            col.progress(factor=factor, type="BAR", text=text)
            return True
        except Exception:
            pass
    try:
        col.label(text=text, icon="TIME")
    except Exception:
        pass
    return True


@contextmanager
def progress_bar(context, total=100, title="KSP"):
    session = ProgressSession(context, total=total, title=title)
    session.begin()
    try:
        yield session
    finally:
        try:
            session.update(session.total, text="Done", force=True)
        except Exception:
            pass
        session.close()


def get_active():
    return _active


def tick(value=None, *, fraction=None, text=None, force=False):
    s = _active
    if s is None:
        return
    s.update(value, fraction=fraction, text=text, force=force)


def tick_items(index, count, start, end, text=None, every=None, force=False):
    s = _active
    if s is None:
        return
    s.items(index, count, start, end, text=text, every=every, force=force)
