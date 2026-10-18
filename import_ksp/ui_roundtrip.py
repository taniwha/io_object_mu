# vim:ts=4:et
# <pep8 compliant>
"""P0–P2 KSPedia UI round-trip helpers (Image / TMP / UI.Text / CanvasScaler / locale)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _pid(ref) -> int:
    if ref is None:
        return 0
    if isinstance(ref, dict):
        try:
            return int(ref.get("m_PathID") or ref.get("path_id") or 0)
        except Exception:
            return 0
    try:
        return int(ref)
    except Exception:
        return 0


def _color(value, default=(1.0, 1.0, 1.0, 1.0)):
    if value is None:
        return default
    if isinstance(value, dict):
        return (
            float(value.get("r", default[0])),
            float(value.get("g", default[1])),
            float(value.get("b", default[2])),
            float(value.get("a", default[3])),
        )
    try:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except Exception:
        return default


def _set_color(tree, key, color):
    r, g, b, a = _color(color)
    current = tree.get(key)
    if isinstance(current, dict):
        current = dict(current)
        current.update({"r": r, "g": g, "b": b, "a": a})
        tree[key] = current
    else:
        tree[key] = {"r": r, "g": g, "b": b, "a": a}


def _pptr(file_id: int, path_id: int):
    return {"m_FileID": int(file_id or 0), "m_PathID": int(path_id or 0)}


def extract_image_fields(tree: dict) -> dict:
    out = {
        "image_type": 0,
        "preserve_aspect": False,
        "fill_center": True,
        "fill_method": 0,
        "fill_amount": 1.0,
        "fill_clock_wise": True,
        "fill_origin": 0,
        "is_raw_image": False,
    }
    if not isinstance(tree, dict):
        return out
    try:
        out["image_type"] = int(tree.get("m_Type") or 0)
    except Exception:
        pass
    try:
        out["preserve_aspect"] = bool(tree.get("m_PreserveAspect", False))
    except Exception:
        pass
    try:
        out["fill_center"] = bool(tree.get("m_FillCenter", True))
    except Exception:
        pass
    try:
        out["fill_method"] = int(tree.get("m_FillMethod") or 0)
    except Exception:
        pass
    try:
        fa = tree.get("m_FillAmount")
        out["fill_amount"] = float(1.0 if fa is None else fa)
    except Exception:
        pass
    try:
        out["fill_clock_wise"] = bool(tree.get("m_FillClockwise", True))
    except Exception:
        pass
    try:
        out["fill_origin"] = int(tree.get("m_FillOrigin") or 0)
    except Exception:
        pass
    sid = _pid(tree.get("m_Sprite"))
    tid = _pid(tree.get("m_Texture"))
    out["is_raw_image"] = (not sid) and bool(tid)
    return out


def _colors_close(a, b, eps=1.0 / 512.0) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return all(abs(float(a[i]) - float(b[i])) <= eps for i in range(4))
    except Exception:
        return False


def ui_image_unchanged(env, mb_path_id: int, **kwargs) -> bool:
    """True when UI.Image / RawImage already matches the fields we would write.

    Used so export only patches dirty images (avoids UnityPy repack cascades).
    """
    if not mb_path_id:
        return True
    color = kwargs.get("color")
    sprite_path_id = kwargs.get("sprite_path_id")
    texture_path_id = kwargs.get("texture_path_id")
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        if int(obj.path_id) != int(mb_path_id):
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            return False
        if not isinstance(tree, dict):
            return False
        is_image = "m_Sprite" in tree or "m_Type" in tree
        is_raw = "m_Texture" in tree and "m_FontData" not in tree and "m_text" not in tree
        if not is_image and not is_raw:
            return False
        if color is not None and "m_Color" in tree:
            if not _colors_close(_color(tree.get("m_Color")), color):
                return False
        fields = extract_image_fields(tree)
        checks = (
            ("image_type", "image_type", int),
            ("preserve_aspect", "preserve_aspect", bool),
            ("fill_center", "fill_center", bool),
            ("fill_method", "fill_method", int),
            ("fill_amount", "fill_amount", float),
            ("fill_clock_wise", "fill_clock_wise", bool),
            ("fill_origin", "fill_origin", int),
        )
        for kw, key, cast in checks:
            if kwargs.get(kw) is None:
                continue
            try:
                want = cast(kwargs.get(kw))
                cur = cast(fields.get(key))
            except Exception:
                return False
            if key == "fill_amount":
                if abs(float(want) - float(cur)) > 1e-4:
                    return False
            elif want != cur:
                return False
        if sprite_path_id is not None and "m_Sprite" in tree:
            if _pid(tree.get("m_Sprite")) != int(sprite_path_id):
                return False
        if texture_path_id is not None and "m_Texture" in tree:
            if _pid(tree.get("m_Texture")) != int(texture_path_id):
                return False
        return True
    return False


def extract_tmp_extra(tree: dict) -> dict:
    out = {
        "horizontal_alignment": 0,
        "vertical_alignment": 0,
        "outline_width": 0.0,
        "outline_color": (0.0, 0.0, 0.0, 1.0),
        "font_asset_path_id": 0,
        "font_asset_file_id": 0,
        "character_spacing": 0.0,
        "word_spacing": 0.0,
        "paragraph_spacing": 0.0,
        "enable_auto_sizing": False,
        "font_size_min": 0.0,
        "font_size_max": 0.0,
        "overflow_mode": 0,
        "enable_kerning": True,
        "is_rich_text": True,
        "face_color": (1.0, 1.0, 1.0, 1.0),
        "enable_vertex_gradient": False,
        "gradient_top_left": (1.0, 1.0, 1.0, 1.0),
        "gradient_top_right": (1.0, 1.0, 1.0, 1.0),
        "gradient_bottom_left": (1.0, 1.0, 1.0, 1.0),
        "gradient_bottom_right": (1.0, 1.0, 1.0, 1.0),
        "tint_all_sprites": False,
        "horizontal_mapping": 0,
        "vertical_mapping": 0,
        "is_volumetric_text": False,
        "page_to_display": 1,
        "linked_text_path_id": 0,
        "sprite_animator_path_id": 0,
    }
    if not isinstance(tree, dict):
        return out
    for key, dest in (
        ("m_HorizontalAlignment", "horizontal_alignment"),
        ("m_VerticalAlignment", "vertical_alignment"),
        ("m_overflowMode", "overflow_mode"),
        ("m_horizontalMapping", "horizontal_mapping"),
        ("m_verticalMapping", "vertical_mapping"),
        ("m_pageToDisplay", "page_to_display"),
    ):
        if key in tree:
            try:
                out[dest] = int(tree.get(key) or 0)
            except Exception:
                pass
    if "m_outlineWidth" in tree:
        try:
            out["outline_width"] = float(tree.get("m_outlineWidth") or 0.0)
        except Exception:
            pass
    if "m_outlineColor" in tree:
        out["outline_color"] = _color(tree.get("m_outlineColor"), out["outline_color"])
    if "m_faceColor" in tree:
        out["face_color"] = _color(tree.get("m_faceColor"), out["face_color"])
    for key, dest in (
        ("m_characterSpacing", "character_spacing"),
        ("m_wordSpacing", "word_spacing"),
        ("m_paragraphSpacing", "paragraph_spacing"),
        ("m_fontSizeMin", "font_size_min"),
        ("m_fontSizeMax", "font_size_max"),
    ):
        if key in tree:
            try:
                out[dest] = float(tree.get(key) or 0.0)
            except Exception:
                pass
    if "m_enableAutoSizing" in tree:
        out["enable_auto_sizing"] = bool(tree.get("m_enableAutoSizing", False))
    if "m_enableKerning" in tree:
        out["enable_kerning"] = bool(tree.get("m_enableKerning", True))
    if "m_isRichText" in tree:
        out["is_rich_text"] = bool(tree.get("m_isRichText", True))
    if "m_enableVertexGradient" in tree:
        out["enable_vertex_gradient"] = bool(tree.get("m_enableVertexGradient", False))
    if "m_tintAllSprites" in tree:
        out["tint_all_sprites"] = bool(tree.get("m_tintAllSprites", False))
    if "m_isVolumetricText" in tree:
        out["is_volumetric_text"] = bool(tree.get("m_isVolumetricText", False))
    grad = tree.get("m_fontColorGradient")
    if isinstance(grad, dict):
        for src, dest in (
            ("topLeft", "gradient_top_left"),
            ("topRight", "gradient_top_right"),
            ("bottomLeft", "gradient_bottom_left"),
            ("bottomRight", "gradient_bottom_right"),
        ):
            if src in grad:
                out[dest] = _color(grad.get(src), out[dest])
    linked = tree.get("m_linkedTextComponent")
    if isinstance(linked, dict):
        out["linked_text_path_id"] = _pid(linked)
    anim = tree.get("m_spriteAnimator")
    if isinstance(anim, dict):
        out["sprite_animator_path_id"] = _pid(anim)
    for key in ("m_fontAsset", "m_font", "m_Font"):
        ref = tree.get(key)
        if isinstance(ref, dict) and _pid(ref):
            out["font_asset_path_id"] = _pid(ref)
            try:
                out["font_asset_file_id"] = int(ref.get("m_FileID") or 0)
            except Exception:
                out["font_asset_file_id"] = 0
            break
    return out


def tmp_display_color(font_color, extra: dict):
    """Pick viewport fill color from fontColor / faceColor / vertex gradient."""
    base = _color(font_color, (1.0, 1.0, 1.0, 1.0))
    if not isinstance(extra, dict):
        return base
    if extra.get("enable_vertex_gradient"):
        cols = [
            extra.get("gradient_top_left", base),
            extra.get("gradient_top_right", base),
            extra.get("gradient_bottom_left", base),
            extra.get("gradient_bottom_right", base),
        ]
        try:
            return tuple(
                sum(float(c[i]) for c in cols) / 4.0 for i in range(4)
            )
        except Exception:
            pass
    face = extra.get("face_color")
    if face is not None:
        try:
            fr, fg, fb, fa = [float(x) for x in face[:4]]
            # Non-white faceColor modulates / replaces fill (TMP face tint).
            if abs(fr - 1.0) > 0.02 or abs(fg - 1.0) > 0.02 or abs(fb - 1.0) > 0.02:
                return (fr, fg, fb, fa if fa > 1e-6 else base[3])
        except Exception:
            pass
    return base


def extract_ui_effect_fields(tree: dict) -> dict:
    """UnityEngine.UI.Outline / Shadow fields on the same GameObject."""
    out = {
        "effect_color": (0.0, 0.0, 0.0, 0.5),
        "effect_distance": (1.0, -1.0),
        "use_graphic_alpha": True,
        "effect_kind": "",
    }
    if not isinstance(tree, dict):
        return out
    if "m_EffectColor" in tree and "m_EffectDistance" in tree:
        out["effect_color"] = _color(tree.get("m_EffectColor"), out["effect_color"])
        dist = tree.get("m_EffectDistance")
        if isinstance(dist, dict):
            out["effect_distance"] = (
                float(dist.get("x", 1.0)),
                float(dist.get("y", -1.0)),
            )
        out["use_graphic_alpha"] = bool(tree.get("m_UseGraphicAlpha", True))
        # Shadow has m_EffectDistance; Outline too — distinguish by script later
        out["effect_kind"] = "effect"
    return out


def read_canvas_scaler(env) -> Tuple[int, Tuple[float, float], float]:
    """Return (uiScaleMode, (refW, refH), scaleFactor) from first CanvasScaler."""
    for obj in getattr(env, "objects", []) or []:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        if "m_UiScaleMode" not in tree and "m_ReferenceResolution" not in tree:
            continue
        mode = int(tree.get("m_UiScaleMode") or 0)
        ref = tree.get("m_ReferenceResolution") or {}
        if isinstance(ref, dict):
            rw = float(ref.get("x") or 0.0)
            rh = float(ref.get("y") or 0.0)
        else:
            try:
                rw, rh = float(ref[0]), float(ref[1])
            except Exception:
                rw = rh = 0.0
        try:
            factor = float(tree.get("m_ScaleFactor") or 1.0)
        except Exception:
            factor = 1.0
        return mode, (rw, rh), factor
    return 0, (0.0, 0.0), 1.0


def collect_materials(env) -> List[Tuple[str, int]]:
    out = []
    for obj in getattr(env, "objects", []) or []:
        if obj.type.name != "Material":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ("mat_%s" % obj.path_id)
        except Exception:
            name = "mat_%s" % obj.path_id
        out.append((str(name), int(obj.path_id)))
    return out


def set_game_object_active(env, mb_path_id: int, active: bool) -> bool:
    """Toggle m_IsActive on the GameObject owning this MonoBehaviour.

    A translation that dropped a sentence has no such object at all, so this
    only ever fires for boxes the user deleted for one language: the asset
    stays in the bundle but KSPedia stops drawing it.
    """
    go_id = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        if int(obj.path_id) != int(mb_path_id):
            continue
        try:
            tree = obj.read_typetree()
            go_id = int((tree.get("m_GameObject") or {}).get("m_PathID") or 0)
        except Exception:
            return False
        break
    if not go_id:
        return False
    for obj in env.objects:
        if obj.type.name != "GameObject" or int(obj.path_id) != go_id:
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            return False
        want = 1 if active else 0
        if int(tree.get("m_IsActive", 1) or 0) == want:
            return False
        tree["m_IsActive"] = want
        obj.save_typetree(tree)
        return True
    return False


def set_game_object_active_by_name(env, name: str, active: bool) -> bool:
    """Toggle m_IsActive on GameObjects matching ``m_Name``.

    Used when a LOCAL Load Image was previously cloned into a sibling ``.lang``
    and the English MonoBehaviour path_id does not remap.
    """
    want_name = (name or "").strip()
    if not want_name:
        return False
    did = False
    want = 1 if active else 0
    for obj in env.objects:
        try:
            if obj.type.name != "GameObject":
                continue
            tree = obj.read_typetree()
        except Exception:
            continue
        if str(tree.get("m_Name") or "").strip() != want_name:
            continue
        if int(tree.get("m_IsActive", 1) or 0) == want:
            continue
        tree["m_IsActive"] = want
        try:
            obj.save_typetree(tree)
            did = True
        except Exception:
            pass
    return did


def apply_ui_image(
    env,
    mb_path_id: int,
    *,
    color=None,
    image_type=None,
    preserve_aspect=None,
    fill_center=None,
    fill_method=None,
    fill_amount=None,
    fill_clock_wise=None,
    fill_origin=None,
    sprite_path_id=None,
    texture_path_id=None,
) -> bool:
    """Patch Unity UI.Image / RawImage fields."""
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        if int(obj.path_id) != int(mb_path_id):
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            return False
        is_image = "m_Sprite" in tree or "m_Type" in tree
        is_raw = "m_Texture" in tree and "m_FontData" not in tree and "m_text" not in tree
        if not is_image and not is_raw:
            return False
        changed = False
        if color is not None and "m_Color" in tree:
            cur_col = _color(tree.get("m_Color"))
            if not _colors_close(cur_col, color):
                _set_color(tree, "m_Color", color)
                changed = True
        mapping = (
            ("m_Type", image_type, int),
            ("m_PreserveAspect", preserve_aspect, bool),
            ("m_FillCenter", fill_center, bool),
            ("m_FillMethod", fill_method, int),
            ("m_FillAmount", fill_amount, float),
            ("m_FillClockwise", fill_clock_wise, bool),
            ("m_FillOrigin", fill_origin, int),
        )
        for key, val, cast in mapping:
            if val is None or key not in tree:
                continue
            try:
                new_v = cast(val)
                old_v = tree.get(key)
                if key == "m_FillAmount":
                    if abs(float(old_v if old_v is not None else 0) - float(new_v)) > 1e-4:
                        tree[key] = new_v
                        changed = True
                elif cast(old_v) != new_v:
                    tree[key] = new_v
                    changed = True
            except Exception:
                pass
        if sprite_path_id is not None and "m_Sprite" in tree:
            # Never write a null sprite PPtr — crashes InstantiateScreen.
            if int(sprite_path_id) == 0:
                sprite_path_id = None
        if sprite_path_id is not None and "m_Sprite" in tree:
            cur = tree.get("m_Sprite")
            fid = int(cur.get("m_FileID") or 0) if isinstance(cur, dict) else 0
            if _pid(cur) != int(sprite_path_id):
                tree["m_Sprite"] = _pptr(fid, int(sprite_path_id))
                changed = True
        if texture_path_id is not None and "m_Texture" in tree:
            cur = tree.get("m_Texture")
            fid = int(cur.get("m_FileID") or 0) if isinstance(cur, dict) else 0
            if _pid(cur) != int(texture_path_id):
                tree["m_Texture"] = _pptr(fid, int(texture_path_id))
                changed = True
        if not changed:
            return False
        obj.save_typetree(tree)
        return True
    return False


def extend_apply_ui_style_tree(tree: dict, **kwargs) -> bool:
    """Apply extended TMP / UI.Text fields onto an existing typetree dict.

    Returns True if anything changed. Caller saves.
    """
    from .bundle import _color as bundle_color  # noqa — avoid cycle; use local
    changed = False
    is_tmp = "m_text" in tree
    is_ui = "m_Text" in tree
    fd = tree.get("m_FontData") if isinstance(tree.get("m_FontData"), dict) else None

    # --- UI.Text FontData parity ---
    if is_ui and fd is not None:
        fd = dict(fd)
        if kwargs.get("font_size") is not None:
            fd["m_FontSize"] = int(round(float(kwargs["font_size"])))
            changed = True
        if kwargs.get("text_alignment") is not None and "m_Alignment" in fd:
            fd["m_Alignment"] = int(kwargs["text_alignment"])
            changed = True
        if kwargs.get("font_style") is not None and "m_FontStyle" in fd:
            fd["m_FontStyle"] = int(kwargs["font_style"])
            changed = True
        if kwargs.get("enable_word_wrapping") is not None and "m_HorizontalOverflow" in fd:
            # 0=Wrap 1=Overflow
            fd["m_HorizontalOverflow"] = 0 if kwargs["enable_word_wrapping"] else 1
            changed = True
        if kwargs.get("line_spacing") is not None and "m_LineSpacing" in fd:
            # Blender stores delta from 1.0 for UI.Text import
            ls = float(kwargs["line_spacing"])
            fd["m_LineSpacing"] = 1.0 + ls if abs(ls) < 10 else ls
            changed = True
        if kwargs.get("is_rich_text") is not None and "m_RichText" in fd:
            fd["m_RichText"] = bool(kwargs["is_rich_text"])
            changed = True
        tree["m_FontData"] = fd

    # --- TMP extended ---
    if is_tmp:
        pairs_float = (
            ("m_characterSpacing", "character_spacing"),
            ("m_wordSpacing", "word_spacing"),
            ("m_paragraphSpacing", "paragraph_spacing"),
            ("m_fontSizeMin", "font_size_min"),
            ("m_fontSizeMax", "font_size_max"),
            ("m_outlineWidth", "outline_width"),
        )
        for key, arg in pairs_float:
            val = kwargs.get(arg)
            if val is None or key not in tree:
                continue
            tree[key] = float(val)
            changed = True
        pairs_int = (
            ("m_HorizontalAlignment", "horizontal_alignment"),
            ("m_VerticalAlignment", "vertical_alignment"),
            ("m_overflowMode", "overflow_mode"),
        )
        for key, arg in pairs_int:
            val = kwargs.get(arg)
            if val is None or key not in tree:
                continue
            tree[key] = int(val)
            changed = True
        pairs_bool = (
            ("m_enableAutoSizing", "enable_auto_sizing"),
            ("m_enableKerning", "enable_kerning"),
            ("m_isRichText", "is_rich_text"),
            ("m_enableVertexGradient", "enable_vertex_gradient"),
            ("m_tintAllSprites", "tint_all_sprites"),
            ("m_isVolumetricText", "is_volumetric_text"),
        )
        for key, arg in pairs_bool:
            val = kwargs.get(arg)
            if val is None or key not in tree:
                continue
            tree[key] = bool(val)
            changed = True
        pairs_int2 = (
            ("m_horizontalMapping", "horizontal_mapping"),
            ("m_verticalMapping", "vertical_mapping"),
            ("m_pageToDisplay", "page_to_display"),
        )
        for key, arg in pairs_int2:
            val = kwargs.get(arg)
            if val is None or key not in tree:
                continue
            tree[key] = int(val)
            changed = True
        if kwargs.get("outline_color") is not None and "m_outlineColor" in tree:
            _set_color(tree, "m_outlineColor", kwargs["outline_color"])
            changed = True
        if kwargs.get("face_color") is not None and "m_faceColor" in tree:
            _set_color(tree, "m_faceColor", kwargs["face_color"])
            changed = True
        if kwargs.get("enable_vertex_gradient") and "m_fontColorGradient" in tree:
            grad = tree.get("m_fontColorGradient")
            if isinstance(grad, dict):
                grad = dict(grad)
                for arg, key in (
                    ("gradient_top_left", "topLeft"),
                    ("gradient_top_right", "topRight"),
                    ("gradient_bottom_left", "bottomLeft"),
                    ("gradient_bottom_right", "bottomRight"),
                ):
                    if kwargs.get(arg) is not None and key in grad:
                        c = kwargs[arg]
                        cur = grad.get(key)
                        if isinstance(cur, dict):
                            cur = dict(cur)
                            cur.update(
                                {
                                    "r": float(c[0]),
                                    "g": float(c[1]),
                                    "b": float(c[2]),
                                    "a": float(c[3]),
                                }
                            )
                            grad[key] = cur
                tree["m_fontColorGradient"] = grad
                changed = True
        if kwargs.get("linked_text_path_id") is not None and "m_linkedTextComponent" in tree:
            cur = tree.get("m_linkedTextComponent")
            fid = int(cur.get("m_FileID") or 0) if isinstance(cur, dict) else 0
            tree["m_linkedTextComponent"] = _pptr(fid, int(kwargs["linked_text_path_id"]))
            changed = True
        # Font asset PPtr (same FileID, new PathID) when provided
        fpid = kwargs.get("font_asset_path_id")
        if fpid is not None:
            for key in ("m_fontAsset", "m_font", "m_Font"):
                if key not in tree:
                    continue
                cur = tree.get(key)
                fid = int(cur.get("m_FileID") or 0) if isinstance(cur, dict) else int(kwargs.get("font_asset_file_id") or 0)
                tree[key] = _pptr(fid, int(fpid))
                changed = True
                break

    # UI.Text font PPtr
    if is_ui and fd is not None and kwargs.get("font_asset_path_id") is not None:
        fd = dict(tree.get("m_FontData") or fd)
        cur = fd.get("m_Font")
        fid = int(cur.get("m_FileID") or 0) if isinstance(cur, dict) else int(kwargs.get("font_asset_file_id") or 0)
        fd["m_Font"] = _pptr(fid, int(kwargs["font_asset_path_id"]))
        tree["m_FontData"] = fd
        changed = True

    return changed


def resolve_font_path_id_by_name(env, name: str) -> Tuple[int, int]:
    """Find Font / TMP_FontAsset path_id by m_Name. Returns (file_id=0, path_id)."""
    if not name:
        return 0, 0
    want = name.strip().lower()
    for obj in getattr(env, "objects", []) or []:
        t = obj.type.name
        if t not in ("Font", "MonoBehaviour"):
            continue
        try:
            if t == "Font":
                data = obj.read()
                n = (getattr(data, "m_Name", "") or "").lower()
                if n == want or want in n:
                    return 0, int(obj.path_id)
            else:
                tree = obj.read_typetree()
                if not isinstance(tree, dict):
                    continue
                # TMP_FontAsset often has m_faceInfo
                n = (tree.get("m_Name") or "").lower()
                if (n == want or want in n) and (
                    "m_faceInfo" in tree or "m_glyphInfoList" in tree or "m_CharacterTable" in tree
                ):
                    return 0, int(obj.path_id)
        except Exception:
            continue
    return 0, 0


def _font_name_key(name: str) -> str:
    import re

    raw = (name or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"(?i)\s*sdf.*$", "", raw).strip()
    raw = re.sub(r"[\s_\-]+", "", raw)
    return raw


def resolve_font_path_id_from_kb(kb, name: str) -> Tuple[int, int]:
    """Look up Font / TMP path_id from persisted ``kb.font_inventory`` (no UnityFS).

    Prefer an exact (case-insensitive) name, then SDF-stripped equality so
    ``OpenSans-Regular`` can match a bundle Font without pointing UI.Text at a
    TMP ``… SDF`` asset (that pairing used to paint tofu in-game).
    """
    want = (name or "").strip()
    if not want or kb is None:
        return 0, 0
    want_l = want.lower()
    want_key = _font_name_key(want)
    want_sdf = "sdf" in want_l
    exact = None
    stripped_same = None
    stripped_any = None
    try:
        items = list(getattr(kb, "font_inventory", None) or [])
    except Exception:
        items = []
    for it in items:
        n = str(getattr(it, "name", "") or "").strip()
        if not n:
            continue
        try:
            pid = int(getattr(it, "path_id", 0) or 0)
        except Exception:
            pid = 0
        if not pid:
            continue
        try:
            fid = int(getattr(it, "file_id", 0) or 0)
        except Exception:
            fid = 0
        hit = (fid, pid)
        nl = n.lower()
        if nl == want_l:
            exact = hit
            break
        if want_key and _font_name_key(n) == want_key:
            n_sdf = "sdf" in nl
            if n_sdf == want_sdf:
                stripped_same = hit
            elif stripped_any is None:
                stripped_any = hit
    if exact is not None:
        return exact
    if stripped_same is not None:
        return stripped_same
    return 0, 0


def tag_locale_trees(elements, prefer="en"):
    """Tag all locale trees; keep ALL elements for export (P2 dual-locale).

    Returns (all_elements, preferred_rect_ids set for viewport).
    """
    import re
    from collections import defaultdict

    if not elements:
        return [], set()

    kids = defaultdict(list)
    roots = []
    for el in elements:
        pid = int(getattr(el, "parent_rect_path_id", 0) or 0)
        if pid:
            kids[pid].append(el)
        else:
            roots.append(el)

    if len(roots) <= 1:
        for el in elements:
            el.locale_tag = ""
        return list(elements), {int(el.rect_path_id) for el in elements}

    cjk_re = re.compile("[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
    lat_re = re.compile(r"[A-Za-z]")

    def walk(rid, acc):
        for el in kids.get(int(rid), []):
            acc.append(el)
            walk(int(el.rect_path_id), acc)

    scored = []
    for root in roots:
        acc = [root]
        walk(int(root.rect_path_id), acc)
        blob = "\n".join(
            (el.text or "") for el in acc if getattr(el, "kind", "") == "text"
        )
        lat = len(lat_re.findall(blob))
        cjk = len(cjk_re.findall(blob))
        tag = "cjk" if cjk > lat else "en"
        if lat == 0 and cjk == 0:
            tag = "other"
        for el in acc:
            el.locale_tag = tag
        scored.append((root, acc, lat, cjk, tag))

    prefer = (prefer or "en").strip().lower()
    if prefer in ("cjk", "zh", "ja", "jp", "ko", "cn"):
        scored.sort(key=lambda t: (t[3], t[2]), reverse=True)
    else:
        scored.sort(key=lambda t: (t[2], -t[3]), reverse=True)
    preferred = {int(el.rect_path_id) for el in scored[0][1]}
    return list(elements), preferred
