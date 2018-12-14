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
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Quaternion
from bpy.props import StringProperty, EnumProperty

from ..preferences import Preferences
from ..cfgnode import ConfigNode, ConfigNodeError
from ..utils import collect_objects, strip_nnn, util_collection
from ..model import compile_model

def loaded_props_collection():
    return util_collection("loaded_props")

class Prop:
    @classmethod
    def Preloaded(cls):
        preloaded = {}
        for g in bpy.data.collections:
            if g.name[:5] == "prop:":
                url = g.name[5:]
                prop = Prop("", ConfigNode.load(g.mumodelprops.config))
                prop.model = g
                preloaded[url] = prop
        return preloaded
    def __init__(self, path, cfg):
        self.cfg = cfg
        self.path = os.path.dirname(path)
        self.name = cfg.GetValue("name")
        self.model = None
    def get_model(self):
        if not self.model:
            self.model = compile_model(self.db, self.path, "prop", self.name,
                                       self.cfg, loaded_props_collection())
            props = self.model.mumodelprops
            props.config = self.cfg.ToString(-1)
        model = self.instantiate(Vector((0, 0, 0)),
                                 Quaternion((1,0,0,0)),
                                 Vector((1, 1, 1)))
        return model

    def instantiate(self, loc, rot, scale):
        obj = bpy.data.objects.new(self.name, None)
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = self.model
        obj.location = loc
        return obj

gamedata = None
def import_prop(filepath):
    global gamedata
    if not gamedata:
        from .gamedata import GameData
        gamedata = GameData(Preferences().GameData)
    try:
        propcfg = ConfigNode.loadfile(filepath)
    except ConfigNodeError as e:
        print(filepath+e.message)
        return
    if filepath[:len(gamedata.root)] == gamedata.root:
        #the prop is in GameData
        propnode = propcfg.GetNode("PROP")
        name = propnode.GetValue("name")
        return gamedata.props[name]
    # load it directly
    return Prop(path, propcfg)

def make_prop(obj):
    name = strip_nnn(obj.name)
    collection = collect_objects("prop:"+name, obj)
    obj.muproperties.modelType = 'PROP'
    #FIXME group instancing seems to work with the object's world location
    #rather than its local location
    collection.dupli_offset = obj.location #FIXME update if the prop is later moved
    #necessary because groups don't support rotation or scale offsets
    obj.rotation_quaternion = Quaternion((1, 0, 0, 0))
    obj.scale = Vector((1, 1, 1))
    collection.mumodelprops.name = name
    collection.mumodelprops.type = "prop"
