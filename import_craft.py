import sys
import os

import bpy
from mathutils import Vector,Matrix,Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import BoolProperty, FloatProperty, StringProperty, EnumProperty

from .cfgnode import ConfigNode, ConfigNodeError
from .import_mu import import_mu


loaded_models = {}
parts = {}
resources = {}
gamedata = "/home/bill/ksp/KSP_linux-ckan/GameData"

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
                mesh = "model"
                if cfg.HasValue("mesh"):
                    mesh = cfg.GetValue("mesh")
                    if mesh[-3:] == '.mu':
                        mesh = mesh[:-3]
                model = os.path.join(self.path, mesh)
                node = ConfigNode()
                node.AddValue("model", model)
                node.AddValue("position", "0, 0, 0")
                node.AddValue("rotation", "0, 0, 0")
                node.AddValue("scale", "1, 1, 1")
                print(self.name)
                self.model = load_models ([node])
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

def build_cfgdb(path):
    if path[-4:].lower() != ".cfg":
        return
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
            print(part.name, part.path, gdpath, gamedata)
            parts[part.name] = part
        elif node[0] == "RESOURCE_DEFINITION":
            res = node[1]
            resname = res.GetValue("name")
            resources[resname] = res

def import_craft(filepath):
    if not parts:
        recurse_tree(gamedata, build_cfgdb)
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
        recurse_tree(gamedata, build_cfgdb)
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
