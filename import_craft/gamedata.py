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

from ..cfgnode import ConfigNode, ConfigNodeError
from .model import Model
from .part import Part
from .prop import Prop

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

class Internal(Part):
    pass

class GameData:
    ModuleManager = "ModuleManager.ConfigCache"
    def process_mu(self, path):
        gdpath = path[len(self.root):]
        directory, model = os.path.split(gdpath)
        if directory not in self.model_by_path:
            self.model_by_path[directory] = []
        self.model_by_path[directory].append(model[:-3])
        url = gdpath[:-3]
        if url not in self.models:
            self.models[url] = path

    def process_cfgnode(self, path, node):
        if node[0] == "PART":
            part = Part(path, node[1])
            if part.name in self.parts:
                part = self.parts[part.name]
            self.parts[part.name] = part
            part.db = self
        elif node[0] == "PROP":
            prop = Prop(path, node[1])
            if prop.name in self.props:
                prop = self.props[prop.name]
            prop.db = self
            self.props[prop.name] = prop
        elif node[0] == "INTERNAL":
            internal = Internal(path, node[1])
            internal.db = self
            self.internals[internal.name] = internal
        elif node[0] == "RESOURCE_DEFINITION":
            res = node[1]
            resname = res.GetValue("name")
            self.resources[resname] = res
        elif node[0] == "Localization":
            locs = node[1].nodes[0][1]
            for loc in locs.values:
                self.localizations[loc[0]] = loc[1]

    def process_cfg(self, path):
        if self.use_module_manager:
            return
        try:
            cfg = ConfigNode.loadfile(path)
        except ConfigNodeError as e:
            print(path+e.message)
            return
        if not cfg:
            return
        for node in cfg.nodes:
            gdpath = path[len(self.root):]
            self.process_cfgnode(gdpath, node)

    def build_db(self, path):
        if path[-4:].lower() == ".cfg":
            self.process_cfg(path)
            return
        if path[-3:].lower() == ".mu":
            self.process_mu(path)
            return

    def parse_module_manager(self, mmcache):
        try:
            cfg = ConfigNode.loadfile(mmcache)
        except ConfigNodeError as e:
            print(mmcache+e.message)
            return False
        for name, node, line in cfg.nodes:
            if name != "UrlConfig":
                continue
            type = node.GetValue("type")
            path = node.GetValue("parentUrl")
            if type in {"PART", "PROP", "INTERNAL", "RESOURCE_DEFINITION",
                        "Localization"}:
                self.process_cfgnode(path, (type, node.GetNode(type)))
        return True

    def create_db(self):
        mmcache = os.path.join(self.root, self.ModuleManager)
        if os.access(mmcache, os.F_OK):
            if self.parse_module_manager(mmcache):
                self.use_module_manager = True
        recurse_tree(self.root, self.build_db)
        for k in self.model_by_path:
            self.model_by_path[k].sort()

    def __init__(self, path):
        self.use_module_manager = False
        self.root = path
        self.model_by_path = {}
        self.models = Model.Preloaded()
        self.parts = Part.Preloaded()
        self.props = Prop.Preloaded()
        self.internals = {}
        self.localizations = {}
        self.resources = {}
        self.create_db()

    def model(self, url):
        if url not in self.models:
            return None
        if type(self.models[url]) == type(""):
            path = os.path.join(self.root, self.models[url])
            self.models[url] = Model(path, url)
        return self.models[url]

gamedata = None
