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

from struct import unpack
import os.path
from math import pi, sqrt

import bpy
import bpy_types
from mathutils import Vector, Quaternion

from ..mu import Mu
from ..shader import make_shader
from ..utils import set_transform, create_data_object

from .exception import MuImportError
from .animation import create_action, create_object_paths
from .armature import create_armature
from .armature import is_armature, BONE_LENGTH
from .camera import create_camera
from .collider import create_collider
from .light import create_light
from .mesh import create_mesh
from .textures import create_textures

def child_collider(mu, muobj, obj):
    if mu.create_colliders and hasattr(muobj, "collider"):
        if obj.data:
            cobj = create_collider(mu, muobj)
            set_transform(cobj, None)
            mu.collection.objects.link(cobj)
            cobj.parent = obj

import_exclude = {
    "read", "write", "children"
}
type_handlers = {} # filled in by the modules that handle the Mu types

def create_component_object(component, objname, xform):
    name, data, rot = component
    name = ".".join([objname, name])
    if type(data) == bpy_types.Object:
        cobj = data
        if xform:
            set_transform(cobj, xform)
    else:
        cobj = create_data_object(name, data, xform)
    if rot:
        cobj.rotation_quaternion @= rot
    return cobj

def create_object(mu, muobj, parent):
    if muobj in mu.imported_objects:
        # the object has already been processed (probably an armature)
        return muobj.bobj
    mu.imported_objects.add(muobj)

    xform = muobj.transform

    component_data = []
    for a in dir(muobj):
        if a in import_exclude:
            continue
        component = getattr(muobj, a)
        if type(component) in type_handlers:
            data = type_handlers[type(component)](mu, muobj, component, xform.name)
            if data:
                component_data.append(data)

    if len(component_data) != 1:
        #empty or multiple components
        obj = None
        #if a mesh is present, use it for the main object
        for component in component_data:
            if component[0] == "mesh":
                obj = create_component_object(component, xform.name, xform)
                component_data.remove(component)
                break
        if not obj:
            obj = create_data_object(xform.name, None, xform)
        for component in component_data:
            cobj = create_component_object(component, xform.name, None)
            mu.collection.objects.link(cobj)
            cobj.parent = obj
    else:
        obj = create_component_object(component_data[0], xform.name, xform)
    if obj.name not in mu.collection.objects:
        mu.collection.objects.link(obj)

    if not obj.data:
        if xform.name[:5] == "node_":
            #print(name, xform.name[:5])
            obj.empty_display_type = 'SINGLE_ARROW'
            #print(obj.empty_display_type)
            # Blender's empties use the +Z axis for single-arrow
            # display, so that is the most natural orientation for
            # nodes in blender.
            # However, KSP uses the transform's +Z (Unity) axis which
            # is Blender's +Y, so rotate -90 degrees around local X to
            # go from KSP to Blender
            #print(obj.rotation_quaternion)
            rot = Quaternion((0.5**0.5, -(0.5**0.5), 0, 0))
            obj.rotation_quaternion @= rot
            #print(obj.rotation_quaternion)

    muobj.bobj = obj
    obj.parent = parent

    if hasattr(muobj, "tag_and_layer"):
        obj.muproperties.tag = muobj.tag_and_layer.tag
        obj.muproperties.layer = muobj.tag_and_layer.layer

    # prioritize any armatures so their bone objects get consumed
    for child in muobj.children:
        if is_armature(child):
            child.mu = mu
            arm = create_armature(child)
            arm.parent = obj
    for child in muobj.children:
        create_object(mu, child, obj)
    if hasattr(muobj, "animation"):
        for clip in muobj.animation.clips:
            create_action(mu, muobj.path, clip)
    return obj

def create_materials(mu):
    #material info is in the top level object
    for mumat in mu.materials:
        mumat.material = make_shader(mumat, mu)

def process_mu(mu, mudir):
    create_textures(mu, mudir)
    create_materials(mu)
    create_object_paths(mu)
    mu.imported_objects = set()
    return create_object(mu, mu.obj, None)

def import_mu(collection, filepath, create_colliders, force_armature):
    mu = Mu()
    mu.messages = []
    mu.create_colliders = create_colliders
    mu.force_armature = force_armature
    mu.collection = collection
    if not mu.read(filepath):
        raise MuImportError("Mu", "Unrecognized format: magic %x version %d"
                                  % (mu.magic, mu.version))

    return process_mu(mu, os.path.dirname(filepath)), mu
