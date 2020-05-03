import bpy
mat = bpy.context.material.mumatprop

mat.name = ''
mat.shaderName = 'KSP/InternalSpace'
mat.color.name = ''
mat.color.properties.clear()
item_sub_1 = mat.color.properties.add()
item_sub_1.name = '_SpecColor'
item_sub_1.value = (1.0, 1.0, 1.0, 1.0)
item_sub_1 = mat.color.properties.add()
item_sub_1.name = '_LightColor1'
item_sub_1.value = (0.0, 0.0, 0.0, 1.0)
item_sub_1 = mat.color.properties.add()
item_sub_1.name = '_LightColor2'
item_sub_1.value = (0.0, 0.0, 0.0, 1.0)
mat.color.index = 0
mat.color.expanded = False
mat.vector.name = ''
mat.vector.properties.clear()
mat.vector.index = 0
mat.vector.expanded = False
mat.float2.name = ''
mat.float2.properties.clear()
mat.float2.index = 0
mat.float2.expanded = False
mat.float3.name = ''
mat.float3.properties.clear()
item_sub_1 = mat.float3.properties.add()
item_sub_1.name = '_Shininess'
item_sub_1.value = 0.20000000298023224
item_sub_1 = mat.float3.properties.add()
item_sub_1.name = '_LightAmbient'
item_sub_1.value = 2.0
item_sub_1 = mat.float3.properties.add()
item_sub_1.name = '_Occlusion'
item_sub_1.value = 0.800000011920929
mat.float3.index = 0
mat.float3.expanded = False
mat.texture.name = ''
mat.texture.properties.clear()
item_sub_1 = mat.texture.properties.add()
item_sub_1.name = '_MainTex'
item_sub_1.tex = 'white'
item_sub_1.type = False
item_sub_1.rgbNorm = True
item_sub_1.scale = (1.0, 1.0)
item_sub_1.offset = (0.0, 0.0)
item_sub_1 = mat.texture.properties.add()
item_sub_1.name = '_BumpMap'
item_sub_1.tex = 'bump'
item_sub_1.type = False
item_sub_1.rgbNorm = False
item_sub_1.scale = (1.0, 1.0)
item_sub_1.offset = (0.0, 0.0)
item_sub_1 = mat.texture.properties.add()
item_sub_1.name = '_LightMap'
item_sub_1.tex = 'gray'
item_sub_1.type = False
item_sub_1.rgbNorm = True
item_sub_1.scale = (1.0, 1.0)
item_sub_1.offset = (0.0, 0.0)
mat.texture.index = 2
mat.texture.expanded = True
