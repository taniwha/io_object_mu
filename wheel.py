from mu import Mu, MuEnum, MuColliderWheel
from cfgnode import ConfigNode
import sys

wheel_colliders = {}

wheel_mu = sys.argv[1]

def find_wheels(obj, path=""):
    if not path:
        path = obj.transform.name
    else:
        path = ".".join([path, obj.transform.name])
    if hasattr(obj, "collider") and type(obj.collider) == MuColliderWheel:
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

def wheel_cfg(name, wheel):
    node = ConfigNode ()
    node.AddValue("name", name)
    node.AddValue("mass", wheel.mass)
    node.AddValue("radius", wheel.radius)
    node.AddValue("suspensionDistance", wheel.suspensionDistance)
    node.AddValue("center", wheel.center)
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

def main():
    mu = Mu()
    if not mu.read(wheel_mu):
        print("could not read: " + fname)
        raise
    find_wheels(mu.obj)
    for w in wheel_colliders.keys():
        node = wheel_cfg(w, wheel_colliders[w])
        print("Wheel "+ node.ToString())

main()
