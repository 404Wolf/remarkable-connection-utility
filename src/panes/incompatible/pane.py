'''
pane.py
This is a pane that acts as a placeholder when another pane is
recognized as being incompatible with Xochitl.

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

from pathlib import Path
from controllers import UIController
import log
from PySide2.QtGui import QPixmap

class IncompatiblePane(UIController):
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'PaneCompatibilityError.ui')

    def __init__(self, pane_controller, truepanecls):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)
        self.pane_controller = pane_controller
        self.truepanecls = truepanecls
        self.has_continued_loading = False

        # Load big stop sign
        iconfile = str(Path(type(self).bdir / 'icons' / 'process-stop.png'))
        stopsign = QPixmap()
        stopsign.load(iconfile)
        self.window.stop_label.setPixmap(stopsign)

        # The truepane is the one we ought to load, replacing this one.

        self.window.load_pushButton.clicked.connect(
            self.continue_loading)

    def continue_loading(self):
        # Disable the button right away to avoid loading twice
        self.window.load_pushButton.setEnabled(False)
        
        # Insert the new pane into this one's layout view
        self.newpane = self.truepanecls(self.pane_controller)

        self.window.incomp_widget.setEnabled(False)
        self.window.incomp_widget.hide()

        self.window.pane_layout.addWidget(self.newpane.window)
        self.newpane.window.show()
        self.has_continued_loading = True
