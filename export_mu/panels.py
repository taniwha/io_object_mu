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

import bpy, bmesh
from bpy_extras.object_utils import object_data_add
from mathutils import Vector,Matrix,Quaternion
from pprint import pprint
from math import pi
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty

from ..mu import MuEnum, Mu, MuColliderMesh, MuColliderSphere, MuColliderCapsule
from ..mu import MuObject, MuTransform, MuMesh, MuTagLayer, MuRenderer, MuLight
from ..mu import MuCamera
from ..mu import MuColliderBox, MuColliderWheel, MuMaterial, MuTexture, MuMatTex
from ..mu import MuSpring, MuFriction
from ..mu import MuAnimation, MuClip, MuCurve, MuKey
from ..shader import make_shader
from .. import properties
from ..cfgnode import ConfigNode, ConfigNodeError
from ..parser import parse_node
from ..attachnode import AttachNode
from ..utils import strip_nnn, swapyz, swizzleq, vector_str

from .mesh import make_mesh
from .collider import make_collider
from .animation import collect_animations, find_path_root, make_animations
from .material import make_material
from .cfgfile import generate_cfg
from .volume import model_volume
from .operators import KSPMU_OT_MuVolume, KSPMU_OT_ExportMu, KSPMU_OT_ExportMu_quick

class WORKSPACE_PT_tools_mu_export(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_category = "Mu Tools"
    bl_context = ".workspace"
    bl_label = "Export Mu"

    def draw(self, context):
        layout = self.layout
        #col = layout.column(align=True)
        layout.operator("export_object.ksp_mu_quick", text = "Export Mu Model");
        layout.operator("object.mu_volume", text = "Calc Mu Volume");
