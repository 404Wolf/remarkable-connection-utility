'''
UIController.py
This is a super class for all UI controllers.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-21  Davis Remmel

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

import pathlib
import sys
from PySide2.QtCore import QFile, QCoreApplication
from PySide2.QtUiTools import QUiLoader
import log
import re

class UIController:
    identity = ''
    name = ''
    ui_filename = ''
    # pyinstaller moves all datafiles into a tmp dir. This basepath
    # can be overridden by a subclass, like third-party panes.
    ui_basepath = '.'
    if hasattr(sys, '_MEIPASS'):
        ui_basepath = sys._MEIPASS

    # Override in the pane class
    compat_hw = ['^RM[0-9]+$']
    xochitl_versions = [
        '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$',
        '^Parabola.*']

    # Set to True to keep enabled for backups
    is_essential = False

    # Each element of this set should be a len:2 tuple,
    # [('--flag', 1), ...] ## name, arg_length
    cli_args = []

    # Override this in the pane to specify the icon file
    @classmethod
    def get_icon(cls):
        pass

    @classmethod
    def is_compatible(cls, model):
        # Check the self against this xochitl's version and reMarkble
        # hardware version

        # Check hardware compatibilty
        hw_compat = False
        for p in cls.compat_hw:
            pat = re.compile(p)
            # Hardware should always be available, even in recovery
            # mode, because this comes from the protected boot1
            # partition.
            hwver = model.device_info['model'] or 'RM000'
            if pat.match(hwver):
                hw_compat = True
                break

        if not hw_compat:
            return False

        # Check software compatibility
        sw_compat = False
        local_compat = QCoreApplication.sharePath / 'compat.txt'
        if local_compat.exists():
            with open(local_compat, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
                for line in lines:
                    sline = line.split('\t')
                    # do a quick sanity check
                    if 3 != len(sline):
                        log.error('invalid line in compat file: {}'.format(line))
                        continue
                    compat_rcuver = sline[0]
                    compat_pane_identity = sline[1]
                    compat_re = sline[2]
                    if compat_rcuver == \
                       QCoreApplication.version_sortcode \
                       and compat_pane_identity == cls.identity:
                        log.info('adding compat: {} {}'.format(compat_pane_identity, compat_re))
                        cls.xochitl_versions.append(compat_re)
        for p in cls.xochitl_versions:
            pat = re.compile(p)
            # If in recoverymode, the osver might be None. Essential
            # panes should not override the compatibility array.
            osver = model.device_info['osver'] or '0.0.0.0'
            if pat.match(osver):
                sw_compat = True
                break

        if not sw_compat:
            return False

        return True
    
    def __init__(self, model, threadpool=None):
        self.model = model
        self.threadpool = threadpool

        ui_file_name = pathlib.Path(
            type(self).ui_basepath, type(self).ui_filename).__str__()
        ui_file = QFile(ui_file_name)
        if not ui_file.open(QFile.ReadOnly):
            log.error("Cannot open {}: {}".format(
                ui_file_name, ui_file.errorString()))
            return
        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()
        if not self.window:
            log.error('Problem with window ' + loader.errorString())
            return

    def update_view(self):
        # Override this function in the inherited class. It should
        # update the visual elements with new data from the model.
        pass

    def evaluate_cli(self, args):
        # Evaluate cli arguments (no GUI window shown)
        log.info('not implemented')
