'''
svgtools.py
This file provides functions for manipulating SVG and bitmap images.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-22  Davis Remmel

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

from PySide2.QtCore import QByteArray, QIODevice, QBuffer
from PySide2.QtGui import QImage, QPainter, QPixmap
from PySide2.QtSvg import QSvgRenderer

import log

import os

import io
import xml.etree.ElementTree as ET


import base64
import textwrap

import ctypes

def svg_to_png(svgdata, size):
    # svgdata: QByteArray
    # size: (width, height)
    # Retuns QByteArray with PNG data
    image = QImage(*size, QImage.Format_RGB16)
    image.fill(0xFFFF)
    painter = QPainter(image)
    renderer = QSvgRenderer(convert_to_svgt(svgdata))
    renderer.render(painter)
    painter.end()
    ba = QByteArray()
    buffer = QBuffer(ba)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    return ba

def svg_to_rgb8_bytes(svgdata, size):
    # svgdata: QByteArray
    # size: (width, height)
    # Retuns QByteArray with PNG data
    image = QImage(*size, QImage.Format_RGB888)
    image.fill(0xFFFFFF)
    painter = QPainter(image)
    renderer = QSvgRenderer(convert_to_svgt(svgdata))
    renderer.render(painter)
    painter.end()
    # f = open('/tmp/test.rgb', 'wb+')
    # f.write(bytes(image.bits()))
    # f.close()
    return bytes(image.bits())

def svg_to_pixmap(svgdata, size):
    # Convert SVG to tiny spec for Qt
    image = QImage(*size, QImage.Format_RGB16)
    image.fill(0xFFFF)
    painter = QPainter(image)
    renderer = QSvgRenderer(convert_to_svgt(svgdata))
    renderer.render(painter)
    painter.end()
    pxmap = QPixmap.fromImage(image)
    return pxmap

def template_to_painter(painter, template, size, vector=False):
    # This function really doesn't belong here. This will need to
    # get moved into the Template class itself, I think.
    # Setting vector=True will direclty paint the SVG, otherwise
    # the template will be rasterized.
    if not vector:
        pxm = svg_to_pixmap(convert_to_svgt(template.svg),
                            size)
        painter.drawPixmap(0, 0, *size, pxm)
    else:
        renderer = QSvgRenderer(convert_to_svgt(template.svg))
        renderer.render(painter)

def convert_to_svgt(svgdata):
    # As of 2.3.0.16, one SVG template includes <symbol> which is not
    # supported in the SVG Tiny 1.2 spec (what Qt implements). So, these
    # need to be adjusted in a somewhat-hacky way.
    svgns = 'http://www.w3.org/2000/svg'
    xlinkns = 'http://www.w3.org/1999/xlink'
    ET.register_namespace('', svgns)
    ET.register_namespace('xlink', xlinkns)
    try:
        tree = ET.parse(io.BytesIO(svgdata))
        root = tree.getroot()
        # Get all the symbols
        symbols = root.findall('.//{' + svgns + '}symbol')
        # Uses
        uses = root.findall('.//{' + svgns + '}use')

        if not len(symbols) and not len(uses):
            return svgdata
        
        # Match uses to symbols
        for use in uses:
            # Find the symbol
            match = use.attrib['{' + xlinkns + '}href'].strip('#')
            symbol = None
            for s in symbols:
                if s.attrib['id'] == match:
                    symbol = s
                    break
            if symbol:
                # Convert the <use> to a <g>
                use.tag = 'g'
                path = ET.SubElement(use, symbol[0].tag, symbol[0].attrib)
                path.attrib['transform'] = 'translate({},{})'.format(
                    use.attrib['x'],
                    use.attrib['y'])
        outstuff = io.BytesIO()
        tree.write(outstuff)
        outstuff.seek(0)
        return outstuff.read()
    except Exception as e:
        log.error('error converting svg to svg-tiny')
        log.error(str(e))
        log.info('using unfiltered svg data')
    return svgdata

def svg_get_size(svgdata):
    # Returns the active area size of the svgdata's viewBox
    svgns = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', svgns)
    try:
        tree = ET.parse(io.BytesIO(svgdata))
        root = tree.getroot()
        viewbox = root.attrib['viewBox'].split(' ')
        width = float(viewbox[2]) - float(viewbox[0])
        height = float(viewbox[3]) - float(viewbox[1])
        return (width, height)
    except Exception as e:
        log.error('svg_get_size returned an error')
        log.error(e)
    return

def svg_orientation_correction(svgdata):
    # Apply orientation correction to SVG data (make it portrait) so it
    # aligns as-expected on the tablet. If no correction is needed, this
    # will return the original svgdata. This is used when uploading
    # new templates.

    # Technique: change the width, height, and viewBox of the <svg>
    # element. Apply a transform to rotate this element -90 degrees.

    # Will these namespaces suffice for most users? AFAIK these need
    # to be explicitly stated--there isn't a way to first parse the
    # XML without having them registered (which doesn't make sense
    # to me, why can't they be taken out of the root tag?).
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    try:
        tree = ET.parse(io.BytesIO(svgdata))
        root = tree.getroot()
        width = root.attrib['width']
        height = root.attrib['height']
        viewbox = root.attrib['viewBox'].split(' ')

        # Is the SVG already in portrait?
        if int(width) < int(height):
            return svgdata
        log.info('rotating svg orientation')

        # Swap out width and height
        root.attrib['width'] = height
        root.attrib['height'] = width
        vb2 = [viewbox[1], viewbox[0], viewbox[3], viewbox[2]]
        root.attrib['viewBox'] = ' '.join(vb2)

        # Apply -90 transform
        root.attrib['transform'] = 'translate(0, {}) rotate(-90)'\
            .format(width)

        # Write out to new svgdata
        svgdata_rot = io.BytesIO()
        tree.write(svgdata_rot)
        svgdata_rot.seek(0)
        return svgdata_rot.read()
    except Exception as e:
        log.error('error applying svg orientation correction')
        log.error(e)
    
    return svgdata

def png_to_svg(png_filepath):
    # Shove a PNG into an SVG container and return the SVG data.
    # todo: allow read direct png data, no intermediary file ...
    qimage = QImage()
    if not qimage.load(str(png_filepath)):
        log.error('error loading image: {}'.format(png_filepath))
        return
    rect = qimage.rect()
    width = rect.width()
    height = rect.height()
    # Embed the PNG data within an SVG.
    pngdata = QByteArray()
    pngbuf = QBuffer(pngdata)
    pngbuf.open(QIODevice.WriteOnly)
    qimage.save(pngbuf, 'PNG')
    png_b64 = "data:image/png;base64,"
    # Wrap the base64-encoded PNG data so it lessens the chance of
    # other parsers barfing.
    png_b64 += '\n'.join(textwrap.wrap(
        base64.b64encode(pngdata.data()).decode('utf-8'), 72))
    svgdata = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
   xmlns:svg="http://www.w3.org/2000/svg" xmlns="http://www.w3.org/2000/svg"
xmlns:xlink="http://www.w3.org/1999/xlink"
   width="{{width}}" height="{{height}}" viewBox="0 0 {{width}} {{height}}"
   version="1.1" id="svg0">
   <image width="{{width}}" height="{{height}}" preserveAspectRatio="none"
          id="img0" x="0" y="0"
          xlink:href="{{pngdata}}" />
</svg>
'''
    svgdata = svgdata.replace('{{width}}', str(width))
    svgdata = svgdata.replace('{{height}}', str(height))
    svgdata = svgdata.replace('{{pngdata}}', png_b64)
    return bytes(svgdata, 'utf-8')
