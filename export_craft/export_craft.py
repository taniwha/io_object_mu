# vim:ts=4:et
# <pep8 compliant>
"""Export KSP .craft from a previously imported craft hierarchy."""
from __future__ import annotations

import bpy
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty
from mathutils import Vector

from ..cfgnode import ConfigNode, ConfigNodeError
from ..import_craft.craft_util import (
    format_quaternion,
    format_vector,
    set_tweakscale_current,
)


def _find_craft_root(context):
    obj = context.active_object
    if obj is not None and obj.get("ksp_craft_node"):
        return obj
    for o in context.selected_objects:
        if o.get("ksp_craft_node"):
            return o
    for o in bpy.data.objects:
        if o.get("ksp_craft_node"):
            return o
    return None


def _part_objects(craft_root):
    col = getattr(craft_root, "instance_collection", None)
    if col is None:
        return []
    return [o for o in col.objects if o.get("ksp_craft_part_id")]


def _parse_root_pos(craft_root) -> Vector:
    raw = craft_root.get("ksp_craft_root_pos") or "0,0,0"
    try:
        x, y, z = [float(t) for t in str(raw).replace(" ", "").split(",")]
        return Vector((x, y, z))
    except Exception:
        return Vector((0, 0, 0))


def _update_part_node_from_object(part_node: ConfigNode, obj, root_pos: Vector):
    world_pos = root_pos + obj.location
    part_node.SetValue("pos", format_vector(world_pos))
    if part_node.HasValue("attPos0"):
        part_node.SetValue("attPos0", format_vector(world_pos))
    obj.rotation_mode = 'QUATERNION'
    part_node.SetValue("rot", format_quaternion(obj.rotation_quaternion))

    sx, sy, sz = float(obj.scale.x), float(obj.scale.y), float(obj.scale.z)
    mean = (abs(sx) + abs(sy) + abs(sz)) / 3.0
    base_ts = float(obj.get("ksp_tweakscale") or 1.0)
    import_mean = float(obj.get("ksp_import_mean_scale") or 0.0)
    if import_mean > 1e-9:
        abs_ts = base_ts * (mean / import_mean)
        set_tweakscale_current(part_node, abs_ts)


def build_craft_node(craft_root) -> ConfigNode:
    raw = craft_root.get("ksp_craft_node")
    if not raw:
        raise ValueError("missing ksp_craft_node on craft root")
    try:
        craft = ConfigNode.load(str(raw))
    except ConfigNodeError as e:
        raise ValueError(e.message)

    root_pos = _parse_root_pos(craft_root)
    by_id = {}
    for obj in _part_objects(craft_root):
        pid = str(obj.get("ksp_craft_part_id") or "")
        if pid:
            by_id[pid] = obj

    for p in craft.GetNodes("PART"):
        pid = (p.GetValue("part") or "").strip()
        obj = by_id.get(pid)
        if obj is None:
            continue
        _update_part_node_from_object(p, obj, root_pos)

    # Keep ship name in sync with Blender object name when useful
    name = craft_root.get("ksp_craft_name") or craft_root.name
    if name and craft.HasValue("ship"):
        # Preserve autoLOC tokens if original was autoLOC
        orig = craft.GetValue("ship") or ""
        if not orig.startswith("#autoLOC_"):
            craft.SetValue("ship", str(name))
    return craft


def export_craft(filepath, craft_root) -> int:
    craft = build_craft_node(craft_root)
    text = craft.ToString(-1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    n = len(craft.GetNodes("PART"))
    print("INFO: KSP craft export: %d PART node(s) -> %s" % (n, filepath))
    return n


class KSPMU_OT_ExportCraft(bpy.types.Operator, ExportHelper):
    """Save a KSP .craft file from an imported craft"""
    bl_idname = "export_object.ksp_craft"
    bl_label = "Export Craft"
    bl_description = (
        "Export a previously imported KSP .craft, updating pos/rot and "
        "TweakScale from the Blender scene"
    )
    bl_options = {'REGISTER'}

    filename_ext = ".craft"
    filter_glob: StringProperty(default="*.craft", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _find_craft_root(context) is not None

    def invoke(self, context, event):
        root = _find_craft_root(context)
        if root is not None:
            path = root.get("ksp_craft_path") or ""
            if path:
                self.filepath = path
            else:
                self.filepath = (root.get("ksp_craft_name") or root.name) + ".craft"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        root = _find_craft_root(context)
        if root is None:
            self.report({'ERROR'}, "No imported craft (ksp_craft_node) found")
            return {'CANCELLED'}
        try:
            n = export_craft(self.filepath, root)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "Exported %d PART(s) to %s" % (n, self.filepath))
        return {'FINISHED'}


def export_craft_menu_func(self, context):
    self.layout.operator(
        KSPMU_OT_ExportCraft.bl_idname, text="KSP Craft (.craft)"
    )


classes_to_register = (
    KSPMU_OT_ExportCraft,
)

menus_to_register = (
    (bpy.types.TOPBAR_MT_file_export, export_craft_menu_func),
)
