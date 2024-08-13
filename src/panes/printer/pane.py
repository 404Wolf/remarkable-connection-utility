'''
pane.py
This is the virtual print server pane.

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

import log
from controllers import UIController
from pathlib import Path
from PySide2.QtCore import Qt, QSize, QRect, QSettings, QObject, \
    QSettings, QCoreApplication
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QListWidget, QListWidgetItem, \
    QFileDialog, QMessageBox, QSizePolicy, QApplication

import tempfile
import os
from worker import Worker
from datetime import datetime
import platform
import subprocess

from model.document import Document

from .ippserver.behaviour import StatelessPrinter
from .ippserver.server import IPPRequestHandler, IPPServer
from .ippserver.ppd import BasicPostscriptPPD, BasicPdfPPD

class PrinterPane(UIController):
    identity = 'me.davisr.rcu.printer'
    name = 'Printer'
    
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'printer.ui')

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'device-printer.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.service_enabled = None
        self.will_restore_service = False
        self.server = None

        # Indicator label
        ipathstr = str(Path(type(self).bdir / 'icons' / 'status-dialog-information.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(24, 24), QIcon.Normal, QIcon.On)
        self.window.indicator_label.setPixmap(icon.pixmap(24, 24))

        # Load instructions
        self.load_instructions()

        # Button handlers
        self.window.settings_pushButton.clicked.connect(
            self.open_print_settings)
        self.window.start_service_pushButton.clicked.connect(
            self.toggle_service)
        self.window.stop_service_pushButton.clicked.connect(
            self.toggle_service)

        # If we don't connect to the app's aboutToQuit signal, the
        # print server will exist forever, and the main process will
        # never terminate.
        self.model._app.aboutToQuit.connect(self.handle_cx_break)

        # Read QSettings for service check
        self._service_key = 'pane/printer/service_enabled'
        read_val = QSettings().value(self._service_key)
        if None != read_val and int(read_val):
            if not QCoreApplication.args.cli:
                self.start_service()
        else:
            self.stop_service()


    def handle_cx_break(self):
        if self.service_enabled:
            self.will_restore_service = True
            self.stop_service()

    def handle_cx_restore(self):
        if self.will_restore_service:
            self.start_service()
            self.will_restore_service = False

    def load_instructions(self):
        # Determine which instructions to show the user. Hide all of
        # them, then show the one we want.
        self.window.gnome_instructions_label.hide()
        self.window.macos_instructions_label.hide()
        self.window.windows_instructions_label.hide()
        plat = platform.system()
        instructions_label = self.window.gnome_instructions_label
        if 'Darwin' == plat:
            instructions_label = self.window.macos_instructions_label
        if 'Windows' == plat:
            instructions_label = self.window.windows_instructions_label
        instructions_label.show()

    def open_print_settings(self):
        cmd = {
            'FreeBSD': 'system-config-printer &',
            'Linux': 'bash -c "(system-config-printer &) || (gnome-control-center printers &) || (systemsettings kcm_printer_manager &)"',
            'Darwin': 'open -b com.apple.systempreferences /System/Library/PreferencePanes/PrintAndScan.prefPane',
            'Windows': 'printers'
        }
        plat = platform.system()
        if 'Windows' == plat:
            subprocess.run(
                ['control.exe', cmd[plat]],
                stdin=None,
                stdout=None,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP \
                | subprocess.CREATE_BREAKAWAY_FROM_JOB \
                | subprocess.DETACHED_PROCESS)
        else:
            # Linux fails xdg-open with shared library when
            # packaging with pyinstaller.
            newenv = dict(os.environ.copy())
            lp_key = 'LD_LIBRARY_PATH'
            lp_orig = newenv.get(lp_key + '_ORIG')
            if lp_orig is not None:
                newenv[lp_key] = lp_orig
            else:
                lp = newenv.get(lp_key)
            if lp is not None:
                newenv.pop(lp_key)
            subprocess.run(cmd[plat],
                           shell=True,
                           preexec_fn=os.setpgrp,
                           stdin=None,
                           stdout=None,
                           env=newenv)

    def toggle_service(self):
        if not self.service_enabled:
            self.start_service()
        else:
            self.stop_service()

    def finish_toggle_service(self):
        # Set the UI elements
        if self.service_enabled:
            self.window.indicator_label.setEnabled(True)
            self.window.start_service_pushButton.hide()
            self.window.stop_service_pushButton.show()
            self.window.status_label.setText('Running')
            QSettings().setValue(self._service_key,
                                 int(self.service_enabled))
        else:
            self.window.indicator_label.setEnabled(False)
            self.window.stop_service_pushButton.hide()
            self.window.start_service_pushButton.show()
            self.window.status_label.setText('Stopped')
            # service_enabled is None when there is an error -- only
            # update QSettings for legitimate stops.
            if False is self.service_enabled:
                QSettings().setValue(self._service_key,
                                     int(self.service_enabled))

    def start_service(self):
        if not self.service_enabled:
            if not self.server:
                try:
                    self.server = RCUPrintServer(self)
                except Exception as e:
                    log.error('Error starting print server.')
                    self.print_status_callback(e.__str__())
                    self.finish_toggle_service()
                    return
            worker = Worker(lambda progress_callback: self.server.go())
            self.threadpool.start(worker)
            worker.signals.finished.connect(lambda: ())
            self.service_enabled = True
            self.finish_toggle_service()

    def stop_service(self):
        if self.service_enabled:
            self.server.stop()
            self.server = None
            self.service_enabled = False
        if not self.will_restore_service:
            self.finish_toggle_service()

    def print_status_callback(self, data=None):
        date_s = str(datetime.now())[:-7]  # remove second decimals
        text = date_s + ' - ' + data
        self.window.printlog_listWidget.insertItem(0, text)
        log.info(data)


class RCUPrintServer:
    def __init__(self, controller):
        self.controller = controller

        behave = RunCallbackPrinter(
            self.upload_notebook)

        self.server = IPPServer(
            ('127.0.0.1', 8493),
            IPPRequestHandler,
            behave)

    def go(self):
        self.controller.print_status_callback('Started virtual printer')
        self.server.serve_forever()
        # ^^ this executes indefinitely ^^

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.controller.print_status_callback('Stopped virtual printer')

    def upload_notebook(self, pdfpath, doctitle):
        self.controller.print_status_callback('Printed document {}'.format(doctitle))
        dummydoc = Document(self.controller.model)
        dummydoc.upload_file(pdfpath, visible_name=doctitle)
        self.controller.model.restart_xochitl()
        pdfpath.unlink()

class RunCallbackPrinter(StatelessPrinter):
    def __init__(self, callback):
        self.callback = callback
        plat = platform.system()
        ppds = {'FreeBSD': BasicPdfPPD,
                'Linux': BasicPdfPPD,
                'Darwin': BasicPostscriptPPD,
                'Windows': BasicPostscriptPPD}
        super(type(self), self).__init__(ppd=ppds[plat]())

    def handle_postscript(self, ipp_request, postscript_file):
        jobname = ipp_request.lookup(1, b'job-name', 66)[0]\
                             .decode('utf-8')
        filename = Document.get_sanitized_name(jobname)

        # If we're just catching a PDF file (FreeBSD or GNU/Linux),
        # nothing else needs to be done.
        if BasicPdfPPD == type(self.ppd):
            th_pdf, tmp_pdf = tempfile.mkstemp(prefix=filename, suffix='.pdf')
            os.close(th_pdf)
            tmpfile_pdf = Path(tmp_pdf)
            with open(tmpfile_pdf, 'wb') as f:
                while True:
                    block = postscript_file.read(1)
                    if b'' == block:
                        break
                    else:
                        f.write(block)
                f.close()
            self.callback(tmpfile_pdf, jobname)
            return

        # Otherwise, continue by converting the (actual) PostScript
        # input to PDF.
        th_ps, tmp_ps = tempfile.mkstemp(prefix=filename, suffix='.ps')
        os.close(th_ps)
        tmpfile_ps = Path(tmp_ps)

        # All Windows PS exports end with these bytes. Windows does NOT
        # send an EOF (like any sane print driver would).
        win_end = [69, 79, 74, 13, 10, 27, 37, 45, 49, 50, 51, 52, 53, 88]
        with open(tmpfile_ps, 'wb') as f:
            last_bytes = []
            while True:
                block = postscript_file.read(1)
                if b'' == block:
                    break
                else:
                    f.write(block)
                    last_bytes += block
                    if len(last_bytes) > len(win_end):
                        last_bytes = last_bytes[-len(win_end):]
                    if last_bytes == win_end:
                        break
            postscript_file.close()
            f.close()

        th_pdf, tmp_pdf = tempfile.mkstemp(prefix=filename, suffix='.pdf')
        os.close(th_pdf)
        tmpfile_pdf = Path(tmp_pdf)

        # Ghostscript is used on both macOS and Windows. macOS 14
        # removed all Postscript tooling. Prior to this, the built-in
        # `pstopdf` command was used.
        from . import ghostscript
        args = ["ps2pdf", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-sOutputFile={}".format(str(tmpfile_pdf)), "-f", str(tmpfile_ps)]
        gs = ghostscript.Ghostscript(*args)
        del gs
        tmpfile_ps.unlink()
        self.callback(tmpfile_pdf, jobname)
