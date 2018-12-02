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

from mathutils import Quaternion

from ..cfgnode import ConfigNode, ConfigNodeError
from ..utils import strip_nnn, swapyz
from .. import properties

class AttachNode:
    node_types = ["stack", "attach"]
    def __init__(self, obj, inv):
        self.name = strip_nnn(obj.name)
        self.parts = self.name.split("_", 2)
        ind = self.parts[1] == "stack" and 2 or 1
        self.id = "_".join(self.parts[ind:])
        self.pos = swapyz((inv @ obj.matrix_world.col[3])[:3])
        self.dir = swapyz((inv @ obj.matrix_world.col[2])[:3])
        self.size = obj.muproperties.nodeSize
        self.method = obj.muproperties.nodeMethod
        self.crossfeed = obj.muproperties.nodeCrossfeed
        self.rigid = obj.muproperties.nodeRigid
    def __lt__(self, other):
        return self.cmp(other) < 0
    def __eq__(self, other):
        return self.cmp(other) == 0
    def __gt__(self, other):
        return self.cmp(other) > 0
    def cmp(self, other):
        # parts[0] will always be "node"
        if self.parts[1] == other.parts[1]:
            x = len(self.parts) - len(other.parts)
            if x != 0:
                return x
            if len(self.parts) < 3:
                return 0
            if self.parts[2] == other.parts[2]:
                return 0
            if self.parts[2] == "bottom":
                return 1
            if self.parts[2] == "top":
                if other.parts[2] == "bottom":
                    return -1
                else:
                    return 1
            if other.parts[2] == "bottom":
                return -1
            if other.parts[2] == "top":
                if self.parts[2] == "bottom":
                    return 1
                else:
                    return -1
            return self.parts[2] > other.parts[2] and 1 or -1
        elif (self.parts[1] in self.node_types
              and other.parts[1] in self.node_types):
            return ord(other.parts[1][0]) - ord(self.parts[1][0])
        else:
            return self.parts[1] > other.parts[1] and 1 or -1
    def __repr__(self):
        return self.name + self.pos.__repr__() + self.dir.__repr__()
    def methodval(self):
        for i, enum in enumerate(properties.method_items):
            if enum[0] == self.method:
                return i
        return 0
    def cfgstring(self):
        pos = tuple(map (lambda x: x * x > 1e-11 and x or 0, self.pos))
        dir = tuple(map (lambda x: x * x > 1e-11 and x or 0, self.dir))
        flags = (self.size, self.methodval(), int(self.crossfeed),
                 int(self.rigid))
        return "%g, %g, %g, %g, %g, %g, %d, %d, %d, %d" % (pos + dir + flags)
    def cfgnode(self):
        node = ConfigNode ()
        node.AddValue ("name", self.id)
        node.AddValue ("transform", self.name)
        node.AddValue ("size", self.size)
        node.AddValue ("method", self.method)
        node.AddValue ("crossfeed", self.crossfeed)
        node.AddValue ("rigid", self.rigid)
        return node
    def keep_transform(self):
        return self.parts[1] not in ["attach"]
    def save(self, cfg):
        if self.parts[1] in ["attach"]:
            # currently, KSP fails to check for attach NODEs so must use the
            # old format
            cfg.AddValue (self.name, self.cfgstring())
        else:
            cfg.AddNode("NODE", self.cfgnode())

# Blender's empties use the +Z axis for single-arrow display, so
# that is the most natural orientation for nodes in blender.
# However, KSP uses the transform's +Z (Unity) axis which is
# Blender's +Y, so rotate 90 degrees around local X to go from
# Blender to KSP
rotation_correction = Quaternion((0.5**0.5, 0.5**0.5, 0, 0))
