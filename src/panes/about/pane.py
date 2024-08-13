'''
pane.py
This is the About pane.

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

import log
from pathlib import Path
from controllers import UIController
import sys

from worker import Worker

from PySide2.QtCore import Qt, QByteArray, QUrl, QSize, \
    QCoreApplication, QSettings
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QMessageBox
import urllib.request
import hashlib

import certifi # PyInstaller pickup (should be auto-used by urllib)

class AboutPane(UIController):
    identity = 'me.davisr.rcu.about'
    name = 'About RCU'
    
    uiname = 'about.ui'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / uiname)

    is_essential = True

    update_url = 'https://files.davisr.me/projects/rcu/latest-version.txt'
    compat_url = 'https://files.davisr.me/projects/rcu/latest-compat.txt'
    rcu_announce_url = 'https://lists.davisr.me/mailman/private/rcu-announce/'

    onstart_settings_key = 'pane/about/checkfetch_onstart'

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'help-about.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon
    
    def __init__(self, pane_controller, checkfetch=True):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.pane_controller = pane_controller
        self.checkfetch = checkfetch
        self.did_checkfetch = False

        self.version = QCoreApplication.applicationVersion().strip()
        self.version_sc = QCoreApplication.version_sortcode
        
        self.remote_version_body = None
        self.remote_compat_body = None

        # Set button icon
        ipathstr = str(Path(type(self).bdir / 'icons' / 'rcu-icon.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(32, 32), QIcon.Normal, QIcon.On)
        self.window.icon_label.setPixmap(icon.pixmap(32, 32))

        # Replace version
        ttext = self.window.label.text()
        self.window.label.setText(ttext.replace(
            '{{version}}', self.version))

        # Replace Python license
        vi = sys.version_info
        pylicense = 'COPYING_PYTHON_{}_{}_{}'.format(vi.major,
                                                     vi.minor,
                                                     vi.micro)
        licensedir = Path(type(self).adir.parent / 'licenses')
        licensepath = licensedir / pylicense
        ltextb = self.window.python_textBrowser
        if not licensepath.exists():
            # Keep as info line so self-compiled RCU won't trigger on
            # all CLI operations.
            log.info('Python license file not found: {}'.format(
                pylicense))
            missing_license_link = \
                'https://docs.python.org/{}.{}/license.html'.format(
                    vi.major, vi.minor)
            missing_license_text = '<p>Python license file not found.</p><p>Please visit <a href="{}">{}</a> to see the terms of this distribution.</p>'.format(missing_license_link, missing_license_link)
            ltextb.setHtml(missing_license_text)
        else:
            with open(licensepath, 'r', encoding='utf-8') as f:
                ltextb.setPlainText(f.read())
                f.close()

        # Button registration
        self.window.checkupdates_pushButton.clicked.connect(
            self.check_for_updates_async)
        self.window.checkcompat_pushButton.clicked.connect(
            self.check_for_compat_async)

        # Load and handle auto check/fetch checkbox
        onstart_state = bool(int(QSettings().value(self.onstart_settings_key) or 0))
        self.window.onstart_checkBox.setChecked(onstart_state)
        self.window.onstart_checkBox.clicked.connect(
            self.toggle_auto_checkfetch)
        if self.checkfetch:
            self.do_auto_checkfetch()

    def do_auto_checkfetch(self):
        if self.window.onstart_checkBox.isChecked() \
           and not self.did_checkfetch:
            log.info('doing auto check/fetch')
            self.check_for_updates_async(
                show_mb=False, callback=lambda:
                self.check_for_compat_async(show_mb=False))
            self.did_checkfetch = True

    def toggle_auto_checkfetch(self):
        onstart_state = self.window.onstart_checkBox.isChecked()
        QSettings().setValue(self.onstart_settings_key, int(onstart_state))

    def check_for_updates_async(self, show_mb=True, callback=lambda:()):
        # Runs the update check in a new thread, not to block the GUI.
        worker = Worker(fn=self.check_for_updates)
        self.threadpool.start(worker)
        worker.signals.finished.connect(
            lambda: self.finished_check_for_updates(
                show_mb=show_mb, callback=callback))

    def check_for_compat_async(self, show_mb=True, callback=lambda:()):
        # Runs the compat check in a new thread, not to block the GUI.
        worker = Worker(fn=self.check_for_compat)
        self.threadpool.start(worker)
        worker.signals.finished.connect(
            lambda: self.finished_check_for_compat(
                show_mb=show_mb, callback=callback))

    def check_for_updates(self, progress_callback=lambda x: ()):
        log.info('checking for updates')
        self.window.checkupdates_pushButton.setEnabled(False)
        with urllib.request.urlopen(type(self).update_url,
                                    cafile=certifi.where()) as response:
            self.remote_version_body = response.read(100)

    def check_for_compat(self, progress_callback=lambda x: ()):
        log.info('checking for compat')
        self.window.checkcompat_pushButton.setEnabled(False)
        with urllib.request.urlopen(type(self).compat_url,
                                    cafile=certifi.where()) as response:
            self.remote_compat_body = response.read(10000)

    def finished_check_for_updates(self, show_mb=True, \
                                   callback=lambda:()):
        # Picks up when async worker is done
        reply = self.remote_version_body
        self.window.checkupdates_pushButton.setEnabled(True)

        if reply is None:
            # Problem contacting update server, probably no net.
            log.error('problem contacting update server')
            if not show_mb:
                return
            mb = QMessageBox(self.pane_controller.window)
            mb.setWindowTitle('Version Check')
            mb.setText('Unable to contact the update server. Please try again later.')
            mb.exec()
            # Don't callback -- break the chain because others will also
            # likely fail.
            return
        
        replystrings = str(reply, 'utf-8').strip().split('\n')
        # Get the version with the matching flag
        foundver = None
        for s in replystrings:
            split = s.split('\t')
            sortcode = split[0]
            prettyver = split[1]
            release_flag = prettyver[0]
            if release_flag == self.version[0]:
                foundver = (sortcode, prettyver)
                break
        if not foundver:
            # Unknown what the latest version is!
            log.error('error checking version: cannot find version flag in list')
            if not show_mb:
                return callback()  # this one can have a callback
            mb = QMessageBox(self.pane_controller.window)
            mb.setWindowTitle('Version Check')
            mb.setText('Unable to contact the update server. Please try again later.')
            mb.exec()
            return
        # assume foundver
        message = 'You have the latest version of RCU.'
        if self.version_sc < foundver[0]:
            message = '<p>A newer version of RCU is available: {}.</p>'.format(
                foundver[1])
            if 'd' == release_flag:
                message += "<p>Development versions may be downloaded from the lower-half of the latest download page.</p><p>Active customers may find the latest download page in the <a href=\"{}\">RCU-Announce mailing list archives</a>, or in your email from <i>rcu-announce@lists.davisr.me</i>.</p>".format(type(self).rcu_announce_url)
            else:
                message += "<p>Release versions may be downloaded from the latest download page.</p><p>Active customers may find the latest download page in the <a href=\"{}\">RCU-Announce mailing list archives</a>, or in your email from <i>rcu-announce@lists.davisr.me</i>.</p>".format(type(self).rcu_announce_url)
        else:
            if not show_mb:
                return callback()
        mb = QMessageBox(self.pane_controller.window)
        mb.setWindowTitle('Version Check')
        mb.setTextFormat(Qt.RichText)
        mb.setText(message)
        mb.exec()
        callback()

    def finished_check_for_compat(self, show_mb=True, \
                                  callback=lambda:()):
        reply = self.remote_compat_body
        self.window.checkcompat_pushButton.setEnabled(True)

        if reply is None:
            # Problem contacting update server, probably no net.
            log.error('problem contacting update server')
            if not show_mb:
                return
            mb = QMessageBox(self.pane_controller.window)
            mb.setWindowTitle('Compatibility Check')
            mb.setText('Unable to contact the update server. Please try again later.')
            mb.exec()
            return
        
        # Get the local compat file checksum to compare to server's
        # response.
        local_compat = QCoreApplication.sharePath / 'compat.txt'
        local_compat_hash = None
        if local_compat.exists():
            with open(local_compat, 'rb') as f:
                local_compat_hash = hashlib.md5(f.read()).hexdigest()
                f.close()
        remote_compat_body = reply
        remote_compat_hash = \
            hashlib.md5(remote_compat_body).hexdigest()
        if local_compat_hash != remote_compat_hash:
            self.new_compat_avail = True
            with open(local_compat, 'wb') as f:
                f.write(remote_compat_body)
                f.close()
        else:
            self.new_compat_avail = False
        message = 'You have the latest compatibility table.'
        if self.new_compat_avail:
            message = 'The compatibility table was updated. Please restart RCU to make these changes take effect.'
        else:
            if not show_mb:
                return callback()
        mb = QMessageBox(self.pane_controller.window)
        mb.setWindowTitle('Compatibility Check')
        mb.setText(message)
        mb.exec()
        callback()

        
