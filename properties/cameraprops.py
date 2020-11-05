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
from bpy.props import BoolVectorProperty, FloatProperty
from bpy.props import FloatVectorProperty, EnumProperty

clearflag_items = (
    ('SKYBOX', "Skybox", ""),
    ('COLOR', "Solid Color", ""),
    ('DEPTH', "Depth", ""),
    ('NOTHING', "Nothing", ""),
)

class MuCameraProperties(bpy.types.PropertyGroup):
    clearFlags: EnumProperty(items = clearflag_items, name = "Clear Flags", default = 'SKYBOX')
    backgroundColor: FloatVectorProperty(name="Background Color", size = 4, subtype='COLOR', min = 0.0, max = 1.0, default = (0.0, 0.0, 0.0, 1.0))
    cullingMask: BoolVectorProperty(size=32, name = "Culling Mask", subtype = 'LAYER')
    depth: FloatProperty(name = "Depth")

class OBJECT_PT_MuCameraPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_label = 'Mu Properties'

    @classmethod
    def poll(cls, context):
        """
        Return true if the given context is active.

        Args:
            cls: (todo): write your description
            context: (dict): write your description
        """
        if type(context.active_object.data) in [bpy.types.Camera]:
            return True
        return False

    def draw(self, context):
        """
        Draw layout

        Args:
            self: (todo): write your description
            context: (dict): write your description
        """
        layout = self.layout
        muprops = context.active_object.data.mucameraprop
        row = layout.row()
        col = row.column()
        col.prop(muprops, "clearFlags")
        col.prop(muprops, "backgroundColor")
        col.prop(muprops, "cullingMask")
        col.prop(muprops, "depth")

classes_to_register = (
    MuCameraProperties,
    OBJECT_PT_MuCameraPanel
)
custom_properties_to_register = (
    (bpy.types.Camera, "mucameraprop", MuCameraProperties),
)
