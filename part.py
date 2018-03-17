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
import sys
import os

import bpy
from mathutils import Vector,Matrix,Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty

from .cfgnode import ConfigNode, ConfigNodeError
from .parser import parse_float, parse_vector
from .model import Model

def loaded_parts_scene():
    if "loaded_parts" not in bpy.data.scenes:
        return bpy.data.scenes.new("loaded_parts")
    return bpy.data.scenes["loaded_parts"]

def group_objects(name, obj):
    def add_to_group(group, obj):
        group.objects.link (obj)
        for child in obj.children:
            add_to_group(group, child)
    group = bpy.data.groups.new(name)
    add_to_group(group, obj)
    return group

class Part:
    def __init__(self, path, cfg):
        self.cfg = cfg
        self.path = path
        self.name = cfg.GetValue("name").replace("_", ".")
        self.model = None
        self.scale = 1.0
        self.rescaleFactor = 1.25
        if cfg.HasValue("scale"):
            self.scale = parse_float(cfg.GetValue("scale"))
        if cfg.HasValue("rescaleFactor"):
            self.rescaleFactor = parse_float(cfg.GetValue("rescaleFactor"))
    def get_model(self):
        if not self.model:
            cfg = self.cfg
            if cfg.HasNode("MODEL"):
                self.model = self.load_models (cfg.GetNodes("MODEL"))
            else:
                mesh = self.db.model_by_path[self.path][0]
                url = os.path.join(self.path, mesh)
                model = self.db.model(url)
                obj = model.instantiate(self.name+":model",
                                        Vector((0, 0, 0)),
                                        Quaternion((1,0,0,0)),
                                        Vector((1, 1, 1)))
                scene = loaded_parts_scene()
                scene.objects.link(obj)
                self.model = group_objects("part:" + self.name, obj)
        model = self.instantiate(Vector((0, 0, 0)),
                                 Quaternion((1,0,0,0)),
                                 Vector((1, 1, 1)) * self.rescaleFactor)
        return model
    def load_models(self, nodes):
        root = bpy.data.objects.new(self.name+":model", None)
        scene = loaded_parts_scene()
        scene.objects.link(root)
        for n in nodes:
            model = n.GetValue("model")
            position = Vector((0, 0, 0))
            rotation = Vector((0, 0, 0))
            scale = Vector((1, 1, 1))
            if n.HasValue("position"):
                position = parse_vector(n.GetValue("position"))
            if n.HasValue("rotation"):
                rotation = parse_vector(n.GetValue("rotation"))
            if n.HasValue("scale"):
                scale = parse_vector(n.GetValue("scale"))
            mdl = self.db.model(model)
            obj = mdl.instantiate(self.name+":submodel",
                                  position, rotation, scale)
            scene.objects.link(obj)
            obj.parent = root
        return group_objects("part:" + self.name, obj)

    def instantiate(self, loc, rot, scale):
        obj = bpy.data.objects.new(self.name, None)
        obj.dupli_type='GROUP'
        obj.dupli_group=self.model
        obj.location = loc
        return obj

