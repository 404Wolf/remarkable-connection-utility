'''
lines.py
This is the model for Lines, which come from RM files.

This file was written originally for the reMy project and modified for
RCU. Modifications are released under the AGPLv3 (or later).

reMy is a file manager for the reMarkable tablet.
Copyright (C) 2020  Emanuele D'Osualdo.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

...

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-23  Davis Remmel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

import log
from collections import namedtuple
import struct
import json

from .rmscene import scene_items as si
from .rmscene import read_tree, SceneTree, CrdtId
from .rmscene.text import TextDocument

Layer = namedtuple('Layer', ['strokes', 'name'])

Stroke = namedtuple(
    'Stroke',
    ['pen', 'color', 'unk1', 'width', 'unk2', 'segments']
)
Segment = namedtuple(
    'Segment',
    ['x', 'y', 'speed', 'direction', 'width', 'pressure']
)

HEADER_START = b'reMarkable .lines file, version='
S_HEADER_PAGE = struct.Struct('<{}ss10s'.format(len(HEADER_START)))
S_PAGE = struct.Struct('<BBH')    # TODO: might be 'I'
S_LAYER = struct.Struct('<I')
S_STROKE_V3 = struct.Struct('<IIIfI')
S_STROKE_V5 = struct.Struct('<IIIfII')
S_SEGMENT = struct.Struct('<ffffff')

class UnsupportedVersion(Exception):
    pass
class InvalidFormat(Exception):
    pass

def readStruct(fmt, source):
    buff = source.read(fmt.size)
    return fmt.unpack(buff)

def readStroke3(source):
    pen, color, unk1, width, n_segments = readStruct(S_STROKE_V3, source)
    return (pen, color, unk1, width, 0, n_segments)

def readStroke5(source):
    return readStruct(S_STROKE_V5, source)

# source is a filedescriptor from which we can .read(N)
def readLines(source, res_mod):
    try:
        header, ver, *_ = readStruct(S_HEADER_PAGE, source)
        if not header.startswith(HEADER_START):
            raise InvalidFormat("Header is invalid")
        ver = int(ver)
        if ver == 3:
            readStroke = readStroke3
        elif ver == 5:
            readStroke = readStroke5
        elif ver == 6:
            return readLines6(source, res_mod)
        else:
            raise UnsupportedVersion("RCU supports notebooks in the version 3, 5, and 6 format only")
        n_layers, _, _ = readStruct(S_PAGE, source)
        layers = []
        for l in range(n_layers):
            n_strokes, = readStruct(S_LAYER, source)
            strokes = []
            for s in range(n_strokes):
                pen, color, unk1, width, unk2, n_segments = readStroke(source)
                width *= res_mod
                segments = []
                for i in range(n_segments):
                    x, y, speed, direction, width, pressure = readStruct(S_SEGMENT, source)
                    x *= res_mod
                    y *= res_mod
                    width *= res_mod
                    segments.append(Segment(x, y, speed, direction, width, pressure))
                strokes.append(Stroke(pen, color, unk1, width, unk2, segments))
            layers.append(strokes)

        return (ver, layers)

    except struct.error:
        raise InvalidFormat("Error while reading page")

def readLines6(source, res_mod):
    source.seek(0)
    tree = read_tree(source)
    s = _v6_do_group(tree.root)
    layers = []
    for layer_id, strokes in enumerate(s):
        layers.append([])
        for line_id, line in enumerate(strokes):
            color = line.color
            tool = line.tool
            points = line.points

            stroke = Stroke(pen = int(tool),
                            color = color,
                            unk1 = None,
                            width = 30 * res_mod,
                            unk2 = None,
                            segments = [])

            for i, p in enumerate(line.points):
                seg = Segment(x = (p.x + (1404/2)) * res_mod,
                              y = p.y * res_mod,
                              speed = p.speed,
                              direction = p.direction,
                              width = p.width / 4 * res_mod,
                              pressure = p.pressure * 0.005) # guessed
                stroke.segments.append(seg)

            layers[layer_id].append(stroke)
    return (6, layers)

def _v6_do_group(item, level=0, indent=''):
    # rets = ([strokes], [snap_highlights])
    rets = []
    for child_id in item.children:
        child = item.children[child_id]
        # log.debug(indent + '-------- CHILD ---------')
        # if hasattr(child, 'label'):
        #     log.debug(indent + child.label.value)
        if type(child) == si.Group:
            if 0 == level:
                # The groups on the top level are layers.
                rets += [_v6_do_group(child, level=level+1, indent=indent+'  ')]
            else:
                # Other groups of strokes should be ignored.
                rets += _v6_do_group(child, level=level+1, indent=indent+'  ')
        elif type(child) == si.Line:
            rets += [child]
            # log.debug(indent, 'LINE')
        elif type(child) == si.GlyphRange:
            # GlyphRange are snap highlights
            pass
        elif type(child) is not type(None):
            log.error('unknown type', type(child))
            raise Exception("Unsupported feature of v6 lines; aborting. Type: " + str(type(child)))
    return rets

def readHighlights6(source):
    # Read snap highlights. No res_mod here, that's applied during
    # rendering (where the snap highlight conversion moves). This is
    # just a shim function to get fw.2 style highlights out of fw.3
    # files.
    source.seek(0)
    tree = read_tree(source)
    s = _v6_do_snaphighlights(tree.root)
    hlt_dict = {'highlights': s}
    return hlt_dict

def _v6_do_snaphighlights(item, level=0, indent=''):
    rets = []
    for child_id in item.children:
        child = item.children[child_id]
        if type(child) == si.Group:
            if 0 == level:
                # The groups on the top level are layers.
                rets += [_v6_do_snaphighlights(child, level=level+1, indent=indent+'  ')]
            else:
                # Other groups of strokes should be ignored.
                rets += _v6_do_snaphighlights(child, level=level+1, indent=indent+'  ')
        elif type(child) == si.GlyphRange:
            # This is ported from the 2.7 snap highlight format
            hlt_dict = {
                'color': int(child.color),
                'start': child.start,
                'length': child.length,
                'text': child.text,
                'rects': []
            }
            for rect in child.rectangles:
                hlt_dict['rects'].append({
                    'x': (rect.x + (1404/2)),
                    'y': rect.y,
                    'width': rect.w,
                    'height': rect.h
                })
            rets += [hlt_dict]
    return rets

def readText6(source):
    # Read snap highlights. No res_mod here, that's applied during
    # rendering (where the snap highlight conversion moves). This is
    # just a shim function to get fw.2 style highlights out of fw.3
    # files.
    source.seek(0)
    tree = read_tree(source)
    testdoc = TextDocument.from_scene_item(tree.root_text)

    out_text = ''
    for line in testdoc.contents:
        # annotated_
        fmt = None
        try:
            fmt = line.style.value
        except:
            pass

        fmt_line = ''
        for group in line.contents:
            s = group.s
            p = group.properties
            if 'font-weight' in p:
                if 'bold' == p['font-weight']:
                    s = '**{}**'.format(s)
            if 'font-style' in p:
                if 'italic' == p['font-style']:
                    s = '*{}*'.format(s)
            fmt_line += s

        def give_space(out_text):
            if '' != out_text \
               and '\n\n' != out_text[-2:]:
                out_text += '\n'
            return out_text

        if fmt == si.ParagraphStyle.HEADING:
            out_text = give_space(out_text)
            out_text += '# {}\n\n'.format(fmt_line)
        elif fmt == si.ParagraphStyle.HEADING2:
            out_text = give_space(out_text)
            out_text += '## {}\n\n'.format(fmt_line)
        elif fmt == si.ParagraphStyle.BULLET:
            out_text += '* {}\n'.format(fmt_line)
        elif fmt == si.ParagraphStyle.BULLET2:
            out_text += '  * {}\n'.format(fmt_line)
        elif fmt == si.ParagraphStyle.CHECKBOX:
            out_text += '* [ ] {}\n'.format(fmt_line)
        elif fmt == si.ParagraphStyle.CHECKBOX2:
            out_text += '* [X] {}\n'.format(fmt_line)
        else:
            if '' != fmt_line:
                out_text += '{}\n'.format(fmt_line)
            out_text = give_space(out_text)

    return out_text
