#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ghostscript - A Python interface for the Ghostscript interpreter C-API
"""
#
# This file is part of python-ghostscript.
# Copyright 2010-2021 by Hartmut Goebel <h.goebel@crazy-compilers.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

__author__ = "Hartmut Goebel <h.goebel@crazy-compilers.com>"
__copyright__ = "Copyright 2010-2021 by Hartmut Goebel <h.goebel@crazy-compilers.com>"
__licence__ = "GNU General Public License version 3 (GPL v3)"

__all__ = ['Ghostscript', 'revision',
           'GhostscriptError', 'PleaseDisplayUsage']

import sys # :todo: remove, debugging only
from . import _gsprint as gs
__version__ = gs.__version__

GhostscriptError = gs.GhostscriptError

class PleaseDisplayUsage(Warning):
    """
    This exception is raised when Ghostscript asks the application to
    display the usage. The application should catch the exception an
    print the usage message.
    """
    pass


def revision():
    """
    This function returns the revision numbers and strings of the
    Ghostscript interpreter library as a dict. You should call it
    before any other interpreter library functions to make sure that
    the correct version of the Ghostscript interpreter has been
    loaded.
    """
    rev = gs.revision()
    # we assume that the underlying function returns utf-8 strings
    return {
        "product": rev.product.decode('utf-8'),
        "copyright": rev.copyright.decode('utf-8'),
        "revision": rev.revision,
        "revisiondate": rev.revisiondate
    }


MAX_STRING_LENGTH = gs.MAX_STRING_LENGTH


class Ghostscript(object):
    @staticmethod
    def revision():
        return revision()
    
    def __init__(self, *args, stdin=None, stdout=None, stderr=None):
        assert self.revision()['revision'] >= 908, \
            "high-level interface requires ghostscript >= 9.08"
        self._callbacks = None
        self._instance = gs.new_instance()
        if not isinstance(args[0], str):
            import warnings
            warnings.warn(
                "Passing bytes-arguments to 'Ghostscript()' is deprecated",
                DeprecationWarning, stacklevel=2)
        else:
            gs.set_arg_encoding(self._instance, gs.ARG_ENCODING_UTF8)
            args = [a.encode('utf-8') for a in args]
        try:
            self.set_stdio(stdin, stdout, stderr)
            rc = gs.init_with_args(self._instance, args)
            if rc == gs.e_Info:
                raise PleaseDisplayUsage()
            if rc == gs.e_Quit:
                self.exit()
        except:
            self.exit()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.exit()

    def set_stdio(self, stdin=None, stdout=None, stderr=None):
        """Set stdin, stdout and stderr of the ghostscript interpreter.

        The ``stdin`` stream has to support the ``readline()``
        interface. The ``stdout`` and ``stderr`` streams have to
        support the ``write()`` and ``flush()`` interface.

        Please note that this does not affect the input- and output-
        streams of the devices. Esp. setting stdout does not allow
        catching the devise-output even when using ``-sOutputFile=-``.

        """
        if not stdin and not stdout and not stderr:
            return

        self._callbacks = (
            stdin and gs._wrap_stdin(stdin) or None,
            stdout and gs._wrap_stdout(stdout) or None,
            stderr and gs._wrap_stderr(stderr) or None,
            )
        gs.set_stdio(self._instance, *self._callbacks)
        
    def __del__(self):
        self.exit()
        
    def exit(self):
        if self._instance:
            try:
                gs.exit(self._instance)
                gs.delete_instance(self._instance)
            finally:
                self._instance = None
    
    def run_string(self, str, user_errors=False):
        """
        Run the string ``str`` by Ghostscript

        This takes care of Ghostscripts size-limitations and passes
        the string in pieces if necessary.
        """
        instance = self._instance
        if len(str) < MAX_STRING_LENGTH:
            gs.run_string(instance, str)
        else:
            gs.run_string_begin(instance)
            for start in range(0, len(str), MAX_STRING_LENGTH):
                gs.run_string_continue(instance,
                                       str[start:start+MAX_STRING_LENGTH])
            gs.run_string_end(instance)
        

    def run_filename(self, filename, user_errors=False):
        """
        Run the file named by ``filename`` by Ghostscript
        """
        return gs.run_file(self._instance, filename, user_errors)


    def run_file(self, file, user_errors=False):
        """
        Read ``file`` and run the content by Ghostscript.

        ``file`` must already by opened and may by any file-like
        object supporting the ``read()`` method.
        """
        instance = self._instance
        gs.run_string_begin(instance)
        while True:
            str = file.read(MAX_STRING_LENGTH)
            if not str:
                break
            gs.run_string_continue(instance, str)
        gs.run_string_end(instance)


def cleanup():
    pass
