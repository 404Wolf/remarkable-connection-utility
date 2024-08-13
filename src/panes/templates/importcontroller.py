'''
importcontroller.py
This is the controller for the New Template import window. This
appears when a user tries to upload a PNG or SVG.

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

from controllers import UIController
from pathlib import Path
import log

from PySide2.QtCore import QByteArray, QSize, Qt, QTimer, QBuffer, \
    QIODevice, QCoreApplication
from PySide2.QtGui import QFontDatabase, QPixmap, QIcon, QImage, QMatrix
from PySide2.QtWidgets import QListWidgetItem, QMessageBox

from PIL import Image, ImageFont, ImageDraw, ImageOps

import tempfile
import os
import io
import tempfile

from worker import Worker
import svgtools

from model.template import Template


def get_square_box(box):
    # Given a 4-element tuple (box), get the coordinates to crop it into
    # a centered square.
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    cx = x1 + (width / 2)
    cy = y1 + (height / 2)
    # Max side becomes square length
    maxside = width if width > height else height
    # New bounding box
    left = cx - (maxside / 2)
    right = cx + (maxside / 2)
    top = cy - (maxside / 2)
    bottom = cy + (maxside / 2)
    return (left, top, right, bottom)


class TemplateImporter:
    def __init__(self, pane):
        self.pane = pane
        self.model = pane.model
        
        # Stores a cache of icons used by the TemplateImporterDialog
        self.icons = {}
        self.icons_loaded = False

        if not QCoreApplication.args.cli:
            # Run caching operation in background
            self.fill_icon_cache_in_background()

    def fill_icon_cache_in_background(self):
        log.info('fill icon cache')
        worker = Worker(fn=lambda progress_callback:
                        self.pull_device_template_icons())
        self.pane.threadpool.start(worker)

    def get_cached_font_path(self):
        share_dir = QCoreApplication.sharePath
        xochitl_ver = self.model.device_info['osver']
        cfname = 'template-iconfont_xochitl-{}.ttf'.format(xochitl_ver)
        cached_font_path = Path(share_dir / cfname)
        return cached_font_path

    def delete_cached_ttf_font(self):
        cached_font_path = self.get_cached_font_path()
        if cached_font_path.exists():
            log.info('deleting cached iconfont')
            cached_font_path.unlink()

    def get_cached_ttf_font(self):
        # Does it exist in the cache? If not, get it from the device.
        cached_font_path = self.get_cached_font_path()

        # Does this file exist? If not, pull it from the device.
        if cached_font_path.exists():
            ttf_font = None
            with open(cached_font_path, 'rb') as f:
                ttf_font = io.BytesIO(f.read())
                f.close()
            log.info('using cached iconfont')
            return ttf_font

        # This will download and save the .ttf icon font that is
        # embedded within Xochitl. Since ripping this font takes
        # a few seconds, it is better for user experience if we
        # cache it.
        ttf_font = self._get_ttf_font_from_device()

        # cache it
        with open(cached_font_path, 'wb') as f:
            f.write(ttf_font.read())
            f.close()
        ttf_font.seek(0)

        return ttf_font

    def pull_device_template_icons(self):
        # This is the main procedure for loading icon fonts into
        # the icon cache. This happens in a Worker thread, and
        # this cache dictionary is later polled by the main thread.
        ttf_font = self.get_cached_ttf_font()

        # Get all the glyphs used in existing templates
        t_path = '/usr/share/remarkable/templates/templates.json'
        cmd = 'cat "{}"'.format(t_path)
        cmd += ''' | grep iconCode | sort | uniq \
                   | awk -F'"' '{print $4}' \
                   | tr -d 'u' | tr -d '\\' '''
        out, err = self.model.run_cmd(cmd)
        if err:
            log.error('error getting template icon codes')
            log.error(err)
            return
        icon_codes_s = out.strip().splitlines()

        # Reset cache
        self.icons = {}
        try:
            font = ImageFont.truetype(ttf_font, 256)
        except:
            self.delete_cached_ttf_font()
            return

        # Sanitize the codes into normal strings, so they can be
        # worked with and used as keys in the cache. eInkPads
        # screws the templates.json by writing raw, unescaped
        # unicode into the file, breaking the manufacturer's
        # consistency.
        for c, code in enumerate(icon_codes_s):
            if 1 == len(code):
                # got an unescaped code
                icon_codes_s[c] = code.encode('raw_unicode_escape')[-4:].decode('utf-8')

        for code in icon_codes_s:
            # Skip codes that are already in the cache (duplicates).
            # This could happen if there is a combo of escaped and
            # unescaped codes.
            if code in self.icons:
                continue
            
            # Wrap this all up in a try/except block so we can skip
            # problematic icon codes entirely.
            try:
                u_code = chr(int(code, 16))
                im = Image.new('RGB', (600, 600))
                draw = ImageDraw.Draw(im)
                draw.fontmode = '1'  # aliased
                draw.text((100, 100), u_code, font=font)
                # crop to square
                #im = im.crop(get_square_box(im.getbbox()))
                box = im.getbbox()
                if not box:
                    log.error('no box for {}'.format(code))
                    # Invalidate the cached iconfont if it is not
                    # perfect. This will make RCU slower to load, but
                    # will also fix issues of people who's RCU instances
                    # have the wrong font cached.
                    self.delete_cached_ttf_font()
                    continue
                landscape = False
                if box[2] - box[0] > box[3] - box[1]:
                    landscape = True
                im = im.crop(box)
                im = ImageOps.invert(im)
                im = im.convert('1')
                imgdataio = io.BytesIO()
                im.save(imgdataio, format='PNG')
                imgdataio.seek(0)

                # Convert to icon
                pxmap = QPixmap()
                pxmap.loadFromData(imgdataio.read())
                icon = QIcon()
                icon.addPixmap(pxmap)

                # Cache
                self.icons[code] = (icon, landscape)
            except:
                log.error('problem parsing template icon code; skipping.', code)
                self.delete_cached_ttf_font()
                continue

        self.icons_loaded = True
        log.info('template icons finished loading')

    def upload_template(self, filepath):
        # This method handles all template imports. It is activated
        # by the Template Pane controller.
        if '.rmt' == filepath.suffix:
            return self._upload_rmt(filepath)
        elif '.svg' == filepath.suffix:
            return self._upload_svg(filepath)
        elif '.png' == filepath.suffix:
            return self._upload_png(filepath)

    def _upload_rmt(self, filepath):
        # If this is a .rmn, make the new template directly
        template = self.model.add_new_template_from_archive(
            filepath)
        template.install_to_device()
        self.pane.templates_controller.add_template_tree_item(template)
        self.pane.templates_controller.change_category()
        self.model.restart_xochitl()

    def _upload_svg(self, filepath,
                    filename=None):
        if type(filepath) is bytes:
            svgdata = filepath
        else:
            with open(filepath, 'rb') as f:
                svgdata = f.read()
                f.close()

        svgsize = svgtools.svg_get_size(svgdata)

        if svgsize is None:
            mb = QMessageBox(self.pane.window)
            mb.setWindowTitle('Template Error')
            mb.setText('There was a problem with this template: its dimensions could not be determined. If this was an SVG file, is it valid and in the SVG Tiny 1.2 spec?')
            mb.setStandardButtons(QMessageBox.Ok)
            mb.setDefaultButton(QMessageBox.Ok)
            mb.exec()
            return

        # If the size doesn't match the display, give the user a
        # warning (but let them proceed if they want).
        dwidth, dheight = type(self.model.display).portrait_size
        # quick and dirty check
        if dwidth + dheight != svgsize[0] + svgsize[1]:
            mb = QMessageBox(self.pane.window)
            mb.setWindowTitle('Check Template Size')
            mb.setText('The template does not match the display resolution, which is {}x{} pixels. Continue anyway?'.format(dwidth, dheight))
            mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
            mb.setDefaultButton(QMessageBox.No)
            ret = mb.exec()
            if ret == int(QMessageBox.No):
                # abort upload
                return

        # Check orientation of SVG based. This is used to pre-load the
        # orientation combo box.
        ar = svgsize[0] / svgsize[1]  # width / height
        is_landscape = True if ar > 1 else False

        impdiag = TemplateImporterDialog(self,
                                         name=filename or filepath.stem,
                                         landscape=is_landscape)
        
        # Center New Template dialog window over main window
        pw = self.pane.pane_controller.window
        new_pos = pw.frameGeometry().topLeft() \
            + pw.rect().center() - impdiag.window.rect().center()
        impdiag.window.move(new_pos)
        
        retval = impdiag.window.exec()
        if not retval:
            # user cancelled
            return

        # Take properties from import dialog
        # upload template
        template = self.model.add_new_template_from_dict({
            'name': impdiag.name,
            'iconCode': chr(int(impdiag.icon_code, 16)),
            'categories': list(impdiag.categories),
            'landscape': impdiag.landscape})
        template.load_svg_from_bytes(
            svgtools.svg_orientation_correction(svgdata))
        template.install_to_device()
        self.model.restart_xochitl()

    def _upload_png(self, png_filepath):
        # Embed the PNG into an SVG, write out to a temporary file, then
        # piggyback on _upload_svg().

        # The rejection of images does not happen here. It's over in
        # the _upload_svg() method. This will just insert the PNG into
        # an SVG container with no other enhancements (no rotation or
        # scaling). All that happens over in the SVG function. This
        # does the bare-minimum for PNG support.
        svgdata = svgtools.png_to_svg(png_filepath)
        # Piggyback on SVG uploader
        self._upload_svg(svgdata,
                         filename=png_filepath.stem)

    def _get_ttf_font_from_device(self):
        # Extract the icomoon .ttf font compiled into Xochitl. This
        # contains all the icons.
        log.info('getting template icons from device')

        xochitl_bin = b''
        cmd = 'cat "/usr/bin/xochitl"'
        out, err = self.model.run_cmd(cmd, raw_noread=True)
        for chunk in iter(lambda: out.read(4096), b''):
            xochitl_bin += chunk

        # Find the footer in the bin
        # 'b y   I c o M o o n ', followed with more nulls
        seekfooter = b'\x62\x00\x79\x00\x20\x00\x49\x00\x63\x00\x6F\x00\x4D\x00\x6F\x00\x6F\x00\x6E\x00'

        loc = xochitl_bin.find(seekfooter, 0)
        if self.model.is_gt_eq_xochitl_version('3.9'):
            loc = xochitl_bin.find(seekfooter, loc + len(seekfooter))

        if not loc:
            log.error('could not find location of icon ttf')
            return
        ttf_end = loc + len(seekfooter)
        segment = xochitl_bin[:ttf_end]

        # Find the header, plus some to TTF beginning (00 01 00)
        headpart = b'\x63\x6D\x61\x70'  # 'cmap'
        segment_rev = segment[::-1]
        hp_end = segment_rev.find(headpart[::-1])
        # Find a little more (00 01 00)
        ttf_head = b'\x00\x01\x00'  # Identical when reversed
        # The end (beginning) position is really the length
        ttf_length = segment_rev.find(ttf_head, hp_end)
        if not ttf_length:
            log.error('could not find length of icon ttf')
            return
        ttf_length += len(ttf_head)
        ttf_start = ttf_end - ttf_length

        # Cut out the TTF
        ttf_bin = segment[ttf_start:ttf_end]
        ttf_font = io.BytesIO(ttf_bin)
        return ttf_font


ORIENTATION_ROLE = 420
ICON_CODE_ROLE = 421
class TemplateImporterDialog(UIController):
    name = 'New Template'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'newtemplate.ui')

    def __init__(self, controller, name=None, landscape=False):
        self.controller = controller
        pane = controller.pane
        super(type(self), self).__init__(
            pane.model, pane.threadpool)

        self.name = name
        self.landscape = landscape
        self.icon_code = None
        self.categories = set()
        self.listwidget = self.window.icon_listWidget
        self.load_icon_label = self.window.label_loading_icons

        # Assign the actual values to set in the template array
        self.window.creative_checkBox.real_name = 'Creative'
        self.window.grids_checkBox.real_name = 'Grids'
        self.window.life_checkBox.real_name = 'Life/organize'
        self.window.lines_checkBox.real_name = 'Lines'
        # Keep these around to make it easy to set props
        self.checks = [self.window.creative_checkBox,
                       self.window.grids_checkBox,
                       self.window.life_checkBox,
                       self.window.lines_checkBox]

        # Populate icons. This will poll until they are completely
        # loaded, then self-terminate.
        self.populate_icons()

        # Fill widget with passed values
        if self.name:
            self.window.name_lineEdit.setText(self.name)

        # Update this dialog object when UI values change
        self.window.orientation_comboBox.currentIndexChanged.connect(
            self.orientation_changed)
        self.window.name_lineEdit.textChanged.connect(
            self.name_changed)
        self.listwidget.itemSelectionChanged.connect(
            self.icon_changed)
        for check in self.checks:
            check.stateChanged.connect(self.category_changed)

        # Fill init data
        self.category_changed()
        self.orientation_changed()
        self.filter_icon_listwidget()

    def populate_icons(self):
        # Load the icons from the controller into the UI. This will poll
        # the controller for changes until they are loaded, after which
        # the polling will self-terminate.
        if not self.controller.icons_loaded:
            # poll again after timeout
            QTimer.singleShot(1000, self.populate_icons)
            return
        for code in self.controller.icons:
            icon = self.controller.icons[code][0]
            landscape = self.controller.icons[code][1]
            
            item = QListWidgetItem(None)
            item.setIcon(self.controller.icons[code][0])
            item.setSizeHint(QSize(68, 68))
            item.setData(ORIENTATION_ROLE, landscape)
            item.setData(ICON_CODE_ROLE, code)
            self.listwidget.addItem(item)
        self.listwidget.setEnabled(True)
        self.load_icon_label.hide()
        self.orientation_changed()

    def icon_changed(self):
        items = self.listwidget.selectedItems()
        if not len(items):
            self.icon_code = None
        else:
            self.icon_code = items[0].data(ICON_CODE_ROLE)
        self.set_enabled_widgets()

    def name_changed(self, text):
        self.name = text
        self.set_enabled_widgets()
        
    def orientation_changed(self, current_index=None):
        if current_index is None:
            current_index = int(self.landscape)
            self.window.orientation_comboBox.setCurrentIndex(
                current_index)
        self.landscape = bool(current_index)
        self.filter_icon_listwidget()
        self.set_enabled_widgets()

    def filter_icon_listwidget(self):
        # Clear selection
        selection = self.listwidget.selectedItems()
        for item in selection:
            item.setSelected(False)
        # Filter the icon listwidget with the selected orientation
        for i in range(0, self.listwidget.count()):
            item = self.listwidget.item(i)
            ilandscape = item.data(ORIENTATION_ROLE)
            if ilandscape != self.landscape:
                item.setHidden(True)
            else:
                item.setHidden(False)
        self.set_enabled_widgets()

    def category_changed(self):
        state = set()
        for check in self.checks:
            if check.isChecked():
                state.add(check.real_name)
        self.categories = state
        self.set_enabled_widgets()

    def validate_form(self):
        # Validates that all form fields are entered, and enables the
        # 'Create' button if good.

        # Name
        # ...
        if not self.name or '' == self.name:
            return False

        # Category
        # ...
        if not len(self.categories):
            return False

        # Orientation
        # ...

        # Icon
        # ...
        if not self.icon_code:
            return False

        # Good
        return True

    def set_enabled_widgets(self):
        # Sets widget states depending on form validation.
        # Make sure there is at-least one checkbox selected.
        # If only one is selected, disable it.
        checked = []
        for check in self.checks:
            if check.isChecked():
                checked.append(check)
        if 1 == len(checked):
            checked[0].setEnabled(False)
        else:
            for check in self.checks:
                check.setEnabled(True)

        # If the form is valid, enable the 'Create' button
        if self.validate_form():
            self.window.create_pushButton.setEnabled(True)
        else:
            self.window.create_pushButton.setEnabled(False)

    
            

        
        

        
