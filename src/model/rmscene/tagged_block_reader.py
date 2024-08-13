'''
Read structure of remarkable .rm files version 6.

Based on my investigation of the format with lots of help from ddvk's 
v6 reader code.

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
import logging
import typing as tp
from .tagged_block_common import DataStream, TagType, CrdtId, UnexpectedBlockError, LwwValue
_logger = logging.getLogger(__name__)

class BlockInfo:
    """Base class for block/subblock info."""
    __match_args__ = ('offset', 'size', 'extra_data')

    def __init__(self, offset , size , *, extra_data =b'')  :
        self.offset = offset
        self.size = size
        self.extra_data = extra_data

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(offset={self.offset!r}, size={self.size!r}, extra_data={self.extra_data!r})'

    def __eq__(self, other):
        if not isinstance(other, BlockInfo):
            return NotImplemented
        return (self.offset, self.size, self.extra_data) == (other.offset, other.size, other.extra_data)

class MainBlockInfo(BlockInfo):
    """Top-level block info."""
    __match_args__ = ('offset', 'size', 'extra_data', 'block_type', 'min_version', 'current_version')

    def __init__(self, offset , size , block_type , min_version , current_version , *, extra_data =b'')  :
        self.offset = offset
        self.size = size
        self.extra_data = extra_data
        self.block_type = block_type
        self.min_version = min_version
        self.current_version = current_version

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(offset={self.offset!r}, size={self.size!r}, extra_data={self.extra_data!r}, block_type={self.block_type!r}, min_version={self.min_version!r}, current_version={self.current_version!r})'

    def __eq__(self, other):
        if not isinstance(other, MainBlockInfo):
            return NotImplemented
        return (self.offset, self.size, self.extra_data, self.block_type, self.min_version, self.current_version) == (other.offset, other.size, other.extra_data, other.block_type, other.min_version, other.current_version)

class SubBlockInfo(BlockInfo):
    """Sub-block info."""
    __match_args__ = ('offset', 'size', 'extra_data')

    def __init__(self, offset , size , *, extra_data =b'')  :
        self.offset = offset
        self.size = size
        self.extra_data = extra_data

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(offset={self.offset!r}, size={self.size!r}, extra_data={self.extra_data!r})'

    def __eq__(self, other):
        if not isinstance(other, SubBlockInfo):
            return NotImplemented
        return (self.offset, self.size, self.extra_data) == (other.offset, other.size, other.extra_data)

class BlockOverflowError(Exception):
    """Read past end of block."""

class TaggedBlockReader:
    """Read blocks and values from a remarkable v6 file stream."""

    def __init__(self, data ):
        rm_data = DataStream(data)
        self.data = rm_data
        self.current_block  = None
        self._warned_about_extra_data = False

    def read_header(self)  :
        """Read the file header.

        This should be the first call when starting to read a new file.

        """
        self.data.read_header()

    def read_id(self, index )  :
        """Read a tagged CRDT ID."""
        self.data.read_tag(index, TagType.ID)
        result = self.data.read_crdt_id()
        return result

    def read_bool(self, index )  :
        """Read a tagged bool."""
        self.data.read_tag(index, TagType.Byte1)
        result = self.data.read_bool()
        return result

    def read_byte(self, index )  :
        """Read a tagged byte as an unsigned integer."""
        self.data.read_tag(index, TagType.Byte1)
        result = self.data.read_uint8()
        return result

    def read_int(self, index )  :
        """Read a tagged 4-byte unsigned integer."""
        self.data.read_tag(index, TagType.Byte4)
        result = self.data.read_uint32()
        return result

    def read_float(self, index )  :
        """Read a tagged 4-byte float."""
        self.data.read_tag(index, TagType.Byte4)
        result = self.data.read_float32()
        return result

    def read_double(self, index )  :
        """Read a tagged 8-byte double."""
        self.data.read_tag(index, TagType.Byte8)
        result = self.data.read_float64()
        return result

    def _read_optional(self, func, index, default):
        try:
            return func(index)
        except (UnexpectedBlockError, EOFError):
            return default

    def read_id_optional(self, index , default =None)  :
        """Read a tagged CRDT ID, return `default` if not present."""
        return self._read_optional(self.read_id, index, default)

    def read_bool_optional(self, index , default =None)  :
        """Read a tagged bool, return `default` if not present."""
        return self._read_optional(self.read_bool, index, default)

    def read_byte_optional(self, index , default =None)  :
        """Read a tagged byte as an unsigned integer, return `default` if not present."""
        return self._read_optional(self.read_byte, index, default)

    def read_int_optional(self, index , default =None)  :
        """Read a tagged 4-byte unsigned integer, return `default` if not present."""
        return self._read_optional(self.read_int, index, default)

    def read_float_optional(self, index , default =None)  :
        """Read a tagged 4-byte float, return `default` if not present."""
        return self._read_optional(self.read_float, index, default)

    def read_double_optional(self, index , default =None)  :
        """Read a tagged 8-byte double, return `default` if not present."""
        return self._read_optional(self.read_double, index, default)

    @contextmanager
    def read_block(self)  :
        """Read a top-level block header.

        This acts as a context manager. Upon exiting the with-block, the amount
        of data read is checked and an error raised if it has not reached the
        end of the block.

        Returns the `BlockInfo` if successfully read. If no block can be read,
        None is returned.

        """
        if self.current_block is not None:
            raise UnexpectedBlockError('Already in a block')
        try:
            block_length = self.data.read_uint32()
        except EOFError:
            yield None
            return
        unknown = self.data.read_uint8()
        min_version = self.data.read_uint8()
        current_version = self.data.read_uint8()
        block_type = self.data.read_uint8()
        _logger.debug('Block header: %d %d %d', min_version, current_version, block_type)
        assert unknown == 0
        assert current_version >= 0
        assert min_version >= 0
        assert min_version <= current_version
        i0 = self.data.tell()
        self.current_block = MainBlockInfo(offset=i0, size=block_length, block_type=block_type, min_version=min_version, current_version=current_version)
        yield self.current_block
        assert self.current_block is not None
        self._check_position(self.current_block)
        self.current_block = None

    def bytes_remaining_in_block(self)  :
        """Return the number of bytes remaining in the current block."""
        block_info = self.current_block
        if block_info is None:
            raise ValueError('Not in a block')
        return block_info.offset + block_info.size - self.data.tell()

    @contextmanager
    def read_subblock(self, index )  :
        """Read a subblock length and return `SubBlockInfo` as context object.

        Checks that the correct length has been read at the end of the with
        block.
        """
        self.data.read_tag(index, TagType.Length4)
        subblock_length = self.data.read_uint32()
        i0 = self.data.tell()
        subblock = SubBlockInfo(i0, subblock_length)
        yield subblock
        self._check_position(subblock)

    def has_subblock(self, index )  :
        """Check if a subblock with the given index is next."""
        if self.current_block:
            if self.bytes_remaining_in_block() <= 0:
                return False
        return self.data.check_tag(index, TagType.Length4)

    def _check_position(self, block_info ):
        length = block_info.size
        i0 = block_info.offset
        i1 = self.data.tell()
        if i1 > i0 + length:
            raise BlockOverflowError('%s starting at %d, length %d, read up to %d (overflow by %d)' % (type(block_info), i0, length, i1, i1 - (i0 + length)))
        if i1 < i0 + length:
            if not self._warned_about_extra_data:
                _logger.warning('Some data has not been read. The data may have been written using a newer format than this reader supports.')
                self._warned_about_extra_data = True
            _logger.info('In %s only read %d bytes', block_info, i1 - i0)
            remaining = i0 + length - i1
            excess = self.data.read_bytes(remaining)
            block_info.extra_data = excess
            _logger.debug('Excess bytes:\n %s', '\n'.join((excess[i:i + 32].hex() for i in range(0, len(excess), 32))), stack_info=True, stacklevel=4)

    def read_lww_bool(self, index )  :
        """Read a LWW bool."""
        with self.read_subblock(index):
            timestamp = self.read_id(1)
            value = self.read_bool(2)
        return LwwValue(timestamp, value)

    def read_lww_byte(self, index )  :
        """Read a LWW byte."""
        with self.read_subblock(index):
            timestamp = self.read_id(1)
            value = self.read_byte(2)
        return LwwValue(timestamp, value)

    def read_lww_float(self, index )  :
        """Read a LWW float."""
        with self.read_subblock(index):
            timestamp = self.read_id(1)
            value = self.read_float(2)
        return LwwValue(timestamp, value)

    def read_lww_id(self, index )  :
        """Read a LWW ID."""
        with self.read_subblock(index):
            timestamp = self.read_id(1)
            value = self.read_id(2)
        return LwwValue(timestamp, value)

    def read_lww_string(self, index )  :
        """Read a LWW string."""
        with self.read_subblock(index):
            timestamp = self.read_id(1)
            string = self.read_string(2)
        return LwwValue(timestamp, string)

    def read_string(self, index )  :
        """Read a standard string block."""
        with self.read_subblock(index) as block_info:
            string_length = self.data.read_varuint()
            is_ascii = self.data.read_bool()
            assert is_ascii == 1
            assert string_length + 2 <= block_info.size
            b = self.data.read_bytes(string_length)
            string = b.decode()
            if len(b) != len(string):
                _logger.debug('read_string: decoded %r (%d) to %r (%d)', b, len(b), string, len(string))
            return string

    def read_string_with_format(self, index )   :
        """Read a string block with formatting."""
        with self.read_subblock(index) as block_info:
            string_length = self.data.read_varuint()
            is_ascii = self.data.read_bool()
            assert is_ascii == 1
            assert string_length + 2 <= block_info.size
            b = self.data.read_bytes(string_length)
            string = b.decode()
            if len(b) != len(string):
                _logger.debug('read_string: decoded %r (%d) to %r (%d)', b, len(b), string, len(string))
            if self.data.check_tag(2, TagType.Byte4):
                fmt = self.read_int(2)
            else:
                fmt = None
            return (string, fmt)
