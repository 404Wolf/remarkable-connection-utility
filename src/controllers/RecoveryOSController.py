'''
RecoveryOSController.py
This can control a UI, and control the model, for when the tablet
should download the recovery OS and enter recovery mode.

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

from . import UIController
from pathlib import Path
import log
from PySide2.QtCore import QTimer

class RecoveryOSController(UIController):
    adir = Path(__file__).parent.parent
    ui_filename = Path(adir / 'views' / 'RecoveryOS.ui')
    
    def __init__(self, model, skip_windows=False):
        super(type(self), self).__init__(model)
        self.skip_windows = skip_windows
        #self.window.show()

    def stage_1(self, cb, load_info):
        self.window.label_press.show()
        self.window.label_release.hide()
        QTimer.singleShot(5000, lambda: self.stage_2(cb, load_info))

    def stage_2(self, cb, load_info):
        self.model.restart_hw()
        QTimer.singleShot(5000, lambda: self.stage_3(cb, load_info))

    def stage_3(self, cb, load_info):
        self.window.label_press.hide()
        self.window.label_release.show()
        QTimer.singleShot(5000, lambda: self.end_stages(cb, load_info))

    def end_stages(self, cb, load_info):
        self.window.hide()
        self.model.upload_recovery_os(cb, load_info)

    def enter_recovery_mode(self, endcb, load_info=True):
        log.info('enter_recovery_mode')
        if not self.model.connect_restore(load_info=load_info):
            if not self.skip_windows:
                self.window.show()
                self.stage_1(endcb, load_info)
            else:
                self.model.upload_recovery_os(endcb, load_info=load_info)
        else:
            endcb(True)

    def leave_stage_1(self, cb):
        def retry(i):
            if i > 0:
                i -= 1
                log.info('reconnecting...{} retries left'.format(i))
                if self.model.reconnect() \
                   and not self.model.is_in_recovery:
                    log.info('out of recovery mode')
                    cb(not self.model.is_in_recovery)
                    return
                QTimer.singleShot(5000, lambda: retry(i))
            else:
                cb(not self.model.is_in_recovery)
        retry(12)

    def leave_recovery_mode(self, endcb):
        if self.model.is_in_recovery:
            self.model.restart_hw()
            QTimer.singleShot(30000, lambda: self.leave_stage_1(endcb))
        else:
            endcb(self.model.is_in_recovery)

            
        
