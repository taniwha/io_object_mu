# KSP/Particles/Alpha Blended
import bpy
mat = bpy.context.material.mumatprop

mat.name = ''
mat.shaderName = 'KSP/Particles/Alpha Blended'
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
item.tex = 'white'
item = mat.color.properties.add()
item.name = '_TintColor'
item.value = (0.5, 0.5, 0.5, 0.5)
item = mat.float3.properties.add()
item.name = '_InvFade'
item.value = 1.0
