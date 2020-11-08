import bpy
mat = bpy.context.material.mumatprop

mat.name = ''
mat.shaderName = 'KSP/UnlitColor'
mat.color.name = ''
mat.color.properties.clear()
item_sub_1 = mat.color.properties.add()
item_sub_1.name = '_Color'
item_sub_1.value = (1.0, 1.0, 1.0, 1.0)
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
mat.texture.name = ''
mat.texture.properties.clear()
mat.texture.index = 0
mat.texture.expanded = False
