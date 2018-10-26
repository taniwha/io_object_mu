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

from ..utils import strip_nnn

from . import attachnode
from . import export

def is_group_root(obj, group):
    print(obj.name)
    while obj.parent:
        obj = obj.parent
        print(obj.name, obj.users_group)
        if group.name not in obj.users_group:
            return False
    return True

def handle_empty(obj, muobj, mu):
    if obj.dupli_group:
        if obj.dupli_type != 'COLLECTION':
            #FIXME flag an error? figure out something else to do?
            return None
        group = obj.dupli_group
        for o in group.objects:
            # while KSP models (part/prop/internal) will have only one root
            # object, grouping might be used for other purposes (eg, greeble)
            # so support multiple group root objects
            if not is_group_root(o, group):
                continue
            #easiest way to deal with dupli_offset is to temporarily shift
            #the object by the offset and then restor the object's location
            loc = o.location
            o.location -= group.dupli_offset
            child = make_obj(mu, o, special, path)
            o.location = loc
            if child:
                muobj.children.append(child)
    name = strip_nnn(obj.name)
    if name[:5] == "node_":
        n = attachnode.AttachNode(obj, mu.inverse)
        mu.nodes.append(n)
        if not n.keep_transform() and not obj.children:
            return None
        muobj.transform.localRotation @= attachnode.rotation_correction
    elif name in ["CoMOffset", "CoPOffset", "CoLOffset"]:
        setattr(mu, name, (mu.inverse @ obj.matrix_world.col[3])[:3])
        if not obj.children:
            return None
    return muobj

type_handlers = {
    type(None): handle_empty
}

export.type_handlers.update(type_handlers)
