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
from mu import Mu, MuEnum, MuColliderWheel
from cfgnode import ConfigNode
import sys

wheel_colliders = {}

def find_wheels(obj, path=""):
    if not path:
        path = obj.transform.name
    else:
        path = ".".join([path, obj.transform.name])
    if hasattr(obj, "collider") and isinstance(obj.collider, MuColliderWheel):
        wheel_colliders[path] = obj.collider
    for o in obj.children:
        find_wheels(o, path)

def spring_cfg(node, spring):
    node.AddValue("spring", spring.spring)
    node.AddValue("damper", spring.damper)
    node.AddValue("targetPosition", spring.targetPosition)

def friction_cfg(node, friction):
    node.AddValue("extremumSlip", friction.extremumSlip)
    node.AddValue("extremumValue", friction.extremumValue)
    node.AddValue("asymptoteSlip", friction.asymptoteSlip)
    node.AddValue("asymptoteValue", friction.asymptoteValue)
    node.AddValue("stiffness", friction.stiffness)

def ValueString(val):
    if type(val) in [tuple, list]:
        vstr = str(val[0])
        for v in val[1:]:
            vstr += ", " + str(v)
        return vstr
    else:
        return str(val)

def wheel_cfg(name, wheel):
    node = ConfigNode ()
    node.AddValue("name", name)
    node.AddValue("mass", wheel.mass)
    node.AddValue("radius", wheel.radius)
    node.AddValue("suspensionDistance", wheel.suspensionDistance)
    node.AddValue("center", ValueString(wheel.center))
    spring_cfg(node.AddNode("suspensionSpring"), wheel.suspensionSpring)
    friction_cfg(node.AddNode("forwardFriction"), wheel.forwardFriction)
    friction_cfg(node.AddNode("sidewaysFriction"), wheel.sidewaysFriction)
    return node

def fexp(f):
    return (f.extremumSlip, f.extremumValue, f.asymptoteSlip, f.asymptoteValue,
            f.stiffness)

def sexp(s):
    return (s.spring, s.damper, s.targetPosition)

def dump_wheel(wheel):
    print("mass: %f" % wheel.mass)
    print("radius: %f" % wheel.radius)
    print("suspensionDistance: %f" % wheel.suspensionDistance)
    print("center: %f %f %f" % wheel.center)
    print("suspensionSpring: %f %f %f" % sexp(wheel.suspensionSpring))
    print("forwardFriction: %f %f %f %f %f" % fexp(wheel.forwardFriction))
    print("sidewaysFriction: %f %f %f %f %f" % fexp(wheel.sidewaysFriction))

def vector(s):
    return tuple(map(lambda x: float(x),s.split(",")))

wheel_fields = (
    ("mass", float),
    ("radius", float),
    ("suspensionDistance", float),
    ("center", vector),
)

friction_fields = (
    ("extremumSlip", float),
    ("extremumValue", float),
    ("asymptoteSlip", float),
    ("asymptoteValue", float),
    ("stiffness", float),
)

spring_fields = (
    ("spring", float),
    ("damper", float),
    ("targetPosition", float),
)

def adjust_wheel(wheel_node):
    name = wheel_node.GetValue("name")
    wheel = wheel_colliders[name]
    for f in wheel_fields:
        val = wheel_node.GetValue(f[0])
        if val:
            setattr(wheel, f[0], f[1](val))
    spring = wheel_node.GetNode("suspensionSpring")
    if spring:
        for f in spring_fields:
            val = spring.GetValue(f[0])
            if val:
                setattr(wheel.suspensionSpring, f[0], f[1](val))
    for fr in ["forwardFriction", "sidewaysFriction"]:
        friction = wheel_node.GetNode(fr)
        if friction:
            fric = getattr(wheel, fr)
            for f in friction_fields:
                val = friction.GetValue(f[0])
                if val:
                    setattr(fric, f[0], f[1](val))

def main():
    wheel_mu = sys.argv[1]
    mu = Mu()
    if not mu.read(wheel_mu):
        print("could not read: " + fname)
        raise
    find_wheels(mu.obj)
    if len(sys.argv) > 2:
        text = open(sys.argv[2], "rt").read()
        node = ConfigNode.load(text)
        wheel = node.GetNode('Wheel')
        if not wheel:
            print("could not find Wheel")
            sys.exit(1)
        adjust_wheel(wheel)
        mu.write("wheelout.mu")
    else:
        for w in wheel_colliders.keys():
            node = wheel_cfg(w, wheel_colliders[w])
            print("Wheel "+ node.ToString())

main()
