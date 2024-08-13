'''
Process text from remarkable scene files.

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

from collections.abc import Iterable
from collections import defaultdict
import logging
import typing as tp
from . import scene_items as si
from .tagged_block_common import CrdtId, LwwValue
from .crdt_sequence import CrdtSequence, CrdtSequenceItem
_logger = logging.getLogger(__name__)

def expand_text_item(item   )    :
    """Expand TextItem into single-character TextItems.

    Text is stored as strings in TextItems, each with an associated ID for the
    block. This ID identifies the character at the start of the block. The
    subsequent characters' IDs are implicit.

    This function expands a TextItem into multiple single-character TextItems,
    so that each character has an explicit ID.

    """
    if item.deleted_length > 0:
        assert item.value == ''
        chars = [''] * item.deleted_length
        deleted_length = 1
    elif isinstance(item.value, int):
        yield item
        return
    else:
        chars = item.value
        deleted_length = 0
    if not chars:
        _logger.warning('Unexpected empty text item: %s', item)
        return
    item_id = item.item_id
    left_id = item.left_id
    for c in chars[:-1]:
        right_id = CrdtId(item_id.part1, item_id.part2 + 1)
        yield CrdtSequenceItem(item_id, left_id, right_id, deleted_length, c)
        left_id = item_id
        item_id = right_id
    yield CrdtSequenceItem(item_id, left_id, item.right_id, deleted_length, chars[-1])

def expand_text_items(items   )    :
    """Expand a sequence of TextItems into single-character TextItems."""
    for item in items:
        yield from expand_text_item(item)

class CrdtStr:
    """String with CrdtIds for chars and optional properties.

    The properties apply to the whole `CrdtStr`. Use a list of
    `CrdtStr`s to represent a sequence of spans of text with different
    properties.

    """
    __match_args__ = ('s', 'i', 'properties')

    def __init__(self, s ='', i =None, properties =None)  :
        if i is None:
            i = []
        if properties is None:
            properties = {}
        self.s = s
        self.i = i
        self.properties = properties

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(s={self.s!r}, i={self.i!r}, properties={self.properties!r})'

    def __eq__(self, other):
        if not isinstance(other, CrdtStr):
            return NotImplemented
        return (self.s, self.i, self.properties) == (other.s, other.i, other.properties)

    def __str__(self):
        return self.s

class Paragraph:
    """Paragraph of text."""
    __match_args__ = ('contents', 'start_id', 'style')

    def __init__(self, contents , start_id , style =None)  :
        if style is None:
            style = lambda: LwwValue(CrdtId(0, 0), si.ParagraphStyle.PLAIN)()
        self.contents = contents
        self.start_id = start_id
        self.style = style

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(contents={self.contents!r}, start_id={self.start_id!r}, style={self.style!r})'

    def __eq__(self, other):
        if not isinstance(other, Paragraph):
            return NotImplemented
        return (self.contents, self.start_id, self.style) == (other.contents, other.start_id, other.style)

    def __str__(self):
        return ''.join((str(s) for s in self.contents))

class TextDocument:
    __match_args__ = ('contents',)

    def __init__(self, contents )  :
        self.contents = contents

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(contents={self.contents!r})'

    def __eq__(self, other):
        if not isinstance(other, TextDocument):
            return NotImplemented
        return (self.contents,) == (other.contents,)

    @classmethod
    def from_scene_item(cls, text ):
        """Extract spans of text with associated formatting and char ids.

        This uses the inline formatting introduced in v3.3.2.
        """
        char_formats = {k: lww.value for k, lww in text.styles.items()}
        if si.END_MARKER not in char_formats:
            char_formats[si.END_MARKER] = si.ParagraphStyle.PLAIN
        char_items = CrdtSequence(expand_text_items(text.items.sequence_items()))
        keys = list(char_items)
        properties = {'font-weight': 'normal', 'font-style': 'normal'}

        def handle_formatting_code(code):
            if code == 1:
                properties['font-weight'] = 'bold'
            elif code == 2:
                properties['font-weight'] = 'normal'
            elif code == 3:
                properties['font-style'] = 'italic'
            elif code == 4:
                properties['font-style'] = 'normal'
            else:
                _logger.warning('Unknown formatting code in text: %d', code)
            return properties

        def parse_paragraph_contents():
            if keys and char_items[keys[0]] == '\n':
                start_id = keys.pop(0)
            else:
                start_id = si.END_MARKER
            contents = []
            while keys:
                char = char_items[keys[0]]
                if isinstance(char, int):
                    handle_formatting_code(char)
                elif char == '\n':
                    break
                else:
                    assert len(char) <= 1
                    if not contents or contents[-1].properties != properties:
                        contents += [CrdtStr(properties=properties.copy())]
                    contents[-1].s += char
                    contents[-1].i += [keys[0]]
                keys.pop(0)
            return (start_id, contents)
        paragraphs = []
        while keys:
            start_id, contents = parse_paragraph_contents()
            if start_id in text.styles:
                p = Paragraph(contents, start_id, text.styles[start_id])
            else:
                p = Paragraph(contents, start_id)
            paragraphs += [p]
        doc = cls(paragraphs)
        return doc
