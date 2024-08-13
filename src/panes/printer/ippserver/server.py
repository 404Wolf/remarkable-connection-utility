'''
server.py

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

from io import BytesIO
import threading
try:
    import socketserver
except ImportError:
    import SocketServer as socketserver
try:
    from http.server import BaseHTTPRequestHandler
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler
import time
import logging
import os.path

from . import request


def local_file_location(filename):
    return os.path.join(os.path.dirname(__file__), 'data', filename)


def _get_next_chunk(rfile):
    while True:
        chunk_size_s = rfile.readline()
        logging.debug('chunksz=%r', chunk_size_s)
        if not chunk_size_s:
            raise RuntimeError(
                'Socket closed in the middle of a chunked request'
            )
        if chunk_size_s.strip() != b'':
            break

    chunk_size = int(chunk_size_s, 16)
    if chunk_size == 0:
        return b''
    chunk = rfile.read(chunk_size)
    logging.debug('chunk=0x%x', len(chunk))
    return chunk


def read_chunked(rfile):
    while True:
        chunk = _get_next_chunk(rfile)
        if chunk == b'':
            rfile.close()
            break
        else:
            yield chunk


class IPPRequestHandler(BaseHTTPRequestHandler):
    default_request_version = "HTTP/1.1"
    protocol_version = "HTTP/1.1"

    def parse_request(self):
        ret = BaseHTTPRequestHandler.parse_request(self)
        if 'chunked' in self.headers.get('transfer-encoding', ''):
            self.rfile = BytesIO(b"".join(read_chunked(self.rfile)))
        self.close_connection = True
        return ret

    if not hasattr(BaseHTTPRequestHandler, "send_response_only"):
        def send_response_only(self, code, message=None):
            """Send the response header only."""
            if message is None:
                if code in self.responses:
                    message = self.responses[code][0]
                else:
                    message = ''
            if not hasattr(self, '_headers_buffer'):
                self._headers_buffer = []
            self._headers_buffer.append(
                (
                    "%s %d %s\r\n" % (self.protocol_version, code, message)
                ).encode('utf-8')
            )

    def log_error(self, format, *args):
        logging.error(format, *args)

    def log_message(self, format, *args):
        logging.debug(format, *args)

    def send_headers(self, status=200, content_type='text/plain',
                     content_length=None):
        self.log_request(status)
        self.send_response_only(status, None)
        self.send_header('Server', 'rcu-virtual-printer')
        self.send_header('Date', self.date_time_string())
        self.send_header('Content-Type', content_type)
        if content_length:
            self.send_header('Content-Length', '%u' % content_length)
        self.send_header('Connection', 'close')
        self.end_headers()

    def do_POST(self):
        self.handle_ipp()

    def do_GET(self):
        self.handle_www()

    def handle_www(self):
        if self.path == '/':
            self.send_headers(
                status=200, content_type='text/plain'
            )
            with open(local_file_location('homepage.txt'), 'rb') as wwwfile:
                self.wfile.write(wwwfile.read())
        elif self.path.endswith('.ppd'):
            self.send_headers(
                status=200, content_type='text/plain'
            )
            self.wfile.write(self.server.behaviour.ppd.text())
        else:
            self.send_headers(
                status=404, content_type='text/plain'
            )
            with open(local_file_location('404.txt'), 'rb') as wwwfile:
                self.wfile.write(wwwfile.read())

    def handle_expect_100(self):
        """ Disable """
        return True

    def handle_ipp(self):
        self.ipp_request = request.IppRequest.from_file(self.rfile)

        if self.server.behaviour.expect_page_data_follows(self.ipp_request):
            self.send_headers(
                status=100, content_type='application/ipp'
            )
            postscript_file = self.rfile
        else:
            postscript_file = None

        ipp_response = self.server.behaviour.handle_ipp(
            self.ipp_request, postscript_file
        ).to_string()
        self.send_headers(
            status=200, content_type='application/ipp',
            content_length=len(ipp_response)
        )
        self.wfile.write(ipp_response)


class IPPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, address, request_handler, behaviour):
        self.behaviour = behaviour
        socketserver.ThreadingTCPServer.__init__(self, address, request_handler)  # old style class!


def wait_until_ctrl_c():
    try:
        while True:
            time.sleep(300)
    except KeyboardInterrupt:
        return


def run_server(server):
    logging.info('Listening on %r', server.server_address)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    wait_until_ctrl_c()
    logging.info('Ready to shut down')
    server.shutdown()
