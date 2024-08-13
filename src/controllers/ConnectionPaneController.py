'''
ConnectionPaneController.py
The connection pane is a special, privileged pane that allows a user 
to edit device connection information and initiate a connection.

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

import socket
from worker import Worker
import sys
from pathlib import Path
import controllers
import log
from PySide2.QtCore import Qt, QSettings, QObject, QEvent, QPoint, \
    QCoreApplication, QSize
from PySide2.QtWidgets import QMenu, QShortcut, QApplication, QAction, \
    QInputDialog, QLineEdit, QMessageBox
from PySide2.QtGui import QKeySequence, QIcon

class OptionButtonEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress \
           and event.button() == Qt.LeftButton:
            x1 = obj.width() - 15  # estimated margin
            x2 = event.x()
            if x2 < x1:
                obj.menu().defaultAction().trigger()
                return True
        return QObject.eventFilter(self, obj, event)

class ReturnKeyEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and \
           (event.key() == Qt.Key_Return or \
            event.key() == Qt.Key_Enter):
            self.parent().menu().defaultAction().trigger()
        return QObject.eventFilter(self, obj, event)
        



class Preset:
    def __init__(self, manager, adict=None):
        self.manager = manager
        
        if adict:
            self.name = adict['name']
            self.host = adict['host']
            self.username = adict['username']
            self.password = adict['password']
        else:
            plus = 1
            while True:
                trynum = len(self.manager.presets) + plus
                tryname = 'Preset {}'.format(trynum)
                found = False
                for p in self.manager.presets:
                    if p.name == tryname:
                        found = True
                        break
                if not found:
                    self.name = tryname
                    break
                plus += 1
            self.host = None
            self.username = None
            self.password = None

        self.action = QAction(self.name)
        self.action.triggered.connect(self.clicked)

        # UI default state
        self.action.setCheckable(True)
        self.action.setChecked(False)
        
    def clicked(self):
        self.manager.switch_to(self)

    def as_dict(self):
        return {'name': self.name,
                'host': self.host,
                'username': self.username,
                'password': self.password}

    def is_active(self):
        return self.action.isChecked()

    def activate(self):
        # GUI things for the menu
        self.action.setChecked(True)
        self.action.setEnabled(False)

    def deactivate(self):
        # GUI things for the menu
        self.action.setChecked(False)
        self.action.setEnabled(True)
                
class PresetManager:
    def __init__(self, hostmenu, hostline, userline, passline):
        self.hostmenu = hostmenu
        self.hostline = hostline
        self.userline = userline
        self.passline = passline

        self.presets = []
        self.load_settings()

    def add_new(self, pdict=None):
        p = Preset(self, pdict)
        if 0 >= len(self.presets):
            self.hostmenu.insertAction(None, p.action)
        else:
            self.hostmenu.insertAction(
                self.presets[-1].action,
                p.action)
        self.presets.append(p)
        return p
    
    def switch_to(self, presetb):
        # switches to presetb
        for p in self.presets:
            p.deactivate()
        presetb.activate()
        self.hostline.setText(presetb.host)
        self.userline.setText(presetb.username)
        self.passline.setText(presetb.password)
        self.commit_settings()

    def get_current_preset(self):
        for p in self.presets:
            if p.is_active():
                return p

    def save_current_preset(self):
        # turn linedits into preset values
        log.info('saving current preset')
        for p in self.presets:
            if p.is_active():
                p.host = self.hostline.text()
                p.username = self.userline.text()
                p.password = self.passline.text()
                self.commit_settings()
                return

    def rename_current_preset(self, newname):
        p = self.get_current_preset()
        p.action.setText(newname)
        p.name = newname
        self.commit_settings()

    def delete_current_preset(self):
        # deletes the current preset
        if 1 >= len(self.presets):
            return
        for i in range(0, len(self.presets)):
            p = self.presets[i]
            if p.is_active():
                self.hostmenu.removeAction(p.action)
                self.presets = self.presets[:i] + self.presets[i+1:]
                self.switch_to(self.presets[-1])
                return True

    def load_settings(self):
        # Load settings from config file and populate the self with
        # Preset objects. If no settings exist, then populate with
        # a dummy/first preset.
        migrated = False
        settings = QSettings().value('connection/presets')
        if settings is None:
            # Try to migrate old information
            host = None
            if QSettings().value('connection/host'):
                host = QSettings().value('connection/host')
            username = None
            if QSettings().value('connection/user'):
                username = QSettings().value('connection/user')
            password = None
            if QSettings().value('connection/pass'):
                password = QSettings().value('connection/pass')
            
            log.info('no presets exist; migrating from old config')
            settings = {'active': 0, 'presets': [{
                'name': 'Preset 1',
                'host': host,
                'username': username,
                'password': password}]}
            migrated = True
        active = settings['active']
        active_p = None
        for i in range(0, len(settings['presets'])):
            pdict = settings['presets'][i]
            p = self.add_new(pdict)
            if active == i:
                active_p = p
        if active_p:
            self.switch_to(active_p)
        if migrated:
            self.commit_settings()
            QSettings().remove('connection/ip')
            QSettings().remove('connection/host')
            QSettings().remove('connection/user')
            QSettings().remove('connection/pass')

    def commit_settings(self):
        sav = {'active': 0, 'presets': []}
        for i in range(0, len(self.presets)):
            p = self.presets[i]
            sav['presets'].append(p.as_dict())
            if p.is_active():
                sav['active'] = i
        QSettings().setValue('connection/presets', sav)

    
class ConnectionPane(controllers.UIController):
    identity = 'me.davisr.rcu.connection'
    name = 'Connection'
    is_essential = False

    adir = Path(__file__).parent.parent
    ui_filename = Path(adir, 'views', 'ConnectionPane.ui')

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.adir, 'views', 'icons', \
                            'system-shutdown.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon
    
    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.pane_controller = pane_controller
        
        # Load with a PresetManager once we can get a menu instance
        self.presets = None

        # load config
        self.window.host_lineEdit.setText(
            QSettings().value('connection/host'))
        self.window.user_lineEdit.setText(
            QSettings().value('connection/user'))
        self.window.pass_lineEdit.setText(
            QSettings().value('connection/pass'))
        self.window.autoconnect_checkBox.setChecked(
            bool(int(QSettings().value('connection/autoconnect') or 0)))

        # If the user right-clicks on the Connect button, give them
        # an option to load RCU into a Restore mode. For this, assume
        # the tablet is in DFU mode, and ready to be uploaded the
        # restore OS right away.
        connect_btn = self.window.connect_pushButton
        self.cx_menu = self.get_connect_menu()
        connect_btn.setMenu(self.cx_menu)
        connect_btn.installEventFilter(
            OptionButtonEventFilter(self.window))

        # Connection presets are stored behind the Save button
        save_btn = self.window.save_pushButton
        self.preset_menu = self.get_preset_menu()
        save_btn.setMenu(self.preset_menu)
        save_btn.installEventFilter(
            OptionButtonEventFilter(self.window))

        # For these, it would be better to search the QWidget for the
        # default QPushButton. Shortcut: just use connect_btn
        self.window.host_lineEdit.installEventFilter(
            ReturnKeyEventFilter(connect_btn))
        self.window.user_lineEdit.installEventFilter(
            ReturnKeyEventFilter(connect_btn))
        self.window.pass_lineEdit.installEventFilter(
            ReturnKeyEventFilter(connect_btn))

        # Show password toggle
        self.window.showpass_checkBox.clicked.connect(
            self.toggle_password_visibility)

        # Autoconnect toggle
        self.window.autoconnect_checkBox.clicked.connect(
            self.toggle_autoconnect)

        # Autoconnect if that was specified in an argument
        self.ac_set = bool(int(QSettings().value('connection/autoconnect') or 0))
        if (self.ac_set and not QCoreApplication.args.cli) \
           or QCoreApplication.args.autoconnect:
            self.cx_menu.defaultAction().trigger()

    def toggle_password_visibility(self):
        vis = self.window.showpass_checkBox.isChecked()
        if vis:
            self.window.pass_lineEdit.setEchoMode(
                QLineEdit.Normal)
        else:
            self.window.pass_lineEdit.setEchoMode(
                QLineEdit.Password)

    def toggle_autoconnect(self):
        ac = self.window.autoconnect_checkBox.isChecked()
        QSettings().setValue('connection/autoconnect', int(ac))

    def add_new_preset(self):
        # This will add a new preset in the manager, and also refresh
        # self.preset_menu.
        self.presets.switch_to(self.presets.add_new())
        self.recalc_delete_btn()

    def rename_current_preset(self):
        # brings up a rename dialog
        text, ok = QInputDialog().getText(
            self.window,
            'Rename Preset',
            'New Name:',
            QLineEdit.Normal,
            self.presets.get_current_preset().name)
        if ok:
            self.presets.rename_current_preset(text)

    def delete_current_preset(self):
        mb = QMessageBox(self.window)
        mb.setWindowTitle('Delete Preset')
        mb.setText('This action will delete {}. Are you sure?'.format(self.presets.get_current_preset().name))
        mb.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if QMessageBox.Yes == mb.exec():
            self.presets.delete_current_preset()
            self.recalc_delete_btn()

    def recalc_delete_btn(self):
        if 1 >= len(self.presets.presets):
            self.delete_btn.setEnabled(False)
        else:
            self.delete_btn.setEnabled(True)

    def get_preset_menu(self):
        menu = QMenu()
        
        # This loads menu entries for presets
        self.presets = PresetManager(menu,
                                     self.window.host_lineEdit,
                                     self.window.user_lineEdit,
                                     self.window.pass_lineEdit)
        new = menu.addAction('Add new')
        new.triggered.connect(self.add_new_preset)
        
        menu.addSeparator()
        rename = menu.addAction('Rename')
        rename.triggered.connect(self.rename_current_preset)
        save = menu.addAction('Save')
        save.triggered.connect(self.save_config)
        
        menu.addSeparator()
        delete = menu.addAction('Delete')
        delete.triggered.connect(self.delete_current_preset)
        self.delete_btn = delete
        self.recalc_delete_btn()

        menu.setDefaultAction(save)
        return menu

    def get_connect_menu(self):
        menu = QMenu()
        normal_cx = menu.addAction('Connect Normally')
        normal_cx.triggered.connect(self.make_connection_async)
        upload_ros = menu.addAction('Enter Recovery OS')
        upload_ros.triggered.connect(self.upload_recoveryos_and_connect)
        menu.setDefaultAction(normal_cx)
        return menu

    def upload_recoveryos_and_connect(self):
        self.fill_config()
        self.disable_interface()
        controllers.RecoveryOSController(self.model, skip_windows=True)\
                   .enter_recovery_mode(self.continue_loading,
                                        load_info=True)
        
    def fill_config(self):
        # We want to fill the config prior to saving, but sometimes we
        # want to make a connection without saving. This will just fill
        # the config parameters.
        self.model.config.host = self.window.host_lineEdit.text()
        self.model.config.user = self.window.user_lineEdit.text()
        self.model.config.password = self.window.pass_lineEdit.text()
        
    def save_config(self):
        # Saves the current preset to settings file.
        self.fill_config()
        self.presets.save_current_preset()
        
    def make_connection_async(self):
        log.info('make_connection_async')
        self.fill_config()
        self.disable_interface()
        worker = Worker(
            fn=lambda progress_callback: self.model.connect())
        self.threadpool.start(worker)
        worker.signals.finished.connect(self.continue_loading)

    def disable_interface(self):
        self.window.connect_pushButton.setEnabled(False)
        self.window.user_lineEdit.setEnabled(False)
        self.window.host_lineEdit.setEnabled(False)
        self.window.pass_lineEdit.setEnabled(False)
        self.window.save_pushButton.setEnabled(False)
        self.window.showpass_checkBox.setEnabled(False)
        self.window.autoconnect_checkBox.setEnabled(False)
        self.cpbpretext = self.window.connect_pushButton.text()
        
    def continue_loading(self, success=False):
        # Success is disregarded, check for ourselves (it was just
        # for compatibility)
        if self.model.config.is_connected():
            log.info('connection successful')
            # # Pass over to main window
            # self.main_window = controllers.ConnectionUtilityController(
            #     self)
            # self.window.close()
            self.pane_controller.continue_loading_after_connection()
        else:
            log.error('connection unsuccessful')

            self.window.connect_pushButton.setText('Connecting')
            self.model.connect()
            self.window.connect_pushButton.setEnabled(True)
            self.window.connect_pushButton.setText(self.cpbpretext)
            self.window.user_lineEdit.setEnabled(True)
            self.window.host_lineEdit.setEnabled(True)
            self.window.pass_lineEdit.setEnabled(True)
            self.window.save_pushButton.setEnabled(True)
            self.window.showpass_checkBox.setEnabled(True)
            self.window.autoconnect_checkBox.setEnabled(True)

            if not QCoreApplication.args.cli:
                msgs = {
                    '_default': 'A connection could not be made. Please ensure these connection settings are correct, and that your tablet is turned on and plugged in.',
                    'timeout': 'A connection could not be made due to a network timeout. Please ensure the host address is correct, and that your tablet is turned on and plugged in.',
                    'AuthenticationException': 'The connection was denied due to incorrect credentials. Please review the username and password.',
                    'PasswordRequiredException': 'The connection was denied because your public key file is encrypted. Is <code>ssh-agent</code> running, and was the proper key added through <code>ssh-add</code>?'
                    }
                mb = QMessageBox(self.window)
                mb.setWindowTitle('Connection Failure')
                # log.debug(self.model.config.cx_error)
                mb.setTextFormat(Qt.RichText)
                try:
                    msg = msgs[self.model.config.cx_error]
                except:
                    msg = msgs['_default']
                mb.setText(msg)
                mb.setStandardButtons(QMessageBox.Ok)
                mb.exec()
            else:
                QCoreApplication.exit(1)

            # Signal back to maybe do a check/fetch.
            self.pane_controller.cx_failed_callback()
