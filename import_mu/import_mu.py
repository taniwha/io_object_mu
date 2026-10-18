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
import uuid
from math import pi, sqrt

import bpy
import mathutils
from mathutils import Vector, Quaternion

from ..mu import Mu, MuAnimation, MuRenderer, MuParticles
from ..shader import make_shader
from ..utils import set_transform, create_data_object
from .name_protect import mark_protected_name

from .exception import MuImportError
from .animation import create_action, create_object_paths, finalize_animation_preview
from .armature import process_skins, force_armature_hierarchy
from .armature import is_armature, parent_to_bone
from .camera import create_camera
from .collider import create_collider
from .light import create_light
from .mesh import create_mesh
from .textures import create_textures


def _mu_progress(value=None, text=None, force=False):
    try:
        from .progress_util import mu_tick
        mu_tick(value, text=text, force=force)
    except Exception:
        pass


def _mu_progress_items(index, count, start, end, text=None, every=None):
    try:
        from .progress_util import mu_tick_items
        mu_tick_items(index, count, start, end, text=text, every=every)
    except Exception:
        pass


def _count_mu_nodes(muobj):
    n = 1
    for child in getattr(muobj, "children", None) or []:
        n += _count_mu_nodes(child)
    return n

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
    obj = create_data_object(collection, name, data, xform)
    mark_protected_name(obj)
    return obj

def _is_bindpose_object(obj):
    if not obj or type(getattr(obj, "data", None)) != bpy.types.Armature:
        return False
    n = obj.name
    return n.endswith(".bindPose") or ".bindPose." in n

def _smr_props_from(obj):
    if not obj:
        return None
    try:
        if "mu_smr_rotation" not in obj:
            return None
        return (Vector(obj["mu_smr_location"]),
                Quaternion(obj["mu_smr_rotation"]),
                Vector(obj["mu_smr_scale"]))
    except Exception:
        return None

def _find_smr_props_for_armature(arm_obj):
    """bindPose children of the control armature carry mu_smr_*."""
    if not arm_obj:
        return None
    for o in arm_obj.children:
        props = _smr_props_from(o)
        if props:
            return props
    return None

def _bake_smr_transform(obj, smr_loc, smr_rot, smr_sca):
    """Bake Unity SMR local TRS into obj for viewport; keep mu_unity_* for export."""
    if not obj or obj.get("mu_smr_baked"):
        return
    if obj.name.endswith(".skin") or ".skin." in obj.name:
        return
    try:
        obj["mu_unity_location"] = list(obj.location)
        obj["mu_unity_rotation"] = list(obj.rotation_quaternion)
        obj["mu_unity_scale"] = list(obj.scale)
    except Exception:
        pass
    loc = Vector(obj.location)
    rot = Quaternion(obj.rotation_quaternion)
    sca = Vector(obj.scale)
    obj.rotation_mode = 'QUATERNION'
    obj.scale = Vector((smr_sca.x * sca.x, smr_sca.y * sca.y, smr_sca.z * sca.z))
    obj.rotation_quaternion = smr_rot @ rot
    obj.location = smr_loc + smr_rot @ Vector(
        (loc.x * smr_sca.x, loc.y * smr_sca.y, loc.z * smr_sca.z))
    try:
        obj["mu_smr_baked"] = 1
    except Exception:
        pass

def _object_or_child_is_collider(obj):
    try:
        mp = obj.muproperties
        if mp.collider and mp.collider != 'MU_COL_NONE':
            return True
    except Exception:
        pass
    if obj.type == 'MESH' and "collider" in obj.name.lower():
        return True
    for ch in obj.children:
        try:
            mp = ch.muproperties
            if mp.collider and mp.collider != 'MU_COL_NONE':
                return True
        except Exception:
            pass
        if ch.type == 'MESH' and "collider" in ch.name.lower():
            return True
    return False

def _bake_smr_space_for_object(obj):
    """Apply Unity SMR local TRS to colliders parented under bindPose.

    Bone-parented colliders rely on control-armature rest poses that already
    fold in intermediate SMR nodes (see ``_bone_rest_matrix``).
    """
    if not obj or obj.get("mu_smr_baked"):
        return
    if obj.name.endswith(".skin") or ".skin." in obj.name:
        return
    if _is_bindpose_object(obj):
        return
    if not _object_or_child_is_collider(obj):
        return
    # Only direct (or empty-wrapped) children of bindPose — not bone chains
    p = obj.parent
    if not _is_bindpose_object(p):
        return
    props = _smr_props_from(p)
    if props:
        _bake_smr_transform(obj, *props)

def create_component_object(collection, component, objname, xform):
    post = None
    if len(component) >= 4:
        post = component[3:4][0]
    name, data, rot = component[:3]
    if name:
        name = ".".join([objname, name])
    else:
        name = objname
    if type(data) == bpy.types.Object:
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
    nprog = int(getattr(mu, "_prog_n", 0) or 0)
    if nprog:
        iprog = int(getattr(mu, "_prog_i", 0) or 0)
        _mu_progress_items(iprog, nprog, 55, 88, text="Building objects…")
        mu._prog_i = iprog + 1
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

    if (hasattr(muobj, "bone") and not component_data
            and not getattr(muobj, "force_import", False)):
        # Pose-bone only: still recurse children (non-armature nodes / nested
        # joints otherwise vanish — TriBitDrill hose chains) and attach clips.
        # If this node somehow also hosts armature_obj, keep it in the hierarchy.
        arm_obj = getattr(muobj, "armature_obj", None)
        parent_for_children = parent
        if isinstance(arm_obj, bpy.types.Object):
            set_transform(arm_obj, muobj.transform)
            if arm_obj.name not in mu.collection.objects:
                mu.collection.objects.link(arm_obj)
            arm_obj.parent = parent
            parent_for_children = arm_obj
            muobj.bobj = arm_obj
        for child in muobj.children:
            create_object(mu, child, parent_for_children)
        if hasattr(muobj, "animation"):
            for clip in muobj.animation.clips:
                create_action(mu, muobj.path, clip, host=muobj)
        return arm_obj if isinstance(arm_obj, bpy.types.Object) else None

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
        # bindPose must stay at identity (Matrix_YZ skinning); SMR TRS is
        # stored on the object as mu_smr_* and applied to collider children.
        use_xform = xform
        if (type(component[1]) == bpy.types.Object
                and _is_bindpose_object(component[1])):
            use_xform = None
        obj = create_component_object(
            mu.collection, component, xform.name, use_xform)
    
    if obj.name not in mu.collection.objects:
        mu.collection.objects.link(obj)
    if _is_bindpose_object(obj):
        set_transform(obj, None)

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
    try:
        obj["mu_unity_transform_name"] = str(xform.name or "")
    except Exception:
        pass
    if getattr(muobj, "_light_enabled_default", None) is not None:
        obj["mu_light_enabled"] = float(muobj._light_enabled_default)
    # Attach MuParticles to this GO (Unity-style: same transform as mesh/empty)
    pending = getattr(muobj, "_particles_pending", None) or getattr(muobj, "particles", None)
    if pending is not None:
        _attach_particles_to_object(obj, pending)
        muobj._particles_pending = None
        # FX .mu files often have materials with no MeshRenderer — remember
        # particle-shader materials so export can write them back.
        try:
            import json
            mat_names = []
            for mumat in getattr(mu, "materials", []) or []:
                bmat = getattr(mumat, "material", None)
                sname = getattr(mumat, "shaderName", "") or ""
                if bmat and ("particle" in sname.lower() or "Particle" in sname):
                    mat_names.append(bmat.name)
            if mat_names:
                obj["mu_particle_materials"] = json.dumps(mat_names)
        except Exception:
            pass
        # Defer billboard/swarm until full tree exists (ImpactTransform sibling)
        try:
            obj["mu_fx_attach_pending"] = 1
        except Exception:
            pass
    if hasattr(muobj, "bone") and hasattr(muobj, "armature"):
        set_transform(obj, None)
        arm_obj = getattr(muobj.armature, "armature_obj", None)
        # Only parent to a real Blender armature Object — never assign a
        # component/child object as armature_obj (that broke bone animations).
        if isinstance(arm_obj, bpy.types.Object):
            if obj.data and type(obj.data) == bpy.types.Armature:
                # bindPose (or other armature component on a bone node):
                # object-parent under the control armature, not bone-parent.
                obj.parent = arm_obj
            else:
                parent_to_bone(obj, arm_obj, muobj.bone)
        else:
            print(f"WARNING: armature_obj missing for bone '{muobj.bone}' "
                  f"on '{xform.name}'; parenting to hierarchy instead")
            obj.parent = parent
    else:
        obj.parent = parent

    if hasattr(muobj, "tag_and_layer"):
        obj.muproperties.tag = muobj.tag_and_layer.tag
        obj.muproperties.layer = muobj.tag_and_layer.layer

    for child in muobj.children:
        create_object(mu, child, obj)
    # After children exist: bake SMR space onto collider hosts (turboJet etc.)
    _bake_smr_space_for_object(obj)
    if hasattr(muobj, "animation"):
        for clip in muobj.animation.clips:
            create_action(mu, muobj.path, clip, host=muobj)

    return obj

def create_materials(mu):
    #material info is in the top level object
    mats = list(getattr(mu, "materials", None) or [])
    n = max(len(mats), 1)
    for i, mumat in enumerate(mats):
        _mu_progress_items(i, n, 40, 52, text="Creating materials…")
        mumat.material = make_shader(mumat, mu)

def mark_animated_force_import(mu):
    """Ensure animation targets always get a Blender object when not pose bones."""
    def walk(obj):
        if hasattr(obj, "animation") and obj.animation:
            for clip in getattr(obj.animation, "clips", []) or []:
                for curve in getattr(clip, "curves", []) or []:
                    if not curve.path:
                        mu_path = obj.path
                    else:
                        mu_path = "/".join([obj.path, curve.path])
                    target = mu.object_paths.get(mu_path)
                    if target is not None:
                        # Prefer pose-bone animation when an armature owns the
                        # node; otherwise force an empty so curves have a host.
                        if not hasattr(target, "bone"):
                            target.force_import = True
        for child in obj.children:
            walk(child)
    walk(mu.obj)

def create_armatures(mu):
    if getattr(mu, "force_armature", False):
        force_armature_hierarchy(mu, mu.obj)
        mark_animated_force_import(mu)
        return
    # Collect ALL skinned nodes, then build armatures once with root merging.
    # Per-sibling-group processing left bones with owner=None on complex
    # parts (TriBitDrill / hose chains) and broke animation / reimport.
    all_skins = []
    def collect_skins(obj):
        if is_armature(obj):
            all_skins.append(obj)
        for child in obj.children:
            collect_skins(child)
    collect_skins(mu.obj)
    if all_skins:
        # merge_roots lets bone-climbing cross a skin's own boundary so that
        # multiple SkinnedMeshRenderers sharing one physical joint tree
        # (TriBitDrill: DrillBase/BarsMain/.../HOSE all hang off drill_root)
        # end up on a single combined armature. With only one skin in the
        # whole file there is nothing to unify with, so climbing must stop
        # at that skin's own node — otherwise a plain wrapper GameObject
        # sitting above a single nested SMR (turboJet, turboRamJet: an outer
        # "TurboJet"/"TRJ" node with an inner same-purpose SMR child) gets
        # treated as the armature owner and the SMR node itself is flattened
        # into "just a bone", dropping the wrapper's own local position and
        # duplicating/mis-scaling everything under the SMR on export.
        merge_roots = len(all_skins) > 1
        process_skins(mu, all_skins, [], merge_roots=merge_roots)
    mark_animated_force_import(mu)

def _setup_collection_hierarchy(parent_collection, root_name):
    """Create main(vis, collider) collection hierarchy for an imported model."""
    # Avoid name clashes with existing collections
    base = root_name
    n = 0
    while base in bpy.data.collections or (n and f"{root_name}.{n:03d}" in bpy.data.collections):
        n += 1
        base = f"{root_name}.{n:03d}" if n else root_name
    main = bpy.data.collections.new(base)
    parent_collection.children.link(main)
    vis = bpy.data.collections.new(base + ".vis")
    col = bpy.data.collections.new(base + ".collider")
    main.children.link(vis)
    main.children.link(col)
    return main, vis, col

def _is_collider_obj(obj):
    muprops = getattr(obj, "muproperties", None)
    return bool(muprops and muprops.collider and muprops.collider != 'MU_COL_NONE')

def _relink_object_collections(obj, vis_col, col_col):
    """Put collider objects into .collider, everything else into .vis."""
    for o in list(obj.children) if obj else []:
        _relink_object_collections(o, vis_col, col_col)
    if not obj:
        return
    target = col_col if _is_collider_obj(obj) else vis_col
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    if obj.name not in target.objects:
        target.objects.link(obj)

def process_mu(mu, mudir):
    mu.mudir = mudir
    # Load missing textures from GameData / part.cfg before material build
    _mu_progress(8, text="Resolving dependencies…")
    try:
        from .dependency_resolve import resolve_import_dependencies
        resolve_import_dependencies(mu, mudir)
    except Exception as e:
        print(f"WARNING: dependency resolve: {e}")
    _mu_progress(15, text="Loading textures…", force=True)
    create_textures(mu, mudir)
    _mu_progress(40, text="Creating materials…")
    create_materials(mu)
    _mu_progress(50, text="Creating object paths…")
    create_object_paths(mu)
    # Never absorb the file root into a pose-bone-only skip
    mu.obj.force_import = True
    _mu_progress(54, text="Creating armatures…")
    create_armatures(mu)
    mu.obj.force_import = True
    mu.imported_objects = set()
    try:
        mu._prog_n = _count_mu_nodes(mu.obj)
        mu._prog_i = 0
    except Exception:
        mu._prog_n = 0
        mu._prog_i = 0
    _mu_progress(55, text="Building objects…", force=True)
    root = create_object(mu, mu.obj, None)
    if root is None:
        # Armature-only root: use the control armature Object as import root
        arm_obj = getattr(mu.obj, "armature_obj", None)
        if isinstance(arm_obj, bpy.types.Object):
            root = arm_obj
        else:
            # Last resort: any object created during import
            for o in getattr(mu, "collection", bpy.context.scene.collection).objects:
                if o.parent is None:
                    root = o
                    break
    if root and getattr(mu, "vis_collection", None) and getattr(mu, "collider_collection", None):
        _relink_object_collections(root, mu.vis_collection, mu.collider_collection)
    # Prefer first clip (Deploy) for viewport; don't leave Running as ad.action
    _mu_progress(90, text="Attaching previews…")
    finalize_animation_preview()
    # Particle FX preview after full hierarchy so ImpactTransform tip is findable
    try:
        from .particles_preview import attach_particles_preview
        for o in list(bpy.data.objects):
            if not o.get("mu_fx_attach_pending") and not o.get("mu_particles"):
                continue
            if o.get("mu_fx_attach_pending") or o.get("mu_particles"):
                try:
                    attach_particles_preview(o, mu)
                except Exception as e:
                    print(f"WARNING: particles preview: {e}")
                try:
                    if "mu_fx_attach_pending" in o:
                        del o["mu_fx_attach_pending"]
                except Exception:
                    pass
    except Exception as e:
        print(f"WARNING: particles preview finalize: {e}")
    try:
        if root is not None:
            src = getattr(mu, "source_filepath", None) or ""
            if src:
                root["ksp_mu_path"] = src
            stem = getattr(mu, "filepath_stem", None) or ""
            if stem:
                root["ksp_mu_name"] = stem
    except Exception:
        pass
    try:
        from .cfg_preview import attach_cfg_viewport_markers
        # Prefer on-disk basename for cfg lookup — mu.read() overwrites mu.name
        # with the Unity transform (Size1.5_…) which breaks underscore cfg match.
        filepath_stem = getattr(mu, "filepath_stem", None) or ""
        muname = filepath_stem or getattr(mu, "name", None) or ""
        if not muname and mudir:
            muname = os.path.basename(mudir.rstrip("\\/"))
        attach_cfg_viewport_markers(
            root, mudir, muname, filepath_stem=filepath_stem or None
        )
    except Exception as e:
        print(f"WARNING: cfg viewport markers: {e}")
    try:
        from .sound_preview import attach_cfg_animation_sounds
        filepath_stem = getattr(mu, "filepath_stem", None) or ""
        muname = filepath_stem or getattr(mu, "name", None) or ""
        if not muname and mudir:
            muname = os.path.basename(mudir.rstrip("\\/"))
        attach_cfg_animation_sounds(
            root, mudir, muname, filepath_stem=filepath_stem or None
        )
    except Exception as e:
        print(f"WARNING: animation sound preview: {e}")
    # Flare even when no cfg was found (cfg_preview already runs attach when cfg exists)
    try:
        from .flare_preview import attach_flare_preview, _iter_meshes_under
        if root is not None and not any(
            o.get("mu_light_flare") for o in _iter_meshes_under(root)
        ):
            attach_flare_preview(root, None)
    except Exception as e:
        print(f"WARNING: flare preview: {e}")
    return root

def _tag_import_objects(mu):
    """Tag every Blender object belonging to this .mu import.
    Do not rely on Blender parenting here. A single .mu import can result
    in multiple top-level Blender objects, armature helpers, generated
    objects, animation stubs, etc.
    The unique ID lets the MU browser treat all of them as one model.
    """
    import_id = str(getattr(mu, "import_id", "") or "")
    if not import_id:
        return
    collections = []
    for attr in ("main_collection", "vis_collection", "collider_collection", "collection"):
        col = getattr(mu, attr, None)
        if col is not None and col not in collections:
            collections.append(col)
    seen = set()

    def tag_collection(col):
        if col is None:
            return
        for obj in list(col.objects):
            ptr = obj.as_pointer()
            if ptr in seen:
                continue
            seen.add(ptr)
            try:
                obj["mu_import_id"] = import_id
                obj["mu_import_source"] = str(getattr(mu, "filepath_stem", "")or getattr(mu, "name", "")or "")
                obj["mu_import_path"] = str(getattr(mu, "filepath", "")or "")
                mark_protected_name(obj)
            except Exception:
                pass
            # Important: also follow Blender parenting.
            for child in obj.children:
                tag_object(child)
        for child_col in col.children:
            tag_collection(child_col)
    def tag_object(obj):
        if obj is None:
            return
        ptr = obj.as_pointer()
        if ptr in seen:
            return
        seen.add(ptr)
        try:
            obj["mu_import_id"] = import_id
            obj["mu_import_source"] = str(getattr(mu, "filepath_stem", "")or getattr(mu, "name", "")or "")
            obj["mu_import_path"] = str(getattr(mu, "filepath", "")or "")
            mark_protected_name(obj)
        except Exception:
            pass
        for child in obj.children:
            tag_object(child)
    for col in collections:
        tag_collection(col)
    # Material clips are not Blender objects — tag materials used by this import.
    mat_seen = set()
    for obj in bpy.data.objects:
        try:
            if str(obj.get("mu_import_id", "")) != import_id:
                continue
        except Exception:
            continue
        try:
            slots = getattr(obj, "material_slots", []) or []
        except Exception:
            slots = []
        for slot in slots:
            mat = getattr(slot, "material", None)
            if mat is None:
                continue
            try:
                ptr = mat.as_pointer()
            except Exception:
                ptr = id(mat)
            if ptr in mat_seen:
                continue
            mat_seen.add(ptr)
            try:
                mat["mu_import_id"] = import_id
                mat["mu_import_source"] = str(
                    getattr(mu, "filepath_stem", "") or getattr(mu, "name", "") or "")
                mat["mu_import_path"] = str(getattr(mu, "filepath", "") or "")
            except Exception:
                pass

def import_mu(collection, filepath, create_colliders, force_armature, force_mesh=False):
    mu = Mu()
    mu.messages = []
    # Unique ID for this particular .mu import session.
    # Every Blender object created from this file receives the same ID.
    # This is intentionally different from the filename/path so two
    # simultaneously imported copies of the same .mu stay independent.
    mu.import_id = uuid.uuid4().hex
    mu.create_colliders = create_colliders
    mu.force_armature = force_armature
    mu.force_mesh = force_mesh
    root_name = os.path.splitext(os.path.basename(filepath))[0]
    mu.name = root_name
    # Survives mu.read() overwriting mu.name with the embedded transform name.
    mu.filepath_stem = root_name
    mu.source_filepath = os.path.abspath(filepath)
    main_col, vis_col, col_col = _setup_collection_hierarchy(collection, root_name)
    mu.collection = vis_col  # default link target during import
    mu.main_collection = main_col
    mu.vis_collection = vis_col
    mu.collider_collection = col_col
    _mu_progress(2, text="Reading .mu…")
    if not mu.read(filepath):
        raise MuImportError("Mu", "Unrecognized format: magic %x version %d"
                                  % (mu.magic, mu.version))

    _mu_progress(6, text="Processing model…", force=True)
    root = process_mu(mu, os.path.dirname(filepath))
    # Tag the COMPLETE Blender representation of this .mu.
    # This must happen after process_mu(), because armatures, animation
    # stubs and other generated objects may not exist before that point.
    _tag_import_objects(mu)
    try:
        if root is not None:
            root["ksp_mu_path"] = os.path.abspath(filepath)
            root["ksp_mu_name"] = root_name
            root["mu_import_id"] = str(mu.import_id)
    except Exception:
        pass
    # Summary needs mu_import_id on objects — must run after _tag_import_objects.
    try:
        from .animation import print_mu_animation_summary
        print_mu_animation_summary(force=True)
    except Exception as e:
        print("WARN: MU anim summary failed: %s" % (e,))
    _mu_progress(99, text="Import complete")
    return root, mu

def _serialize_mu_particles(component):
    """Pack MuParticles fields into a JSON-friendly dict for round-trip."""
    def vec(v):
        return [float(x) for x in v]
    return {
        "emit": int(component.emit),
        "shape": int(component.shape),
        "shape3d": vec(component.shape3d),
        "shape2d": list(component.shape2d),
        "shape1d": float(component.shape1d),
        "color": list(component.color),
        "useUorldSpace": int(component.useUorldSpace),
        "size": list(component.size),
        "energy": list(component.energy),
        "emission": list(component.emission),
        "worldVelocity": vec(component.worldVelocity),
        "localVelocity": vec(component.localVelocity),
        "rndVelocity": vec(component.rndVelocity),
        "emitterVelocityScale": float(component.emitterVelocityScale),
        "angularVelocity": float(component.angularVelocity),
        "rndAngularVelocity": float(component.rndAngularVelocity),
        "rndRotation": int(component.rndRotation),
        "doesAnimateColor": int(component.doesAnimateColor),
        "colorAnimation": [list(c) for c in component.colorAnimation],
        "worldRotationAxis": vec(component.worldRotationAxis),
        "localRotationAxis": vec(component.localRotationAxis),
        "sizeGrow": float(component.sizeGrow),
        "rndForce": vec(component.rndForce),
        "force": vec(component.force),
        "damping": float(component.damping),
        "castShadows": int(component.castShadows),
        "recieveShadows": int(component.recieveShadows),
        "lengthScale": float(component.lengthScale),
        "velocityScale": float(component.velocityScale),
        "maxParticleSize": float(component.maxParticleSize),
        "particleRenderMode": int(component.particleRenderMode),
        "uvAnimation": list(component.uvAnimation),
        "count": int(component.count),
    }

def _attach_particles_to_object(obj, component):
    """Store full MuParticles payload on the Blender object for lossless export."""
    import json
    obj["mu_particles"] = json.dumps(_serialize_mu_particles(component))

# Add a handler for MuParticles — keep data on the same GameObject as Unity/KSP
# (no extra *_particles child). Export reads the ID property and writes ET_PARTICLES.
def handle_mu_particles(mu, muobj, component, objname):
    # Component already on muobj.particles from MuObject.read; mark for attach
    # after the Blender object is created in create_object().
    muobj._particles_pending = component
    # Ensure a Blender object exists even for bone-only / empty emitters
    muobj.force_import = True
    return None

# Register the handler
type_handlers[MuParticles] = handle_mu_particles
