'''
parsers.py

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
'''

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import struct


def read_struct(f, fmt):
    sz = struct.calcsize(fmt)
    string = f.read(sz)
    return struct.unpack(fmt, string)


def write_struct(f, fmt, *args):
    data = struct.pack(fmt, *args)
    f.write(data)


class Value(object):
    @classmethod
    def from_bytes(cls, _data):
        raise NotImplementedError()

    def bytes(self):
        raise NotImplementedError()

    def __bytes__(self):
        return self.bytes()


class Boolean(Value):
    def __init__(self, value):
        assert isinstance(value, bool)
        self.boolean = value
        Value.__init__(self)

    @classmethod
    def from_bytes(cls, data):
        val, = struct.unpack(b'>b', data)
        return cls([False, True][val])

    def bytes(self):
        return struct.pack(b'>b', 1 if self.boolean else 0)


class Integer(Value):
    def __init__(self, value):
        assert isinstance(value, int)
        self.integer = value
        Value.__init__(self)

    @classmethod
    def from_bytes(cls, data):
        val, = struct.unpack(b'>i', data)
        return cls(val)

    def bytes(self):
        return struct.pack(b'>i', self.integer)


class Enum(Integer):
    pass
