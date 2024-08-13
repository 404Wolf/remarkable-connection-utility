'''
pane.py
This is the Notebook Manager pane.

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

from controllers import UIController
from pathlib import Path
import log
from model.document import Document
from model.collection import Collection
from worker import Worker
import json
from datetime import datetime
import platform
import re
import platform
import subprocess
import os
import traceback
import pikepdf
from model.docrender import DocRenderPrefs

from PySide2.QtCore import Qt, QRect, QSize, QTimer, QSettings, \
    QObject, QEvent, QCoreApplication
from PySide2.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu, \
    QFrame, QAbstractItemView, QHeaderView, QFileDialog, QSizePolicy, \
    QColorDialog, QShortcut, QInputDialog, QLineEdit
from PySide2.QtGui import QIcon, QColor, QPixmap

def prettydate(then, abs=False):
    if not then:
        return
    tzdate = then # rM stores mod date in local timezone
    now = datetime.now()
    fmt = '%b %d, %Y at %I:%M %p'
    if now.date() == tzdate.date():
        fmt = 'Today at %I:%M %p'
    elif (now.date() - tzdate.date()).days == 1:
        fmt = 'Yesterday at %I:%M %p'
    elif now.year - tzdate.year == 0:
        fmt = '%b %d at %I:%M %p'
    if abs:
        fmt = '%B %d, %Y at %I:%M %p'
    return tzdate.strftime(fmt).replace(' 0', ' ')



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

    

class NotebooksPane(UIController):
    identity = 'me.davisr.rcu.notebooks'
    name = 'Notebooks'
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'notebooks.ui')

    xochitl_versions = [
        '^[1-2]\.[0-9]+\.[0-9]+\.[0-9]+$',
        '^3\.[0-4]\.[0-9]+\.[0-9]+$',
        '^3\.[0-9]\.[0-9]\.[0-9]+$',
        '^3\.1[0-1]\.[0-9]\.[0-9]+$'
    ]

    cli_args = [('--list-documents', True, None, 'list documents by ID, Name, and Timestamp'),
                ('--list-collections', True, None, 'list collections by ID, Name, and Timestamp'),
                ('--download-doc', 2, ('id', 'out.rmn'), 'download RMN notebook archive'),
                ('--download-rmdoc', 2, ('doc_id', 'out.rmn'), 'download RMDOC notebook archive'),
                ('--export-pdf-b', 2, ('doc_id', 'out.pdf'), 'export PDF (bitmap)'),
                ('--export-pdf-v', 2, ('doc_id', 'out.pdf'), 'export PDF (vector)'),
                ('--export-pdf-o', 2, ('doc_id', 'out.pdf'), 'export PDF (original)'),
                ('--export-epub-o', 2, ('doc_id', 'out.epub'), 'export Epub (original)'),
                ('--export-pdf-rm', 2, ('doc_id', 'out.pdf'), 'export PDF (rendered on-device)'),
                ('--upload-doc', 1, ('in.{rmn|pdf|epub}'), 'upload document'),
                ('--upload-doc-to', 2, ('in.{rmn|pdf|epub}', 'col_id'), 'upload document to specific collection')
                ]

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'accessories-text-editor.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def evaluate_cli(self, args):
        # set args for later access
        self.args = args
        ecode = None
        if args.list_documents:
            ecode = self.cli_list_documents()
        elif args.list_collections:
            ecode = self.cli_list_collections()
        elif args.download_doc:
            ecode = self.cli_download_doc()
        elif args.download_rmdoc:
            ecode = self.cli_download_rmdoc()
        elif args.export_pdf_b:
            ecode = self.cli_export_pdf(args.export_pdf_b, 'pdf-b')
        elif args.export_pdf_v:
            ecode = self.cli_export_pdf(args.export_pdf_v, 'pdf-v')
        elif args.export_pdf_o:
            ecode = self.cli_export_pdf(args.export_pdf_o, 'pdf-o')
        elif args.export_epub_o:
            ecode = self.cli_export_pdf(args.export_epub_o, 'epub-o')
        elif args.export_pdf_rm:
            ecode = self.cli_export_pdf(args.export_pdf_rm, 'pdf-rm')
        elif args.upload_doc:
            ecode = self.cli_upload_doc(args.upload_doc)
        elif args.upload_doc_to:
            ecode = self.cli_upload_doc(args.upload_doc_to)
        return ecode
            
    def cli_list_documents(self):
        self.model.load_notebooks(trigger_ui=False, force=False)
        for d in self.model.documents:
            log.cli(d)
        return 0

    def cli_list_collections(self):
        self.model.load_notebooks(trigger_ui=False, force=False)
        for c in self.model.collections:
            log.cli(c)
        return 0

    def cli_download_doc(self):
        # RMN archive
        self.model.load_notebooks(trigger_ui=False)
        self.model.load_templates(trigger_ui=False)
        search_docid = QCoreApplication.args.download_doc[0]
        match = None
        for d in self.model.documents:
            if d.uuid == search_docid:
                match = d
                break
        if not match:
            log.error('document not found')
            return 1
        filepath = QCoreApplication.args.download_doc[1]
        # save_archive returns the number of bytes transferred
        ret = match.save_archive(filepath)
        if ret or 0 <= 1:
            return 1 # problem--nothing transferred
        return 0

    def cli_download_rmdoc(self):
        # RMDOC archive
        self.model.load_notebooks(trigger_ui=False)
        self.model.load_templates(trigger_ui=False)
        search_docid = QCoreApplication.args.download_rmdoc[0]
        match = None
        for d in self.model.documents:
            if d.uuid == search_docid:
                match = d
                break
        if not match:
            log.error('document not found')
            return 1
        filepath = QCoreApplication.args.download_rmdoc[1]
        ret = match.save_rm_rmdoc(filepath)
        if True != ret:
            return 1 # problem--nothing transferred
        return 0

    def cli_export_pdf(self, arg, outfmt):
        # outfmt == pdf-b | pdf-v | pdf-o | epub-o | pdf-rm
        self.model.load_notebooks(trigger_ui=False)
        self.model.load_templates(trigger_ui=False)
        search_docid = arg[0]
        match = None
        for d in self.model.documents:
            if d.uuid == search_docid:
                match = d
                break
        if not match:
            log.error('document not found')
            return 1
        outfile = arg[1]

        # Output document
        if 'pdf-o' == outfmt:
            ret = match.save_original_file(outfile, filetype='pdf')
        elif 'epub-o' == outfmt:
            ret = match.save_original_file(outfile, filetype='epub')
        elif 'pdf-rm' == outfmt:
            ret = match.save_rm_pdf(outfile)
        else:
            # Renderer prefs pick up on CLI args.
            # ret = renderer.save_pdf(outfile)
            ret = match.save_pdf(outfile)
        if ret or 0 <= 1:
            return 1
        return 0

    def cli_upload_doc(self, arg):
        filepath = Path(arg[0])
        dummydoc = Document(self.model)
        upload_func = dummydoc.upload_archive
        if '.rmn' != filepath.suffix:
            upload_func = dummydoc.upload_file
        parent = None
        if 2 == len(arg):
            self.model.load_notebooks(trigger_ui=False)
            search_pid = arg[1]
            for c in self.model.collections:
                if c.uuid == search_pid:
                    parent = c
                    break
            if not parent:
                log.error('collection not found')
                return 1
        
        upload_func(filepath, parent)
        self.model.restart_xochitl()

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.notebook_controller = NotebookController(self)

        # Register model
        self.model.register_notebooks_pane(self)
        self.export_pdf_webui_action = None

        # Load widget items from model
        if not QCoreApplication.args.cli:
            self.update_view()

        # UI Cleanup
        self.window.xmitbar_widget.hide()

        # Download buttons
        self.notebook_controller.treewidget.itemSelectionChanged.connect(
            self.set_download_buttons)
        self.window.downloaddocument_pushButton.clicked.connect(
            self.download_items)
        self.window.abort_pushButton.clicked.connect(
            self.abort_tx_items)
        self.window.upload_pushButton.clicked.connect(
            self.upload_items)
        self.window.newcollection_pushButton.clicked.connect(
            self.add_new_collection)

        exportpdfbtn = self.window.exportpdf_pushButton
        exportpdfbtn.installEventFilter(
            OptionButtonEventFilter(self.window))
        self.exportmenu = self.get_exportpdf_menu(exportpdfbtn)
        exportpdfbtn.setMenu(self.exportmenu)

        # Category Combo
        self.categorycombo = self.window.category_comboBox
        self.categorycombo.currentIndexChanged.connect(
            self.change_category)

        # Poll for changes
        self.poll_timer = QTimer(self.window)
        self.poll_timer.setInterval(3000)
        self.poll_timer.timeout.connect(self.update_view)
        self.poll_timer.start()

        # Do a check for possible deleted (but not really) documents.
        no_check_reclaim_storage = QCoreApplication.args.no_check_reclaim_storage
        if not no_check_reclaim_storage:
            self.check_for_reclaimed_storage()

    def set_color(self, menuaction, newcolor=None, from_settings=False):
        # Sets the color for the given menu action.
        
        # If from_settings is True, it will load from settings, or
        # prefer the color the given in newcolor.
        
        # If newcolor and from_settings are both null, open a color
        # picker widget.

        if from_settings:
            key = menuaction.settings_key
            read_val = QSettings().value(key)
            if not read_val:
                QSettings().setValue(key, newcolor)
            else:
                newcolor = read_val

        from_menu = False
        if not newcolor:
            # open dialog
            newcolor = QColorDialog().getColor(
                menuaction.color,
                self.window,
                'Select Color',
                QColorDialog.ShowAlphaChannel)
            if not newcolor or not newcolor.isValid():
                # user cancelled
                menuaction.parent().parent().showMenu()
                return
            from_menu = True

        # Save new color to settings
        QSettings().setValue(menuaction.settings_key, newcolor)
        menuaction.color = newcolor
            
        # Generate icon
        pxmap = QPixmap(30, 30)
        pxmap.fill(newcolor)
        menuaction.setIcon(pxmap)

        if from_menu:
            # Hold the menu open (don't trigger for Reset Colors)
            menuaction.parent().parent().showMenu()

    def get_exportpdf_menu(self, parent):
        menu = QMenu(parent)

        # Save defaults to settings, since those are used as a global
        # space addressed by the brushes.

        # Get the default colors from DocRenderPrefs
        default_prefs = DocRenderPrefs

        # Black color
        black = menu.addAction('Black')
        black.default_color = default_prefs.black
        black.settings_key = 'pane/notebooks/export_pdf_blackink'
        self.set_color(black, black.default_color, from_settings=True)
        black.triggered.connect(lambda: self.set_color(black))

        # Gray color
        gray = menu.addAction('Gray')
        gray.default_color = default_prefs.gray
        gray.settings_key = 'pane/notebooks/export_pdf_grayink'
        self.set_color(gray, gray.default_color, from_settings=True)
        gray.triggered.connect(lambda: self.set_color(gray))

        # White color
        white = menu.addAction('White')
        white.default_color = default_prefs.white
        white.settings_key = 'pane/notebooks/export_pdf_whiteink'
        self.set_color(white, white.default_color, from_settings=True)
        white.triggered.connect(lambda: self.set_color(white))

        # Blue color (firmware 2.11)
        blue = menu.addAction('Blue')
        blue.default_color = default_prefs.blue
        blue.settings_key = 'pane/notebooks/export_pdf_blueink'
        self.set_color(blue, blue.default_color, from_settings=True)
        blue.triggered.connect(lambda: self.set_color(blue))

        # Red color (firmware 2.11)
        red = menu.addAction('Red')
        red.default_color = default_prefs.red
        red.settings_key = 'pane/notebooks/export_pdf_redink'
        self.set_color(red, red.default_color, from_settings=True)
        red.triggered.connect(lambda: self.set_color(red))

        # Highlight yellow (original)
        highlight_yellow = menu.addAction('Highlight Yellow')
        highlight_yellow.default_color = default_prefs.highlight_yellow
        highlight_yellow.settings_key = 'pane/notebooks/export_pdf_highlightink'
        self.set_color(highlight_yellow, highlight_yellow.default_color, from_settings=True)
        highlight_yellow.triggered.connect(lambda: self.set_color(highlight_yellow))

        # Highlight green (firmware 2.11)
        highlight_green = menu.addAction('Highlight Green')
        highlight_green.default_color = default_prefs.highlight_green
        highlight_green.settings_key = 'pane/notebooks/export_pdf_highlightgreenink'
        self.set_color(highlight_green, highlight_green.default_color, from_settings=True)
        highlight_green.triggered.connect(lambda: self.set_color(highlight_green))

        # Highlight pink (firmware 2.11)
        highlight_pink = menu.addAction('Highlight Pink')
        highlight_pink.default_color = default_prefs.highlight_pink
        highlight_pink.settings_key = 'pane/notebooks/export_pdf_highlightpinkink'
        self.set_color(highlight_pink, highlight_pink.default_color, from_settings=True)
        highlight_pink.triggered.connect(lambda: self.set_color(highlight_pink))

        # Highlight gray (firmware 2.12?)
        highlight_gray = menu.addAction('Highlight Gray')
        highlight_gray.default_color = default_prefs.highlight_gray
        highlight_gray.settings_key = 'pane/notebooks/export_graydf_highlightgrayink'
        self.set_color(highlight_gray, highlight_gray.default_color, from_settings=True)
        highlight_gray.triggered.connect(lambda: self.set_color(highlight_gray))

        # Reset colors
        def reset_menu_colors():
            for m in [black, gray, white, red, blue, highlight_yellow,
                      highlight_green, highlight_pink, highlight_gray]:
                self.set_color(m, m.default_color)
            # Hold the menu open only after we're done
            menu.parent().showMenu()
        reset_colors = menu.addAction('Reset Colors')
        reset_colors.triggered.connect(reset_menu_colors)

        def save_checked_state(action, state, showmenu=True):
            QSettings().setValue(action.settings_key, int(state))
            if showmenu:
                action.parent().parent().showMenu()

        # Super Resolution
        menu.addSeparator()
        hires = menu.addAction('High Density')
        hires.setCheckable(True)
        hires.settings_key = 'pane/notebooks/export_pdf_hires'
        try:
            hires_state = bool(int(QSettings().value(hires.settings_key)))
        except:
            hires_state = False
            save_checked_state(hires, hires_state, showmenu=False)
        hires.toggled.connect(lambda state:
                                 save_checked_state(hires, state))
        hires.setChecked(hires_state)

        # Layered PDFs
        ocg = menu.addAction('Layered PDF')
        ocg.setCheckable(True)
        ocg.settings_key = 'pane/notebooks/export_pdf_ocg'
        try:
            ocg_state = bool(int(QSettings().value(ocg.settings_key)))
        except:
            ocg_state = False
            save_checked_state(ocg, ocg_state, showmenu=False)
        ocg.toggled.connect(lambda state:
                            save_checked_state(ocg, state))
        ocg.setChecked(ocg_state)

        # Annotate PDFs
        # menu.addSeparator()
        annotate = menu.addAction('Annotated PDF')
        annotate.setCheckable(True)
        annotate.settings_key = 'pane/notebooks/export_pdf_annotate'
        try:
            annotate_state = bool(int(QSettings().value(annotate.settings_key)))
        except:
            annotate_state = False
            save_checked_state(annotate, annotate_state, showmenu=False)
        annotate.toggled.connect(lambda state:
                                 save_checked_state(annotate, state))
        annotate.setChecked(annotate_state)

        # Grouped Annotations
        grouped_annots = menu.addAction('Grouped Annotations')
        grouped_annots.setCheckable(True)
        grouped_annots.settings_key = 'pane/notebooks/export_pdf_grouped_annots'
        try:
            grouped_annots_state = bool(int(QSettings().value(grouped_annots.settings_key)))
        except:
            grouped_annots_state = False
            save_checked_state(grouped_annots, grouped_annots_state, showmenu=False)
        grouped_annots.toggled.connect(lambda state:
                                       save_checked_state(grouped_annots, state))
        grouped_annots.setChecked(grouped_annots_state)

        # Fallback to Web UI
        webui_fallback = menu.addAction('Web UI Fallback')
        webui_fallback.setCheckable(True)
        webui_fallback.settings_key = \
            'pane/notebooks/export_pdf_webui_fallback'
        try:
            webui_fallback_state = bool(int(QSettings().value(
                webui_fallback.settings_key)))
        except:
            webui_fallback_state = False
            save_checked_state(webui_fallback, webui_fallback_state,
                               showmenu=False)
        webui_fallback.toggled.connect(lambda state:
                            save_checked_state(webui_fallback, state))
        webui_fallback.setChecked(webui_fallback_state)

        # Open immediately
        opennow = menu.addAction('Open Immediately')
        opennow.setCheckable(True)
        opennow.settings_key = 'pane/notebooks/export_pdf_opennow'
        try:
            opennow_state = bool(int(QSettings().value(opennow.settings_key)))
        except:
            opennow_state = False
            save_checked_state(opennow, opennow_state, showmenu=False)
        opennow.toggled.connect(lambda state:
                            save_checked_state(opennow, state))
        opennow.setChecked(opennow_state)

        menu.addSeparator()
        
        # Export PDF actions
        # Choosing one of these sets the default renderer
        export_pdf_settings_key = 'pane/notebooks/export_pdf_default_renderer'
        default_etype = QSettings().value(export_pdf_settings_key) or 'pdf-rm'

        # Port old etypes from pre-2023.001dk
        if default_etype not in ['pdf-rm', 'pdf-b', 'pdf-v']:
            default_etype = 'pdf-rm'

        def save_renderer_and_export(action):
            QSettings().setValue(action.settings_key, action.settings_val)
            menu.setDefaultAction(action)
            self.notebook_controller.treewidget.export_items_to_disk(
                etype=action.settings_val)

        export_pdf_webui = menu.addAction('Export PDF (Web UI)')
        export_pdf_webui.settings_key = export_pdf_settings_key
        export_pdf_webui.settings_val = 'pdf-rm'
        export_pdf_webui.triggered.connect(
            lambda: save_renderer_and_export(export_pdf_webui))
        if export_pdf_webui.settings_val == default_etype:
            menu.setDefaultAction(export_pdf_webui)
        self.export_pdf_webui_action = export_pdf_webui

        export_pdf_bitmap = menu.addAction('Export PDF (Bitmap)')
        export_pdf_bitmap.settings_key = export_pdf_settings_key
        export_pdf_bitmap.settings_val = 'pdf-b'
        export_pdf_bitmap.triggered.connect(
            lambda: save_renderer_and_export(export_pdf_bitmap))
        if export_pdf_bitmap.settings_val == default_etype:
            menu.setDefaultAction(export_pdf_bitmap)

        export_pdf_vector = menu.addAction('Export PDF (Vector)')
        export_pdf_vector.settings_key = export_pdf_settings_key
        export_pdf_vector.settings_val = 'pdf-v'
        export_pdf_vector.triggered.connect(
            lambda: save_renderer_and_export(export_pdf_vector))
        if export_pdf_vector.settings_val == default_etype:
            menu.setDefaultAction(export_pdf_vector)

        return menu

    def update_view(self):
        # This gets bounced back from the model to load_items
        if not self.model.is_connected() or self.model.is_in_recovery:
            return
        if self.model.load_notebooks():
            self.load_items()
        if self.export_pdf_webui_action:
            if self.model.check_conf('WebInterfaceEnabled'):
                self.export_pdf_webui_action.setEnabled(True)
            else:
                self.export_pdf_webui_action.setEnabled(False)

    def change_category(self):
        # Filter the list of notebooks to the selected category
        self.change_category_recursive(
            self.notebook_controller.treewidget,
            self.categorycombo.currentText())

    def change_category_recursive(self, collectionitem, catname):
        # Search through a CollectionTreeWidgetItem and recursively set
        # the visibility of items for the category name. This also works
        # when passed a QTreeWidgetItem.
        catname = catname.lower()
        
        if type(collectionitem) is CollectionTreeWidgetItem:
            ccount = collectionitem.childCount()
            cfunc = collectionitem.child
        else:
            ccount = collectionitem.topLevelItemCount()
            cfunc = collectionitem.topLevelItem
        for i in range(0, ccount):
            item = cfunc(i)
            if type(item) is not DocumentTreeWidgetItem:
                self.change_category_recursive(item, catname)
                continue
            # DocumentTreeWidgetItem
            ftype = item.userData().get_filetype().lower()
            if catname == 'all' or catname == ftype:
                item.setHidden(False)
            else:
                item.setHidden(True)
        # # Hide the collection itself if there are no visible children
        # if type(collectionitem) is CollectionTreeWidgetItem:
        #     hasvisible = False
        #     for i in range(0, ccount):
        #         item = cfunc(i)
        #         if not item.isHidden():
        #             hasvisible = True
        #             break
        #     if not hasvisible:
        #         collectionitem.setHidden(True)
        #         return
        #     collectionitem.setHidden(False)
    
    def load_items(self):
        self.notebook_controller.load_all_items()
        self.notebook_controller.treewidget.setEnabled(True)
        self.window.category_comboBox.setEnabled(True)
        self.window.upload_pushButton.setEnabled(True)
        self.window.newcollection_pushButton.setEnabled(True)

    def set_download_buttons(self):
        if not self.notebook_controller.is_downloadable():
            self.window.downloaddocument_pushButton.setEnabled(False)
            self.window.exportpdf_pushButton.setEnabled(False)
            return
        self.window.downloaddocument_pushButton.setEnabled(True)
        self.window.exportpdf_pushButton.setEnabled(True)

    def check_for_reclaimed_storage(self):
        # Check for deleted items. These are logged intially in rcu.py,
        # but there is no logic there for handling them, other than
        # recording their presense as Collection/Document-type objects.
        # This SHOULD be a one-off function, since reMarkable needs to
        # fix this on their end. This function will be removed when they
        # do that.
        log.info('checking for deleted documents for reclaim storage')
        if len(self.model.deleted_items):
            mb = QMessageBox(self.window)
            mb.setWindowTitle('Reclaim Storage')
            mb.setText("There is a defect in reMarkable's software (2.6 and above) where documents aren't truly deleted until the tablet synchronizes with their cloud. Since you don't use their cloud, there are documents on your tablet that were marked for deletion, but never actually deleted.\n\nWould you like to permanently purge these documents and reclaim storage space?")
            di_names = []
            for di in self.model.deleted_items:
                di_names.append(di.visible_name)
            di_names.sort(key=lambda x: x.lower())
            mb.setDetailedText('\n'.join(di_names))
            mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
            mb.setDefaultButton(QMessageBox.No)
            ret = mb.exec()
            if int(QMessageBox.Yes) == ret:
                # go ahead and purge all those items
                log.info('purging items flagged for deletion')
                for di in self.model.deleted_items:
                    di.delete()
                self.model.restart_xochitl()

    def download_items(self):
        dlitems = self.notebook_controller.get_download_items()
        if not dlitems:
            return
        worker = Worker(fn=lambda progress_callback:
                        self.notebook_controller.download_items(
                            dlitems, progress_callback))
        self.threadpool.start(worker)
        worker.signals.finished.connect(
            lambda: self.set_ui_transmitting(False))
        worker.signals.progress.connect(
            lambda x: self.set_ui_transmitting(x))
        self.set_ui_transmitting(True)

    def abort_tx_items(self):
        self.notebook_controller.abort_transfer(True)
        self.window.abort_pushButton.setEnabled(False)
        self.window.save_progressBar.setEnabled(False)

    def upload_items(self, parent=None):
        ulitems = self.notebook_controller.get_upload_items()
        if not ulitems:
            return
        worker = Worker(fn=lambda progress_callback:
                        self.notebook_controller.save_ulitems(
                            ulitems, parent, progress_callback))
        self.threadpool.start(worker)
        worker.signals.finished.connect(
            lambda: self.set_ui_transmitting(False,
                                             reload_items=True))
        worker.signals.progress.connect(
            lambda x: self.set_ui_transmitting(x))

    def set_ui_transmitting(self, value, reload_items=False):
        if value is not False:
            self.window.actionbar_widget.hide()
            self.window.xmitbar_widget.show()
            try:
                self.window.save_progressBar.setValue(value)
            except:
                pass
        else:
            self.window.xmitbar_widget.hide()
            self.window.save_progressBar.setValue(0)
            self.window.actionbar_widget.show()
            self.window.abort_pushButton.setEnabled(True)
            self.window.save_progressBar.setEnabled(True)
            if reload_items:
                self.model.load_notebooks()

    def add_new_collection(self):
        c = Collection(self.model)
        prename = c.get_pretty_name()
        text, ok = QInputDialog().getText(
            self.window, 'New Folder', 'Name:',
            QLineEdit.Normal, prename)
        if ok:
            self.model.collections.add(c)
            c.rename(text)
            self.model.restart_xochitl()
            # return collection.rename(text)
        return False


import tarfile
import io
class NotebookController:
    def __init__(self, pane):
        self.pane = pane
        self.model = self.pane.model
        self.window = self.pane.window

        placeholder = self.window.tree_placeholderWidget
        new_tree = NotebookTreeWidget(self)
        self.window.displaypanelframe.replaceWidget(placeholder, new_tree)
        self.treewidget = new_tree
        self.allitems = set()
        self.abort_transfer_flag = False

        refresh1 = QShortcut('Ctrl+R', self.treewidget)
        refresh1.activated.connect(
            lambda: self.model.load_notebooks(force=True))
        refresh2 = QShortcut('F5', self.treewidget)
        refresh2.activated.connect(
            lambda: self.model.load_notebooks(force=True))
        # # This one apparently doesn't work anymore in Qt 5.15
        # refresh3 = QShortcut(QKeySequence.Refresh, self.treewidget)
        # refresh3.activated.connect(
        #     lambda: self.model.load_notebooks(force=True))

        rename = QShortcut('F2', self.treewidget)
        rename.activated.connect(
            lambda: self.rename_current_item())

        delete = QShortcut('Del', self.treewidget)
        delete.activated.connect(
            lambda: self.treewidget.delete_selected_items())

    def rename_current_item(self):
        if len(self.treewidget.selectedItems()) \
           and self.treewidget.currentItem().test_rename():
            self.treewidget.rename_selected_item()
            
    def load_all_items(self):
        # If there are any treewidget items that don't exist in the new
        # collections or documents, remove them.
        to_remove = set()
        
        for item in self.allitems:
            data = item.userData()
            og_parent = item.og_parent
            exists = False
            parent_changed = False
            if type(item) is CollectionTreeWidgetItem:
                for c in self.model.collections:
                    if c.uuid == data.uuid:
                        exists = True
                        if c.parent != og_parent:
                            parent_changed = True
                        break
            elif type(item) is DocumentTreeWidgetItem:
                for d in self.model.documents:
                    if d.uuid == data.uuid:
                        exists = True
                        if d.parent != og_parent:
                            parent_changed = True
                        break
            if not exists:
                # item will remove self from treewidget
                item.remove()
                # blacklist to not spawn again
                to_remove.add(item)
            if parent_changed:
                if 'trash' == og_parent:
                    # Can't remove from anywhere, do nothing. This might
                    # change if I implement a Trash collection.
                    pass
                else:
                    item.remove()
            # Reload treewidgetitem view contents
            item.update_from_data()

        for collection in self.model.collections:
            exists = False
            for item in self.allitems:
                if item.userData() is collection:
                    exists = True
                    break
            if not exists:
                citem = CollectionTreeWidgetItem(self)
                citem.setUserData(collection)
                self.allitems.add(citem)

        for document in self.model.documents:
            exists = False
            for item in self.allitems:
                if item.userData() is document:
                    exists = True
                    break
            if not exists:
                ditem = DocumentTreeWidgetItem(self)
                ditem.setUserData(document)
                self.allitems.add(ditem)

        # remove blacklisted
        for item in to_remove:
            self.allitems.remove(item)
            
        # make heirarchy
        for item in self.allitems:
            if not item.userData().parent:
                self.treewidget.addTopLevelItem(item)
                continue
            # skip trash items
            if 'trash' == item.userData().parent:
                continue
            # put into parent item
            noparent = True
            for i2 in self.allitems:
                if i2.userData().uuid == item.userData().parent \
                   and type(i2) is CollectionTreeWidgetItem:
                    i2.addChild(item)
                    noparent = False
                    break
                elif i2.userData().uuid == item.userData().parent:
                    log.error('cannot add child to non-collection type')
                    log.error('problem doc: {}'.format(item.userData().uuid))
                    break
            # there is a parent on-file, but that collection doesn't
            # exist. rM devices show this in the root collection.
            if noparent:
                self.treewidget.addTopLevelItem(item)
                continue
        # Re-sort
        self.treewidget.sortItems(*self.treewidget.sort_direction)

        # Sometimes, the UI fails to notice a change--repaint.
        self.treewidget.repaint()
        QTimer().singleShot(500, self.window.repaint)

    def is_downloadable(self):
        # Tests whether the currently-selected item is downloadable
        items = self.treewidget.selectedItems()
        if len(items):
            for item in items:
                if not item.test_export_pdf_bitmap() \
                   or not item.test_download_rmn():
                    return False
            return True
        return False

    # In function so works in async
    def abort_transfer(self, v=None):
        if v is True or v is False:
            self.abort_transfer_flag = v
            if v is True:
                log.info('aborting document transfer')
        return self.abort_transfer_flag

    def get_download_items(self):
        wtitle = 'Save Document'
        ftype = 'rM Documents'
        fext = '.rmn'
        return self.get_items_to_save(wtitle, ftype, fext)

    def get_items_to_save(self, wtitle, ftype, fext):
        # This is on its own so it won't divorce the thread
        # (download_items) from the GUI elements
        items = self.treewidget.selectedItems()

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/notebooks/last_export_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/notebooks/last_export_path',
                Path.home())
            default_savepath = Path.home()

        # Prune the item list. If a child and its parent are both
        # selected, then ignore the child.
        if len(items) > 1:
            newitems = []
            # Take out children
            for d in items:
                if type(d) is DocumentTreeWidgetItem:
                    # Look for its parent.
                    found = False
                    for c in items:
                        if c.userData().uuid == d.userData().parent:
                            found = True
                            break
                    if not found:
                        newitems.append(d)
                else:
                    # Really a collection; always carry.
                    newitems.append(d)
            items = newitems

        # Continue loading download items after sanitization.
        dlitems = []
        if len(items) == 1:
            # Select a file to save
            item = items[0]
            fname = item.userData().get_sanitized_filepath()
            # If this single item is a collection, use a directory
            # picker. Otherwise use file picker.
            d = QFileDialog()
            if type(item) is CollectionTreeWidgetItem:
                d.setFileMode(QFileDialog.AnyFile)
                filename = d.getSaveFileName(
                    self.window,
                    wtitle,
                    Path(default_savepath / fname).__str__())
            else:
                fname = str(fname) + fext  # append extension if not collection
                filename = d.getSaveFileName(
                    self.window,
                    wtitle,
                    Path(default_savepath / fname).__str__(),
                    '{} (*{})'.format(ftype, fext))
            if not filename[0] or filename[0] == '':
                return
            filepath = Path(filename[0])
            # What can we do if this fails?
            dlitems.append((item, filepath))
            # Save the last path directory for convenience
            QSettings().setValue(
                'pane/notebooks/last_export_path',
                filepath.parent)
        if len(items) > 1:
            # Pluralize
            if 's' != wtitle[-1]:
                wtitle += 's'
            else:
                wtitle += 'es'
            # Select a directory; gives files default names
            dirname = QFileDialog.getExistingDirectory(
                self.window,
                wtitle,
                str(default_savepath))
            if not dirname:
                return
            dirpath = Path(dirname)
            for item in items:
                if type(item) is CollectionTreeWidgetItem:
                    fname = item.userData().get_sanitized_filepath()
                else:
                    fname = item.userData().get_sanitized_filepath(fext)
                filepath = Path(dirpath / fname)
                dlitems.append((item, filepath))
            # Save the last path directory for convenience
            QSettings().setValue(
                'pane/notebooks/last_export_path',
                dirpath)
        return dlitems

    def export_items(self, items, progress_callback, etype):
        # This gets executed on its own thread.
        # items is an array of tuples, (item, to_filepath)

        # Use the total number of documents as the progress meter. It
        # would be even better to use the number of bytes processed,
        # but they each have their disadvantages. Using this for now
        # since it is easier.

        failed_docs = []
        docs_processed = 0
        num_docs = 0
        for d in items:
            if type(d[0]) is CollectionTreeWidgetItem:
                num_docs += d[0].userData().get_num_child_documents()
            else:
                num_docs += 1
        
        for i, d in enumerate(items):
            if self.abort_transfer():
                continue
            
            item = d[0]
            filepath = d[1]
            
            dat = item.userData()
            curprog = docs_processed / num_docs * 100

            def davemit(x):
                progress_callback.emit(curprog + (x / num_docs))

            try:
                if 'pdf-o' == etype:
                    docs_processed += dat.save_original_file(
                        filepath,
                        filetype='pdf',
                        prog_cb=davemit,
                        abort_func=self.abort_transfer) or 1
                elif 'epub-o' == etype:
                    docs_processed += dat.save_original_file(
                        filepath,
                        filetype='epub',
                        prog_cb=davemit,
                        abort_func=self.abort_transfer) or 1
                elif 'pdf-rm' == etype:
                    docs_processed += dat.save_rm_pdf(
                        filepath,
                        prog_cb=davemit,
                        abort_func=self.abort_transfer) or 1
                elif 'txt-md' == etype:
                    docs_processed += dat.save_text(
                        filepath,
                        prog_cb=davemit,
                        abort_func=self.abort_transfer) or 1
                elif 'snaphl-txt' == etype:
                    docs_processed += dat.save_snaphighlights(
                        filepath,
                        prog_cb=davemit,
                        abort_func=self.abort_transfer) or 1
                elif 'rmdoc-rm' == etype:
                    docs_processed += dat.save_rm_rmdoc(
                        filepath,
                        prog_cb=davemit,
                        abort_func=self.abort_transfer) or 1
                else:
                    if 'pdf-b' == etype:
                        save_func = lambda: dat.save_pdf(
                            filepath, vector=False, prog_cb=davemit,
                            abort_func=self.abort_transfer)
                    elif 'pdf-v' == etype:
                        save_func = lambda: dat.save_pdf(
                            filepath, vector=True, prog_cb=davemit,
                            abort_func=self.abort_transfer)
                    try:
                        docs_processed += save_func() or 1
                    except Exception as e:
                        # Don't lump password errors in with the webui
                        # fallback, otherwise the password condition
                        # cannot get recognized.
                        if type(e) is pikepdf.PasswordError:
                            raise e
                        webui_fallback = bool(int(QSettings().value(
                            'pane/notebooks/export_pdf_webui_fallback')))
                        if webui_fallback:
                            log.error('problem exporting document with rcu rendering; trying on-device rendering')
                            docs_processed += dat.save_rm_pdf(
                                filepath,
                                prog_cb=davemit,
                                abort_func=self.abort_transfer) or 1
                        else:
                            raise e

            except Exception as e:
                tbstr = ''
                log.error('hit exception exporting document', e)
                log.error('problematic document: {}'.\
                          format(dat.visible_name))
                if type(e) is not pikepdf.PasswordError:
                    tbstr = traceback.format_exc()
                    log.error(tbstr)
                log.info('adding failed doc')
                failed_docs.append((d, e, tbstr))
                # Do something to correct the progress meter?
                # ... TODO
                continue

            # Should we open it?
            open_me = bool(int(QSettings().value(
                'pane/notebooks/export_pdf_opennow')))
            # Don't open .rmdoc (.rmn is handled in download_items(), a
            # somewhat vestigial function)
            if 'rmdoc-rm' == etype:
                open_me = False
            if open_me and (True == open_me or 'true' == open_me):
                cmd = {
                    'FreeBSD': 'xdg-open "{}"'.format(filepath),
                    'Linux': 'xdg-open "{}"'.format(filepath),
                    'Darwin': 'open "{}"'.format(filepath),
                    'Windows': '{}'.format(filepath)
                }
                plat = platform.system()
                if 'Windows' == plat:
                    subprocess.run(['explorer.exe', cmd[plat]],
                                   stdin=None,
                                   stdout=None,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.DETACHED_PROCESS)
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
                    
        self.abort_transfer(False) # reset

        # Result: failed documents. Lets us give a messagebox notice.
        return failed_docs
        

    def download_items(self, data, progress_callback):
        # This gets executed on its own thread, hence why it's seperate
        # from get_download_items().
        # data is array of tuples, (item, save_filepath)
        
        # First we must estimate the size of all the files, to give a
        # good number back to the progress bar.
        est_totalbytes = 0
        problem_items = []
        for i in range(0, len(data)):
            d = data[i]
            estsizeb = d[0].userData().estimate_size(self.abort_transfer)
            if not estsizeb and not self.abort_transfer():
                problem_items.append(i)
                continue
            # Append the estimated size to the data tuple
            data[i] = d + (estsizeb,)
            est_totalbytes += estsizeb

        # Remove problem items
        for i in problem_items:
            data.pop(i)
        # todo: maybe show a message about the problem items?

        # After size estimation, perform the actual dump
        btransferred = 0
        for d in data:
            # What to do if a tranfer fails?
            try:
                filepath = d[1]
                est_bytes = d[2]
                btransferred += d[0].userData().save_archive(
                    filepath, est_bytes, lambda bcount:
                    progress_callback.emit(
                        (btransferred + bcount) / est_totalbytes * 100),
                    self.abort_transfer)
            except Exception as e:
                log.error('hit exception downloading document archive:',
                          e)
        progress_callback.emit(100)
        self.abort_transfer(False) # reset

    def get_upload_items(self):
        # Select the .rmn files for upload

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/notebooks/last_import_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/notebooks/last_import_path',
                Path.home())
            default_savepath = Path.home()
        
        filenames = QFileDialog.getOpenFileNames(
            self.window,
            'Upload Documents',
            str(default_savepath),
            'rM Documents (*.rmn *.pdf *.epub *.RMN *.PDF *.EPUB)')
        if not filenames[0] or not len(filenames[0]):
            return False
        paths = []
        for s in filenames[0]:
            paths.append(Path(s))
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/notebooks/last_import_path',
            paths[0].parent)
        return paths

    def save_ulitems(self, ulitempaths, parent, progress_callback):
        # Extracts .rmn tar files to device
        # Go through to get total transmit size
        txsize = 0
        for filepath in ulitempaths:
            txsize += filepath.stat().st_size
        txbytes = 0
        
        for filepath in ulitempaths:
            dummydoc = Document(self.model)
            upload_func = dummydoc.upload_archive
            if '.rmn' != filepath.suffix:
                upload_func = dummydoc.upload_file
            
            txbytes = upload_func(
                filepath,
                parent,
                lambda x: progress_callback.emit((txbytes + x) / txsize * 100),
                self.abort_transfer)
            
            if self.abort_transfer():
                # cleanup is handled in upload_func
                break

        # Notebooks are reloaded by the pane class in the
        # ui_transmitting method

        self.model.restart_xochitl()
        self.abort_transfer(False) # reset

    def delete_notebook_by_id(self, idstring):
        for document in self.model.documents:
            if document.uuid == idstring:
                document.delete()
                for item in self.allitems:
                    if item.userData() is document:
                        self.allitems.discard(item)
                        break
                break
        # What could we even do if it failed to delete?
        self.model.restart_xochitl()

        
        
class NotebookTreeWidget(QTreeWidget):
    def __init__(self, controller, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.controller = controller

        self.setEnabled(False)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self.open_menu)

        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, 'Name')
        __qtreewidgetitem.setText(1, 'Mod. Date')
        __qtreewidgetitem.setText(2, 'ID')
        __qtreewidgetitem.setText(3, '')
        self.setHeaderItem(__qtreewidgetitem)

        self.setObjectName('notebooks_treeWidget')
        # self.setGeometry(QRect(10, 40, 461, 361))
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setEditTriggers(
            QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        #self.setSelectionBehavior(
        #    QAbstractItemView.SelectRows)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setAllColumnsShowFocus(True)
        self.header().setVisible(True)
        self.header().setSectionHidden(2, True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(QHeaderView.Stretch)
        self.header().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)

        sizePolicy2 = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(sizePolicy2)

        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setProperty("showDropIndicator", True)

        # # Platform-specific stuff
        # plat = platform.system()
        # if 'Windows' == plat:
        #     self.setAlternatingRowColors(False)
        # else:
        #     self.setAlternatingRowColors(True)
        self.setAlternatingRowColors(True)
        # Windows shows the default differently, so be explicit
        #self.setStyleSheet('alternate-background-color: #f9f9f9;')

        self.header().sortIndicatorChanged.connect(
            self.handle_sort_direction)

        self.itemExpanded.connect(lambda item: item.triggerExpanded())
        self.itemCollapsed.connect(lambda item: item.triggerExpanded())

        self.pressed.connect(lambda: self.controller.pane.set_download_buttons())

        # Keep track of sort direction to sticky collections at top
        self.sort_direction = (0, Qt.SortOrder.AscendingOrder)
        test_sd = QSettings().value('pane/notebooks/sort_direction')
        if test_sd:
            self.sort_direction = test_sd
        #self.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.sortItems(*self.sort_direction)

    def dropEvent(self, event):
        di_pos = self.dropIndicatorPosition()
        item = self.itemAt(event.pos())

        if QAbstractItemView.AboveItem == di_pos:
            target_item = item.parent()
        if QAbstractItemView.BelowItem == di_pos:
            target_item = item.parent()
        if QAbstractItemView.OnItem == di_pos:
            target_item = item
        if QAbstractItemView.OnViewport == di_pos:
            target_item = None

        parent_model = None
        if target_item:
            parent_model = target_item.userData()

        something_changed = False
        for widget_item in self.selectedItems():
            ret = widget_item.userData().move_to_parent(parent_model)
            if ret:
                something_changed = True

        if something_changed:
            self.controller.model.restart_xochitl()

        return super(type(self), self).dropEvent(event)

    def handle_sort_direction(self, column, order):
        self.sort_direction = (column, order)
        QSettings().setValue('pane/notebooks/sort_direction',
                             self.sort_direction)

    def open_menu(self, position):
        # This used to be based on particular items, but I am now
        # migrating it to be more-global, so different kind of file
        # operations may happen.

        # Get the item under the position. If it is a Collection,
        # deselect all non-collections.

        menu = QMenu()
        
        items = self.selectedItems()

        can_upload_here = True
        can_new_subcollection = True
        can_exp_pdf_rm = True
        can_exp_pdf_bitmap = True
        can_exp_pdf_vector = True
        can_exp_pdf_original = True
        can_exp_epub_original = True
        can_exp_text_md = True
        can_exp_rmdoc_rm = True
        can_rename = True
        can_delete = True
        can_pin = True
        can_unpin = True
        for item in items:
            # Once it's set to False, it can't change again
            if can_upload_here:
                can_upload_here = item.test_can_upload_here()
            if can_new_subcollection:
                can_new_subcollection = item.test_new_subcollection()
            if can_exp_pdf_rm:
                can_exp_pdf_rm = item.test_export_pdf_rm()
            if can_exp_pdf_bitmap:
                can_exp_pdf_bitmap = item.test_export_pdf_bitmap()
            if can_exp_pdf_vector:
                can_exp_pdf_vector = item.test_export_pdf_vector()
            if can_exp_pdf_original:
                can_exp_pdf_original = item.test_export_pdf_original()
            if can_exp_epub_original:
                can_exp_epub_original = item.test_export_epub_original()
            if can_exp_text_md:
                can_exp_text_md = item.test_export_text_markdown()
            if can_exp_rmdoc_rm:
                can_exp_rmdoc_rm = item.test_export_rmdoc_rm()
            if can_rename:
                can_rename = item.test_rename()
            if can_delete:
                can_delete = item.test_delete()
            if can_pin:
                can_pin = item.test_pin()
            if can_unpin:
                can_unpin = item.test_unpin()

        if can_new_subcollection or can_upload_here:
            if len(items) == 1:
                if can_new_subcollection:
                    new_subcollection = menu.addAction('New sub-folder')
                    new_subcollection.triggered.connect(self.new_subcollection)
                if can_upload_here:
                    upload_here = menu.addAction('Upload here')
                    upload_here.triggered.connect(self.upload_to_collection)
                menu.addSeparator()

        if can_exp_pdf_bitmap or can_exp_pdf_vector \
           or can_exp_pdf_original or can_exp_pdf_rm:
            export_sub = menu.addMenu('Export')
            
            # if can_exp_pdf_rm:
            export_pdf_rm = export_sub.addAction('Export PDF (Web UI)')
            export_pdf_rm.triggered.connect(
                lambda: self.export_items_to_disk(etype='pdf-rm'))
            if not can_exp_pdf_rm:
                export_pdf_rm.setEnabled(False)
            
            if can_exp_pdf_bitmap:
                export_pdf_b = export_sub.addAction('Export PDF (Bitmap)')
                export_pdf_b.triggered.connect(
                    lambda: self.export_items_to_disk(etype='pdf-b'))
            if can_exp_pdf_vector:
                export_pdf_v = export_sub.addAction('Export PDF (Vector)')
                export_pdf_v.triggered.connect(
                    lambda: self.export_items_to_disk(etype='pdf-v'))

            #######################
            ## TEXT EXPORT TYPES ##
            export_sub.addSeparator()
            if can_exp_text_md:
                export_text_md = export_sub.addAction('Export Typed Text (Markdown)')
                export_text_md.triggered.connect(
                    lambda: self.export_items_to_disk(etype='txt-md'))
            # Snap highlights can exist in any kind of doc.
            export_snaphl_txt = export_sub.addAction('Export Snap Highlights (Text)')
            export_snaphl_txt.triggered.connect(
                lambda: self.export_items_to_disk(etype='snaphl-txt'))
            export_sub.addSeparator()
            #######################

            if can_exp_pdf_original:
                export_pdf_o = export_sub.addAction('Download Original Base PDF')
                export_pdf_o.triggered.connect(
                    lambda: self.export_items_to_disk(etype='pdf-o'))

            if can_exp_epub_original:
                export_epub_o = export_sub.addAction('Download Original Base Epub')
                export_epub_o.triggered.connect(
                    lambda: self.export_items_to_disk(etype='epub-o'))

            export_rmdoc_rm = export_sub.addAction('Download RMDOC (Web UI)')
            export_rmdoc_rm.triggered.connect(
                lambda: self.export_items_to_disk(etype='rmdoc-rm'))
            if not can_exp_rmdoc_rm:
                export_rmdoc_rm.setEnabled(False)

        if len(items) == 1 and can_rename:
            rename = menu.addAction('Rename')
            rename.triggered.connect(self.rename_selected_item)

        if can_pin:
            pin = menu.addAction('Favorite')
            pin.triggered.connect(self.pin_selected_items)

        if can_unpin:
            unpin = menu.addAction('Un-favorite')
            unpin.triggered.connect(self.unpin_selected_items)

        if can_delete:
            menu.addSeparator()
            delete = menu.addAction('Delete')
            delete.triggered.connect(self.delete_selected_items)

        menu.exec_(self.viewport().mapToGlobal(position))

    def upload_to_collection(self):
        # Uploads a document to the currently-selected Collection.
        item = self.selectedItems()[0]
        self.controller.pane.upload_items(item.userData())

    def new_subcollection(self):
        item = self.selectedItems()[0]
        item.new_subcollection() \
            and self.controller.model.restart_xochitl()
        

    def rename_selected_item(self):
        item = self.selectedItems()[0]
        item.rename() and self.controller.model.restart_xochitl()

    def delete_selected_items(self):
        # Deletes all the selected items.
        items = self.selectedItems()

        # Warn the user
        wtitle = 'Delete'
        wmsg = 'Do you want to permanently delete this?'
        if len(items) > 1:
            wmsg = 'Do you want to permanently delete these?'

        wdetail = []
        for item in items:
            wdetail.append(item.userData().visible_name)
        wdetail = '\n'.join(wdetail)
        
        mb = QMessageBox(self.controller.window)
        mb.setWindowTitle(wtitle)
        mb.setText(wmsg)
        mb.setDetailedText(wdetail)
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.No)
        ret = mb.exec()
        if int(QMessageBox.Yes) != ret:
            return
        
        for item in items:
            item.delete()
        self.controller.model.restart_xochitl()

    def pin_selected_items(self):
        items = self.selectedItems()
        for item in items:
            item.pin()
        # re-sorting seems necessary to prevent graphical glitch
        self.sortItems(*self.sort_direction)
        self.controller.model.restart_xochitl()

    def unpin_selected_items(self):
        items = self.selectedItems()
        for item in items:
            item.unpin()
        # re-sorting seems necessary to prevent graphical glitch
        self.sortItems(*self.sort_direction)
        self.controller.model.restart_xochitl()

    def export_items_to_disk(self, etype, items=None):
        # This is the master function for exporting GUI-selected items
        # to disk. Various parameters are used to handle how file
        # selectors are titled/displayed.
        #
        # If no items are specified, whatever is selected in the GUI
        # will be used.

        failed_items = []
        if not items:
            if 'pdf-rm' == etype:
                items = self.controller.get_items_to_save(
                    'Export PDF', 'PDFs', '.pdf')
            elif 'pdf-b' == etype:
                items = self.controller.get_items_to_save(
                    'Export PDF', 'PDFs', '.pdf')
            elif 'pdf-v' == etype:
                items = self.controller.get_items_to_save(
                    'Export PDF', 'PDFs', '.pdf')
            elif 'pdf-o' == etype:
                items = self.controller.get_items_to_save(
                    'Export PDF', 'PDFs', '.pdf')
            elif 'epub-o' == etype:
                items = self.controller.get_items_to_save(
                    'Export Epub', 'Epubs', '.epub')
            elif 'txt-md' == etype:
                items = self.controller.get_items_to_save(
                    'Export Markdown', 'Markdown Files', '.md')
            elif 'snaphl-txt' == etype:
                items = self.controller.get_items_to_save(
                    'Export Text', 'Text Files', '.txt')
            elif 'rmdoc-rm' == etype:
                items = self.controller.get_items_to_save(
                    'Export RMDOC', 'RMDOC Files', '.rmdoc')

        if not items or not len(items):
            log.error('no export items given; aborting')
            return

        worker = Worker(fn=lambda progress_callback:
                        self.controller.export_items(
                            items, progress_callback,
                            etype=etype))
        self.controller.pane.threadpool.start(worker)
        worker.signals.finished.connect(
            lambda: self.controller.pane.set_ui_transmitting(False))
        worker.signals.progress.connect(
            lambda x: self.controller.pane.set_ui_transmitting(x))
        worker.signals.result.connect(
            lambda result: self.alert_on_failed_items(result, etype))
        self.controller.pane.set_ui_transmitting(True)

    def alert_on_failed_items(self, result, etype):
        # If there were failed documents, tell the user about them and
        # give them the exception.
        # 'result' will return as [(doc, exception, traceback), ...].
        if 0 >= len(result):
            return

        # Some export failures may have been due to requiring a PDF
        # password. Try asking for those, and if they still fail, then
        # abandon.

        password_docs = []
        
        for d, e, t in result:
            if type(e) is pikepdf.PasswordError:
                password, ok = QInputDialog().getText(
                    self.controller.window, 'Password Required',
                    'A password is required to decode "{}".'.format(
                        d[0].userData().get_pretty_name()),
                    QLineEdit.Password)
                if ok:
                    d[0].userData()._pdf_password = password
                    password_docs.append(d)

        if len(password_docs):
            # Set password on internal memory, try exporting them again.
            # The password is cleared when the document exports.
            self.export_items_to_disk(etype=etype,
                                      items=password_docs)
            return

        mb = QMessageBox(self.controller.window)
        mb.setWindowTitle('Export Failure')

        details = ''
        # dstring = traceback.print_tb(e.__traceback__)
        for d, e, t in result:
            dw, dest = d
            dstring = '{}: ({})'.format(dw.userData().visible_name,
                                        str(t))
            details += dstring + '\n'
        mb.setDetailedText(details)

        # What text to describe the issue?
        msg_text = 'Some documents were not able to be exported.'
        if 'Connection refused' in details:
            msg_text += ' An attempt was made to use the Web UI, but it seems not to be enabled on the tablet.'
        else:
            msg_text += ' Try using the "Web UI Fallback" export option, under the Export PDF menu.'
        msg_text += '\n\nA log is provided below, which may be useful to diagnose the issue.'
        mb.setText(msg_text)
        mb.exec()



        
class CollectionTreeWidgetItem(QTreeWidgetItem):
    def __init__(self, controller, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.controller = controller
        
        icon = QIcon()
        ipathstr = str(Path(NotebooksPane.bdir / 'icons' / 'folder.png'))
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        self.setIcon(0, icon)

        self.setFlags(self.flags() | Qt.ItemIsDropEnabled)
        
    def setUserData(self, userData=None):
        self._userData = userData
        self.update_from_data()
        
    def userData(self):
        return self._userData

    def update_from_data(self):
        userData = self.userData()
        self.setData(0, 0, userData.visible_name)
        self.setData(1, 0, '')
        self.setData(2, 0, userData.uuid)
        self.setData(3, 0, '\u2605' if userData.pinned else '')
        self.og_parent = userData.parent
                
    def triggerExpanded(self):
        if self.isExpanded():
            icon = QIcon()
            ipathstr = str(Path(NotebooksPane.bdir / 'icons' / 'folder-open.png'))
            icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
            self.setIcon(0, icon)
            # disable selection, as to not interfere with export actions
            # self.setFlags(self.flags() & ~Qt.ItemIsSelectable)
        else:
            icon = QIcon()
            ipathstr = str(Path(NotebooksPane.bdir / 'icons' / 'folder.png'))
            icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
            self.setIcon(0, icon)
            # enable selection
            # self.setFlags(self.flags() | Qt.ItemIsSelectable)
        # update ui download buttons (seem not to be triggered with
        # 'pressed' event on NotebookTreeWidget)
        self.controller.pane.set_download_buttons()
            
    def __lt__(self, other):
        tw = self.treeWidget()
        if not tw:
            return False

        sort_direction = tw.header().sortIndicatorOrder()
        flip = False
        if sort_direction == Qt.SortOrder.DescendingOrder:
            flip = True

        # don't compare to documents
        if type(other) is not type(self):
            return True ^ flip

        # starred come first
        if self.userData().pinned and not other.userData().pinned:
            return True ^ flip
        if not self.userData().pinned and other.userData().pinned:
            return False ^ flip

        sortcol = tw.sortColumn()
        if 0 == sortcol:
            return self.name_sort(other)
        else:
            return self.name_sort(other) ^ flip

    def remove(self):
        # Removes this item from the tree widget, and all its children.
        # If the item was in the trash, then it may not be displayed (so
        # try/catch).
        try:
            for i in range(0, self.childCount()):
                item = self.child(i)
                item.remove()
            if self.parent():
                self.parent().removeChild(self)
            else:
                i = self.treeWidget().indexOfTopLevelItem(self)
                self.treeWidget().takeTopLevelItem(i)
        except:
            pass
    
    def name_sort(self, other):
        # If the names are equal, sort based on the number of contents
        a = self.text(0).lower()
        b = other.text(0).lower()

        if a == b:
            return self.childCount() < other.childCount()
        return a < b
    
    def get_children(self):
        alist = []
        for i in range(0, self.childCount()):
            alist.append(self.child(i))
        return alist

    ## Shared funcs
    def test_download_rmn(self):
        return True
    
    def test_export_pdf_bitmap(self):
        can = True
        for c in self.get_children():
            if not c.test_export_pdf_bitmap():
                can = False
                break
        return can

    def test_export_pdf_vector(self):
        can = True
        for c in self.get_children():
            if not c.test_export_pdf_vector():
                can = False
                break
        return can

    def test_export_pdf_original(self):
        can = True
        for c in self.get_children():
            if not c.test_export_pdf_original():
                can = False
                break
        return can

    def test_export_epub_original(self):
        can = True
        for c in self.get_children():
            if not c.test_export_epub_original():
                can = False
                break
        return can

    def test_export_pdf_rm(self):
        can = True
        for c in self.get_children():
            if not c.test_export_pdf_rm():
                can = False
                break
        return can

    def test_export_rmdoc_rm(self):
        can = True
        for c in self.get_children():
            if not c.test_export_rmdoc_rm():
                can = False
                break
        return can

    def test_export_text_markdown(self):
        can = True
        for c in self.get_children():
            if not c.test_export_text_markdown():
                can = False
                break
        return can

    def test_delete(self):
        can = True
        for c in self.get_children():
            if not c.test_delete():
                can = False
                break
        return can

    def test_can_upload_here(self):
        return True

    def test_rename(self):
        return True

    def test_new_subcollection(self):
        return True

    def test_pin(self):
        return not self.userData().get_pin()

    def test_unpin(self):
        return self.userData().get_pin()
    
    def delete(self):
        # Delete all the children, then delete the self.
        for c in self.get_children():
            c.delete()
        self.remove()
        self.userData().delete()
        self.controller.allitems.discard(self)

    def rename(self):
        # Opens a dialog to rename this item.
        collection = self.userData()
        loadname = collection.visible_name
        text, ok = QInputDialog().getText(
            self.controller.window, 'Rename Collection', 'New Name:',
            QLineEdit.Normal, loadname)
        if ok:
            self.setText(0, text)
            return collection.rename(text)
        return False

    def pin(self):
        self.setData(3, 0, '\u2605')
        self.userData().pin()

    def unpin(self):
        self.setData(3, 0, '')
        self.userData().unpin()

    def new_subcollection(self):
        # Creates a new collection and adds it under this item
        collection = Collection(self.controller.model)
        collection.parent = self.userData().uuid
        loadname = collection.visible_name
        text, ok = QInputDialog().getText(
            self.controller.window, 'New Folder', 'Name:',
            QLineEdit.Normal, loadname)
        if ok:
            self.controller.model.collections.add(collection)
            return collection.rename(text)
        return False

    
from PySide2.QtWidgets import QMenu, QAction, QMessageBox
class DocumentTreeWidgetItem(QTreeWidgetItem):
    def __init__(self, controller, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.controller = controller

        icon = QIcon()
        ipathstr = str(Path(NotebooksPane.bdir / 'icons' / 'text-x-generic.png'))
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        self.setIcon(0, icon)

        self.setFlags(self.flags() & ~Qt.ItemIsDropEnabled)
        
    def setUserData(self, userData):
        self._userData = userData
        self.update_from_data()
            
    def userData(self):
        return self._userData

    def update_from_data(self):
        userData = self.userData()
        self.setData(0, 0, userData.visible_name)
        pdate = prettydate(userData.get_last_modified_date())
        self.setData(1, 0, pdate)
        self.setData(2, 0, userData.uuid)
        self.setData(3, 0, '\u2605' if userData.pinned else '')
        self.og_parent = userData.parent
        if 'pdf' == userData.get_filetype():
            icon = QIcon()
            ipathstr = str(Path(NotebooksPane.bdir / 'icons' / 'application-pdf.png'))
            icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
            self.setIcon(0, icon)
        elif 'epub' == userData.get_filetype():
            icon = QIcon()
            ipathstr = str(Path(NotebooksPane.bdir / 'icons' / 'font-x-generic.png'))
            icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
            self.setIcon(0, icon)
    
    def __lt__(self, other):
        tw = self.treeWidget()
        if not tw:
            return False

        sort_direction = tw.header().sortIndicatorOrder()
        flip = False
        if sort_direction == Qt.SortOrder.DescendingOrder:
            flip = True
        
        # don't compare to collections
        if type(other) is not type(self):
            return False ^ flip

        # starred come first
        if self.userData().pinned and not other.userData().pinned:
            return True ^ flip
        if not self.userData().pinned and other.userData().pinned:
            return False ^ flip
        
        sortcol = tw.sortColumn()
        if sortcol == 0:
            return self.name_sort(other)
        if sortcol == 1:
            # by date, really use raw timestamp
            thists = self.userData().last_modified
            thatts = other.userData().last_modified
            return int(thists) < int(thatts)
        return False

    def remove(self):
        # Remove this widgetitem from the treewidget. If the item was
        # in the trash, then it may not be displayed (so try/catch).
        try:
            if self.parent():
                self.parent().removeChild(self)
            else:
                i = self.treeWidget().indexOfTopLevelItem(self)
                self.treeWidget().takeTopLevelItem(i)
        except:
            pass
    
    def name_sort(self, other):
        return self.text(0).lower() < other.text(0).lower()
    
    ## Private (single-selection)
    def rename(self):
        # Opens a dialog to rename this item.
        document = self.userData()
        loadname = document.visible_name
        text, ok = QInputDialog().getText(
            self.controller.window, 'Rename Document', 'New Name:',
            QLineEdit.Normal, loadname)
        if ok:
            self.setText(0, text)
            return document.rename(text)
        return False

    ## Shared (multi-selection)
    def test_download_rmn(self):
        return True
    
    def test_export_pdf_bitmap(self):
        return True

    def test_export_pdf_vector(self):
        return True

    def test_export_pdf_original(self):
        if 'pdf' == self.userData().get_filetype() \
           or 'epub' == self.userData().get_filetype():
            return True
        return False

    def test_export_epub_original(self):
        if 'epub' == self.userData().get_filetype():
            return True
        return False

    def test_export_pdf_rm(self):
        return self.controller.model.check_conf('WebInterfaceEnabled')

    def test_export_rmdoc_rm(self):
        ret = True
        if not self.controller.model.is_gt_eq_xochitl_version('3.10'):
            ret = False
        if not self.controller.model.check_conf('WebInterfaceEnabled'):
            ret = False
        return ret

    def test_export_text_markdown(self):
        ft = self.userData().get_filetype()
        if 'pdf' != ft and 'epub' != ft:
            return True

    def test_delete(self):
        return True

    def test_can_upload_here(self):
        return False

    def test_rename(self):
        return True

    def test_new_subcollection(self):
        return False

    def test_pin(self):
        return not self.userData().get_pin()

    def test_unpin(self):
        return self.userData().get_pin()
    
    def delete(self):
        # Removes files from device, deletes self from treewidget
        self.remove()
        self.userData().delete()
        self.controller.allitems.discard(self)

    def pin(self):
        self.setData(3, 0, '\u2605')
        self.userData().pin()

    def unpin(self):
        self.setData(3, 0, '')
        self.userData().unpin()
