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
from mathutils import Matrix, Vector
from math import sqrt

from .. import properties
from ..quickhull.convex_hull import quickhull
from ..utils.solver import solve_cubic
from .seb import smalest_enclosing_ball

def _swap_rows(mat, r1, r2):
    mat[r1], mat[r2] = Vector(mat[r2]), Vector(mat[r1])

def _canonicalize_matrix(mat):
    # ensure all vectors are cannonical (aligned with +ve axis)
    if mat[0][0] < 0:
        mat[0] = -mat[0]
    if mat[1][1] < 0:
        mat[1] = -mat[1]
    if mat[2][2] < 0:
        mat[2] = -mat[2]

def equal(a, b):
    return abs(a - b) < 1e-5

def swap_rows(mat, r1, r2):
    t = Vector(mat[r1])
    mat[r1] = mat[2]
    mat[2] = t

def row_echelon(mat):
    if abs(mat[0][0]) < abs(mat[1][0]):
        swap_rows(mat, 0, 1)
    if abs(mat[0][0]) < abs(mat[2][0]):
        swap_rows(mat, 0, 2)
    mat[0] /= mat[0][0]
    mat[1] -= mat[1][0] * mat[0]
    mat[2] -= mat[2][0] * mat[0]
    if abs(mat[1][1]) < abs(mat[2][1]):
        swap_rows(mat, 1, 2)
    if equal(mat[1][1], 0):
        mat[1][1] = 0
        if equal(mat[1][2], 0):
            mat[1][1] = 0
        else:
            mat[1] /= mat[1][2]
    else:
        mat[1] /= mat[1][1]
    mat[2] -= mat[2][1] * mat[1]
    # ensure rows that are supposed to be 0 are actually 0 ("fixes" -0.0)
    mat[1][0] = 0
    mat[2][0] = 0
    mat[2][1] = 0
    if equal(mat[2][2], 0):
        mat[2][2] = 0
    else:
        mat[0][2] = 0
        mat[1][2] = 0
    if not equal(mat[1][1], 0):
        mat[0] -= mat[0][1] * mat[1]
        mat[0][1] = 0

def find_nullspace(mat):
    """Fiond the nullspace vectors of the privoded row reduced echelon form
    3x3 matrix. NOTE: returns an empty list for the trivial nullspace"""
    pivots = []
    for i in range(3):
        if 1 in mat[i]:
            pivots.append(tuple(mat[i]).index(1))
        else:
            #hit a 0 row: all further rows should be 0
            break
    nullspace = []
    I = Matrix.Identity(3)
    for i in range(3):
        if i in pivots:
            continue
        if not mat.col[i]:
            nullspace.append(I[i])
        v = -I[i]
        for j in range(i):
            if j not in pivots:
                continue
            v += mat.col[i] * mat.col[j]
        nullspace.append(v)
    return nullspace

def _eigen_vectors(mat):
    """Return the eigen vectors as a rotation matrix.
    Note that mat is assumed to be symmetric
    """
    a = -1
    b = mat[0][0] + mat[1][1] + mat[2][2]
    c = (mat[0][1]**2 + mat[0][2]**2 + mat[1][2]**2
         - mat[0][0] * mat[2][2] - mat[0][0] * mat[1][1]
         - mat[1][1] * mat[2][2])
    d = (mat[0][0] * mat[1][1] * mat[2][2]
         + 2 * mat[0][1] * mat[0][2] * mat[1][2]
         - mat[0][0] * mat[1][2]**2 - mat[1][1] * mat[0][2]**2
         - mat[2][2] * mat[0][1]**2)
    L = solve_cubic(a, b, c, d)
    L = [l.real for l in L]
    L.sort(reverse=True)
    #print(L)
    if equal(L[0], L[2]) and equal(L[0], L[2]):
        # three repeated eigenvalues so any basis is good, so go for unrotated
        return Matrix.Identity(3)
    if equal(L[0], L[1]):
        # two repeated eigenvalues, but they come first. make them last
        #print("L[0] and L[1] repeated")
        L = L[2:3] + L[0:2]
    if equal(L[1], L[2]):
        # two repeated eigenvalues
        #print("L[1] and L[2] repeated")
        I = Matrix.Identity(3)
        Aa = mat - L[0] * I
        Ab = mat - L[1] * I
        row_echelon(Aa)
        nullspace = find_nullspace(Aa)
        row_echelon(Ab)
        nullspace += find_nullspace(Ab)
        nullspace[2] -= (nullspace[2] @ nullspace[1]) * nullspace[1] / (nullspace[1] @ nullspace[1])
        nullspace = [v.normalized() for v in nullspace]
        Q = Matrix(nullspace).transposed()
    else:
        # Use Cayley-Hamilton to find the eigenvectors
        I = Matrix.Identity(3)
        Aa = mat - L[0] * I
        Ab = mat - L[1] * I
        Ac = mat - L[2] * I
        Q = Matrix((max(Aa @ Ab).normalized(),
                    max(Aa @ Ac).normalized(),
                    max(Ab @ Ac).normalized()))
    _canonicalize_matrix(Q)
    return Q

def _linear_regression(verts):
    # Note that this is the centroid of the points, NOT the center of mass,
    # so it is not directly usable
    centroid = sum(verts, start=Vector((0, 0, 0))) / len(verts)
    A = Matrix(((0, 0, 0),)*3)
    for vert in verts:
        v = vert - centroid
        A += Matrix(((v.x * v.x, v.x * v.y, v.x * v.z),
                     (v.x * v.y, v.y * v.y, v.y * v.z),
                     (v.x * v.z, v.y * v.z, v.z * v.z)))
    s = max(max(A))
    A *= (1/s)
    Q = _eigen_vectors(A)
    # The rotation is never more than 45 degrees as higher angles simply
    # change the principle axes
    rotation = Q.to_quaternion()
    # Note that this is not the actual axis moments, but their
    # contributions: that is, for Ixx, add moment.y and moment.z. However,
    # the size of the equivalent box edge length can be found from
    # sqrt(m/2). More importantly, it is the moments of the point masses
    # rather than of the solid object.
    moment = Q.inverted() @ A @ Q
    return centroid, rotation, moment @ Vector((1,1,1)), Q.inverted()

def _calc_p(x, frame):
    """ Find properties of each point
    Distance along the primary axis
    Distance squared from the primary axis
    Projection onto the primary plane (secondary axes) for SEB
    """
    n, s, t = frame
    u = x @ s
    v = x @ t
    w = x @ n
    return w, u**2 + v**2, (u * s, v * t)

def _key_u(uv2):
    return uv2[0]

def _key_v2(uv2):
    return uv2[1]

class Points:
    def __init__(self):
        self.verts = []

    @property
    def valid(self):
        return len(self.verts) > 0

    def add_verts(self, verts, xform, selected=False):
        if selected:
            verts = [v for v in verts if v.select]
        base = len(self.verts)
        self.verts = self.verts + [None] * len(verts)
        for i, v in enumerate(verts):
            self.verts[base + i] = (xform @ v.co).freeze()

    def calc_box(self):
        if not self.verts:
            return Vector((0, 0, 0)), Vector((0, 0, 0))
        mins = Vector(self.verts[0])
        maxs = Vector(self.verts[0])
        for v in self.verts:
            mins.x = min(mins.x, v.x)
            mins.y = min(mins.y, v.y)
            mins.z = min(mins.z, v.z)
            maxs.x = max(maxs.x, v.x)
            maxs.y = max(maxs.y, v.y)
            maxs.z = max(maxs.z, v.z)
        size = (maxs - mins)
        center = (maxs + mins) / 2
        return size, center

    def calc_sphere(self):
        return smalest_enclosing_ball(self.verts)

    def calc_hull(self):
        return quickhull(self)

    def calc_capsule(self):
        loc, rot, mom, Q = _linear_regression(self.verts)
        m = list(mom)
        l = max(m)
        i = m.index(l)
        axis = properties.dir_items[i][0]
        del m[i]
        r = max(m)
        # pick a frame (n, s, t) such that n is the primary axis and s,t are
        # the secondary axes of the capsule
        frame = Q[i], Q[(i + 1) % 3], Q[(i + 2) % 3]
        p = [_calc_p(x - loc, frame) for x in self.verts]
        mi, ma = min(p, key=_key_u)[0], max(p, key=_key_u)[0]
        r2 = max(p, key=_key_v2)[1]
        mi = min([p[0] + sqrt(r2 - p[1]) for p in p if (p[0] - mi)**2 < r2])
        ma = max([p[0] - sqrt(r2 - p[1]) for p in p if (p[0] - ma)**2 < r2])
        #print (mi, ma)
        r = sqrt(r2)
        length = (ma - mi) + 2 * r
        return loc, rot, axis, length, r
