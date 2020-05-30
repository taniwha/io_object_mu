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

from struct import pack, unpack

class BinaryReader:
    def __init__(self, file):
        self.file = file

    def close(self):
        self.file.close()

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

    def read_7int(self, count=1, force_list=False):
        def readval():
            val = 0
            mult = 1
            while True:
                valb = self.read_byte()
                val += (valb & 127) * mult
                if valb < 128:
                    break
                mult *= 128
            return val
        if count == 1 and not force_list:
            return readval()
        vals = [None] * count
        for i in range(count):
            vals[i] = readval()
        return vals

    def read_uint(self, count=1, force_list=False):
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%dI" % count, data)
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

class BinaryWriter:
    def __init__(self, file):
        self.file = file

    def close(self):
        self.file.close()

    def write_byte(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%dB" % len(data)), *data))

    def write_int(self, data):
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%di" % len(data)), *data))

    def write_7int(self, data):
        def writeval(val):
            if val < 0:
                val += 1 << 32
            val &= (1 << 32) - 1
            while val > 127:
                self.write_byte((val & 127) + 128)
                val >>= 7
            self.write_byte(val)
        if not hasattr(data, "__len__"):
            data = (data,)
        for d in data:
            writeval(d)

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

    def write_color(self, c):
        cb = tuple(map(lambda x: int(bound(0, x, 1) * 255), c))
        self.write_byte(cb)

    def write_bytes(self, data, size=-1):
        if size == -1:
            size = len(data)
        self.file.write(data[:size])
        if size > len(data):
            self.file.write(bytes(size - len(data)))

    def write_string(self, data, size=-1):
        data = data.encode()
        size = len(data)
        self.write_7int(size)
        self.write_bytes(data, size)
