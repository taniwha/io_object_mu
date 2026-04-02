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
import mathutils
from mathutils import Vector, Quaternion

from ..mu import Mu, MuAnimation, MuRenderer, MuParticles
from ..shader import make_shader
from ..utils import set_transform, create_data_object

from .exception import MuImportError
from .animation import create_action, create_object_paths
from .armature import process_skins
from .armature import is_armature, parent_to_bone
from .camera import create_camera
from .collider import create_collider
from .light import create_light
from .mesh import create_mesh
from .textures import create_textures

def skip_component(mu, muobj, mumesh, name):
    return None

# further filled in by the modules that handle the Mu types
type_handlers = {
    MuAnimation: skip_component,
    MuRenderer: skip_component,
    MuParticles: skip_component
}

def create_protected_data_object(collection, name, data, xform):
    # protect the imported name from blender's duplicate name extension
    name += "∧"
    return create_data_object(collection, name, data, xform)

def create_component_object(collection, component, objname, xform):
    post = None
    if len(component) >= 4:
        post = component[3:4][0]
    name, data, rot = component[:3]
    if name:
        name = ".".join([objname, name])
    else:
        name = objname
    if type(data) == bpy.types.Object: #if type(data) == bpy_types.Object:
        cobj = data
        if xform:
            set_transform(cobj, xform)
        if not cobj.name in collection.objects:
            collection.objects.link(cobj)
    else:
        cobj = create_protected_data_object(collection, name, data, xform)
    if rot:
        cobj.rotation_quaternion @= rot
    if post:
        post[0](cobj, *post[1:])
    return cobj

def create_object(mu, muobj, parent):
    if muobj in mu.imported_objects:
        # The object has already been processed (probably an armature)
        return None
    mu.imported_objects.add(muobj)

    xform = muobj.transform

    component_data = []
    for component in muobj.components:
        if type(component) in type_handlers:
            data = type_handlers[type(component)](mu, muobj, component, xform.name)
            if data:
                component_data.append(data)
        else:
            print(f"unhandled component {component}")

    if hasattr(muobj, "armature_obj") or len(component_data) != 1:
        # empty or multiple components
        obj = None
        if hasattr(muobj, "armature_obj"):
            obj = muobj.armature_obj
            set_transform(obj, muobj.transform)
            if obj.name not in mu.collection.objects:
                mu.collection.objects.link(obj)
        if not obj:
            # if a mesh is present, use it for the main object
            for component in component_data:
                if component[0] == "mesh":
                    component_data.remove(component)
                    component = (None,) + component[1:]
                    obj = create_component_object(mu.collection, component, xform.name, xform)
                    break
        if not obj:
            obj = create_protected_data_object(mu.collection, xform.name, None, xform)
        for component in component_data:
            cobj = create_component_object(mu.collection, component, xform.name, None)
            cobj.parent = obj
    else:
        component = component_data[0]
        component = (None,) + component[1:]
        obj = create_component_object(mu.collection, component, xform.name, xform)
    
    if obj.name not in mu.collection.objects:
        mu.collection.objects.link(obj)

    if not obj.data:
        if xform.name[:5] == "node_":
            # print(name, xform.name[:5])
            obj.empty_display_type = 'SINGLE_ARROW'
            # print(obj.empty_display_type)
            # Blender's empties use the +Z axis for single-arrow
            # display, so that is the most natural orientation for
            # nodes in blender.
            # However, KSP uses the transform's +Z (Unity) axis which
            # is Blender's +Y, so rotate -90 degrees around local X to
            # go from KSP to Blender
            # print(obj.rotation_quaternion)
            rot = Quaternion((0.5**0.5, -(0.5**0.5), 0, 0))
            obj.rotation_quaternion @= rot
            # print(obj.rotation_quaternion)

    muobj.bobj = obj
    if hasattr(muobj, "bone") and hasattr(muobj, "armature"):
        set_transform(obj, None)
        # Ensure armature_obj is set on armature (OPTIONAL)
        if not hasattr(muobj.armature, 'armature_obj'):
            try:
                muobj.armature.armature_obj = obj
            except Exception as e:
                print(f"ERROR: {e}, for armature: {muobj.armature}")
                #FIXME add handle to no attribute 'armature_obj'
        else:
            parent_to_bone(obj, muobj.armature.armature_obj, muobj.bone)
    else:
        obj.parent = parent

    if hasattr(muobj, "tag_and_layer"):
        obj.muproperties.tag = muobj.tag_and_layer.tag
        obj.muproperties.layer = muobj.tag_and_layer.layer

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

def create_armatures(mu):
    def scan_for_skins(mu, obj):
        # prioritize any armatures so their bone objects get consumed
        # however, unity allows for multiple skins to share one armature
        skins = []
        for child in obj.children:
            if is_armature(child):
                skins.append(child)
        if skins:
            process_skins(mu, skins, obj.children)
        for child in obj.children:
            scan_for_skins(mu, child)
    if is_armature(mu.obj):
        process_skins(mu, [mu.obj], [mu.obj])
    else:
        scan_for_skins(mu, mu.obj)

def process_mu(mu, mudir):
    create_textures(mu, mudir)
    create_materials(mu)
    create_object_paths(mu)
    create_armatures(mu)
    mu.imported_objects = set()
    return create_object(mu, mu.obj, None)

def import_mu(collection, filepath, create_colliders, force_armature, force_mesh=False):
    mu = Mu()
    mu.messages = []
    mu.create_colliders = create_colliders
    mu.force_armature = force_armature
    mu.force_mesh = force_mesh
    mu.collection = collection
    if not mu.read(filepath):
        raise MuImportError("Mu", "Unrecognized format: magic %x version %d"
                                  % (mu.magic, mu.version))

    return process_mu(mu, os.path.dirname(filepath)), mu

# Add a handler for MuParticles
def handle_mu_particles(mu, muobj, component, objname):
    # Create a new mesh object to which the particle system will be attached
    part_sys_name = f"{objname}_particles"
    particles_obj = bpy.data.objects.new(part_sys_name, bpy.data.meshes.new(part_sys_name))
    mu.collection.objects.link(particles_obj)
    
    # Create a new particle system
    psys = particles_obj.modifiers.new(name=part_sys_name, type='PARTICLE_SYSTEM').particle_system
    psettings = psys.settings

    # Calculate the magnitude of worldVelocity manually
    world_velocity_magnitude = mathutils.Vector(component.worldVelocity).length

    # Set some example parameters (these should ideally come from the component)
    psettings.count = component.count
    psettings.frame_start = 1
    psettings.frame_end = 200
    psettings.lifetime = component.energy[1]
    psettings.emit_from = 'VOLUME'
    psettings.physics_type = 'NEWTON'
    
    # Velocity settings
    psettings.normal_factor = world_velocity_magnitude

    # Setting other properties from the MuParticles component
    psettings.render_type = 'HALO'
    psettings.particle_size = component.size[1]

    # Mapping other potential settings
    psettings.emit_from = 'VOLUME'
    psettings.render_type = 'HALO'
    psettings.use_emit_random = True
    psettings.lifetime_random = component.energy[0] / component.energy[1]

    return ("particles", particles_obj, None)

# Register the handler
type_handlers[MuParticles] = handle_mu_particles
