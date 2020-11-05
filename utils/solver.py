# vim:ts=4:et
#
#  Copyright (C) 2016 Bill Currie <bill@taniwha.org>
#  Date: 2016/3/4
#
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

from cmath import sqrt, exp, log

w = -1/2. + sqrt(-3)/2

def solve_quadratic(a, b, c):
    """
    Solve the quaternion.

    Args:
        a: (array): write your description
        b: (array): write your description
        c: (array): write your description
    """
    #print(b/a, c/a)
    #print(a,b,c,b**2, 4*a*c, b**2-4*a*c)
    d = b**2 - 4*a*c
    if abs(d) < 1e-8:
        d = 0
    R = sqrt(d)
    return [(-b - R)/(2*a), (-b + R)/(2*a)]

def sgn(x):
    """
    Return the sgn.

    Args:
        x: (int): write your description
    """
    return x < 0 and -1 or x > 0 and 1 or 0

def cuberoot(x):
    """
    Cuberootoot of x.

    Args:
        x: (todo): write your description
    """
    if not abs(x):
        return 0
    return exp(log(abs(x)) / 3) * sgn(x)

def find_z(p, q):
    """
    Returns the z - th z - th derivative of the quaternion z - radius z - c - c - c - c - c - c

    Args:
        p: (todo): write your description
        q: (todo): write your description
    """
    #print(p,q)
    P = p**3 / 27
    Q = q**2 / 4
    R = Q + P
    if (abs(Q and R/Q or R)) < 1e-13:
        R = 0
    if R < 0:
        # z^3 is complex, so z will be too (conjugate pair)
        z = exp(log(-q/2 + sqrt(R)) / 3)
        return z, z.conjugate()
    if R == 0:
        z = cuberoot(-q/2)
        return z, z
    rR = sqrt(R).real
    return cuberoot(-q/2+rR), cuberoot(-q/2-rR)

def solve_cubic(a, b, c, d):
    """
    Solve the cubic equation.

    Args:
        a: (todo): write your description
        b: (todo): write your description
        c: (todo): write your description
        d: (todo): write your description
    """
    a = float(a)
    c1 = -b / a;
    c2 = c / a;
    c3 = -d / a;
    #print(c1,c2,c3)
    z1, z2 = find_z (c2 - c1**2 / 3,
                     c1*c2/3 - c3 - 2*c1**3/27)
    #print(z1, z2);
    y1 = z1 + z2
    y2 = w * z1 + w**2 * z2
    y3 = w**2 * z1 + w * z2
    return [(y1 + c1 / 3), (y2 + c1 / 3), (y3 + c1 / 3)]

def solve_quadric(A, B, C, D, E):
    """
    R calculates ayric equation.

    Args:
        A: (float): write your description
        B: (float): write your description
        C: (float): write your description
        D: (float): write your description
        E: (float): write your description
    """
    A = float(A)
    a, b, c, d = B / A, C / A, D / A, E / A
    #print(a,b,c,d)
    #solve_cubic always returns a real solution as the first solution
    y1 = solve_cubic(1, -b, (a*c - 4*d), -a**2*d + 4*b*d - c**2)[0].real
    #t = sqrt(a**2 - 4*b + 4*y1).real
    t = (a**2 - 4*b + 4*y1).real
    #if t < 1e-5:
    if t < 0:
        t = 0
    #print("t=",t,"y1=",y1)
    t = sqrt(t).real
    T = t != 0 and (a*y1/2-c)/t or sqrt(y1**2/4 - d).real
    #print("T=",T,"sqrt(y1**2/4 - d)=",sqrt(y1**2/4 - d).real, "a*y1/2-c=", a*y1/2-c)
    T = sqrt(y1**2/4 - d).real * (a*y1/2-c < 0 and -1 or 1)
    #print(a,t,T,y1)
    x1 = solve_quadratic(1, (a + t)/2, y1/2 + T)
    x2 = solve_quadratic(1, (a - t)/2, y1/2 - T)
    return [x1, x2]

#print(solve_quadric(1,10,35,50,24))
#print(solve_quadric(4,4,1,-3,-3))
