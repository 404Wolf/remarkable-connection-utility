'''
document_renderer.py
Primary logic for rendering documents.

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
from model import lines
from model.template import Template
from model.pens.textures import PencilTextures
from .document_renderer_page import DocumentPage

from PySide2.QtGui import QPainter, QImage, QPen, QPixmap, \
    QPageSize, QColor, QBrush, QPainterPath, QTransform
from PySide2.QtCore import Qt, QByteArray, QIODevice, QBuffer, QSizeF, \
    QSettings, QRectF, QPointF, QCoreApplication
from PySide2.QtPrintSupport import QPrinter

from pathlib import Path
import shutil
import json
import tempfile
import os
import pikepdf
import tarfile
import svgtools

DEBUG_MARKS = False


def rmdir(path):
    if path.is_file() and path.exists():
        path.unlink()
    try:
        for child in path.glob('*'):
            if child.is_file():
                child.unlink()
            else:
                rmdir(child)
        path.rmdir()
    except:
        pass

class DocRenderPrefs:
    # Default colors
    black = QColor(0, 0, 0)
    gray = QColor(128, 128, 128)
    white = QColor(255, 255, 255)
    blue = QColor(0, 0, 255)
    red = QColor(217, 7, 7)
    highlight_yellow = QColor(253, 255, 50)
    highlight_green = QColor(169, 250, 92)
    highlight_pink = QColor(255, 85, 207)
    highlight_gray = QColor(207, 207, 207)

    @classmethod
    def add_cli_args_to_parser(self, parser):
        def qcolor_to_string(qcolor):
            return '{},{},{}'.format(qcolor.red(),
                                        qcolor.green(),
                                        qcolor.blue())
        parser.add_argument('--color-black',
                            nargs=1,
                            metavar=qcolor_to_string(self.black),
                            help='r,g,b')
        parser.add_argument('--color-gray',
                            nargs=1,
                            metavar=qcolor_to_string(self.gray),
                            help='r,g,b')
        parser.add_argument('--color-white',
                            nargs=1,
                            metavar=qcolor_to_string(self.white),
                            help='r,g,b')
        parser.add_argument('--color-blue',
                            nargs=1,
                            metavar=qcolor_to_string(self.blue),
                            help='r,g,b')
        parser.add_argument('--color-red',
                            nargs=1,
                            metavar=qcolor_to_string(self.red),
                            help='r,g,b')
        parser.add_argument('--color-highlight',
                            nargs=1,
                            metavar=qcolor_to_string(self.highlight_yellow),
                            help='r,g,b')
        parser.add_argument('--color-highlight-green',
                            nargs=1,
                            metavar=qcolor_to_string(self.highlight_green),
                            help='r,g,b')
        parser.add_argument('--color-highlight-pink',
                            nargs=1,
                            metavar=qcolor_to_string(self.highlight_pink),
                            help='r,g,b')
        parser.add_argument('--color-highlight-gray',
                            nargs=1,
                            metavar=qcolor_to_string(self.highlight_gray),
                            help='r,g,b')
        parser.add_argument('--page-range',
                            nargs=1,
                            metavar='1,3-10',
                            help='list of pages to use in final result')
        parser.add_argument('--layered',
                            nargs=1,
                            metavar='1',
                            help='export with layers')
        parser.add_argument('--annotated',
                            nargs=1,
                            metavar='1',
                            help='export with annotations')
        parser.add_argument('--grouped-annots',
                            nargs=1,
                            metavar='1',
                            help='combine nearby annotations')
        parser.add_argument('--res-mod',
                            nargs=1,
                            metavar='2',
                            help='bitmap pixel density modifier')
    
    def __init__(self):
        self.page_range = None  # page numbers as set, index starts at 0

        self.vector = False
        self.annotated = False
        self.grouped_annots = False
        self.layered = False
        self.res_mod = 1  # Bitmap export density

        self.pencil_textures = PencilTextures()

        self.load_all_from_qsettings()
        self.override_with_args()

    def load_all_from_qsettings(self):
        if bool(int(QSettings().value('pane/notebooks/export_pdf_annotate') or 0)):
            self.annotated = True
        if bool(int(QSettings().value('pane/notebooks/export_pdf_grouped_annots') or 0)):
            self.grouped_annots = True
        if bool(int(QSettings().value('pane/notebooks/export_pdf_hires') or 0)):
            self.res_mod = 2
        if bool(int(QSettings().value('pane/notebooks/export_pdf_ocg') or 0)):
            self.layered = True
        load_black = QSettings().value('pane/notebooks/export_pdf_blackink')
        if load_black:
            self.black = load_black
        load_gray = QSettings().value('pane/notebooks/export_pdf_grayink')
        if load_gray:
            self.gray = load_gray
        load_white = QSettings().value('pane/notebooks/export_pdf_whiteink')
        if load_white:
            self.white = load_white
        load_blue = QSettings().value('pane/notebooks/export_pdf_blueink')
        if load_blue:
            self.blue = load_blue
        load_red = QSettings().value('pane/notebooks/export_pdf_redink')
        if load_red:
            self.red = load_red
        load_highlight = QSettings().value('pane/notebooks/export_pdf_highlightink')
        if load_highlight:
            self.highlight_yellow = load_highlight
        load_highlight_green = QSettings().value('pane/notebooks/export_pdf_highlightgreenink')
        if load_highlight_green:
            self.highlight_green = load_highlight_green
        load_highlight_pink = QSettings().value('pane/notebooks/export_pdf_highlightpinkink')
        if load_highlight_pink:
            self.highlight_pink = load_highlight_pink
        load_highlight_gray = QSettings().value('pane/notebooks/export_pdf_highlightgrayink')
        if load_highlight_gray:
            self.highlight_gray = load_highlight_gray
        if bool(int(QSettings().value('pane/notebooks/export_pdf_hires') or 0)):
            self.res_mod = 2

    def override_with_args(self):
        args = QCoreApplication.args
        
        def color_parse(rgba_string_list):
            c = rgba_string_list[0].split(',')
            for n in range(0, len(c)):
                c[n] = int(c[n])
            return (c[0], c[1], c[2])

        def range_parse(range_string):
            result = set()
            for part in range_string.split(','):
                x = part.split('-')
                result.update(range(int(x[0])-1, int(x[-1])-1 + 1))
            result = sorted(result)
            return sorted(result)
    
        # Override prefs with CLI options
        if args.color_black:
            self.black = QColor(*color_parse(args.color_black))
        if args.color_gray:
            self.gray = QColor(*color_parse(args.color_gray))
        if args.color_white:
            self.white = QColor(*color_parse(args.color_white))
        if args.color_blue:
            self.blue = QColor(*color_parse(args.color_blue))
        if args.color_red:
            self.red = QColor(*color_parse(args.color_red))
        if args.color_highlight:
            self.highlight = QColor(*color_parse(args.color_highlight))
        if args.color_highlight_green:
            self.highlight_green = QColor(*color_parse(args.color_highlight_green))
        if args.color_highlight_pink:
            self.highlight_pink = QColor(*color_parse(args.color_highlight_pink))
        if args.color_highlight_gray:
            self.highlight_gray = QColor(*color_parse(args.color_highlight_gray))
        if args.page_range:
            self.page_range = range_parse(args.page_range[0])
        if args.layered:
            self.layered = bool(int(args.layered[0]))
        if args.annotated:
            self.annotated = bool(int(args.annotated[0]))
        if args.grouped_annots:
            self.grouped_annots = bool(int(args.grouped_annots[0]))
        if args.res_mod:
            self.res_mod = int(args.res_mod[0])
        # Exclusive
        if args.render_rmn_pdf_b or args.export_pdf_b:
            self.vector = False
        elif args.render_rmn_pdf_v or args.export_pdf_v:
            self.vector = True
        
class DocRender:
    def __init__(self,
                 doc,
                 QCoreApplication=QCoreApplication):
        self.doc = doc
        # x_path: the extracted path of an .rmn archive
        self.x_path = None
        self.prefs = DocRenderPrefs()

        self.cleanup_stuff = set()

    def cleanup(self, incl_extract=False):
        for thing in self.cleanup_stuff:
            rmdir(thing)
        if incl_extract and self.x_path:
            rmdir(self.x_path)
            self.x_path = None

    def extract(self, prog_cb=lambda x: (), abort_func=lambda: False):
        # Extract the document to a local holding path.
        # prog_cb will issue on a scale of 0 to 1.0.
        
        self.x_path = Path(tempfile.mkdtemp())
        # self.cleanup_stuff.add(Path(self.x_path))

        # Extract the archive to disk in some temporary directory
        if self.doc.use_local_archive:
            tmparchive = Path(self.doc.use_local_archive)
            prog_cb(1)
        else:
            th, tmp = tempfile.mkstemp()
            os.close(th)
            tmparchive = Path(tmp)
            self.cleanup_stuff.add(tmparchive)
            est_bytes = self.doc.estimate_size()
            self.doc.save_archive(tmparchive, est_bytes,
                                  abort_func=abort_func,
                                  bytes_cb=lambda x: prog_cb(
                                      x / est_bytes))
        
        with tarfile.open(tmparchive, 'r') as tar:
            tar.extractall(path=self.x_path)
            tar.close()

        return self.x_path

    def get_qprinter_stream_for_template(self, template):
        res = self.doc.model.display.dpi
        width, height = self.doc.model.display.portrait_size
        ptperpx = 72 / res
        p_width = width * ptperpx
        p_height = height * ptperpx

        th, tmp = tempfile.mkstemp()
        os.close(th)
        tmp_pdf = Path(tmp)

        qpdfprinter = QPrinter()
        qpdfprinter.setOutputFormat(QPrinter.PdfFormat)
        qpdfprinter.setPaperSize(QSizeF(width/res, height/res),
                                 QPrinter.Inch)
        qpdfprinter.setResolution(res)
        qpdfprinter.setPageMargins(0, 0, 0, 0, QPrinter.Inch)
        qpdfprinter.setOutputFileName(str(tmp_pdf))

        painter = QPainter(qpdfprinter)
        # size doesn't matter to vectors, so (None, None)
        svgtools.template_to_painter(painter, template,
                                     (None, None), vector=True)
        painter.end()

        f = pikepdf.open(tmp_pdf)
        stream_s = f.pages[0].Contents.read_bytes().decode('utf-8')
        bbox = f.pages[0].MediaBox
        f.close()
        tmp_pdf.unlink()

        return (stream_s, bbox)

    def make_base_pdf_from_templates(self):
        # Create a new basepdf from the template imagery. This does not
        # add OCGs. To prevent duplicate data, template images are only
        # saved once into a PDF XObject, and referenced via an indirect
        # object on each page.

        used_templates = {}
        base_pdf = pikepdf.new()
        
        width, height = type(self.doc.model.display).portrait_size
        res = type(self.doc.model.display).dpi
        ptperpx = 72 / res
        pdfheight = height * ptperpx
        pdfwidth = width * ptperpx
        
        for page_i in range(0, self.doc.get_pages_len()):
            # Add the page where this template will be drawn.
            pdf_page = base_pdf.add_blank_page(page_size=(pdfwidth, pdfheight))
            
            page = DocumentPage(self, page_i, self.x_path)
            template = page.template
            if not template:
                log.error('template does not exist for page {}'.format(
                    page_i))
                continue
            # We have to go based on template ID, since each page will
            # create a new Template object.
            t_id = page.template.filename

            if t_id not in used_templates:
                # add
                if not self.prefs.vector:
                    # get the template image data
                    res_mod = self.prefs.res_mod
                    t_size = (width*res_mod, height*res_mod)
                    t_data = svgtools.svg_to_rgb8_bytes(
                        template.svg, t_size)
                    xobj = pikepdf.Stream(base_pdf, t_data)
                    xobj.Type = pikepdf.Name('/XObject')
                    xobj.Subtype = pikepdf.Name('/Image')
                    xobj.ColorSpace = pikepdf.Name('/DeviceRGB')
                    xobj.BitsPerComponent = 8
                    xobj.Width, xobj.Height = t_size
                    xobj.Interpolate = False

                    tpdfi_name = '/ImTemplate' + str(len(used_templates))
                    used_templates[t_id] = (tpdfi_name, xobj)
                else:
                    # use qt to render the svg into pdf and yank out the
                    # data.
                    stream_s, bbox = self.get_qprinter_stream_for_template(template)
                    xobj = pikepdf.Stream(base_pdf, stream_s.encode('utf-8'))
                    xobj.Type = pikepdf.Name('/XObject')
                    xobj.Subtype = pikepdf.Name('/Form')
                    xobj.BBox = bbox
                    xobj.ColorSpace = pikepdf.Name('/DeviceRGB')

                    tpdfi_name = '/ImTemplate' + str(len(used_templates))
                    used_templates[t_id] = (tpdfi_name, xobj)
                    
            tpdfi_name = used_templates[t_id][0]
            xobj = used_templates[t_id][1]
            pdf_page.Resources.XObject = pikepdf.Dictionary()
            pdf_page.Resources.XObject[tpdfi_name] = xobj

            pdf_page.Resources.ExtGState = pikepdf.Dictionary(
                GSa=pikepdf.Dictionary(
                    Type=pikepdf.Name('/ExtGState'),
                    AIS=False,  # SMask is for opacity
                    CA=1.0,     # Opacity=1
                    SA=True,    # Automatic stroke adjustment
                    SM=0.02,    # Smoothness tolerance
                    SMask=pikepdf.Name('/None')))  # Soft mask

            if not '/ColorSpace' in pdf_page.Resources:
                pdf_page.Resources.ColorSpace = pikepdf.Dictionary()
            # These are defined for Qt vector output. Keep them in the
            # page's ColorSpace dict (todo: avoid clobbering).
            pdf_page.Resources.ColorSpace.CSp = \
                pikepdf.Name('/DeviceRGB')
            pdf_page.Resources.ColorSpace.CSpg = \
                pikepdf.Name('/DeviceGray')
            pdf_page.Resources.ColorSpace.PCSp = \
                [pikepdf.Name('/Pattern'), pikepdf.Name('/DeviceRGB')]

            if not self.prefs.vector:
                t_c_stream = \
                    'q' + '\n' + \
                    '/GSa gs' + '\n' + \
                    '1 0 0 1 0 0 cm' + '\n' + \
                    '{} 0 0 {} 0 0 cm {}  Do'.format(pdfwidth,
                                                     pdfheight,
                                                     tpdfi_name) + '\n' + \
                    'Q' + '\n'
            else:
                t_c_stream = \
                    'q' + '\n' + \
                    '/GSa gs' + '\n' + \
                    '1 0 0 1 0 0 cm' + '\n' + \
                    '{} Do'.format(tpdfi_name) + '\n' + \
                    'Q' + '\n'
            pdf_page.Contents.write(bytes(t_c_stream, 'utf-8'))

        # save
        # ...
        th, tmp = tempfile.mkstemp()
        os.close(th)
        tmp_pdf = Path(tmp)
        self.cleanup_stuff.add(tmp_pdf)
        base_pdf.save(tmp_pdf)

        # return path
        return tmp_pdf


    def resize_page(self, pdf_page, base_pdf):
        # This will resize a pdf_page to the proper bounding rect,
        # using the ratio of the tablet's screen.

        # Add rotate parameter to pdf_page to make later logic less
        # verbose.
        if not '/Rotate' in pdf_page:
            pdf_page.Rotate = 0
        temp_mb = None
        temp_cb = None
        # Find MediaBox
        if '/MediaBox' in pdf_page:
            temp_mb = pdf_page.MediaBox
        elif '/Parent' in pdf_page and '/MediaBox' in pdf_page.Parent:
            temp_mb = pdf_page.Parent.MediaBox
        elif '/MediaBox' in base_pdf.Root.Pages:
            temp_mb = base_pdf.Root.Pages.MediaBox
        # Find CropBox
        if '/CropBox' in pdf_page:
            temp_cb = pdf_page.CropBox
        elif '/Parent' in pdf_page and '/CropBox' in pdf_page.Parent:
            temp_cb = pdf_page.Parent.CropBox
        elif '/CropBox' in base_pdf.Root.Pages:
            temp_cb = base_pdf.Root.Pages.CropBox
        # Deal with what we have. If missing one, use the other.
        if temp_mb and not temp_cb:
            temp_cb = temp_mb
        elif temp_cb and not temp_mb:
            temp_mb = temp_cb
        elif not temp_mb and not temp_cb:
            temp_mb = [-2000, -2000, 2000, 2000]
            temp_cb = temp_mb
            log.error('no mediabox or cropbox found in PDF! using {}'.format(temp_cb))
        # Now that we have the bounding rects of both, do a clone so
        # we can have the objects for both. Regardless of where they
        # came from, they will be added to pdf_page (prioritized).
        if not '/MediaBox' in pdf_page:
            pdf_page.MediaBox = pikepdf.Array(temp_mb)
        if not '/CropBox' in pdf_page:
            pdf_page.CropBox = pikepdf.Array(temp_cb)
        # Set for use.
        mediabox = pdf_page.MediaBox
        cropbox = pdf_page.CropBox
        # These boxes may be incorrectly applied in the PDF (improper
        # coordinate ordering), but that turns out not to be an issue
        # because when we find their intersection area with QRectF,
        # it gives us functions to find left(), bottom(), etc.
        mb_rect = QRectF(float(mediabox[0]),
                         float(mediabox[1]),
                         float(mediabox[2])-float(mediabox[0]),
                         float(mediabox[3])-float(mediabox[1]))
        cb_rect = QRectF(float(cropbox[0]),
                         float(cropbox[1]),
                         float(cropbox[2])-float(cropbox[0]),
                         float(cropbox[3])-float(cropbox[1]))
        boundbox_rect = mb_rect.intersected(cb_rect)
        # normalize
        boundbox_rect = QRectF(boundbox_rect.x(),
                               boundbox_rect.y(),
                               abs(boundbox_rect.width()),
                               abs(boundbox_rect.height()))
        boundbox = [boundbox_rect.x(),
                    boundbox_rect.y(),
                    boundbox_rect.x() + abs(boundbox_rect.width()),
                    boundbox_rect.y() + abs(boundbox_rect.height())]
        # At this point, we use boundbox for all geometric calculations.
        del boundbox_rect
        del mb_rect
        del cb_rect
        del mediabox
        del cropbox
        # Calculate some pleasantry variables.
        basepage_width = boundbox[2] - boundbox[0]
        basepage_height = boundbox[3] - boundbox[1]
        # Round because floating point makes finicky comparisons.
        basepage_ratio = round(basepage_width / basepage_height * 10000) / 10000
        # Track adjustments to the boundbox.
        adjust_w = 0
        adjust_h = 0
        basepage_landscape = False
        xobj_flip = False
        # Calculate new page dimensions based on the display ratio.
        display = self.doc.model.display
        display_ratio = display.portrait_size[0] / display.portrait_size[1]
        if basepage_ratio < display_ratio:
            # Like A4
            # expand width by pulling right over,
            # but keep static height
            new_w = basepage_height * display_ratio
            adjust_w = new_w - basepage_width
            if 180 == pdf_page.Rotate or 270 == pdf_page.Rotate:
                xobj_flip = True
                boundbox[0] -= adjust_w
            else:
                boundbox[2] += adjust_w
        elif basepage_ratio >= display_ratio and basepage_ratio < 1:
            # Like US Letter
            # expand the height by pulling bottom down,
            # but keep static width
            new_h = basepage_width / display_ratio
            adjust_h = new_h - basepage_height
            if 180 == pdf_page.Rotate or 270 == pdf_page.Rotate:
                xobj_flip = True
                boundbox[3] += adjust_h
            else:
                boundbox[1] -= adjust_h
        elif basepage_ratio >= 1:
            # page is rotated on rm screen because of landscape
            # basepage.
            basepage_landscape = True
            # Was it really a tall page or not?
            if 1/basepage_ratio < display_ratio:
                # Like A4...
                new_h = basepage_width * display_ratio
                adjust_h = new_h - basepage_height
                if 90 == pdf_page.Rotate or 180 == pdf_page.Rotate:
                    xobj_flip = True
                    boundbox[3] += adjust_h
                else:
                    boundbox[1] -= adjust_h
            else:
                # Like US Letter...
                new_w = basepage_height / display_ratio
                adjust_w = new_w - basepage_width
                if 90 == pdf_page.Rotate or 180 == pdf_page.Rotate:
                    xobj_flip = True
                    boundbox[2] += adjust_w
                else:
                    boundbox[0] -= adjust_w
        # Recalculate the pleasantry variables.
        boundbox_width = boundbox[2] - boundbox[0]
        boundbox_height = boundbox[3] - boundbox[1]

        if DEBUG_MARKS:
            if not '/Annots' in pdf_page:
                pdf_page.Annots = pikepdf.Array()
            a_dict = base_pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name('/Annot'),
                Rect=boundbox,
                ANN='pdfmark',
                Subtype=pikepdf.Name('/Square'),
                P=pdf_page.obj,
                CA=1.0,
                C=[1.0, 0, 0]))
            pdf_page.Annots.append(a_dict)



        
        
        # Apply transform (used in the tablet's Adjust View feature).
        # !!! !DO NOT TOUCH! !!! !!! !Verified correct! !!!
        tsfm = self.doc.get_tsfm()
        if not basepage_landscape:
            real_transform = QTransform(
                tsfm['m11'], tsfm['m12'], tsfm['m13'],
                tsfm['m21'], tsfm['m22'], tsfm['m23'],
                tsfm['m31']*boundbox_width,
                tsfm['m32']*boundbox_height,
                tsfm['m33'])
            bpbr = QRectF(0, 0,
                      boundbox_width, boundbox_height)
            invt = real_transform.inverted()[0]
            should_be = real_transform.inverted()[0].mapRect(bpbr)
            if not xobj_flip:
                newbox = [boundbox[0] + should_be.left(),
                          boundbox[3] - should_be.bottom(),
                          boundbox[0] + should_be.right(),
                          boundbox[3] - should_be.top()]
            else:
                newbox = [boundbox[2] - should_be.right(),
                          boundbox[1] + should_be.top(),
                          boundbox[2] - should_be.left(),
                          boundbox[1] + should_be.bottom()]
        else:
            real_transform = QTransform(
                tsfm['m11'], tsfm['m12'], tsfm['m13'],
                tsfm['m21'], tsfm['m22'], tsfm['m23'],
                tsfm['m31']*boundbox_height,
                tsfm['m32']*boundbox_width,
                tsfm['m33'])
            invt = real_transform.inverted()[0]
            bpbr = QRectF(0, 0,
                          boundbox_height, boundbox_width)
            should_be = invt.mapRect(bpbr)
            if not xobj_flip:
                newbox = [boundbox[2] - should_be.bottom(),
                          boundbox[3] - should_be.right(),
                          boundbox[2] - should_be.top(),
                          boundbox[3] - should_be.left()]
            else:
                newbox = [boundbox[0] + should_be.top(),
                          boundbox[1] + should_be.left(),
                          boundbox[0] + should_be.bottom(),
                          boundbox[1] + should_be.right()]


        if DEBUG_MARKS:
            a_dict = base_pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name('/Annot'),
                Rect=newbox,
                ANN='pdfmark',
                Subtype=pikepdf.Name('/Square'),
                P=pdf_page.obj,
                CA=1.0,
                C=[0, 1.0, 0]))
            pdf_page.Annots.append(a_dict)

        
        # Once the transform is done, that's basically it. Pages will be
        # added as XObjects and scaled to the edges, so their transforms
        # are implicit by the page location. We don't need to worry
        # about landscape pages because they are rendered into the
        # proper orientation. Not doing this adds A LOT of complication
        # to calculating geometries. Also, some useres strip out images
        # with automated tools, and with this method their extracted
        # images have proper orientation.
        pdf_page.MediaBox = pikepdf.Array(newbox)
        pdf_page.CropBox = pikepdf.Array(newbox)
        # Done!
        return (basepage_landscape, xobj_flip)

    
    def render_pdf(self, filepath, prog_cb=lambda x: (),
                   abort_func=lambda: False):
        # Each page renders individually. Can be multithreaded later.
        filepath = Path(filepath)
        pdfpath = Path(self.x_path / Path(self.doc.uuid + '.pdf'))

        # Set the default page range to "all" if the prefs didn't
        # dictate a range.
        if not self.prefs.page_range:
            p_range = set()
            page_length = self.doc.get_pages_len()
            p_range.update(range(0, page_length))
            self.prefs.page_range = p_range
        
        # If we don't have a base PDF already existing, make one out of
        # the templates and update the layer name to reflect what
        # the tablet's UI shows.
        bg_ocg_title = 'Background'
        if not pdfpath.exists():
            pdfpath = self.make_base_pdf_from_templates()
            bg_ocg_title = 'Template'

        # Try to open the document as-normal. If there is a password,
        # an exception will be raised. If there isn't already a
        # _pdf_password property on the document, then this is the first
        # time the exception is hit, and if we raise the exception the
        # Notebook Controller will handle it (prompt the user, then
        # get back here with the _pdf_password property set). If the
        # password is still wrong, another exception will be raised
        # automatically.
        try:
            base_pdf = pikepdf.open(pdfpath)
        except Exception as e:
            if not self.doc._pdf_password:
                raise e
            base_pdf = pikepdf.open(pdfpath, password=self.doc._pdf_password)
        # If we get to this point, then we assume the password is
        # correct, and re-use it during any save procedure.
 
        # This var used to be used, but I think I want to take it in
        # a different direction (it's kind of hacky).
        pages_drawn_since_last_save = 0

        # This used to use len(base_pdf.pages), but now with 2.12 it is
        # better to use doc._content_dict['pages'] since some PDF pages
        # may be removed.
        # ;; numpages = len(base_pdf.pages)
        if 'pageCount' in self.doc._content_dict:
            numpages = self.doc._content_dict['pageCount']
        else:
            # Old way as fallback
            numpages = len(base_pdf.pages)

        pdf_orig_num_pages = len(base_pdf.pages)

        log.info('page count is', numpages)

        # stores each template background, which are later merged with
        # the orignial pdf document
        tmp_bg_path = Path(tempfile.mkdtemp())
        self.cleanup_stuff.add(tmp_bg_path)

        n = -1
        num_pages_inserted = 0
        for page_i in range(0, numpages):
            n += 1

            # Don't render pages that will get deleted at the end.
            if page_i not in self.prefs.page_range:
                continue
            
            # Firmware 2.12 added the ability to add and remove PDF
            # pages from PDF documents. Neither operation touches the
            # base PDF file, but a record is stored in the document's
            # content dict. Check to see if this is a new page (give a
            # blank template) or a removed page (skip processing).
            basepdf_p = self.doc.get_redirection_for_page(page_i)

            # Copy this page to the end of the file, and work on that.
            # At the end of the procedure, the original PDF page
            # will be destroyed. It is necessary to keep something at
            # the original page index so we have a fixed index refernce.

            if 'pdf' == self.doc.get_filetype() and 0 <= basepdf_p:
                # Make a copy of this page at the end of the file, then
                # swap the original page (target of hyperlinks) with
                # the clone. The cloned page will retain the original
                # page index, so if it is duplicated later, the clone
                # will be copied and hyperlinks will point to the
                # true original page.

                # Make a shallow copy at the end
                base_pdf.pages.append(base_pdf.pages[basepdf_p])

                # Swap them, so the hyperlink-target page goes to
                # the end of the file, and so the shallow copy is what
                # would be cloned if the user duplicated the page.

                # Start with original references
                p1 = base_pdf.pages[basepdf_p]
                p2 = base_pdf.pages[-1] # shallow copy
                # Dereference original pages
                tmp_deref_page = base_pdf.add_blank_page(
                    page_size=(100, 100))
                base_pdf.pages[basepdf_p] = tmp_deref_page
                base_pdf.pages[-2] = tmp_deref_page
                # Re-reference pages
                base_pdf.pages[-2] = p1
                base_pdf.pages[basepdf_p] = p2
                del base_pdf.pages[-1] # tmp_deref_page
            elif 'pdf' == self.doc.get_filetype():
                # if template not exists:
                #   make_template()
                # else
                #   use template
                # !! TODO !!
                # -- for now, only insert a blank page
                oldpp = base_pdf.pages[-1]
                newpdfpage = base_pdf.add_blank_page(
                    page_size=(
                        abs(oldpp.MediaBox[2] - oldpp.MediaBox[0]),
                        abs(oldpp.MediaBox[3] - oldpp.MediaBox[1])))
            else:
                # Just a regular notebook page, which was already
                # rendered as base_pdf.
                base_pdf.pages.append(base_pdf.pages[page_i])

            pdf_page = base_pdf.pages[-1]
            r_page = DocumentPage(self, page_i, self.x_path,
                                  pencil_textures=self.prefs.pencil_textures)

            # Apply new size based on rM's display ratio to the
            # pdf_page. The page receives a compliant CropBox.
            basepage_landscape, xobj_flip = \
                self.resize_page(pdf_page, base_pdf)
            boundbox = pdf_page.CropBox
            page_width = boundbox[2] - boundbox[0]
            page_height = boundbox[3] - boundbox[1]

            # This will be needed to insert each page layer. It is
            # created automatically when using a template-backed
            # notebook, but may not exist when using the Blank
            # template, or using a background PDF page.
            if not '/XObject' in pdf_page.Resources:
                pdf_page.Resources.XObject = pikepdf.Dictionary()
            # This will be needed for potential OCG.
            if not 'Properties' in pdf_page.Resources:
                pdf_page.Resources.Properties = pikepdf.Dictionary()
            # XObjects will require a graphics state. The normal
            # state is /GSa, but more may be added depending on the Pen
            # type.
            if not '/ExtGState' in pdf_page.Resources:
                pdf_page.Resources.ExtGState = pikepdf.Dictionary()
            if not '/GSa' in pdf_page.Resources.ExtGState:
                pdf_page.Resources.ExtGState.GSa = pikepdf.Dictionary(
                    Type=pikepdf.Name('/ExtGState'),
                    AIS=False,  # SMask is for opacity
                    CA=1.0,     # Opacity=1
                    SA=True,    # Automatic stroke adjustment
                    SM=0.02,    # Smoothness tolerance
                    SMask=pikepdf.Name('/None'))  # Soft mask
            
            # Surround the existing background/template with OCG. We
            # will splice each part into the stream, so that stream
            # carries the following format:
            # 
            # -- begin contents
            #    template ocg start
            #    template stream
            #    template ocg end
            #    page ocg start
            #    layer0 ocg start
            #    layer0 stream
            #    layer0 ocg end
            #    ...etc
            #    page ocg end
            # -- end contents

            try:
                pdf_page.Contents.read_bytes()
                pdf_page.Contents = pikepdf.Array([pdf_page.Contents])
            except:
                pass
            contents = pdf_page.Contents

            # Wrap each content stream in a q..Q, so any transforms done
            # in those contexts STAY in those contexts. Some PDFs aren't
            # so nice about this (looking at you, Cairo graphics).
            for c in contents:
                try:
                    try:
                        cd = c.read_bytes().decode('utf-8')
                        cs = 'q\n' + cd + 'Q\n'
                        c.write(cs.encode('utf-8'))
                    except:
                        cd = c.read_bytes().decode('latin_1')
                        cs = 'q\n' + cd + 'Q\n'
                        c.write(cs.encode('latin_1'))
                except:
                    cd = c.read_bytes().decode('utf-8', errors='ignore')
                    cs = 'q\n' + cd + 'Q\n'
                    c.write(cs.encode('utf-8'))

            # Set up the page to render
            r_page.pdf_page = pdf_page
            r_page.base_pdf = base_pdf
            r_page.is_landscape = basepage_landscape
            r_page.xobj_flip = xobj_flip
            r_page.bg_ocg_title = bg_ocg_title
            # Render the page
            if -1 != r_page.render_marks():
                pages_drawn_since_last_save += 1
            prog_cb((page_i+1) / numpages)
            
            # Debug expand cropbox, mediabox
            if DEBUG_MARKS:
                pdf_page.CropBox = [-2000, -2000, 2000, 2000]
                pdf_page.MediaBox = [-2000, -2000, 2000, 2000]
                pdf_page.TrimBox = [-2000, -2000, 2000, 2000]

            if pages_drawn_since_last_save >= 10 \
               or page_i == max(self.prefs.page_range) - 1:
                log.error('saving')
                if self.doc._pdf_password:
                    base_pdf.save(filepath, encryption=pikepdf.Encryption(
                        user=self.doc._pdf_password,
                        owner=self.doc._pdf_password))
                else:
                    base_pdf.save(filepath)
                base_pdf.close()
                # Don't use pathlib.Path.replace() because it does not
                # work on Windows across drive letters.
                shutil.move(filepath, pdfpath)
                if self.doc._pdf_password:
                    base_pdf = pikepdf.open(
                        pdfpath, password=self.doc._pdf_password)
                else:
                    base_pdf = pikepdf.open(pdfpath)
                # self.cleanup()
                pages_drawn_since_last_save = 0

        # Delete the original PDF pages, which are located at the
        # beginning of the document.
        log.info('removing original pages')
        for n in range(0, pdf_orig_num_pages):
            del base_pdf.pages[0]

        # base_pdf.remove_unreferenced_resources()
        if self.doc._pdf_password:
            base_pdf.save(filepath, encryption=pikepdf.Encryption(
                user=self.doc._pdf_password,
                owner=self.doc._pdf_password))
        else:
            base_pdf.save(filepath)
        base_pdf.close()
        self.cleanup()

        return True

    def render_text_as_markdown(self, filepath, prog_cb=lambda x: (),
                                abort_func=lambda: False):
        # This will dump all the text from a fw3.3+ notebook.
        numpages = len(self.doc._content_dict['cPages']['pages'])
        out_text = ''
        n = 0
        for page_i in range(0, numpages):
            n += 1
            r_page = DocumentPage(self, page_i, self.x_path)
            # out_text += '--- PAGE {} ---\n\n'.format(n)
            out_text += r_page.return_text_as_markdown()
            prog_cb(n / numpages * 100)
        with open(filepath, 'w') as f:
            f.write(out_text)
            f.close()
        return out_text

    def render_snaphighlights_as_text(self, filepath, prog_cb=lambda x: (),
                                      abort_func=lambda: False):
        # This will dump all the highlights from a document. It should
        # work on all firmwares since the snap highlights are normalized
        # in lines.py.
        # numpages = len(self.doc.contentdict['cPages']['pages'])
        numpages = self.doc.get_pages_len()
        out_text = ''
        n = 0
        for page_i in range(0, numpages):
            n += 1
            r_page = DocumentPage(self, page_i, self.x_path)
            # out_text += '--- PAGE {} ---\n\n'.format(n)

            page_snaphl = r_page.return_snaphighlights_as_text()

            if '' == page_snaphl:
                continue
            if '' != out_text:
                out_text += '\n'
            out_text += '[Page {}]\n\n'.format(n)
            out_text += r_page.return_snaphighlights_as_text()
            prog_cb(n / numpages * 100)
        with open(filepath, 'wb') as f:
            f.write(out_text.encode('utf-8'))
            f.close()
        return out_text
