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
"""TextMeshPro / Unity UI rich-text subset used by KSPedia.

Supported tags (case-insensitive):
  <b> </b>  <i> </i>  <u> </u>
  <color=#RRGGBB> <color=#RRGGBBAA> <color=name> </color>
  <size=N> </size>
  <alpha=#AA> </alpha>  (applied as color alpha)
  <noparse>...</noparse>
  <br> / <br/>

Named colors follow Unity's common set. Unknown tags are stripped for
display but the original string is preserved for .ksp export.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple


_TAG_RE = re.compile(
    r"<(/?)([a-zA-Z]+)(\s*=\s*([^>]*))?(/?)>|<br\s*/?>",
    re.IGNORECASE,
)

# Unity / TMP common named colors (sRGB 0-1)
_NAMED_COLORS = {
    "red": (1.0, 0.0, 0.0, 1.0),
    "green": (0.0, 1.0, 0.0, 1.0),
    "blue": (0.0, 0.0, 1.0, 1.0),
    "white": (1.0, 1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0, 1.0),
    "yellow": (1.0, 0.92, 0.016, 1.0),
    "cyan": (0.0, 1.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0, 1.0),
    "grey": (0.5, 0.5, 0.5, 1.0),
    "gray": (0.5, 0.5, 0.5, 1.0),
    "clear": (0.0, 0.0, 0.0, 0.0),
}


@dataclass
class TextStyle:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: Optional[Tuple[float, float, float, float]] = None
    size: Optional[float] = None  # absolute TMP size override


@dataclass
class TextRun:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: Optional[Tuple[float, float, float, float]] = None
    size: Optional[float] = None


@dataclass
class ParsedRichText:
    """Parsed TMP markup."""

    raw: str
    plain: str
    runs: List[TextRun] = field(default_factory=list)
    has_markup: bool = False


def _parse_color(value: str) -> Optional[Tuple[float, float, float, float]]:
    if not value:
        return None
    v = value.strip().strip("\"'").strip()
    if not v:
        return None
    low = v.lower()
    if low in _NAMED_COLORS:
        return _NAMED_COLORS[low]
    if v.startswith("#"):
        h = v[1:]
        try:
            if len(h) == 3:
                r = int(h[0] * 2, 16) / 255.0
                g = int(h[1] * 2, 16) / 255.0
                b = int(h[2] * 2, 16) / 255.0
                return (r, g, b, 1.0)
            if len(h) == 4:
                r = int(h[0] * 2, 16) / 255.0
                g = int(h[1] * 2, 16) / 255.0
                b = int(h[2] * 2, 16) / 255.0
                a = int(h[3] * 2, 16) / 255.0
                return (r, g, b, a)
            if len(h) == 6:
                r = int(h[0:2], 16) / 255.0
                g = int(h[2:4], 16) / 255.0
                b = int(h[4:6], 16) / 255.0
                return (r, g, b, 1.0)
            if len(h) == 8:
                r = int(h[0:2], 16) / 255.0
                g = int(h[2:4], 16) / 255.0
                b = int(h[4:6], 16) / 255.0
                a = int(h[6:8], 16) / 255.0
                return (r, g, b, a)
        except ValueError:
            return None
    return None


def _parse_size(value: str) -> Optional[float]:
    if not value:
        return None
    v = value.strip().strip("\"'%").rstrip("px")
    try:
        return float(v)
    except ValueError:
        return None


def _unescape(s: str) -> str:
    # TMP uses both &lt; and raw; also \n already real newlines in assets
    return html.unescape(s.replace("\\n", "\n"))


def parse_tmp_rich_text(raw: str, base_style: Optional[TextStyle] = None) -> ParsedRichText:
    """Parse TMP markup into plain text + styled runs."""
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raw = str(raw)
    base = base_style or TextStyle()
    if not raw:
        return ParsedRichText(raw="", plain="", runs=[], has_markup=False)

    # Fast path: no tags
    if "<" not in raw:
        plain = _unescape(raw)
        return ParsedRichText(
            raw=raw,
            plain=plain,
            runs=[TextRun(
                text=plain, bold=base.bold, italic=base.italic,
                underline=base.underline, color=base.color, size=base.size,
            )],
            has_markup=False,
        )

    runs: List[TextRun] = []
    plain_parts: List[str] = []
    style_stack: List[TextStyle] = [base]
    has_markup = False
    noparse = False
    pos = 0

    def current() -> TextStyle:
        return style_stack[-1]

    def emit(text: str):
        if not text:
            return
        text = _unescape(text)
        if not text:
            return
        st = current()
        plain_parts.append(text)
        if runs and (
            runs[-1].bold == st.bold
            and runs[-1].italic == st.italic
            and runs[-1].underline == st.underline
            and runs[-1].color == st.color
            and runs[-1].size == st.size
            and "\n" not in runs[-1].text
        ):
            # Merge adjacent same-style runs (keep newlines as separators
            # for layout). Always append for simplicity / correctness.
            pass
        runs.append(
            TextRun(
                text=text,
                bold=st.bold,
                italic=st.italic,
                underline=st.underline,
                color=st.color,
                size=st.size,
            )
        )

    def push(new_style: TextStyle):
        style_stack.append(new_style)

    def pop_matching(tag: str):
        # Pop until we would leave base; TMP is not strict XML
        if len(style_stack) > 1:
            style_stack.pop()

    while pos < len(raw):
        if noparse:
            end = raw.lower().find("</noparse>", pos)
            if end < 0:
                emit(raw[pos:])
                break
            emit(raw[pos:end])
            pos = end + len("</noparse>")
            noparse = False
            has_markup = True
            continue

        # Manual <br>
        if raw[pos:pos + 4].lower() == "<br>" or raw[pos:pos + 5].lower() == "<br/>":
            has_markup = True
            emit("\n")
            pos += 5 if raw[pos:pos + 5].lower() == "<br/>" else 4
            continue

        if raw[pos] != "<":
            nxt = raw.find("<", pos)
            if nxt < 0:
                emit(raw[pos:])
                break
            emit(raw[pos:nxt])
            pos = nxt
            continue

        m = _TAG_RE.match(raw, pos)
        if not m:
            # Literal '<'
            emit(raw[pos])
            pos += 1
            continue

        has_markup = True
        full = m.group(0)
        # <br/> already handled above via regex alternate — check
        if full.lower().startswith("<br"):
            emit("\n")
            pos = m.end()
            continue

        closing = bool(m.group(1))
        tag = (m.group(2) or "").lower()
        value = (m.group(4) or "").strip()
        self_closing = bool(m.group(5))
        pos = m.end()

        if tag == "noparse" and not closing:
            noparse = True
            continue
        if tag == "noparse" and closing:
            continue

        if self_closing and tag in ("br",):
            emit("\n")
            continue

        cur = current()
        if closing:
            pop_matching(tag)
            continue

        if tag == "b":
            push(replace(cur, bold=True))
        elif tag == "i":
            push(replace(cur, italic=True))
        elif tag == "u":
            push(replace(cur, underline=True))
        elif tag == "color":
            col = _parse_color(value)
            push(replace(cur, color=col if col is not None else cur.color))
        elif tag == "size":
            sz = _parse_size(value)
            push(replace(cur, size=sz if sz is not None else cur.size))
        elif tag == "alpha":
            col = cur.color or (1.0, 1.0, 1.0, 1.0)
            a = _parse_color("#" + value.lstrip("#")) if value else None
            if a is not None:
                # alpha tag value is #AA
                av = a[0] if len(value.lstrip("#")) <= 2 else a[3]
                push(replace(cur, color=(col[0], col[1], col[2], av)))
            else:
                push(cur)
        else:
            # Unknown tag: ignore (don't push) — content still emitted
            pass

    # Merge consecutive runs with identical style
    merged: List[TextRun] = []
    for r in runs:
        if merged and (
            merged[-1].bold == r.bold
            and merged[-1].italic == r.italic
            and merged[-1].underline == r.underline
            and merged[-1].color == r.color
            and merged[-1].size == r.size
        ):
            merged[-1] = TextRun(
                text=merged[-1].text + r.text,
                bold=r.bold,
                italic=r.italic,
                underline=r.underline,
                color=r.color,
                size=r.size,
            )
        else:
            merged.append(r)

    plain = "".join(plain_parts)
    if not merged and plain:
        merged = [TextRun(
            text=plain, bold=base.bold, italic=base.italic,
            underline=base.underline, color=base.color, size=base.size,
        )]
    return ParsedRichText(
        raw=raw, plain=plain, runs=merged, has_markup=has_markup
    )


def strip_tmp_tags(raw: str) -> str:
    """Convenience: markup → plain visible text."""
    return parse_tmp_rich_text(raw).plain


def dominant_style(parsed: ParsedRichText, fallback_color=(1.0, 1.0, 1.0, 1.0)):
    """Pick a single style for one-FONT fallback (longest run wins)."""
    if not parsed.runs:
        return False, False, False, fallback_color, None
    best = max(parsed.runs, key=lambda r: len(r.text.replace(" ", "")))
    color = best.color if best.color is not None else fallback_color
    any_bold = any(r.bold for r in parsed.runs)
    any_italic = any(r.italic for r in parsed.runs)
    any_underline = any(r.underline for r in parsed.runs)
    return (
        any_bold or best.bold,
        any_italic or best.italic,
        any_underline or best.underline,
        color,
        best.size,
    )
