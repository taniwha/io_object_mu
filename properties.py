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
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty
from bpy.props import BoolVectorProperty, CollectionProperty, PointerProperty
from bpy.props import FloatVectorProperty, IntProperty
from mathutils import Vector,Matrix,Quaternion

from .mu import MuEnum

class MuSpringProp(bpy.types.PropertyGroup):
    spring = FloatProperty(name = "Spring")
    damper = FloatProperty(name = "Damper")
    targetPosition = FloatProperty(name = "Target")

    def draw(self, context, layout):
        row = layout.row()
        col = row.column()
        col.prop(self, "spring")
        col.prop(self, "damper")
        col.prop(self, "targetPosition")

class MuFrictionProp(bpy.types.PropertyGroup):
    extremumSlip = FloatProperty(name = "Slip")
    extremumValue = FloatProperty(name = "Value")
    asymptoteSlip = FloatProperty(name = "Slip")
    asymptoteValue = FloatProperty(name = "Value")
    stiffness = FloatProperty(name = "Stiffness")

    def draw(self, context, layout):
        row = layout.row()
        col = row.column()
        col.label("Extremum")
        col.prop(self, "extremumSlip")
        col.prop(self, "extremumValue")
        col.label("Asymptote")
        col.prop(self, "asymptoteSlip")
        col.prop(self, "asymptoteValue")
        col.separator()
        col.prop(self, "stiffness")

dir_map = {
    'MU_X':0,
    'MU_Y':2,   # unity is LHS, blender is RHS
    'MU_Z':1,   # unity is LHS, blender is RHS
    0:'MU_X',
    2:'MU_Y',   # unity is LHS, blender is RHS
    1:'MU_Z',   # unity is LHS, blender is RHS
}
dir_items = (
    ('MU_X', "X", ""),
    ('MU_Y', "Y", ""),
    ('MU_Z', "Z", ""),
)
collider_items = (
    ('MU_COL_NONE', "", ""),
    ('MU_COL_MESH', "Mesh", ""),
    ('MU_COL_SPHERE', "Sphere", ""),
    ('MU_COL_CAPSULE', "Capsule", ""),
    ('MU_COL_BOX', "Box", ""),
    ('MU_COL_WHEEL', "Wheel", ""),
)

def SetPropMask(prop, mask):
    for i in range(32):
       prop[i] = (mask & (1 << i)) and True or False

def GetPropMask(prop):
    mask = 0
    for i in range(32):
        mask |= int(prop[i]) << i;
    return mask

def collider_update(self, context):
    from .collider import update_collider
    obj = context.active_object
    update_collider(obj)

class MuProperties(bpy.types.PropertyGroup):
    tag = StringProperty(name = "Tag", default="Untagged")
    layer = IntProperty(name = "Layer")

    collider = EnumProperty(items = collider_items, name = "Collider")
    isTrigger = BoolProperty(name = "Trigger", update=collider_update)
    center = FloatVectorProperty(name = "Center", subtype = 'XYZ', update=collider_update)
    radius = FloatProperty(name = "Radius", update=collider_update)
    height = FloatProperty(name = "Height", update=collider_update)
    direction = EnumProperty(items = dir_items, name = "Direction", update=collider_update)
    size = FloatVectorProperty(name = "Size", subtype = 'XYZ', update=collider_update)

    mass = FloatProperty(name = "Mass")
    suspensionDistance = FloatProperty(name = "Distance")
    suspensionSpring = PointerProperty(type=MuSpringProp, name = "Spring")
    forwardFriction = PointerProperty(type=MuFrictionProp, name = "Forward")
    sideFriction = PointerProperty(type=MuFrictionProp, name = "Sideways")

    cullingMask = BoolVectorProperty(size=32, name = "Mask", subtype = 'LAYER')

class MuPropertiesPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_label = 'Mu Properties'

    @classmethod
    def poll(cls, context):
            return True

    def draw(self, context):
        layout = self.layout
        muprops = context.active_object.muproperties
        row = layout.row()
        col = row.column()
        col.prop(muprops, "tag")
        col.prop(muprops, "layer")
        if type(context.active_object.data) in [bpy.types.PointLamp,
                                                bpy.types.SunLamp,
                                                bpy.types.SpotLamp,
                                                bpy.types.HemiLamp,
                                                bpy.types.AreaLamp]:
            col.prop(muprops, "cullingMask")

class MuColliderPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_label = 'Mu Collider'

    @classmethod
    def poll(cls, context):
        muprops = context.active_object.muproperties
        return muprops.collider and muprops.collider != 'MU_COL_NONE'

    def draw(self, context):
        layout = self.layout
        muprops = context.active_object.muproperties
        row = layout.row()
        col = row.column()
        # can't change object types :/ (?)
        #col.prop(muprops, "collider")
        if muprops.collider == 'MU_COL_MESH':
            col.prop(muprops, "isTrigger")
        elif muprops.collider == 'MU_COL_SPHERE':
            col.prop(muprops, "isTrigger")
            col.prop(muprops, "radius")
            col.prop(muprops, "center")
        elif muprops.collider == 'MU_COL_CAPSULE':
            col.prop(muprops, "isTrigger")
            col.prop(muprops, "radius")
            col.prop(muprops, "height")
            col.prop(muprops, "direction")
            col.prop(muprops, "center")
        elif muprops.collider == 'MU_COL_BOX':
            col.prop(muprops, "isTrigger")
            col.prop(muprops, "size")
            col.prop(muprops, "center")
        elif muprops.collider == 'MU_COL_WHEEL':
            col.prop(muprops, "isTrigger")
            col.prop(muprops, "radius")
            col.prop(muprops, "center")
            col.prop(muprops, "mass")
            col.prop(muprops, "suspensionDistance")
            box = col.box()
            box.label("Suspension")
            muprops.suspensionSpring.draw(context, box)
            box = col.box()
            box.label("Forward Friction")
            muprops.forwardFriction.draw(context, box.box())
            box = col.box()
            box.label("Side Friction")
            muprops.sideFriction.draw(context, box.box())

def register():
    bpy.types.Object.muproperties = PointerProperty(type=MuProperties)

def unregister():
    pass
