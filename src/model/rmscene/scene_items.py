'''
Data structures for the contents of a scene.

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

import enum
import logging
import typing as tp
from .tagged_block_common import CrdtId, LwwValue
from .crdt_sequence import CrdtSequence
from .text import expand_text_items
_logger = logging.getLogger(__name__)

class SceneItem:
    """Base class for items stored in scene tree."""
    def __init__(self):
        pass

class Group(SceneItem):
    """A Group represents a group of nested items.

    Groups are used to represent layers.

    node_id is the id that this sub-tree is stored as a "SceneTreeBlock".

    children is a sequence of other SceneItems.

    `anchor_id` refers to a text character which provides the anchor y-position
    for this group. There are two values that seem to be special:
    - `0xfffffffffffe` seems to be used for lines right at the top of the page?
    - `0xffffffffffff` seems to be used for lines right at the bottom of the page?

    """
    __match_args__ = ('node_id', 'children', 'label', 'visible', 'anchor_id', 'anchor_type', 'anchor_threshold', 'anchor_origin_x')

    def __init__(self, node_id , children =None, label =LwwValue(CrdtId(0, 0), ''), visible =LwwValue(CrdtId(0, 0), True), anchor_id =None, anchor_type =None, anchor_threshold =None, anchor_origin_x =None)  :
        if children is None:
            children = CrdtSequence()
        self.node_id = node_id
        self.children = children
        self.label = label
        self.visible = visible
        self.anchor_id = anchor_id
        self.anchor_type = anchor_type
        self.anchor_threshold = anchor_threshold
        self.anchor_origin_x = anchor_origin_x

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(node_id={self.node_id!r}, children={self.children!r}, label={self.label!r}, visible={self.visible!r}, anchor_id={self.anchor_id!r}, anchor_type={self.anchor_type!r}, anchor_threshold={self.anchor_threshold!r}, anchor_origin_x={self.anchor_origin_x!r})'

    def __eq__(self, other):
        if not isinstance(other, Group):
            return NotImplemented
        return (self.node_id, self.children, self.label, self.visible, self.anchor_id, self.anchor_type, self.anchor_threshold, self.anchor_origin_x) == (other.node_id, other.children, other.label, other.visible, other.anchor_id, other.anchor_type, other.anchor_threshold, other.anchor_origin_x)

@enum.unique
class PenColor(enum.IntEnum):
    """
    Color index value.
    """
    BLACK = 0
    GRAY = 1
    WHITE = 2
    YELLOW = 3
    GREEN = 4
    PINK = 5
    BLUE = 6
    RED = 7
    GRAY_OVERLAP = 8

@enum.unique
class Pen(enum.IntEnum):
    """
    Stroke pen id representing reMarkable tablet tools.

    Tool examples: ballpoint, fineliner, highlighter or eraser.
    """
    BALLPOINT_1 = 2
    BALLPOINT_2 = 15
    CALIGRAPHY = 21
    ERASER = 6
    ERASER_AREA = 8
    FINELINER_1 = 4
    FINELINER_2 = 17
    HIGHLIGHTER_1 = 5
    HIGHLIGHTER_2 = 18
    MARKER_1 = 3
    MARKER_2 = 16
    MECHANICAL_PENCIL_1 = 7
    MECHANICAL_PENCIL_2 = 13
    PAINTBRUSH_1 = 0
    PAINTBRUSH_2 = 12
    PENCIL_1 = 1
    PENCIL_2 = 14

    @classmethod
    def is_highlighter(cls, value )  :
        return value in (cls.HIGHLIGHTER_1, cls.HIGHLIGHTER_2)

class Point:
    __match_args__ = ('x', 'y', 'speed', 'direction', 'width', 'pressure')

    def __init__(self, x , y , speed , direction , width , pressure )  :
        self.x = x
        self.y = y
        self.speed = speed
        self.direction = direction
        self.width = width
        self.pressure = pressure

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(x={self.x!r}, y={self.y!r}, speed={self.speed!r}, direction={self.direction!r}, width={self.width!r}, pressure={self.pressure!r})'

    def __eq__(self, other):
        if not isinstance(other, Point):
            return NotImplemented
        return (self.x, self.y, self.speed, self.direction, self.width, self.pressure) == (other.x, other.y, other.speed, other.direction, other.width, other.pressure)

class Line(SceneItem):
    __match_args__ = ('color', 'tool', 'points', 'thickness_scale', 'starting_length')

    def __init__(self, color , tool , points , thickness_scale , starting_length )  :
        self.color = color
        self.tool = tool
        self.points = points
        self.thickness_scale = thickness_scale
        self.starting_length = starting_length

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(color={self.color!r}, tool={self.tool!r}, points={self.points!r}, thickness_scale={self.thickness_scale!r}, starting_length={self.starting_length!r})'

    def __eq__(self, other):
        if not isinstance(other, Line):
            return NotImplemented
        return (self.color, self.tool, self.points, self.thickness_scale, self.starting_length) == (other.color, other.tool, other.points, other.thickness_scale, other.starting_length)

@enum.unique
class ParagraphStyle(enum.IntEnum):
    """
    Text paragraph style.
    """
    BASIC = 0
    PLAIN = 1
    HEADING = 2
    HEADING2 = 3
    BULLET = 4
    BULLET2 = 5
    CHECKBOX = 6
    CHECKBOX2 = 7
END_MARKER = CrdtId(0, 0)

class Text(SceneItem):
    """Block of text.

    `items` are a CRDT sequence of strings. The `item_id` for each string refers
    to its first character; subsequent characters implicitly have sequential
    ids.

    When formatting is present, some of `items` have a value of an integer
    formatting code instead of a string.

    `styles` are LWW values representing a mapping of character IDs to
    `ParagraphStyle` values. These formats apply to each line of text (until the
    next newline).

    `pos_x`, `pos_y` and `width` are dimensions for the text block.

    """
    __match_args__ = ('items', 'styles', 'pos_x', 'pos_y', 'width')

    def __init__(self, items   , styles  , pos_x , pos_y , width )  :
        self.items = items
        self.styles = styles
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.width = width

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(items={self.items!r}, styles={self.styles!r}, pos_x={self.pos_x!r}, pos_y={self.pos_y!r}, width={self.width!r})'

    def __eq__(self, other):
        if not isinstance(other, Text):
            return NotImplemented
        return (self.items, self.styles, self.pos_x, self.pos_y, self.width) == (other.items, other.styles, other.pos_x, other.pos_y, other.width)

class Rectangle:
    __match_args__ = ('x', 'y', 'w', 'h')

    def __init__(self, x , y , w , h )  :
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(x={self.x!r}, y={self.y!r}, w={self.w!r}, h={self.h!r})'

    def __eq__(self, other):
        if not isinstance(other, Rectangle):
            return NotImplemented
        return (self.x, self.y, self.w, self.h) == (other.x, other.y, other.w, other.h)

class GlyphRange(SceneItem):
    """Highlighted text

    `start` is only available in SceneGlyphItemBlock version=0, prior to ReMarkable v3.6

    `length` is the length of the text

    `text` is the highlighted text itself

    `color` represents the highlight color

    `rectangles` represent the locations of the highlight.
    """
    __match_args__ = ('start', 'length', 'text', 'color', 'rectangles')

    def __init__(self, start , length , text , color , rectangles )  :
        self.start = start
        self.length = length
        self.text = text
        self.color = color
        self.rectangles = rectangles

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(start={self.start!r}, length={self.length!r}, text={self.text!r}, color={self.color!r}, rectangles={self.rectangles!r})'

    def __eq__(self, other):
        if not isinstance(other, GlyphRange):
            return NotImplemented
        return (self.start, self.length, self.text, self.color, self.rectangles) == (other.start, other.length, other.text, other.color, other.rectangles)
