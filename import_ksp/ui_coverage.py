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
"""MonoScript + field-level UI coverage for KSP .ksp AssetBundles.

Classifies MonoBehaviours (TMP / UI.Text / Image / layout meta) and scans
RectTransform + text/image serialized keys so gaps like skipped
``m_LocalRotation`` (Craft Pitches ±90°) surface at import time — even when
the value is rare across the corpus.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# class name (no namespace) → role
SCRIPT_KIND = {
    # Text
    "TextMeshProUGUI": "text",
    "TextMeshPro": "text",
    "TMP_Text": "text",
    "Text": "text",  # UnityEngine.UI.Text
    # Images
    "Image": "image",
    "RawImage": "image",
    # Known non-visual / child — keep as empty, do not warn as unknown
    "TMP_SubMeshUI": "meta",
    "TMP_SubMesh": "meta",
    "DatabaseScreen": "meta",  # page marker; no visual fields
    "Button": "meta",
    "Toggle": "meta",
    "Slider": "meta",
    "Scrollbar": "meta",
    "ScrollRect": "meta",
    "Mask": "meta",
    "RectMask2D": "meta",
    "LayoutElement": "meta",
    "ContentSizeFitter": "meta",
    "HorizontalLayoutGroup": "meta",
    "VerticalLayoutGroup": "meta",
    "GridLayoutGroup": "meta",
    "Outline": "meta",
    "Shadow": "meta",
    "CanvasScaler": "meta",
    "GraphicRaycaster": "meta",
    "Canvas": "meta",
    "CanvasGroup": "meta",
    # Extra UGUI / TMP (meta / passthrough unless listed text/image)
    "InputField": "meta",
    "TMP_InputField": "meta",
    "Dropdown": "meta",
    "TMP_Dropdown": "meta",
    "Selectable": "meta",
    "ToggleGroup": "meta",
    "AspectRatioFitter": "meta",
    "LayoutGroup": "meta",
    "TextMeshProEffect": "meta",
    "TMP_SpriteAnimator": "meta",
}

# --- Field support registries (Unity serialized names) ---
RT_KEYS_KNOWN = frozenset({
    "m_GameObject",
    "m_Father",
    "m_Children",
    "m_LocalRotation",
    "m_LocalPosition",
    "m_LocalScale",
    "m_AnchorMin",
    "m_AnchorMax",
    "m_AnchoredPosition",
    "m_SizeDelta",
    "m_Pivot",
    "m_OffsetMin",
    "m_OffsetMax",
})

RT_VIEWPORT = frozenset({
    "m_LocalRotation",
    "m_LocalPosition",
    "m_LocalScale",
    "m_AnchorMin",
    "m_AnchorMax",
    "m_AnchoredPosition",
    "m_SizeDelta",
    "m_Pivot",
    "m_OffsetMin",
    "m_OffsetMax",
    "m_Father",
    "m_Children",
})

RT_ROUNDTRIP = RT_VIEWPORT | frozenset({"m_GameObject"})

RT_CRITICAL_NONDEFAULT = frozenset({
    "m_LocalRotation",
    "m_LocalScale",
})

TMP_VIEWPORT = frozenset({
    "m_text",
    "m_Text",
    "m_fontSize",
    "m_fontColor",
    "m_Color",
    "m_fontStyle",
    "m_textAlignment",
    "m_horizontalAlignment",
    "m_verticalAlignment",
    "m_enableWordWrapping",
    "m_lineSpacing",
    "m_characterSpacing",
    "m_wordSpacing",
    "m_paragraphSpacing",
    "m_margin",
    "m_fontAsset",
    "m_enableAutoSizing",
    "m_fontSizeMin",
    "m_fontSizeMax",
    "m_overflowMode",
    "m_enableKerning",
    "m_isRichText",
    "m_outlineColor",
    "m_outlineWidth",
    "m_faceColor",
    "m_enableVertexGradient",
    "m_fontColorGradient",
    "m_tintAllSprites",
    "m_horizontalMapping",
    "m_verticalMapping",
    "m_isVolumetricText",
    "m_pageToDisplay",
    "m_linkedTextComponent",
    "m_spriteAnimator",
    "m_FontData",
})

TMP_ROUNDTRIP = TMP_VIEWPORT | frozenset({
    "m_fontColor32",
    "m_fontSizeBase",
    "m_sharedMaterial",
    "m_fontSharedMaterials",
    "m_fontMaterial",
    "m_fontMaterials",
    "m_spriteAsset",
})

TMP_PRESERVE_WARN_IF_SET = frozenset({
    "m_fontColorGradientPreset",
    "m_overrideHtmlColors",
    "m_lineSpacingMax",
    "m_charWidthMaxAdj",
    "m_wordWrappingRatios",
    "m_isLinkedTextComponent",
    "m_enableExtraPadding",
    "m_parseCtrlCharacters",
    "m_isCullingEnabled",
    "m_ignoreRectMaskCulling",
    "m_ignoreCulling",
    "m_uvLineOffset",
    "m_geometrySortingOrder",
    "m_firstVisibleCharacter",
    "m_useMaxVisibleDescender",
})

IMAGE_VIEWPORT = frozenset({
    "m_Sprite",
    "m_Texture",
    "m_Color",
    "m_Type",
    "m_PreserveAspect",
    "m_FillCenter",
    "m_FillMethod",
    "m_FillAmount",
    "m_FillClockwise",
    "m_FillOrigin",
})

IMAGE_ROUNDTRIP = IMAGE_VIEWPORT | frozenset({
    "m_Material",
    "m_RaycastTarget",
    "m_UseSpriteMesh",
    "m_Maskable",
})


@dataclass
class UiCoverageReport:
    by_script: Dict[str, int] = field(default_factory=dict)
    by_kind: Dict[str, int] = field(default_factory=dict)
    unknown_scripts: Dict[str, int] = field(default_factory=dict)
    skipped_scripts: Dict[str, int] = field(default_factory=dict)
    field_fallback: int = 0
    rt_keys_seen: Dict[str, int] = field(default_factory=dict)
    rt_unknown_keys: Dict[str, int] = field(default_factory=dict)
    rt_critical_hits: List[str] = field(default_factory=list)
    tmp_keys_seen: Dict[str, int] = field(default_factory=dict)
    tmp_unhandled_nonzero: Dict[str, int] = field(default_factory=dict)
    image_keys_seen: Dict[str, int] = field(default_factory=dict)
    image_unhandled_nonzero: Dict[str, int] = field(default_factory=dict)
    support_notes: List[str] = field(default_factory=list)
    # Unique Font / TMP families in the .ksp (assets + unused), not usage×counts.
    font_count: int = 0

    def summary_line(self) -> str:
        kinds = self.by_kind or {}
        unk = sum(self.unknown_scripts.values())
        crit = len(self.rt_critical_hits)
        gap = sum(self.tmp_unhandled_nonzero.values()) + sum(
            self.image_unhandled_nonzero.values()
        )
        return (
            "text=%d fonts=%d image=%d meta=%d empty=%d skip=%d unknown=%d "
            "fallback=%d rt_critical=%d field_gaps=%d"
            % (
                int(kinds.get("text", 0)),
                int(self.font_count or 0),
                int(kinds.get("image", 0)),
                int(kinds.get("meta", 0)),
                int(kinds.get("empty", 0)),
                int(kinds.get("skip", 0)),
                unk,
                int(self.field_fallback),
                crit,
                gap,
            )
        )

    def format_report(self, max_unknown: int = 12) -> str:
        lines = ["KSP UI coverage: " + self.summary_line()]
        if self.by_script:
            top = sorted(self.by_script.items(), key=lambda kv: -kv[1])[:10]
            lines.append(
                "  scripts: "
                + ", ".join("%s×%d" % (n, c) for n, c in top)
            )
        if self.rt_critical_hits:
            lines.append(
                "  CRITICAL RectTransform non-defaults (must be applied):"
            )
            for s in self.rt_critical_hits[:max_unknown]:
                lines.append("    - %s" % s)
            extra = len(self.rt_critical_hits) - max_unknown
            if extra > 0:
                lines.append("    … +%d more" % extra)
        if self.rt_unknown_keys:
            lines.append("  UNKNOWN RectTransform keys (new Unity schema?):")
            for name, c in sorted(
                self.rt_unknown_keys.items(), key=lambda kv: -kv[1]
            )[:max_unknown]:
                lines.append("    - %s ×%d" % (name, c))
        if self.tmp_unhandled_nonzero:
            lines.append(
                "  TMP fields with non-default values (viewport partial):"
            )
            for name, c in sorted(
                self.tmp_unhandled_nonzero.items(), key=lambda kv: -kv[1]
            )[:max_unknown]:
                lines.append("    - %s ×%d" % (name, c))
        if self.image_unhandled_nonzero:
            lines.append(
                "  Image fields with non-default values (viewport partial):"
            )
            for name, c in sorted(
                self.image_unhandled_nonzero.items(), key=lambda kv: -kv[1]
            )[:8]:
                lines.append("    - %s ×%d" % (name, c))
        if self.unknown_scripts:
            lines.append("  UNKNOWN MonoScripts (need support?):")
            for name, c in sorted(
                self.unknown_scripts.items(), key=lambda kv: -kv[1]
            )[:max_unknown]:
                lines.append("    - %s ×%d" % (name, c))
        if self.skipped_scripts:
            top = sorted(self.skipped_scripts.items(), key=lambda kv: -kv[1])[:6]
            lines.append(
                "  skipped: "
                + ", ".join("%s×%d" % (n, c) for n, c in top)
            )
        for note in self.support_notes[:6]:
            lines.append("  note: %s" % note)
        return "\n".join(lines)


def build_monoscript_map(env) -> Dict[int, str]:
    """Map MonoScript path_id → 'Namespace.Class' or 'Class'."""
    out: Dict[int, str] = {}
    for obj in getattr(env, "objects", []) or []:
        try:
            if obj.type.name != "MonoScript":
                continue
            data = obj.read()
            cn = getattr(data, "m_ClassName", "") or ""
            ns = getattr(data, "m_Namespace", "") or ""
            if not cn:
                tree = obj.read_typetree()
                if isinstance(tree, dict):
                    cn = tree.get("m_ClassName") or ""
                    ns = tree.get("m_Namespace") or ""
            label = (
                ("%s.%s" % (ns, cn))
                if ns
                else (cn or ("Script_%s" % obj.path_id))
            )
            out[int(obj.path_id)] = label
        except Exception:
            continue
    return out


def script_label_from_tree(tree: dict, script_map: Dict[int, str]) -> str:
    if not isinstance(tree, dict):
        return ""
    ref = tree.get("m_Script")
    pid = 0
    if isinstance(ref, dict):
        try:
            pid = int(ref.get("m_PathID") or ref.get("path_id") or 0)
        except Exception:
            pid = 0
    elif ref is not None:
        try:
            pid = int(ref)
        except Exception:
            pid = 0
    if not pid:
        return ""
    return script_map.get(int(pid), "")


def class_name_only(label: str) -> str:
    if not label:
        return ""
    if "." in label:
        return label.rsplit(".", 1)[-1]
    return label


def classify_mb_role(
    tree: dict, script_map: Dict[int, str]
) -> Tuple[str, str, bool]:
    """Return (role, script_label, used_field_fallback)."""
    label = script_label_from_tree(tree, script_map)
    cn = class_name_only(label)
    role = SCRIPT_KIND.get(cn)
    if role:
        return role, label or cn, False

    if isinstance(tree, dict):
        if "m_text" in tree or "m_Text" in tree:
            return "text", label or "(fields:m_text)", True
        if "m_Sprite" in tree:
            return "image", label or "(fields:m_Sprite)", True
        if "m_Texture" in tree and "m_FontData" not in tree:
            return "image", label or "(fields:m_Texture)", True

    if label:
        return "unknown", label, False
    return "empty", "", False


def accumulate_coverage(
    report: UiCoverageReport,
    role: str,
    script_label: str,
    field_fallback: bool,
) -> None:
    if script_label:
        report.by_script[script_label] = report.by_script.get(script_label, 0) + 1
    kind_key = role if role != "unknown" else "empty"
    if role == "meta":
        kind_key = "empty"
    elif role == "skip":
        kind_key = "skip"
        if script_label:
            report.skipped_scripts[script_label] = (
                report.skipped_scripts.get(script_label, 0) + 1
            )
    elif role == "unknown":
        kind_key = "empty"
        if script_label:
            report.unknown_scripts[script_label] = (
                report.unknown_scripts.get(script_label, 0) + 1
            )
    report.by_kind[kind_key] = report.by_kind.get(kind_key, 0) + 1
    if field_fallback:
        report.field_fallback += 1


def merge_element_kinds(report: UiCoverageReport, elements) -> None:
    """Overwrite by_kind with final KspUiElement.kind histogram."""
    c = Counter(getattr(el, "kind", "empty") for el in elements or [])
    report.by_kind = {
        "text": int(c.get("text", 0)),
        "image": int(c.get("image", 0)),
        "empty": int(c.get("empty", 0)),
        "meta": int(c.get("meta", 0)),
        "skip": int(
            report.skipped_scripts
            and sum(report.skipped_scripts.values())
            or 0
        ),
    }


def _quat_xyzw(v):
    if v is None:
        return (0.0, 0.0, 0.0, 1.0)
    if isinstance(v, dict):
        return (
            float(v.get("x", 0.0)),
            float(v.get("y", 0.0)),
            float(v.get("z", 0.0)),
            float(v.get("w", 1.0)),
        )
    try:
        return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    except Exception:
        return (0.0, 0.0, 0.0, 1.0)


def _vec3(v):
    if v is None:
        return (0.0, 0.0, 0.0)
    if isinstance(v, dict):
        return (
            float(v.get("x", 0.0)),
            float(v.get("y", 0.0)),
            float(v.get("z", 0.0)),
        )
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _is_identity_quat(q, eps=1e-5):
    x, y, z, w = _quat_xyzw(q)
    return (
        abs(x) <= eps
        and abs(y) <= eps
        and abs(z) <= eps
        and abs(abs(w) - 1.0) <= eps
    )


def _is_identity_scale(s, eps=1e-5):
    x, y, z = _vec3(s)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return True
    return abs(x - 1.0) <= eps and abs(y - 1.0) <= eps and abs(z - 1.0) <= eps


def _is_defaultish(key: str, value) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Unity sometimes serializes bools as 0/1
        if key in (
            "m_enableKerning",
            "m_isRichText",
            "m_enableWordWrapping",
            "m_parseCtrlCharacters",
            "m_useMaxVisibleDescender",
            "m_isOrthographic",
            "m_FillCenter",
            "m_FillClockwise",
            "m_RaycastTarget",
            "m_Maskable",
            "m_Enabled",
            "m_ignoreCulling",
            "m_ignoreRectMaskCulling",
        ) and float(value) in (0.0, 1.0):
            value = bool(int(value))
    if isinstance(value, bool):
        if key in (
            "m_enableKerning",
            "m_isRichText",
            "m_enableWordWrapping",
            "m_parseCtrlCharacters",
            "m_useMaxVisibleDescender",
            "m_isOrthographic",
            "m_FillCenter",
            "m_FillClockwise",
            "m_RaycastTarget",
            "m_Maskable",
            "m_Enabled",
        ):
            return bool(value) is True
        if key in ("m_ignoreCulling", "m_ignoreRectMaskCulling"):
            return True
        return bool(value) is False
    if isinstance(value, (int, float)):
        fv = float(value)
        if abs(fv) < 1e-9:
            return True
        if key == "m_pageToDisplay" and abs(fv - 1.0) < 1e-6:
            return True
        if key == "m_wordWrappingRatios" and abs(fv - 0.4) < 1e-4:
            return True
        if key == "m_PixelsPerUnitMultiplier" and abs(fv - 1.0) < 1e-4:
            return True
        return False
    if isinstance(value, str):
        return not value
    if isinstance(value, dict):
        if "m_PathID" in value:
            try:
                return int(value.get("m_PathID") or 0) == 0
            except Exception:
                return True
        nums = []
        for k in ("x", "y", "z", "w", "r", "g", "b", "a"):
            if k in value:
                try:
                    nums.append(float(value[k]))
                except Exception:
                    pass
        if not nums:
            return True
        if "Color" in key:
            if len(nums) >= 3 and all(abs(n - 1.0) < 1e-4 for n in nums[:3]):
                return True
            if all(abs(n) < 1e-4 for n in nums[:3]):
                return True
        return all(abs(n) < 1e-6 for n in nums)
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def _go_name_map(env) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for obj in getattr(env, "objects", []) or []:
        try:
            if obj.type.name != "GameObject":
                continue
            tree = obj.read_typetree()
            out[int(obj.path_id)] = str(tree.get("m_Name") or "")
        except Exception:
            continue
    return out


def analyze_field_coverage(env, elements, report: UiCoverageReport) -> None:
    """Scan RectTransform / TMP / Image keys; flag critical gaps."""
    go_names = _go_name_map(env)
    el_by_rect: Dict[int, object] = {}
    for el in elements or []:
        try:
            el_by_rect[int(getattr(el, "rect_path_id", 0) or 0)] = el
        except Exception:
            pass

    rt_count = 0
    rot_loaded = 0
    scale_loaded = 0

    for obj in getattr(env, "objects", []) or []:
        try:
            tname = obj.type.name
        except Exception:
            continue
        if tname == "RectTransform":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if not isinstance(tree, dict):
                continue
            rt_count += 1
            for k in tree.keys():
                report.rt_keys_seen[k] = report.rt_keys_seen.get(k, 0) + 1
                if k not in RT_KEYS_KNOWN:
                    report.rt_unknown_keys[k] = (
                        report.rt_unknown_keys.get(k, 0) + 1
                    )

            rid = int(obj.path_id)
            el = el_by_rect.get(rid)
            go_ref = tree.get("m_GameObject")
            go_id = 0
            if isinstance(go_ref, dict):
                try:
                    go_id = int(go_ref.get("m_PathID") or 0)
                except Exception:
                    go_id = 0
            name = (
                go_names.get(go_id)
                or getattr(el, "name", "")
                or ("RT_%s" % rid)
            )

            q = tree.get("m_LocalRotation")
            if not _is_identity_quat(q):
                qx, qy, qz, qw = _quat_xyzw(q)
                loaded_ok = False
                if el is not None:
                    lq = getattr(el, "local_rotation", None)
                    if lq is not None and not _is_identity_quat(lq):
                        loaded_ok = True
                        rot_loaded += 1
                status = "loaded" if loaded_ok else "MISSING_ON_ELEMENT"
                report.rt_critical_hits.append(
                    "m_LocalRotation on %r quat=(%.4f,%.4f,%.4f,%.4f) [%s]"
                    % (name, qx, qy, qz, qw, status)
                )
                if not loaded_ok:
                    report.support_notes.append(
                        "RectTransform rotation present but not on element: %s"
                        % name
                    )

            sc = tree.get("m_LocalScale")
            if not _is_identity_scale(sc):
                sx, sy, sz = _vec3(sc)
                loaded_ok = False
                if el is not None:
                    ls = getattr(el, "local_scale", None)
                    if ls is not None and not _is_identity_scale(ls):
                        loaded_ok = True
                        scale_loaded += 1
                status = "loaded" if loaded_ok else "MISSING_ON_ELEMENT"
                report.rt_critical_hits.append(
                    "m_LocalScale on %r scale=(%.4f,%.4f,%.4f) [%s]"
                    % (name, sx, sy, sz, status)
                )

        elif tname == "MonoBehaviour":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if not isinstance(tree, dict):
                continue
            is_tmp = "m_text" in tree or "m_fontAsset" in tree
            is_uitext = "m_FontData" in tree or (
                "m_Text" in tree and "m_text" not in tree
            )
            is_image = ("m_Sprite" in tree or "m_Type" in tree) and not is_tmp
            if is_tmp or is_uitext:
                for k, v in tree.items():
                    if not str(k).startswith("m_"):
                        continue
                    report.tmp_keys_seen[k] = report.tmp_keys_seen.get(k, 0) + 1
                    if k in TMP_VIEWPORT or k in TMP_ROUNDTRIP:
                        continue
                    if k in TMP_PRESERVE_WARN_IF_SET and not _is_defaultish(k, v):
                        report.tmp_unhandled_nonzero[k] = (
                            report.tmp_unhandled_nonzero.get(k, 0) + 1
                        )
                    elif (
                        k
                        not in (
                            "m_GameObject",
                            "m_Script",
                            "m_Name",
                            "m_Enabled",
                            "m_Material",
                            "m_RaycastTarget",
                            "m_OnCullStateChanged",
                            "m_Maskable",
                            "m_textInfo",
                            "m_subTextObjects",
                            "m_baseMaterial",
                            "m_hasFontAssetChanged",
                            "m_isAlignmentEnumConverted",
                            "m_firstOverflowCharacterIndex",
                            "m_isTextTruncated",
                            "m_spriteAnimator",
                            "m_fontWeight",
                            "m_fontColor32",
                        )
                        and not _is_defaultish(k, v)
                    ):
                        report.tmp_unhandled_nonzero[k] = (
                            report.tmp_unhandled_nonzero.get(k, 0) + 1
                        )
            elif is_image:
                for k, v in tree.items():
                    if not str(k).startswith("m_"):
                        continue
                    report.image_keys_seen[k] = (
                        report.image_keys_seen.get(k, 0) + 1
                    )
                    if k in IMAGE_VIEWPORT or k in IMAGE_ROUNDTRIP:
                        continue
                    if k in (
                        "m_GameObject",
                        "m_Script",
                        "m_Name",
                        "m_Enabled",
                        "m_OnCullStateChanged",
                    ):
                        continue
                    if not _is_defaultish(k, v):
                        report.image_unhandled_nonzero[k] = (
                            report.image_unhandled_nonzero.get(k, 0) + 1
                        )

    report.support_notes.insert(
        0,
        "RectTransform×%d; non-id rot loaded=%d scale loaded=%d"
        % (rt_count, rot_loaded, scale_loaded),
    )


def support_matrix_text() -> str:
    """Human-readable possible-vs-plugin matrix."""
    lines = [
        "=== KSP UI support matrix (plugin) ===",
        "",
        "[RectTransform]",
        "  viewport+roundtrip: " + ", ".join(sorted(RT_VIEWPORT)),
        "  critical non-default: "
        + ", ".join(sorted(RT_CRITICAL_NONDEFAULT)),
        "",
        "[TMP / UI.Text — viewport]",
        "  " + ", ".join(sorted(TMP_VIEWPORT)),
        "",
        "[TMP — roundtrip extras]",
        "  "
        + ", ".join(sorted(TMP_ROUNDTRIP - TMP_VIEWPORT) or ["(none)"]),
        "",
        "[TMP — preserve / warn if set (no full viewport yet)]",
        "  " + ", ".join(sorted(TMP_PRESERVE_WARN_IF_SET)),
        "",
        "[UI.Image / RawImage — viewport]",
        "  " + ", ".join(sorted(IMAGE_VIEWPORT)),
        "",
        "[MonoBehaviour roles]",
    ]
    by_role: Dict[str, List[str]] = {}
    for cn, role in SCRIPT_KIND.items():
        by_role.setdefault(role, []).append(cn)
    for role in sorted(by_role):
        lines.append("  %s: %s" % (role, ", ".join(sorted(by_role[role]))))
    return "\n".join(lines)
