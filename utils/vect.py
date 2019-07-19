# vim:ts=4:et
from math import sqrt, acos, cos

def add (a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

def sub (a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def dot (a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def cross (a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

def mul (a, b):
    if type (a) in (int, float):
        return (a * b[0], a * b[1], a * b[2])
    elif type (b) in (int, float):
        return (a[0] * b, a[1] * b, a[2] * b)
    else:
        return (a[0] * b[0], a[1] * b[1], a[2] * b[2])

def div (a, b):
    return (a[0] / b, a[1] / b, a[2] / b)

def neg (a):
    return (-a[0], -a[1], -a[2])

def qadd (a, b):
    return (a[0] + b[0], add (a[1], b[1]))

def qsub (a, b):
    return (a[0] - b[0], sub (a[1], b[1]))

def qdot (a, b):
    return a[0] * b[0] + dot (a[1], b[1])

def qmul (a, b):
    if type (a) in (int, float):
        return (a * b[0], mul (a, b[1]))
    elif type (b) in (int, float):
        return (a[0] * b, mul (a[1], b))
    elif len (b) == 3:
        s = -dot (a[1], b)
        tv = cross (a[1], v)
        tv = add (tv, mul (a[0], v))
        o = cross (a[1], tv)
        o = sub (o, mul (s, a[1]))
        o = add (o, mul (a[0], tv))
        return o
    else:
        return (a[0] * b[0] - dot (a[1], b[1]), add (add (mul (a[0], b[1]), mul (a[1], b[0])),
                                                     cross (a[1], b[1])))

def qconj (a):
    return (a[0], neg (a[1]))

def qdiv (a, b):
    if type (b) in (int, float):
        return (a[0] / b, div (a[1], b))
    else:
        return qdiv (qmul (a, qconj (b)), qdot (b, b))

def getq (a, b):
    #"""Assumes both a and b are unit vectors.
    #Fails when a and b are in opposite directions (a.b=-1)"""
    # Get the unit vector dividing the angle (theta) between a and b in two.
    c = add (a, b)
    C = dot (c, c)
    C = sqrt (C)
    h = div (c, C)
    # (cos(theta/2), sin(theta/2) * n) where n is the unit vector of the axis rotating a onto b
    return (dot (a, h), cross (a, h))

def qmat (q):
    q = (q[0],) + q[1]
    aa = q[0] * q[0]
    ab = q[0] * q[1]
    ac = q[0] * q[2]
    ad = q[0] * q[3]
    bb = q[1] * q[1]
    bc = q[1] * q[2]
    bd = q[1] * q[3]
    cc = q[2] * q[2]
    cd = q[2] * q[3]
    dd = q[3] * q[3]

    m = ((aa + bb - cc - dd, 2 * (bc - ad), 2 * (bd + ac)),
         (2 * (bc + ad), aa - bb + cc - dd, 2 * (cd - ab)),
         (2 * (bd - ac), 2 * (cd + ab), aa - bb - cc + dd))
    return m

def mtrans (m):
    t = ((m[0][0], m[1][0], m[2][0]),
         (m[0][1], m[1][1], m[2][1]),
         (m[0][2], m[1][2], m[2][2]))
    return t

def mtrace (m):
    return m[0][0] + m[1][1] + m[2][2]

def madd (a, b):
    return (add (a[0], b[0]), add (a[1], b[1]), add (a[2], b[2]))

def msub (a, b):
    return (sub (a[0], b[0]), sub (a[1], b[1]), sub (a[2], b[2]))

def mmul (a, b):
    if type (b) in (int, float):
        return (mul (a[0], b), mul (a[1], b), mul (a[2], b))
    if type (a) in (int, float):
        return (mul (b[0], a), mul (b[1], a), mul (b[2], a))
    if type (b[0]) in (int, float):
        return (dot (a[0], b), dot (a[1], b), dot (a[2], b))
    b = mtrans(b)
    return ((dot (a[0], b[0]), dot (a[0], b[1]), dot (a[0], b[2])),
            (dot (a[1], b[0]), dot (a[1], b[1]), dot (a[1], b[2])),
            (dot (a[2], b[0]), dot (a[2], b[1]), dot (a[2], b[2])))

def mdet (a):
    return dot (a[0], cross (a[1], a[2]))

def meigen (m):
    #note: only symetric matrices
    p = m[0][1]**2 + m[1][2]**2 + m[1][2]**2
    if p < 1e-6:
        return m[0][0], m[1][1], m[2][2]
    q = mtrace (m) / 3
    p = (m[0][0] - q)**2 + (m[1][1] - q)**2 + (m[2][2] - q)**2 + 2*p
    p = sqrt(p)
    B = mmul (msub (m, mmul (q, I)), 1.0 / p)
    r = mdet (B) / 2
    if r >= 1:
        phi = 0
    elif r <= -1:
        phy = pi / 3
    else:
        phy = acos (r) / 3

    e1 = q + 2*p*cos (phi)
    e3 = q + 2*p*cos (phi + pi * 2 / 3)
    e2 = 3*q - e1 - e3
    return e1, r2, r3

def round (f, e):
    return int(f / e + 0.5) * e

def minvmonde (v):
    vr = []
    vv = []
    for v1 in v:
        r = round (v1, 0.5**20)
        if not r in vr:
            vr.append(r)
            vv.append(v1)
    if len(vv) == 3:
        v1, v2, v3 = vv
        a = v2 - v1
        b = v3 - v1
        c = v3 - v2
        inv = (( v2*v3/(a*b), -(v2+v3)/(a*b),  1.0/(a*b)),
               (-v1*v3/(a*c),  (v1+v3)/(a*c), -1.0/(a*c)),
               ( v1*v2/(b*c), -(v1+v2)/(b*c),  1.0/(b*c)))
    elif len(vv) == 2:
        v1, v2 = vv
        a = v2 - v1
        inv = ((v2 / a, -1 / a), (-v1 / a, 1 / a))
    else:
        inv = ((1,),)
    l = map (lambda x: sqrt(x), vv)
    return (map (lambda x, y: map (lambda z: z / y, x), inv, l),
            map (lambda x, y: map (lambda z: z * y, x), inv, l))
