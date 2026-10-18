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
from bpy.app.handlers import persistent
from bpy.props import BoolProperty
from bpy.props import CollectionProperty
from bpy.props import FloatVectorProperty, IntProperty


def _material_from_prop(prop, context=None):
    if context is not None:
        mat = getattr(context, "material", None)
        if mat is not None:
            return mat
    idd = getattr(prop, "id_data", None)
    if isinstance(idd, bpy.types.Material):
        return idd
    return None


def apply_color_prop_to_nodes(mat, prop):
    """Push one mumatprop color into its Color4 (or similar) node."""
    if not mat or not mat.node_tree:
        return
    name = getattr(prop, "name", "") or ""
    if not name:
        return
    node = mat.node_tree.nodes.get(name)
    if node is None or not node.inputs:
        return
    try:
        rgba = tuple(float(x) for x in prop.value)
    except Exception:
        return
    # Soft-clamp only near-white RCS end-of-clip wash (stock thruster curves
    # finish at RGB white). Do NOT crush yellow/orange ModuleAnimateHeat —
    # that progression is the whole point of Cone_Heat / airplaneTail.
    if name == "_EmissiveColor":
        r, g, b, a = rgba[0], rgba[1], rgba[2], rgba[3] if len(rgba) > 3 else 1.0
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        chroma = max(r, g, b) - min(r, g, b)
        if lum > 0.82 and chroma < 0.18:
            t = min(1.0, max(0.0, (lum - 0.75) / 0.25))
            tr, tg, tb = 0.28, 0.08, 0.01
            r = r * (1.0 - t) + tr * t
            g = g * (1.0 - t) + tg * t
            b = b * (1.0 - t) + tb * t
            if lum > 0.92:
                r *= 0.55
                g *= 0.50
                b *= 0.50
            rgba = (r, g, b, a)
    try:
        node.inputs[0].default_value = rgba
    except Exception:
        pass
    if len(node.inputs) > 1:
        try:
            node.inputs[1].default_value = rgba[3]
        except Exception:
            pass


def sync_mumatprop_color_nodes(mat):
    """Copy all mumatprop.color values into shader nodes (animation-safe)."""
    mp = getattr(mat, "mumatprop", None)
    if not mp:
        return
    try:
        props = mp.color.properties
    except Exception:
        return
    for prop in props:
        apply_color_prop_to_nodes(mat, prop)


def sync_all_mumatprop_color_nodes(scene=None):
    for mat in bpy.data.materials:
        sync_mumatprop_color_nodes(mat)


def color_update(self, context):
    mat = _material_from_prop(self, context)
    if mat is None:
        return
    apply_color_prop_to_nodes(mat, self)


@persistent
def _mu_frame_change_sync_colors(scene, depsgraph=None):
    # FCurve evaluation does not reliably call Property update(); push colors
    # into nodes so ModuleLight / ModuleAnimateHeat preview works.
    sync_all_mumatprop_color_nodes(scene)


def register_handlers():
    handlers = bpy.app.handlers.frame_change_pre
    if _mu_frame_change_sync_colors not in handlers:
        handlers.append(_mu_frame_change_sync_colors)


def unregister_handlers():
    handlers = bpy.app.handlers.frame_change_pre
    try:
        handlers.remove(_mu_frame_change_sync_colors)
    except ValueError:
        pass


class MuColorProp(bpy.types.PropertyGroup):
    value: FloatVectorProperty(
        name="",
        size=4,
        subtype="COLOR",
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        update=color_update,
    )


class MuMaterialColorPropertySet(bpy.types.PropertyGroup):
    bl_label = "Colors"
    properties: CollectionProperty(type=MuColorProp, name="Colors")
    index: IntProperty()
    expanded: BoolProperty()

    def draw_item(self, layout):
        item = self.properties[self.index]
        row = layout.row()
        col = row.column()
        col.prop(item, "name", text="Name")
        col.prop(item, "value", text="")


classes_to_register = (
    MuColorProp,
    MuMaterialColorPropertySet,
)
