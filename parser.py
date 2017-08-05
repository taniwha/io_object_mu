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

import sys, traceback, math
from struct import unpack
from pprint import pprint

def build_dictionary(mu, node):
    value_dict={
        "math":math,
        "model":mu.name + ".mu",
        "modelSkinVolume":mu.skin_volume,
        "modelExtVolume":mu.ext_volume,
    }
    i = 0
    while i < len(node.nodes):
        if node.nodes[i][0] == "values":
            for val in node.nodes[i][1].values:
                vstr = val[1].strip()
                if vstr[:2] == "${" and vstr[-1:] == "}":
                    try:
                        nval=eval(vstr[2:-1], value_dict)
                    except Exception as e:
                        print(mu.name + ":" + val[2] + ": " + e.message)
                    else:
                        vstr = nval
                value_dict[val[0]] = vstr
            del (node.nodes[i])
            continue
        i += 1
    return value_dict

def parse_node(mu, node):
    def recurse(value_dict, node):
        for i,val in enumerate(node.values):
            vstr = val[1].strip()
            if vstr[:2] == "${" and vstr[-1:] == "}":
                try:
                    nval=eval(vstr[2:-1], value_dict)
                except Exception as e:
                    print(mu.name + ":" + str(val[2]) + ": " + str(e))
                else:
                    node.values[i] = (val[0], nval, val[2])
        for n in node.nodes:
            recurse(value_dict, n[1])

    value_dict = build_dictionary(mu, node)
    recurse(value_dict, node)
