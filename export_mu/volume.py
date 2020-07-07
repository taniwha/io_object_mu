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

def sortedSum(terms):
    sum = 0
    for t in sorted(terms, key=abs):
        sum += t
    return sum

def calcVolumeCentroid(mesh):
    terms=[]
    terms_x = []
    terms_y = []
    terms_z = []
    num_tetras = 0
    for face in mesh.polygons:
        a = mesh.vertices[face.vertices[0]].co
        b = mesh.vertices[face.vertices[1]].co
        for i in range(2, len(face.vertices)):
            c = mesh.vertices[face.vertices[i]].co
            vp = [ a.y*b.z*c.x,  a.z*b.x*c.y,  a.x*b.y*c.z]
            vm = [-a.z*b.y*c.x, -a.x*b.z*c.y, -a.y*b.x*c.z]
            terms.extend(vp)
            terms.extend(vm)
            terms_x.extend([a.x * vp[0], b.x * vp[0], c.x * vp[0]])
            terms_y.extend([a.y * vp[0], b.y * vp[0], c.y * vp[0]])
            terms_z.extend([a.z * vp[0], b.z * vp[0], c.z * vp[0]])
            terms_x.extend([a.x * vp[1], b.x * vp[1], c.x * vp[1]])
            terms_y.extend([a.y * vp[1], b.y * vp[1], c.y * vp[1]])
            terms_z.extend([a.z * vp[1], b.z * vp[1], c.z * vp[1]])
            terms_x.extend([a.x * vp[2], b.x * vp[2], c.x * vp[2]])
            terms_y.extend([a.y * vp[2], b.y * vp[2], c.y * vp[2]])
            terms_z.extend([a.z * vp[2], b.z * vp[2], c.z * vp[2]])
            terms_x.extend([a.x * vm[0], b.x * vm[0], c.x * vm[0]])
            terms_y.extend([a.y * vm[0], b.y * vm[0], c.y * vm[0]])
            terms_z.extend([a.z * vm[0], b.z * vm[0], c.z * vm[0]])
            terms_x.extend([a.x * vm[1], b.x * vm[1], c.x * vm[1]])
            terms_y.extend([a.y * vm[1], b.y * vm[1], c.y * vm[1]])
            terms_z.extend([a.z * vm[1], b.z * vm[1], c.z * vm[1]])
            terms_x.extend([a.x * vm[2], b.x * vm[2], c.x * vm[2]])
            terms_y.extend([a.y * vm[2], b.y * vm[2], c.y * vm[2]])
            terms_z.extend([a.z * vm[2], b.z * vm[2], c.z * vm[2]])
            b = c
            num_tetras += 1
    vol = sortedSum(terms) / 6
    c_x = sortedSum(terms_x)
    c_y = sortedSum(terms_y)
    c_z = sortedSum(terms_z)
    cent = Vector((c_x, c_y, c_z)) / (6 * 4 * vol)

    return vol, cent

def obj_volume_centroid(obj):
    origin = Vector((0, 0, 0))
    if type(obj.data) != bpy.types.Mesh:
        return (0, 0), (origin, origin)
    if obj.muproperties.collider and obj.muproperties.collider != 'MU_COL_NONE':
        return (0, 0), (origin, origin)
    #FIXME skin_mesh = obj.to_mesh(bpy.context.scene, True, 'PREVIEW')
    #FIXME ext_mesh = obj.to_mesh(bpy.context.scene, True, 'RENDER')

    #FIXME horible hack until I figure out how to get a render mode depsgraph
    modifiers = collect_modifiers(obj)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    skin_mesh = obj.evaluated_get(depsgraph).to_mesh()
    skin_vol, skin_cent = calcVolumeCentroid(skin_mesh)
    obj.to_mesh_clear()
    for mod in modifiers:
        mod.show_viewport = False
    depsgraph.update()
    ext_mesh = obj.evaluated_get(depsgraph).to_mesh()
    ext_vol, ext_cent = calcVolumeCentroid(ext_mesh)
    obj.to_mesh_clear()
    for mod in modifiers:
        mod.show_viewport = True

    return (skin_vol, ext_vol), (skin_cent, ext_cent)

def obj_volume(obj):
    return obj_volume_centroid(obj)[0]

def model_volume_centroid(obj):
    origin = Vector((0, 0, 0))
    base_pos = obj.matrix_world @ origin
    svols = []
    evols = []
    scents_x = []
    scents_y = []
    scents_z = []
    ecents_x = []
    ecents_y = []
    ecents_z = []
    def group(g):
        for o in g.objects:
            recurse(o)
        for c in g.children:
            group(c)
    def recurse(o):
        pos = o.matrix_world @ origin
        v, c = obj_volume_centroid(o)
        svols.append(v[0])
        evols.append(v[1])
        sc = c[0] + pos
        ec = c[1] + pos
        scents_x.append(v[0]*sc.x)
        scents_y.append(v[0]*sc.y)
        scents_z.append(v[0]*sc.z)
        ecents_x.append(v[1]*ec.x)
        ecents_y.append(v[1]*ec.y)
        ecents_z.append(v[1]*ec.z)
        if (o.muproperties.collider
            and o.muproperties.collider != 'MU_COL_NONE'):
            return
        for c in o.children:
            recurse(c)
        if o.instance_collection and o.instance_type == 'COLLECTION':
            group(o.instance_collection)
    recurse(obj)
    skinvol = sortedSum(svols)
    extvol = sortedSum(evols)
    sc_x = sortedSum(scents_x)
    sc_y = sortedSum(scents_y)
    sc_z = sortedSum(scents_z)
    ec_x = sortedSum(ecents_x)
    ec_y = sortedSum(ecents_y)
    ec_z = sortedSum(ecents_z)
    skincent = Vector((sc_x, sc_y, sc_z))
    if skinvol != 0:
        skincent /= skinvol
    extcent = Vector((ec_x, ec_y, ec_z))
    if extvol != 0:
        extcent /= extvol
    return (skinvol, extvol), (skincent - base_pos, extcent - base_pos)

def model_volume(obj):
    return model_volume_centroid(obj)[0]

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
            (svol, evol), (scent, escent) = model_volume_centroid(obj)
        elif obj.data and type(obj.data) == bpy.types.Mesh:
            (svol, evol), (scent, escent) = obj_volume_centroid(obj)
        else:
            svol = 0
            scent = origin
        wpos = (pos + scent) * svol
        weighted_x[i] = wpos.x
        weighted_y[i] = wpos.y
        weighted_z[i] = wpos.z
        vols[i] = svol
    vol = sortedSum(vols)
    x = sortedSum(weighted_x)
    y = sortedSum(weighted_y)
    z = sortedSum(weighted_z)
    pos = Vector((x, y, z))
    if vol != 0:
        pos /= vol
    return pos + base_pos
