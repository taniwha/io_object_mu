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

import sys, os
from pprint import pprint

import bpy
from mathutils import Vector

from ..cfgnode import ConfigNode

shader_configs = {}

def load_shader_configs(path):
    files = os.listdir(path)
    for f in files:
        if f[0] in [".", "_"]:
            continue
        if f[-4:] == ".cfg":
            p = "/".join((path, f))
            if os.path.isfile(p):
                cfg = ConfigNode.loadfile(p)
                for shader in cfg.GetNodes("shader"):
                    if shader.HasValue("name"):
                        shader_configs[shader.GetValue("name")] = shader
    #pprint(shader_configs)
