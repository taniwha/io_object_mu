# vim:ts=4:et
"""Full part.cfg tree storage + coverage of parameters from the scan report.

Every key/value from PART and nested MODULEs is kept on the import root as
``mu_cfg_tree`` (JSON) so unsupported report rows become stored/round-trippable.
Viewport handlers in cfg_preview.py remain the active consumers; this module
guarantees *no* parameter is dropped on import.
"""

from __future__ import annotations

import json
import os
import re

import bpy

MU_CFG_TREE_KEY = "mu_cfg_tree"
MU_CFG_PATH_KEY = "mu_cfg_path"


def _parse_cfg_nodes(text):
    """Brace-aware parse of a KSP .cfg into a nested dict/list tree.

    Returns a list of top-level nodes: {"type": "PART", "values": {k: v or [v]},
    "children": [nodes...]}.
    """
    if not text:
        return []

    # Tokenize: NODE_NAME { ... } or key = value
    i = 0
    n = len(text)

    def skip_ws():
        nonlocal i
        while i < n:
            c = text[i]
            if c in " \t\r\n":
                i += 1
                continue
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] not in "\r\n":
                    i += 1
                continue
            break

    def read_ident():
        nonlocal i
        skip_ws()
        start = i
        while i < n and (text[i].isalnum() or text[i] in "._-"):
            i += 1
        return text[start:i]

    def read_value():
        nonlocal i
        skip_ws()
        start = i
        while i < n and text[i] not in "\r\n":
            # stop before // comment
            if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
                break
            i += 1
        return text[start:i].strip()

    def parse_block(node_type):
        nonlocal i
        skip_ws()
        if i >= n or text[i] != "{":
            return {"type": node_type, "values": {}, "children": []}
        i += 1  # {
        values = {}
        children = []
        while i < n:
            skip_ws()
            if i >= n:
                break
            if text[i] == "}":
                i += 1
                break
            # Peek: name then either = or {
            name = read_ident()
            if not name:
                i += 1
                continue
            skip_ws()
            if i < n and text[i] == "=":
                i += 1
                val = read_value()
                if name in values:
                    prev = values[name]
                    if isinstance(prev, list):
                        prev.append(val)
                    else:
                        values[name] = [prev, val]
                else:
                    values[name] = val
            elif i < n and text[i] == "{":
                children.append(parse_block(name))
            else:
                # bare token — skip line
                while i < n and text[i] not in "\r\n":
                    i += 1
        return {"type": node_type, "values": values, "children": children}

    roots = []
    while i < n:
        skip_ws()
        if i >= n:
            break
        if text[i] == "{":
            # anonymous
            roots.append(parse_block(""))
            continue
        name = read_ident()
        if not name:
            i += 1
            continue
        skip_ws()
        if i < n and text[i] == "{":
            roots.append(parse_block(name))
        elif i < n and text[i] == "=":
            i += 1
            val = read_value()
            roots.append({"type": "@root", "values": {name: val}, "children": []})
        else:
            while i < n and text[i] not in "\r\n":
                i += 1
    return roots


def flatten_cfg_parameters(nodes, path_prefix=""):
    """Yield dicts: context, module, element, value for coverage-style rows."""
    for node in nodes or []:
        ntype = node.get("type") or ""
        ctx = path_prefix + ntype if path_prefix else ntype
        mod_name = None
        vals = node.get("values") or {}
        if ntype == "MODULE" or ntype.upper() == "MODULE":
            mod_name = vals.get("name") or ""
            if isinstance(mod_name, list):
                mod_name = mod_name[0] if mod_name else ""
        for k, v in vals.items():
            if isinstance(v, list):
                for item in v:
                    yield {
                        "context": ctx,
                        "module": mod_name or "",
                        "element": k,
                        "value": item,
                    }
            else:
                yield {
                    "context": ctx,
                    "module": mod_name or "",
                    "element": k,
                    "value": v,
                }
        child_prefix = ctx + "/" if ctx else ""
        for row in flatten_cfg_parameters(node.get("children") or [], child_prefix):
            yield row


def attach_full_cfg_tree(root, cfg_path, text=None):
    """Parse part.cfg fully and store on *root* as mu_cfg_tree."""
    if root is None:
        return None
    if text is None:
        if not cfg_path or not os.path.isfile(cfg_path):
            return None
        try:
            text = open(cfg_path, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            return None
    try:
        nodes = _parse_cfg_nodes(text)
    except Exception as e:
        print(f"WARNING: cfg tree parse: {e}")
        return None
    flat = list(flatten_cfg_parameters(nodes))
    payload = {
        "path": cfg_path or "",
        "nodes": nodes,
        "flat": flat,
        "count": len(flat),
    }
    try:
        root[MU_CFG_TREE_KEY] = json.dumps(payload, ensure_ascii=False)
        if cfg_path:
            root[MU_CFG_PATH_KEY] = cfg_path
    except Exception as e:
        print(f"WARNING: store cfg tree: {e}")
        return None
    return payload


def get_cfg_tree(root):
    if root is None or MU_CFG_TREE_KEY not in root:
        return None
    try:
        return json.loads(root[MU_CFG_TREE_KEY])
    except Exception:
        return None


def coverage_status_for(module, element):
    """Return HANDLED / STORED / UNKNOWN relative to the coverage registry."""
    try:
        from .cfg_param_registry import MODULE_PARAMETERS, PART_PARAMETERS
    except Exception:
        return "UNKNOWN"
    el = (element or "").strip()
    mod = (module or "").strip()
    if not el:
        return "UNKNOWN"
    # Viewport-active set (kept in sync with cfg_preview consumers)
    VIEWPORT = {
        ("ModuleB9PartSwitch", "transform"),
        ("ModuleB9PartSwitch", "name"),
        ("ModuleB9PartSwitch", "title"),
        ("ModuleB9PartSwitch", "texture"),
        ("ModuleB9PartSwitch", "shaderProperty"),
        ("ModuleB9PartSwitch", "isNormalMap"),
        ("ModuleB9PartSwitch", "node"),
        ("ModulePartVariants", "baseVariant"),
        ("ModulePartVariants", "name"),
        ("ModuleColorChanger", "shaderProperty"),
        ("ModuleWheelSuspension", "suspensionTransformName"),
        ("ModuleWheelSuspension", "suspensionDistance"),
        ("FXModuleLookAtConstraint", "targetName"),
        ("FXModuleLookAtConstraint", "rotatorsName"),
        ("FXModuleConstrainPosition", "targetName"),
        ("FXModuleConstrainPosition", "moversName"),
        ("FXModuleConstrainPosition", "matchRotation"),
        ("FXModuleConstrainPosition", "matchPosition"),
        ("ModuleAeroSurface", "transformName"),
        ("ModuleAeroSurface", "ctrlSurfaceRange"),
    }
    if (mod, el) in VIEWPORT:
        return "VIEWPORT"
    if mod and mod in MODULE_PARAMETERS and el in MODULE_PARAMETERS[mod]:
        return "STORED"
    if el in PART_PARAMETERS:
        return "STORED"
    return "STORED"  # generic tree stores everything


# --- UI helpers -------------------------------------------------------------

def _cfg_enum_items(self, context):
    items = [("NONE", "(no cfg data)", "")]
    root = None
    try:
        from .cfg_preview import find_variant_root
        root = find_variant_root(
            getattr(context, "active_object", None), context=context
        )
    except Exception:
        root = getattr(context, "active_object", None)
        while root is not None and root.parent is not None:
            root = root.parent
    data = get_cfg_tree(root) if root else None
    if not data:
        return items
    flat = data.get("flat") or []
    filt = ""
    try:
        filt = (getattr(context.scene, "mu_cfg_filter", "") or "").lower()
    except Exception:
        pass
    out = []
    seen = set()
    for i, row in enumerate(flat):
        el = row.get("element") or ""
        mod = row.get("module") or ""
        val = str(row.get("value") or "")
        label = f"{mod}.{el}" if mod else el
        if filt and filt not in label.lower() and filt not in val.lower():
            continue
        key = f"{i}:{label}"
        if key in seen:
            continue
        seen.add(key)
        status = coverage_status_for(mod, el)
        out.append((key, f"[{status}] {label} = {val[:40]}", val[:200]))
        if len(out) >= 200:
            break
    return out or items


def register_cfg_ui():
    if not hasattr(bpy.types.Scene, "mu_cfg_filter"):
        bpy.types.Scene.mu_cfg_filter = bpy.props.StringProperty(
            name="CFG Filter",
            description="Filter CFG parameter list",
            default="",
        )
    if not hasattr(bpy.types.Scene, "mu_cfg_param"):
        bpy.types.Scene.mu_cfg_param = bpy.props.EnumProperty(
            name="CFG Parameter",
            description="Parameters from the selected part.cfg (full tree)",
            items=_cfg_enum_items,
        )


def unregister_cfg_ui():
    if hasattr(bpy.types.Scene, "mu_cfg_param"):
        del bpy.types.Scene.mu_cfg_param
    if hasattr(bpy.types.Scene, "mu_cfg_filter"):
        del bpy.types.Scene.mu_cfg_filter
