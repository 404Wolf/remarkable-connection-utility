'''
ppd.py

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


class PPD(object):
    def text(self):
        raise NotImplementedError()


class BasicPostscriptPPD(PPD):
    product = 'RCU'
    manufacturer = 'Davis Remmel'
    model = 'RCU Virtual Printer'

    def text(self):
        return b'''*PPD-Adobe: "4.3"

*%% This is a minimal config file
*%% and is almost certainly missing lots of features

*%%     ___________
*%%    |           |
*%%    | PPD File. |
*%%    |           |
*%%  (============(@|
*%%  |            | |
*%%  | [        ] | |
*%%  |____________|/
*%%

*%% About this PPD file
*LanguageLevel: "2"
*LanguageEncoding: ISOLatin1
*LanguageVersion: English
*PCFileName: "%(ppdfilename)s"

*%% Basic capabilities of the device
*FileSystem: False

*%% Printer name
*Product: "%(product)s"
*Manufacturer:  "%(manufacturer)s"
*ModelName: "%(model)s"

*%% Color
*ColorDevice: True
*DefaultColorSpace: CMYK
*Throughput: "1"
*Password: "0"
''' % \
{
    b"product": self.product.encode("ascii"),
    b"manufacturer": self.manufacturer.encode("ascii"),
    b"model": self.model.encode("ascii"),
    b"ppdfilename": b"%s%s" % (self.model.encode("ascii"), b'.ppd')
}


class BasicPdfPPD(BasicPostscriptPPD):
    model = 'RCU Virtual Printer'

    def text(self):
        return super(BasicPdfPPD, self).text() + b'''
*% The printer can only handle PDF files, so get CUPS to send that
*% https://en.wikipedia.org/wiki/CUPS#Filter_system
*% https://www.cups.org/doc/spec-ppd.html
*cupsFilter2: "application/pdf application/vnd.cups-pdf 0 pdftopdf"
*cupsFilter2: "application/postscript application/vnd.cups-pdf 50 pstopdf"
'''
