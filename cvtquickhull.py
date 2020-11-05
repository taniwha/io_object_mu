import sys

from mu import Mu, MuObject, MuTransform, MuMesh, MuTagLayer
from multiprocessing import Pool

def read_vertices(input):
    """
    Reads vertices from the input array.

    Args:
        input: (todo): write your description
    """
    count = input.read_int()
    verts = [None] * count
    for i in range(count):
        verts[i] = input.read_vector()
    return verts

class Face:
    pass

def read_face(input):
    """
    Reads a face.

    Args:
        input: (todo): write your description
    """
    f = Face()
    a, b, c = input.read_int(3)
    if not a:
        f.tri = a, c, b
    else:
        f.tri = c, b, a
    f.highest = input.read_int()
    count = input.read_int()
    f.vispoints = input.read_int(count)
    return f

def read_facelist(input):
    """
    Reads a list of faces from the input array.

    Args:
        input: (todo): write your description
    """
    count = input.read_int()
    faces = [None] * count
    for i in range(count):
        faces[i] = read_face(input)
    return faces

def make_transform(name):
    """
    Create a new transform.

    Args:
        name: (str): write your description
    """
    transform = MuTransform()
    transform.name = name
    transform.localPosition = (0, 0, 0)
    transform.localRotation = (1, 0, 0, 0)
    transform.localScale = (1, 1, 1)
    return transform

def make_empty(name):
    """
    Create an empty tag.

    Args:
        name: (str): write your description
    """
    obj = MuObject()
    obj.transform = make_transform(name)
    obj.tag_and_layer = MuTagLayer()
    obj.tag_and_layer.tag = ""
    obj.tag_and_layer.layer = 0
    return obj

def make_tris(faces):
    """
    Convert a list of a list of faces.

    Args:
        faces: (list): write your description
    """
    tris = []
    for f in faces:
        tris.append(f.tri)
    return tris

def make_mesh(name, verts, faces):
    """
    Make a mesh from a mesh.

    Args:
        name: (str): write your description
        verts: (str): write your description
        faces: (todo): write your description
    """
    obj = make_empty(name)
    mesh = MuMesh()
    mesh.verts = verts
    mesh.submeshes = [make_tris(faces)]
    obj.shared_mesh = mesh
    return obj

extra_points = set()

def thread_func(parms):
    """
    Generate a thread

    Args:
        parms: (str): write your description
    """
    name = parms
    input = Mu()
    input.file = open(name + ".bin", "rb");
    verts = read_vertices(input)
    faces = read_facelist(input)
    final_faces = read_facelist(input)
    point = input.read_int()
    lit_faces = read_facelist(input)
    new_faces = read_facelist(input)
    output = Mu()
    output.materials = []
    output.textures = []
    output.obj = make_empty(name)
    output.obj.children.append(make_mesh("faces", verts, faces))
    output.obj.children.append(make_mesh("final_faces", verts, final_faces))
    output.obj.children.append(make_mesh("lit_faces", verts, lit_faces))
    output.obj.children.append(make_mesh("new_faces", verts, new_faces))
    if (point >= 0):
        p = make_empty(f"point-{point}")
        p.transform.localPosition = verts[point]
        output.obj.children.append(p)
    for ep in extra_points:
        p = make_empty(f"epoint-{ep}")
        p.transform.localPosition = verts[ep]
        output.obj.children.append(p)
    output.write(name+".mu")
    print(name)

for a in sys.argv[1:]:
    extra_points.add(int(a))
i = 0
work_queue = []
while True:
    name = f"quickhull-{i:#05d}"
    try:
        file = open(name + ".bin", "rb");
    except:
        break
    else:
        file.close()
        work_queue.append(name)
    i+=1
print(len(work_queue))
with Pool(12) as p:
    p.map(thread_func, work_queue)
