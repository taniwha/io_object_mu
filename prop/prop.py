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
from ..model import compile_model, instantiate_model

def loaded_props_collection():
    """
    Return a collection of all collection documents.

    Args:
    """
    return util_collection("loaded_props")

class Prop:
    @classmethod
    def Preloaded(cls):
        """
        Return a dictionary of pre - defined in - order.

        Args:
            cls: (todo): write your description
        """
        preloaded = {}
        for g in bpy.data.collections:
            if g.name[:5] == "prop:":
                url = g.name[5:]
                prop = Prop("", ConfigNode.load(g.mumodelprops.config))
                prop.model = g
                preloaded[url] = prop
        return preloaded
    def __init__(self, path, cfg):
        """
        Initialize the configuration.

        Args:
            self: (todo): write your description
            path: (str): write your description
            cfg: (todo): write your description
        """
        self.cfg = cfg
        self.path = os.path.dirname(path)
        self.name = cfg.GetValue("name")
        self.model = None
    def get_model(self):
        """
        Get model

        Args:
            self: (todo): write your description
        """
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
        """
        Instantiates a copy of the given location.

        Args:
            self: (todo): write your description
            loc: (todo): write your description
            rot: (todo): write your description
            scale: (float): write your description
        """
        obj = bpy.data.objects.new(self.name, None)
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = self.model
        obj.location = loc
        return obj

gamedata = None
def import_prop(filepath):
    """
    Imports a property from a file

    Args:
        filepath: (str): write your description
    """
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
    """
    Create a quaternion object from an object.

    Args:
        obj: (todo): write your description
    """
    name = strip_nnn(obj.name)
    obj.select_set(False)
    prop = collect_objects("prop:"+name, obj)
    obj.muproperties.modelType = 'PROP'
    loc = Vector(obj.location)
    rot = Quaternion(obj.rotation_quaternion)
    scale = Vector(obj.scale)
    parent = obj.parent
    obj.location = Vector((0, 0, 0))
    obj.rotation_quaternion = Quaternion((1, 0, 0, 0))
    obj.scale = Vector((1, 1, 1))
    obj.parent = None
    prop.mumodelprops.name = name
    prop.mumodelprops.type = "prop"
    loaded_props = loaded_props_collection()
    loaded_props.children.link(prop)
    for c in bpy.data.collections:
        if c == prop:
            continue
        for o in prop.objects:
            if o.name in c.objects:
                c.objects.unlink(o)
    obj = instantiate_model(prop, prop.mumodelprops.name, loc, rot, scale)
    obj.muproperties.modelType = 'PROP'
    bpy.context.layer_collection.collection.objects.link(obj)
    obj.parent = parent
    return obj
