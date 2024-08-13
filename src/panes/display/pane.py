'''
pane.py
This is the Display pane.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-24  Davis Remmel

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

from PySide2.QtCore import Qt, QSize, QObject, QEvent, QSettings, \
    QCoreApplication
from PySide2.QtGui import QImage, QPixmap, QColor, QIcon
from PySide2.QtWidgets import QFileDialog, QWidget, QApplication, \
    QShortcut
from pathlib import Path
from datetime import datetime
from controllers import UIController
from worker import Worker
import log
import gc
import ctypes


def load_label_pixmap(container_widget, label):
    # label should have attrs: pixmap_copy, pixmap_size
    if not hasattr(label, 'pixmap_copy') \
       or not hasattr(label, 'pixmap_size'):
        return False
    width = container_widget.width()
    height = container_widget.height()
    orig_ratio = width / height
    dest_ratio = label.pixmap_size[0] / label.pixmap_size[1]
    if dest_ratio > orig_ratio:
        # fit label to width
        new_width = width
        new_height = width / dest_ratio
    else:
        # fit label to height
        new_width = height * dest_ratio
        new_height = height
    label.setFixedWidth(new_width)
    label.setFixedHeight(new_height)
    label.setPixmap(label.pixmap_copy)
    return True

class ResizeEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            return load_label_pixmap(obj, self.window.testlabel)
        else:
            # standard event processing
            return QObject.eventFilter(self, obj, event)
    

class DisplayPane(UIController):
    identity = 'me.davisr.rcu.display'
    name = 'Display'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'display.ui')

    compat_hw = ['^RM100$', '^RM102$', '^RM110$']

    cli_args = [('--screenshot-0', 1, ('out.png'), 'take a screenshot (portrait)'),
                ('--screenshot-90', 1, ('out.png'), 'take a screenshot (landscape)'),
                ('--screenshot-180', 1, ('out.png'), 'take a screenshot (upside down)'),
                ('--screenshot-270', 1, ('out.png'), 'take a screenshot (type folio)')]

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'video-display.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def set_radio_buttons_from_orientation(self):
        if 90 == self.orientation:
            self.window.landscape_radioButton.setChecked(True)
        elif 180 == self.orientation:
            self.window.upsidedown_radioButton.setChecked(True)
        elif 270 == self.orientation:
            self.window.typefolio_radioButton.setChecked(True)
        else:
            self.window.portrait_radioButton.setChecked(True)

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.pane_controller = pane_controller
        self.orientation = 0
    
        if not QCoreApplication.args.cli:
            # Load initial orientation
            angle = QSettings().value(
                'pane/display/orientation') or 0
            self.orientation = int(angle)
            self.set_radio_buttons_from_orientation()
            self.soft_load_screen_async()

            # Replace placeholder label with our own
            efilt = ResizeEventFilter(self.window)
            efilt.window = self.window
            self.window.screen_widget.installEventFilter(efilt)
        
            # Button handlers
            self.window.screenshot_pushButton.clicked.connect(
                self.save_image)
            self.window.clipboard_pushButton.clicked.connect(
                self.copy_image_to_clipboard)
            self.window.refresh_pushButton.clicked.connect(
                self.hard_load_screen_async)
            self.window.portrait_radioButton.clicked.connect(
                lambda: self.change_orientation(angle=0))
            self.window.landscape_radioButton.clicked.connect(
                lambda: self.change_orientation(angle=90))
            self.window.upsidedown_radioButton.clicked.connect(
                lambda: self.change_orientation(angle=180))
            self.window.typefolio_radioButton.clicked.connect(
                lambda: self.change_orientation(angle=270))

            # Keyboard shortcuts
            save = QShortcut('Ctrl+S', self.window)
            save.activated.connect(self.save_image)
            copy = QShortcut('Ctrl+C', self.window)
            copy.activated.connect(self.copy_image_to_clipboard)
            refresh = QShortcut('Ctrl+R', self.window)
            refresh.activated.connect(self.hard_load_screen_async)
            refresh2 = QShortcut('F5', self.window)
            refresh2.activated.connect(self.hard_load_screen_async)

    def update_view(self):
        self.hard_load_screen_async()

    def change_orientation(self, angle):
        if angle != self.orientation:
            # Orientation changed
            log.info('changing display orientation to', angle)
            self.orientation = angle
            # Remember orientation
            QSettings().setValue(
                'pane/display/orientation',
                int(self.orientation))
            self.soft_load_screen_async()

    def hard_load_screen_async(self, prog_cb=lambda x: ()):
        self.model.display.invalidate_pixel_cache()
        self.soft_load_screen_async(prog_cb=prog_cb)

    def soft_load_screen_async(self, prog_cb=lambda x: ()):
        # Used to kick off thread
        self.disable_buttons()
        worker = Worker(fn=self.load_screen)
        self.threadpool.start(worker)
        worker.signals.finished.connect(self.enable_buttons)
        worker.signals.progress.connect(
            lambda x: self.window.progressBar.setValue(x))

    def disable_buttons(self):
        self.window.screenshot_pushButton.setEnabled(False)
        self.window.clipboard_pushButton.setEnabled(False)
        self.window.refresh_pushButton.setEnabled(False)
        self.window.portrait_radioButton.setEnabled(False)
        self.window.landscape_radioButton.setEnabled(False)
        self.window.typefolio_radioButton.setEnabled(False)
        self.window.upsidedown_radioButton.setEnabled(False)
        self.window.progress_label.show()
        self.window.progressBar.show()
        self.window.progressBar.setValue(0)

    def enable_buttons(self):
        self.window.screenshot_pushButton.setEnabled(True)
        self.window.clipboard_pushButton.setEnabled(True)
        self.window.refresh_pushButton.setEnabled(True)
        self.window.portrait_radioButton.setEnabled(True)
        self.window.landscape_radioButton.setEnabled(True)
        self.window.typefolio_radioButton.setEnabled(True)
        self.window.upsidedown_radioButton.setEnabled(True)
        self.window.progress_label.hide()
        self.window.progressBar.hide()

    def copy_image_to_clipboard(self):
        # Copies screenshot to system clipboard
        if not hasattr(self.window.testlabel, 'pixmap_copy'):
            log.info('Cannot save screenshot when one does not exist')
            return
        QApplication.clipboard().setPixmap(self.window.testlabel.pixmap_copy)
        log.info('copied screenshot to clipboard')

    def save_image(self, outfile=None):
        # Saves screenshot to disk

        if not hasattr(self.window.testlabel, 'pixmap_copy'):
            log.info('Cannot save screenshot when one does not exist')
            return

        # Get the default directory to save under
        if not outfile:
            default_savepath = QSettings().value(
                'pane/display/last_export_path')
            if not default_savepath:
                QSettings().setValue(
                    'pane/display/last_export_path',
                    Path.home())
                default_savepath = Path.home()
            pfile = datetime.now().strftime('rM Screen %Y-%m-%d %H_%M_%S.png')
            filename = QFileDialog.getSaveFileName(
                self.window,
                'Save Screenshot',
                Path(default_savepath / pfile).__str__(),
                'Images (*.png *.PNG)')
            if not filename[0] or filename[0] == '':
                return False
            outfile = Path(filename[0])
        else:
            outfile = Path(outfile[0])

        # # If landscape, rotate it. (only used for cli, todo: use in gui)
        # if landscape:
        #     self.window.testlabel.pixmap_copy
        self.window.testlabel.pixmap_copy.save(str(outfile), 'PNG')
        log.info('saved screenshot')
        # # Save the last path directory for convenience
        # QSettings().setValue(
        #     'pane/display/last_export_path',
        #     outfile.parent)

    def load_screen(self, progress_callback=None):
        # Captures the screen from the device and loads it into a
        # QPixmap.
        
        pngdata, size = self.model.display.get_png_data(
            rotation=self.orientation)

        # if progress_callback:
        #     progress_callback.emit(50)

        label = self.window.testlabel
        pxmap = QPixmap()
        pxmap.loadFromData(pngdata, 'PNG')

        label.pixmap_copy = pxmap.copy()
        label.pixmap_size = size

        ctypes.c_long.from_address(id(pxmap)).value=1
        del pxmap
        gc.collect()

        load_label_pixmap(
            self.window.screen_widget, label)

        # if progress_callback:
        #     progress_callback.emit(100)

    def evaluate_cli(self, args):
        outfile = None
        if args.screenshot_0:
            self.orientation = 0
            outfile = args.screenshot_0
        elif args.screenshot_90:
            self.orientation = 90
            outfile = args.screenshot_90
        elif args.screenshot_180:
            self.orientation = 180
            outfile = args.screenshot_180
        elif args.screenshot_270:
            self.orientation = 270
            outfile = args.screenshot_270
        if outfile:
            self.load_screen()
            if self.save_image(outfile=outfile):
                return 0
        return 1
