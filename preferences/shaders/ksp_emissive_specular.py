# KSP/Emissive/Specular
import bpy
mat = bpy.context.material.mumatprop

mat.name = ''
mat.shaderName = 'KSP/Emissive/Specular'
mat.texture.name = ''
mat.texture.properties.clear()
mat.texture.index = 0
mat.texture.expanded = False
mat.color.name = ''
mat.color.properties.clear()
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
mat.float3.index = 0
mat.float3.expanded = False
item = mat.texture.properties.add()
item.name = '_MainTex'
item.tex = 'gray'
item = mat.color.properties.add()
item.name = '_Color'
item.value = (1, 1, 1, 1)
item = mat.texture.properties.add()
item.name = '_Emissive'
item.tex = 'white'
item = mat.color.properties.add()
item.name = '_EmissiveColor'
item.value = (0, 0, 0, 1)
item = mat.color.properties.add()
item.name = '_SpecColor'
item.value = (0.5, 0.5, 0.5, 1)
item = mat.float3.properties.add()
item.name = '_Shininess'
item.value = 0.4
