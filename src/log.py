'''
log.py
Handles common logging functions

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

import sys

activated = True

def get_string(args):
    na = []
    for n, a in enumerate(args):
        na.append(str(a))
    if len(na) == 1:
        string = str(''.join(na)) + '\n'
    else:
        string = str(' '.join(na)) + '\n'
    return string

def info(*args):
    if activated:
        sys.stdout.write(get_string(args))
    
def error(*args):
    sys.stderr.write(get_string(args))

def cli(*args):
    sys.stdout.write(get_string(args))

def debug(*args):
    sys.stdout.write('===(debug)===> ' + get_string(args))
