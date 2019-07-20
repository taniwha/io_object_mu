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
from mathutils import Vector, Quaternion

from ..mu import Mu
from ..shader import make_shader
from ..utils import set_transform, create_data_object

from .exception import MuImportError
from .animation import create_action, create_object_paths
from .armature import create_armature, create_armature_modifier
from .armature import is_armature, BONE_LENGTH, create_vertex_groups
from .camera import create_camera
from .collider import create_collider
from .light import create_light
from .mesh import create_mesh
from .textures import create_textures

def attach_material(mesh, renderer, mu):
    if mu.materials and renderer.materials:
        #KSP supports only the first submesh and thus only the first
        #material
        mumat = mu.materials[renderer.materials[0]]
        mesh.materials.append(mumat.material)

def child_collider(mu, muobj, obj):
    if mu.create_colliders and hasattr(muobj, "collider"):
        if obj.data:
            cobj = create_collider(mu, muobj)
            set_transform(cobj, None)
            mu.collection.objects.link(cobj)
            cobj.parent = obj

def create_object(mu, muobj, parent):
    obj = None
    mesh = None
    name = muobj.transform.name
    xform = None if hasattr(muobj, "bone") else muobj.transform
    if hasattr(muobj, "shared_mesh") and hasattr(muobj, "renderer"):
        mesh = create_mesh(mu, muobj.shared_mesh, name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_data_object(name, mesh, xform)
        attach_material(mesh, muobj.renderer, mu)
        child_collider(mu, muobj, obj)
    elif hasattr(muobj, "skinned_mesh_renderer"):
        smr = muobj.skinned_mesh_renderer
        mesh = create_mesh(mu, smr.mesh, name)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = create_data_object(name, mesh, xform)
        create_vertex_groups(obj, smr.bones, smr.mesh.boneWeights)
        if hasattr(muobj.parent, "armature_obj"):
            create_armature_modifier(obj, muobj.parent)
        attach_material(mesh, smr, mu)
        child_collider(mu, muobj, obj)
    if not obj:
        data = None
        if hasattr(muobj, "light"):
            data = create_light(mu, muobj.light, name)
        elif hasattr(muobj, "camera"):
            data = create_camera(mu, muobj.camera, name)
        if data:
            obj = create_data_object(name, data, xform)
            # Blender points spotlights along local -Z, unity along local +Z
            # which is Blender's +Y, so rotate 90 degrees around local X to
            # go from Unity to Blender
            rot = Quaternion((0.5**0.5,0.5**0.5,0,0))
            obj.rotation_quaternion @= rot
    if hasattr(muobj, "bone"):
        if obj:
            obj.parent = muobj.armature.armature_obj
            obj.parent_type = 'BONE'
            obj.parent_bone = muobj.bone
            obj.matrix_parent_inverse[1][3] = -BONE_LENGTH
        pbone = muobj.armature.armature_obj.pose.bones[muobj.bone]
        pbone.scale = muobj.transform.localScale
    else:
        if not obj:
            if mu.create_colliders and hasattr(muobj, "collider"):
                #print(muobj.transform.name)
                obj = create_collider(mu, muobj)
                set_transform(obj, xform)
            else:
                obj = create_data_object(name, None, xform)
                if name[:5] == "node_":
                    #print(name, name[:5])
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

        obj.parent = parent
    if obj:
        if obj.name not in mu.collection.objects:
            mu.collection.objects.link(obj)
        if hasattr(muobj, "tag_and_layer"):
            obj.muproperties.tag = muobj.tag_and_layer.tag
            obj.muproperties.layer = muobj.tag_and_layer.layer
        muobj.bobj = obj
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
