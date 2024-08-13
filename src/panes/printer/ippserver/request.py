'''
request.py

This file was written originally for the ipp-server project and modified
for RCU. Modifications are released under the AGPLv3 (or later).

ipp-server is a pure-Python implementation of a virtual IPP printer.
Copyright (c) 2017, 2018: David Batley (h2g2bob), Alexander (devkral)

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are 
met:

1. Redistributions of source code must retain the above copyright 
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright 
   notice, this list of conditions and the following disclaimer in the 
   documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT 
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A 
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT 
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, 
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT 
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, 
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY 
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT 
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE 
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
along with this program.  If not, see <https://www.gnu.org/licenses/>
'''

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from io import BytesIO
import operator
import itertools

from .parsers import read_struct, write_struct
from .constants import SectionEnum, TagEnum


class IppRequest(object):
    def __init__(self, version, opid_or_status, request_id, attributes):
        self.version = version  # (major, minor)
        self.opid_or_status = opid_or_status
        self.request_id = request_id
        self._attributes = attributes

    def __cmp__(self, other):
        return self.__eq__(other)

    def __eq__(self, other):
        return type(self) == type(other) or self._attributes == other._attributes

    def __repr__(self):
        return 'IppRequest(%r, 0x%04x, 0x%02x, %r)' % (
            self.version,
            self.opid_or_status,
            self.request_id,
            self._attributes,)

    @classmethod
    def from_string(cls, string):
        return cls.from_file(BytesIO(string))

    @classmethod
    def from_file(cls, f):
        version = read_struct(f, b'>bb')  # (major, minor)
        operation_id_or_status_code, request_id = read_struct(f, b'>hi')

        attributes = {}
        current_section = None
        current_name = None
        while True:
            tag, = read_struct(f, b'>B')

            if tag == SectionEnum.END:
                break
            elif SectionEnum.is_section_tag(tag):
                current_section = tag
                current_name = None
            else:
                if current_section is None:
                    raise Exception('No section delimiter')

                name_len, = read_struct(f, b'>h')
                if name_len == 0:
                    if current_name is None:
                        raise Exception('Additional attribute needs a name to follow')
                    else:
                        # additional attribute, under the same name
                        pass
                else:
                    current_name = f.read(name_len)

                value_len, = read_struct(f, b'>h')
                value_str = f.read(value_len)
                attributes.setdefault((current_section, current_name, tag), []).append(value_str)

        return cls(version, operation_id_or_status_code, request_id, attributes)

    def to_string(self):
        sio = BytesIO()
        self.to_file(sio)
        return sio.getvalue()

    def to_file(self, f):
        version_major, version_minor = 1, 0
        write_struct(f, b'>bb', version_major, version_minor)
        write_struct(f, b'>hi', self.opid_or_status, self.request_id)

        for section, attrs_in_section in itertools.groupby(
            sorted(self._attributes.keys()), operator.itemgetter(0)
        ):
            write_struct(f, b'>B', section)
            for key in attrs_in_section:
                _section, name, tag = key
                for i, value in enumerate(self._attributes[key]):
                    write_struct(f, b'>B', tag)
                    if i == 0:
                        write_struct(f, b'>h', len(name))
                        f.write(name)
                    else:
                        write_struct(f, b'>h', 0)
                    # Integer must be 4 bytes
                    assert (tag != TagEnum.integer or len(value) == 4)
                    write_struct(f, b'>h', len(value))
                    f.write(value)
        write_struct(f, b'>B', SectionEnum.END)

    def attributes_to_multilevel(self, section=None):
        ret = {}
        for key in self._attributes.keys():
            if section and section != key[0]:
                continue
            ret.setdefault(key[0], {})
            ret[key[0]].setdefault(key[1], {})
            ret[key[0]][key[1]][key[2]] = self._attributes[key]
        return ret

    def lookup(self, section, name, tag):
        return self._attributes[section, name, tag]

    def only(self, section, name, tag):
        items = self.lookup(section, name, tag)
        if len(items) == 1:
            return items[0]
        elif len(items) == 0:
            raise RuntimeError('self._attributes[%r, %r, %r] is empty list' % (section, name, tag,))
        else:
            raise ValueError('self._attributes[%r, %r, %r] has more than one value' % (section, name, tag,))
