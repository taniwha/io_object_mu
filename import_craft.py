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
from .import_mu import import_mu


model_by_path = {}
loaded_models = {}
parts = {}
resources = {}
gamedata = "/home/bill/ksp/KSP_linux/GameData"
loaded_models_object = None
parts_object = None

def parse_vector_string(string):
    s = string.split(",")
    if len(s) == 1:
        s = string.split()
    return map(lambda x: float(x), s)

def parse_float(string):
    #FIXME better parsing
    return float(string)

def parse_vector(string):
    # blender is right-handed, KSP is left-handed
    x, z, y = parse_vector_string(string)
    return Vector((x, y, z))

def parse_quaternion(string):
    # blender is right-handed, KSP is left-handed
    x, z, y, w = parse_vector_string(string)
    return Quaternion((w, -x, -y, -z))

def select_objects(obj):
    obj.select = True
    for o in obj.children:
        select_objects(o)

def hide_objects(obj):
    obj.hide = True
    for o in obj.children:
        hide_objects(o)

def show_objects(obj):
    obj.hide = False
    for o in obj.children:
        show_objects(o)

def copy_objects(obj):
    new_obj = obj.copy()
    bpy.context.scene.objects.link(new_obj)
    for o in obj.children:
        no = copy_objects(o)
        no.parent = new_obj
    return new_obj

def load_models(nodes):
    global loaded_models_object
    if not loaded_models_object:
        loaded_models_object = bpy.data.objects.new("loaded_models", None)
        bpy.context.scene.objects.link(loaded_models_object)
        loaded_models_object.hide = True
    objects = []
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
        if model not in loaded_models:
            path = os.path.join(gamedata, model) + ".mu"
            m = import_mu(path, False)
            hide_objects(m)
            loaded_models[model] = m
            m.parent = loaded_models_object
        obj = copy_objects(loaded_models[model])
        obj.location = position
        # blender is right-handed, KSP is left-handed
        # FIXME: it might be better to convert the given euler rotation
        # to a quaternion (for consistency)
        obj.rotation_mode = 'XZY'
        obj.rotation_euler = -rotation
        obj.scale = scale
        objects.append(obj)
    if len(objects) > 1:
        obj = bpy.data.objects.new("something", None)
        bpy.context.scene.objects.link(obj)
        obj.hide = True
        for o in objects:
            o.parent = obj
    else:
        obj = objects[0]
    return obj

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

def process_cfg(path):
    bytes = open(path, "rb").read()
    text = "".join(map(lambda b: chr(b), bytes))
    try:
        cfg = ConfigNode.load(text)
    except ConfigNodeError as e:
        print(path+e.message)
        return
    for node in cfg.nodes:
        if node[0] == "PART":
            gdpath = path[len(gamedata) + 1:]
            part = Part(gdpath, node[1])
            parts[part.name] = part
        elif node[0] == "RESOURCE_DEFINITION":
            res = node[1]
            resname = res.GetValue("name")
            resources[resname] = res

def process_mu(path):
    gdpath = path[len(gamedata) + 1:]
    directory, model = os.path.split(gdpath)
    if directory not in model_by_path:
        model_by_path[directory] = []
    model_by_path[directory].append(model[:-3])

def build_db(path):
    if path[-4:].lower() == ".cfg":
        process_cfg(path)
        return
    if path[-3:].lower() == ".mu":
        process_mu(path)
        return

def create_db():
    recurse_tree(gamedata, build_db)
    for k in model_by_path:
        model_by_path[k].sort()

def import_craft(filepath):
    if not parts:
        create_db()
    bytes = open(filepath, "rb").read()
    text = "".join(map(lambda b: chr(b), bytes))
    try:
        craft = ConfigNode.load(text)
    except ConfigNodeError as e:
        print(path+e.message)
        return
    vessel = bpy.data.objects.new(craft.GetValue("ship"), None)
    vessel.hide = True
    vessel.location = Vector((0, 0, 0))
    vessel.rotation_mode = 'QUATERNION'
    vessel.rotation_quaternion = Quaternion((1,0,0,0))
    vessel.scale = Vector((1, 1, 1))
    bpy.context.scene.objects.link(vessel)
    for p in craft.GetNodes("PART"):
        pname = p.GetValue("part").split("_")[0]
        pos = parse_vector(p.GetValue("pos"))
        rot = parse_quaternion(p.GetValue("rot"))
        part = parts[pname].get_model()
        part.location = pos
        part.rotation_mode = 'QUATERNION'
        part.rotation_quaternion = rot
        part.parent = vessel
    return vessel

def import_craft_op(self, context, filepath):
    if not parts:
        create_db()
    operator = self
    undo = bpy.context.user_preferences.edit.use_global_undo
    bpy.context.user_preferences.edit.use_global_undo = False

    for obj in bpy.context.scene.objects:
        obj.select = False

    obj = import_craft(filepath)
    show_objects(obj)
    select_objects(obj)
    bpy.context.scene.objects.active = obj

    bpy.context.user_preferences.edit.use_global_undo = undo
    return {'FINISHED'}

class ImportCraft(bpy.types.Operator, ImportHelper):
    '''Load a KSP craft file'''
    bl_idname = "import_object.ksp_craft"
    bl_label = "Import Craft"
    bl_description = """Import a KSP .craft (ship) file."""
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".craft"
    filter_glob = StringProperty(default="*.craft", options={'HIDDEN'})

    def execute(self, context):
        keywords = self.as_keywords(ignore=("filter_glob",))
        return import_craft_op(self, context, **keywords)
