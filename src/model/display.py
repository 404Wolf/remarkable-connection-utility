'''
display.py
This handles the display of each reMarkable model, which is most-useful
when taking screenshots.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-24  Davis Remmel

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

...

reStream was used for the RM2 framebuffer capture.
Copyright (c) 2020 Rien Maertens <Rien.Maertens@posteo.be>

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

import log
from PySide2.QtCore import QByteArray, QBuffer, QIODevice
from PySide2.QtGui import QImage, QMatrix
import math
import gc
import ctypes

class DisplayRMGeneric:
    @classmethod
    def from_model(cls, model):
        # Initialize for the model-specific display.
        real_model = model.device_info['model']
        if 'RM100' == real_model or 'RM102' == real_model:
            return DisplayRM1(model)
        if 'RM110' == real_model:
            # Are hacks applied (using rm2fb)? There should be the
            # existence of a new framebuffer.
            if DisplayRM2_rm2fb.applies(model):
                return DisplayRM2_rm2fb(model)
            elif model.is_gt_eq_xochitl_version('3.6'):
                return DisplayRM2_3_6(model)
            else:
                return DisplayRM2(model)
        log.error('model not recognized: cannot get display')
        return None

    def __init__(self):
        pass


class ProtoDisplayRM:
    screenwidth = 1404
    screenheight = 1872
    realwidth = 1408
    dpi = 226
    bpp = 2
    pixformat = QImage.Format_Grayscale16
    portrait_size = (1404, 1872)
    devicefile = '/dev/fb0'
    
    def __init__(self, model):
        # Stores raw image buffer. The exact function that sets this may
        # vary depending upon the rM model.
        self.model = model

        # Cache of raw framebuffer data. Speeds up soft-refresh
        # operations like getting a rotated copy.
        self.raw_pixel_data = None
        self.capture_fb_cmd = None

    def invalidate_pixel_cache(self, clear_addr=False):
        self.raw_pixel_data = None
        gc.collect()
        if clear_addr:
            log.info('clearing cached framebuffer memory address')
            self.capture_fb_cmd = None

    def get_png_data(self, rotation=0):
        return


class DisplayRM1(ProtoDisplayRM):
    def _grab_fb(self):
        out, err = self.model.run_cmd(
            'dd if={} bs=5271552 count=1'.format(type(self).devicefile),
            raw=True)
        if len(out) == 0:
            log.error('framebuffer length was 0; aborting')
            return
        self.raw_pixel_data = out
        return self.raw_pixel_data

    def get_png_data(self, rotation=0):
        pixformat = self.pixformat
        realwidth = self.realwidth
        width = self.screenwidth
        height = self.screenheight

        # Use cached data whenever possible (refreshing takes seconds).
        if self.raw_pixel_data:
            raw_fb = self.raw_pixel_data
        else:
            raw_fb = self._grab_fb()

        # The copy() operation crops off the black border. Convert to
        # Gray8 to reduce saved file size.
        qimage = QImage(raw_fb, realwidth, height, pixformat).copy(
            0, 0, width, height).convertToFormat(
                QImage.Format_Grayscale8)

        center = qimage.rect().center()
        matrix = QMatrix()
        if rotation:
            matrix.translate(center.x(), center.y())
            matrix.rotate(rotation)
            if rotation in (90, 270):
                width, height = (height, width)
        qimage_rot = qimage.transformed(matrix)

        # Dump as PNG
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        qimage_rot.save(buffer, 'PNG')
        pngdata = ba.data()

        ctypes.c_long.from_address(id(qimage)).value=1
        ctypes.c_long.from_address(id(qimage_rot)).value=1
        del qimage
        del qimage_rot
        gc.collect()
        
        return (pngdata, (width, height))


class DisplayRM2_rm2fb(ProtoDisplayRM):
    devicefile = '/dev/shm/swtfb.01'
    realwidth = 1404

    @classmethod
    def applies(cls, model):
        cmd = 'test -e {}; echo $?'.format(cls.devicefile)
        out, err = model.run_cmd(cmd)
        if len(err):
            log.error('problem testing for rm2fb')
            log.error(err)
            return
        out = out.strip('\n')
        if '0' == out:
            log.info('detected rm2fb')
            return True
        return False


class DisplayRM2(ProtoDisplayRM):
    screenwidth = 1872
    screenheight = 1404
    realwidth = 1872
    bpp = 1
    pixformat = QImage.Format_Grayscale8
    pagesize = 4096

    def __init__(self, model):
        ProtoDisplayRM.__init__(self, model)

    def _cache_memory_locations(self):
        log.info('caching display memory locations')
        width = type(self).realwidth
        height = type(self).screenheight
        bpp = type(self).bpp
        self.fb_size = width * height * bpp

        out, err = self.model.run_cmd('pidof xochitl')
        if len(err):
            log.error('problem getting pid of xochitl')
            log.error(e)
            return
        pid = out.strip()

        # In-memory framebuffer location is just after the noise from
        # /dev/fb0.
        out, err = self.model.run_cmd("grep -C1 '{}' /proc/{}/maps | tail -n1 | sed 's/-.*$//'".format(type(self).devicefile, pid))
        if len(err):
            log.error('problem getting address of RM2 framebuffer')
            log.error(err)
            return
        # log.debug('++ memory address', out.strip())
        skip_bytes = int(out.strip(), 16) + 8
        block_size = type(self).pagesize
        fb_start = int(skip_bytes / block_size)
        self.fb_offset = skip_bytes % block_size
        fb_length = math.ceil(self.fb_size / block_size)
        self.capture_fb_cmd = '''dd if=/proc/{}/mem bs={} \
                                 skip={} count={} 2>/dev/null'''.format(
                                     pid, block_size,
                                     fb_start, fb_length)
        # self.capture_fb_cmd = 'cat /tmp/framebuffer.raw'
        # log.debug(self.capture_fb_cmd)

    def _grab_fb(self):
        if not self.capture_fb_cmd:
            self._cache_memory_locations()
        out, err = self.model.run_cmd(self.capture_fb_cmd, raw=True)
        if len(err):
            log.error('problem grabbing framebuffer')
            log.error(str(err))
            return
            
        # Because the grab captured excess data (it was aligned to the
        # page size) we need to trim some off.
        raw_fb_4bit = out[self.fb_offset:][:self.fb_size]

        # RM2 only uses the 4 least significant bits (16 shades of gray)
        raw_fb_8bit = bytearray()
        for i, b in enumerate(raw_fb_4bit):
            raw_fb_8bit.append((b & 0b00001111) * 17)

        self.raw_pixel_data = raw_fb_8bit
        return self.raw_pixel_data

    def get_png_data(self, rotation=0):
        width = type(self).realwidth
        height = type(self).screenheight
        pixformat = type(self).pixformat
        
        # Use cached data whenever possible (refreshing takes seconds).
        if self.raw_pixel_data:
            raw_fb = self.raw_pixel_data
        else:
            raw_fb = self._grab_fb()

        qimage = QImage(raw_fb, width, height, pixformat)

        # Compensate for RM2 portrait being -90deg.
        rotation -= 90
        center = qimage.rect().center()
        matrix = QMatrix()
        if rotation:
            matrix.translate(center.x(), center.y())
            matrix.rotate(rotation)
        rotated_qi = qimage.transformed(matrix)

        if 0 != rotation % 180:
            width, height = (height, width)

        # Dump as PNG
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        rotated_qi.save(buffer, 'PNG')
        pngdata = ba.data()

        ctypes.c_long.from_address(id(qimage)).value=1
        ctypes.c_long.from_address(id(rotated_qi)).value=1
        del qimage
        del rotated_qi
        gc.collect()
        
        return (pngdata, (width, height))


class DisplayRM2_3_6(DisplayRM2):
    # For whatever reason, the framebuffer format changed in fw.3.6.
    # Every other byte holds data (and others are 0x00). Bytes like
    # 0xFF are represented as 0b00011110, and need to be shifted
    # right. The image also needs a flip and transpose.
    bpp = 2

    def _grab_fb(self):
        if not self.capture_fb_cmd:
            self._cache_memory_locations()
        out, err = self.model.run_cmd(self.capture_fb_cmd, raw=True)
        if len(err):
            log.error('problem grabbing framebuffer')
            log.error(str(err))

        # Because the grab captured excess data (it was aligned to the
        # page size) we need to trim some off.
        raw_fb_4bit = out[self.fb_offset:][:self.fb_size]

        # Read every other byte, ignoring 0x00 in between
        outbin = bytearray()
        length = len(raw_fb_4bit)
        b = 0
        while b < length:
            r1 = raw_fb_4bit[b]
            r1 = (r1 >> 1) * 17  # Convert to 8bit gray
            outbin.append(r1)
            b += 2
        # Reverse to match fw.3.5 framebuffer format
        outbin.reverse()
        del raw_fb_4bit

        # Flip image to match fw.3.5 framebuffer format
        outbin2 = bytearray()
        width = type(self).realwidth
        l = 0
        while l < len(outbin):
            start = l
            end = l + width
            sect = outbin[start:end]
            sect.reverse()
            outbin2 += sect
            l += width
        del outbin
        raw_fb_8bit = outbin2
        del outbin2

        self.raw_pixel_data = raw_fb_8bit
        return self.raw_pixel_data
