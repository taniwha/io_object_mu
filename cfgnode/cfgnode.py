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

try:
    from .script import Script
except ImportError:
    from script import Script

class ConfigNodeError(Exception):
    def __init__(self, fname, line, message):
        Exception.__init__(self, "%s:%d: %s" % (fname, line, message))
        self.message = "%s:%d: %s" % (fname, line, message)
        self.line = line

def cfg_error(self, msg):
    raise ConfigNodeError(self.filename, self.line, msg)

class ConfigValue:
    def __init__(self, name, value, line, comment=""):
        self.name = name
        self.value = value
        self.line = line
        self.comment = comment
    def ToString(self):
        comment = f" // {self.comment}" if self.comment else ""
        return f"{self.name} = {self.value}{comment}"

class ConfigNode:
    def __init__(self, name="", line=0, comment=""):
        self.name = name
        self.line = line
        self.comment = comment
        self.values = []
        self.nodes = []
    @classmethod
    def ParseNode(cls, node, script, top = False):
        while script.tokenAvailable(True):
            token_start = script.pos
            if script.getToken(True) == None:
                break
            if script.token == "\xef\xbb\xbf":
                continue
            if script.token in (['{', '}', '='] if top else ['{', '=']):
                cfg_error(script, "unexpected " + script.token)
            if script.token == '}':
                return
            token_end = script.pos
            key = script.token
            #print(key,script.line)
            while script.tokenAvailable(True):
                script.getToken(True)
                token_end = script.pos
                line = script.line
                if script.token == '=':
                    value = ''
                    if script.tokenAvailable(False):
                        script.getLine()
                        value = script.token.strip()
                    node.values.append(ConfigValue(key, value, line))
                    break
                elif script.token == '{':
                    new_node = ConfigNode(key, line)
                    ConfigNode.ParseNode(new_node, script, False)
                    node.nodes.append(new_node)
                    break
                else:
                    #cfg_error(script, "unexpected " + script.token)
                    key = script.text[token_start:token_end]
        if not top:
            cfg_error(script, "unexpected end of file")
    @classmethod
    def load(cls, text):
        if not text:
            return []
        script = Script("", text, "{}=", False)
        script.error = cfg_error.__get__(script, Script)
        nodes = []
        while script.tokenAvailable(True):
            node = ConfigNode("", script.line)
            ConfigNode.ParseNode(node, script, True)
            nodes.append(node)
        if len(nodes) == 1:
            return nodes[0]
        else:
            return nodes
    @classmethod
    def loadfile(cls, path):
        bytes = open(path, "rb").read()
        text = "".join(map(lambda b: chr(b), bytes))
        return cls.load(text)
    def GetNode(self, key):
        for n in self.nodes:
            if n.name == key:
                return n
        return None
    def GetNodeLine(self, key):
        for n in self.nodes:
            if n.name == key:
                return n.line
        return None
    def GetNodes(self, key):
        nodes = []
        for n in self.nodes:
            if n.name == key:
                nodes.append(n)
        return nodes
    def GetValue(self, key):
        for v in self.values:
            if v.name == key:
                return v.value.strip()
        return None
    def HasNode(self, key):
        for n in self.nodes:
            if n.name == key:
                return True
        return False
    def HasValue(self, key):
        for v in self.values:
            if v.name == key:
                return True
        return False
    def GetValueLine(self, key):
        for v in self.values:
            if v.name == key:
                return v.line
        return None
    def GetValues(self, key):
        values = []
        for v in self.values:
            if v.name == key:
                values.append(v.value)
        return values
    def AddNode(self, key, node):
        node.name = key
        self.nodes.append(node)
        return node
    def AddNewNode (self, key):
        node = ConfigNode (key, 0)
        self.nodes.append(node)
        return node

    def AddValue(self, key, value, comment=""):
        self.values.append(ConfigValue(key, value, 0, comment))
    def SetValue(self, key, value, comment=""):
        for i in range(len(self.values)):
            if self.values[i].name == key:
                self.values[i] = ConfigValue(key, value, 0, comment)
                return
        self.AddValue(key, value, comment)
    def ToString(self, level = 0):
        extra = 0
        if level >= 0:
            extra = 2
        text=[None] * (len(self.values) + len(self.nodes) + extra)
        index = 0
        comment = f" // {self.comment}" if self.comment else ""
        if level >= 0:
            text[index] = f"{{{comment}\n"
            index += 1
        else:
            if comment: 
                text[index] = f"{comment[1:]}\n"
                index += 1
        for val in self.values:
            text[index] = "%s%s\n" % ("    " * (level + 1), val.ToString())
            index += 1
        for node in self.nodes:
            ntext = node.ToString(level + 1)
            text[index] = "%s%s %s\n" % ("    " * (level + 1), node.name, ntext)
            index += 1
        if level >= 0:
            text[index] = "%s}\n" % ("    " * (level))
            index += 1
        return "".join(text)

if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        text = open(arg, "rt").read()
        try:
            node = ConfigNode.load(text)
        except ConfigNodeError as e:
            print(arg+e.message)
