'''
Helpers for reading/writing tagged block files.

Copyright (c) 2023 Rick Lupton

Permission is hereby granted, free of charge, to any person obtaining a 
copy of this software and associated documentation files (the 
"Software"), to deal in the Software without restriction, including 
without limitation the rights to use, copy, modify, merge, publish, 
distribute, sublicense, and/or sell copies of the Software, and to 
permit persons to whom the Software is furnished to do so, subject to 
the following conditions:

The above copyright notice and this permission notice shall be included 
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS 
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF 
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. 
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY 
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, 
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE 
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
import enum
import logging
import struct
import typing as tp
from functools import total_ordering
_logger = logging.getLogger(__name__)
HEADER_V6 = b'reMarkable .lines file, version=6          '

class TagType(enum.IntEnum):
    """Tag type representing the type of following data."""
    ID = 15
    Length4 = 12
    Byte8 = 8
    Byte4 = 4
    Byte1 = 1

class UnexpectedBlockError(Exception):
    """Unexpected tag or index in block stream."""

@total_ordering
class CrdtId:
    """An identifier or timestamp."""
    __match_args__ = ('part1', 'part2')

    def __init__(self, part1 , part2 )  :
        object.__setattr__(self, 'part1', part1)
        object.__setattr__(self, 'part2', part2)

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(part1={self.part1!r}, part2={self.part2!r})'

    def __eq__(self, other):
        if not isinstance(other, CrdtId):
            return NotImplemented
        return (self.part1, self.part2) == (other.part1, other.part2)

    def __lt__(self, other):
        if not isinstance(other, CrdtId):
            return NotImplemented
        return (self.part1, self.part2) < (other.part1, other.part2)

    def __hash__(self):
        return hash((self.part1, self.part2))

    def __setattr__(self, name, value):
        raise AttributeError(f"Can't set attribute {name!r}")

    def __delattr__(self, name):
        raise AttributeError(f"Can't delete attribute {name!r}")

    def __repr__(self)  :
        return f'CrdtId({self.part1}, {self.part2})'

class DataStream:
    """Read basic values from a remarkable v6 file stream."""

    def __init__(self, data ):
        self.data = data

    def tell(self)  :
        return self.data.tell()

    def read_header(self)  :
        """Read the file header.

        This should be the first call when starting to read a new file.

        """
        header = self.read_bytes(len(HEADER_V6))
        if header != HEADER_V6:
            raise ValueError('Wrong header: %r' % header)

    def write_header(self)  :
        """Write the file header.

        This should be the first call when starting to read a new file.

        """
        self.write_bytes(HEADER_V6)

    def check_tag(self, expected_index , expected_type )  :
        """Check that INDEX and TAG_TYPE are next.

        Returns True if the expected index and tag type are found. Does not
        advance the stream.

        """
        pos = self.data.tell()
        try:
            index, tag_type = self._read_tag_values()
            return index == expected_index and tag_type == expected_type
        except (ValueError, EOFError):
            return False
        finally:
            self.data.seek(pos)

    def read_tag(self, expected_index , expected_type )   :
        """Read a tag from the stream.

        Raise an error if the expected index and tag type are not found, and
        rewind the stream.

        """
        pos = self.data.tell()
        index, tag_type = self._read_tag_values()
        if index != expected_index:
            self.data.seek(pos)
            raise UnexpectedBlockError('Expected index %d, got %d, at position %d' % (expected_index, index, self.data.tell()))
        if tag_type != expected_type:
            self.data.seek(pos)
            raise UnexpectedBlockError('Expected tag type %s (0x%X), got 0x%X at position %d' % (expected_type.name, expected_type.value, tag_type, self.data.tell()))
        return (index, tag_type)

    def _read_tag_values(self)   :
        """Read tag values from the stream."""
        x = self.read_varuint()
        index = x >> 4
        tag_type = x & 15
        try:
            tag_type = TagType(tag_type)
        except ValueError as e:
            raise ValueError('Bad tag type 0x%X at position %d' % (tag_type, self.data.tell()))
        return (index, tag_type)

    def write_tag(self, index , tag_type ):
        """Write a tag to the stream."""
        x = index << 4 | int(tag_type)
        self.write_varuint(x)

    def read_bytes(self, n )  :
        """Read `n` bytes, raising `EOFError` if there are not enough."""
        result = self.data.read(n)
        if len(result) != n:
            raise EOFError()
        return result

    def write_bytes(self, b ):
        """Write bytes to underlying stream."""
        self.data.write(b)

    def _read_struct(self, pattern ):
        pattern = '<' + pattern
        n = struct.calcsize(pattern)
        return struct.unpack(pattern, self.read_bytes(n))[0]

    def _write_struct(self, pattern , value):
        pattern = '<' + pattern
        self.data.write(struct.pack(pattern, value))

    def read_bool(self)  :
        """Read a bool from the data stream."""
        return self._read_struct('?')

    def read_uint8(self)  :
        """Read a uint8 from the data stream."""
        return self._read_struct('B')

    def read_uint16(self)  :
        """Read a uint16 from the data stream."""
        return self._read_struct('H')

    def read_uint32(self)  :
        """Read a uint32 from the data stream."""
        return self._read_struct('I')

    def read_float32(self)  :
        """Read a float32 from the data stream."""
        return self._read_struct('f')

    def read_float64(self)  :
        """Read a float64 (double) from the data stream."""
        return self._read_struct('d')

    def read_varuint(self)  :
        """Read a varuint from the data stream."""
        shift = 0
        result = 0
        while True:
            i = ord(self.read_bytes(1))
            result |= (i & 127) << shift
            shift += 7
            if not i & 128:
                break
        return result

    def read_crdt_id(self)  :
        part1 = self.read_uint8()
        part2 = self.read_varuint()
        return CrdtId(part1, part2)

    def write_bool(self, value ):
        """Write a bool to the data stream."""
        self._write_struct('?', value)

    def write_uint8(self, value ):
        """Write a uint8 to the data stream."""
        return self._write_struct('B', value)

    def write_uint16(self, value ):
        """Write a uint16 to the data stream."""
        return self._write_struct('H', value)

    def write_uint32(self, value ):
        """Write a uint32 to the data stream."""
        return self._write_struct('I', value)

    def write_float32(self, value ):
        """Write a float32 to the data stream."""
        return self._write_struct('f', value)

    def write_float64(self, value ):
        """Write a float64 (double) to the data stream."""
        return self._write_struct('d', value)

    def write_varuint(self, value ):
        """Write a varuint to the data stream."""
        if value < 0:
            raise ValueError('value is negative')
        b = bytearray()
        while True:
            to_write = value & 127
            value >>= 7
            if value:
                b.append(to_write | 128)
            else:
                b.append(to_write)
                break
        self.data.write(b)

    def write_crdt_id(self, value ):
        """Write a `CrdtId` to the data stream."""
        if value.part1 >= 2 ** 8 or value.part2 >= 2 ** 64:
            raise ValueError('CrdtId too large: %s' % value)
        self.write_uint8(value.part1)
        self.write_varuint(value.part2)
_T = tp.TypeVar('_T')

class LwwValue(tp.Generic[_T]):
    """Container for a last-write-wins value."""
    __match_args__ = ('timestamp', 'value')

    def __init__(self, timestamp , value )  :
        object.__setattr__(self, 'timestamp', timestamp)
        object.__setattr__(self, 'value', value)

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(timestamp={self.timestamp!r}, value={self.value!r})'

    def __eq__(self, other):
        if not isinstance(other, LwwValue):
            return NotImplemented
        return (self.timestamp, self.value) == (other.timestamp, other.value)

    def __hash__(self):
        return hash((self.timestamp, self.value))

    def __setattr__(self, name, value):
        raise AttributeError(f"Can't set attribute {name!r}")

    def __delattr__(self, name):
        raise AttributeError(f"Can't delete attribute {name!r}")
