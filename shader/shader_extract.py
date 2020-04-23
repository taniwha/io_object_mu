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
from .. import cfgnode

node_common = {
    "__doc__",
    "__module__",
    "__slots__",
    "type",
    "location",
    "width",
    "width_hidden",
    "height",
    "dimensions",
    "name",
    "label",
    "inputs",
    "outputs",
    "parent",
    "use_custom_color",
    "color",
    "select",
    "show_options",
    "show_preview",
    "hide",
    "mute",
    "show_texture",
    "draw_buttons",
    "draw_buttons_ext",
    "internal_links",
    "input_template",
    "output_template",
    "is_registered_node_type",
    "poll",
    "poll_instance",
    "bl_idname",
    "bl_label",
    "bl_rna",
    "bl_description",
    "bl_icon",
    "bl_static_type",
    "bl_width_default",
    "bl_width_min",
    "bl_width_max",
    "bl_height_default",
    "bl_height_min",
    "bl_height_max",
    "rna_type",
    "socket_value_update",
    "update",
    "interface",

    #texture stuff, not directly usable?
    "color_mapping",
    "image_user",
}

node_groups = set()

def record_inputs(treenode, inputs):
    if not inputs:
        return
    node = treenode.AddNewNode("inputs")
    for input in inputs:
        node.AddValue("input", input.name)

def record_outputs(treenode, outputs):
    if not outputs:
        return
    node = treenode.AddNewNode("outputs")
    for output in outputs:
        node.AddValue("output", output.name)
        
def record_texture_mapping(texmap):
    node = cfgnode.ConfigNode()
    node.AddValue("type", texmap.vector_type)
    node.AddValue("translation", tuple(texmap.translation))
    node.AddValue("rotation", tuple(texmap.rotation))
    node.AddValue("scale", tuple(texmap.scale))
    node.AddValue("min", tuple(texmap.min))
    node.AddValue("max", tuple(texmap.max))
    node.AddValue("use_min", texmap.use_min)
    node.AddValue("use_max", texmap.use_max)
    node.AddValue("mapping_x", texmap.mapping_x)
    node.AddValue("mapping_y", texmap.mapping_y)
    node.AddValue("mapping_z", texmap.mapping_z)
    node.AddValue("mapping", texmap.mapping)
    return node

def record_node(node):
    out = cfgnode.ConfigNode()
    out.AddValue("location", tuple(node.location))
    out.AddValue("width", node.width)
    out.AddValue("width_hidden", node.width_hidden)
    out.AddValue("height", node.height)
    out.AddValue("name", node.name)
    out.AddValue("label", node.label)
    out.AddValue("parent", node.parent.name if node.parent else "")
    out.AddValue("use_custom_color", node.use_custom_color)
    out.AddValue("color", tuple(node.color))
    out.AddValue("select", node.select)
    out.AddValue("show_options", node.show_options)
    out.AddValue("show_preview", node.show_preview)
    out.AddValue("hide", node.hide)
    out.AddValue("mute", node.mute)
    out.AddValue("show_texture", node.show_texture)
    for a in dir(node):
        if a in node_common:
            continue
        attr = getattr(node, a)
        if hasattr(type(attr), "bl_rna"):
            t = type(attr).bl_rna.identifier
            if t == "TexMapping":
                out.AddNode(a, record_texture_mapping(attr))
            elif t == "Image":
                out.AddValue(a, attr.name)
            elif t == "ShaderNodeTree":
                out.AddValue(a, attr.name)
                node_groups.add(attr.name)
            else:
                out.AddValue(a, attr)
        else:
            out.AddValue(a, attr)
    return out

def record_nodes(treenode, nodes):
    if not nodes:
        return
    node = treenode.AddNewNode("nodes")
    for n in nodes:
        node.AddNode(type(n).bl_rna.identifier, record_node(n))

def record_link(link):
    node = cfgnode.ConfigNode()
    node.AddValue("from_node", link.from_node.name)
    node.AddValue("to_node", link.to_node.name)
    node.AddValue("from_socket", link.from_socket.name)
    node.AddValue("to_socket", link.to_socket.name)
    node.AddValue("is_hidden", link.is_hidden)
    return node

def record_links(treenode, links):
    if not links:
            return
    node = treenode.AddNewNode("links")
    for l in links:
        node.AddNode("link", record_link(l))

def record_node_tree(node_tree, treenode):
    treenode.AddValue("name", node_tree.name)
    treenode.AddValue("tag", node_tree.tag)
    treenode.AddValue("view_center", tuple(node_tree.view_center))
    record_nodes(treenode, node_tree.nodes)
    record_links(treenode, node_tree.links)
    record_inputs(treenode, node_tree.inputs)
    record_outputs(treenode, node_tree.outputs)

def record_material(mat):
    matnode = cfgnode.ConfigNode()
    matnode.AddValue("blend_method", mat.blend_method)
    matnode.AddValue("shadow_method", mat.shadow_method)
    matnode.AddValue("alpha_threshold", mat.alpha_threshold)
    matnode.AddValue("show_transparent_back", mat.show_transparent_back)
    matnode.AddValue("use_backface_culling", mat.use_backface_culling)
    matnode.AddValue("use_screen_refraction", mat.use_screen_refraction)
    matnode.AddValue("use_sss_translucency", mat.use_sss_translucency)
    matnode.AddValue("refraction_depth", mat.refraction_depth)
    matnode.AddValue("use_sss_translucency", mat.use_sss_translucency)
    matnode.AddValue("preview_render_type", mat.preview_render_type)
    matnode.AddValue("use_preview_world", mat.use_preview_world)
    matnode.AddValue("pass_index", mat.pass_index)
    matnode.AddValue("use_nodes", mat.use_nodes)
    matnode.AddValue("diffuse_color", tuple(mat.diffuse_color))
    matnode.AddValue("specular_color", tuple(mat.specular_color))
    matnode.AddValue("roughness", mat.roughness)
    matnode.AddValue("specular_intensity", mat.specular_intensity)
    matnode.AddValue("metallic", mat.metallic)
    if mat.use_nodes:
        treenode = matnode.AddNewNode("node_tree")
        record_node_tree(mat.node_tree, treenode)
    node = cfgnode.ConfigNode()
    node.AddNode("Material", matnode)
    print(node_groups)
    while node_groups:
        group = node_groups.pop()
        treenode = node.AddNewNode("node_tree")
        record_node_tree(bpy.data.node_groups[group], treenode)
    return node
