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
import bpy
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
from mathutils import Vector

from ..import_mu import MuImportError
from ..cfgnode import ConfigNode, ConfigNodeError
from ..cfgnode import parse_vector, parse_quaternion
from ..preferences import Preferences
from ..utils import util_collection

from .gamedata import GameData, gamedata
from .craft_util import split_part_id, tweakscale_factor


def craft_collection():
    return util_collection("craft_collection")


def select_objects(obj):
    obj.select_set(True)
    for o in obj.children:
        select_objects(o)


def _stamp_part_props(obj, part_node, part_id, pname, root_pos):
    try:
        obj["ksp_craft_part_id"] = part_id
        obj["ksp_craft_part_name"] = pname
        obj["ksp_craft_part_node"] = "PART " + part_node.ToString(0)
        if root_pos is not None:
            obj["ksp_craft_root_pos"] = "%g,%g,%g" % (
                float(root_pos.x), float(root_pos.y), float(root_pos.z)
            )
        ts = tweakscale_factor(part_node)
        if ts is not None:
            obj["ksp_tweakscale"] = float(ts)
    except Exception:
        pass


def import_craft(filepath):
    global gamedata
    if not gamedata:
        gd_path = (Preferences().GameData or "").strip()
        if not gd_path:
            raise MuImportError(
                "Craft",
                "Set Preferences > GameData before importing .craft",
            )
        gamedata = GameData(gd_path)
    try:
        craft = ConfigNode.loadfile(filepath)
    except ConfigNodeError as e:
        raise MuImportError("Craft", e.message)

    craft_name = craft.GetValue("ship") or "craft"
    if craft_name[:9] == "#autoLOC_" and craft_name in gamedata.localizations:
        craft_name = gamedata.localizations[craft_name].strip()

    vessel = bpy.data.collections.new(craft_name)
    craft_collection().children.link(vessel)

    root_pos = None
    n_ok = 0
    n_miss = 0
    n_ts = 0
    for p in craft.GetNodes("PART"):
        part_id = (p.GetValue("part") or "").strip()
        pname, _uid = split_part_id(part_id)
        if not pname:
            n_miss += 1
            continue
        if pname not in gamedata.parts:
            print("WARNING: craft part not in GameData: %s" % pname)
            n_miss += 1
            continue
        try:
            pos = parse_vector(p.GetValue("pos") or "0,0,0")
        except Exception:
            pos = Vector((0, 0, 0))
        try:
            rot = parse_quaternion(p.GetValue("rot") or "0,0,0,1")
        except Exception:
            from mathutils import Quaternion
            rot = Quaternion((1, 0, 0, 0))

        try:
            part = gamedata.parts[pname].get_model()
        except Exception as e:
            print("WARNING: craft part model failed (%s): %s" % (pname, e))
            part = bpy.data.objects.new(pname, None)
            n_miss += 1

        if root_pos is None:
            root_pos = pos
        part.location = pos - root_pos
        part.rotation_mode = 'QUATERNION'
        part.rotation_quaternion = rot

        ts = tweakscale_factor(p)
        if ts is not None and abs(ts - 1.0) > 1e-6:
            try:
                part.scale = part.scale * float(ts)
            except Exception:
                pass
            n_ts += 1
        else:
            ts = 1.0 if ts is None else float(ts)

        _stamp_part_props(part, p, part_id, pname, root_pos)
        try:
            part["ksp_tweakscale"] = float(ts)
            sx = float(getattr(part.scale, "x", 1.0))
            sy = float(getattr(part.scale, "y", 1.0))
            sz = float(getattr(part.scale, "z", 1.0))
            part["ksp_import_mean_scale"] = (abs(sx) + abs(sy) + abs(sz)) / 3.0
        except Exception:
            pass
        vessel.objects.link(part)
        n_ok += 1

    obj = bpy.data.objects.new(craft_name, None)
    obj.instance_type = 'COLLECTION'
    obj.instance_collection = vessel
    obj.location = bpy.context.scene.cursor.location
    bpy.context.layer_collection.collection.objects.link(obj)
    try:
        obj["ksp_craft_path"] = filepath
        obj["ksp_craft_name"] = craft_name
        obj["ksp_craft_node"] = craft.ToString(-1)
        if root_pos is not None:
            obj["ksp_craft_root_pos"] = "%g,%g,%g" % (
                float(root_pos.x), float(root_pos.y), float(root_pos.z)
            )
    except Exception:
        pass

    print(
        "INFO: KSP craft import: %d part(s), %d missing, %d TweakScale"
        % (n_ok, n_miss, n_ts)
    )
    return obj


def import_craft_op(self, context, filepath):
    operator = self
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False

    try:
        obj = import_craft(filepath)
    except MuImportError as e:
        operator.report({'ERROR'}, e.message)
        return {'CANCELLED'}
    else:
        for o in bpy.context.scene.objects:
            o.select_set(False)
        select_objects(obj)
        bpy.context.view_layer.objects.active = obj
        return {'FINISHED'}
    finally:
        bpy.context.preferences.edit.use_global_undo = undo


class KSPMU_OT_ImportCraft(bpy.types.Operator, ImportHelper):
    '''Load a KSP craft file'''
    bl_idname = "import_object.ksp_craft"
    bl_label = "Import Craft"
    bl_description = (
        "Import a KSP .craft (ship) file. Stores PART/MODULE data "
        "(incl. TweakScale) for round-trip export."
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".craft"
    filter_glob: StringProperty(default="*.craft", options={'HIDDEN'})

    def execute(self, context):
        keywords = self.as_keywords(ignore=("filter_glob",
                                            "axis_forward", "axis_up"))
        return import_craft_op(self, context, **keywords)


def import_craft_menu_func(self, context):
    self.layout.operator(
        KSPMU_OT_ImportCraft.bl_idname, text="KSP Craft (.craft)"
    )


classes_to_register = (
    KSPMU_OT_ImportCraft,
)

menus_to_register = (
    (bpy.types.TOPBAR_MT_file_import, import_craft_menu_func),
)
