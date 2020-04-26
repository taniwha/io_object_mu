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
from mathutils import Vector

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

    #FIXME horible hack until I figure out how to get a render mode depsgraph
    modifiers = collect_modifiers(obj)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    skin_mesh = obj.evaluated_get(depsgraph).to_mesh()
    skin_vol = calcVolume(skin_mesh);
    obj.to_mesh_clear()
    for mod in modifiers:
        mod.show_viewport = False
    depsgraph.update()
    ext_mesh = obj.evaluated_get(depsgraph).to_mesh()
    ext_vol = calcVolume(ext_mesh)
    obj.to_mesh_clear()
    for mod in modifiers:
        mod.show_viewport = True

    return skin_vol, ext_vol

def model_volume(obj):
    svols = []
    evols = []
    def group(g):
        for o in g.objects:
            recurse(o)
        for c in g.children:
            group(c)
    def recurse(o):
        v = obj_volume(o)
        svols.append(v[0])
        evols.append(v[1])
        for c in o.children:
            recurse(c)
        if o.instance_collection and o.instance_type == 'COLLECTION':
            group(o.instance_collection)
    recurse(obj)
    skinvol = 0
    extvol = 0
    for s in sorted(svols, key=abs):
        skinvol += s
    for e in sorted(evols, key=abs):
        extvol += e
    return skinvol, extvol

def find_com(objects):
    origin = Vector((0, 0, 0))
    base_pos = objects[0].matrix_world @ origin
    weighted_x = [None] * len(objects)
    weighted_y = [None] * len(objects)
    weighted_z = [None] * len(objects)
    vols = [None] * len(objects)
    for i, obj in enumerate(objects):
        pos = obj.matrix_world @ origin - base_pos
        if obj.instance_collection and obj.instance_type == 'COLLECTION':
            vol = model_volume(obj)[0]
        elif obj.data and type(obj.data) == bpy.types.Mesh:
            vol = obj_volume(obj)[0]
        else:
            vol = 0
        wpos = pos * vol
        weighted_x[i] = wpos.x
        weighted_y[i] = wpos.y
        weighted_z[i] = wpos.z
        vols[i] = vol
    vol = 0
    x = 0
    y = 0
    z = 0
    for v in sorted(vols, key=abs):
        vol += v
    for c in sorted(weighted_x, key=abs):
        x += c
    for c in sorted(weighted_y, key=abs):
        y += c
    for c in sorted(weighted_z, key=abs):
        z += c
    pos = Vector((x, y, z))
    if vol > 0:
        pos /= vol
    print((x,y,z),vol,pos,base_pos)
    return pos + base_pos
