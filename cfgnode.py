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

from script import Script

class ConfigNodeError(Exception):
    def __init__(self, fname, line, message):
        Exception.__init__(self, "%s:%d: %s" % (fname, line, message))
        self.line = line

def cfg_error(self, msg):
    raise ConfigNodeError(self.filename, self.line, msg)

class ConfigNode:
    def __init__(self):
        self.values = []
        self.nodes = []
    @classmethod
    def ParseNode(cls, node, script, top = False):
        while script.getToken(True) != None:
            if script.token in (top and ['{', '}', '='] or ['{', '=']):
                cfg_error(script, "unexpected " + script.token)
            if script.token == '}':
                return
            key = script.token
            if script.tokenAvailable(True):
                script.getToken(True)
                if script.token == '=':
                    value = ''
                    if script.tokenAvailable(False):
                        script.getLine()
                        value = script.token
                    node.values.append((key, value))
                elif script.token == '{':
                    new_node = ConfigNode()
                    ConfigNode.ParseNode(new_node, script, False)
                    node.nodes.append((key, new_node))
                else:
                    cfg_error(script, "unexpected " + script.token)
        if not top:
            cfg_error(script, "unexpected end of file")
    @classmethod
    def load(cls, text):
        script = Script("", text, "{}=")
        script.error = cfg_error.__get__(script, Script)
        node = ConfigNode()
        ConfigNode.ParseNode(node, script, True)
        return node
    def GetNode(self, key):
        for n in self.nodes:
            if n[0] == key:
                return n[1]
        return None
    def GetNodes(self, key):
        nodes = []
        for n in self.nodes:
            if n[0] == key:
                nodes.append(n[1])
        return nodes
    def GetValue(self, key):
        for v in self.values:
            if v[0] == key:
                return v[1]
        return None
    def GetValues(self, key):
        values = []
        for v in self.values:
            if v[0] == key:
                values.append(v[1])
        return values
    def AddNode(self, key):
        node = ConfigNode ()
        self.nodes.append((key, node))
        return node
    def AddValue(self, key, value):
        self.values.append((key, value))
    def ToString(self, level = 0):
        text = "{ \n"
        for val in self.values:
            text += "%s%s = %s\n" % ("    " * (level + 1), val[0], val[1])
        for node in self.nodes:
            ntext = node[1].ToString(level + 1)
            text += "%s%s %s\n" % ("    " * (level + 1), node[0], ntext)
        text += "%s}\n" % ("    " * (level))
        return text
