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
from mathutils import Vector, Quaternion

from ..cfgnode import ConfigNode
from ..cfgnode import parse_float
from .model import compile_model

def loaded_parts_collection():
    if "loaded_parts" not in bpy.data.collections:
        lp = bpy.data.collections.new("loaded_parts")
        lp.hide_viewport = True
        lp.hide_render = True
        lp.hide_select = True
        bpy.context.scene.collection.children.link(lp)
    return bpy.data.collections["loaded_parts"]

class Part:
    @classmethod
    def Preloaded(cls):
        preloaded = {}
        for g in bpy.data.collections:
            if g.name[:5] == "part:":
                url = g.name[5:]
                part = Part("", ConfigNode.load(g.mumodelprops.config))
                #part.model = bpy.data.collections[g.name]
                part.model = g
                preloaded[part.name] = part
        return preloaded
    def __init__(self, path, cfg):
        self.cfg = cfg
        self.path = os.path.dirname(path)
        if not cfg.HasValue("name"):
            print("PART missing name in " + path)
            self.name = ""
        else:
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
            self.model = compile_model(self.db, self.path, "part", self.name,
                                       self.cfg, loaded_parts_collection())
            props = self.model.mumodelprops
            props.config = self.cfg.ToString(-1)
        scale = self.rescaleFactor
        model = self.instantiate(Vector((0, 0, 0)),
                                 Quaternion((1,0,0,0)),
                                 Vector((1, 1, 1)) * scale)
        return model

    def instantiate(self, loc, rot, scale):
        obj = bpy.data.objects.new(self.name, None)
        obj.dupli_type='COLLECTION'
        obj.dupli_group=self.model
        obj.location = loc
        obj.scale = scale
        return obj

