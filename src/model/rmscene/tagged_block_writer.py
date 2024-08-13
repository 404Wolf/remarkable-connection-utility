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
from io import BytesIO
import logging
import typing as tp
from .tagged_block_common import TagType, DataStream, CrdtId, LwwValue, UnexpectedBlockError
_logger = logging.getLogger(__name__)

class TaggedBlockWriter:
    """Write blocks and values to a remarkable v6 file stream."""

    def __init__(self, data , options =None):
        if options is None:
            options = {}
        self.options = options
        rm_data = DataStream(data)
        self.data = rm_data
        self._in_block  = False

    def write_header(self)  :
        """Write the file header.

        This should be the first call when starting to write a new file.

        """
        self.data.write_header()

    def write_id(self, index , value ):
        """Write a tagged CRDT ID."""
        self.data.write_tag(index, TagType.ID)
        self.data.write_crdt_id(value)

    def write_bool(self, index , value ):
        """Write a tagged bool."""
        self.data.write_tag(index, TagType.Byte1)
        self.data.write_bool(value)

    def write_byte(self, index , value ):
        """Write a tagged byte as an unsigned integer."""
        self.data.write_tag(index, TagType.Byte1)
        self.data.write_uint8(value)

    def write_int(self, index , value ):
        """Write a tagged 4-byte unsigned integer."""
        self.data.write_tag(index, TagType.Byte4)
        self.data.write_uint32(value)

    def write_float(self, index , value ):
        """Write a tagged 4-byte float."""
        self.data.write_tag(index, TagType.Byte4)
        self.data.write_float32(value)

    def write_double(self, index , value ):
        """Write a tagged 8-byte double."""
        self.data.write_tag(index, TagType.Byte8)
        self.data.write_float64(value)

    @contextmanager
    def write_block(self, block_type , min_version , current_version )  :
        """Write a top-level block header.

        Within this block, other writes are accumulated, so that the
        whole block can be written out with its length at the end.

        """
        if self._in_block:
            raise UnexpectedBlockError('Already in a block')
        previous_data = self.data
        block_buf = BytesIO()
        block_data = DataStream(block_buf)
        try:
            self.data = block_data
            self._in_block = True
            yield
        finally:
            self.data = previous_data
        assert self._in_block
        self._in_block = False
        self.data.write_uint32(len(block_buf.getbuffer()))
        self.data.write_uint8(0)
        self.data.write_uint8(min_version)
        self.data.write_uint8(current_version)
        self.data.write_uint8(block_type)
        self.data.write_bytes(block_buf.getbuffer())

    @contextmanager
    def write_subblock(self, index )  :
        """Write a subblock tag and length once the with-block has exited.

        Within this block, other writes are accumulated, so that the
        whole block can be written out with its length at the end.
        """
        previous_data = self.data
        subblock_buf = BytesIO()
        subblock_data = DataStream(subblock_buf)
        try:
            self.data = subblock_data
            yield
        finally:
            self.data = previous_data
        self.data.write_tag(index, TagType.Length4)
        self.data.write_uint32(len(subblock_buf.getbuffer()))
        self.data.write_bytes(subblock_buf.getbuffer())
        _logger.debug('Wrote subblock %d: %s', index, subblock_buf.getvalue().hex())

    def write_lww_bool(self, index , value ):
        """Write a LWW bool."""
        with self.write_subblock(index):
            self.write_id(1, value.timestamp)
            self.write_bool(2, value.value)

    def write_lww_byte(self, index , value ):
        """Write a LWW byte."""
        with self.write_subblock(index):
            self.write_id(1, value.timestamp)
            self.write_byte(2, value.value)

    def write_lww_float(self, index , value ):
        """Write a LWW float."""
        with self.write_subblock(index):
            self.write_id(1, value.timestamp)
            self.write_float(2, value.value)

    def write_lww_id(self, index , value ):
        """Write a LWW ID."""
        with self.write_subblock(index):
            self.write_id(1, value.timestamp)
            self.write_id(2, value.value)

    def write_lww_string(self, index , value ):
        """Write a LWW string."""
        with self.write_subblock(index):
            self.write_id(1, value.timestamp)
            self.write_string(2, value.value)

    def write_string(self, index , value ):
        """Write a standard string block."""
        with self.write_subblock(index):
            b = value.encode()
            bytes_length = len(b)
            is_ascii = True
            self.data.write_varuint(bytes_length)
            self.data.write_bool(is_ascii)
            self.data.write_bytes(b)

    def write_string_with_format(self, index , text , fmt ):
        """Write a string block with formatting."""
        with self.write_subblock(index):
            b = text.encode()
            bytes_length = len(b)
            is_ascii = True
            self.data.write_varuint(bytes_length)
            self.data.write_bool(is_ascii)
            self.data.write_bytes(b)
            self.write_int(2, fmt)
