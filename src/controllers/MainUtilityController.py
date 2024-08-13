'''
MainUtilityController.py
This is the main window of the application.

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

from PySide2.QtCore import Qt, QObject, QEvent, QCoreApplication, \
    QSettings, QTimer, QRect
from PySide2.QtWidgets import QListWidgetItem, QShortcut, QApplication
from PySide2.QtGui import QKeySequence, QPalette, QPixmap
from controllers import UIController, ConnectionPane
from panes import paneslist, IncompatiblePane, AboutPane
from pathlib import Path
import log
import gc
import platform

PANEROLE = 420

class GeometryEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize \
           or event.type() == QEvent.Move:
            if not hasattr(obj, '_appsettings'):
                return False
            size = obj.size()
            pos = obj.pos()
            obj._appsettings.setValue('cx_utility_controller/geosize', size)
            obj._appsettings.setValue('cx_utility_controller/geopos', pos)
            return True
        else:
            # standard event processing
            try:
                return QObject.eventFilter(self, obj, event)
            except:
                return False

class DroppedConnectionController(UIController):
    adir = Path(__file__).parent.parent
    ui_filename = Path(adir / 'views' / 'DroppedConnection.ui')

    def __init__(self, parent_controller):
        super(type(self), self).__init__(parent_controller.model,
                                         parent_controller.threadpool)
        iconfile = str(Path(type(self).adir / 'views' / 'icons' / 'dialog-warning.png'))
        icon = QPixmap()
        icon.load(iconfile)
        self.window.icon_label.setPixmap(icon)

class MainUtilityController(UIController):
    adir = Path(__file__).parent.parent
    ui_filename = Path(adir / 'views' / 'ConnectionUtility.ui')
    
    def __init__(self, model, threadpool):
        super(type(self), self).__init__(model,
                                         threadpool)
        self.current_pane = None

        self.load_cx_pane()

        if QCoreApplication.args.cli:
            # Everything that follows is meant for GUI
            return

        # Fix highlight color to whatever was set with theme
        ss = self.window.listWidget.styleSheet()
        newbgcolor = QCoreApplication.instance().palette().color(
            QPalette.Highlight)
        newbgalpha = 50
        if QCoreApplication.is_dark_mode:
            newbgalpha = 100
        newbgstr = 'rgba({}, {}, {}, {})'.format(newbgcolor.red(),
                                                 newbgcolor.green(),
                                                 newbgcolor.blue(),
                                                 newbgalpha)
        newcolor = QCoreApplication.instance().palette().color(
            QPalette.Text)
        newcolorstr = 'rgb({}, {}, {})'.format(newcolor.red(),
                                               newcolor.green(),
                                               newcolor.blue())
        ss += '''
QListWidget::item::selected  {
	/*background-color: rgb(191, 218, 229);*/
	/*background-color: rgba(150, 200, 210, 128);*/
	border: 1px solid rgba(90, 90, 90, 80);
	border-right: 1px solid rgba(128, 128, 128, 64);
	margin-right: -10px;
        background-color: ''' + newbgstr + ''';
        color: ''' + newcolorstr + ''';
}'''
        self.window.listWidget.setStyleSheet(ss)

        # Restore geometry
        oldsize = QSettings().value('cx_utility_controller/geosize')
        oldpos = QSettings().value('cx_utility_controller/geopos')
        desktop_rect = QApplication.desktop().availableGeometry()
        if oldsize:
            self.window.resize(oldsize)
        if oldpos:
            # Check if the window pos will be on the screen -- if not,
            # render it at neutral coordinates.
            if desktop_rect.contains(QRect(oldpos, oldsize)):
                log.info('repositioning window normally')
                self.window.move(oldpos)
            else:
                window_rect = QRect(oldpos, oldsize)
                log.info('desktop does not encompass window')
                log.info(str(window_rect), str(desktop_rect))
                if 'Windows' == platform.system():
                    # Any sane window manager would relocate windows
                    # that are painted outside the screen bounds. All
                    # of them do, except Windows.
                    window_rect.moveCenter(desktop_rect.center())
                    # # Go right->up->left->down, so the top-left window
                    # # corner will always end up in the top-left of screen.
                    # if window_rect.right() > desktop_rect.right():
                    #     log.debug('shifting leftwards')
                    #     window_rect.moveRight(desktop_rect.right())
                    # if window_rect.bottom() > desktop_rect.bottom():
                    #     log.debug('shifting upwards')
                    #     log.debug(window_rect.bottom(), desktop_rect.bottom())
                    #     window_rect.moveBottom(desktop_rect.bottom())
                    # if window_rect.left() < desktop_rect.left():
                    #     log.debug('shifting rightwards')
                    #     window_rect.moveLeft(desktop_rect.left())
                    # if window_rect.top() < desktop_rect.top():
                    #     log.debug('shifting downwards')
                    #     window_rect.moveTop(desktop_rect.top())
                # Move to final position
                self.window.move(window_rect.left(), window_rect.top())

        # Save geometry on resize
        self.window._appsettings = QSettings()
        efilt = GeometryEventFilter(self.window)
        self.window.installEventFilter(efilt)

        # do on click
        self.window.listWidget.currentItemChanged.connect(
            lambda a: self.pane_change(a, save=False))

        # Quit shortcut
        quitshortcut = QShortcut(QKeySequence.Quit, self.window)
        quitshortcut.activated.connect(QApplication.instance().quit)
        closeshortcut = QShortcut(QKeySequence.Close, self.window)
        closeshortcut.activated.connect(QApplication.instance().quit)

        self.window.show()

    def evaluate_cli_args(self, args):
        # Ask each pane to process its CLI arguments, then exit.
        count = self.window.listWidget.count()
        for n in range(0, count):
            pane = self.window.listWidget.item(n).data(PANEROLE)
            ret = pane.evaluate_cli(args)
            if ret is not None:
                QCoreApplication.exit(ret)

    def continue_loading_after_connection(self):
        self.disable_all_panes()
        self.load_other_panes()

        # Start active connection polling
        self.cx_timer = QTimer()
        self.cx_timer.setInterval(1000)
        self.cx_timer.timeout.connect(self.connection_check)
        self.cx_counter = 5
        # self.cx_timer.start()
        self.cx_check_pane = DroppedConnectionController(self)
        self.window.pane_layout.addWidget(self.cx_check_pane.window)
        self.cx_check_pane.window.hide()

        # CLI vs. GUI
        if QCoreApplication.args.cli:
            return self.evaluate_cli_args(QCoreApplication.args)

        self.window.show()
        self.cx_timer.start()

    def connection_check(self):
        if self.cx_counter > 0:
            self.cx_counter -= 1
        else:
            self.cx_counter = 5
            if not self.model.is_connected() and not self.model.reconnect():
                log.error('no active connection; device is probably sleeping')
                self.show_checkscreen()
            else:
                self.hide_checkscreen()

    def show_checkscreen(self):
        if not self.cx_check_pane.window.isVisible():
            self.disable_all_panes()
            self.current_pane.data(PANEROLE).window.hide()
            self.cx_check_pane.window.show()

    def hide_checkscreen(self):
        if self.cx_check_pane.window.isVisible():
            self.reload_pane_compatibility()
            self.update_all_pane_data()
            self.enable_all_panes()
            self.cx_check_pane.window.hide()
            self.current_pane.data(PANEROLE).window.show()

    def pane_change(self, new=None, save=True):
        if not new:
            return
        new_pane = new.data(PANEROLE)
        layout = self.window.pane_layout

        if self.current_pane:
            previous_pane = self.current_pane.data(PANEROLE)
            layout.removeWidget(previous_pane.window)
            previous_pane.window.hide()
        
        # load new pane into frame
        layout.addWidget(new_pane.window)
        new_pane.window.show()
        self.current_pane = new

        # Set the sidebar
        row = self.window.listWidget.row(new)
        self.window.listWidget.setCurrentRow(row)

        # save to config to reload on new start
        if save:
            pname = type(new_pane).name
            QSettings().setValue(
                'cx_utility_controller/current_pane', pname)

    def load_cx_pane(self):
        # Load the Connection Pane
        panecls = ConnectionPane
        newitem = QListWidgetItem(
            panecls.get_icon(),
            panecls.name)
        newitem.setData(PANEROLE, panecls(self))
        self.window.listWidget.addItem(newitem)
        self.pane_change(newitem, save=False)
        newitem.data(PANEROLE).window.host_lineEdit.setFocus()

        # When autoconnect is set, don't checkfetch right away.
        checkfetch = True
        if newitem.data(PANEROLE).ac_set:
            checkfetch = False

        # Load the About Pane
        panecls = AboutPane
        newitem = QListWidgetItem(
            panecls.get_icon(),
            panecls.name)
        newitem.setData(PANEROLE, panecls(self, checkfetch=checkfetch))
        self.window.listWidget.addItem(newitem)

        self.enable_all_panes()

    def cx_failed_callback(self):
        self.ask_about_pane_for_checkfetch()

    def ask_about_pane_for_checkfetch(self):
        aboutpane = self.window.listWidget.item(
            self.window.listWidget.count() - 1)
        aboutpane.data(PANEROLE).do_auto_checkfetch()

    def load_other_panes(self):
        # Registers each pane in the sidebar
        restore_pane_name = QSettings().value(
            'cx_utility_controller/current_pane')
        firstpane = True
        restore_pane = False

        # Remove special Connection Pane
        self.window.listWidget.takeItem(0)

        # Did the About Pane already check/fetch?
        ap = self.window.listWidget.item(0).data(PANEROLE)
        did_checkfetch = ap.did_checkfetch
        del ap

        # Remove special About Pane
        self.window.listWidget.takeItem(0)

        # Load list items for panes _before_ checking them for other
        # operations. This will fill the GUI, so it doesn't look
        # weird when loading (if, for instance, a QMessageBox shows
        # and pauses the template loading.
        for panecls in paneslist:
            newitem = QListWidgetItem(
                panecls.get_icon(),
                panecls.name)
            # Add pane to list
            self.window.listWidget.addItem(newitem)

        for p, panecls in enumerate(paneslist):
            newitem = self.window.listWidget.item(p)
            
            # Check compatibility
            no_check_compat = QCoreApplication.args.no_check_compat
            if no_check_compat:
                log.info('skipping pane compatibility check for {}'.
                         format(panecls.name))
            if not no_check_compat \
               and not panecls.is_compatible(self.model):
                # load the other pane
                log.error('{} pane: unknown compatibility with {}'\
                          .format(panecls.name, self.model.device_info['osver']))
                log.info(self, panecls)
                newitem.setData(PANEROLE, IncompatiblePane(self, panecls))
            else:
                # If this is the About Pane, and we didn't already
                # check/fetch, tell it to do so.
                if panecls is AboutPane and did_checkfetch:
                    newitem.setData(PANEROLE, panecls(self, checkfetch=False))
                else:
                    # The actual pane instance is stored with the
                    # listwidgetitem
                    newitem.setData(PANEROLE, panecls(self))

            # Open the default pane upon load
            if firstpane:
                self.pane_change(newitem)
                firstpane = False
            elif panecls.name == restore_pane_name \
                 and not self.model.is_in_recovery:
                restore_pane = newitem
        if restore_pane:
            self.pane_change(restore_pane)
        if self.model.is_in_recovery:
            self.disable_nonessential_panes()
        # change do on click to save last-used pane
        self.window.listWidget.currentItemChanged.connect(
            lambda x: self.pane_change(x, save=True))

    def reload_pane_compatibility(self):
        # After a restore, the version of Xochitl might have changed. Go
        # through each pane, and determine whether it should be replaced
        # with an incompatibility barrier, or the existing barrier
        # released.

        for i in range(0, self.window.listWidget.count()):
            lwitem = self.window.listWidget.item(i)
            pane = lwitem.data(PANEROLE)

            # If it is _already_ an IncompatiblePane, should it be?
            if type(pane) is IncompatiblePane \
               and not pane.has_continued_loading \
               and pane.truepanecls.is_compatible(self.model):
                # It really is compatible, so reload this pane with
                # full compatibility.
                lwitem.setData(PANEROLE, pane.truepanecls(self))

            # If it is _not_ an IncompatiblePane, should it be?
            if type(pane) is not IncompatiblePane \
               and not type(pane).is_compatible(self.model):
                try:
                    pane.poll_timer.stop()
                except Exception as e:
                    pass
                pane.window.close()
                pane.window.setParent(None)
                lwitem.setData(PANEROLE,
                               IncompatiblePane(self, type(pane)))
        gc.collect() # destroy old pane refs

    def update_all_pane_data(self):
        # Asks all the panes to update their data
        for i in range(0, self.window.listWidget.count()):
            pane = self.window.listWidget.item(i).data(PANEROLE)
            pane.update_view()

    def disable_nonessential_panes(self):
        # Disables panes during backups
        for i in range(0, self.window.listWidget.count()):
            item = self.window.listWidget.item(i)
            pane = item.data(PANEROLE)
            if not type(pane).is_essential:
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)

    def enable_all_panes(self):
        # The antithesis to disable_nonessential_panes()
        for i in range(0, self.window.listWidget.count()):
            item = self.window.listWidget.item(i)
            pane = item.data(PANEROLE)
            item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if hasattr(pane, 'handle_cx_restore'):
                pane.handle_cx_restore()

    def disable_all_panes(self):
        for i in range(0, self.window.listWidget.count()):
            item = self.window.listWidget.item(i)
            pane = item.data(PANEROLE)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            if hasattr(pane, 'handle_cx_break'):
                pane.handle_cx_break()
