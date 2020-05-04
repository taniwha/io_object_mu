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

import bpy
from mathutils import Vector

from ..cfgnode import ConfigNode, ConfigNodeError
from ..cfgnode import parse_node

def str2bool(boolstr):
    if not boolstr:
        return False
    return boolstr.lower() == "true"

def str2float(floatstr):
    if not floatstr:
        return 0.0
    return float(floatstr)

def str2int(intstr):
    if not intstr:
        return 0
    return int(intstr)

def str2vec3(vecstr):
    if not vecstr:
        return Vector((0, 0, 0))
    x,y,z = vecstr.split(",")
    return Vector((str2float(x.strip()),
                   str2float(y.strip()),
                   str2float(z.strip())))

def parseItems(items):
    enum = []
    for i in items.values:
        name, desc, line = i
        enum.append((name, name, desc))
    return enum

available_modules=[]
available_modules_map={}
available_modules_enum=[]

class KSPField:
    def __init__(self, name, type, default, description, min=None, max=None, items=None):
        self.name = name
        self.type = type
        self.default = default
        self.description = description
        self.items = items
        self.min = min
        self.max = max
    def property(self):
        if self.type == "bool":
            return "boolProperties"
        elif self.type == "float":
            return "floatProperties"
        elif self.type == "enum":
            return "stringProperties"
        elif self.type == "int":
            return "intProperties"
        elif self.type == "Vector3":
            return "vectorProperties"
        elif self.type == "string":
            return "stringProperties"
        elif self.type == "transform":
            return "pointerProperties"
        elif self.type == "FloatCurve":
            return "pointerProperties"

class KSPModule:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
        self.field_map = {}
        for f in fields:
            self.field_map[f.name] = f

def generate_module_properties(module_def):
    moduleName = module_def.GetValue("name")
    field_defs = module_def.GetNodes("field")
    fields=[]
    for field_node in field_defs:
        params = {}
        fldType = params["type"] = field_node.GetValue("type")
        fldName = params["name"] = field_node.GetValue("name")
        params["default"] = field_node.GetValue("default")
        params["description"] = field_node.GetValue("description")
        params["min"] = None
        params["max"] = None
        if params["description"] == None:
            params["description"] = ""
        if fldType == 'bool':
            params["default"] = str2bool (params["default"])
        elif fldType == 'enum':
            params["items"] = parseItems(field_node.GetNode("items"))
        elif fldType == 'float':
            params["min"] = str2float(field_node.GetValue("min"));
            params["max"] = str2float(field_node.GetValue("max"));
            params["default"] = str2float (params["default"])
        elif fldType == 'int':
            params["default"] = str2int (params["default"])
        elif fldType == 'Vector3':
            params["default"] = str2vec3 (params["default"])
        elif fldType == 'string':
            if params["default"] == None:
                params["default"] = ""
        elif fldType in ["transform", "FloatCurve"]:
            pass
        else:
            raise TypeError('Unsupported type (%s) for %s on %s' % (fldType, fldName, moduleName))
        field = KSPField(**params)
        fields.append(field)

    module = KSPModule(moduleName, fields)
    available_modules.append(module)
    available_modules_map[moduleName] = module
    item = (module.name, module.name, module.name)
    available_modules_enum.append(item)
    
def build_modules():
    available_modules.clear()
    available_modules_map.clear()
    available_modules_enum.clear()
    for modtext in bpy.data.texts:
        if modtext.name[-4:] == ".mod":
            try:
                moddefs = ConfigNode.load(modtext.as_string())
            except ConfigNodeError as e:
                print("Error reading", modtext.name, e.message)
            else:
                for mod in moddefs.nodes:
                    if mod[0] == "MODULE":
                        generate_module_properties(mod[1])

def ksp_module_items(self, context):
    return available_modules_enum
