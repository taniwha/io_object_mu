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

from ..utils import collect_modifiers

def calcVolume(mesh):
    terms=[]
    for face in mesh.polygons:
        a = mesh.vertices[face.vertices[0]].co
        b = mesh.vertices[face.vertices[1]].co
        for i in range(2, len(face.vertices)):
            c = mesh.vertices[face.vertices[i]].co
            vp =  a.y*b.z*c.x + a.z*b.x*c.y + a.x*b.y*c.z
            vm = -a.z*b.y*c.x - a.x*b.z*c.y - a.y*b.x*c.z
            terms.extend([vp, vm])
            b = c
    vol = 0
    for t in sorted(terms, key=abs):
        vol += t
    return vol / 6

def obj_volume(obj):
    if type(obj.data) != bpy.types.Mesh:
        return 0, 0
    if obj.muproperties.collider and obj.muproperties.collider != 'MU_COL_NONE':
        return 0, 0
    #FIXME skin_mesh = obj.to_mesh(bpy.context.scene, True, 'PREVIEW')
    #FIXME ext_mesh = obj.to_mesh(bpy.context.scene, True, 'RENDER')

    #FIXME horible hack to work around blender 2.8 not (yet) allowing control
    # over render/preview when converting an object to a mesh
    modifiers = collect_modifiers(obj)
    skin_mesh = obj.to_mesh(bpy.context.depsgraph, True)
    for mod in modifiers:
        mod.show_viewport = False
    ext_mesh = obj.to_mesh(bpy.context.depsgraph, True)
    for mod in modifiers:
        mod.show_viewport = True

    return calcVolume(skin_mesh), calcVolume(ext_mesh)
    return 0, 0

def model_volume(obj):
    svols = []
    evols = []
    def recurse(o):
        v = obj_volume(o)
        svols.append(v[0])
        evols.append(v[1])
        for c in o.children:
            recurse(c)
    recurse(obj)
    skinvol = 0
    extvol = 0
    for s in sorted(svols, key=abs):
        skinvol += s
    for e in sorted(evols, key=abs):
        extvol += e
    return skinvol, extvol
