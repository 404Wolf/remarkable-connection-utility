'''
Read structure of reMarkable tablet lines format v6

With help from ddvk's v6 reader, and enum values from remt.

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

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
import math
from uuid import UUID, uuid4
import logging
import typing as tp
from packaging.version import Version
from .tagged_block_common import CrdtId, LwwValue, UnexpectedBlockError
from .tagged_block_reader import TaggedBlockReader, MainBlockInfo
from .tagged_block_writer import TaggedBlockWriter
from .crdt_sequence import CrdtSequence, CrdtSequenceItem
from .scene_tree import SceneTree
from . import scene_items as si
_logger = logging.getLogger(__name__)

class Block(ABC):
    #BLOCK_TYPE: tp.ClassVar
    __match_args__ = ('extra_data',)

    def __init__(self, *, extra_data =b'')  :
        self.extra_data = extra_data

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r})'

    def __eq__(self, other):
        if not isinstance(other, Block):
            return NotImplemented
        return (self.extra_data,) == (other.extra_data,)

    def version_info(self, writer )   :
        """Return (min_version, current_version) to use when writing."""
        return (1, 1)

    def get_block_type(self)  :
        """Return block type for this block.

        By default, returns the block's BLOCK_TYPE attribute, but this method
        can be overriden if a single block subclass can handle multiple block
        types.

        """
        return self.BLOCK_TYPE

    @classmethod
    def lookup(cls, block_type )  :
        if getattr(cls, 'BLOCK_TYPE', None) == block_type:
            return cls
        for subclass in cls.__subclasses__():
            match = subclass.lookup(block_type)
            if match:
                return match
        return None

    def write(self, writer ):
        """Write the block header and content to the stream."""
        min_version, current_version = self.version_info(writer)
        with writer.write_block(self.get_block_type(), min_version, current_version):
            self.to_stream(writer)

    @classmethod
    @abstractmethod
    def from_stream(cls, reader )  :
        """Read content of block from stream."""
        raise NotImplementedError()

    @abstractmethod
    def to_stream(self, writer ):
        """Write content of block to stream."""
        raise NotImplementedError()

class UnreadableBlock(Block):
    """Represent a block which could not be read for some reason."""
    __match_args__ = ('extra_data', 'error', 'data', 'info')

    def __init__(self, error , data , info , *, extra_data =b'')  :
        self.extra_data = extra_data
        self.error = error
        self.data = data
        self.info = info

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, error={self.error!r}, data={self.data!r}, info={self.info!r})'

    def __eq__(self, other):
        if not isinstance(other, UnreadableBlock):
            return NotImplemented
        return (self.extra_data, self.error, self.data, self.info) == (other.extra_data, other.error, other.data, other.info)

    def get_block_type(self)  :
        return self.info.block_type

    @classmethod
    def from_stream(cls, reader )  :
        raise NotImplementedError()

    def to_stream(self, writer ):
        writer.data.write_bytes(self.data)

class AuthorIdsBlock(Block):
    BLOCK_TYPE  = 9
    __match_args__ = ('extra_data', 'author_uuids')

    def __init__(self, author_uuids  , *, extra_data =b'')  :
        self.extra_data = extra_data
        self.author_uuids = author_uuids

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, author_uuids={self.author_uuids!r})'

    def __eq__(self, other):
        if not isinstance(other, AuthorIdsBlock):
            return NotImplemented
        return (self.extra_data, self.author_uuids) == (other.extra_data, other.author_uuids)

    @classmethod
    def from_stream(cls, stream )  :
        _logger.debug('Reading %s', cls.__name__)
        num_subblocks = stream.data.read_varuint()
        author_ids = {}
        for _ in range(num_subblocks):
            with stream.read_subblock(0):
                uuid_length = stream.data.read_varuint()
                if uuid_length != 16:
                    raise ValueError('Expected UUID length to be 16 bytes')
                uuid = UUID(bytes_le=stream.data.read_bytes(uuid_length))
                author_id = stream.data.read_uint16()
                author_ids[author_id] = uuid
        return AuthorIdsBlock(author_ids)

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        num_subblocks = len(self.author_uuids)
        writer.data.write_varuint(num_subblocks)
        for author_id, uuid in self.author_uuids.items():
            with writer.write_subblock(0):
                writer.data.write_varuint(len(uuid.bytes_le))
                writer.data.write_bytes(uuid.bytes_le)
                writer.data.write_uint16(author_id)

class MigrationInfoBlock(Block):
    BLOCK_TYPE  = 0
    __match_args__ = ('extra_data', 'migration_id', 'is_device', '_unknown')

    def __init__(self, migration_id , is_device , _unknown =False, *, extra_data =b'')  :
        self.extra_data = extra_data
        self.migration_id = migration_id
        self.is_device = is_device
        self._unknown = _unknown

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, migration_id={self.migration_id!r}, is_device={self.is_device!r}, _unknown={self._unknown!r})'

    def __eq__(self, other):
        if not isinstance(other, MigrationInfoBlock):
            return NotImplemented
        return (self.extra_data, self.migration_id, self.is_device, self._unknown) == (other.extra_data, other.migration_id, other.is_device, other._unknown)

    @classmethod
    def from_stream(cls, stream )  :
        """Parse migration info"""
        _logger.debug('Reading %s', cls.__name__)
        migration_id = stream.read_id(1)
        is_device = stream.read_bool(2)
        if stream.bytes_remaining_in_block():
            unknown = stream.read_bool(3)
        else:
            unknown = False
        return MigrationInfoBlock(migration_id, is_device, unknown)

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        version = writer.options.get('version', Version('9.9.9'))
        writer.write_id(1, self.migration_id)
        writer.write_bool(2, self.is_device)
        if version >= Version('3.2.2'):
            writer.write_bool(3, self._unknown)

class TreeNodeBlock(Block):
    BLOCK_TYPE  = 2
    __match_args__ = ('extra_data', 'group')

    def __init__(self, group , *, extra_data =b'')  :
        self.extra_data = extra_data
        self.group = group

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, group={self.group!r})'

    def __eq__(self, other):
        if not isinstance(other, TreeNodeBlock):
            return NotImplemented
        return (self.extra_data, self.group) == (other.extra_data, other.group)

    @classmethod
    def from_stream(cls, stream )  :
        """Parse tree node block."""
        _logger.debug('Reading %s', cls.__name__)
        group = si.Group(node_id=stream.read_id(1), label=stream.read_lww_string(2), visible=stream.read_lww_bool(3))
        if stream.bytes_remaining_in_block() > 0:
            group.anchor_id = stream.read_lww_id(7)
            group.anchor_type = stream.read_lww_byte(8)
            group.anchor_threshold = stream.read_lww_float(9)
            group.anchor_origin_x = stream.read_lww_float(10)
        return cls(group)

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        group = self.group
        writer.write_id(1, group.node_id)
        writer.write_lww_string(2, group.label)
        writer.write_lww_bool(3, group.visible)
        if group.anchor_id is not None:
            assert group.anchor_type is not None and group.anchor_threshold is not None and (group.anchor_origin_x is not None)
            writer.write_lww_id(7, group.anchor_id)
            writer.write_lww_byte(8, group.anchor_type)
            writer.write_lww_float(9, group.anchor_threshold)
            writer.write_lww_float(10, group.anchor_origin_x)

class PageInfoBlock(Block):
    BLOCK_TYPE  = 10
    __match_args__ = ('extra_data', 'loads_count', 'merges_count', 'text_chars_count', 'text_lines_count', '_unknown')

    def __init__(self, loads_count , merges_count , text_chars_count , text_lines_count , _unknown =0, *, extra_data =b'')  :
        self.extra_data = extra_data
        self.loads_count = loads_count
        self.merges_count = merges_count
        self.text_chars_count = text_chars_count
        self.text_lines_count = text_lines_count
        self._unknown = _unknown

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, loads_count={self.loads_count!r}, merges_count={self.merges_count!r}, text_chars_count={self.text_chars_count!r}, text_lines_count={self.text_lines_count!r}, _unknown={self._unknown!r})'

    def __eq__(self, other):
        if not isinstance(other, PageInfoBlock):
            return NotImplemented
        return (self.extra_data, self.loads_count, self.merges_count, self.text_chars_count, self.text_lines_count, self._unknown) == (other.extra_data, other.loads_count, other.merges_count, other.text_chars_count, other.text_lines_count, other._unknown)

    def version_info(self, _)   :
        """Return (min_version, current_version) to use when writing."""
        return (0, 1)

    @classmethod
    def from_stream(cls, stream )  :
        """Parse page info block"""
        _logger.debug('Reading %s', cls.__name__)
        info = PageInfoBlock(loads_count=stream.read_int(1), merges_count=stream.read_int(2), text_chars_count=stream.read_int(3), text_lines_count=stream.read_int(4))
        if stream.bytes_remaining_in_block():
            info._unknown = stream.read_int(5)
        return info

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        writer.write_int(1, self.loads_count)
        writer.write_int(2, self.merges_count)
        writer.write_int(3, self.text_chars_count)
        writer.write_int(4, self.text_lines_count)
        version = writer.options.get('version', Version('9999'))
        if version >= Version('3.2.2'):
            writer.write_int(5, self._unknown)

class SceneTreeBlock(Block):
    BLOCK_TYPE  = 1
    __match_args__ = ('extra_data', 'tree_id', 'node_id', 'is_update', 'parent_id')

    def __init__(self, tree_id , node_id , is_update , parent_id , *, extra_data =b'')  :
        self.extra_data = extra_data
        self.tree_id = tree_id
        self.node_id = node_id
        self.is_update = is_update
        self.parent_id = parent_id

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, tree_id={self.tree_id!r}, node_id={self.node_id!r}, is_update={self.is_update!r}, parent_id={self.parent_id!r})'

    def __eq__(self, other):
        if not isinstance(other, SceneTreeBlock):
            return NotImplemented
        return (self.extra_data, self.tree_id, self.node_id, self.is_update, self.parent_id) == (other.extra_data, other.tree_id, other.node_id, other.is_update, other.parent_id)

    @classmethod
    def from_stream(cls, stream )  :
        """Parse scene tree block"""
        _logger.debug('Reading %s', cls.__name__)
        tree_id = stream.read_id(1)
        node_id = stream.read_id(2)
        is_update = stream.read_bool(3)
        with stream.read_subblock(4):
            parent_id = stream.read_id(1)
        return SceneTreeBlock(tree_id, node_id, is_update, parent_id)

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        writer.write_id(1, self.tree_id)
        writer.write_id(2, self.node_id)
        writer.write_bool(3, self.is_update)
        with writer.write_subblock(4):
            writer.write_id(1, self.parent_id)

def point_from_stream(stream , version =2)  :
    if version not in (1, 2):
        raise ValueError('Unknown version %s' % version)
    d = stream.data
    x = d.read_float32()
    y = d.read_float32()
    if version == 1:
        speed = d.read_float32() * 4
        direction = 255 * d.read_float32() / (math.pi * 2)
        width = int(round(d.read_float32() * 4))
        pressure = d.read_float32() * 255
    else:
        speed = d.read_uint16()
        width = d.read_uint16()
        direction = d.read_uint8()
        pressure = d.read_uint8()
    return si.Point(x, y, speed, direction, width, pressure)

def point_serialized_size(version =2)  :
    if version == 1:
        return 24
    elif version == 2:
        return 14
    else:
        raise ValueError('Unknown version %s' % version)

def point_to_stream(point , writer , version =2):
    if version not in (1, 2):
        raise ValueError('Unknown version %s' % version)
    d = writer.data
    d.write_float32(point.x)
    d.write_float32(point.y)
    _logger.debug('Writing Point v%d: %s', version, point)
    if version == 1:
        d.write_float32(point.speed / 4)
        d.write_float32(point.direction * (2 * math.pi) / 255)
        d.write_float32(point.width / 4)
        d.write_float32(point.pressure / 255)
    else:
        d.write_uint16(point.speed)
        d.write_uint16(point.width)
        d.write_uint8(point.direction)
        d.write_uint8(point.pressure)

def line_from_stream(stream , version =2)  :
    _logger.debug('Reading Line version %d', version)
    tool_id = stream.read_int(1)
    tool = si.Pen(tool_id)
    color_id = stream.read_int(2)
    color = si.PenColor(color_id)
    thickness_scale = stream.read_double(3)
    starting_length = stream.read_float(4)
    with stream.read_subblock(5) as block_info:
        data_length = block_info.size
        point_size = point_serialized_size(version)
        if data_length % point_size != 0:
            raise ValueError('Point data size mismatch: %d is not multiple of point_size' % data_length)
        num_points = data_length // point_size
        points = [point_from_stream(stream, version=version) for _ in range(num_points)]
    timestamp = stream.read_id(6)
    return si.Line(color, tool, points, thickness_scale, starting_length)

def line_to_stream(line , writer , version =2):
    _logger.debug('Writing Line version %d', version)
    writer.write_int(1, line.tool)
    writer.write_int(2, line.color)
    writer.write_double(3, line.thickness_scale)
    writer.write_float(4, line.starting_length)
    with writer.write_subblock(5):
        for point in line.points:
            point_to_stream(point, writer, version)
    timestamp = CrdtId(0, 1)
    writer.write_id(6, timestamp)

class SceneItemBlock(Block):
    ITEM_TYPE  = 0
    __match_args__ = ('extra_data', 'parent_id', 'item')

    def __init__(self, parent_id , item , *, extra_data =b'')  :
        self.extra_data = extra_data
        self.parent_id = parent_id
        self.item = item

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, parent_id={self.parent_id!r}, item={self.item!r})'

    def __eq__(self, other):
        if not isinstance(other, SceneItemBlock):
            return NotImplemented
        return (self.extra_data, self.parent_id, self.item) == (other.extra_data, other.parent_id, other.item)

    @classmethod
    def from_stream(cls, stream )  :
        """Group item block?"""
        _logger.debug('Reading %s', cls.__name__)
        assert stream.current_block
        block_type = stream.current_block.block_type
        if block_type == SceneGlyphItemBlock.BLOCK_TYPE:
            subclass = SceneGlyphItemBlock
        elif block_type == SceneGroupItemBlock.BLOCK_TYPE:
            subclass = SceneGroupItemBlock
        elif block_type == SceneLineItemBlock.BLOCK_TYPE:
            subclass = SceneLineItemBlock
        elif block_type == SceneTextItemBlock.BLOCK_TYPE:
            subclass = SceneTextItemBlock
        else:
            raise ValueError('unknown scene type %d in %s' % (block_type, stream.current_block))
        parent_id = stream.read_id(1)
        item_id = stream.read_id(2)
        left_id = stream.read_id(3)
        right_id = stream.read_id(4)
        deleted_length = stream.read_int(5)
        if stream.has_subblock(6):
            with stream.read_subblock(6) as block_info:
                item_type = stream.data.read_uint8()
                assert item_type == subclass.ITEM_TYPE
                value = subclass.value_from_stream(stream)
            extra_data = block_info.extra_data
        else:
            value = None
            extra_data = b''
        return subclass(parent_id, CrdtSequenceItem(item_id, left_id, right_id, deleted_length, value), extra_data=extra_data)

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        writer.write_id(1, self.parent_id)
        writer.write_id(2, self.item.item_id)
        writer.write_id(3, self.item.left_id)
        writer.write_id(4, self.item.right_id)
        writer.write_int(5, self.item.deleted_length)
        if self.item.value is not None:
            with writer.write_subblock(6):
                writer.data.write_uint8(self.ITEM_TYPE)
                self.value_to_stream(writer, self.item.value)
                writer.data.write_bytes(self.extra_data)

    @classmethod
    @abstractmethod
    def value_from_stream(cls, reader )  :
        """Read the specific content of this block"""
        raise NotImplementedError()

    @abstractmethod
    def value_to_stream(self, writer , value ):
        """Write the specific content of this block"""
        raise NotImplementedError()

def glyph_range_from_stream(stream )  :
    start = stream.read_int_optional(2)
    length = stream.read_int_optional(3)
    color_id = stream.read_int(4)
    color = si.PenColor(color_id)
    text = stream.read_string(5)
    if length is None:
        length = len(text)
    if len(text) != length:
        _logger.debug('GlyphRange text length %d != length value %d: %r', len(text), length, text)
    with stream.read_subblock(6):
        num_rects = stream.data.read_varuint()
        rectangles = [si.Rectangle(*[stream.data.read_float64() for _ in range(4)]) for _ in range(num_rects)]
    return si.GlyphRange(start, length, text, color, rectangles)

def glyph_range_to_stream(stream , item ):
    if item.start is not None:
        stream.write_int(2, item.start)
        stream.write_int(3, item.length)
    stream.write_int(4, item.color)
    stream.write_string(5, item.text)
    with stream.write_subblock(6):
        stream.data.write_varuint(len(item.rectangles))
        for rect in item.rectangles:
            stream.data.write_float64(rect.x)
            stream.data.write_float64(rect.y)
            stream.data.write_float64(rect.w)
            stream.data.write_float64(rect.h)

class SceneGlyphItemBlock(SceneItemBlock):
    BLOCK_TYPE  = 3
    ITEM_TYPE  = 1

    @classmethod
    def value_from_stream(cls, reader )  :
        value = glyph_range_from_stream(reader)
        return value

    def value_to_stream(self, writer , value):
        glyph_range_to_stream(writer, value)

class SceneGroupItemBlock(SceneItemBlock):
    BLOCK_TYPE  = 4
    ITEM_TYPE  = 2

    @classmethod
    def value_from_stream(cls, reader )  :
        value = reader.read_id(2)
        return value

    def value_to_stream(self, writer , value ):
        writer.write_id(2, value)

class SceneLineItemBlock(SceneItemBlock):
    BLOCK_TYPE  = 5
    ITEM_TYPE  = 3

    def version_info(self, writer )   :
        """Return (min_version, current_version) to use when writing."""
        version = writer.options.get('version', Version('9999'))
        return (2, 2) if version > Version('3.0') else (1, 1)

    @classmethod
    def value_from_stream(cls, reader )  :
        assert reader.current_block is not None
        version = reader.current_block.current_version
        value = line_from_stream(reader, version)
        return value

    def value_to_stream(self, writer , value ):
        version = writer.options.get('version', Version('9999'))
        line_version = 2 if version > Version('3.0') else 1
        line_to_stream(value, writer, version=line_version)

class SceneTextItemBlock(SceneItemBlock):
    BLOCK_TYPE  = 6
    ITEM_TYPE  = 5

    @classmethod
    def value_from_stream(cls, reader )  :
        return None

    def value_to_stream(self, writer , value):
        pass

def text_item_from_stream(stream )    :
    with stream.read_subblock(0):
        item_id = stream.read_id(2)
        left_id = stream.read_id(3)
        right_id = stream.read_id(4)
        deleted_length = stream.read_int(5)
        if stream.has_subblock(6):
            text, fmt = stream.read_string_with_format(6)
            if fmt is not None:
                if text:
                    _logger.error('Unhandled combined text and format: %s, %s', text, fmt)
                value = fmt
            else:
                value = text
        else:
            value = ''
    return CrdtSequenceItem(item_id, left_id, right_id, deleted_length, value)

def text_item_to_stream(item   , writer ):
    with writer.write_subblock(0):
        writer.write_id(2, item.item_id)
        writer.write_id(3, item.left_id)
        writer.write_id(4, item.right_id)
        writer.write_int(5, item.deleted_length)
        if item.value:
            if isinstance(item.value, str):
                writer.write_string(6, item.value)
            elif isinstance(item.value, int):
                writer.write_string_with_format(6, '', item.value)

def text_format_from_stream(stream )   :
    char_id = stream.data.read_crdt_id()
    timestamp = stream.read_id(1)
    with stream.read_subblock(2):
        c = stream.data.read_uint8()
        assert c == 17
        format_code = stream.data.read_uint8()
        try:
            format_type = si.ParagraphStyle(format_code)
        except ValueError:
            _logger.warning('Unrecognised text format code %d.', format_code)
            _logger.debug('Unrecognised text format code %d at position %d.', format_code, stream.data.tell())
            format_type = si.ParagraphStyle.PLAIN
    return (char_id, LwwValue(timestamp, format_type))

def text_format_to_stream(char_id , value , writer ):
    format_type = value.value
    writer.data.write_crdt_id(char_id)
    writer.write_id(1, value.timestamp)
    with writer.write_subblock(2):
        c = 17
        writer.data.write_uint8(c)
        writer.data.write_uint8(format_type)

class RootTextBlock(Block):
    BLOCK_TYPE  = 7
    __match_args__ = ('extra_data', 'block_id', 'value')

    def __init__(self, block_id , value , *, extra_data =b'')  :
        self.extra_data = extra_data
        self.block_id = block_id
        self.value = value

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(extra_data={self.extra_data!r}, block_id={self.block_id!r}, value={self.value!r})'

    def __eq__(self, other):
        if not isinstance(other, RootTextBlock):
            return NotImplemented
        return (self.extra_data, self.block_id, self.value) == (other.extra_data, other.block_id, other.value)

    @classmethod
    def from_stream(cls, stream )  :
        """Parse root text block."""
        _logger.debug('Reading %s', cls.__name__)
        block_id = stream.read_id(1)
        assert block_id == CrdtId(0, 0)
        with stream.read_subblock(2):
            with stream.read_subblock(1):
                with stream.read_subblock(1):
                    num_subblocks = stream.data.read_varuint()
                    text_items = [text_item_from_stream(stream) for _ in range(num_subblocks)]
            with stream.read_subblock(2):
                with stream.read_subblock(1):
                    num_subblocks = stream.data.read_varuint()
                    text_formats = dict((text_format_from_stream(stream) for _ in range(num_subblocks)))
        with stream.read_subblock(3):
            pos_x = stream.data.read_float64()
            pos_y = stream.data.read_float64()
        width = stream.read_float(4)
        value = si.Text(items=CrdtSequence(text_items), styles=text_formats, pos_x=pos_x, pos_y=pos_y, width=width)
        return RootTextBlock(block_id, value)

    def to_stream(self, writer ):
        _logger.debug('Writing %s', type(self).__name__)
        writer.write_id(1, self.block_id)
        with writer.write_subblock(2):
            text_items = self.value.items.sequence_items()
            with writer.write_subblock(1):
                with writer.write_subblock(1):
                    writer.data.write_varuint(len(text_items))
                    for item in text_items:
                        text_item_to_stream(item, writer)
            text_formats = self.value.styles
            with writer.write_subblock(2):
                with writer.write_subblock(1):
                    writer.data.write_varuint(len(text_formats))
                    for key, item in text_formats.items():
                        text_format_to_stream(key, item, writer)
        with writer.write_subblock(3):
            writer.data.write_float64(self.value.pos_x)
            writer.data.write_float64(self.value.pos_y)
        writer.write_float(4, self.value.width)

def _read_blocks(stream )  :
    """
    Parse blocks from reMarkable v6 file.
    """
    while True:
        with stream.read_block() as block_info:
            if block_info is None:
                return
            block_type = Block.lookup(block_info.block_type)
            if block_type:
                try:
                    yield block_type.from_stream(stream)
                except Exception as e:
                    _logger.warning('Error reading block: %s', e)
                    stream.data.data.seek(block_info.offset)
                    data = stream.data.read_bytes(block_info.size)
                    yield UnreadableBlock(str(e), data, block_info)
            else:
                msg = f'Unknown block type {block_info.block_type}. Skipping {block_info.size} bytes.'
                _logger.warning(msg)
                data = stream.data.read_bytes(block_info.size)
                yield UnreadableBlock(msg, data, block_info)

def read_blocks(data )  :
    """
    Parse reMarkable file and return iterator of document items.

    :param data: reMarkable file data.
    """
    stream = TaggedBlockReader(data)
    stream.read_header()
    yield from _read_blocks(stream)

def write_blocks(data , blocks , options =None):
    """
    Write blocks to file.
    """
    if options is not None and 'version' in options:
        options['version'] = Version(options['version'])
    stream = TaggedBlockWriter(data, options=options)
    stream.write_header()
    for block in blocks:
        block.write(stream)

def build_tree(tree , blocks ):
    """Read `blocks` and add contents to `tree`."""
    for b in blocks:
        if isinstance(b, SceneTreeBlock):
            tree.add_node(b.tree_id, parent_id=b.parent_id)
        elif isinstance(b, TreeNodeBlock):
            if b.group.node_id not in tree:
                raise ValueError('Node does not exist for TreeNodeBlock: %s' % b.group.node_id)
            node = tree[b.group.node_id]
            node.label = b.group.label
            node.visible = b.group.visible
            node.anchor_id = b.group.anchor_id
            node.anchor_type = b.group.anchor_type
            node.anchor_threshold = b.group.anchor_threshold
            node.anchor_origin_x = b.group.anchor_origin_x
        elif isinstance(b, SceneGroupItemBlock):
            node_id = b.item.value
            if node_id not in tree:
                raise ValueError('Node does not exist for SceneGroupItemBlock: %s' % node_id)
            new_dict = b.item.__dict__
            item = type(b.item)(**new_dict)
            item.value = tree[node_id]
            tree.add_item(item, b.parent_id)
        elif isinstance(b, (SceneLineItemBlock, SceneGlyphItemBlock)):
            tree.add_item(b.item, b.parent_id)
        elif isinstance(b, RootTextBlock):
            if tree.root_text is not None:
                _logger.error('Overwriting root text\n  Old: %s\n  New: %s', tree.root_text, b.value)
            tree.root_text = b.value
    pass

def read_tree(data )  :
    """
    Parse reMarkable file and return `SceneTree`.

    :param data: reMarkable file data.
    """
    tree = SceneTree()
    build_tree(tree, read_blocks(data))
    return tree

def simple_text_document(text , author_uuid=None)  :
    """Return the basic blocks to represent `text` as plain text.

    TODO: replace this with a way to generate the tree with given text, and a
    function to write a tree to blocks.

    """
    if author_uuid is None:
        author_uuid = uuid4()
    yield AuthorIdsBlock(author_uuids={1: author_uuid})
    yield MigrationInfoBlock(migration_id=CrdtId(1, 1), is_device=True)
    yield PageInfoBlock(loads_count=1, merges_count=0, text_chars_count=len(text) + 1, text_lines_count=text.count('\n') + 1)
    yield SceneTreeBlock(tree_id=CrdtId(0, 11), node_id=CrdtId(0, 0), is_update=True, parent_id=CrdtId(0, 1))
    yield RootTextBlock(block_id=CrdtId(0, 0), value=si.Text(items=CrdtSequence([CrdtSequenceItem(item_id=CrdtId(1, 16), left_id=CrdtId(0, 0), right_id=CrdtId(0, 0), deleted_length=0, value=text)]), styles={CrdtId(0, 0): LwwValue(timestamp=CrdtId(1, 15), value=si.ParagraphStyle.PLAIN)}, pos_x=-468.0, pos_y=234.0, width=936.0))
    yield TreeNodeBlock(si.Group(node_id=CrdtId(0, 1)))
    yield TreeNodeBlock(si.Group(node_id=CrdtId(0, 11), label=LwwValue(timestamp=CrdtId(0, 12), value='Layer 1')))
    yield SceneGroupItemBlock(parent_id=CrdtId(0, 1), item=CrdtSequenceItem(item_id=CrdtId(0, 13), left_id=CrdtId(0, 0), right_id=CrdtId(0, 0), deleted_length=0, value=CrdtId(0, 11)))
