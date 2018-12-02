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

from ..mu import MuMaterial, MuTexture, MuMatTex

def make_texture(mu, tex):
    if tex.tex and tex.tex not in mu.textures:
        mutex = MuTexture()
        mutex.name = tex.tex
        mutex.type = tex.type
        mutex.index = len(mu.textures)
        mu.textures[tex.tex] = mutex
    mattex = MuMatTex()
    if tex.tex:
        mattex.index = mu.textures[tex.tex].index
    else:
        mattex.index = -1
    mattex.scale = list(tex.scale)
    mattex.offset = list(tex.offset)
    return mattex

def make_property(blendprop):
    muprop = {}
    for item in blendprop:
        if type(item.value) is float:
            muprop[item.name] = item.value
        else:
            muprop[item.name] = list(item.value)
    return muprop

def make_tex_property(mu, blendprop):
    muprop = {}
    for item in blendprop:
        muprop[item.name] = make_texture(mu, item)
    return muprop

def make_material(mu, mat):
    material = MuMaterial()
    material.name = mat.name
    material.index = len(mu.materials)
    matprops = mat.mumatprop
    material.shaderName = matprops.shaderName
    material.colorProperties = make_property(matprops.color.properties)
    material.vectorProperties = make_property(matprops.vector.properties)
    material.floatProperties2 = make_property(matprops.float2.properties)
    material.floatProperties3 = make_property(matprops.float3.properties)
    material.textureProperties = make_tex_property(mu, matprops.texture.properties)
    return material
