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
from .parser import parse_float

def recurse_tree(path, func):
    files = os.listdir(path)
    files.sort()
    for f in files:
        if f[0] in [".", "_"]:
            continue
        p = os.path.join(path, f)
        if os.path.isdir(p):
            recurse_tree(p, func)
        else:
            func(p)

class Part:
    def __init__(self, path, cfg):
        self.cfg = cfg
        self.path = os.path.dirname(path)
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
                self.model = load_models (cfg.GetNodes("MODEL"))
            else:
                mesh = model_by_path[self.path][0]
                #if cfg.HasValue("mesh"):
                #    mesh = cfg.GetValue("mesh")
                #    if mesh[-3:] == '.mu':
                #        mesh = mesh[:-3]
                model = os.path.join(self.path, mesh)
                node = ConfigNode()
                node.AddValue("model", model)
                node.AddValue("position", "0, 0, 0")
                node.AddValue("rotation", "0, 0, 0")
                node.AddValue("scale", "1, 1, 1")
                self.model = load_models ([node])
            global parts_object
            if not parts_object:
                parts_object = bpy.data.objects.new("parts", None)
                bpy.context.scene.objects.link(parts_object)
                parts_object.hide = True
            self.model.parent = parts_object
        model = copy_objects(self.model)
        model.location = Vector((0, 0, 0))
        model.rotation_mode = 'QUATERNION'
        model.rotation_quaternion = Quaternion((1,0,0,0))
        model.scale *= self.rescaleFactor
        return model

class GameData:
    def process_mu(self, path):
        gdpath = path[len(self.root) + 1:]
        directory, model = os.path.split(gdpath)
        if directory not in self.model_by_path:
            self.model_by_path[directory] = []
        self.model_by_path[directory].append(model[:-3])

    def process_cfg(self, path):
        bytes = open(path, "rb").read()
        text = "".join(map(lambda b: chr(b), bytes))
        try:
            cfg = ConfigNode.load(text)
        except ConfigNodeError as e:
            print(path+e.message)
            return
        if not cfg:
            return
        for node in cfg.nodes:
            if node[0] == "PART":
                gdpath = path[len(self.root) + 1:]
                part = Part(gdpath, node[1])
                self.parts[part.name] = part
            elif node[0] == "RESOURCE_DEFINITION":
                res = node[1]
                resname = res.GetValue("name")
                self.resources[resname] = res

    def build_db(self, path):
        if path[-4:].lower() == ".cfg":
            self.process_cfg(path)
            return
        if path[-3:].lower() == ".mu":
            self.process_mu(path)
            return

    def create_db(self):
        recurse_tree(self.root, self.build_db)
        for k in self.model_by_path:
            self.model_by_path[k].sort()

    def __init__(self, path):
        self.root = path
        self.model_by_path = {}
        self.parts = {}
        self.resources = {}
        self.create_db()
