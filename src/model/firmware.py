'''
firmware.py
This handles general functions relating to device firmware.

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

...

extractor.py
Copyright (c) 2021 ddvk

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

from .update_metadata_pb2 import DeltaArchiveManifest 
import sys, os, struct, bz2

import log

class Firmware():
    BLOCK_SIZE = 4096

    def __init__(self, fw_bin):
        self.fw_bin = fw_bin
        
    def extract_to_file(self, outpath, prog_cb=lambda x: (),
                        abort_func=lambda x: ()):
        with open(outpath,'wb') as out:
            with open(self.fw_bin,'rb') as f:
                magic = f.read(4)
                if magic != b'CrAU':
                    raise 'Wrong header'
                major = struct.unpack('>Q',f.read(8))[0]
                if major != 1:
                    raise 'Unsupported version'
                size = struct.unpack('>Q', f.read(8))[0]
                manifest = f.read(size)
                msg = DeltaArchiveManifest.FromString(manifest)
                pos = f.tell()
                written=0
                for chunk in msg.install_operations:
                    f.seek(pos + chunk.data_offset)
                    data  = f.read(chunk.data_length)
                    dst_offset = chunk.dst_extents[0].start_block * self.BLOCK_SIZE
                    dst_length  = chunk.dst_extents[0].num_blocks * self.BLOCK_SIZE
                    if chunk.type == 1:
                        data = bz2.decompress(data)
                    elif chunk.type == 0:
                        log.info('offset:{}'.format(dst_offset))
                    else:
                        raise 'Unsupported type ' + chunk.type
    
                    padding = dst_length - len(data)
                    if (padding < 0):
                        raise 'Wrong length'
                    out.seek(dst_offset)
                    out.write(data)
                    out.write(b'\x00'*padding)
                    written += len(data)
                    prog_cb(written)
