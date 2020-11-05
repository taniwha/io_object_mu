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
        """
        Initialize file

        Args:
            self: (todo): write your description
            file: (str): write your description
        """
        self.file = file

    def close(self):
        """
        Close the connection.

        Args:
            self: (todo): write your description
        """
        self.file.close()

    def read_byte(self, count=1, force_list=False):
        """
        Read a byte from the file.

        Args:
            self: (todo): write your description
            count: (int): write your description
            force_list: (list): write your description
        """
        size = 1 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%dB" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_int(self, count=1, force_list=False):
        """
        Reads an integer from the stream.

        Args:
            self: (todo): write your description
            count: (int): write your description
            force_list: (list): write your description
        """
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%di" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_7int(self, count=1, force_list=False):
        """
        Read bits as an unsigned integer.

        Args:
            self: (todo): write your description
            count: (int): write your description
            force_list: (list): write your description
        """
        def readval():
            """
            Reads a single value from the stream.

            Args:
            """
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
        """
        Reads a uint8 int.

        Args:
            self: (todo): write your description
            count: (int): write your description
            force_list: (list): write your description
        """
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%dI" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_float(self, count=1, force_list=False):
        """
        Reads a float.

        Args:
            self: (todo): write your description
            count: (int): write your description
            force_list: (list): write your description
        """
        size = 4 * count
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        data = unpack("<%df" % count, data)
        if count == 1 and not force_list:
            return data[0]
        return data

    def read_vector(self):
        """
        Reads the vector.

        Args:
            self: (todo): write your description
        """
        v = self.read_float(3)
        #convert from Unity's LHS to Blender's RHS
        v = v[0], v[2], v[1]
        return v

    def read_quaternion(self):
        """
        Reads the quaternion.

        Args:
            self: (todo): write your description
        """
        q = self.read_float(4)
        # Unity is xyzw, blender is wxyz. However, Unity is left-handed and
        # blender is right handed. To convert between LH and RH (either
        # direction), just swap y and z and reverse the rotation direction.
        q = q[3], -q[0], -q[2], -q[1]
        return q

    def read_tangent(self):
        """
        Reads a tang variable.

        Args:
            self: (todo): write your description
        """
        t = self.read_float(4)
        t = t[0], t[2], t[1], -t[3]
        return t

    def read_bytes(self, size):
        """
        Read at most size bytes from the file.

        Args:
            self: (todo): write your description
            size: (int): write your description
        """
        data = self.file.read(size)
        if len(data) < size:
            raise EOFError
        return data

class BinaryWriter:
    def __init__(self, file):
        """
        Initialize file

        Args:
            self: (todo): write your description
            file: (str): write your description
        """
        self.file = file

    def close(self):
        """
        Close the connection.

        Args:
            self: (todo): write your description
        """
        self.file.close()

    def write_byte(self, data):
        """
        Write a byte to the file.

        Args:
            self: (todo): write your description
            data: (todo): write your description
        """
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%dB" % len(data)), *data))

    def write_int(self, data):
        """
        Writes an int to the int.

        Args:
            self: (todo): write your description
            data: (todo): write your description
        """
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%di" % len(data)), *data))

    def write_7int(self, data):
        """
        Write a single byte array to the device.

        Args:
            self: (todo): write your description
            data: (todo): write your description
        """
        def writeval(val):
            """
            Write a value to the value.

            Args:
                val: (str): write your description
            """
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
        """
        Write an unsigned integer as an unsigned integer.

        Args:
            self: (todo): write your description
            data: (todo): write your description
        """
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%dI" % len(data)), *data))

    def write_float(self, data):
        """
        Writes float float to the float.

        Args:
            self: (todo): write your description
            data: (todo): write your description
        """
        if not hasattr(data, "__len__"):
            data = (data,)
        self.file.write(pack(("<%df" % len(data)), *data))

    def write_vector(self, v):
        """
        Write vector to vector.

        Args:
            self: (todo): write your description
            v: (array): write your description
        """
        #convert from Blender's RHS to Unity's LHS
        v = v[0], v[2], v[1]
        self.write_float(v)

    def write_quaternion(self, q):
        """
        Writes the quaternion to the quaternion.

        Args:
            self: (todo): write your description
            q: (todo): write your description
        """
        # Unity is xyzw, blender is wxyz. However, Unity is left-handed and
        # blender is right handed. To convert between LH and RH (either
        # direction), just swap y and z and reverse the rotation direction.
        q = -q[1], -q[3], -q[2], q[0]
        self.write_float(q)

    def write_tangent(self, t):
        """
        Writes a tangu.

        Args:
            self: (todo): write your description
            t: (todo): write your description
        """
        t = t[0], t[2], t[1], -t[3]
        self.write_float(t)

    def write_color(self, c):
        """
        Writes the color.

        Args:
            self: (todo): write your description
            c: (str): write your description
        """
        cb = tuple(map(lambda x: int(bound(0, x, 1) * 255), c))
        self.write_byte(cb)

    def write_bytes(self, data, size=-1):
        """
        Write given bytes to the file.

        Args:
            self: (todo): write your description
            data: (todo): write your description
            size: (int): write your description
        """
        if size == -1:
            size = len(data)
        self.file.write(data[:size])
        if size > len(data):
            self.file.write(bytes(size - len(data)))

    def write_string(self, data, size=-1):
        """
        Writes a string.

        Args:
            self: (todo): write your description
            data: (todo): write your description
            size: (int): write your description
        """
        data = data.encode()
        size = len(data)
        self.write_7int(size)
        self.write_bytes(data, size)
