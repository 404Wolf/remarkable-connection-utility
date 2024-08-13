'''
BatteryInfoController.py
This dialog is responsible for showing battery statistics.

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

import log

from controllers import UIController
from pathlib import Path

class BatteryInfoController(UIController):
    name = 'Battery Information'
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'battinfo.ui')
    is_essential = False
    
    def __init__(self, pane):
        super(type(self), self).__init__(
            pane.model, pane.threadpool)
        self.pane = pane
        # Load the battery type into group label
        self.loaded_type = False

    def update_view(self):
        # Loads info strings into labels and progress meters
        title = 'Battery'
        batt_type = self.model.battery.get_type()
        if batt_type:
            title += ' ({})'.format(batt_type)
        self.window.groupBox.setTitle(title)
        self.window.status_label.setText(
            self.model.battery.get_status())
        self.window.temperature_label.setText(
            self.model.battery.get_temperature())
        self.window.currentcharge_label.setText(
            self.model.battery.get_current_charge())
        self.window.fullcharge_label.setText(
            self.model.battery.get_full_charge())
        self.window.designcapacity_label.setText(
            self.model.battery.get_designed_full_charge())

        self.window.charge_progressBar.setValue(
            self.model.battery.get_current_capacity())
        self.window.health_progressBar.setValue(
            self.model.battery.get_current_health())

    def start_window(self):
        self.update_view()
        # Center battery info window over main window
        pw = self.pane.pane_controller.window
        new_pos = pw.frameGeometry().topLeft() \
            + pw.rect().center() - self.window.rect().center()

        self.window.move(new_pos)
        self.window.show()
