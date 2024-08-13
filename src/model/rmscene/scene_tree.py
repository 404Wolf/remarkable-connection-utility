'''
Build scene tree structure from block data.

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

import logging
import typing as tp
from .tagged_block_common import CrdtId
from .crdt_sequence import CrdtSequenceItem
from . import scene_items as si
_logger = logging.getLogger(__name__)
ROOT_ID = CrdtId(0, 1)

class SceneTree:

    def __init__(self):
        self.root = si.Group(ROOT_ID)
        self._node_ids = {self.root.node_id: self.root}
        self.root_text  = None

    def __contains__(self, node_id ):
        return node_id in self._node_ids

    def __getitem__(self, node_id ):
        return self._node_ids[node_id]

    def add_node(self, node_id , parent_id ):
        if node_id in self._node_ids:
            raise ValueError('Node %s already in tree' % node_id)
        node = si.Group(node_id)
        self._node_ids[node_id] = node

    def add_item(self, item , parent_id ):
        if parent_id not in self._node_ids:
            raise ValueError('Parent id not known: %s' % parent_id)
        parent = self._node_ids[parent_id]
        parent.children.add(item)

    def walk(self)  :
        """Iterate through all leaf items (not groups)."""
        yield from _walk_items(self.root)

def _walk_items(item):
    if isinstance(item, si.Group):
        for child in item.children.values():
            yield from _walk_items(child)
    else:
        yield item
