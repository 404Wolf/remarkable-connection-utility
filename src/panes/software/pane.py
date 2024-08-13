'''
pane.py
This is the Software Manager pane.

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

import log
from controllers import UIController
from pathlib import Path
from PySide2.QtCore import Qt, QSize, QRect, QSettings
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QListWidget, QListWidgetItem, \
    QFileDialog, QMessageBox, QSizePolicy

class SoftwarePane(UIController):
    identity = 'me.davisr.rcu.software'
    name = 'Software'
    
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'software.ui')

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'emblem-package-16.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.listwidget = PkgListWidget()
        self.listwidget.currentItemChanged.connect(
            self.set_uninstall_button)
        self.window.list_layout.replaceWidget(
            self.window.listWidget_placeholder,
            self.listwidget)

        self.packages = set()
        self.update_view()

        # Button handlers
        self.window.upload_install_pushButton.clicked.connect(
            self.upload_and_install_package)
        self.window.uninstall_remove_pushButton.clicked.connect(
            self.uninstall_and_remove_package)

    def update_view(self):
        self.load_internal_packages()
        self.load_widget_items()
        self.set_uninstall_button()

    def set_uninstall_button(self):
        item = self.listwidget.currentItem()
        if not item:
            self.window.uninstall_remove_pushButton.setEnabled(False)
            return
        self.window.uninstall_remove_pushButton.setEnabled(True)

    def load_internal_packages(self):
        # Finds all the installed software on the device. Looks into the
        # ~/.rmpkg folder for packages, then checks if their manifests
        # are unloaded to the file system.

        # The system should have an ~/.rmpkg directory where package
        # files are kept. These packages may or may not be installed.
        # This command will test each one to see which ones are
        # installed. It is faster to run these in one go, rather than
        # making a new RMPackage, then using some is_installed()
        # method.

        cmd = 'find $HOME/.rmpkg -maxdepth 1 -type f -name "*.rmpkg"'
        out, err = self.model.run_cmd(cmd)
        if err:
            log.info('no rmpkgs detected ({})'.format(err.strip()))
            return

        new_packages = set()
        for rmpath in out.splitlines():
            # If this package exists in self.packages, take that one
            # as the reference. Otherwise, make a new one.
            no_pkg = True
            for pkg in self.packages:
                if pkg.rmpath == rmpath:
                    no_pkg = False
                    new_packages.add(pkg)
                    break
            if no_pkg:
                pkg = RMPackage(self.model, rmpath)
                new_packages.add(pkg)
        self.packages = new_packages

    def load_widget_items(self):
        # Takes the internal packages and puts them into the list
        # widget. If the package touches any system files, it will
        # get a Microchip emblem. Otherwise, it will get a Package
        # emblem.
        lw = self.listwidget

        # Remove all items from the list widget that do not exist
        # in the package list.
        to_remove = []
        for i in range(0, lw.count()):
            item = lw.item(i)
            if item.userData not in self.packages:
                to_remove.append(i)
        to_remove.reverse()
        for i in to_remove:
            lw.takeItem(i)

        # Add all the items from the package list to the list
        # widget.
        for pkg in self.packages:
            found = False
            for i in range(0, lw.count()):
                item = lw.item(i)
                if pkg is item.userData:
                    found = True
                    break
            if not found:
                info = pkg.info()
                log.info(info['title'])
                item = RMPackageListWidgetItem(info['title'])
                # Add emblem
                ipath = Path(type(self).bdir / 'icons')
                icon = QIcon()
                if pkg.is_system_package():
                    icon.addFile(str(ipath / 'application-x-firmware.png'), QSize(24, 24), QIcon.Normal, QIcon.On)
                else:
                    icon.addFile(str(ipath / 'emblem-package.png'), QSize(24, 24), QIcon.Normal, QIcon.On)
                item.setIcon(icon)
                item.setToolTip(info['description'])
                item.userData = pkg
                lw.insertItem(lw.count(), item)

    def upload_and_install_package(self):
        # This is tied to the Upload button. A user selects a package on
        # the local disk, it is uploaded to the tablet, and installed.

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/software/last_import_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/software/last_import_path',
                Path.home())
            default_savepath = Path.home()

        # Get package from file manager
        filename = QFileDialog.getOpenFileName(
            self.window,
            'Install Package',
            str(default_savepath),
            'rM Packages (*.rmpkg *.RMPKG)')
        if not filename or '' == filename[0]:
            return False
        filepath = Path(filename[0])
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/software/last_import_path',
            filepath.parent)

        # Upload package to ~/.rmpkg
        cmd = 'mkdir -p $HOME/.rmpkg'
        out, err = self.model.run_cmd(cmd)
        
        cmd = 'cat > "$HOME/.rmpkg/{}"'.format(filepath.name)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                stdin.write(chunk)
            stdin.close()
            f.close()

        cmd = 'chmod +x $HOME/.rmpkg/{}'.format(filepath.name)
        out, err = self.model.run_cmd(cmd)

        cmd = 'realpath $HOME/.rmpkg/{}'.format(filepath.name)
        out, err = self.model.run_cmd(cmd)
        if err:
            log.error(err)
            return
        rmpath = out.strip()

        # Make temporary RMPackage()
        tmp_pkg = RMPackage(self.model, rmpath)

        # Check for conflicts
        # ... !!! TODO

        # Run pkg install
        tmp_pkg.install()

        # Reload view
        self.update_view()

    def uninstall_and_remove_package(self):
        # This is tied to the uninstall button. A user selects a package
        # and it is uninstalled and removed from the tablet.
        items = self.listwidget.selectedItems()
        if len(items) != 1:
            return
        item = items[0]
        pkg = item.userData

        # Throw up a message box
        # ...

        ret = pkg.uninstall()
        if not ret:
            # This should throw a message window
            # ...
            log.error('Could not uninstall package!')
            return

        ret = pkg.delete()
        if not ret:
            # This should throw a message window
            # ...
            log.error('Could not delete package!')
            return

        self.update_view()

class RMPackage:
    # This class holds information about a package on the device.
    
    def __init__(self, model, rmpath):
        self.model = model
        self.rmpath = rmpath

        self._info = None
        self._manifest = None

    def is_installed(self):
        # Checks that all the files listed in the package manifest exit
        # in the filesystem.
        cmd = '''{} --manifest | while read -r t; do
                 if ! test -e $t; then exit 1; fi;
                 done; echo $?'''.format(self.rmpath)
        out, err = self.model.run_cmd(cmd)
        if err:
            log.error('Error checking package is_installed')
            log.error(err)
            return
        ret = out.strip()
        if '0' != ret:
            return False
        return True

    def info(self):
        if self._info:
            return self._info
        
        cmd = '{} --info'.format(self.rmpath)
        out, err = self.model.run_cmd(cmd)
        if err:
            log.error('Error getting package info')
            log.error(err)
            return
        ret = {
            'title': '',
            'description': '' }
        out = out.strip()
        split = out.split('\n')
        ret['title'] = split[0]
        ret['description'] = '\n'.join(split[2:])

        self._info = ret
        return self._info

    def _load_manifest(self):
        cmd = '{} --manifest'.format(self.rmpath)
        out, err = self.model.run_cmd(cmd)
        if err:
            log.error('Error loading package manifest')
            log.error(err)
            return
        self._manifest = out.strip()

    def is_system_package(self):
        # A System package touches system files. Packages that keep
        # themselves to ~/.local are Regular packages.
        if not self._manifest:
            self._load_manifest()
        is_sys = False
        for line in self._manifest.splitlines():
            if not line.startswith('/home'):
                is_sys = True
                break
        return is_sys

    def install(self):
        cmd = '{} --install; echo $?'.format(self.rmpath)
        out, err = self.model.run_cmd(cmd)
        # May throw errors out.
        if len(err):
            log.error(err)
            return False
        return True

    def uninstall(self):
        cmd = '{} --uninstall'.format(self.rmpath)
        out, err = self.model.run_cmd(cmd)
        return True

    def delete(self):
        cmd = 'rm {}'.format(self.rmpath)
        out, err = self.model.run_cmd(cmd)
        if err:
            log.error('Could not delete package')
            log.error(err)
            return False
        return True

class RMPackageListWidgetItem(QListWidgetItem):
    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)

class PkgListWidget(QListWidget):
    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)

        self.setObjectName(u"listWidget")
        # self.setGeometry(QRect(10, 31, 461, 371))
        self.setProperty("showDropIndicator", False)
        self.setAlternatingRowColors(True)
        # Windows shows the default differently, so be explicit
        #self.setStyleSheet('alternate-background-color: #f9f9f9;')
        self.setIconSize(QSize(24, 24))
        self.setSortingEnabled(True)

        sizePolicy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(sizePolicy)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Escape and
            event.modifiers() == Qt.NoModifier):
            self.selectionModel().clear()
        else:
            super(type(self), self).keyPressEvent(event)
    def mousePressEvent(self, event):
        if not self.indexAt(event.pos()).isValid():
            self.selectionModel().clear()
        super(type(self), self).mousePressEvent(event)

    
