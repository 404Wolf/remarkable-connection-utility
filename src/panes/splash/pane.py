'''
pane.py
This is the Splash Screen pane.

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

from PySide2.QtCore import QSize, Qt, QObject, QEvent, QSettings
from PySide2.QtGui import QPixmap, QImage, QIcon
from PySide2.QtWidgets import QFileDialog, QMessageBox
from pathlib import Path
from datetime import datetime
import log
from controllers import UIController


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
            return load_label_pixmap(obj, self.window.img_label)
        else:
            # standard event processing
            return QObject.eventFilter(self, obj, event)


class SplashPane(UIController):
    identity = 'me.davisr.rcu.splash'
    name = 'Wallpaper'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'splash.ui')

    # Todo: implement xochitl version support to handle all filepaths
    default_images = {
        'suspend': {'filename': 'suspended.png', 'label': 'Suspended'},
        'poweroff': {'filename': 'poweroff.png', 'label': 'Powered Off'},
        'starting': {'filename': 'starting.png', 'label': 'Starting'},
        'rebooting': {'filename': 'rebooting.png', 'label': 'Rebooting'},
        'overheating': {'filename': 'overheating.png', 'label': 'Overheating'},
        'batteryempty': {'filename': 'batteryempty.png', 'label': 'Battery Empty'},
    }

    xochitl_versions = [
        '^[1-2]\.[0-9]+\.[0-9]+\.[0-9]+$',
        '^3\.[0-4]\.[0-9]+\.[0-9]+$',
        '^3\.[0-9]\.[0-9]\.[0-9]+$',
        '^3\.1[0-1]\.[0-9]\.[0-9]+$'
    ]

    device_local_path = '$HOME/.local/share/davisr/rcu/splash'
    device_sys_path = '/usr/share/remarkable'

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'preferences-desktop-wallpaper.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon
    
    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)
        self.pane_controller = pane_controller

        self.device_image_data = None

        # Button handlers
        self.window.upload_pushButton.clicked.connect(
            self.upload_splash)
        self.window.reset_pushButton.clicked.connect(
            self.reset_splash)
        self.window.download_pushButton.clicked.connect(
            self.download_splash)

        # Replace placeholder label with our own
        efilt = ResizeEventFilter(self.window)
        efilt.window = self.window
        self.window.splash_widget.installEventFilter(efilt)

        self.window.comboBox.currentIndexChanged.connect(
            self.change_image)

        # Proxy command for basic set-up
        self.handle_cx_restore()

    def handle_cx_restore(self):
        self._migrate_to_local()
        self.check_broken_splashes()
        self.update_view()
        self.set_all_enabled()

    def change_image(self):
        data = self.window.comboBox.itemData(
            self.window.comboBox.currentIndex())
        if data:
            self.set_label_pixmap(data['filename'])

    def update_view(self):
        if 0 >= self.window.comboBox.count():
            # Populate the combobox with options
            for key in self.default_images:
                item = self.default_images[key]
                self.window.comboBox.addItem(item['label'])
                self.window.comboBox.setItemData(
                    self.window.comboBox.count() - 1,
                    item)
        # todo: set_label_pixmap('key') on all of them
        # vvv this one is going to get removed
            self.set_label_pixmap('suspended.png')

    def set_all_disabled(self):
        self.window.comboBox.setEnabled(False)
        self.window.upload_pushButton.setEnabled(False)
        self.window.reset_pushButton.setEnabled(False)
        self.window.download_pushButton.setEnabled(False)

    def set_all_enabled(self):
        self.window.comboBox.setEnabled(True)
        self.window.upload_pushButton.setEnabled(True)
        self.window.reset_pushButton.setEnabled(True)
        self.window.download_pushButton.setEnabled(True)

    def _migrate_to_local(self):
        # RCU used to upload directly to /usr/share/remarkable. This
        # couldn't persist between software updates, and so a similar
        # technique to RCU's user-templates is used.
        local_path = type(self).device_local_path

        # Create the directory if it doesn't exist
        cmd = 'mkdir -p "' + local_path + '"'
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error(err)
            return

        # Move any existing splash backups to the .local directory.
        ver = self.model.device_info['osver']
        cmd = 'cd ' + self.device_sys_path + ' && ' \
            + '(for f in *.png.bak; do ' \
            + '(yes n | cp -i \"\$f\" \"' \
              + local_path + '/\${f%.bak}.system_' + ver + '\") && ' \
            + '(yes n | cp -i \"\${f%.bak}\" \"' + local_path +'/\${f%.bak}.user\"); ' \
            + 'done)'
        out, err = self.model.run_cmd('bash -c "' + cmd + '"')
        if len(err):
            # Commented out, since cp -i prints to stderr and isn't
            # useful.
            # log.error('error migrating old splash backups')
            # log.error(err)
            # return
            pass

    def check_broken_splashes(self):
        # Detect if there are user splash images that are not copied
        # to the sys directory. Prompt the user to restore if necessary.
        cmd = 'cd ' + type(self).device_local_path + ' && for f in *.user; ' \
            + 'do fname="$(basename "$f")"; fname="${fname%.user}"; ' \
            + 'if cmp -s "$fname.user" "/usr/share/remarkable/$fname"; ' \
            + 'then :; else echo "$fname"; fi; done'
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('error getting broken splashes')
            log.error(err)
            return
        filenames = out.strip().split('\n')
        if not len(filenames):
            return
        if '*' == filenames[0] or '' == filenames[0]:
            return
        log.info('detected broken splash images')

        mb = QMessageBox(self.pane_controller.window)
        mb.setWindowTitle('Broken Wallpaper Detected')
        mb.setText('Broken wallpaper (splash images) were detected. This may have occurred after a recent OS software update. Repair them?')
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.Yes)
        ret = mb.exec()
        if ret == int(QMessageBox.Yes):
            self._fix_broken_splashes(filenames)

    def _fix_broken_splashes(self, filenames):
        ver = self.model.device_info['osver']
        all_cmds = []
        for fn in filenames:
            # if a system file doesn't exist, create it
            cmd = '(yes n | cp -i "{}" "{}")'.format(
                type(self).device_sys_path + '/' + fn,
                type(self).device_local_path + '/' + fn + '.system_' + ver)
            all_cmds.append(cmd)
            # copy the .user file into the system directory
            cmd = '(cp "{}" "{}")'.format(
                type(self).device_local_path + '/' + fn + '.user',
                type(self).device_sys_path + '/' + fn)
            all_cmds.append(cmd)
        # Run all cmds
        cmd = '; '.join(all_cmds)
        self.model.run_cmd(cmd)
        for fn in filenames:
            self.set_label_pixmap(fn)
        self.model.restart_xochitl()

    def read_device_image(self, filename):
        # Reads the image from the device and returns a QPixMap. Returns
        # nothing if the image can't be read.
        fpath = type(self).device_sys_path \
            + '/' + filename
        out, err = self.model.run_cmd('cat "{}"'.format(fpath),
                                      raw=True)
        if len(err):
            log.error('problem reading png from device; ' + filename)
            log.error(err.decode('utf-8'))
            return
        pixmap = QPixmap()
        pixmap.loadFromData(out)
        self.device_image_data = out
        return pixmap

    def set_label_pixmap(self, filename):
        pxmap = self.read_device_image(filename) or QPixmap()
        label = self.window.img_label
        label.pixmap_copy = pxmap.copy()
        # this is cheating: it should use the actual image size. TODO
        label.pixmap_size = type(self.model.display).portrait_size
        load_label_pixmap(self.window.splash_widget, label)

        import ctypes, gc
        ctypes.c_long.from_address(id(pxmap)).value=1
        del pxmap
        gc.collect()

    def upload_splash(self):
        # Sets a new splash image. 'Name' referrs to the list in
        # default_filepaths. This will open a file dialog to grab the
        # new image.

        filename = self.window.comboBox.currentData()['filename']

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/splash/last_import_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/splash/last_import_path',
                Path.home())
            default_savepath = Path.home()
        
        localfile = QFileDialog.getOpenFileName(
            self.window,
            'Upload Image',
            str(default_savepath),
            'Images (*.png *.PNG)')
        if not localfile[0] or localfile[0] == '':
            return
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/splash/last_import_path',
            Path(localfile[0]).parent)
        try:
            # If a backup of the factory image doesn't exist, create it.
            sys_path = type(self).device_sys_path + '/' + filename
            ver = self.model.device_info['osver']
            local_path = type(self).device_local_path + '/' + filename \
                + '.system_' + ver

            cmd = 'yes n | cp -i "{}" "{}"'.format(
                sys_path,
                local_path)
            self.model.run_cmd(cmd)

            # Todo: check to see if the png matches the resolution /
            # color profile / filesize.
            # ...

            # Write the user image to local path.
            local_path = type(self).device_local_path + '/' + filename \
                + '.user'

            # Get real local path for SFTP put (can't handle variable
            # expansion).
            cmd = 'realpath "{}"'.format(local_path)
            out, err = self.model.run_cmd(cmd)
            real_local_path = out.strip()
            self.model.put_file(localfile[0], real_local_path)

            # Copy the new user image to sys directory.
            cmd = 'cp "{}" "{}"'.format(
                local_path,
                sys_path)
            # How to handle error here? TODO
            self.model.run_cmd(cmd)

            # Finish up
            self.set_label_pixmap(filename)
            self.model.restart_xochitl()
            log.info('set new splash for', filename)
        except Exception as e:
            log.error('unable to set splash; ' + e.__str__())
            return False
    
    def reset_splash(self):
        # Resets the splash image to factory-default (if it was backed
        # up with RCU).
        filename = self.window.comboBox.currentData()['filename']
        log.info('resetting splash for ' + filename)

        device_sys_file = type(self).device_sys_path + '/' + filename

        ver = self.model.device_info['osver']
        device_local_file = type(self).device_local_path \
            + '/' + filename + '.system_' + ver

        self.make_free_space()

        # If the local file exists, copy it to the sys directory and
        # purge backups.
        user_local_path = type(self).device_local_path + '/' + filename \
            + '.user'
        cmd = 'cp "{}" "{}" && rm -f "{}" "{}"'.format(
            device_local_file,
            device_sys_file,
            device_local_file,
            user_local_path)
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error(err)
            return

        # Finish up
        self.set_label_pixmap(filename)
        self.model.restart_xochitl()

    def download_splash(self):
        filename = self.window.comboBox.currentData()['filename']
        default_savepath = QSettings().value(
            'pane/wallpaper/last_download_path') or Path.home()
        d = QFileDialog()
        fname = d.getSaveFileName(
            self.window,
            'Download Image',
            Path(default_savepath / filename).__str__(),
            'Images (*.png *.PNG)')
        if not fname[0] or fname[0] == '':
            return
        filepath = Path(fname[0])
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/wallpaper/last_download_path',
            filepath.parent)
        print('saving to ', filepath)
        png_data = self.device_image_data
        with open(filepath, 'wb') as f:
            f.write(self.device_image_data)
            f.close()

    def make_free_space(self):
        out, err = self.model.run_cmd(
            'journalctl --vacuum-size=10M')
