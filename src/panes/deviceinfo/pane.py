'''
pane.py
This is the Device Info pane.

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

from pathlib import Path
import math
import controllers
import log
from worker import Worker
from . import backup
from PySide2.QtWidgets import QInputDialog, QLineEdit, QMessageBox, \
    QMenu, QFileDialog
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtCore import Qt, QSize, QSettings, QCoreApplication
import time
import platform
from .BatteryInfoController import BatteryInfoController
from model.firmware import Firmware
import os
import tempfile
import hashlib



class ProgressMeter():
    def __init__(self, window):
        self.window = window
        self.layout = self.window.progressbar_layout
        log.info('got layout', self.layout)
    def activate(self):
        pass
    def deactivate(self):
        pass
    def set_abort_func(self, new_abort_func):
        pass
    def set_progress(self, x):
        pass
        



def prettynum(num):
    return ('%.1f'%(num)).__str__().replace('.0', '')

def hide_all_in_layout(layout):
    for i in range(0, layout.count()):
        item = layout.itemAt(i)
        item.hide()
def show_all_in_layout(layout):
    for i in range(0, layout.count()):
        item = layout.itemAt(i)
        item.show()
        
class DeviceInfoPane(controllers.UIController):
    identity = 'me.davisr.rcu.deviceinfo'
    name = 'Device Info'
    
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'deviceinfo.ui')

    is_essential = True

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'utilities-system-monitor.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)
        self.pane_controller = pane_controller

        self.device_name = None

        self.recoveryos_controller = controllers.RecoveryOSController(
            self.model)

        self.backup_dir = QCoreApplication.sharePath / Path('backups')
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        log.info('backups are stored in {}'.format(self.backup_dir))
        self.backup_controller = backup.BackupController(self)

        self.battinfo_controller = BatteryInfoController(self)

        self.hwmodeltype = type(self.model).modelnum_to_hwtype(
            self.model.device_info['model'])

        self.wrote_fw_cleanly = None
        
        self.backup_types = None
        if 'RM1' == self.hwmodeltype:
            self.backup_types = backup.rm1_backup_types
        if 'RM2' == self.hwmodeltype:
            self.backup_types = backup.rm2_backup_types

        # Tracking this variable is a poor man's way of getting past
        # the gray-out tint when setting a label to 'disabled'.
        self.allow_prodimage_menu = True

        if not QCoreApplication.args.cli:
            self.update_view(loadinfo=False)
            # Load product image
            imagepath = type(self).adir / type(self).bdir / Path('icons')
            pxm = QPixmap()
            if 'RM1' == self.hwmodeltype:
                filename = imagepath / 'rm1.png'
            else: #if 'RM2' == self.hwmodeltype:
                filename = imagepath / 'rm2.png'
            pxm.load(str(filename))
            prodimage_label = self.window.prodimage_label
            prodimage_label.setPixmap(pxm)

            # Button registration
            self.window.backup_pushButton.clicked.connect(
                self.make_backup)
            self.window.abort_pushButton.clicked.connect(
                self.abort_backup)
            self.window.rename_pushButton.clicked.connect(
                self.rename_device)
            self.window.battinfo_pushButton.clicked.connect(
                self.battinfo_controller.start_window)

            # Add a menu for switching boot partitions
            prodimage_label.setContextMenuPolicy(Qt.CustomContextMenu)
            prodimage_label.customContextMenuRequested.connect(
                self.open_prodimage_menu)

            # Load backup types
            self.load_backup_types()

            # visual stuff
            self.set_buttons_relaxed()
            
            # Register to get a callback (like if storage space changes)
            self.model.register_device_info_pane(self)

    def open_prodimage_menu(self, position):
        if not self.allow_prodimage_menu:
            return
        prodimage_menu = QMenu()

        def pretty_label(name, curval):
            prefix = 'Disable' if curval else 'Enable'
            return '{} {}'.format(prefix, name)

        # Toggle Web UI
        toggle_webui = prodimage_menu.addAction(
            pretty_label('Web UI', self.model.check_conf('WebInterfaceEnabled')))
        toggle_webui.triggered.connect(lambda: self.model.toggle_conf('WebInterfaceEnabled'))

        # Toggle Wi-Fi
        def wificheck():
            if not self.model.is_using_usb():
                # show message box
                mb = QMessageBox(self.window)
                mb.setWindowTitle('Disable Wi-Fi')
                mb.setText("Peforming this operation may break the connection with your tablet. Are you sure?")
                mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
                mb.setDefaultButton(QMessageBox.No)
                ret = mb.exec()
                if int(QMessageBox.Yes) != ret:
                    return
            self.model.toggle_conf('wifion')
        toggle_wifi = prodimage_menu.addAction(
            pretty_label('Wi-Fi', self.model.check_conf('wifion')))
        toggle_wifi.triggered.connect(wificheck)

        # Toggle Automatic Updates
        # (Not a xochitl.conf thing, but a systemctl service)
        autoupd_svc = 'update-engine'
        def checkautoupd():
            status = self.model.get_systemd_service(autoupd_svc)
            return status
        toggle_autoupd = prodimage_menu.addAction(
            pretty_label('Automatic Updates',
                         self.model.get_systemd_service(autoupd_svc)))
        toggle_autoupd.triggered.connect(
            lambda: self.model.set_systemd_service(
                'update-engine',
                not self.model.get_systemd_service(autoupd_svc)))

        prodimage_menu.addSeparator()

        # Flip boot partition
        flip_boot = prodimage_menu.addAction('Flip Boot Partition')
        flip_boot.triggered.connect(lambda x: self.flip_boot_partition())

        # Upload firmware
        upl_fw = prodimage_menu.addAction('Upload Firmware')
        upl_fw.triggered.connect(lambda x: self.upload_firmware())

        # Add contextual menu
        prodimage_menu.exec_(self.window.prodimage_label.mapToGlobal(position))

    def flip_boot_partition(self, warn=True):
        if warn:
            mb = QMessageBox(self.window)
            mb.setWindowTitle('Warning')
            mb.setText("Flipping the boot partition may have unexpected side effects on your tablet's data. Are you sure you want to continue?")
            mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
            mb.setDefaultButton(QMessageBox.No)
            ret = mb.exec()
            if int(QMessageBox.Yes) != ret:
                return
        oldpart = int(self.model.run_cmd('/sbin/fw_printenv -n active_partition')[0].strip())
        newpart = 2
        if 2 == oldpart:
            newpart = 3
        self.model.run_cmd('/sbin/fw_setenv "upgrade_available" "1"')
        self.model.run_cmd('/sbin/fw_setenv "bootcount" "0"')
        self.model.run_cmd('/sbin/fw_setenv "fallback_partition" "{}"'.format(oldpart))
        self.model.run_cmd('/sbin/fw_setenv "active_partition" "{}"'.format(newpart))
        self.model.restart_hw()

    def upload_firmware(self):
        mb = QMessageBox(self.window)
        mb.setWindowTitle('Warning')
        mb.setText("Uploading new firmware may have unexpected side effects on your tablet's data. Are you sure you want to continue?")
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.No)
        ret = mb.exec()
        if int(QMessageBox.Yes) != ret:
            return
        log.info('uploading firmware')

        # If not using local connection, try to abort.
        if not self.check_if_usb_cx(action_msg='Uploading new firmware'):
            return
        
        # Select the firmware file
        fw_path = QSettings().value('pane/deviceinfo/firmware_path') or Path.home()
        filename = QFileDialog.getOpenFileName(
            self.window,
            'Select a firmware file...',
            str(fw_path),
            'rM Firmware (*.signed *.SIGNED)')
        if not filename \
           or not len(filename) \
           or not filename[0] \
           or '' == filename[0]:
            log.error('did not get a filename, aborting')
            return

        # Save the path for next time
        fw_path = Path(filename[0]).parent
        QSettings().setValue('pane/deviceinfo/firmware_path', str(fw_path))

        # Use as Firmware object
        fw_file = Path(filename[0])
        log.info('using fw file:', fw_file.name)
        fw = Firmware(fw_file)

        # Set the buttons as 'busy'
        self.set_buttons_backup()
        self.window.abort_pushButton.setEnabled(False)
        self.pane_controller.disable_nonessential_panes()
        self.pane_controller.cx_timer.stop()

        # Kick off a worker to upload the firmware
        worker = Worker(fn=lambda progress_callback:
                        self.do_write_firmware(progress_callback, fw))
        self.threadpool.start(worker)
        worker.signals.progress.connect(
            lambda x: self.window.backup_progressBar.setValue(x))
        worker.signals.finished.connect(self.do_finish_firmware)


    def do_write_firmware(self, progress_callback, fw):
        # This function is called in a thread.

        # master abort signal
        abort = False

        # Progress callback values:
        # 00..26   extracting firmware
        # 26..63   taking safety backup
        # 63..100  writing new firmware

        progress_callback.emit(0)

        # release these files upon complete
        tmp_filepaths = []
        def cleanup():
            for f in tmp_filepaths:
                log.info('cleanup: unlinking tmp file {}'.format(f))
                f.unlink()

        def get_checksum_from_device(device):
            # Verify the checksum on the device matches.
            log.info('getting checksum from device')
            cmd = 'md5sum {} | cut -d" " -f1'.format(device)
            out, err = self.model.run_cmd(cmd)
            checksum = out.strip()
            log.info(checksum, device)
            # sanity check
            if 32 != len(checksum):
                log.error('checksum did not pass sanity check')
                return False
            return checksum

        def get_local_checksum(filepath):
            md5 = hashlib.md5()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(1048576), b''):
                    md5.update(chunk)
            return md5.hexdigest()

        def get_binfile_from_device(device, progsize=283115520,
                                    progcb=lambda x: ()):
            th, tmp = tempfile.mkstemp(suffix='.ext4')
            os.close(th)
            binfile = Path(tmp)
            tmp_filepaths.append(binfile)
            log.info('cloning {} to {}'.format(device, binfile))
            bytes_read = 0
            with open(binfile, 'ab+') as f:
                cmd = 'dd if={} bs=4M'.format(device)
                out, err = self.model.run_cmd(cmd, raw_noread=True)
                for chunk in iter(lambda: out.read(1048576), b''):
                    f.write(chunk)
                    bytes_read += len(chunk)
                    progcb(bytes_read / progsize)
            if get_local_checksum(binfile) != get_checksum_from_device(device):
                log.error('local binfile did not match expected checksum')
                return False
            return binfile

        def write_binfile_to_device(binfile, device, progsize=283115520,
                                    progcb=lambda x: ()):
            # Copy the firmware data over the target partition.
            log.info('writing out to device')
            cmd = 'cat > "{}"'.format(device)
            out, err, stdin = self.model.run_cmd(
                cmd, raw_noread=True, with_stdin=True)
            bytes_written = 0
            with open(binfile, 'rb') as f:
                for chunk in iter(lambda: f.read(1048576), b''):
                    stdin.write(chunk)
                    bytes_written += len(chunk)
                    progcb(bytes_written / progsize)
                f.close()
                stdin.close()
            log.info('wrote firmware')
            if get_checksum_from_device(device) != get_local_checksum(binfile):
                log.error('checksum did not match what was written!')
                return False
            return True

        # Find the inactive partition. This is what we will
        # overwrite.
        # 
        # This is probably something which could happen in rcu.py,
        # but I'm not sure if it would be used anywhere else, and
        # so it makes sense to keep it here.
        cmd = '/sbin/fw_printenv -n fallback_partition'
        out, err = self.model.run_cmd(cmd)
        if len(err.strip()):
            log.error(err)
            log.error('aborting do_extract_firmware')
            return cleanup()
        try:
            target_partnum = int(out.strip())
        except Exception as e:
            log.error('error getting partition number')
            log.error(e)
            return cleanup()
        device = '{}p{}'.format(
            self.model.boot_disk,
            out.strip())
        log.info('target partition to overwrite is', device)

        # Test that the partition exists, and isn't mounted.
        cmd = 'if test -e {} && ! (df {} >/dev/null 2>&1); then echo yes; fi'.format(
            device, device)
        out, err = self.model.run_cmd(cmd)
        if 'yes' != out.strip():
            log.error(out.strip())
            log.error('either the target device does not exist, or it is mounted')
            return cleanup()

        # Get pre-size (let's us an easy abort before spending lots of
        # time checksumming or transferring).
        cmd = 'wc -c {} | cut -d" " -f1'.format(device)
        out, err = self.model.run_cmd(cmd)
        if len(err.strip()):
            log.error(err)
            return cleanup()
        old_size = int(out.strip())

        # Extract the new firmware to a temporary file. This should be
        # done before transferring any real data because that is slower,
        # giving opportunity to abort quicker.
        th, tmp = tempfile.mkstemp(suffix='.ext4')
        os.close(th)
        extracted_fw = Path(tmp)
        log.info('extracting firmware to', extracted_fw)
        fw.extract_to_file(extracted_fw, prog_cb=lambda x:
                         progress_callback.emit(x / old_size * 25))
        tmp_filepaths.append(extracted_fw)
        fw_size = os.stat(extracted_fw).st_size

        if fw_size < old_size:
            log.info('size of partition ({}) does not equal firmware ({})!'.\
                      format(old_size, fw_size))
            log.info('resizing to match')
            total_bytes = old_size
            written = fw_size
            chunksize = 1048576
            with open(extracted_fw, 'ab+') as f:
                while (total_bytes - written) > chunksize:
                    f.write(bytearray(chunksize))
                    written += chunksize
                    progress_callback.emit(written / total_bytes * 26)
                if (total_bytes - written):
                    f.write(bytearray(total_bytes - written))
                    written += (total_bytes - written)
                    progress_callback.emit(written / total_bytes * 26)

        fw_size = os.stat(extracted_fw).st_size
        if old_size != fw_size:
            log.error('size of partition ({}) too small for firmware ({})!'.\
                      format(old_size, fw_size))
            return cleanup()

        # Take the existing partition as a temporary backup.
        # NOTE: this is all pretty much duplicated from BackupFile.py.
        # TODO: augment BackupFile.py to be used here.
        log.info('making safety copy of device partition')
        old_clone = get_binfile_from_device(
            device, progsize=old_size, progcb=lambda x:
            progress_callback.emit(26 + (x * 37)))
        if not old_clone:
            return cleanup()

        # Copy the firmware data over the target partition.
        log.info('writing new firmware')
        ret = write_binfile_to_device(
            extracted_fw, device, progsize=fw_size, progcb=lambda x:
            progress_callback.emit(63 + (x * 37)))
        if not ret:
            log.error('failure writing firmware to device')
            log.info('writing back safety copy')
            ret = write_binfile_to_device(
                old_clone, device, progsize=old_size,
                progcb=lambda x: progress_callback.emit(60 + (x * 40)))
            if not ret:
                log.error('there was a fatal problem writing firmware. tablet may be in a broken state. recommended to investigate manually.')
                return cleanup()
        log.info('wrote firmware successfully')
        self.wrote_fw_cleanly = True
        progress_callback.emit(100)
        return cleanup()

    def do_finish_firmware(self):
        self.set_buttons_relaxed()
        self.pane_controller.cx_timer.start()
        self.pane_controller.enable_all_panes()
        if self.wrote_fw_cleanly:
            self.wrote_fw_cleanly = None
            self.flip_boot_partition(warn=False)
        else:
            self.wrote_fw_cleanly = None
            log.error('firmware was not written cleanly!')
            mb = QMessageBox(self.pane_controller.window)
            mb.setWindowTitle('Dirty Firmware Written')
            mb.setText('Something happened, and the firmware was not written successfully. The fallback partition might not boot! Try uploading the firmware again.')
            mb.exec()
        self.pane_controller.reload_pane_compatibility()
        self.pane_controller.update_all_pane_data()

    def load_backup_types(self):
        self.window.backuptype_comboBox.clear()
        
        for btype in self.backup_types:
            # Quick hack for Parabola to only allow Full-level backup
            if 'Full' in btype:
                self.window.backuptype_comboBox.addItem(
                    btype,
                    userData=self.backup_types[btype])
            # Don't add non-full backup types while in recovery mode
            elif self.model.device_info and 'osver' in self.model.device_info and self.model.device_info['osver'] and 'Parabola' not in self.model.device_info['osver']:
                self.window.backuptype_comboBox.addItem(
                    btype,
                    userData=self.backup_types[btype])

    def update_view(self, loadinfo=True):
        if loadinfo:
            self.model.load_device_info()
            self.load_backup_types()
        self.load_device_name()
        self.load_strings()
        
    def set_buttons_relaxed(self):
        self.window.backup_progressBar.hide()
        self.window.backup_progressBar.setValue(0)
        self.window.abort_pushButton.setEnabled(False)
        self.window.abort_pushButton.hide()
        self.window.abort_pushButton.setText('Abort')
        # self.window.import_pushButton.setEnabled(True)
        # self.window.import_pushButton.show()
        self.window.backup_pushButton.setEnabled(True)
        self.window.backup_pushButton.show()
        self.window.backup_treeWidget.setEnabled(True)
        self.window.rename_pushButton.setEnabled(True)
        self.window.battinfo_pushButton.setEnabled(True)
        self.window.backuptype_comboBox.show()
        self.allow_prodimage_menu = True

        if self.model.is_in_recovery:
            self.window.rename_pushButton.setEnabled(False)
            # self.window.battinfo_pushButton.setEnabled(False)
        
        
    def load_strings(self):
        # Loads the device info strings into labels
        nastring = '—'

        model = self.model.device_info['model'] or nastring
        self.window.model_label.setText(model)

        serial = self.model.device_info['serial'] or nastring
        self.window.serial_label.setText(serial)

        osver = self.model.device_info['osver'] or nastring
        self.window.osver_label.setText(osver)

        cpu = self.model.device_info['cpu'] or nastring
        self.window.cpu_label.setText(cpu)

        ram = (prettynum(self.model.device_info['ram']) \
               + ' MB') if self.model.device_info['ram'] else nastring
        self.window.ram_label.setText(ram)

        storavail = (prettynum(self.model.device_info['storage_max'] \
                               - self.model.device_info['storage_used']) + ' GB available') if self.model.device_info['storage_max'] else nastring
        self.window.storage_label.setText(storavail)

    def load_device_name(self):
        # Gets the name from the device
        name = self.model.device_info['rcuname']
        self.device_name = name
        if name != '' and name != type(self.model).default_name:
            # posession
            if name[-1] == 's':
                name += "'"
            else:
                name += "'s"

        # load in window
        if not self.device_name or name == type(self.model).default_name:
            name = 'Connected'
        w = self.window.deviceinfo_groupBox
        w.setTitle(name + ' reMarkable')
        
    def rename_device(self):
        # Adds a file to the device containing the owner's name
        # grab the name
        # ...
        # Cut to
        loadname = '' if self.device_name == type(self.model).default_name else self.device_name
        text, ok = QInputDialog().getText(
            self.window, 'Rename Device', "Owner's Name:", QLineEdit.Normal,
            loadname)
        if ok:
            self.model.set_device_name(text)
            self.load_device_name()
        
        
    def set_buttons_backup(self):
        self.window.backup_progressBar.setEnabled(True)
        self.window.backup_progressBar.show()
        # self.window.import_pushButton.setEnabled(False)
        # self.window.import_pushButton.hide()
        self.window.backup_pushButton.setEnabled(False)
        self.window.backup_pushButton.hide()
        self.window.abort_pushButton.setEnabled(True)
        self.window.abort_pushButton.show()
        self.window.backup_treeWidget.setEnabled(False)
        self.window.rename_pushButton.setEnabled(False)
        self.window.battinfo_pushButton.setEnabled(False)
        self.window.backuptype_comboBox.hide()
        self.allow_prodimage_menu = False

    def check_if_usb_cx(self, action_msg='The selected action'):
        # Warn the user if they are not on a USB connection and trying
        # to take or restore a backup.
        if self.model.is_using_usb():
            return True
        mb = QMessageBox(self.window)
        mb.setWindowTitle('Warning')
        mb.setText('It appears this tablet is not connected over USB. {} must happen over a USB connection. Continue anyway?'.format(action_msg))
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.No)
        ret = mb.exec()
        if int(QMessageBox.Yes) != ret:
            return False
        return True

    def show_failed_operation_device_in_recovery(self):
        mb = QMessageBox(self.window)
        mb.setWindowTitle('Failed Backup/Recovery Operation')
        mb.setText('The tablet may be stuck in recovery mode. If this is the case, please hold the Power button for 10 seconds, release it, then turn it on again normally.')
        mb.setStandardButtons(QMessageBox.Ok)
        mb.exec()

    def abort_backup(self):
        # Abort a currently-running backup
        log.info('aborting backup!')
        self.backup_controller.set_abort()
        self.window.abort_pushButton.setText('Aborting')
        self.window.abort_pushButton.setEnabled(False)
        self.window.backup_progressBar.setEnabled(False)


        
        
    def make_backup(self):
        # Depending on the option selected, this will make a backup.
        log.info('make_backup')
        if not self.check_if_usb_cx(action_msg='Taking a snapshot'):
            return
        self.pane_controller.disable_nonessential_panes()
        self.set_buttons_backup()
        self.pane_controller.cx_timer.stop()
        bfiles = self.window.backuptype_comboBox.currentData()
        needs_recovery = False
        for bf in bfiles:
            if 'bin' == bf[1]:
                needs_recovery = True
                break
        if needs_recovery:
            self.do_backup()
        else:
            self.do_soft_backup()
        
    def do_backup(self):
        bfiles = self.window.backuptype_comboBox\
                            .currentData()
        def entered(is_in_recovery):
            if is_in_recovery:
                worker = Worker(
                    fn=lambda progress_callback, bfiles=bfiles:
                    self.backup_controller.make_backup(
                        progress_callback, bfiles))
                self.threadpool.start(worker)
                worker.signals.progress.connect(
                    lambda x: self.window.backup_progressBar.setValue(
                        int(round(x))))
                worker.signals.finished.connect(
                    self.make_backup_finished)
            else:
                log.error('cannot do_backup because recoveryos is not loaded')
                self.make_backup_finished()
        self.recoveryos_controller.enter_recovery_mode(entered, load_info=False)

    def make_backup_finished(self):
        def left(is_out):
            if not is_out:
                log.error('could not leave recovery mode after backup')
                self.show_failed_operation_device_in_recovery()
            else:
                self.backup_controller.find_and_load_backups()
            self.set_buttons_relaxed()
            self.pane_controller.enable_all_panes()
            self.pane_controller.cx_timer.start()
        self.recoveryos_controller.leave_recovery_mode(left)

    def do_soft_backup(self):
        # This is a 'soft' backup -- where we don't load the recovery OS
        # to perform it. Instead, we remount the data partition as
        # read-only, dump it, then remount it as read-write again.

        mb = QMessageBox(self.window)
        mb.setWindowTitle('Soft Backup')
        mb.setText('Your tablet will become unresponsive during this backup. If you encounter a problem, you may need to restart RCU, or restart the tablet manually by holding the power button.')
        mb.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        mb.setDefaultButton(QMessageBox.Cancel)
        ret = mb.exec()
        if int(QMessageBox.Ok) != ret:
            self.make_soft_backup_finished()
            return
        # return True
        self.model.notebooks_pane.poll_timer.stop()
        self.model.run_cmd('touch /tmp/rcu_taking_backup')
        # kill xochitl and unmount home partition
        log.info('!! doing soft backup')
        bfiles = self.window.backuptype_comboBox\
                            .currentData()
        self.model.stop_xochitl()
        # There isn't a great place to put this, but if doing softbin
        # backups, unmount those drives. If the ydon't unmount cleanly,
        # abort the rest of the procedure.
        for bf in bfiles:
            if 'softbin' == bf[1]:
                out, err = self.model.run_cmd('cd / && umount {}'.format(bf[2]))
                if err and len(err):
                    log.error(str(err))
                    return self.make_soft_backup_finished()
        worker = Worker(
            fn=lambda progress_callback, bfiles=bfiles:
            self.backup_controller.make_backup(
                progress_callback, bfiles))
        self.threadpool.start(worker)
        worker.signals.progress.connect(
            lambda x: self.window.backup_progressBar.setValue(
                int(round(x))))
        worker.signals.finished.connect(
            self.make_soft_backup_finished)

    def make_soft_backup_finished(self):
        # insurance policy against aborted checksum procedure
        self.model.run_cmd("ps | grep 'md5sum /dev/mmcblk2p4' 2>/dev/null | awk '{print $1}' | xargs kill")
        self.model.run_cmd('mount -a')
        self.model.run_cmd('rm -f /tmp/rcu_taking_backup')
        self.model.start_xochitl()
        self.model.run_cmd('sleep 5')

        if hasattr(self, 'backup_controller'):
            self.backup_controller.find_and_load_backups()
            self.set_buttons_relaxed()
            self.pane_controller.enable_all_panes()
            self.pane_controller.cx_timer.start()
            self.model.notebooks_pane.poll_timer.start()

    def make_restore(self, trig):
        # This function is triggered from the contextual menu in
        # BackupController.py.
        log.info('make_restore')
        if not self.check_if_usb_cx(action_msg='Restoring a snapshot'):
            return
        # Called by a button to restore a backup to the device
        self.set_buttons_backup()
        self.window.abort_pushButton.setEnabled(False)
        self.pane_controller.disable_nonessential_panes()
        self.pane_controller.cx_timer.stop()

        bfiles = self.window.backuptype_comboBox.currentData()
        needs_recovery = False
        for bf in bfiles:
            if 'bin' == bf[1]:
                needs_recovery = True
                break
        if needs_recovery:
            self.do_restore(trig)
        else:
            self.do_soft_restore(trig)

    def do_restore(self, trig):
        def entered(is_in_recovery):
            if is_in_recovery:
                log.info('starting restore worker')
                worker = Worker(
                    fn=lambda progress_callback:
                    trig(progress_callback))
                self.threadpool.start(worker)
                worker.signals.progress.connect(
                    lambda x: self.window.backup_progressBar.setValue(
                        int(round(x))))
                # On finish, reload all the windows
                worker.signals.finished.connect(self.finish_restore)
            else:
                log.error('cannot do_restore because recoveryos is not loaded')
                self.finish_restore()
            self.recoveryos_controller.enter_recovery_mode(entered, load_info=False)

    def do_soft_restore(self, trig):
        mb = QMessageBox(self.window)
        mb.setWindowTitle('Soft Restore')
        mb.setText('Your tablet will become unresponsive during this backup. If you encounter a problem, you may need to restart RCU, or restart the tablet manually by holding the power button.')
        mb.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        mb.setDefaultButton(QMessageBox.Cancel)
        ret = mb.exec()
        if int(QMessageBox.Ok) != ret:
            self.make_soft_restore_finished()
            return
        self.model.notebooks_pane.poll_timer.stop()
        self.model.stop_xochitl()

        log.info('starting restore worker')
        worker = Worker(
            fn=lambda progress_callback:
            trig(progress_callback))
        worker.signals.progress.connect(
            lambda x: self.window.backup_progressBar.setValue(
                int(round(x))))
        # On finish, reload all the windows
        # worker.signals.finished.connect(self.finish_restore)
        worker.signals.finished.connect(self.make_soft_restore_finished)
        self.threadpool.start(worker)

    def make_soft_restore_finished(self):
        self.model.start_xochitl()
        self.model.run_cmd('sleep 5')
        if hasattr(self, 'backup_controller'):
            self.backup_controller.find_and_load_backups()
            self.set_buttons_relaxed()
            self.pane_controller.enable_all_panes()
            self.pane_controller.cx_timer.start()
            self.model.notebooks_pane.poll_timer.start()

    def finish_restore(self):
        def left(has_left):
            if not has_left:
                log.error('could not leave recovery mode after restore')
                self.show_failed_operation_device_in_recovery()
            else:
                self.pane_controller.reload_pane_compatibility()
                self.pane_controller.update_all_pane_data()
                self.pane_controller.enable_all_panes()
                self.pane_controller.cx_timer.start()
            self.set_buttons_relaxed()
            self.window.abort_pushButton.setEnabled(False)
        self.recoveryos_controller.leave_recovery_mode(left)
