'''
Data structure representing CRDT sequence.

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

import typing as tp
from typing import Iterable
from collections import defaultdict
from .tagged_block_common import CrdtId
_T = tp.TypeVar('_T', covariant=True)

class CrdtSequenceItem(tp.Generic[_T]):
    __match_args__ = ('item_id', 'left_id', 'right_id', 'deleted_length', 'value')

    def __init__(self, item_id , left_id , right_id , deleted_length , value )  :
        self.item_id = item_id
        self.left_id = left_id
        self.right_id = right_id
        self.deleted_length = deleted_length
        self.value = value

    def __repr__(self):
        cls = type(self).__name__
        return f'{cls}(item_id={self.item_id!r}, left_id={self.left_id!r}, right_id={self.right_id!r}, deleted_length={self.deleted_length!r}, value={self.value!r})'

    def __eq__(self, other):
        if not isinstance(other, CrdtSequenceItem):
            return NotImplemented
        return (self.item_id, self.left_id, self.right_id, self.deleted_length, self.value) == (other.item_id, other.left_id, other.right_id, other.deleted_length, other.value)
_Ti = tp.TypeVar('_Ti', covariant=False)

class CrdtSequence(tp.Generic[_Ti]):
    """Ordered CRDT Sequence container.

    The Sequence contains `CrdtSequenceItem`s, each of which has an ID and
    left/right IDs establishing a partial order.

    Iterating through the `CrdtSequence` yields IDs following this order.

    """

    def __init__(self, items=None):
        if items is None:
            items = []
        self._items = {item.item_id: item for item in items}

    def __eq__(self, other):
        if isinstance(other, CrdtSequence):
            return self._items == other._items
        if isinstance(other, (list, tuple)):
            return self == CrdtSequence(other)
        raise NotImplemented

    def __repr__(self):
        return 'CrdtSequence(%s)' % ', '.join((str(i) for i in self._items.values()))

    def __iter__(self)  :
        """Return ids in order"""
        yield from toposort_items(self._items.values())

    def keys(self)  :
        """Return CrdtIds in order."""
        return list(self)

    def values(self)  :
        """Return list of sorted values."""
        return [self[item_id] for item_id in self]

    def items(self)   :
        """Return list of sorted key, value pairs."""
        return [(item_id, self[item_id]) for item_id in self]

    def __getitem__(self, key )  :
        """Return item with key"""
        return self._items[key].value

    def sequence_items(self)  :
        """Iterate through CrdtSequenceItems."""
        return list(self._items.values())

    def add(self, item ):
        if item.item_id in self._items:
            raise ValueError('Already have item %s' % item.item_id)
        self._items[item.item_id] = item
END_MARKER = CrdtId(0, 0)

def toposort_items(items )  :
    """Sort SequenceItems based on left and right ids.

    Returns `CrdtId`s in the sorted order.

    """
    item_dict = {}
    for item in items:
        item_dict[item.item_id] = item
    if not item_dict:
        return

    def _side_id(item, side):
        side_id = getattr(item, f'{side}_id')
        if side_id == END_MARKER:
            return '__start' if side == 'left' else '__end'
        else:
            return side_id
    data = defaultdict(set)
    for item in item_dict.values():
        left_id = _side_id(item, 'left')
        right_id = _side_id(item, 'right')
        data[item.item_id].add(left_id)
        data[right_id].add(item.item_id)
    sources_not_in_data = {dep for deps in data.values() for dep in deps} - {k for k in data.keys()}
    data.update({k: set() for k in sources_not_in_data})
    while True:
        next_items = {item for item, deps in data.items() if not deps}
        if next_items == {'__end'}:
            break
        assert next_items
        yield from sorted((k for k in next_items if k in item_dict))
        data = {item: deps - next_items for item, deps in data.items() if item not in next_items}
    if data != {'__end': set()}:
        raise ValueError('cyclic dependency')
