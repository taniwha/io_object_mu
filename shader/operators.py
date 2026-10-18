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

import os

import bpy
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, EnumProperty
from bl_operators.presets import AddPresetBase
from .shader_extract import record_material
from .shader import create_nodes
from .. import preferences


def _iter_shader_preset_dirs():
    """User-installed preset dirs, then bundled preferences/shaders."""
    subdir = preferences.package_name + "/shaders"
    seen = set()
    for path in bpy.utils.preset_paths(subdir) or []:
        if not path or not os.path.isdir(path):
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        yield path
    try:
        bundled = os.path.join(os.path.dirname(preferences.__file__), "shaders")
    except Exception:
        bundled = None
    if bundled and os.path.isdir(bundled):
        key = os.path.normcase(os.path.abspath(bundled))
        if key not in seen:
            yield bundled


def _shader_preset_enum_items(self, context):
    items = []
    seen = set()
    for path in _iter_shader_preset_dirs():
        try:
            names = sorted(os.listdir(path))
        except Exception:
            continue
        for fn in names:
            if not fn.lower().endswith(".py"):
                continue
            stem = os.path.splitext(fn)[0]
            if stem in seen:
                continue
            seen.add(stem)
            label = bpy.path.display_name(fn)
            items.append((stem, label, ""))
    if not items:
        items = [("NONE", "(no presets)", "")]
    return items


def _resolve_shader_preset(stem):
    if not stem or stem == "NONE":
        return None
    subdir = preferences.package_name + "/shaders"
    filepath = bpy.utils.preset_find(stem, subdir, ext=".py")
    if not filepath:
        filepath = bpy.utils.preset_find(
            stem, subdir, display_name=True, ext=".py"
        )
    if filepath:
        return filepath
    for path in _iter_shader_preset_dirs():
        candidate = os.path.join(path, stem + ".py")
        if os.path.isfile(candidate):
            return candidate
    return None


def _materials_on_selection(context):
    mats = []
    seen = set()
    objs = list(context.selected_objects)
    if not objs and context.active_object:
        objs = [context.active_object]
    for obj in objs:
        for slot in getattr(obj, "material_slots", []) or []:
            mat = slot.material
            if mat is None or mat.name in seen:
                continue
            if not hasattr(mat, "mumatprop"):
                continue
            seen.add(mat.name)
            mats.append(mat)
    return mats

class KSPMU_OT_MuShaderPropExpand(bpy.types.Operator):
    '''Expand/collapse mu shader property set'''
    bl_idname = "object.mushaderprop_expand"
    bl_label = "Mu shader prop expand"
    propertyset: StringProperty()
    def execute(self, context):
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        propset.expanded = not propset.expanded
        return {'FINISHED'}


class KSPMU_OT_MuShaderPropAdd(bpy.types.Operator):
    '''Add a mu shader property'''
    bl_idname = "object.mushaderprop_add"
    bl_label = "Mu shader prop Add"
    propertyset: StringProperty()
    def execute(self, context):
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        prop = propset.properties.add()
        prop.name = "New Property"
        for i, p in enumerate(propset.properties):
            if p == prop:
                propset.index = i
                break
        return {'FINISHED'}

class KSPMU_OT_MuShaderPropRemove(bpy.types.Operator):
    '''Remove a mu shader property'''
    bl_idname = "object.mushaderprop_remove"
    bl_label = "Mu shader prop Remove"
    propertyset: StringProperty()
    def execute(self, context):
        matprops = context.material.mumatprop
        propset = getattr(matprops, self.propertyset)
        if propset.index >= 0:
            propset.properties.remove(propset.index)
        return {'FINISHED'}

class IO_OBJECT_MU_OT_shader_presets(AddPresetBase, bpy.types.Operator):
    bl_idname = "io_object_mu.shader_presets"
    bl_label = "Shaders"
    bl_description = "Mu Shader Presets"
    preset_menu = "IO_OBJECT_MU_MT_shader_presets"
    preset_subdir = "io_object_mu/shaders"

    preset_defines = [
        "mat = bpy.context.material.mumatprop"
        ]
    preset_values = [
        "mat.name",
        "mat.shaderName",
        "mat.color",
        "mat.vector",
        "mat.float2",
        "mat.float3",
        "mat.texture",
        ]

def export_material(operator, context, filepath):
    mat = context.material
    matnode = record_material(mat)
    of = open(filepath,"wt")
    of.write("shader " + matnode.ToString())
    return {'FINISHED'}

class IO_OBJECT_MU_OT_shader_rebuild(bpy.types.Operator):
    '''Rebuild the material node tree'''
    bl_idname = "io_object_mu.shader_rebuild"
    bl_label = "Rebuild Shader"

    @classmethod
    def poll(cls, context):
        return hasattr(context, "material") and context.material != None

    def execute(self, context):
        create_nodes(context.material)
        return {'FINISHED'}


class IO_OBJECT_MU_OT_shader_preset_selection(bpy.types.Operator):
    '''Apply a Mu Shader preset to all materials on selected objects'''
    bl_idname = "io_object_mu.shader_preset_selection"
    bl_label = "Apply Shader Preset to Selection"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Preset",
        items=_shader_preset_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return bool(_materials_on_selection(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset", text="")

    def execute(self, context):
        from .menus import IO_OBJECT_MU_MT_shader_presets

        filepath = _resolve_shader_preset(self.preset)
        if not filepath:
            self.report({'WARNING'}, "Preset not found")
            return {'CANCELLED'}
        mats = _materials_on_selection(context)
        if not mats:
            self.report({'WARNING'}, "No materials on selection")
            return {'CANCELLED'}
        n = 0
        for mat in mats:
            try:
                with context.temp_override(material=mat):
                    IO_OBJECT_MU_MT_shader_presets.reset_cb(context)
                    bpy.utils.execfile(filepath)
                    IO_OBJECT_MU_MT_shader_presets.post_cb(context)
                n += 1
            except Exception as e:
                self.report({'WARNING'}, f"{mat.name}: {e}")
        self.report({'INFO'}, f"Applied preset to {n} material(s)")
        return {'FINISHED'}


class IO_OBJECT_MU_OT_shader_export(bpy.types.Operator, ExportHelper):
    '''Save a material as a .cfg file'''
    bl_idname = "export_material.ksp_cfg"
    bl_label = "Export Material"

    filename_ext = ".cfg"
    filter_glob: StringProperty(default="*.cfg", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return hasattr(context, "material") and context.material != None

    def execute(self, context):
        keywords = self.as_keywords (ignore=("check_existing", "filter_glob",
                                             "axis_forward", "axis_up"))
        return export_material(self, context, **keywords)

classes_to_register = (
    KSPMU_OT_MuShaderPropExpand,
    KSPMU_OT_MuShaderPropAdd,
    KSPMU_OT_MuShaderPropRemove,
    IO_OBJECT_MU_OT_shader_presets,
    IO_OBJECT_MU_OT_shader_rebuild,
    IO_OBJECT_MU_OT_shader_preset_selection,
    IO_OBJECT_MU_OT_shader_export,
)
