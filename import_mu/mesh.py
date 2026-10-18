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
import bmesh

from ..mu import MuMesh, MuSkinnedMeshRenderer
from ..utils import create_data_object

from .armature import create_vertex_groups, create_armature_modifier
from .armature import create_bindPose

def attach_material(mesh, renderer, mu):
    """Attach all renderer material slots (one per submesh when present)."""
    if not mu.materials or not getattr(renderer, "materials", None):
        return
    for mid in renderer.materials:
        try:
            mid = int(mid)
        except Exception:
            continue
        if mid < 0 or mid >= len(mu.materials):
            continue
        mumat = mu.materials[mid]
        bmat = getattr(mumat, "material", None)
        if bmat:
            mesh.materials.append(bmat)

def create_uvs(mu, uvs, mesh, name):
    uv_layer = mesh.uv_layers.new(name=name).data
    for i, loop in enumerate(mesh.loops):
        uv_layer[i].uv = uvs[loop.vertex_index]

def create_normals(mu, normals, mesh):
    custom_normals = [None] * len(mesh.loops)
    for i, loop in enumerate(mesh.loops):
        custom_normals[i] = normals[loop.vertex_index]
    mesh.normals_split_custom_set(custom_normals)
    if hasattr(mesh, "use_auto_smooth"):
        # From blender 4.1 release notes:
        #  use_auto_smooth is removed. Face corner normals are now used
        #  automatically if there are mixed smooth vs. not smooth tags.
        #  Meshes now always use custom normals if they exist.
        mesh.use_auto_smooth = True

def create_colors(mu, colors, mesh):
    # Always use "colors" so ShaderNodeVertexColor.layer_name matches.
    # Blender 5 returns black for a missing layer; MainColor does V*C*T so a
    # mismatched name (e.g. shader "∧default" vs mesh "colors") blacks out albedo.
    # Synthetic white (no MU vertex colors) is tagged so export can skip it.
    if not mesh.color_attributes:
        mesh.color_attributes.new("colors", 'FLOAT_COLOR', 'POINT')
    color_layer = mesh.color_attributes.active_color
    use_white = not colors
    if colors:
        # Near-black VCols (common docking / airlock-style data) multiply
        # MainColor albedo to ~0 — treat as unused and use synthetic white.
        try:
            n = min(len(colors), 256)
            acc = 0.0
            for i in range(n):
                c = colors[i]
                acc += (float(c[0]) + float(c[1]) + float(c[2])) / 3.0
            use_white = (acc / max(1, n)) < 0.02
        except Exception:
            use_white = False
    if colors and not use_white:
        for i, c in enumerate(colors):
            color_layer.data[i].color = c
        if "mu_synthetic_vcol" in mesh:
            del mesh["mu_synthetic_vcol"]
    else:
        for i in range(len(color_layer.data)):
            color_layer.data[i].color = (1, 1, 1, 1)
        mesh["mu_synthetic_vcol"] = 1

def create_tangents(mumesh, mesh):
    """Store Mu per-vertex tangents (xyzw) for round-trip / normal mapping."""
    tangents = getattr(mumesh, "tangents", None) or []
    if not tangents or len(tangents) != len(mumesh.verts):
        return
    # FLOAT_COLOR POINT: rgb = tangent xyz, a = handedness (bitangent sign)
    if "mu_tangent" in mesh.attributes:
        try:
            mesh.attributes.remove(mesh.attributes["mu_tangent"])
        except Exception:
            pass
    attr = mesh.attributes.new("mu_tangent", 'FLOAT_COLOR', 'POINT')
    for i, t in enumerate(tangents):
        try:
            x, y, z = float(t[0]), float(t[1]), float(t[2])
            w = float(t[3]) if len(t) > 3 else 1.0
        except Exception:
            x = y = z = 0.0
            w = 1.0
        attr.data[i].color = (x, y, z, w)
    mesh["mu_has_tangents"] = 1

def create_mesh(mu, mumesh, name):
    mesh = bpy.data.meshes.new(name)
    faces = []
    face_mat = []
    for smi, sm in enumerate(mumesh.submeshes):
        for face in sm:
            faces.append(face)
            face_mat.append(smi)
    mesh.from_pydata(mumesh.verts, [], faces)
    # Submesh index → material slot (renderer.materials[i])
    for i, poly in enumerate(mesh.polygons):
        if i < len(face_mat):
            poly.material_index = face_mat[i]
    if mumesh.uvs:
        create_uvs(mu, mumesh.uvs, mesh, "UVMap")
    if mumesh.uv2s:
        create_uvs(mu, mumesh.uv2s, mesh, "UVMap2")
    if mumesh.normals:
        create_normals(mu, mumesh.normals, mesh)
    create_colors(mu, mumesh.colors, mesh)
    create_tangents(mumesh, mesh)
    return mesh

def mesh_post(obj, renderer):
    obj.muproperties.castShadows = renderer.castShadows
    obj.muproperties.receiveShadows = renderer.receiveShadows
    # Viewport EEVEE shadows follow KSP renderer flags — except additive /
    # translucent (ModuleLight Flare): Blender 5 ignores cfg shadow_method=NONE,
    # and use_transparent_shadow=False + visible_shadow stamps opaque silhouettes
    # onto part textures (gear lamp halo cards).
    cast = bool(renderer.castShadows)
    try:
        from .flare_preview import mesh_should_skip_viewport_shadows
        if mesh_should_skip_viewport_shadows(obj, renderer):
            cast = False
    except Exception:
        pass
    try:
        obj.visible_shadow = cast
    except Exception:
        pass
    try:
        # receive: Blender has no per-object receive flag in 5.x; material-level
        # is handled in shader tune when receiveShadows is False.
        obj["mu_receive_shadows"] = 1 if renderer.receiveShadows else 0
    except Exception:
        pass

def create_mesh_component(mu, muobj, mumesh, name):
    if not mu.force_mesh and not hasattr(muobj, "renderer"):
        return None
    mesh = create_mesh (mu, mumesh, name)
    if hasattr(muobj, "renderer"):
        attach_material(mesh, muobj.renderer, mu)
        return "mesh", mesh, None, (mesh_post, muobj.renderer)
    else:
        return "mesh", mesh, None

def create_skinned_mesh_component(mu, muobj, skin, name):
    create_bindPose(mu, muobj, skin)
    # bindPose stays at identity so Matrix_YZ skinning stays correct, but the
    # Unity SMR local transform (often -90° X) must be remembered for:
    #   • export (restore on the SMR node)
    #   • non-skin children (mesh colliders) so they match the skinned mesh
    bp = skin.bindPose_obj
    xform = muobj.transform
    try:
        bp["mu_smr_location"] = list(xform.localPosition)
        bp["mu_smr_rotation"] = list(xform.localRotation)
        bp["mu_smr_scale"] = list(xform.localScale)
    except Exception:
        pass
    mesh = create_mesh(mu, skin.mesh, name)
    obj = create_data_object(mu.collection, name + ".skin", mesh, None)
    create_vertex_groups(obj, skin.bones, skin.mesh.boneWeights)
    attach_material(mesh, skin, mu)
    obj.parent = bp
    create_armature_modifier(obj, "BindPose", bp)
    return "armature", bp, None
    #return None

type_handlers = {
    MuMesh: create_mesh_component,
    MuSkinnedMeshRenderer: create_skinned_mesh_component
}
