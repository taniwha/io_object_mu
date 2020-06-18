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
from math import sqrt

def circum_sphere(points):
    num_points = len(points)
    if num_points == 1:
        center = (points[0], 0)
    elif num_points == 2:
        center = (points[0] + points[1]) / 2
    elif num_points == 3:
        a = points[0] - points[1]
        b = points[0] - points[2]
        c = points[1] - points[2]
        aa = a @ a
        bb = b @ b
        cc = c @ c
        axc = a.cross(c)
        div = 2 * (axc @ axc)
        if div < 1e-6:
            return None
        alpha = cc * (a @ b) / div
        beta = -bb * (a @ c) / div
        gamma = aa * (b @ c) / div
        center = alpha * points[0] + beta * points[1] + gamma * points[2]
    elif num_points == 4:
        a = points[1] - points[0]
        b = points[2] - points[0]
        c = points[3] - points[0]
        bxc = b.cross(c)
        cxa = c.cross(a)
        axb = a.cross(b)
        div = 2 * (a @ bc)
        if abs(div) < 1e-6:
            return None
        aa = (a @ a) / div
        bb = (b @ b) / div
        cc = (c @ c) / div
        center = aa * bc + bb * cz + cc * ab + points[0]
    else:
        return None
    radius = (points[0] - center).magnitude
    return center, radius

def closest_affine_point(points, x):
    num_points = len(points)
    #FIXME assumes the points form a non-degenerate simplex
    if num_points == 4:
        return x
    elif num_points == 3:
        a = points[1] - points[0]
        b = points[2] - points[0]
        n = a.cross(b)
        d = points[0] - x
        l = (d @ n) / (n @ n)
        return x + l * n
    elif num_points == 2:
        n = points[1] - points[0]
        d = x - points[0]
        l = (d @ n) / (n @ n)
        return points[0] + l * n
    else:
        return points[0]

def barycentric_coords(points, p):
    num_points = len(points)
    lam = [None] * num_points
    if num_points == 1:
        lam[0] = 1
    elif num_points == 2:
        x = p - points[0]
        a = points[1] - points[0]
        lam[1] = (x @ a) / (a @ a)
        lam[0] = 1 - lam[1]
    elif num_points == 3:
        x = p - points[0]
        a = points[1] - points[0]
        b = points[2] - points[0]
        axb = a.cross(b)
        div = axb @ axb
        n = x.cross(b)
        lam[1] = (n @ axb) / div
        n = a.cross(x)
        lam[2] = (n @ axb) / div
        lam[0] = 1 - lam[1] - lam[2]
    elif num_points == 4:
        x = p - points[0]
        a = points[1] - points[0]
        b = points[2] - points[0]
        c = points[3] - points[0]
        axb = a.cross(b)
        bxc = b.cross(c)
        cxa = c.cross(a)
        div = a @ bxc
        lam[1] = (x @ bxc) / div
        lam[2] = (x @ cxa) / div
        lam[3] = (x @ axb) / div
        lam[0] = 1 - lam[1] - lam[2] - lam[3]
    return lam

def smalest_enclosing_ball(points):
    if not points:
        return None
    if len(points) == 1:
        return (points[0], 0)
    elif len(points) == 2:
        p = (points[0] + points[1]) / 2
        return (p, (points[0] - p).magnitude)
    support = []
    center = points[0]
    best_dist = 0
    best = None
    for p in points[1:]:
        dist = (p - center).length_squared
        if dist > best_dist:
            best_dist = dist
            best = p
    if best is None:
        return center, 0
    support.append(best)
    radius = best_dist # note: radius squared until the end

    iter = 0
    while True:
        #print(f"{iter} support: {support}")
        iter += 1
        lam = barycentric_coords(support, center)
        #print(f"    lambda: {lam}")
        i = 0
        dropped = set()
        while i < len(support):
            if lam[i] < 0:
                dropped.add(support[i])
                del lam[i]
                del support[i]
            else:
                i += 1
        if len(support) == 4 and not dropped:
            break
        affine = closest_affine_point(support, center)
        center_to_affine = affine - center
        affine_dist = center_to_affine @ center_to_affine
        #print(f"    affine: {affine}")
        if affine_dist < 1e-6 * radius:
            break

        best = None
        scale = 1
        for p in points:
            if p in support or p in dropped:
                continue
            center_to_point = p - center
            point_proj = center_to_affine @ center_to_point
            if affine_dist - point_proj <= 0:
                continue
            point_dist = center_to_point @ center_to_point
            bound = radius - point_dist
            bound /= 2 * (affine_dist - point_proj)
            if bound < scale:
                best = p
                scale = bound
        #print(f"    scale: {scale} best:{best}")
        if best is None:
            best = center
        center = center + scale * center_to_affine
        radius = (center - best).length_squared
        support.append(best)
        #print(f"    center: {center} radius:{sqrt(radius)}")
    best_dist = 0
    for p in points[1:]:
        dist = (p - center).length_squared
        if dist > best_dist:
            best_dist = dist
    radius = sqrt(best_dist)
    return center, radius

if __name__ == "__main__":
    class Vector:
        def __init__(self, vals):
            self.x = float(vals[0])
            self.y = float(vals[1])
            self.z = float(vals[2])
        def __add__(self, b):
            return Vector((self.x + b.x, self.y + b.y, self.z + b.z))
        def __sub__(self, b):
            return Vector((self.x - b.x, self.y - b.y, self.z - b.z))
        def __mul__(self, s):
            return Vector((self.x * s, self.y * s, self.z * s))
        def __rmul__(self, s):
            return Vector((self.x * s, self.y * s, self.z * s))
        def __div__(self, s):
            return Vector((self.x / s, self.y / s, self.z / s))
        def __truediv__(self, s):
            return Vector((self.x / s, self.y / s, self.z / s))
        def __idiv__(self, s):
            return Vector((self.x / s, self.y / s, self.z / s))
        def __matmul__(self, b):
            return self.x * b.x + self.y * b.y + self.z * b.z
        def __eq__(self, b):
            return self.x == b.x and self.y == b.y and self.z == b.z
        def __hash__(self):
            return self.x.__hash__() ^ self.y.__hash__() ^ self.z.__hash__()
        def cross(self, b):
            return Vector((self.y * b.z - self.z * b.y,
                           self.z * b.x - self.x * b.z,
                           self.x * b.y - self.y * b.x))
        @property
        def magnitude(self):
            return sqrt(self @ self)
        @property
        def length_squared(self):
            return self @ self
        def __str__(self):
            return f"[{self.x}, {self.y}, {self.z}]"
        def __repr__(self):
            return f"Vector(({self.x}, {self.y}, {self.z}))"

    points = [
        Vector(( 1,  1,  1)),
        Vector((-1, -1,  1)),
        Vector(( 1, -1, -1)),
        Vector((-1,  1, -1)),
    ]
    print(smalest_enclosing_ball(points[:1]))
    print(smalest_enclosing_ball(points[:2]))
    print(smalest_enclosing_ball(points[:3]))
    print(smalest_enclosing_ball(points))
