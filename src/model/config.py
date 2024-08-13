'''
config.py
The configuration manager is responsible for storing connection settings
and maintaining a connection to the device.

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

import paramiko
import log
from pathlib import Path
import json
from .transport import Transport

class Config:
    def __init__(self):
        self.connection = None
        self.host = None
        self.user = None
        self.password = None
        self.cx_error = None
        
    def connect(self):
        # Starts a connection to the device
        if not self.is_connected():
            client = paramiko.SSHClient()
            # paramiko.common.logging.basicConfig(level=paramiko.common.DEBUG)
            # if the user does not have the host key should we give them
            # a warning?
            client.set_missing_host_key_policy(
                paramiko.client.AutoAddPolicy)
            try:
                split = self.host.split(':')
                if len(split) > 1:
                    host = split[0]
                    port = split[1]
                else:
                    host = self.host
                    port = 22

                # Assemble opts
                sshopts = {'port': port,
                           'username': self.user,
                           'password': None,
                           'look_for_keys': True,
                           'allow_agent': True,
                           'timeout': 1}

                # If a password was supplied, force usage of that
                # instead of looking for keys or using SSH agent.
                if self.password and len(self.password):
                    sshopts['look_for_keys'] = False
                    sshopts['allow_agent'] = False
                    sshopts['password'] = self.password
                    log.info('using password auth')
                else:
                    # sshopts['look_for_keys'] = False
                    # sshopts['allow_agent'] = True
                    log.info('using key auth')

                client.connect(host, **sshopts)
                client.get_transport().set_keepalive(10)
                self.connection = client
                self.cx_error = None
                return True
            except Exception as e:
                log.error(e)
                self.cx_error = type(e).__name__
                return False
            
    def connect_restore(self):
        # Starts a restoration connection to the device, which always
        # uses these static settings.
        if not self.is_connected():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(
                paramiko.client.AutoAddPolicy)
            try:
                # paramiko client doesn't support password-less auth, so
                # have to form our own transport and inject it into a
                # client.
                # Use a custom transport that lowers the connection
                # timeout.
                t = Transport(('10.11.99.1', 22))
                t.set_keepalive(10)
                t.connect()
                t.auth_none('root')
                client._transport = t
                self.connection = client
                return True
            except Exception as e:
                log.error(e)
                self.cx_error = type(e).__name__
                return False
            
    def disconnect(self, force=False):
        # Destroys a connection to the device
        if self.connection or force:
            try:
                self.connection.close()
            except:
                pass
            self.connection = False
            
    def is_connected(self):
        if self.connection and \
           self.connection.get_transport().is_authenticated():
            return True
        return False
