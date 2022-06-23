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
from mathutils import Vector
from math import pi

from ..cfgnode import ConfigNode, ConfigNodeError
from ..cfgnode import parse_node
from ..utils import strip_nnn, swapyz, swizzleq, vector_str

#gotta mess with the heads of 6.28 fans :)
tau = 180 / pi

def find_template(mu, filepath):
    base = os.path.splitext(filepath)
    cfg = base[0] + ".cfg"

    cfgin = mu.name + ".cfg.in"
    if cfgin in bpy.data.texts:
        return cfg, ConfigNode.load(bpy.data.texts[cfgin].as_string())

    cfgin = base[0] + ".cfg.in"
    if os.path.isfile (cfgin):
        try:
            return cfg, ConfigNode.loadfile(cfgin)
        except ConfigNodeError as e:
            print("Error reading", cfgin, e.message)

    return None, None

def add_internal_node(node, internal):
    # NOTE this assumes the internal is the direct child of the part's root
    # also, it assumes the internal is correctly oriented relative to the part
    # (FIXME?)
    inode = node.AddNewNode('INTERNAL')
    inode.AddValue("name", strip_nnn(internal.name))
    if internal.location:
        inode.AddValue("offset", vector_str(swapyz(internal.location)))
    # not really a good idea IMHO, but it's there...
    if internal.scale != Vector((1, 1, 1)):
        inode.AddValue("scale", vector_str(swapyz(internal.scale)))

def add_prop_node(mu, node, prop):
    path, prop = prop
    name = strip_nnn(prop.name)
    path = f"{path}/{name}"
    xform = mu.inverse @ prop.matrix_world
    location = xform.translation
    rotation = xform.to_quaternion()
    scale = xform.to_scale()
    pnode = node.AddNewNode('PROP')
    pnode.comment = path
    pnode.AddValue("name", name)
    pnode.AddValue("position", vector_str(swapyz(location)))
    pnode.AddValue("rotation", vector_str(swizzleq(rotation)))
    pnode.AddValue("scale", vector_str(swapyz(scale)))

def add_model_node(mu, node, model):
    path, model, extra = model
    if not extra:
        parent = model.parent
        matrix = model.matrix_local
    else:
        parent, matrix = extra
        matrix = matrix @ model.matrix_local
    name = strip_nnn(model.name)
    modelPath = bpy.context.scene.musceneprops.modelPath
    if modelPath:
        modelPath = "/".join([modelPath, name])
    else:
        modelPath = name
    path = f"{path}/{name}"
    location = matrix.to_translation()
    scale = matrix.to_scale()
    yxz_rotation = Vector(matrix.to_euler('YXZ'))
    mnode = node.AddNewNode('MODEL')
    mnode.comment = path
    mnode.AddValue("model", modelPath)
    mnode.AddValue("parent", strip_nnn(parent.name))
    mnode.AddValue("name", name)
    mnode.AddValue("position", vector_str(swapyz(location)))
    mnode.AddValue("rotation", vector_str(swapyz(-yxz_rotation * tau)))
    mnode.AddValue("scale", vector_str(swapyz(scale)))

def generate_cfg(mu, filepath):
    cfgfile, cfgnode = find_template(mu, filepath)
    if not cfgnode:
        return
    ntype = mu.type
    if ntype == 'NONE':
        ntype = bpy.context.scene.musceneprops.modelType
    node = cfgnode.GetNode(ntype)
    if not node:
        return
    parse_node(mu, cfgnode)
    for model in mu.models:
        add_model_node(mu, node, model)
    if ntype == 'PART':
        if mu.CoMOffset != None:
            node.AddValue("CoMOffset", vector_str(swapyz(mu.CoMOffset)))
        if mu.CoPOffset != None:
            node.AddValue("CoPOffset", vector_str(swapyz(mu.CoPOffset)))
        if mu.CoLOffset != None:
            node.AddValue("CoLOffset", vector_str(swapyz(mu.CoLOffset)))
        if mu.internals:
            add_internal_node(node, mu.internals[0])
        mu.nodes.sort()
        for n in mu.nodes:
            n.save(node)
    elif ntype == 'INTERNAL':
        for prop in mu.props:
            add_prop_node(mu, node, prop)
    # nothing meaningful for PROP
    of = open(cfgfile, "wt")
    for n in cfgnode.nodes:
        of.write(n.name + " " + n.ToString())
