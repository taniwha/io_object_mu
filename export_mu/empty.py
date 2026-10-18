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

import json

from ..utils import strip_nnn
from ..mu import MuParticles

from . import attachnode
from . import export
from .export_util import is_collider

def _particles_from_id_prop(obj):
    raw = obj.get("mu_particles") if hasattr(obj, "get") else None
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        return None
    p = MuParticles()
    for k, v in data.items():
        setattr(p, k, v)
    return p

def is_group_root(obj, objects):
    if not obj.parent:
        return True
    return obj.parent.name not in objects

def collect_objects(collection):
    objects = {}
    def collect(col):
        for o in col.objects:
            objects[o.name] = o
        for c in col.children:
            collect(c)
    collect(collection)
    return objects

def export_collection(obj, muobj, mu):
    saved_exported_objects = set(mu.exported_objects)
    group = obj.instance_collection
    objects = collect_objects(group)
    group_objects = []
    for n in objects:
        o = objects[n]
        # while KSP models (part/prop/internal) will have only one root
        # object, grouping might be used for other purposes (eg, greeble)
        # so support multiple group root objects
        if o.hide_render or not is_group_root(o, objects):
            continue
        group_objects.append(o)
    if len(group_objects) == 1:
        # there's only one object, so export that directly rather than the
        # collection instance acting as a middle-man (one less game object
        # in the hierarchy)
        xform = (obj.parent, obj.matrix_local)
        muobj = export.make_obj(mu, group_objects[0], mu.path, xform)
    else:
        for o in group_objects:
            child = export.make_obj(mu, o, mu.path)
            if child:
                muobj.children.append(child)
    mu.exported_objects = saved_exported_objects
    return muobj

def handle_empty(obj, muobj, mu):
    if obj.instance_collection:
        if obj.instance_type != 'COLLECTION':
            # Non-collection instance types are not exported as hierarchies.
            return None
        # Collider gizmos are COLLECTION instances whose only purpose is a
        # viewport mesh ("mesh:Name"). Exporting that collection replaces the
        # real hierarchy (Base/Display/...) and orphans animation hosts.
        coll = obj.instance_collection
        is_col_gizmo = is_collider(obj) or any(
            o.name.startswith("mesh:") for o in coll.objects
        )
        if is_col_gizmo:
            return muobj
        return export_collection(obj, muobj, mu)
    # Particles are attached in make_obj_core (any object type). Here only
    # skip Blender-only preview children if present.
    for child in obj.children:
        if (".preview" in child.name or ".fx_preview" in child.name
                or ".fx_emitter" in child.name or ".cfg_preview" in child.name
                or child.get("mu_fx_preview")):
            mu.exported_objects.add(child)
    name = strip_nnn(obj.name)
    if name[:5] == "node_":
        n = attachnode.AttachNode(obj, mu.inverse)
        mu.nodes.append(n)
        if not n.keep_transform() and not obj.children:
            return None
        muobj.transform.localRotation @= attachnode.rotation_correction
    elif name == "thrustTransform":
        # Only for Blender-authored empties (SINGLE_ARROW). Imported KSP
        # thrustTransforms already store Unity localRotation — applying the
        # +90° X correction again rotates the nozzle ~90° on round-trip.
        # cfg_preview also sets SINGLE_ARROW on imported thrustTransforms for
        # viewport arrows — detect imports via ∧ / mu_unity_* / children.
        is_imported = (
            "\u2227" in (obj.name or "")
            or "mu_unity_rotation" in obj
            or bool(obj.children)
        )
        if (getattr(obj, "empty_display_type", "") == "SINGLE_ARROW"
                and not is_imported):
            muobj.transform.localRotation @= attachnode.rotation_correction
    elif name in ["CoMOffset", "CoPOffset", "CoLOffset"]:
        setattr(mu, name, (mu.inverse @ obj.matrix_world.col[3])[:3])
        if not obj.children:
            return None
    return muobj

type_handlers = {
    type(None): handle_empty
}
