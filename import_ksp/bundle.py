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
"""Load / save / patch KSP .ksp Unity AssetBundles (UnityFS)."""

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .deps import ensure_unitypy, ensure_unitypy_or_prompt, last_error


class KspBundleError(Exception):
    """Raised when a .ksp AssetBundle cannot be loaded or patched."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _vec2(v):
    if v is None:
        return (0.0, 0.0)
    if isinstance(v, dict):
        return (float(v.get("x", 0.0)), float(v.get("y", 0.0)))
    if hasattr(v, "x"):
        return (float(v.x), float(v.y))
    try:
        return (float(v[0]), float(v[1]))
    except Exception:
        return (0.0, 0.0)


def _vec3(v):
    if v is None:
        return (0.0, 0.0, 0.0)
    if isinstance(v, dict):
        return (
            float(v.get("x", 0.0)),
            float(v.get("y", 0.0)),
            float(v.get("z", 0.0)),
        )
    if hasattr(v, "x"):
        return (float(v.x), float(v.y), float(getattr(v, "z", 0.0)))
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _quat(v):
    """Unity quaternion as (x, y, z, w); identity when missing."""
    if v is None:
        return (0.0, 0.0, 0.0, 1.0)
    if isinstance(v, dict):
        return (
            float(v.get("x", 0.0)),
            float(v.get("y", 0.0)),
            float(v.get("z", 0.0)),
            float(v.get("w", 1.0)),
        )
    if hasattr(v, "x"):
        return (
            float(v.x),
            float(v.y),
            float(v.z),
            float(getattr(v, "w", 1.0)),
        )
    try:
        if len(v) >= 4:
            return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    except Exception:
        pass
    return (0.0, 0.0, 0.0, 1.0)


def _tree_vec3(current, value):
    x, y, z = _vec3(value)
    if isinstance(current, dict):
        out = dict(current)
        out.update({"x": x, "y": y, "z": z})
        return out
    return {"x": x, "y": y, "z": z}


def _tree_quat(current, value):
    x, y, z, w = _quat(value)
    if isinstance(current, dict):
        out = dict(current)
        out.update({"x": x, "y": y, "z": z, "w": w})
        return out
    return {"x": x, "y": y, "z": z, "w": w}


def _color(v):
    if v is None:
        return (1.0, 1.0, 1.0, 1.0)
    if isinstance(v, dict):
        return (
            float(v.get("r", 1.0)),
            float(v.get("g", 1.0)),
            float(v.get("b", 1.0)),
            float(v.get("a", 1.0)),
        )
    if hasattr(v, "r"):
        return (float(v.r), float(v.g), float(v.b), float(getattr(v, "a", 1.0)))
    try:
        if len(v) >= 4:
            return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
        return (float(v[0]), float(v[1]), float(v[2]), 1.0)
    except Exception:
        return (1.0, 1.0, 1.0, 1.0)


def _pid(ref):
    """Extract path_id from a PPtr / dict / int."""
    if ref is None:
        return 0
    if isinstance(ref, int):
        return int(ref)
    if isinstance(ref, dict):
        return int(ref.get("m_PathID", ref.get("path_id", 0)) or 0)
    return int(getattr(ref, "path_id", getattr(ref, "m_PathID", 0)) or 0)


@dataclass
class KspTexture:
    name: str
    path_id: int
    width: int
    height: int
    png_bytes: bytes = b""
    external: bool = False
    texture_format: int = 0
    content_hash: str = ""


@dataclass
class KspTextAsset:
    name: str
    path_id: int
    text: str = ""
    script_bytes: bytes = b""


@dataclass
class KspShaderInfo:
    name: str
    path_id: int


@dataclass
class KspUiElement:
    name: str
    path_id: int
    go_path_id: int
    rect_path_id: int
    kind: str = "empty"
    text: str = ""
    font_size: float = 14.0
    color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    anchored_position: Tuple[float, float] = (0.0, 0.0)
    size_delta: Tuple[float, float] = (0.0, 0.0)
    anchor_min: Tuple[float, float] = (0.5, 0.5)
    anchor_max: Tuple[float, float] = (0.5, 0.5)
    pivot: Tuple[float, float] = (0.5, 0.5)
    offset_min: Optional[Tuple[float, float]] = None
    offset_max: Optional[Tuple[float, float]] = None
    # RectTransform local TRS (Unity). Rotation is critical for vertical
    # labels (e.g. Serenity "Craft Pitches" ≈ ±90° Z).
    local_rotation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    local_scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    local_position_z: float = 0.0
    # TMP: m_textAlignment bitfield / m_fontStyle flags / rich text
    text_alignment: int = 0
    font_style: int = 0
    is_rich_text: bool = True
    enable_word_wrapping: bool = True
    line_spacing: float = 0.0
    # TMP margin: left, top, right, bottom
    margin: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # Extra TMP spacing / sizing (often 0 on stock KSPedia; still universal)
    character_spacing: float = 0.0
    word_spacing: float = 0.0
    paragraph_spacing: float = 0.0
    enable_auto_sizing: bool = False
    font_size_min: float = 0.0
    font_size_max: float = 0.0
    overflow_mode: int = 0
    enable_kerning: bool = True
    parent_rect_path_id: int = 0
    # Index in parent's RectTransform.m_Children (draw/sibling order).
    sibling_index: int = 10**9
    mb_path_id: int = 0
    sprite_path_id: int = 0
    texture_path_id: int = 0
    # TMP font asset / family name (for viewport face selection)
    font_family: str = ""
    font_asset_path_id: int = 0
    font_asset_file_id: int = 0
    # True when texture_path_id was resolved from a dependency bundle
    texture_external: bool = False
    image_type: int = 0
    preserve_aspect: bool = False
    fill_center: bool = True
    fill_method: int = 0
    fill_amount: float = 1.0
    fill_clock_wise: bool = True
    fill_origin: int = 0
    is_raw_image: bool = False
    horizontal_alignment: int = 0
    vertical_alignment: int = 0
    outline_width: float = 0.0
    outline_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    locale_tag: str = ""
    is_ui_text: bool = False  # UnityEngine.UI.Text (not TMP)
    # TMP extras (gradient / face / mapping / linked / page)
    face_color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    enable_vertex_gradient: bool = False
    gradient_top_left: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    gradient_top_right: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    gradient_bottom_left: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    gradient_bottom_right: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    tint_all_sprites: bool = False
    horizontal_mapping: int = 0
    vertical_mapping: int = 0
    is_volumetric_text: bool = False
    page_to_display: int = 1
    linked_text_path_id: int = 0
    sprite_animator_path_id: int = 0
    # Meta UGUI (Button/Toggle/Outline/…) — store + optional viewport empty
    script_class: str = ""
    meta_scripts: str = ""  # comma-separated roles on this GO
    effect_distance: Tuple[float, float] = (0.0, 0.0)
    use_graphic_alpha: bool = True
    has_ui_outline: bool = False
    has_ui_shadow: bool = False


@dataclass
class KspBundle:
    filepath: str
    name: str
    kind: str
    textures: List[KspTexture] = field(default_factory=list)
    text_assets: List[KspTextAsset] = field(default_factory=list)
    shaders: List[KspShaderInfo] = field(default_factory=list)
    ui_elements: List[KspUiElement] = field(default_factory=list)
    object_counts: Dict[str, int] = field(default_factory=dict)
    coverage_report: str = ""
    coverage_unknown: int = 0
    canvas_scale_mode: int = 0
    canvas_ref_resolution: Tuple[float, float] = (0.0, 0.0)
    canvas_scale_factor: float = 1.0
    materials: List[Tuple[str, int]] = field(default_factory=list)
    preferred_locale_rect_ids: List[int] = field(default_factory=list)
    # Font asset / UI usage inventory from load (name -> path_id, 0 if unknown)
    font_inventory: Dict[str, int] = field(default_factory=dict)


def _texture_png_bytes(data) -> bytes:
    img = getattr(data, "image", None)
    if img is None:
        return b""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _texture_meta(data, png: bytes):
    """Return (texture_format, content_hash)."""
    import hashlib
    fmt = 0
    try:
        fmt = int(getattr(data, "m_TextureFormat", 0) or 0)
    except Exception:
        fmt = 0
    h = hashlib.sha1(png).hexdigest() if png else ""
    return fmt, h


def _text_asset_payload(data) -> Tuple[str, bytes]:
    script = getattr(data, "m_Script", b"")
    if script is None:
        return "", b""
    if isinstance(script, bytes):
        raw = script
    elif isinstance(script, str):
        raw = script.encode("utf-8", errors="replace")
    else:
        raw = bytes(script)
    try:
        text = raw.decode("utf-8")
    except Exception:
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    return text, raw


def _classify_kind(counts, ui_elements, text_assets, shaders, textures):
    n_rt = counts.get("RectTransform", 0)
    n_tex = counts.get("Texture2D", 0)
    n_sh = counts.get("Shader", 0)
    n_ta = counts.get("TextAsset", 0)
    has_ui_text = any(e.kind == "text" for e in ui_elements)
    if has_ui_text or (n_rt > 0 and n_tex > 0):
        return "kspedia_ui"
    if n_sh > 0 and n_tex == 0 and n_rt == 0:
        return "shaders"
    if n_ta > 0 and n_tex == 0 and n_rt == 0 and n_sh == 0:
        return "xml_index"
    if n_tex > 0 and n_rt == 0 and not has_ui_text:
        return "textures"
    return "other"


def _build_sprite_tex_map(env) -> Dict[int, int]:
    out = {}
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        rd = tree.get("m_RD") or tree.get("m_RenderData") or {}
        tex = None
        if isinstance(rd, dict):
            tex = rd.get("texture") or rd.get("m_Texture")
        if tex is None:
            tex = tree.get("m_Texture")
        tid = _pid(tex)
        if tid:
            out[int(obj.path_id)] = tid
    return out


def _text_is_artwork_overlay(text: str) -> bool:
    """True for UI.Text pads sitting on shared artwork (any pack, any name).

    Detection is the string shape, never GameObject names or PBS tokens:
    a leading newline, a run of spaces, or figure-spaces. Font / size /
    box / GO rename do not matter. A rewrite that drops the pad is a
    normal label and may be skipped when inactive/empty like any other.
    """
    t = text or ""
    if "<color" in t.lower():
        return False
    lead = t.lstrip("\r")
    if lead.startswith("\n"):
        return True
    n_sp = len(lead) - len(lead.lstrip(" \t"))
    if n_sp >= 4:
        return True
    n_fig = len(t) - len(t.lstrip("\u2007\u2008"))
    return n_fig >= 4


def _collect_ui(env, sprite_tex: Dict[int, int], skip_inactive_text: bool = False):
    """Collect UI elements. Returns (elements, UiCoverageReport).

    ``skip_inactive_text``: viewport import of the main .ksp drops deleted
    (inactive / empty) labels so they do not come back as vacant FONT boxes.
    Locale ``.lang`` parsing must pass False — otherwise a deactivated
    sibling GO disappears from present_names and locale switch / export
    treats the stock original as deleted.
    """
    from . import ui_coverage

    by_id = {int(o.path_id): o for o in env.objects}
    go_trees = {}
    rt_trees = {}
    mb_trees = {}
    for o in env.objects:
        try:
            if o.type.name == "GameObject":
                go_trees[int(o.path_id)] = o.read_typetree()
            elif o.type.name == "RectTransform":
                rt_trees[int(o.path_id)] = o.read_typetree()
            elif o.type.name == "MonoBehaviour":
                mb_trees[int(o.path_id)] = o.read_typetree()
        except Exception:
            continue

    script_map = ui_coverage.build_monoscript_map(env)
    report = ui_coverage.UiCoverageReport()
    elements = []
    for go_id, go in go_trees.items():
        name = go.get("m_Name") or ("GO_%s" % go_id)
        go_active = go.get("m_IsActive", True)
        comps = go.get("m_Component") or []
        rect_id = 0
        mb_ids = []
        for c in comps:
            if isinstance(c, dict):
                cref = c.get("component") or c
            else:
                cref = c
            cid = _pid(cref)
            if not cid or cid not in by_id:
                continue
            tname = by_id[cid].type.name
            if tname == "RectTransform":
                rect_id = cid
            elif tname == "MonoBehaviour":
                mb_ids.append(cid)

        if not rect_id or rect_id not in rt_trees:
            continue
        rt = rt_trees[rect_id]
        anchored = _vec2(rt.get("m_AnchoredPosition"))
        size = _vec2(rt.get("m_SizeDelta"))
        amin = _vec2(rt.get("m_AnchorMin"))
        amax = _vec2(rt.get("m_AnchorMax"))
        pivot = _vec2(rt.get("m_Pivot"))
        local_rotation = _quat(rt.get("m_LocalRotation"))
        local_scale = _vec3(rt.get("m_LocalScale"))
        if abs(local_scale[0]) < 1e-12 and abs(local_scale[1]) < 1e-12:
            local_scale = (1.0, 1.0, 1.0)
        lp = rt.get("m_LocalPosition")
        try:
            local_position_z = float(_vec3(lp)[2]) if lp is not None else 0.0
        except Exception:
            local_position_z = 0.0
        parent_id = _pid(rt.get("m_Father"))
        # Optional; when present they are authoritative for stretch layouts
        offset_min = None
        offset_max = None
        if "m_OffsetMin" in rt:
            offset_min = _vec2(rt.get("m_OffsetMin"))
        if "m_OffsetMax" in rt:
            offset_max = _vec2(rt.get("m_OffsetMax"))

        kind = "empty"
        text = ""
        font_size = 14.0
        color = (1.0, 1.0, 1.0, 1.0)
        text_alignment = 0
        font_style = 0
        is_rich_text = True
        enable_word_wrapping = True
        line_spacing = 0.0
        margin = (0.0, 0.0, 0.0, 0.0)
        character_spacing = 0.0
        word_spacing = 0.0
        paragraph_spacing = 0.0
        enable_auto_sizing = False
        font_size_min = 0.0
        font_size_max = 0.0
        overflow_mode = 0
        enable_kerning = True
        mb_path_id = 0
        sprite_path_id = 0
        texture_path_id = 0
        font_family = ""
        is_ui_text = False
        texture_external = False
        font_asset_path_id = 0
        font_asset_file_id = 0
        image_type = 0
        preserve_aspect = False
        fill_center = True
        fill_method = 0
        fill_amount = 1.0
        fill_clock_wise = True
        fill_origin = 0
        is_raw_image = False
        horizontal_alignment = 0
        vertical_alignment = 0
        outline_width = 0.0
        outline_color = (0.0, 0.0, 0.0, 1.0)
        face_color = (1.0, 1.0, 1.0, 1.0)
        enable_vertex_gradient = False
        gradient_top_left = (1.0, 1.0, 1.0, 1.0)
        gradient_top_right = (1.0, 1.0, 1.0, 1.0)
        gradient_bottom_left = (1.0, 1.0, 1.0, 1.0)
        gradient_bottom_right = (1.0, 1.0, 1.0, 1.0)
        tint_all_sprites = False
        horizontal_mapping = 0
        vertical_mapping = 0
        is_volumetric_text = False
        page_to_display = 1
        linked_text_path_id = 0
        sprite_animator_path_id = 0
        script_class = ""
        meta_scripts = []
        effect_distance = (0.0, 0.0)
        use_graphic_alpha = True
        has_ui_outline = False
        has_ui_shadow = False

        for mid in mb_ids:
            tree = mb_trees.get(mid) or {}
            role, script_label, used_fb = ui_coverage.classify_mb_role(
                tree, script_map
            )
            ui_coverage.accumulate_coverage(
                report, role, script_label, used_fb
            )
            cn = ui_coverage.class_name_only(script_label)
            if role == "skip":
                continue
            if role == "meta":
                if cn and cn not in meta_scripts:
                    meta_scripts.append(cn)
                if not script_class:
                    script_class = cn or script_label
                # Unity UI Outline / Shadow on same GO as Graphic
                if cn in ("Outline", "Shadow") or (
                    "m_EffectColor" in tree and "m_EffectDistance" in tree
                ):
                    from . import ui_roundtrip as _urt
                    eff = _urt.extract_ui_effect_fields(tree)
                    outline_color = tuple(eff.get("effect_color") or outline_color)
                    effect_distance = tuple(
                        eff.get("effect_distance") or effect_distance
                    )
                    use_graphic_alpha = bool(eff.get("use_graphic_alpha", True))
                    dx, dy = effect_distance
                    mag = (abs(dx) ** 2 + abs(dy) ** 2) ** 0.5
                    if outline_width < 1e-6 and mag > 1e-6:
                        outline_width = float(mag)
                    if cn == "Outline" or (cn != "Shadow" and mag > 0):
                        has_ui_outline = has_ui_outline or (cn == "Outline")
                    if cn == "Shadow":
                        has_ui_shadow = True
                    if cn == "Outline":
                        has_ui_outline = True
                # CanvasScaler / DatabaseScreen alone — keep for meta element
                continue
            # TextMeshProUGUI uses m_text; classic Unity UI.Text uses m_Text + m_FontData
            # (PlanetaryBaseInc / older KSPedia pages). Prefer script role, then fields.
            if role == "text" or "m_text" in tree or "m_Text" in tree:
                if kind == "text":
                    continue
                kind = "text"
                text = tree.get("m_text")
                if text is None:
                    text = tree.get("m_Text") or ""
                if not isinstance(text, str):
                    text = str(text)
                fd = tree.get("m_FontData") if isinstance(tree.get("m_FontData"), dict) else {}
                if "m_fontSize" in tree:
                    font_size = float(tree.get("m_fontSize") or 14.0)
                else:
                    font_size = float(fd.get("m_FontSize") or 14.0)
                is_ui_text = ("m_FontData" in tree) or (
                    "m_Text" in tree and "m_text" not in tree
                )
                color = _color(tree.get("m_fontColor") or tree.get("m_Color"))
                try:
                    if "m_textAlignment" in tree:
                        text_alignment = int(tree.get("m_textAlignment") or 0)
                    else:
                        # Unity UI TextAnchor 0..8 → approximate TMP horizontal
                        text_alignment = int(fd.get("m_Alignment") or 0)
                except Exception:
                    text_alignment = 0
                try:
                    if "m_fontStyle" in tree:
                        font_style = int(tree.get("m_fontStyle") or 0)
                    else:
                        font_style = int(fd.get("m_FontStyle") or 0)
                except Exception:
                    font_style = 0
                try:
                    if "m_isRichText" in tree:
                        is_rich_text = bool(tree.get("m_isRichText", True))
                    elif "m_RichText" in fd:
                        is_rich_text = bool(fd.get("m_RichText", True))
                    else:
                        is_rich_text = True
                except Exception:
                    is_rich_text = True
                try:
                    if "m_enableWordWrapping" in tree:
                        enable_word_wrapping = bool(
                            tree.get("m_enableWordWrapping", True)
                        )
                    else:
                        # UI.Text: HorizontalOverflow 0=Wrap, 1=Overflow
                        enable_word_wrapping = int(
                            fd.get("m_HorizontalOverflow") or 0
                        ) == 0
                except Exception:
                    enable_word_wrapping = True
                try:
                    if "m_lineSpacing" in tree:
                        line_spacing = float(tree.get("m_lineSpacing") or 0.0)
                    else:
                        # UI.Text line spacing is a multiplier (1.0 = default)
                        ls = float(fd.get("m_LineSpacing") or 1.0)
                        line_spacing = 0.0 if abs(ls - 1.0) < 1e-6 else (ls - 1.0)
                except Exception:
                    line_spacing = 0.0
                try:
                    character_spacing = float(tree.get("m_characterSpacing") or 0.0)
                except Exception:
                    character_spacing = 0.0
                try:
                    word_spacing = float(tree.get("m_wordSpacing") or 0.0)
                except Exception:
                    word_spacing = 0.0
                try:
                    paragraph_spacing = float(
                        tree.get("m_paragraphSpacing") or 0.0
                    )
                except Exception:
                    paragraph_spacing = 0.0
                try:
                    enable_auto_sizing = bool(
                        tree.get("m_enableAutoSizing", False)
                    )
                except Exception:
                    enable_auto_sizing = False
                try:
                    font_size_min = float(tree.get("m_fontSizeMin") or 0.0)
                except Exception:
                    font_size_min = 0.0
                try:
                    font_size_max = float(tree.get("m_fontSizeMax") or 0.0)
                except Exception:
                    font_size_max = 0.0
                try:
                    overflow_mode = int(tree.get("m_overflowMode") or 0)
                except Exception:
                    overflow_mode = 0
                try:
                    enable_kerning = bool(tree.get("m_enableKerning", True))
                except Exception:
                    enable_kerning = True
                mraw = tree.get("m_margin")
                if isinstance(mraw, dict):
                    margin = (
                        float(mraw.get("x", 0.0) or 0.0),
                        float(mraw.get("y", 0.0) or 0.0),
                        float(mraw.get("z", 0.0) or 0.0),
                        float(mraw.get("w", 0.0) or 0.0),
                    )
                elif mraw is not None:
                    try:
                        margin = (
                            float(mraw[0]), float(mraw[1]),
                            float(mraw[2]), float(mraw[3]),
                        )
                    except Exception:
                        margin = (0.0, 0.0, 0.0, 0.0)
                mb_path_id = mid
                # font family resolved later in load_bundle when deps known
                font_family = _tmp_font_family(tree)
                from . import ui_roundtrip as _urt
                _ex = _urt.extract_tmp_extra(tree)
                font_asset_path_id = int(_ex.get("font_asset_path_id") or 0)
                font_asset_file_id = int(_ex.get("font_asset_file_id") or 0)
                horizontal_alignment = int(_ex.get("horizontal_alignment") or 0)
                vertical_alignment = int(_ex.get("vertical_alignment") or 0)
                outline_width = float(_ex.get("outline_width") or 0.0)
                outline_color = tuple(_ex.get("outline_color") or (0, 0, 0, 1))
                if _ex.get("character_spacing") is not None:
                    character_spacing = float(_ex["character_spacing"])
                if _ex.get("word_spacing") is not None:
                    word_spacing = float(_ex["word_spacing"])
                if _ex.get("paragraph_spacing") is not None:
                    paragraph_spacing = float(_ex["paragraph_spacing"])
                enable_auto_sizing = bool(_ex.get("enable_auto_sizing", False))
                font_size_min = float(_ex.get("font_size_min") or 0.0)
                font_size_max = float(_ex.get("font_size_max") or 0.0)
                overflow_mode = int(_ex.get("overflow_mode") or 0)
                enable_kerning = bool(_ex.get("enable_kerning", True))
                is_rich_text = bool(_ex.get("is_rich_text", True))
                face_color = tuple(_ex.get("face_color") or face_color)
                enable_vertex_gradient = bool(
                    _ex.get("enable_vertex_gradient", False)
                )
                gradient_top_left = tuple(
                    _ex.get("gradient_top_left") or gradient_top_left
                )
                gradient_top_right = tuple(
                    _ex.get("gradient_top_right") or gradient_top_right
                )
                gradient_bottom_left = tuple(
                    _ex.get("gradient_bottom_left") or gradient_bottom_left
                )
                gradient_bottom_right = tuple(
                    _ex.get("gradient_bottom_right") or gradient_bottom_right
                )
                tint_all_sprites = bool(_ex.get("tint_all_sprites", False))
                horizontal_mapping = int(_ex.get("horizontal_mapping") or 0)
                vertical_mapping = int(_ex.get("vertical_mapping") or 0)
                is_volumetric_text = bool(_ex.get("is_volumetric_text", False))
                page_to_display = int(_ex.get("page_to_display") or 1)
                linked_text_path_id = int(_ex.get("linked_text_path_id") or 0)
                sprite_animator_path_id = int(
                    _ex.get("sprite_animator_path_id") or 0
                )
                # Viewport fill: faceColor / vertex gradient average
                color = tuple(_urt.tmp_display_color(color, _ex))
                # UI Outline on same GO may have already set outline_*; TMP
                # outlineWidth wins when larger.
                tw = float(_ex.get("outline_width") or 0.0)
                if tw > outline_width:
                    outline_width = tw
                    outline_color = tuple(
                        _ex.get("outline_color") or outline_color
                    )
                # Do not break — later Outline/Shadow meta on same GO must apply.
                continue
            if role == "image" or "m_Sprite" in tree or (
                "m_Texture" in tree and "m_FontData" not in tree
            ):
                if kind == "image":
                    continue
                kind = "image"
                sprite_path_id = _pid(tree.get("m_Sprite"))
                if sprite_path_id:
                    texture_path_id = sprite_tex.get(sprite_path_id, 0)
                else:
                    texture_path_id = _pid(tree.get("m_Texture"))
                color = _color(tree.get("m_Color"))
                mb_path_id = mid
                from . import ui_roundtrip as _urt
                _im = _urt.extract_image_fields(tree)
                image_type = int(_im.get("image_type") or 0)
                preserve_aspect = bool(_im.get("preserve_aspect", False))
                fill_center = bool(_im.get("fill_center", True))
                fill_method = int(_im.get("fill_method") or 0)
                fill_amount = float(_im.get("fill_amount") if _im.get("fill_amount") is not None else 1.0)
                fill_clock_wise = bool(_im.get("fill_clock_wise", True))
                fill_origin = int(_im.get("fill_origin") or 0)
                is_raw_image = bool(_im.get("is_raw_image", False))

        if kind == "empty" and meta_scripts:
            kind = "meta"
            if not script_class:
                script_class = meta_scripts[0]

        # Deleted labels are exported as m_IsActive=false (and often empty
        # m_Text). Reimport used to rebuild them as vacant FONT boxes.
        # Artwork pads (leading newline / space run on the image) stay.
        # if skip_inactive_text:
        if kind == "text" and skip_inactive_text:
            overlay = _text_is_artwork_overlay(text)
            if not overlay:
                # _inject_inactive_ui_ancestors: ConfS1 links ConfB1 into Configuration
                try:
                    if go_active in (False, 0, "false", "False"):
                        continue
                except Exception:
                    pass
                if not str(text or "").strip():
                    continue

        elements.append(
            KspUiElement(
                name=name,
                path_id=go_id,
                go_path_id=go_id,
                rect_path_id=rect_id,
                kind=kind,
                text=text,
                font_size=font_size,
                color=color,
                anchored_position=anchored,
                size_delta=size,
                anchor_min=amin,
                anchor_max=amax,
                pivot=pivot,
                offset_min=offset_min,
                offset_max=offset_max,
                local_rotation=local_rotation,
                local_scale=local_scale,
                local_position_z=local_position_z,
                text_alignment=text_alignment,
                font_style=font_style,
                is_rich_text=is_rich_text,
                enable_word_wrapping=enable_word_wrapping,
                line_spacing=line_spacing,
                margin=margin,
                character_spacing=character_spacing,
                word_spacing=word_spacing,
                paragraph_spacing=paragraph_spacing,
                enable_auto_sizing=enable_auto_sizing,
                font_size_min=font_size_min,
                font_size_max=font_size_max,
                overflow_mode=overflow_mode,
                enable_kerning=enable_kerning,
                parent_rect_path_id=parent_id,
                mb_path_id=mb_path_id,
                sprite_path_id=sprite_path_id,
                texture_path_id=texture_path_id,
                # UI.Text family from m_FontData.m_Font (OpenSans /
                # Amaranth on PBS). Leave empty when unresolved — import
                # falls back to Arial only as last resort after inventory.
                font_family=(font_family or ""),
                is_ui_text=is_ui_text,
                font_asset_path_id=int(font_asset_path_id or 0),
                font_asset_file_id=int(font_asset_file_id or 0),
                texture_external=texture_external,
                image_type=int(image_type or 0),
                preserve_aspect=bool(preserve_aspect),
                fill_center=bool(fill_center),
                fill_method=int(fill_method or 0),
                fill_amount=float(fill_amount),
                fill_clock_wise=bool(fill_clock_wise),
                fill_origin=int(fill_origin or 0),
                is_raw_image=bool(is_raw_image),
                horizontal_alignment=int(horizontal_alignment or 0),
                vertical_alignment=int(vertical_alignment or 0),
                outline_width=float(outline_width or 0.0),
                outline_color=tuple(outline_color),
                locale_tag="",
                face_color=tuple(face_color),
                enable_vertex_gradient=bool(enable_vertex_gradient),
                gradient_top_left=tuple(gradient_top_left),
                gradient_top_right=tuple(gradient_top_right),
                gradient_bottom_left=tuple(gradient_bottom_left),
                gradient_bottom_right=tuple(gradient_bottom_right),
                tint_all_sprites=bool(tint_all_sprites),
                horizontal_mapping=int(horizontal_mapping or 0),
                vertical_mapping=int(vertical_mapping or 0),
                is_volumetric_text=bool(is_volumetric_text),
                page_to_display=int(page_to_display or 1),
                linked_text_path_id=int(linked_text_path_id or 0),
                sprite_animator_path_id=int(sprite_animator_path_id or 0),
                script_class=str(script_class or ""),
                meta_scripts=",".join(meta_scripts),
                effect_distance=tuple(effect_distance),
                use_graphic_alpha=bool(use_graphic_alpha),
                has_ui_outline=bool(has_ui_outline),
                has_ui_shadow=bool(has_ui_shadow),
            )
        )

    # Sibling draw order from RectTransform.m_Children (Image before labels).
    sibling_of: Dict[int, int] = {}
    for _rt_id, rt in rt_trees.items():
        children = rt.get("m_Children") or []
        if not isinstance(children, list):
            continue
        for i, ch in enumerate(children):
            cid = _pid(ch)
            if cid:
                sibling_of[int(cid)] = int(i)
    for el in elements:
        rid = int(getattr(el, "rect_path_id", 0) or 0)
        if rid in sibling_of:
            el.sibling_index = sibling_of[rid]
    ui_coverage.merge_element_kinds(report, elements)
    try:
        ui_coverage.analyze_field_coverage(env, elements, report)
    except Exception:
        pass
    return elements, report



def _bundle_dependency_names(env) -> List[str]:
    """Return AssetBundle.m_Dependencies names (e.g. ['squadcore'])."""
    names = []
    for obj in env.objects:
        if obj.type.name != "AssetBundle":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        deps = tree.get("m_Dependencies") or []
        if isinstance(deps, list):
            for d in deps:
                if isinstance(d, str) and d and d not in names:
                    names.append(d)
                elif isinstance(d, dict):
                    n = d.get("name") or d.get("m_Name") or ""
                    if n and n not in names:
                        names.append(str(n))
        break
    return names


def _resolve_dep_paths(filepath: str, dep_names: List[str]) -> List[str]:
    """Locate dependency .ksp files next to the loaded bundle.

    Also checks addon ``import_ksp/samples/`` (bundled kspfonts) and the
    optional test GameData tree — same offline idea as ``flags/``.
    """
    directory = os.path.dirname(os.path.abspath(filepath))
    addon_ksp = os.path.dirname(os.path.abspath(__file__))
    samples = os.path.join(addon_ksp, "samples")
    test_gd = os.path.join(
        os.path.dirname(addon_ksp), "test tools v2", "GameData", "Squad", "KSPedia"
    )
    out = []
    seen = set()
    for name in dep_names:
        candidates = [
            os.path.join(directory, name + ".ksp"),
            os.path.join(directory, name),
            os.path.join(directory, name.lower() + ".ksp"),
        ]
        parent = os.path.dirname(directory)
        candidates.extend([
            os.path.join(parent, "KSPedia", name + ".ksp"),
            os.path.join(parent, name + ".ksp"),
            os.path.join(samples, name + ".ksp"),
            os.path.join(test_gd, name + ".ksp"),
        ])
        for c in candidates:
            c = os.path.abspath(c)
            if c not in seen and os.path.isfile(c):
                seen.add(c)
                out.append(c)
                break
    return out


def _load_env_safe(UnityPy, filepath: str):
    try:
        return UnityPy.load(filepath)
    except Exception:
        return None


def _collect_textures_from_env(env) -> Dict[int, KspTexture]:
    out = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ("tex_%s" % obj.path_id)
            png = _texture_png_bytes(data)
            out[int(obj.path_id)] = KspTexture(
                name=name,
                path_id=int(obj.path_id),
                width=int(getattr(data, "m_Width", 0) or 0),
                height=int(getattr(data, "m_Height", 0) or 0),
                png_bytes=png,
                external=True,
            )
        except Exception:
            continue
    return out


def _build_sprite_tex_map_multi(envs) -> Dict[int, int]:
    """Merge sprite→texture maps from primary + dependency environments."""
    out = {}
    for env in envs:
        if env is None:
            continue
        out.update(_build_sprite_tex_map(env))
    return out


def _sprite_file_id(tree) -> int:
    sp = tree.get("m_Sprite")
    if isinstance(sp, dict):
        try:
            return int(sp.get("m_FileID", sp.get("file_id", 0)) or 0)
        except Exception:
            return 0
    return 0


def _tmp_font_family(tree, by_id=None, dep_envs=None) -> str:
    """Best-effort TMP / UI.Text font asset name from font PPtrs.

    Stock KSPedia pages store the TMP Font Asset on ``m_fontAsset``
    (often FileID=1 → squadcore), while ``m_font`` is usually null.
    Classic UI.Text keeps the Font on ``m_FontData.m_Font`` (PBS OpenSans /
    Amaranth) — without that lookup every PBS body fell back to Arial.
    """
    refs = [
        tree.get("m_fontAsset"),
        tree.get("m_font"),
        tree.get("m_Font"),
    ]
    fd = tree.get("m_FontData")
    if isinstance(fd, dict):
        refs.append(fd.get("m_Font"))
    pids = []
    for ref in refs:
        pid = _pid(ref)
        if pid and pid not in pids:
            pids.append(pid)
    if not pids:
        return ""
    # Search local then dependency envs for MonoBehaviour / named asset
    envs = []
    if by_id is not None:
        envs.append(("local", by_id))
    for env in (dep_envs or []):
        if env is None:
            continue
        envs.append(("dep", {int(o.path_id): o for o in env.objects}))
    for pid in pids:
        for _tag, idmap in envs:
            obj = idmap.get(int(pid))
            if obj is None:
                continue
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "") or ""
                if name:
                    return str(name)
            except Exception:
                pass
            try:
                t = obj.read_typetree()
                if isinstance(t, dict):
                    n = t.get("m_Name") or ""
                    if n:
                        return str(n)
                    fi = t.get("m_faceInfo") or t.get("m_fontInfo") or {}
                    if isinstance(fi, dict):
                        fam = fi.get("m_FamilyName") or fi.get("Name") or ""
                        if fam:
                            return str(fam)
            except Exception:
                pass
    return ""


def _asset_object_name(obj) -> str:
    try:
        data = obj.read()
        name = getattr(data, "m_Name", "") or ""
        if name:
            return str(name)
    except Exception:
        pass
    try:
        t = obj.read_typetree()
        if isinstance(t, dict):
            n = t.get("m_Name") or ""
            if n:
                return str(n)
    except Exception:
        pass
    return ""


def _inventory_ksp_fonts(env, dep_envs=None, ui_elements=None) -> Dict[str, int]:
    """Unique Font / TMP family name → path_id (0 if usage-only, no local asset).

    Scans Font and TMP Font Asset objects in the primary bundle, then adds
    ``font_family`` names from UI.Text / TMP elements so unused assets and
    used-but-external faces both count.  Verbose per-face INFO/WARNING dumps
    are omitted — coverage folds this into ``fonts=N``.
    """
    # name -> path_id (first local asset wins; usage-only stays 0)
    path_ids: Dict[str, int] = {}

    for obj in env.objects:
        try:
            tname = obj.type.name
        except Exception:
            continue
        pid = 0
        try:
            pid = int(obj.path_id)
        except Exception:
            pid = 0
        if tname == "Font":
            n = _asset_object_name(obj)
            if n:
                path_ids.setdefault(str(n), pid)
            continue
        if tname != "MonoBehaviour":
            continue
        try:
            t = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(t, dict):
            continue
        if not (t.get("m_faceInfo") or t.get("m_fontInfo") or t.get("m_glyphInfoList")):
            continue
        n = str(t.get("m_Name") or "") or ""
        if not n:
            fi = t.get("m_faceInfo") or t.get("m_fontInfo") or {}
            if isinstance(fi, dict):
                n = str(fi.get("m_FamilyName") or fi.get("Name") or "")
        if n:
            path_ids.setdefault(n, pid)

    for el in (ui_elements or []):
        if getattr(el, "kind", "") != "text":
            continue
        fam = str(getattr(el, "font_family", "") or "").strip()
        if fam and not fam.startswith("("):
            path_ids.setdefault(fam, 0)
            el_pid = int(getattr(el, "font_asset_path_id", 0) or 0)
            if el_pid and not path_ids.get(fam):
                path_ids[fam] = el_pid

    return path_ids


# abspath -> (mtime, KspBundle) — sibling .lang parse without textures/deps
_LOCALE_UI_CACHE: Dict[str, Tuple[float, KspBundle]] = {}


def load_env_for_export(filepath: str):
    """Open UnityFS for patching/export without Texture2D→PNG conversion.

    Export already reads image bytes from Blender ``kb.textures``; decoding every
    Texture2D in the template (~1s+ on PBS) is wasted work on each save.
    """
    return _open_unityfs_env(filepath)


def _open_unityfs_env(filepath: str):
    """Load a UnityFS file into UnityPy. Shared by full and locale-only parsers."""
    if not ensure_unitypy_or_prompt():
        from .deps import need_restart
        msg = last_error() or "unknown"
        if need_restart():
            raise KspBundleError(msg)
        raise KspBundleError("UnityPy is not available: %s" % msg)
    import UnityPy

    if not hasattr(UnityPy, "load"):
        raise KspBundleError(
            "Broken UnityPy install (no load). "
            "Restart Blender after Ensure UnityPy / pip install."
        )
    filepath = os.path.abspath(filepath)
    if not os.path.isfile(filepath):
        raise KspBundleError("File not found: %s" % filepath)
    try:
        with open(filepath, "rb") as f:
            magic = f.read(7)
        if magic != b"UnityFS":
            raise KspBundleError(
                "Not a UnityFS AssetBundle (missing UnityFS magic): %s"
                % filepath
            )
        env = UnityPy.load(filepath)
    except KspBundleError:
        raise
    except Exception as e:
        raise KspBundleError("Failed to load AssetBundle: %s" % e)
    return filepath, env


def load_locale_ui_bundle(filepath: str) -> KspBundle:
    """Parse a .ksp/.lang for locale text/layout maps only.

    Skips Texture2D PNG conversion, dependency bundles, sprite atlas attach,
    and font inventory — those are only needed for the viewport import of
    the main English .ksp.
    """
    filepath = os.path.abspath(filepath)
    try:
        mtime = os.path.getmtime(filepath)
    except Exception:
        mtime = 0.0
    cached = _LOCALE_UI_CACHE.get(filepath)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    filepath, env = _open_unityfs_env(filepath)
    counts = {}
    text_assets = []
    for obj in env.objects:
        tname = obj.type.name
        counts[tname] = counts.get(tname, 0) + 1
        if tname != "TextAsset":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ("text_%s" % obj.path_id)
            text, raw = _text_asset_payload(data)
            text_assets.append(
                KspTextAsset(
                    name=name,
                    path_id=int(obj.path_id),
                    text=text,
                    script_bytes=raw,
                )
            )
        except Exception:
            continue
    ui_elements, ui_report = _collect_ui(env, {}, skip_inactive_text=False)
    name = os.path.splitext(os.path.basename(filepath))[0]
    kind = _classify_kind(counts, ui_elements, text_assets, [], [])
    coverage = ""
    unknown = 0
    try:
        coverage = ui_report.format_report()
        unknown = sum(ui_report.unknown_scripts.values())
    except Exception:
        pass
    bundle = KspBundle(
        filepath=filepath,
        name=name,
        kind=kind,
        textures=[],
        text_assets=text_assets,
        shaders=[],
        ui_elements=ui_elements,
        object_counts=counts,
        coverage_report=coverage,
        coverage_unknown=unknown,
    )
    try:
        _LOCALE_UI_CACHE[filepath] = (mtime, bundle)
    except Exception:
        pass
    return bundle


def load_bundle(filepath: str) -> Tuple[KspBundle, Any]:
    """Load a .ksp UnityFS AssetBundle. Returns (KspBundle, UnityPy env)."""
    try:
        from .progress_util import tick
        tick(6, text="Opening UnityFS…")
    except Exception:
        pass
    filepath, env = _open_unityfs_env(filepath)
    try:
        from .progress_util import tick
        tick(10, text="Scanning assets…")
    except Exception:
        pass
    import UnityPy
    counts = {}
    textures = []
    text_assets = []
    shaders = []

    objects = list(env.objects)
    n_obj = max(len(objects), 1)
    for i, obj in enumerate(objects):
        if (i % max(1, n_obj // 30)) == 0 or i + 1 >= n_obj:
            try:
                from .progress_util import tick_items
                tick_items(i, n_obj, 10, 18, text="Scanning assets…")
            except Exception:
                pass
        tname = obj.type.name
        counts[tname] = counts.get(tname, 0) + 1
        try:
            if tname == "Texture2D":
                data = obj.read()
                name = getattr(data, "m_Name", "") or ("tex_%s" % obj.path_id)
                png = _texture_png_bytes(data)
                fmt, th = _texture_meta(data, png)
                textures.append(
                    KspTexture(
                        name=name,
                        path_id=int(obj.path_id),
                        width=int(getattr(data, "m_Width", 0) or 0),
                        height=int(getattr(data, "m_Height", 0) or 0),
                        png_bytes=png,
                        texture_format=fmt,
                        content_hash=th,
                    )
                )
            elif tname == "TextAsset":
                data = obj.read()
                name = getattr(data, "m_Name", "") or ("text_%s" % obj.path_id)
                text, raw = _text_asset_payload(data)
                text_assets.append(
                    KspTextAsset(
                        name=name,
                        path_id=int(obj.path_id),
                        text=text,
                        script_bytes=raw,
                    )
                )
            elif tname == "Shader":
                data = obj.read()
                name = getattr(data, "m_Name", "") or ("shader_%s" % obj.path_id)
                shaders.append(
                    KspShaderInfo(name=name, path_id=int(obj.path_id))
                )
        except Exception:
            continue

    # Resolve dependency bundles (typically squadcore) for Background* sprites
    dep_names = _bundle_dependency_names(env)
    if not dep_names:
        dep_names = ["squadcore"]
    dep_envs = []
    dep_tex_by_id = {}
    for dep_path in _resolve_dep_paths(filepath, dep_names):
        denv = _load_env_safe(UnityPy, dep_path)
        if denv is None:
            continue
        dep_envs.append(denv)
        for tid, tex in _collect_textures_from_env(denv).items():
            dep_tex_by_id[tid] = tex

    # Merge bundled Background* sprite→tex ids (flags-style offline pack)
    try:
        from .assets_util import (
            bundled_sprite_tex_map,
            load_background_png_bytes,
        )
        bundled_map = bundled_sprite_tex_map()
    except Exception:
        bundled_map = {}
        load_background_png_bytes = None  # type: ignore

    sprite_tex = _build_sprite_tex_map_multi([env] + dep_envs)
    for sid, tid in bundled_map.items():
        sprite_tex.setdefault(int(sid), int(tid))

    try:
        from .progress_util import tick
        tick(18, text="Collecting UI…", force=True)
    except Exception:
        pass
    ui_elements, ui_report = _collect_ui(env, sprite_tex, skip_inactive_text=True)
    try:
        from .progress_util import tick
        tick(22, text="UI collected", force=True)
    except Exception:
        pass
    _pref_rects = []
    # Tag locale trees (keep all for export; preferred ids for viewport).
    try:
        from .layout import prefer_locale_ui_elements
        import os as _os
        from .layout import classify_ui_layout_mode
        from . import ui_roundtrip as _urt
        prefer = _os.environ.get("KSP_UI_LOCALE", "en")
        _mode = classify_ui_layout_mode(ui_elements)
        if _mode == "locale":
            # P2: keep ALL locale trees for export; preferred ids for viewport
            ui_elements, _preferred_locale_rects = _urt.tag_locale_trees(
                ui_elements, prefer=prefer
            )
            _pref_rects = sorted(int(x) for x in (_preferred_locale_rects or []))
        else:
            # multipage / single: do not collapse or locale-tag roots
            _pref_rects = []
    except Exception:
        pass

    # Attach external textures. Background* sprites that live in the KSPedia
    # sprite atlas (BackgroundBlack / BackgroundWhite) share one Texture2D
    # path_id with the full atlas — loading that dep texture stretches the
    # whole atlas (black/grey/white bands) as the page background. Always
    # prefer the cropped bundled PNG keyed by sprite_path_id first.
    local_tex_ids = {t.path_id for t in textures}
    atlas_tids = set()
    for sid, tid in bundled_map.items():
        # Multiple Background* sprites mapping to the same tid → atlas
        if tid and sum(1 for _s, _t in bundled_map.items() if _t == tid) > 1:
            atlas_tids.add(int(tid))

    def _attach_bundled_bg(el, sid, tid):
        if load_background_png_bytes is None:
            return False
        png, bname, bw, bh = load_background_png_bytes(
            sprite_path_id=sid, texture_path_id=0 if sid else tid,
        )
        if not png:
            # Fallback: tid-only resolve (non-atlas Background* textures)
            if tid and tid not in atlas_tids:
                png, bname, bw, bh = load_background_png_bytes(
                    sprite_path_id=0, texture_path_id=tid,
                )
        if not png:
            return False
        # Unique key per sprite so Black/White (shared atlas tid) do not collide
        use_tid = int(sid) if sid else int(tid) or (
            -abs(hash(bname or ("bg_%s" % sid))) & 0x7FFFFFFFFFFFFFFF
        )
        if use_tid not in local_tex_ids:
            textures.append(
                KspTexture(
                    name=bname or ("Background_%s" % sid),
                    path_id=int(use_tid),
                    width=int(bw or 0),
                    height=int(bh or 0),
                    png_bytes=png,
                    external=True,
                )
            )
            local_tex_ids.add(int(use_tid))
        el.texture_path_id = int(use_tid)
        el.texture_external = True
        return True

    for el in ui_elements:
        if el.kind != "image":
            continue
        tid = int(el.texture_path_id or 0)
        sid = int(el.sprite_path_id or 0)
        # Bundled Background* (incl. atlas crops) — before dep atlas load
        if sid and sid in bundled_map:
            if _attach_bundled_bg(el, sid, tid):
                continue
        if tid and tid in atlas_tids:
            # Known atlas tid without sprite map hit — still try crop by tid/name
            if _attach_bundled_bg(el, sid, tid):
                continue
        if tid and tid not in local_tex_ids and tid in dep_tex_by_id:
            # Skip attaching raw atlas Texture2D as a page background
            if tid in atlas_tids:
                if _attach_bundled_bg(el, sid, tid):
                    continue
            tex = dep_tex_by_id[tid]
            # Prefer bundled crop when dep tex name is a SpriteAtlas*
            tname = (tex.name or "").lower()
            if "spriteatlas" in tname or "atlas" in tname:
                if _attach_bundled_bg(el, sid, tid):
                    continue
            textures.append(tex)
            local_tex_ids.add(tid)
            el.texture_external = True
            continue
        if tid and tid in local_tex_ids:
            el.texture_external = False
            continue
        # Bundled background PNG (offline / no GameData)
        _attach_bundled_bg(el, sid, tid)

    # Only fall back to the sole local page texture when the sprite was local
    # but failed to resolve — never clobber a still-unresolved external bg.
    if len([t for t in textures if not getattr(t, "external", False)]) == 1:
        only = next(
            t.path_id for t in textures if not getattr(t, "external", False)
        )
        for el in ui_elements:
            if el.kind != "image" or el.texture_path_id:
                continue
            if el.sprite_path_id and el.sprite_path_id not in sprite_tex:
                continue
            el.texture_path_id = only

    # Re-resolve TMP / UI.Text font families with dependency envs available.
    # Overwrite empty / Arial placeholders once Font assets are indexed.
    by_id = {int(o.path_id): o for o in env.objects}
    for el in ui_elements:
        if el.kind != "text" or not el.mb_path_id:
            continue
        cur = (el.font_family or "").strip()
        if cur and cur.lower() not in ("arial", "liberation sans"):
            continue
        try:
            obj = by_id.get(int(el.mb_path_id))
            if obj is None:
                continue
            tree = obj.read_typetree()
            if isinstance(tree, dict):
                resolved = _tmp_font_family(tree, by_id, dep_envs)
                if resolved:
                    el.font_family = resolved
        except Exception:
            pass

    # Always inventory fonts at load start (unique assets + UI.Text / TMP names).
    font_inventory = _inventory_ksp_fonts(env, dep_envs, ui_elements)
    try:
        ui_report.font_count = len(
            [
                n for n in (font_inventory or {})
                if n and not str(n).startswith("(")
            ]
        )
    except Exception:
        ui_report.font_count = len(font_inventory or {})

    name = os.path.splitext(os.path.basename(filepath))[0]
    from . import ui_roundtrip as _urt
    _cmode, _cref, _cfactor = _urt.read_canvas_scaler(env)
    _mats = _urt.collect_materials(env)
    kind = _classify_kind(counts, ui_elements, text_assets, shaders, textures)
    bundle = KspBundle(
        filepath=filepath,
        name=name,
        kind=kind,
        textures=textures,
        text_assets=text_assets,
        shaders=shaders,
        ui_elements=ui_elements,
        object_counts=counts,
        coverage_report=ui_report.format_report(),
        coverage_unknown=sum(ui_report.unknown_scripts.values()),
        canvas_scale_mode=_cmode,
        canvas_ref_resolution=_cref,
        canvas_scale_factor=_cfactor,
        materials=_mats,
        preferred_locale_rect_ids=list(locals().get("_pref_rects") or []),
        font_inventory=dict(font_inventory or {}),
    )
    try:
        print("INFO: %s" % (bundle.coverage_report or "").splitlines()[0])
        for _line in (bundle.coverage_report or "").splitlines()[1:]:
            print("INFO: %s" % _line)
    except Exception:
        pass
    return bundle, env


_COMPRESSION_NAMES = {0: "none", 1: "lzma", 2: "lz4", 3: "lz4hc", 4: "lzham"}


def detect_bundle_compression(filepath: str) -> str:
    """Compression of a UnityFS file on disk: none / lzma / lz4 / lz4hc.

    Reads the archive header directly, so it also works before UnityPy
    parsed the file (and when the file is only used as an export template).
    """
    try:
        with open(filepath, "rb") as f:
            head = f.read(256)
    except Exception:
        return ""
    if not head.startswith(b"UnityFS"):
        return ""
    try:
        pos = head.index(b"\x00") + 1
        pos += 4  # format (u32)
        for _ in range(2):  # version_player, version_engine
            pos = head.index(b"\x00", pos) + 1
        pos += 8 + 4 + 4  # size (i64), compressed / uncompressed blocks info
        flags = int.from_bytes(head[pos:pos + 4], "big")
    except Exception:
        return ""
    return _COMPRESSION_NAMES.get(flags & 0x3F, "")


def save_bundle(
    env, filepath: str, packer: str = "original", fallback: str = "lz4"
) -> None:
    """Serialize UnityPy environment to filepath via temp + os.replace.

    ``original`` reuses the source archive flags, so a re-exported bundle
    keeps its compression instead of ballooning (KSP ships LZMA, a plain
    repack fell back to LZ4 and roughly doubled every file).
    """
    filepath = os.path.abspath(filepath)
    directory = os.path.dirname(filepath) or "."
    os.makedirs(directory, exist_ok=True)
    try:
        data = env.file.save(packer=packer)
    except Exception as exc:
        if packer == fallback:
            raise
        print(
            "WARNING: KSP export: packer %r failed (%s), using %r"
            % (packer, exc, fallback)
        )
        data = env.file.save(packer=fallback)
    if not isinstance(data, (bytes, bytearray)):
        data = bytes(data)
    # Drop UnityPy read handles before replacing the source path — on Windows
    # os.replace fails with Access Denied while the .lang/.ksp is still mapped.
    try:
        for obj in (
            getattr(env, "file", None),
            getattr(getattr(env, "file", None), "stream", None),
            getattr(getattr(env, "file", None), "files", None),
        ):
            if obj is None:
                continue
            close = getattr(obj, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        import gc
        gc.collect()
    except Exception:
        pass
    fd, tmp = tempfile.mkstemp(
        prefix=".ksp_export_", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # Retry replace — AV / lingering handles can flake once on Windows.
        last_err = None
        for _ in range(8):
            try:
                os.replace(tmp, filepath)
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                try:
                    import time
                    time.sleep(0.05)
                except Exception:
                    pass
        if last_err is not None:
            raise last_err
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


# Unity TextureFormats that store 4x4 blocks (DXT/BC/ETC…). Width/height
# must be multiples of 4 or KSP/Unity often hard-crashes on GPU upload.
_BLOCK_TEX_FORMATS = frozenset({
    10, 11, 12,  # DXT1 / DXT3 / DXT5
    24, 25, 26, 27,  # BC6H / BC7 / BC4 / BC5
    34, 45, 46, 47, 48,  # ETC / EAC family (common ids)
})


# Longest-side cap when rewriting a Texture2D to a new size (user-added art).
# DXT/KSPedia stay happy; 4K sources downscale uniformly. Aspect is kept.
MAX_USER_TEX_SIDE = 2048


def _pad_rgba_for_block_format(img, fmt: int):
    """Pad RGBA image so DXT/BC dimensions are multiples of 4."""
    fmt = int(fmt or 0)
    if fmt not in _BLOCK_TEX_FORMATS:
        return img
    w, h = img.size
    nw = (int(w) + 3) // 4 * 4
    nh = (int(h) + 3) // 4 * 4
    if nw == w and nh == h:
        return img
    from PIL import Image

    out = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    out.paste(img, (0, 0))
    return out


def scale_rgba_preserving_aspect(img, max_side: int = MAX_USER_TEX_SIDE):
    """Uniform downscale so max(w,h) <= max_side. Never stretches.

    Tiny transparent pad (0–3 px) only to satisfy DXT block size — not a
    letterbox that changes the visible aspect.
    """
    from PIL import Image

    if img is None:
        return Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    src = img.convert("RGBA")
    cap = max(4, int(max_side or 0) or MAX_USER_TEX_SIDE)
    sw, sh = src.size
    longest = max(int(sw), int(sh))
    if longest > cap:
        scale = float(cap) / float(longest)
        nw = max(1, int(round(sw * scale)))
        nh = max(1, int(round(sh * scale)))
        src = src.resize((nw, nh), Image.Resampling.LANCZOS)
    return src


def fit_rgba_into_canvas(img, target_w: int, target_h: int):
    """Scale ``img`` to fit inside ``target_w x target_h`` and pad (centered).

    KSPedia page art must keep the Unity Texture2D / Sprite size — changing
    to an arbitrary PNG size (e.g. 1197x847) crashes InstantiateScreen.

    Padding is fully transparent RGBA (0,0,0,0) — never opaque black.
    Callers must embed with an alpha-capable format (DXT5/RGBA32); DXT1
    turns transparent letterbox into solid black in-game.
    """
    from PIL import Image

    tw = max(1, int(target_w or 0))
    th = max(1, int(target_h or 0))
    if img is None:
        return Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    src = img.convert("RGBA")
    if src.size == (tw, th):
        return src
    sw, sh = src.size
    scale = min(float(tw) / float(sw), float(th) / float(sh))
    nw = max(1, int(sw * scale))
    nh = max(1, int(sh * scale))
    # Prefer multiples of 4 inside the canvas for DXT content regions.
    nw = max(1, (nw // 4) * 4) if tw >= 4 else nw
    nh = max(1, (nh // 4) * 4) if th >= 4 else nh
    nw = min(nw, tw)
    nh = min(nh, th)
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    out.paste(resized, ((tw - nw) // 2, (th - nh) // 2), resized)
    return out


def _rgba_needs_alpha_format(img) -> bool:
    """True when any pixel is not fully opaque (letterbox / soft edges)."""
    if img is None:
        return False
    try:
        src = img if img.mode == "RGBA" else img.convert("RGBA")
        extrema = src.getextrema()
        if extrema and len(extrema) >= 4:
            a0, _a1 = extrema[3]
            return int(a0) < 255
    except Exception:
        pass
    return False


# Unity TextureFormat ids without usable alpha (transparent → black).
_NO_ALPHA_TEX_FORMATS = frozenset({
    3,   # RGB24
    7,   # RGB565
    10,  # DXT1 / BC1
})


def _format_with_alpha(fmt: int) -> int:
    """Upgrade RGB/DXT1 to DXT5 (BC3); leave other formats alone."""
    f = int(fmt or 0)
    if f in _NO_ALPHA_TEX_FORMATS or f == 0:
        return 12  # DXT5
    return f


def _clear_texture_stream(data) -> None:
    """Force embedded pixels — UnityPy set_image may leave m_StreamData set."""
    try:
        stream = getattr(data, "m_StreamData", None)
        if stream is None:
            return
        for attr, val in (("path", ""), ("size", 0), ("offset", 0)):
            if hasattr(stream, attr):
                try:
                    setattr(stream, attr, val)
                except Exception:
                    pass
    except Exception:
        pass


def _rebind_texture_reader(obj) -> bool:
    """Point ObjectReader at in-memory ``obj.data`` after Texture2D.save().

    UnityPy ``obj.read()`` otherwise seeks ``byte_start`` on the shared file
    stream and reloads the *original* empty/streamed asset — wiping embeds.
    """
    data = getattr(obj, "data", None)
    if not data:
        return False
    try:
        from UnityPy.streams import EndianBinaryReader

        endian = obj.reader.endian
        obj.reader = EndianBinaryReader(data, endian=endian)
        obj.byte_start = 0
        obj.byte_size = len(data)
        return True
    except Exception:
        return False


def texture_has_embedded_or_streamed_pixels(data) -> bool:
    """True when Texture2D has local image_data or a non-empty m_StreamData."""
    try:
        raw = getattr(data, "image_data", None) or b""
        if raw:
            return True
    except Exception:
        pass
    try:
        stream = getattr(data, "m_StreamData", None)
        if stream is None:
            return False
        size = int(getattr(stream, "size", 0) or 0)
        path = str(getattr(stream, "path", "") or "").strip()
        return bool(size > 0 and path)
    except Exception:
        return False


def _sync_sprites_to_texture_size(env, tex_path_id: int, width: int, height: int) -> int:
    """Update Sprite rects + mesh that reference ``tex_path_id`` to full-frame size.

    Cloned sprites often keep the donor's 2048x1536 rect **and vertex mesh**
    after a smaller PNG replace — KSP then crashes in
    ``KSPediaController.InstantiateScreen`` when opening the page.
    """
    tid = int(tex_path_id or 0)
    w = int(width or 0)
    h = int(height or 0)
    if not tid or w <= 0 or h <= 0:
        return 0
    n = 0
    for obj in env.objects:
        if getattr(getattr(obj, "type", None), "name", "") != "Sprite":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        try:
            rd = getattr(data, "m_RD", None)
            tex = getattr(rd, "texture", None) if rd is not None else None
            pid = int(getattr(tex, "path_id", 0) or 0) if tex is not None else 0
        except Exception:
            pid = 0
        if pid != tid:
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            tree = None
        if not isinstance(tree, dict):
            continue
        try:
            old_rect = tree.get("m_Rect") or {}
            old_w = float(old_rect.get("width") or 0) or float(w)
            old_h = float(old_rect.get("height") or 0) or float(h)
        except Exception:
            old_w, old_h = float(w), float(h)
        ppu = float(tree.get("m_PixelsToUnits") or 100.0)
        tree["m_Rect"] = {
            "x": 0.0, "y": 0.0, "width": float(w), "height": float(h),
        }
        rd_tree = tree.get("m_RD")
        if isinstance(rd_tree, dict):
            for rect_key in ("textureRect", "m_TextureRect"):
                if rect_key in rd_tree and isinstance(rd_tree[rect_key], dict):
                    rd_tree[rect_key] = {
                        **rd_tree[rect_key],
                        "x": 0.0, "y": 0.0,
                        "width": float(w), "height": float(h),
                    }
            # Stock full-frame pattern: (ppu, w/2, ppu, h/2)
            if "uvTransform" in rd_tree:
                rd_tree["uvTransform"] = {
                    "x": float(ppu),
                    "y": float(w) * 0.5,
                    "z": float(ppu),
                    "w": float(h) * 0.5,
                }
            # Do NOT scale baked vertex bytes. Donor Sprite meshes are
            # interleaved (pos+uv+…) — treating the first 12 floats as four
            # xyz verts corrupts InstantiateScreen and crashes KSP.
            # keep_unity_size already letterboxes the Texture2D to this rect.
        try:
            obj.save_typetree(tree)
            try:
                _rebind_texture_reader(obj)
            except Exception:
                pass
            n += 1
        except Exception:
            pass
    return n


def apply_texture_png(
    env, path_id: int, png_bytes: bytes, texture_format: int = 0,
    *,
    keep_unity_size: bool = True,
    max_side: int = 0,
) -> bool:
    """Replace a Texture2D from PNG, keeping original Unity format when possible.

    By default fits the PNG into the **existing** Texture2D width/height (GEP
    Antenna = 2048x1536). Changing Unity size without a full sprite rebuild
    crashes KSP in ``KSPediaController.InstantiateScreen``.

    Pass ``keep_unity_size=False`` for user-added art whose aspect differs from
    the donor slot — letterboxing would squeeze the image. ``max_side`` then
    uniformly downscales (default ``MAX_USER_TEX_SIDE``).
    """
    from PIL import Image

    for obj in env.objects:
        if obj.type.name != "Texture2D" or int(obj.path_id) != int(path_id):
            continue
        data = obj.read()
        img = Image.open(io.BytesIO(png_bytes))
        img = img.convert("RGBA")
        fmt = int(texture_format or 0) or int(
            getattr(data, "m_TextureFormat", 0) or 0
        )
        try:
            orig_w = int(getattr(data, "m_Width", 0) or 0)
            orig_h = int(getattr(data, "m_Height", 0) or 0)
        except Exception:
            orig_w = orig_h = 0
        size_changed = False
        letterboxed = False
        if keep_unity_size and (orig_w <= 0 or orig_h <= 0):
            # Empty Load-Image clones often have 0×0 until PNG write; use the
            # cloned sprite rect so we don't shrink Unity size under a donor mesh.
            try:
                for _sp in env.objects:
                    if getattr(getattr(_sp, "type", None), "name", "") != "Sprite":
                        continue
                    st = _sp.read_typetree()
                    rd = st.get("m_RD") or {}
                    tex = rd.get("texture") if isinstance(rd, dict) else None
                    tpid = int((tex or {}).get("m_PathID") or 0) if isinstance(tex, dict) else 0
                    if tpid != int(path_id):
                        continue
                    r = st.get("m_Rect") or {}
                    ow = int(float(r.get("width") or 0))
                    oh = int(float(r.get("height") or 0))
                    if ow >= 4 and oh >= 4:
                        orig_w, orig_h = ow, oh
                        break
            except Exception:
                pass
        if keep_unity_size and orig_w > 0 and orig_h > 0:
            if img.size != (orig_w, orig_h):
                letterboxed = True
            img = fit_rgba_into_canvas(img, orig_w, orig_h)
        else:
            cap = int(max_side or 0) or MAX_USER_TEX_SIDE
            img = scale_rgba_preserving_aspect(img, max_side=cap)
            img = _pad_rgba_for_block_format(img, fmt)
            size_changed = (img.size[0] != orig_w) or (img.size[1] != orig_h)
        # Transparent letterbox / soft alpha needs DXT5 (DXT1 → black bars).
        if letterboxed or _rgba_needs_alpha_format(img):
            fmt = _format_with_alpha(fmt)
        try:
            # UnityPy: keep compressed format (DXT5=12 when alpha needed)
            if fmt:
                data.set_image(img, target_format=fmt)
            else:
                data.set_image(img)
        except TypeError:
            data.set_image(img)
            if fmt:
                try:
                    data.m_TextureFormat = fmt
                except Exception:
                    pass
        try:
            data.m_TextureFormat = int(fmt)
        except Exception:
            pass
        # Clear streaming AFTER set_image (it may re-point at .resS).
        # Do NOT obj.read() again here - that reloads the original file bytes
        # and wipes the just-embedded image_data (empty clones stay empty;
        # dirty=False + content_hash then skips forever).
        _clear_texture_stream(data)
        try:
            data.m_Width = int(img.size[0])
            data.m_Height = int(img.size[1])
        except Exception:
            pass
        # Prefer set_image's m_CompleteImageSize (= len(image_data)). Only
        # fill in a DXT1-sized estimate when image_data is somehow missing.
        try:
            embedded = getattr(data, "image_data", None) or b""
            if embedded:
                data.m_CompleteImageSize = len(embedded)
            elif fmt in _BLOCK_TEX_FORMATS:
                # DXT1=8 B/block; DXT3/5=16 B/block
                bpb = 16 if int(fmt) in (11, 12) else 8
                data.m_CompleteImageSize = (
                    (int(img.size[0]) // 4) * (int(img.size[1]) // 4) * bpb
                )
        except Exception:
            pass
        if not (getattr(data, "image_data", None) or b""):
            return False
        data.save()
        _rebind_texture_reader(obj)
        # Always sync sprites that reference this tex. Cloned Load-Image
        # sprites often keep a donor mesh/rect; even keep_unity_size embeds
        # must stay consistent or InstantiateScreen AVs.
        try:
            _sync_sprites_to_texture_size(
                env, int(path_id), int(img.size[0]), int(img.size[1])
            )
        except Exception:
            pass
        return True
    return False



def _walk_collect_path_ids(node, out: set) -> None:
    """Collect every m_PathID / path_id from a typetree node."""
    if isinstance(node, dict):
        if "m_PathID" in node or "path_id" in node:
            try:
                pid = int(node.get("m_PathID", node.get("path_id", 0)) or 0)
            except Exception:
                pid = 0
            if pid:
                out.add(pid)
        for v in node.values():
            _walk_collect_path_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_collect_path_ids(v, out)


def _read_typetree_fresh(obj):
    """Read typetree preferring in-memory ``obj.data`` after save_typetree.

    UnityPy ``read_typetree`` resets to ``byte_start`` on the shared file
    reader, so edits via ``save_typetree`` are invisible until reload unless
    we parse ``obj.data`` directly.
    """
    data = getattr(obj, "data", None)
    if data:
        try:
            from UnityPy.helpers import TypeTreeHelper
            from UnityPy.streams import EndianBinaryReader

            node = obj._get_typetree_node()
            endian = getattr(getattr(obj, "reader", None), "endian", "<")
            reader = EndianBinaryReader(data, endian=endian)
            return TypeTreeHelper.read_typetree(
                node,
                reader,
                as_dict=True,
                assetsfile=obj.assets_file,
                byte_size=len(data),
                check_read=False,
            )
        except Exception:
            pass
    return obj.read_typetree()


def collect_path_id_referrers(env, *, ignore_types=None):
    """Map target path_id -> set of (type_name, referrer_path_id).

    ``ignore_types`` skips whole object types (typically AssetBundle preload
    noise — those entries are scrubbed separately when deleting).
    """
    ignore = set(ignore_types or ())
    refs = {}
    for obj in list(getattr(env, "objects", []) or []):
        tname = getattr(getattr(obj, "type", None), "name", "") or ""
        if tname in ignore:
            continue
        try:
            tree = _read_typetree_fresh(obj)
        except Exception:
            continue
        found = set()
        _walk_collect_path_ids(tree, found)
        try:
            src = int(obj.path_id)
        except Exception:
            continue
        for pid in found:
            if int(pid) == src:
                continue
            refs.setdefault(int(pid), set()).add((tname, src))
    return refs


def _sprite_texture_pid_from_tree(tree) -> int:
    if not isinstance(tree, dict):
        return 0
    rd = tree.get("m_RD") or tree.get("RD") or {}
    if isinstance(rd, dict):
        return _pid(rd.get("texture") or rd.get("m_Texture"))
    return _pid(tree.get("m_Texture"))


def _null_pptr():
    return {"m_FileID": 0, "m_PathID": 0}


def clear_image_mb_sprite_refs(env, mb_path_ids) -> int:
    """Null Image sprite/texture PPtrs so orphan Texture2D can be purged."""
    want = set()
    for x in mb_path_ids or []:
        try:
            pid = int(x or 0)
        except Exception:
            pid = 0
        if pid:
            want.add(pid)
    if not want:
        return 0
    n = 0
    for obj in list(getattr(env, "objects", []) or []):
        if getattr(getattr(obj, "type", None), "name", "") != "MonoBehaviour":
            continue
        try:
            if int(obj.path_id) not in want:
                continue
        except Exception:
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        changed = False
        for key in ("m_Sprite", "m_OverrideSprite", "m_Texture"):
            if key not in tree:
                continue
            if _pid(tree.get(key)):
                tree[key] = _null_pptr()
                changed = True
        if not changed:
            continue
        try:
            obj.save_typetree(tree)
            n += 1
        except Exception:
            pass
    return n


def scrub_assetbundle_refs(env, remove_ids) -> int:
    """Remove preload / container PPtrs for deleted path_ids; remap slices."""
    remove_ids = {int(x) for x in (remove_ids or []) if int(x or 0)}
    if not remove_ids:
        return 0
    n = 0
    for obj in list(getattr(env, "objects", []) or []):
        if getattr(getattr(obj, "type", None), "name", "") != "AssetBundle":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        changed = False
        preload = tree.get("m_PreloadTable")
        index_map = {}
        if isinstance(preload, list):
            new_preload = []
            for i, pp in enumerate(preload):
                pid = _pid(pp)
                if pid in remove_ids:
                    index_map[i] = None
                    changed = True
                    continue
                index_map[i] = len(new_preload)
                new_preload.append(pp)
            if changed:
                tree["m_PreloadTable"] = new_preload
        cont = tree.get("m_Container")
        if isinstance(cont, list) and index_map:
            new_cont = []
            for entry in cont:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    path, info = entry[0], entry[1]
                    as_list = isinstance(entry, list)
                else:
                    new_cont.append(entry)
                    continue
                if not isinstance(info, dict):
                    new_cont.append(entry)
                    continue
                info = dict(info)
                asset_pid = _pid(info.get("asset"))
                if asset_pid in remove_ids:
                    changed = True
                    continue
                pidx = int(info.get("preloadIndex", 0) or 0)
                psize = int(info.get("preloadSize", 0) or 0)
                if psize > 0 and index_map:
                    kept = []
                    for j in range(pidx, pidx + psize):
                        nj = index_map.get(j, j if j not in index_map else None)
                        # If map incomplete (no preload filter), keep old idx
                        if j in index_map:
                            if index_map[j] is not None:
                                kept.append(index_map[j])
                        else:
                            kept.append(j)
                    if kept:
                        info["preloadIndex"] = int(min(kept))
                        info["preloadSize"] = int(len(kept))
                    else:
                        info["preloadIndex"] = 0
                        info["preloadSize"] = 0
                    changed = True
                new_cont.append([path, info] if as_list else (path, info))
            tree["m_Container"] = new_cont
        if not changed:
            continue
        try:
            obj.save_typetree(tree)
            n += 1
        except Exception:
            pass
    return n


def remove_env_objects(env, path_ids) -> int:
    """Delete local SerializedFile objects and scrub AssetBundle refs."""
    path_ids = {int(x) for x in (path_ids or []) if int(x or 0)}
    if not path_ids:
        return 0
    scrub_assetbundle_refs(env, path_ids)
    removed = 0
    seen_af = set()
    for obj in list(getattr(env, "objects", []) or []):
        af = getattr(obj, "assets_file", None)
        if af is None:
            continue
        af_id = id(af)
        if af_id in seen_af:
            continue
        seen_af.add(af_id)
        objs = getattr(af, "objects", None)
        if not isinstance(objs, dict):
            continue
        for pid in list(path_ids):
            if pid not in objs:
                continue
            try:
                del objs[pid]
                removed += 1
            except Exception:
                pass
    return removed


def texture_pids_kept_by_blender(kb) -> set:
    """Texture2D path_ids still tracked by Blender (must not be purged)."""
    keep = set()
    for item in list(getattr(kb, "textures", []) or []):
        try:
            if bool(getattr(item, "texture_external", False)):
                continue
        except Exception:
            pass
        try:
            pid = int(getattr(item, "path_id", 0) or 0)
        except Exception:
            pid = 0
        if pid:
            keep.add(pid)
    for el in list(getattr(kb, "ui_elements", []) or []):
        try:
            if bool(getattr(el, "missing_in_locale", False)):
                continue
        except Exception:
            pass
        for attr in ("texture_path_id",):
            try:
                pid = int(getattr(el, attr, 0) or 0)
            except Exception:
                pid = 0
            if pid:
                keep.add(pid)
    return keep


def pending_remove_texture_pids(kb, root=None) -> set:
    raw = ""
    try:
        raw = str(getattr(kb, "pending_remove_textures", "") or "")
    except Exception:
        raw = ""
    if (not raw) and root is not None:
        try:
            raw = str(root.get("ksp_pending_remove_textures") or "")
        except Exception:
            raw = ""
    out = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out


def collect_orphan_texture_candidates(env, kb, root=None) -> set:
    """Unity Texture2D ids not kept by Blender, plus explicit pending removals."""
    keep = texture_pids_kept_by_blender(kb)
    pending = pending_remove_texture_pids(kb, root)
    present = set()
    for obj in list(getattr(env, "objects", []) or []):
        if getattr(getattr(obj, "type", None), "name", "") == "Texture2D":
            try:
                present.add(int(obj.path_id))
            except Exception:
                pass
    return (present - keep) | (pending & present)


def purge_unreferenced_texture_assets(
    env, candidate_tex_ids, *, keep_tex_ids=None
):
    """Remove candidate Texture2D (+ orphan Sprites) with no real referrers.

    AssetBundle preload/container alone does **not** count as a use — those
    entries are scrubbed when the asset is deleted. Fonts / shared backgrounds
    stay when any Sprite / Material / MonoBehaviour / other asset still points
    at them.

    Disabled Image MonoBehaviours (``m_Enabled=False``, e.g. page-root
    Background hidden after Blender delete) do **not** keep textures alive —
    their sprite/texture PPtrs are cleared before removal so orphans from old
    Antenna tests / stock BackgroundBlueGrid can leave the bundle.

    Returns ``(n_tex_removed, n_sprite_removed)``.
    """
    keep = {int(x) for x in (keep_tex_ids or []) if int(x or 0)}
    candidates = set()
    for x in candidate_tex_ids or []:
        try:
            pid = int(x or 0)
        except Exception:
            pid = 0
        if pid and pid not in keep:
            candidates.add(pid)
    if not candidates:
        return 0, 0

    # Restrict to real Texture2D objects present in the env.
    present_tex = set()
    for obj in list(getattr(env, "objects", []) or []):
        if getattr(getattr(obj, "type", None), "name", "") != "Texture2D":
            continue
        try:
            pid = int(obj.path_id)
        except Exception:
            continue
        if pid in candidates:
            present_tex.add(pid)
    candidates = present_tex
    if not candidates:
        return 0, 0

    refs = collect_path_id_referrers(env, ignore_types=("AssetBundle",))
    sprite_of_tex = {tid: [] for tid in candidates}
    for obj in list(getattr(env, "objects", []) or []):
        if getattr(getattr(obj, "type", None), "name", "") != "Sprite":
            continue
        try:
            sid = int(obj.path_id)
            tree = _read_typetree_fresh(obj)
        except Exception:
            continue
        tid = _sprite_texture_pid_from_tree(tree)
        if tid in sprite_of_tex:
            sprite_of_tex[tid].append(sid)

    # Cache: MonoBehaviour path_id → disabled Image?
    disabled_image_mbs = set()
    by_id = {}
    for obj in list(getattr(env, "objects", []) or []):
        try:
            by_id[int(obj.path_id)] = obj
        except Exception:
            pass
    for pid, obj in by_id.items():
        if getattr(getattr(obj, "type", None), "name", "") != "MonoBehaviour":
            continue
        try:
            tree = _read_typetree_fresh(obj)
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        if "m_Sprite" not in tree and "m_Texture" not in tree:
            continue
        if tree.get("m_Enabled", True) is False:
            disabled_image_mbs.add(int(pid))

    def _real_sprite_refs(sid: int):
        """Referrers that keep a Sprite alive (ignore disabled Images)."""
        srefs = refs.get(sid, set())
        real = set()
        disabled_mbs = set()
        for t, p in srefs:
            if t in ("Texture2D", "AssetBundle", "Sprite"):
                continue
            if t == "MonoBehaviour" and int(p) in disabled_image_mbs:
                disabled_mbs.add(int(p))
                continue
            real.add((t, p))
        return real, disabled_mbs

    removable_tex = set()
    removable_spr = set()
    clear_mb_ids = set()
    for tid in candidates:
        rset = refs.get(tid, set())
        non_sprite = set()
        for t, p in rset:
            if t == "Sprite":
                continue
            if t == "MonoBehaviour" and int(p) in disabled_image_mbs:
                clear_mb_ids.add(int(p))
                continue
            non_sprite.add((t, p))
        if non_sprite:
            continue
        spr_ids = list(sprite_of_tex.get(tid) or [])
        blocked = False
        for sid in spr_ids:
            real, disabled_mbs = _real_sprite_refs(sid)
            clear_mb_ids.update(disabled_mbs)
            if real:
                blocked = True
                break
        if blocked:
            continue
        removable_tex.add(tid)
        removable_spr.update(spr_ids)

    if not removable_tex and not removable_spr:
        return 0, 0

    # Null disabled Image PPtrs so Unity does not keep dangling refs.
    if clear_mb_ids:
        try:
            clear_image_mb_sprite_refs(env, clear_mb_ids)
        except Exception:
            pass

    remove_env_objects(env, set(removable_tex) | set(removable_spr))
    return len(removable_tex), len(removable_spr)



def apply_text_asset(env, path_id: int, text: str) -> bool:
    """Replace TextAsset m_Script with UTF-8 text.

    UnityPy TypeTree writer expects m_Script as str (it encodes to utf8).
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    for obj in env.objects:
        if obj.type.name != "TextAsset" or int(obj.path_id) != int(path_id):
            continue
        data = obj.read()
        data.m_Script = text
        data.save()
        return True
    return False


def _tree_vec2(existing, value):
    """Return a Unity TypeTree-compatible Vector2 preserving key spelling."""
    x, y = _vec2(value)
    if isinstance(existing, dict):
        out = dict(existing)
        out["x"] = float(x)
        out["y"] = float(y)
        return out
    return {"x": float(x), "y": float(y)}


def apply_ui_style(
    env,
    mb_path_id: int,
    *,
    text=None,
    color=None,
    font_size=None,
    text_alignment=None,
    font_style=None,
    enable_word_wrapping=None,
    line_spacing=None,
    margin=None,
    **extra,
) -> bool:
    """Patch TMP / UI.Text fields without disturbing others."""
    apply_ui_style._extra_kwargs = extra
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        if int(obj.path_id) != int(mb_path_id):
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            return False
        is_tmp = "m_text" in tree
        is_ui_text = "m_Text" in tree
        if not is_tmp and not is_ui_text:
            return False
        changed = False
        if text is not None:
            if is_tmp:
                tree["m_text"] = str(text)
            else:
                tree["m_Text"] = str(text)
            changed = True
        if color is not None:
            key = "m_fontColor" if "m_fontColor" in tree else "m_Color"
            if key in tree:
                r, g, b, a = _color(color)
                current = tree.get(key)
                if isinstance(current, dict):
                    current = dict(current)
                    current.update({"r": r, "g": g, "b": b, "a": a})
                    tree[key] = current
                else:
                    tree[key] = {"r": r, "g": g, "b": b, "a": a}
                changed = True
        if font_size is not None:
            if "m_fontSize" in tree:
                tree["m_fontSize"] = float(font_size)
                changed = True
            elif isinstance(tree.get("m_FontData"), dict):
                fd = dict(tree.get("m_FontData"))
                fd["m_FontSize"] = int(round(float(font_size)))
                tree["m_FontData"] = fd
                changed = True
        if text_alignment is not None and "m_textAlignment" in tree:
            tree["m_textAlignment"] = int(text_alignment)
            changed = True
        if font_style is not None and "m_fontStyle" in tree:
            tree["m_fontStyle"] = int(font_style)
            changed = True
        if enable_word_wrapping is not None and "m_enableWordWrapping" in tree:
            tree["m_enableWordWrapping"] = bool(enable_word_wrapping)
            changed = True
        if line_spacing is not None and "m_lineSpacing" in tree:
            tree["m_lineSpacing"] = float(line_spacing)
            changed = True
        if margin is not None and "m_margin" in tree:
            ml, mt, mr, mb = [float(x) for x in margin]
            current = tree.get("m_margin")
            if isinstance(current, dict):
                current = dict(current)
                current.update({"x": ml, "y": mt, "z": mr, "w": mb})
                tree["m_margin"] = current
            else:
                tree["m_margin"] = {"x": ml, "y": mt, "z": mr, "w": mb}
            changed = True
        # P0 UI.Text FontData + P1 TMP extended (kwargs collected via ** below)
        from . import ui_roundtrip as _urt
        extra = getattr(apply_ui_style, "_extra_kwargs", {}) or {}
        if _urt.extend_apply_ui_style_tree(
            tree,
            font_size=font_size,
            text_alignment=text_alignment,
            font_style=font_style,
            enable_word_wrapping=enable_word_wrapping,
            line_spacing=line_spacing,
            **extra
        ):
            changed = True
        if not changed:
            return False
        obj.save_typetree(tree)
        return True
    return False


def apply_ui_text(env, mb_path_id: int, text: str) -> bool:
    """Backward-compatible wrapper for patching a TMP text field."""
    return apply_ui_style(env, mb_path_id, text=text)


def apply_rect_transform(
    env,
    rect_path_id: int,
    *,
    anchored_position=None,
    size_delta=None,
    pivot=None,
    anchor_min=None,
    anchor_max=None,
    offset_min=None,
    offset_max=None,
    local_rotation=None,
    local_scale=None,
    local_position_z=None,
) -> bool:
    """Patch specified RectTransform fields while preserving all other data."""
    fields = (
        ("m_AnchoredPosition", anchored_position),
        ("m_SizeDelta", size_delta),
        ("m_Pivot", pivot),
        ("m_AnchorMin", anchor_min),
        ("m_AnchorMax", anchor_max),
        ("m_OffsetMin", offset_min),
        ("m_OffsetMax", offset_max),
    )
    for obj in env.objects:
        if obj.type.name != "RectTransform" or int(obj.path_id) != int(rect_path_id):
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            return False
        changed = False
        for key, value in fields:
            if value is None:
                continue
            # Offset fields do not occur in every Unity version; include them
            # when requested so a template can gain authoritative stretch data.
            tree[key] = _tree_vec2(tree.get(key), value)
            changed = True
        if local_rotation is not None:
            tree["m_LocalRotation"] = _tree_quat(
                tree.get("m_LocalRotation"), local_rotation
            )
            changed = True
        if local_scale is not None:
            tree["m_LocalScale"] = _tree_vec3(tree.get("m_LocalScale"), local_scale)
            changed = True
        if local_position_z is not None and "m_LocalPosition" in tree:
            cur = tree.get("m_LocalPosition")
            xyz = _vec3(cur)
            tree["m_LocalPosition"] = _tree_vec3(
                cur, (xyz[0], xyz[1], float(local_position_z))
            )
            changed = True
        if not changed:
            return False
        obj.save_typetree(tree)
        # Same as Texture2D: without rebind, later read_typetree / pack can
        # reload the pre-edit stream and drop sizeDelta / AP patches (Load
        # Image clones then ship as 0×0 and vanish in KSPedia).
        _rebind_texture_reader(obj)
        return True
    return False


def apply_ui_image(env, mb_path_id: int, **kwargs) -> bool:
    """Patch UI.Image / RawImage (see ui_roundtrip.apply_ui_image)."""
    from . import ui_roundtrip
    return ui_roundtrip.apply_ui_image(env, mb_path_id, **kwargs)
