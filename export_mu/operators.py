# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

import bpy
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, EnumProperty
from mathutils import Vector
from math import pi

from ..utils import strip_nnn, collect_hierarchy_objects, swapyz, vector_str, swizzleq

#gotta mess with the heads of 6.28 fans :)
tau = 180 / pi

from . import export
from . import volume

def export_root_object(obj):
    """Pick the hierarchy root to export.

    Walk to the topmost parent, but if that root is a tiny bone fragment
    (e.g. joint35) while a much richer scene-root exists, prefer the
    richest root so TriBitDrill/Serenity parts export completely.
    """
    if obj is None:
        return None

    def score(o):
        n = 0
        stack = [o]
        while stack:
            cur = stack.pop()
            n += 1
            stack.extend(cur.children)
        return n

    root = obj
    while root.parent:
        root = root.parent
    scene_roots = [o for o in bpy.context.scene.objects if o.parent is None]
    if not scene_roots:
        return root
    best = max(scene_roots, key=score)
    # Prefer richer root when walked root looks like an orphan bone chain
    name = strip_nnn(root.name).lower()
    looks_like_bone = name.startswith("joint") or name.startswith("bone")
    if best is not root and (looks_like_bone or score(best) >= score(root) * 3):
        return best
    return root

def _alive_object(obj):
    """Return obj if it is a live Blender Object, else None (stale RNA)."""
    if obj is None:
        return None
    try:
        _ = obj.name
        return obj
    except ReferenceError:
        return None

def export_mu(operator, context, filepath, bake_active_variant=False):
    collections = export.enable_collections()
    prev_variant = None
    flag_restore = None
    root = None
    mu = None
    try:
        active = _alive_object(context.active_object)
        # If nothing sensible is active, pick richest scene root
        if active is None:
            roots = [o for o in context.scene.objects if o.parent is None]
            active = max(roots, key=lambda o: len(o.children_recursive)) if roots else None
        obj = export_root_object(active)
        root = obj
        active_name = None
        alive_active = _alive_object(context.active_object)
        if alive_active is not None:
            active_name = strip_nnn(alive_active.name)
        if obj is not None and obj is not alive_active:
            operator.report(
                {'INFO'},
                f"Exporting hierarchy root '{strip_nnn(obj.name)}' "
                f"(active was '{active_name}')")
        # Normal export: always write stock .mu materials / GAMEOBJECTS, even
        # when Options preview shows a paint or model variant.
        if not bake_active_variant and obj is not None:
            try:
                from ..import_mu.cfg_preview import (
                    prepare_stock_for_export,
                    find_variant_root,
                )
                vroot = find_variant_root(obj, context=context) or obj
                prev_variant = prepare_stock_for_export(vroot)
                root = vroot
            except Exception as e:
                operator.report({'WARNING'}, f"variant stock restore: {e}")
            # Robotics preview may have rotated Bar mesh data / hardMin pose;
            # restore authored bind (incl. mu_robotic_mesh_backup) before write.
            try:
                from ..import_mu.robotics_preview import restore_robotics_bind_pose
                restore_robotics_bind_pose(context.scene)
            except Exception as e:
                operator.report({'WARNING'}, f"robotics bind restore: {e}")
        # No Flag hides FlagDecal in viewport; unhide so .mu keeps the mesh.
        if obj is not None:
            try:
                from ..import_mu.flag_preview import (
                    find_flag_root,
                    prepare_flag_for_export,
                )
                froot = find_flag_root(obj, context=context) or root or obj
                flag_restore = prepare_flag_for_export(froot)
            except Exception as e:
                operator.report({'WARNING'}, f"flag export unhide: {e}")
        mu = export.export_object(
            obj, filepath, bake_active_variant=bake_active_variant
        )
    finally:
        if not bake_active_variant and prev_variant and root is not None:
            try:
                from ..import_mu.cfg_preview import finish_stock_export
                finish_stock_export(root, prev_variant)
            except Exception:
                pass
        try:
            from ..import_mu.flag_preview import finish_flag_export
            finish_flag_export(flag_restore)
        except Exception:
            pass
        export.restore_collections(collections)
    if mu is not None:
        for m in mu.messages:
            operator.report(m[0], m[1])
        # When exporting .mu to a different folder than the stock cfg,
        # also write a patched part.cfg beside the new .mu (no overwrite prompt).
        try:
            _maybe_write_cfg_beside_mu(root, filepath, operator)
        except Exception as e:
            operator.report({'WARNING'}, f"part cfg beside mu: {e}")
    return {'FINISHED'}


def _maybe_write_cfg_beside_mu(root, filepath, operator):
    if root is None or not filepath:
        return
    try:
        from ..preferences import Preferences
        if not Preferences().WritePartCfg:
            return
    except Exception:
        pass
    import json
    import os
    from .variants_cfg import write_part_cfg
    data = None
    raw = root.get("mu_variants")
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = None
    mu_sounds = None
    try:
        from ..import_mu.sound_preview import (
            MU_SOUNDS_KEY,
            flush_sounds_from_vse,
        )
        flush_sounds_from_vse(root)
        sraw = root.get(MU_SOUNDS_KEY)
        if sraw:
            mu_sounds = json.loads(sraw)
    except Exception:
        mu_sounds = None
    if not data and not mu_sounds:
        return
    orig = root.get("mu_cfg_path") or ""
    out_dir = os.path.dirname(os.path.abspath(filepath))
    orig_dir = os.path.dirname(os.path.abspath(orig)) if orig else ""
    if orig_dir and os.path.normpath(out_dir) == os.path.normpath(orig_dir):
        # Same folder as original — do not silently overwrite; use Save Part Cfg
        return
    source = None
    if orig and os.path.isfile(orig):
        with open(orig, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    cfg_name = os.path.basename(orig) if orig else (
        os.path.splitext(os.path.basename(filepath))[0] + ".cfg"
    )
    out_cfg = os.path.join(out_dir, cfg_name)
    try:
        from ..import_mu.sound_preview import log_sound_entries
        log_sound_entries("KSP sound export", mu_sounds)
    except Exception:
        pass
    write_part_cfg(
        out_cfg,
        data or {},
        source_text=source,
        mudir=out_dir,
        mu_basename=os.path.basename(filepath),
        mu_sounds=mu_sounds,
    )
    if operator is not None:
        n = len((mu_sounds or {}).get("entries") or []) if mu_sounds else 0
        if n:
            operator.report(
                {'INFO'}, f"Wrote {out_cfg} (+ {n} animation sound entr(y/ies))"
            )
        else:
            operator.report({'INFO'}, f"Wrote {out_cfg}")


exportable_objects = {
    type(None),
    bpy.types.Mesh,
    bpy.types.Armature,
}

class KSPMU_OT_ExportMu(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File'''
    bl_idname = "export_object.ksp_mu"
    bl_label = "Export Mu"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob",
                                             "axis_forward", "axis_up"))
        return export_mu(self, context, **keywords)

class KSPMU_OT_ExportMu_quick(bpy.types.Operator, ExportHelper):
    '''Save a KSP Mu (.mu) File, defaulting name to selected object'''
    bl_idname = "export_object.ksp_mu_quick"
    bl_label = "Export Mu (quick)"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob",
                                             "axis_forward", "axis_up"))
        return export_mu(self, context, **keywords)

    def invoke(self, context, event):
        obj = context.active_object
        if obj != None:
            self.filepath = strip_nnn(obj.name) + self.filename_ext
        return ExportHelper.invoke(self, context, event)


class KSPMU_OT_ExportMu_variant(bpy.types.Operator, ExportHelper):
    '''Export .mu baked with the currently active ModulePartVariants look'''
    bl_idname = "export_object.ksp_mu_variant"
    bl_label = "Export Active Variant"

    filename_ext = ".mu"
    filter_glob: StringProperty(default="*.mu", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        keywords = self.as_keywords(ignore=("check_existing", "filter_glob",
                                            "axis_forward", "axis_up"))
        return export_mu(self, context, bake_active_variant=True, **keywords)

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            suffix = ""
            try:
                from ..import_mu.cfg_preview import (
                    find_variant_root,
                    get_active_variant_name,
                )
                vroot = find_variant_root(obj, context=context)
                active = get_active_variant_name(vroot) if vroot else None
                if active:
                    safe = "".join(
                        c if c.isalnum() or c in "-_" else "_"
                        for c in active
                    )
                    suffix = "_" + safe
            except Exception:
                pass
            self.filepath = strip_nnn(obj.name) + suffix + self.filename_ext
        return ExportHelper.invoke(self, context, event)

volume_selection_enum = (
    ('ACTIVE', "Active", "Calculate volume of only the active object"),
    ('SELECTED', "Selected", "Calculate the volume of all selected objects"),
    ('HIERARCHY', "Hierarchy", "Calculate the volume of selected objects and their descendents"),
)

class KSPMU_OT_MuVolume(bpy.types.Operator):
    '''Calculate the volume of selected objects'''
    bl_idname = 'object.mu_volume'
    bl_label = 'Mu Volume'

    bl_options = {'PRESET'}

    selection: EnumProperty(name = "Selection",
                            description = "Which objects to measure",
                            items = volume_selection_enum)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj != None and type(obj.data) in exportable_objects

    def execute(self, context):
        obj = context.active_object
        if self.selection == 'ACTIVE':
            if obj.data and type(obj.data) == bpy.types.Mesh:
                vol = volume.obj_volume(obj)
            else:
                vol = volume.model_volume(obj)
        elif self.selection == 'HIERARCHY':
            vol = (0, 0)
            for obj in bpy.context.selected_objects:
                v = volume.model_volume(obj)
                vol = vol[0] + v[0], vol[1] + v[1]
        else:
            vol = (0, 0)
            for obj in bpy.context.selected_objects:
                if obj.data and type(obj.data) == bpy.types.Mesh:
                    v = volume.obj_volume(obj)
                    vol = vol[0] + v[0], vol[1] + v[1]
        self.report({'INFO'}, 'Skin Volume = %g m^3, Ext Volume = %g m^3' % vol)
        return {'FINISHED'}

class KSPMU_OT_MuFindCoM(bpy.types.Operator):
    bl_idname = 'object.mu_snap_cursor_to_com'
    bl_label = 'Mu Center of Mass'

    @classmethod
    def poll(cls, context):
        #print(context.selected_objects)
        if len(context.selected_objects) == 1 and context.active_object:
            return True
        if context.selected_objects:
            return True
        return False

    def execute(self, context):
        obj = context.active_object
        if len(context.selected_objects) == 1 and context.active_object:
            objects = collect_hierarchy_objects(context.active_object)
            #print(objects)
        elif context.selected_objects:
            objects = context.selected_objects[:]
        pos = volume.find_com(objects)
        bpy.context.scene.cursor.location = pos
        return {'FINISHED'}

class KSPMU_OT_MuShowTransform(bpy.types.Operator):
    bl_idname = 'object.mu_show_transform'
    bl_label = 'Mu Show Transform'

    @classmethod
    def poll(cls, context):
        #print(context.selected_objects)
        if len(context.selected_objects) == 1 and context.active_object:
            return True
        if context.selected_objects:
            return True
        return False

    def execute(self, context):
        for obj in context.selected_objects:
            mat = obj.matrix_local
            location = mat.to_translation()
            scale = mat.to_scale()
            yxz_rotation = -Vector(mat.to_euler('YXZ')) * tau
            quat_rot = mat.to_quaternion()
            self.report({'INFO'},
                        f"{obj.name}")
            self.report({'INFO'},
                        f"    position = {vector_str(swapyz(location))}")
            self.report({'INFO'},
                        f"    rotation = {vector_str(swapyz(yxz_rotation))} //euler")
            self.report({'INFO'},
                        f"    rotation = {vector_str(swizzleq(quat_rot))} //quaternion")
            self.report({'INFO'},
                        f"    scale = {vector_str(swapyz(scale))}")
        return {'FINISHED'}
