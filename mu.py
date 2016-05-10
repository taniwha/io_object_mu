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

from struct import pack, unpack
class MuEnum:
    MODEL_BINARY = 76543
    FILE_VERSION = 4

    ET_CHILD_TRANSFORM_START = 0
    ET_CHILD_TRANSFORM_END = 1
    ET_ANIMATION = 2
    ET_MESH_COLLIDER = 3
    ET_SPHERE_COLLIDER = 4
    ET_CAPSULE_COLLIDER = 5
    ET_BOX_COLLIDER = 6
    ET_MESH_FILTER = 7
    ET_MESH_RENDERER = 8
    ET_SKINNED_MESH_RENDERER = 9
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
    ET_LIGHT = 23
    ET_TAG_AND_LAYER = 24
    ET_MESH_COLLIDER2 = 25
    ET_SPHERE_COLLIDER2 = 26
    ET_CAPSULE_COLLIDER2 = 27
    ET_BOX_COLLIDER2 = 28
    ET_WHEEL_COLLIDER = 29
    ET_CAMERA = 30
    ET_PARTICLES = 31
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
        'ET_PARTICLES':ET_PARTICLES,
    }

    ST_CUSTOM = 0
    ST_DIFFUSE = 1
    ST_SPECULAR = 2
    ST_BUMPED = 3
    ST_BUMPED_SPECULAR = 4
    ST_EMISSIVE = 5
    ST_EMISSIVE_SPECULAR = 6
    ST_EMISSIVE_BUMPED_SPECULAR = 7
    ST_ALPHA_CUTOFF = 8
    ST_ALPHA_CUTOFF_BUMPED = 9
    ST_ALPHA = 10
    ST_ALPHA_SPECULAR = 11
    ST_ALPHA_UNLIT = 12
    ST_UNLIT = 13
    ST_PARTICLES_ALPHA_BLENDED = 14
    ST_PARTICLES_ADDITIVE = 15
    SHADER_TYPES = {
        'ST_CUSTOM':ST_CUSTOM,
        'ST_DIFFUSE':ST_DIFFUSE,
        'ST_SPECULAR':ST_SPECULAR,
        'ST_BUMPED':ST_BUMPED,
        'ST_BUMPED_SPECULAR':ST_BUMPED_SPECULAR,
        'ST_EMISSIVE':ST_EMISSIVE,
        'ST_EMISSIVE_SPECULAR':ST_EMISSIVE_SPECULAR,
        'ST_EMISSIVE_BUMPED_SPECULAR':ST_EMISSIVE_BUMPED_SPECULAR,
        'ST_ALPHA_CUTOFF':ST_ALPHA_CUTOFF,
        'ST_ALPHA_CUTOFF_BUMPED':ST_ALPHA_CUTOFF_BUMPED,
        'ST_ALPHA':ST_ALPHA,
        'ST_ALPHA_SPECULAR':ST_ALPHA_SPECULAR,
        'ST_ALPHA_UNLIT':ST_ALPHA_UNLIT,
        'ST_UNLIT':ST_UNLIT,
        'ST_PARTICLES_ALPHA_BLENDED':ST_PARTICLES_ALPHA_BLENDED,
        'ST_PARTICLES_ADDITIVE':ST_PARTICLES_ADDITIVE,
    }
    ShaderNames = (
        "",
        "KSP/Diffuse",
        "KSP/Specular",
        "KSP/Bumped",
        "KSP/Bumped Specular",
        "KSP/Emissive/Diffuse",
        "KSP/Emissive/Specular",
        "KSP/Emissive/Bumped Specular",
        "KSP/Alpha/Cutoff",
        "KSP/Alpha/Cutoff Bumped",
        "KSP/Alpha/Translucent",
        "KSP/Alpha/Translucent Specular",
        "KSP/Alpha/Unlit Transparent",
        "KSP/Unlit",
        "KSP/Particles/Alpha Blended",
        "KSP/Particles/Additive",
    )

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
        #print("MuTexture")
        self.name = mu.read_string()
        self.type = mu.read_int()
        #print("   ", self.name, self.type)
        return self
    def write(self, mu):
        mu.write_string(self.name)
        mu.write_int(self.type)

class MuMatTex:
    def __init__(self):
        pass
    def read(self, mu):
        #print("MuMatTex")
        self.index = mu.read_int()
        self.scale = mu.read_float(2)
        self.offset = mu.read_float(2)
        return self
    def write(self, mu):
        mu.write_int(self.index)
        mu.write_float(self.scale)
        mu.write_float(self.offset)

def read_material4(self, mu):
    self.name = mu.read_string()
    self.shaderName = mu.read_string()
    num_properties = mu.read_int()
    #print("MuMaterial4", self.name, self.shaderName, num_properties)
    while num_properties > 0:
        propName = mu.read_string()
        propType = mu.read_int()
        if propType == 0:
            v = self.colorProperties[propName] = mu.read_float(4)
        elif propType == 1:
            v = self.vectorProperties[propName] = mu.read_float(4)
        elif propType == 2:
            v = self.floatProperties2[propName] = mu.read_float()
        elif propType == 3:
            v = self.floatProperties3[propName] = mu.read_float()
        elif propType == 4:
            v = self.textureProperties[propName] = MuMatTex().read(mu)
        #print("   ", propName, propType, v)
        num_properties -= 1
    return self

def read_material3(self, mu):
    self.name = mu.read_string()
    type = mu.read_int()
    self.shaderName = MuEnum.ShaderNames[type]
    if type == MuEnum.ST_SPECULAR:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.colorProperties["_SpecColor"] = mu.read_float(4)
        self.floatProperties3["_Shininess"] = mu.read_float()
    elif type == MuEnum.ST_BUMPED:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.textureProperties["_BumpMap"] = MuMatTex().read(mu)
    elif type == MuEnum.ST_BUMPED_SPECULAR:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.textureProperties["_BumpMap"] = MuMatTex().read(mu)
        self.colorProperties["_SpecColor"] = mu.read_float(4)
        self.floatProperties3["_Shininess"] = mu.read_float()
    elif type == MuEnum.ST_EMISSIVE:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.textureProperties["_Emissive"] = MuMatTex().read(mu)
        self.colorProperties["_EmissiveColor"] = mu.read_float(4)
    elif type == MuEnum.ST_EMISSIVE_SPECULAR:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.colorProperties["_SpecColor"] = mu.read_float(4)
        self.floatProperties3["_Shininess"] = mu.read_float()
        self.textureProperties["_Emissive"] = MuMatTex().read(mu)
        self.colorProperties["_EmissiveColor"] = mu.read_float(4)
    elif type == MuEnum.ST_EMISSIVE_BUMPED_SPECULAR:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.textureProperties["_BumpMap"] = MuMatTex().read(mu)
        self.colorProperties["_SpecColor"] = mu.read_float(4)
        self.floatProperties3["_Shininess"] = mu.read_float()
        self.textureProperties["_Emissive"] = MuMatTex().read(mu)
        self.colorProperties["_EmissiveColor"] = mu.read_float(4)
    elif type == MuEnum.ST_ALPHA_CUTOFF:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        #FIXME floatProperties2?
        self.floatProperties3["_Cutoff"] = mu.read_float()
    elif type == MuEnum.ST_ALPHA_CUTOFF_BUMPED:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.textureProperties["_BumpMap"] = MuMatTex().read(mu)
        #FIXME floatProperties2?
        self.floatProperties3["_Cutoff"] = mu.read_float()
    elif type == MuEnum.ST_ALPHA:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
    elif type == MuEnum.ST_ALPHA_SPECULAR:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        #FIXME floatProperties2?
        self.floatProperties3["_Gloss"] = mu.read_float()
        self.colorProperties["_SpecColor"] = mu.read_float(4)
        self.floatProperties3["_Shininess"] = mu.read_float()
    elif type == MuEnum.ST_ALPHA_UNLIT:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.colorProperties["_Color"] = mu.read_float(4)
    elif type == MuEnum.ST_UNLIT:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.colorProperties["_Color"] = mu.read_float(4)
    elif type == MuEnum.ST_DIFFUSE:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
    elif type == MuEnum.ST_PARTICLES_ALPHA_BLENDED:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.colorProperties["_Color"] = mu.read_float(4)
        #FIXME floatProperties3?
        self.floatProperties2["_InvFade"] = mu.read_float()
    elif type == MuEnum.ST_PARTICLES_ADDITIVE:
        self.textureProperties["_MainTex"] = MuMatTex().read(mu)
        self.colorProperties["_Color"] = mu.read_float(4)
        #FIXME floatProperties3?
        self.floatProperties2["_InvFade"] = mu.read_float()
    else:
        raise ValueError("MuMaterial %d" % self.type)
    return self

class MuMaterial:
    def __init__(self):
        self.colorProperties = {}
        self.vectorProperties = {}
        self.floatProperties2 = {}
        self.floatProperties3 = {}
        self.textureProperties = {}
        pass
    def read(self, mu):
        #print("MuMaterial")
        if mu.version >= 4:
            return read_material4(self, mu)
        else:
            return read_material3(self, mu)
    def write(self, mu):
        num_properties = (
            len(self.colorProperties)
            + len(self.vectorProperties)
            + len(self.floatProperties2)
            + len(self.floatProperties3)
            + len(self.textureProperties)
        )
        mu.write_string(self.name)
        mu.write_string(self.shaderName)
        mu.write_int(num_properties)
        for k in self.colorProperties:
            mu.write_string(k)
            mu.write_int(0)
            mu.write_float(self.colorProperties[k])
        for k in self.vectorProperties:
            mu.write_string(k)
            mu.write_int(1)
            mu.write_float(self.vectorProperties[k])
        for k in self.floatProperties2:
            mu.write_string(k)
            mu.write_int(2)
            mu.write_float(self.floatProperties2[k])
        for k in self.floatProperties3:
            mu.write_string(k)
            mu.write_int(3)
            mu.write_float(self.floatProperties3[k])
        for k in self.textureProperties:
            mu.write_string(k)
            mu.write_int(4)
            self.textureProperties[k].write(mu)

class MuTransform:
    def __init__(self):
        pass
    def read(self, mu):
        #print("MuTransform")
        self.name = mu.read_string()
        self.localPosition = mu.read_vector()
        self.localRotation = mu.read_quaternion()
        self.localScale = mu.read_vector()
        #print("   ", self.name, self.localPosition, self.localRotation,
        #      self.localScale)
        return self
    def write(self, mu):
        mu.write_string(self.name)
        mu.write_vector(self.localPosition)
        mu.write_quaternion(self.localRotation)
        mu.write_vector(self.localScale)

class MuTagLayer:
    def __init__(self):
        pass
    def read(self, mu):
        #print("MuTagLayer")
        self.tag = mu.read_string()
        self.layer = mu.read_int()
        #print("   ", self.tag, self.layer)
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_TAG_AND_LAYER)
        mu.write_string(self.tag)
        mu.write_int(self.layer)

class MuKey:
    def __init__(self):
        pass
    def read(self, mu):
        #print("MuKey")
        self.time = mu.read_float()
        self.value = mu.read_float()
        self.tangent = mu.read_float(2) # in, out
        self.tangentMode = mu.read_int()
        # editable, smooth, linear, stepped (0..3?)
        #print("   ", self.time, self.value, self.tangent, self.tangentMode)
        return self
    def write(self, mu):
        mu.write_float(self.time)
        mu.write_float(self.value)
        mu.write_float(self.tangent)
        mu.write_int(self.tangentMode)

class MuCurve:
    def __init__(self):
        pass
    def read(self, mu):
        #print("MuCurve")
        self.path = mu.read_string()
        self.property = mu.read_string()
        self.type = mu.read_int()
        self.wrapMode = mu.read_int(2)  # pre, post
        #print("   ", self.path, self.property, self.type, self.wrapMode)
        num_keys = mu.read_int()
        #print(num_keys)
        self.keys = []
        for i in range(num_keys):
            self.keys.append(MuKey().read(mu))
        return self
    def write(self, mu):
        mu.write_string(self.path)
        mu.write_string(self.property)
        mu.write_int(self.type)
        mu.write_int(self.wrapMode)
        mu.write_int(len(self.keys))
        for key in self.keys:
            key.write(mu)

class MuClip:
    def __init__(self):
        self.curves = []
    def read(self, mu):
        #print("MuClip")
        self.name = mu.read_string()
        self.lbCenter = mu.read_vector()
        self.lbSize = mu.read_vector()
        self.wrapMode = mu.read_int()
        #print("   ", self.name, self.lbCenter, self.lbSize, self.wrapMode)
        num_curves = mu.read_int()
        for i in range(num_curves):
            self.curves.append(MuCurve().read(mu))
        return self
    def write(self, mu):
        mu.write_string(self.name)
        mu.write_vector(self.lbCenter)
        mu.write_vector(self.lbSize)
        mu.write_int(self.wrapMode)
        mu.write_int(len(self.curves))
        for curve in self.curves:
            curve.write(mu)

class MuAnimation:
    def __init__(self):
        self.clips = []
    def read(self, mu):
        #print("MuAnimation")
        num_clips = mu.read_int()
        for i in range(num_clips):
            self.clips.append(MuClip().read(mu))
        self.clip = mu.read_string()
        self.autoPlay = mu.read_byte()
        #print(self.clip, self.autoPlay)
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_ANIMATION)
        mu.write_int(len(self.clips))
        for clip in self.clips:
            clip.write(mu)
        mu.write_string(self.clip)
        mu.write_byte(self.autoPlay)  #XXX is this right?

class MuBoneWeight:
    def __init__(self):
        self.indices = []
        self.weights = []
    def read(self, mu):
        for i in range(4):
            self.indices.append(mu.read_int())
            self.weights.append(mu.read_float())
        return self
    def write(self, mu):
        for i in range(4):
            mu.write_int(self.indices[i])
            mu.write_float(self.weights[i])

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
        #print("MuMesh")
        start = mu.read_int()
        if start != MuEnum.ET_MESH_START:
            raise
        num_verts, submesh_count = mu.read_int(2)
        while True:
            type = mu.read_int()
            if type == MuEnum.ET_MESH_END:
                break
            elif type == MuEnum.ET_MESH_VERTS:
                #print("    verts")
                for i in range(num_verts):
                    self.verts.append(mu.read_vector())
            elif type == MuEnum.ET_MESH_UV:
                #print("    uvs")
                for i in range(num_verts):
                    self.uvs.append(mu.read_float(2))
            elif type == MuEnum.ET_MESH_UV2:
                #print("    uv2s")
                for i in range(num_verts):
                    self.uv2s.append(mu.read_float(2))
            elif type == MuEnum.ET_MESH_NORMALS:
                #print("    normals")
                for i in range(num_verts):
                    self.normals.append(mu.read_vector())
            elif type == MuEnum.ET_MESH_TANGENTS:
                #print("    tangents")
                for i in range(num_verts):
                    self.tangents.append(mu.read_tangent())
            elif type == MuEnum.ET_MESH_BONE_WEIGHTS:
                #print("    bone weights")
                for i in range(num_verts):
                    self.boneWeights.append(MuBoneWeight().read(mu))
            elif type == MuEnum.ET_MESH_BIND_POSES:
                #print("    bind poses")
                num_poses = mu.read_int()
                for i in range(num_poses):
                    self.bindPoses.append(mu.read_float(16))
            elif type == MuEnum.ET_MESH_TRIANGLES:
                #print("    sub mesh")
                num_tris = mu.read_int()
                tris = []
                for i in range(int(num_tris / 3)):   #FIXME is this guaranteed?
                    tri = mu.read_int(3)
                    #reverse the triangle winding for Blender (because of the
                    # LHS/RHS swap)
                    #avoid putting 0 at the end of the list (Blender doesn't
                    #like that)
                    if not tri[0]:
                        tri = tri[0], tri[2], tri[1]
                    else:
                        tri = tri[2], tri[1], tri[0]
                    tris.append(tri)
                self.submeshes.append(tris)
            else:
                raise ValueError("MuMesh %x %d" % (mu.file.tell(), type))
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_MESH_START)
        mu.write_int(len(self.verts))
        mu.write_int(len(self.submeshes))

        mu.write_int(MuEnum.ET_MESH_VERTS)
        for v in self.verts:
            mu.write_vector(v)
        if len(self.uvs) == len(self.verts):
            mu.write_int(MuEnum.ET_MESH_UV)
            for uv in self.uvs:
                mu.write_float(uv)
        if len(self.uv2s) == len(self.verts):
            mu.write_int(MuEnum.ET_MESH_UV2)
            for uv in self.uv2s:
                mu.write_float(uv)
        if len(self.normals) == len(self.verts):
            mu.write_int(MuEnum.ET_MESH_NORMALS)
            for n in self.normals:
                mu.write_vector(n)
        if len(self.tangents) == len(self.verts):
            mu.write_int(MuEnum.ET_MESH_TANGENTS)
            for t in self.tangents:
                mu.write_tangent(t)
        if len(self.boneWeights) == len(self.verts):
            mu.write_int(MuEnum.ET_MESH_BONE_WEIGHTS)
            for bw in self.boneWeights:
                bw.write(mu)
        if len(self.bindPoses):
            mu.write_int(MuEnum.ET_MESH_BIND_POSES)
            mu.write_int(len(self.bindPoses))
            for bp in self.bindPoses:
                mu.write_float(bp)
        for sm in self.submeshes:
            mu.write_int(MuEnum.ET_MESH_TRIANGLES)
            mu.write_int(len(sm) * 3)
            for tri in sm:
                #reverse the triangle winding for Blender (because of the
                # LHS/RHS swap)
                tri = tri[0], tri[2], tri[1]
                mu.write_int(tri)
        mu.write_int(MuEnum.ET_MESH_END)

class MuRenderer:
    def __init__(self):
        self.castShadows = 1
        self.receiveShadows = 1
    def read(self, mu):
        if mu.version > 0:
            self.castShadows = mu.read_byte()
            self.receiveShadows = mu.read_byte()
        num_mat = mu.read_int()
        self.materials = mu.read_int(num_mat, True)
        #print(self.castShadows, self.receiveShadows, self.materials)
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_MESH_RENDERER)
        mu.write_byte(self.castShadows)
        mu.write_byte(self.receiveShadows)
        mu.write_int(len(self.materials))
        mu.write_int(self.materials)

class MuSkinnedMeshRenderer:
    def __init__(self):
        self.materials = []
        self.bones = []
    def read(self, mu):
        num_mat = mu.read_int()
        for i in range(num_mat):
            self.materials.append(mu.read_int())
        self.center = mu.read_vector()
        self.size = mu.read_vector()
        self.quality = mu.read_int()
        self.updateWhenOffscreen = mu.read_byte()
        nBones = mu.read_int()
        for i in range(nBones):
            self.bones.append(mu.read_string())
        self.mesh = MuMesh().read(mu)
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_SKINNED_MESH_RENDERER)
        mu.write_int(len(self.materials))
        mu.write_int(self.materials)
        mu.write_vector(self.center)
        mu.write_vector(self.size)
        mu.write_int(self.quality)
        mu.write_byte(self.updateWhenOffscreen)
        mu.write_int(len(self.bones))
        for bone in self.bones:
            mu.write_string(bone)
        self.mesh.write(mu)

class MuCollider_Base:
    def __init__(self, type):
        self.type = type

class MuColliderMesh(MuCollider_Base):
    def read(self, mu):
        #print("MuColliderMesh", self.type)
        #print(self.isTrigger, self.convex)
        self.isTrigger = 0
        if self.type:
            self.isTrigger = mu.read_byte()
        self.convex = mu.read_byte()
        self.mesh = MuMesh().read(mu)
        return self
    def write(self, mu):
        if self.type:
            mu.write_int(MuEnum.ET_MESH_COLLIDER2)
            mu.write_byte(self.isTrigger)
        else:
            mu.write_int(MuEnum.ET_MESH_COLLIDER)
        mu.write_byte(self.convex)
        self.mesh.write(mu)

class MuColliderSphere(MuCollider_Base):
    def read(self, mu):
        #print("MuColliderSphere", self.type)
        self.isTrigger = 0
        if self.type:
            self.isTrigger = mu.read_byte()
        self.radius = mu.read_float()
        self.center = mu.read_vector()
        #print(self.isTrigger, self.radius, self.center)
        return self
    def write(self, mu):
        if self.type:
            mu.write_int(MuEnum.ET_SPHERE_COLLIDER2)
            mu.write_byte(self.isTrigger)
        else:
            mu.write_int(MuEnum.ET_SPHERE_COLLIDER)
        mu.write_float(self.radius)
        mu.write_vector(self.center)

class MuColliderCapsule(MuCollider_Base):
    def read(self, mu):
        #print("MuColliderCapsule", self.type)
        self.isTrigger = 0
        if self.type:
            self.isTrigger = mu.read_byte()
        self.radius = mu.read_float()
        self.height = mu.read_float()
        self.direction = mu.read_int()
        self.center = mu.read_vector()
        return self
    def write(self, mu):
        if self.type:
            mu.write_int(MuEnum.ET_CAPSULE_COLLIDER2)
            mu.write_byte(self.isTrigger)
        else:
            mu.write_int(MuEnum.ET_CAPSULE_COLLIDER)
        mu.write_float(self.radius)
        mu.write_float(self.height)
        mu.write_int(self.direction)
        mu.write_vector(self.center)

class MuColliderBox(MuCollider_Base):
    def read(self, mu):
        #print("MuColliderBox", self.type)
        self.isTrigger = 0
        if self.type:
            self.isTrigger = mu.read_byte()
        self.size = mu.read_vector()
        self.center = mu.read_vector()
        #print(self.isTrigger, self.size, self.center)
        return self
    def write(self, mu):
        if self.type:
            mu.write_int(MuEnum.ET_BOX_COLLIDER2)
            mu.write_byte(self.isTrigger)
        else:
            mu.write_int(MuEnum.ET_BOX_COLLIDER)
        mu.write_vector(self.size)
        mu.write_vector(self.center)

class MuSpring:
    def __init__(self):
        pass
    def read(self, mu):
        self.spring = mu.read_float()
        self.damper = mu.read_float()
        self.targetPosition = mu.read_float()
        return self
    def write(self, mu):
        mu.write_float(self.spring)
        mu.write_float(self.damper)
        mu.write_float(self.targetPosition)

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
    def write(self, mu):
        mu.write_float(self.extremumSlip)
        mu.write_float(self.extremumValue)
        mu.write_float(self.asymptoteSlip)
        mu.write_float(self.asymptoteValue)
        mu.write_float(self.stiffness)

class MuColliderWheel(MuCollider_Base):
    def __init__(self):
        MuCollider_Base.__init__(self, 0)
    def read(self, mu):
        #print("MuColliderWheel")
        self.mass = mu.read_float()
        self.radius = mu.read_float()
        self.suspensionDistance = mu.read_float()
        self.center = mu.read_vector()
        self.suspensionSpring = MuSpring().read(mu)
        self.forwardFriction = MuFriction().read(mu)
        self.sidewaysFriction = MuFriction().read(mu)
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_WHEEL_COLLIDER)
        mu.write_float(self.mass)
        mu.write_float(self.radius)
        mu.write_float(self.suspensionDistance)
        mu.write_vector(self.center)
        self.suspensionSpring.write(mu)
        self.forwardFriction.write(mu)
        self.sidewaysFriction.write(mu)

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

class MuCamera:
    def __init__(self):
        pass
    def read(self, mu):
        self.clearFlags = mu.read_int()
        self.backgroundColor = mu.read_float(4)
        self.cullingMask = mu.read_int()
        self.orthographic = mu.read_byte()
        self.fov = mu.read_float()
        self.near = mu.read_float()
        self.far = mu.read_float()
        self.dept = mu.read_float()
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_CAMERA)
        mu.write_int(self.clearFlags)
        mu.write_float(self.backgroundColor)
        mu.write_int(self.cullingMask)
        mu.write_int(self.orthographic)
        mu.write_float(self.fov)
        mu.write_float(self.near)
        mu.write_float(self.far)
        mu.write_float(self.dept)

class MuParticles:
    def __init__(self):
        pass
    def read(self, mu):
        self.emit = mu.read_byte()
        self.shape = mu.read_int()
        self.shape3d = mu.read_vector()
        self.shape2d = mu.read_float(2)
        self.shape1d = mu.read_float()
        self.color = mu.read_float(4)
        self.useUorldSpace = mu.read_byte()
        self.size = mu.read_float(2)    #min, max
        self.energy = mu.read_float(2)  #min, max
        self.emission = mu.read_int(2)  #min, max
        self.worldVelocity = mu.read_vector()
        self.localVelocity = mu.read_vector()
        self.rndVelocity = mu.read_vector()
        self.emitterVelocityScale = mu.read_float()
        self.angularVelocity = mu.read_float()
        self.rndAngularVelocity = mu.read_float()
        self.rndRotation = mu.read_byte()
        self.doesAnimateColor = mu.read_byte()
        self.colorAnimation = [None]*5
        for i in range(5):
            self.colorAnimation[i] = mu.read_float(4)
        self.worldRotationAxis = mu.read_vector()
        self.localRotationAxis = mu.read_vector()
        self.sizeGrow = mu.read_float()
        self.rndForce = mu.read_vector()
        self.force = mu.read_vector()
        self.damping = mu.read_float()
        self.castShadows = mu.read_byte()
        self.recieveShadows = mu.read_byte()
        self.lengthScale = mu.read_float()
        self.velocityScale = mu.read_float()
        self.maxParticleSize = mu.read_float()
        self.particleRenderMode = mu.read_int()
        self.uvAnimation = mu.read_int(3) #xtile, ytile, cycles
        self.count = mu.read_int()
        return self
    def write(self, mu):
        mu.write_byte(self.emit)
        mu.write_int(self.shape)
        mu.write_vector(self.shape3d)
        mu.write_float(self.shape2d)
        mu.write_float(self.shape1d)
        mu.write_float(self.color)
        mu.write_byte(self.useUorldSpace)
        mu.write_float(self.size)
        mu.write_float(self.energy)
        mu.write_int(self.emission)
        mu.write_vector(self.worldVelocity)
        mu.write_vector(self.localVelocity)
        mu.write_vector(self.rndVelocity)
        mu.write_float(self.emitterVelocityScale)
        mu.write_float(self.angularVelocity)
        mu.write_float(self.rndAngularVelocity)
        mu.write_byte(self.rndRotation)
        mu.write_byte(self.doesAnimateColor)
        for i in range(5):
            mu.write_float(self.colorAnimation[i])
        mu.write_vector(self.worldRotationAxis)
        mu.write_vector(self.localRotationAxis)
        mu.write_float(self.sizeGrow)
        mu.write_vector(self.rndForce)
        mu.write_vector(self.force)
        mu.write_float(self.damping)
        mu.write_byte(self.castShadows)
        mu.write_byte(self.recieveShadows)
        mu.write_float(self.lengthScale)
        mu.write_float(self.velocityScale)
        mu.write_float(self.maxParticleSize)
        mu.write_int(self.particleRenderMode)
        mu.write_int(self.uvAnimation)
        mu.write_int(self.count)

class MuLight:
    def __init__(self):
        pass
    def read(self, mu):
        self.type = mu.read_int()
        self.intensity = mu.read_float()
        self.range = mu.read_float()
        self.color = mu.read_float(4)
        self.cullingMask = mu.read_int()
        if mu.version > 1:
            self.spotAngle = mu.read_float()
        return self
    def write(self, mu):
        mu.write_int(MuEnum.ET_LIGHT)
        mu.write_int(self.type)
        mu.write_float(self.intensity)
        mu.write_float(self.range)
        mu.write_float(self.color)
        mu.write_uint(self.cullingMask)
        mu.write_float(self.spotAngle)

class MuObject:
    def __init__(self, name=""):
        self.name = name
        self.children = []
    def read(self, mu):
        #print("MuObject")
        self.transform = MuTransform().read(mu)
        while True:
            try:
                entry_type = mu.read_int()
            except EOFError:
                break
            #print(entry_type, hex(mu.file.tell()))
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
            elif entry_type == MuEnum.ET_SKINNED_MESH_RENDERER:
                self.skinned_mesh_renderer = MuSkinnedMeshRenderer().read(mu)
            elif entry_type == MuEnum.ET_ANIMATION:
                self.animation = MuAnimation().read(mu)
            elif entry_type == MuEnum.ET_CAMERA:
                self.camera = MuCamera().read(mu)
            elif entry_type == MuEnum.ET_PARTICLES:
                self.particles = MuParticles().read(mu)
            elif entry_type == MuEnum.ET_LIGHT:
                self.light = MuLight().read(mu)
            elif entry_type == MuEnum.ET_MATERIALS:
                mat_count = mu.read_int()
                for i in range(mat_count):
                    mat = MuMaterial().read(mu)
                    mu.materials.append(mat)
            elif entry_type == MuEnum.ET_TEXTURES:
                tex_count = mu.read_int()
                for i in range(tex_count):
                    mu.textures.append(MuTexture().read(mu))
            else:
                #print(entry_type, hex(mu.file.tell()))
                pass
        return self
    def write(self, mu):
        self.transform.write(mu)
        self.tag_and_layer.write(mu)
        if hasattr(self, "collider"):
            self.collider.write(mu)
        if hasattr(self, "shared_mesh"):
            mu.write_int(MuEnum.ET_MESH_FILTER)
            self.shared_mesh.write(mu)
        if hasattr(self, "renderer"):
            self.renderer.write(mu)
        if hasattr(self, "skinned_mesh_renderer"):
            self.skinned_mesh_renderer.write(mu)
        if hasattr(self, "animation"):
            self.animation.write(mu)
        if hasattr(self, "camera"):
            self.camera.write(mu)
        if hasattr(self, "light"):
            self.light.write(mu)
        for child in self.children:
            mu.write_int(MuEnum.ET_CHILD_TRANSFORM_START)
            child.write(mu)
            mu.write_int(MuEnum.ET_CHILD_TRANSFORM_END)

class Mu:

    def read_byte(self, count=1, force_list=False):
        size = 1 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%dB" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_int(self, count=1, force_list=False):
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%di" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_float(self, count=1, force_list=False):
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%df" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_vector(self):
        v = self.read_float(3)
        #convert from Unity's LHS to Blender's RHS
        v = v[0], v[2], v[1]
        return v

    def read_quaternion(self):
        q = self.read_float(4)
        # Unity is xyzw, blender is wxyz. However, Unity is left-handed and
        # blender is right handed. To convert between LH and RH (either
        # direction), just swap y and z and reverse the rotation direction.
        q = q[3], -q[0], -q[2], -q[1]
        return q

    def read_tangent(self):
        t = self.read_float(4)
        t = t[0], t[2], t[1], -t[3]
        return t

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
        if type(data) == type(""):
            return data
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

    def write_uint(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%dI" % len(data)), *data))

    def write_float(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%df" % len(data)), *data))

    def write_vector(self, v):
        #convert from Blender's RHS to Unity's LHS
        v = v[0], v[2], v[1]
        self.write_float(v)

    def write_quaternion(self, q):
        # Unity is xyzw, blender is wxyz. However, Unity is left-handed and
        # blender is right handed. To convert between LH and RH (either
        # direction), just swap y and z and reverse the rotation direction.
        q = -q[1], -q[3], -q[2], q[0]
        self.write_float(q)

    def write_tangent(self, t):
        t = t[0], t[2], t[1], -t[3]
        self.write_float(t)

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
        self.write_byte(size)
        self.write_bytes(data, size)

    def __init__(self, name = "mu"):
        self.name = name
        pass
    def read(self, filepath):
        self.materials = []
        self.textures = []
        self.file = open(filepath, "rb")
        self.magic, self.version = self.read_int(2)
        if (self.magic != MuEnum.MODEL_BINARY or self.version < 0
            or self.version > MuEnum.FILE_VERSION):
            return None
        self.name = self.read_string()
        #print("version: %d '%s'" % (self.version, self.name))
        self.obj = MuObject().read(self)
        #self.read_materials()
        #self.read_textures()
        del self.file
        return self
    def write(self, filepath):
        self.file = open(filepath, "wb")
        self.write_int(MuEnum.MODEL_BINARY)
        self.write_int(MuEnum.FILE_VERSION)
        self.write_string(self.name)
        self.obj.write(self)
        if len(self.materials):
            self.write_int(MuEnum.ET_MATERIALS)
            self.write_int(len(self.materials))
            for mat in self.materials:
                mat.write(self)
        if len(self.textures):
            self.write_int(MuEnum.ET_TEXTURES)
            self.write_int(len(self.textures))
            for tex in self.textures:
                tex.write(self)
        del self.file

if __name__ == "__main__":
    mu = Mu()
    mu.read("model.mu")
    #mu.write("write.mu")
