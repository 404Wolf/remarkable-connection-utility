'''
constants.py

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

try:
    from enum import IntEnum
except ImportError:
    IntEnum = object


class SectionEnum(IntEnum):
    # delimiters (sections)
    SECTIONS      = 0x00
    SECTIONS_MASK = 0xf0
    operation     = 0x01
    job           = 0x02
    END           = 0x03
    printer       = 0x04
    unsupported   = 0x05

    @classmethod
    def is_section_tag(cls, tag):
        return (tag & cls.SECTIONS_MASK) == cls.SECTIONS


class TagEnum(IntEnum):
    unsupported_value     = 0x10
    unknown_value         = 0x12
    no_value              = 0x13

    # int types
    integer               = 0x21
    boolean               = 0x22
    enum                  = 0x23

    # string types
    octet_str             = 0x30
    datetime_str          = 0x31
    resolution            = 0x32
    range_of_integer      = 0x33
    text_with_language    = 0x35
    name_with_language    = 0x36

    text_without_language = 0x41
    name_without_language = 0x42
    keyword               = 0x44
    uri                   = 0x45
    uri_scheme            = 0x46
    charset               = 0x47
    natural_language      = 0x48
    mime_media_type       = 0x49


class StatusCodeEnum(IntEnum):
    # https://tools.ietf.org/html/rfc2911#section-13.1
    ok = 0x0000
    server_error_internal_error = 0x0500
    server_error_operation_not_supported = 0x0501
    server_error_job_canceled = 0x508


class OperationEnum(IntEnum):
    # https://tools.ietf.org/html/rfc2911#section-4.4.15
    print_job = 0x0002
    validate_job = 0x0004
    cancel_job = 0x0008
    get_job_attributes = 0x0009
    get_jobs = 0x000a
    get_printer_attributes = 0x000b

    # 0x4000 - 0xFFFF is for extensions
    # CUPS extensions listed here:
    # https://web.archive.org/web/20061024184939/http://uw714doc.sco.com/en/cups/ipp.html
    cups_get_default = 0x4001
    cups_list_all_printers = 0x4002


class JobStateEnum(IntEnum):
    # https://tools.ietf.org/html/rfc2911#section-4.3.7
    pending = 3
    pending_held = 4
    processing = 5
    processing_stopped = 6
    canceled = 7
    aborted = 8
    completed = 9
