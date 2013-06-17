# vim:ts=4:et

from struct import pack, unpack
class MuEnum:
    MODEL_BINARY = 76543
    FILE_VERSION = 2

    ET_CHILD_TRANSFORM_START = 0
    ET_CHILD_TRANSFORM_END = 1
    ET_ANIMATION = 2
    ET_MESH_COLLIDER = 3
    ET_SPHERE_COLLIDER = 4
    ET_CAPSULE_COLLIDER = 5
    ET_BOX_COLLIDER = 6
    ET_MESH_FILTER = 7
    ET_MESH_RENDERER = 8
    ET_SKINNED_MESH_RENDERER = 9    #XXX
    ET_MATERIALS = 10
    ET_MATERIAL = 11    #XXX not used?
    ET_TEXTURES = 12
    ET_MESH_START = 13
    ET_MESH_VERTS = 14
    ET_MESH_UV = 15
    ET_MESH_UV2 = 16
    ET_MESH_NORMALS = 17
    ET_MESH_TANGENTS = 18
    ET_MESH_TRIANGLES = 19
    ET_MESH_BONE_WEIGHTS = 20
    ET_MESH_BIND_POSES = 21
    ET_MESH_END = 22
    ET_LIGHT = 23   #XXX
    ET_TAG_AND_LAYER = 24
    ET_MESH_COLLIDER2 = 25
    ET_SPHERE_COLLIDER2 = 26
    ET_CAPSULE_COLLIDER2 = 27
    ET_BOX_COLLIDER2 = 28
    ET_WHEEL_COLLIDER = 29
    ET_CAMERA = 30  #XXX
    ENTRY_TYPES = {
        'ET_CHILD_TRANSFORM_START':ET_CHILD_TRANSFORM_START,
        'ET_CHILD_TRANSFORM_END':ET_CHILD_TRANSFORM_END,
        'ET_ANIMATION':ET_ANIMATION,
        'ET_MESH_COLLIDER':ET_MESH_COLLIDER,
        'ET_SPHERE_COLLIDER':ET_SPHERE_COLLIDER,
        'ET_CAPSULE_COLLIDER':ET_CAPSULE_COLLIDER,
        'ET_BOX_COLLIDER':ET_BOX_COLLIDER,
        'ET_MESH_FILTER':ET_MESH_FILTER,
        'ET_MESH_RENDERER':ET_MESH_RENDERER,
        'ET_SKINNED_MESH_RENDERER':ET_SKINNED_MESH_RENDERER,
        'ET_MATERIALS':ET_MATERIALS,
        'ET_MATERIAL':ET_MATERIAL,
        'ET_TEXTURES':ET_TEXTURES,
        'ET_MESH_START':ET_MESH_START,
        'ET_MESH_VERTS':ET_MESH_VERTS,
        'ET_MESH_UV':ET_MESH_UV,
        'ET_MESH_UV2':ET_MESH_UV2,
        'ET_MESH_NORMALS':ET_MESH_NORMALS,
        'ET_MESH_TANGENTS':ET_MESH_TANGENTS,
        'ET_MESH_TRIANGLES':ET_MESH_TRIANGLES,
        'ET_MESH_BONE_WEIGHTS':ET_MESH_BONE_WEIGHTS,
        'ET_MESH_BIND_POSES':ET_MESH_BIND_POSES,
        'ET_MESH_END':ET_MESH_END,
        'ET_LIGHT':ET_LIGHT,
        'ET_TAG_AND_LAYER':ET_TAG_AND_LAYER,
        'ET_MESH_COLLIDER2':ET_MESH_COLLIDER2,
        'ET_SPHERE_COLLIDER2':ET_SPHERE_COLLIDER2,
        'ET_CAPSULE_COLLIDER2':ET_CAPSULE_COLLIDER2,
        'ET_BOX_COLLIDER2':ET_BOX_COLLIDER2,
        'ET_WHEEL_COLLIDER':ET_WHEEL_COLLIDER,
        'ET_CAMERA':ET_CAMERA,
    }

    ST_CUSTOM = 0
    ST_DIFFUSE = 1
    ST_SPECULAR = 2
    ST_BUMPED = 3
    ST_BUMPED_SPECULAR = 4
    ST_EMISSIVE = 5
    ST_EMISSIVE_SPECULAR = 6
    ST_EMISSIVE_BUMPED_SPECULAR = 7
    ST_ALPHA_CUTOUT = 8
    ST_ALPHA_CUTOUT_BUMPED = 9
    ST_ALPHA = 10
    ST_ALPHA_SPECULAR = 11
    ST_ALPHA_UNLIT = 12
    ST_UNLIT = 13
    SHADER_TYPES = {
        'ST_CUSTOM':ST_CUSTOM,
        'ST_DIFFUSE':ST_DIFFUSE,
        'ST_SPECULAR':ST_SPECULAR,
        'ST_BUMPED':ST_BUMPED,
        'ST_BUMPED_SPECULAR':ST_BUMPED_SPECULAR,
        'ST_EMISSIVE':ST_EMISSIVE,
        'ST_EMISSIVE_SPECULAR':ST_EMISSIVE_SPECULAR,
        'ST_EMISSIVE_BUMPED_SPECULAR':ST_EMISSIVE_BUMPED_SPECULAR,
        'ST_ALPHA_CUTOUT':ST_ALPHA_CUTOUT,
        'ST_ALPHA_CUTOUT_BUMPED':ST_ALPHA_CUTOUT_BUMPED,
        'ST_ALPHA':ST_ALPHA,
        'ST_ALPHA_SPECULAR':ST_ALPHA_SPECULAR,
        'ST_ALPHA_UNLIT':ST_ALPHA_UNLIT,
        'ST_UNLIT':ST_UNLIT,
    }

    AT_TRANSFORM = 0
    AT_MATERIAL = 1
    AT_LIGHT = 2
    AT_AUDIO_SOURCE = 3
    ANIMATION_TYPES = {
        'AT_TRANSFORM':AT_TRANSFORM,
        'AT_MATERIAL':AT_MATERIAL,
        'AT_LIGHT':AT_LIGHT,
        'AT_AUDIO_SOURCE':AT_AUDIO_SOURCE,
    }

    TT_TEXTURE = 0
    TT_NORMAL_MAP = 1
    TEXTURE_TYPES = {
        'TT_TEXTURE':TT_TEXTURE,
        'TT_NORMAL_MAP':TT_NORMAL_MAP,
    }

class MuTexture:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuTexture")
        self.name = mu.read_string()
        self.type = mu.read_int()
        print("   ", self.name, self.type)
        return self

class MuMatTex:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuMatTex")
        self.index = mu.read_int()
        self.scale = mu.read_float(2)
        self.offset = mu.read_float(2)
        return self

class MuMaterial:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuMaterial")
        self.name = mu.read_string()
        self.type = mu.read_int()
        if self.type == MuEnum.ST_SPECULAR:
            self.mainTex = MuMatTex().read(mu)
            self.specColor = mu.read_float(4)
            self.shininess = mu.read_float()
        elif self.type == MuEnum.ST_BUMPED:
            self.mainTex = MuMatTex().read(mu)
            self.bumpMap = MuMatTex().read(mu)
        elif self.type == MuEnum.ST_BUMPED_SPECULAR:
            self.mainTex = MuMatTex().read(mu)
            self.bumpMap = MuMatTex().read(mu)
            self.specColor = mu.read_float(4)
            self.shininess = mu.read_float()
        elif self.type == MuEnum.ST_EMISSIVE:
            self.mainTex = MuMatTex().read(mu)
            self.emmisive = MuMatTex().read(mu)
            self.emissiveColor = mu.read_float(4)
        elif self.type == MuEnum.ST_EMISSIVE_SPECULAR:
            self.mainTex = MuMatTex().read(mu)
            self.specColor = mu.read_float(4)
            self.shininess = mu.read_float()
            self.emmisive = MuMatTex().read(mu)
            self.emissiveColor = mu.read_float(4)
        elif self.type == MuEnum.ST_EMISSIVE_SPECULAR:
            self.mainTex = MuMatTex().read(mu)
            self.bumpMap = MuMatTex().read(mu)
            self.specColor = mu.read_float(4)
            self.shininess = mu.read_float()
            self.emmisive = MuMatTex().read(mu)
            self.emissiveColor = mu.read_float(4)
        elif self.type == MuEnum.ST_ALPHA_CUTOUT:
            self.mainTex = MuMatTex().read(mu)
            self.cutoff = mu.read_float()
        elif self.type == MuEnum.ST_ALPHA_CUTOUT_BUMPED:
            self.mainTex = MuMatTex().read(mu)
            self.bumpMap = MuMatTex().read(mu)
            self.cutoff = mu.read_float()
        elif self.type == MuEnum.ST_ALPHA:
            self.mainTex = MuMatTex().read(mu)
        elif self.type == MuEnum.ST_ALPHA_SPECULAR:
            self.mainTex = MuMatTex().read(mu)
            self.gloss = mu.read_float()
            self.specColor = mu.read_float(4)
            self.shininess = mu.read_float()
        elif self.type == MuEnum.ST_ALPHA_UNLIT:
            self.mainTex = MuMatTex().read(mu)
            self.color = mu.read_float(4)
        elif self.type == MuEnum.ST_UNLIT:
            self.mainTex = MuMatTex().read(mu)
            self.color = mu.read_float(4)
        elif self.type == MuEnum.ST_DIFFUSE:
            self.mainTex = MuMatTex().read(mu)
        else:
            raise ValueError("MuMaterial %d" % self.type)
        return self

class MuTransform:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuTransform")
        self.name = mu.read_string()
        self.localPosition = mu.read_float(3)
        self.localRotation = mu.read_float(4)
        self.localScale = mu.read_float(3)
        print("   ", self.name, self.localPosition, self.localRotation,
              self.localScale)
        return self

class MuTagLayer:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuTagLayer")
        self.tag = mu.read_string()
        self.layer = mu.read_int()
        print("   ", self.tag, self.layer)
        return self

class MuKey:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuKey")
        self.time = mu.read_float()
        self.value = mu.read_float()
        self.tangent = mu.read_float(2) # in, out
        self.tangentMode = mu.read_int()
        # editable, smooth, linear, stepped (0..3?)
        print("   ", self.time, self.value, self.tangent, self.tangentMode)
        return self

class MuCurve:
    def __init__(self):
        pass
    def read(self, mu):
        print("MuCurve")
        self.path = mu.read_string()
        self.property = mu.read_string()
        self.type = mu.read_int()
        self.wrapMode = mu.read_int(2)  # pre, post
        print("   ", self.path, self.property, self.type, self.wrapMode)
        num_keys = mu.read_int()
        print(num_keys)
        self.keys = []
        for i in range(num_keys):
            self.keys.append(MuKey().read(mu))
        return self

class MuClip:
    def __init__(self):
        self.curves = []
    def read(self, mu):
        print("MuClip")
        self.name = mu.read_string()
        self.lbCenter = mu.read_float(3)
        self.lbSize = mu.read_float(3)
        self.wrapMode = mu.read_int()
        print("   ", self.name, self.lbCenter, self.lbSize, self.wrapMode)
        num_curves = mu.read_int()
        for i in range(num_curves):
            self.curves.append(MuCurve().read(mu))
        return self

class MuAnimation:
    def __init__(self):
        self.clips = []
    def read(self, mu):
        print("MuAnimation")
        num_clips = mu.read_int()
        for i in range(num_clips):
            self.clips.append(MuClip().read(mu))
        self.clip = mu.read_string()
        self.autoPlay = mu.read_byte()  #XXX is this right?
        print(self.clip, self.autoPlay)
        return self

class MuBoneWeight:
    def __init__(self):
        self.indices = []
        self.weights = []
    def read(self, mu):
        for i in range(4):
            self.indices.append(mu.read_int())
            self.weights.append(mu.read_float())
        return self

class MuMesh:
    def __init__(self):
        self.verts = []
        self.uvs = []
        self.uv2s = []
        self.normals = []
        self.tangents = []
        self.boneWeights = []
        self.bindPoses = []
        self.submeshes = []
    def read(self, mu):
        print("MuMesh")
        start = mu.read_int()
        if start != MuEnum.ET_MESH_START:
            raise
        num_verts, submesh_count = mu.read_int(2)
        while True:
            type = mu.read_int()
            if type == MuEnum.ET_MESH_END:
                break
            elif type == MuEnum.ET_MESH_VERTS:
                print("    verts")
                for i in range(num_verts):
                    self.verts.append(mu.read_float(3))
            elif type == MuEnum.ET_MESH_UV:
                print("    uvs")
                for i in range(num_verts):
                    self.uvs.append(mu.read_float(2))
            elif type == MuEnum.ET_MESH_UV2:
                print("    uv2s")
                for i in range(num_verts):
                    self.uv2s.append(mu.read_float(2))
            elif type == MuEnum.ET_MESH_NORMALS:
                print("    normals")
                for i in range(num_verts):
                    self.normals.append(mu.read_float(3))
            elif type == MuEnum.ET_MESH_TANGENTS:
                print("    tangents")
                for i in range(num_verts):
                    self.tangents.append(mu.read_float(4))
            elif type == MuEnum.ET_MESH_BONE_WEIGHTS:
                print("    bone weights")
                for i in range(num_verts):
                    self.boneWeights.append(MuBoneWeight().read(mu))
            elif type == MuEnum.ET_MESH_BIND_POSES:
                print("    bind poses")
                num_poses = mu.read_int()
                for i in range(num_poses):
                    self.boneWeights.append(mu.read_float(12))
            elif type == MuEnum.ET_MESH_TRIANGLES:
                print("    sub mesh")
                num_tris = mu.read_int()
                tris = []
                for i in range(int(num_tris / 3)):   #FIXME is this guaranteed?
                    tris.append(mu.read_int(3))
                self.submeshes.append(tris)
            else:
                raise ValueError("MuMesh %x %d" % (mu.file.tell(), type))
        return self

class MuRenderer:
    def __init__(self):
        pass
    def read(self, mu):
        self.castShadows = mu.read_byte()
        self.receiveShadows = mu.read_byte()
        num_mat = mu.read_int()
        self.materials = mu.read_int(num_mat)
        return self

class MuCollider_Base:
    def __init__(self, type):
        self.type = type

class MuColliderMesh(MuCollider_Base):
    def read(self, mu):
        print("MuColliderMesh", self.type)
        self.isTrigger, self.convex = mu.read_byte(2)
        print(self.isTrigger, self.convex)
        self.mesh = MuMesh().read(mu)
        return self

class MuColliderSphere(MuCollider_Base):
    def read(self, mu):
        print("MuColliderSphere", self.type)
        self.isTrigger = mu.read_byte()
        self.radius = mu.read_float()
        self.center = mu.read_float(3)
        print(self.isTrigger, self.radius, self.center)
        return self

class MuColliderCapsule(MuCollider_Base):
    def read(self, mu):
        print("MuColliderCapsule", self.type)
        print(hex(mu.file.tell()))
        raise
        return self

class MuColliderBox(MuCollider_Base):
    def read(self, mu):
        print("MuColliderBox", self.type)
        self.isTrigger = mu.read_byte()
        self.size = mu.read_float(3)
        self.center = mu.read_float(3)
        print(self.isTrigger, self.size, self.center)
        return self

class MuSpring:
    def __init__(self):
        pass
    def read(self, mu):
        self.spring = mu.read_float()
        self.damper = mu.read_float()
        self.targetPosition = mu.read_float()
        return self

class MuFriction:
    def __init__(self):
        pass
    def read(self, mu):
        self.extremumSlip = mu.read_float()
        self.extremumValue = mu.read_float()
        self.asymptoteSlip = mu.read_float()
        self.asymptoteValue = mu.read_float()
        self.stiffness = mu.read_float()
        return self

class MuColliderWheel(MuCollider_Base):
    def __init__(self):
        MuCollider_Base.__init__(self, 0)
    def read(self, mu):
        print("MuColliderWheel")
        self.mass = mu.read_float()
        self.radius = mu.read_float()
        self.suspensionDistance = mu.read_float()
        self.center = mu.read_float(3)
        self.suspensionSprint = MuSpring().read(mu)
        self.forwardFriction = MuFriction().read(mu)
        self.sidewaysFriction = MuFriction().read(mu)
        return self

def MuCollider(type):
    if type in [MuEnum.ET_MESH_COLLIDER, MuEnum.ET_MESH_COLLIDER2]:
        return MuColliderMesh(type == MuEnum.ET_MESH_COLLIDER2)
    elif type in [MuEnum.ET_SPHERE_COLLIDER, MuEnum.ET_SPHERE_COLLIDER2]:
        return MuColliderSphere(type == MuEnum.ET_SPHERE_COLLIDER2)
    elif type in [MuEnum.ET_CAPSULE_COLLIDER, MuEnum.ET_CAPSULE_COLLIDER2]:
        return MuColliderCapsule(type == MuEnum.ET_CAPSULE_COLLIDER2)
    elif type in [MuEnum.ET_BOX_COLLIDER, MuEnum.ET_BOX_COLLIDER2]:
        return MuColliderBox(type == MuEnum.ET_BOX_COLLIDER2)
    elif type in [MuEnum.ET_WHEEL_COLLIDER]:
        return MuColliderWheel()
    else:
        raise ValueError("MuCollider %d" % type)

class MuLight:
    def __init__(self):
        pass
    def read(self, mu):
        self.type = mu.read_int()
        self.intensity = mu.read_float()
        self.range = mu.read_float()
        self.color = mu.read_float(3)
        self.spotAngle = mu.read_float()
        return self

class MuObject:
    def __init__(self):
        self.name = ""
        self.children = []
        self.materials = []
        self.textures = []
    def read(self, mu):
        print("MuObject")
        self.transform = MuTransform().read(mu)
        while True:
            try:
                entry_type = mu.read_int()
            except EOFError:
                break
            if entry_type == MuEnum.ET_CHILD_TRANSFORM_START:
                self.children.append(MuObject().read(mu))
            elif entry_type == MuEnum.ET_CHILD_TRANSFORM_END:
                break
            elif entry_type == MuEnum.ET_TAG_AND_LAYER:
                self.tag_and_layer = MuTagLayer().read(mu)
            elif entry_type in [MuEnum.ET_MESH_COLLIDER,
                                MuEnum.ET_SPHERE_COLLIDER,
                                MuEnum.ET_CAPSULE_COLLIDER,
                                MuEnum.ET_BOX_COLLIDER,
                                MuEnum.ET_MESH_COLLIDER2,
                                MuEnum.ET_SPHERE_COLLIDER2,
                                MuEnum.ET_CAPSULE_COLLIDER2,
                                MuEnum.ET_BOX_COLLIDER2,
                                MuEnum.ET_WHEEL_COLLIDER]:
                self.collider = MuCollider(entry_type).read(mu)
            elif entry_type == MuEnum.ET_MESH_FILTER:
                self.shared_mesh = MuMesh().read(mu)
            elif entry_type == MuEnum.ET_MESH_RENDERER:
                self.renderer = MuRenderer().read(mu)
            elif entry_type == MuEnum.ET_ANIMATION:
                self.animation = MuAnimation().read(mu)
            elif entry_type == MuEnum.ET_MATERIALS:
                mat_count = mu.read_int()
                for i in range(mat_count):
                    self.materials.append(MuMaterial().read(mu))
            elif entry_type == MuEnum.ET_TEXTURES:
                tex_count = mu.read_int()
                for i in range(tex_count):
                    self.textures.append(MuTexture().read(mu))
            else:
                print (entry_type, hex(mu.file.tell()))
        return self

class Mu:

    def read_byte(self, count=1):
        size = 1 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%dB" % count, data)
        if count == 1:
            return data[0]
        return data

    def read_int(self, count=1):
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%di" % count, data)
        if count == 1:
            return data[0]
        return data

    def read_float(self, count=1):
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%df" % count, data)
        if count == 1:
            return data[0]
        return data

    def read_bytes(self, size):
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        return data

    def read_string(self):
        size = self.read_byte()
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        s = ""
        for c in data:
            s = s + chr(c)
        return s

    def write_byte(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%dB" % len(data)), *data))

    def write_int(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%di" % len(data)), *data))

    def write_float(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%df" % len(data)), *data))

    def write_bytes(self, data, size=-1):
        if size == -1:
            size = len(data)
        self.file.write(data[:size])
        if size > len(data):
            self.file.write(bytes(size - len(data)))

    def write_string(self, data, size=-1):
        data = data.encode()
        size = len(data)
        if size > 255:
            size = 255  # just truncate for now (FIXME exception?)
        self.write_byte(data, size)
        self.write_bytes(data, size)

    def __init__(self, name = "mu"):
        self.name = name
        pass
    def read(self, filepath):
        self.file = open(filepath, "rb")
        self.magic, self.version = self.read_int(2)
        if (self.magic != MuEnum.MODEL_BINARY or self.version < 0
            or self.version > MuEnum.FILE_VERSION):
            return None
        self.name = self.read_string()
        print("version: %d '%s'" % (self.version, self.name))
        self.obj = MuObject().read(self)
        #self.read_materials()
        #self.read_textures()
        return self

if __name__ == "__main__":
    mu = Mu()
    mu.read("model.mu")
