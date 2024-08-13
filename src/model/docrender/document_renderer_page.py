'''
document_renderer_page.py
Procedures for rendering document pages and page layers.

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
from model.template import Template
from model import lines
from model.pens.textures import PencilTextures

from PySide2.QtGui import QPainter, QImage, QPen, QPixmap, \
    QPageSize, QColor, QBrush, QPainterPath, QTransform
from PySide2.QtCore import Qt, QByteArray, QIODevice, QBuffer, QSizeF, \
    QSettings, QRectF, QPointF
from PySide2.QtPrintSupport import QPrinter

from pathlib import Path
import json
import svgtools
import ctypes
import gc
import tempfile
import pikepdf
import os
import io

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
    
class DocumentPage:
    # A single page in a document
    # From local disk!! When making agnostic later, only keep the
    # document and pagenum args.
    def __init__(self, renderer, pagenum, archivepath, \
                 pencil_textures=None):
        # Page 0 is the first page!
        self.renderer = renderer
        self.doc = renderer.doc
        self.num = pagenum
        self.display = renderer.doc.model.display  # Carried from model
        self.pencil_textures = pencil_textures
        self.cleanup_stuff = set()
        self.bg_ocg_title = 'Background'
        self.base_pdf = None
        self.pdf_page = None
        self.is_landscape = False # Set externally
        self.xobj_flip = False # Set externally

        # get page id
        self.uuid = self.doc.get_uuid_for_page(pagenum)

        self.rmpath = Path(
            archivepath / \
            Path(self.doc.uuid) / Path(self.uuid + '.rm'))

        # Try to load page metadata
        self.metadict = None
        self.metafilepath = Path(
            archivepath / Path(self.doc.uuid) / \
            Path(self.uuid + '-metadata.json'))
        if self.metafilepath.exists():
            with open(self.metafilepath, 'r') as f:
                self.metadict = json.load(f)
                f.close()

        # Try to load highlights
        self.highlights = []
        self.highlightspath = Path(
            archivepath / Path(self.doc.uuid + '.highlights') \
            / Path(self.uuid + '.json'))
        if self.highlightspath.exists():
            with open(self.highlightspath, 'r') as f:
                jdict = json.load(f)
                if 'highlights' in jdict:
                    self.highlights = jdict['highlights']
                f.close()
        else:
            # If we didn't find highlights, this might be a v6 lines
            # file (or just really old, pre-2.7).
            try:
                with open(self.rmpath, 'rb') as f:
                    self.highlights = lines.readHighlights6(
                        f)['highlights']
                    f.close()
            except Exception as e:
                # log.error('error reading v6 lines')
                # log.error(e)
                pass

        # Try to load template
        self.template = None
        tmpnamearray = []
        pagedatapath = Path(
            archivepath / Path(self.doc.uuid + '.pagedata'))
        if pagedatapath.exists():
            f = open(pagedatapath, 'r')
            pd_lines = f.read()
            for line in pd_lines.splitlines():
                tmpnamearray.append(line)
            f.close()

        if len(tmpnamearray):
            # I have encountered an issue with some PDF files, where the
            # rM won't save the page template for later pages. In this
            # case, just take the last-available page template, which
            # is usually 'Blank'.
            tmpname = tmpnamearray[-1]
            if self.num < len(tmpnamearray):
                tmpname = tmpnamearray[self.num]
            tmparchivepath = Path(
                    archivepath / Path(tmpname + '.rmt'))
            if tmparchivepath.exists():
                self.template = Template(
                    self.doc.model).from_archive(tmparchivepath)

        # Load layers
        self.layers = []
        self.load_layers()

    def cleanup(self):
        for thing in self.cleanup_stuff:
            rmdir(thing)

    def load_layers(self):
        # Loads layers from the .rm files
        self.layers = []
        
        if not self.rmpath.exists():
            # no layers, obv
            return

        # Load reMy version of page layers
        pagever = None
        pagelayers = None
        with open(self.rmpath, 'rb') as f:
            pagever, pagelayers = lines.readLines(
                f, self.renderer.prefs.res_mod)
            f.close()

        # Load layer data
        for i in range(0, len(pagelayers)):
            layerstrokes = pagelayers[i]

            try:
                name = self.metadict['layers'][i]['name']
            except:
                name = 'Layer ' + str(i + 1)

            layer = DocumentPageLayer(self,
                                      i,
                                      name=name,
                                      pencil_textures=self.pencil_textures)
            layer.strokes = layerstrokes
            self.layers.append(layer)

    def render_marks(self):
        # This will render all layers in this page to a specified
        # base_pdf. That PDF must be a pikepdf object.

        # Add OCGs for page, if not already exist.
        if self.renderer.prefs.layered:
            if not '/OCProperties' in self.base_pdf.Root:
                self.base_pdf.Root.OCProperties = pikepdf.Dictionary(
                    OCGs=pikepdf.Array(),
                    D=pikepdf.Dictionary(
                        Order=pikepdf.Array()))
            p_ocg_id = '/OcgPage{}'.format(self.num)
            p_ocg_title = 'Page {}'.format(self.num + 1)
            p_ocg_prop = pikepdf.Pdf.make_indirect(
                self.base_pdf, pikepdf.Dictionary(
                    Type=pikepdf.Name('/OCG'),
                    Name=p_ocg_title))
            self.pdf_page.Resources.Properties[p_ocg_id] = p_ocg_prop
            self.base_pdf.Root.OCProperties.OCGs.append(p_ocg_prop)
            self.base_pdf.Root.OCProperties.D.Order.append(p_ocg_prop)
            # Append inner order (where layers will add their OCG props)
            self.base_pdf.Root.OCProperties.D.Order.append([])

            # Add inner OCG for background page stream(s).
            b_ocg_id = '/OcgBackground{}'.format(self.num)
            b_ocg_title = self.bg_ocg_title
            b_ocg_prop = pikepdf.Pdf.make_indirect(
                self.base_pdf, pikepdf.Dictionary(
                    Type=pikepdf.Name('/OCG'),
                    Name=b_ocg_title))
            for c in self.pdf_page.Contents:
                try:
                    try:
                        cd = c.read_bytes().decode('utf-8')
                        cs = '/OC {} BDC\n'.format(b_ocg_id) + cd + 'EMC\n'
                        c.write(cs.encode('utf-8'))
                    except:
                        cd = c.read_bytes().decode('latin_1')
                        cs = '/OC {} BDC\n'.format(b_ocg_id) + cd + 'EMC\n'
                        c.write(cs.encode('latin_1'))
                except:
                    cd = c.read_bytes().decode('utf-8', errors='ignore')
                    cs = '/OC {} BDC\n'.format(b_ocg_id) + cd + 'EMC\n'
                    c.write(cs.encode('utf-8'))
            self.pdf_page.Resources.Properties[b_ocg_id] = b_ocg_prop
            self.base_pdf.Root.OCProperties.OCGs.append(b_ocg_prop)
            self.base_pdf.Root.OCProperties.D.Order[-1].append(b_ocg_prop)

        # Render each layer's strokes.
        rendered_anything = False
        for layer in self.layers:
            if -1 != layer.render_marks():
                rendered_anything = True
        if not rendered_anything:
            return -1

    def return_text_as_markdown(self):
        # This is called 'return', not 'render', because it doesn't
        # apply something to an existing object. It just parses/returns.
        text = ''
        with open(self.rmpath, 'rb') as f:
            text = lines.readText6(f)
            f.close()
        return text

    def return_snaphighlights_as_text(self):
        # Similar to return_text_as_markdown()
        highlights = ''
        for layer in self.highlights:
            for hl in layer:
                highlights += hl['text'] + '\n'
        return highlights

from model.pens import *
class DocumentPageLayer:
    # These pen codes probably refer to different versions through
    # various system software updates. We'll just render them all
    # the same (across all versions).
    pen_lookup = [
        PaintbrushPen,       # Brush
        PencilPen,           # Pencil
        BallpointPen,        # Ballpoint
        MarkerPen,           # Marker
        FinelinerPen,        # Fineliner
        HighlighterPen,      # Highlighter
        EraserPen,           # Eraser
        MechanicalPencilPen1,# Mechanical Pencil
        EraseAreaPen,        # Erase Area
        None,                # unknown
        None,                # unknown
        None,                # unknown
        PaintbrushPen,       # Brush
        MechanicalPencilPen, # Mechanical Pencil
        PencilPen,           # Pencil
        BallpointPen,        # Ballpoint
        MarkerPen,           # Marker
        FinelinerPen,        # Fineliner
        HighlighterPen,      # Highlighter
        EraserPen,           # Eraser
        None,                # unknown
        CalligraphyPen       # Calligraphy
    ]

    def __init__(self, page, index, name=None, pencil_textures=None):
        self.page = page
        self.name = name
        self.index = index
        self.pencil_textures = pencil_textures

        self.colors = [
            self.page.renderer.prefs.black,
            # Note: the old pre-2.11 highlighter has its color=='1',
            # so there's a special handling condition for that later.
            self.page.renderer.prefs.gray,
            self.page.renderer.prefs.white,
            self.page.renderer.prefs.highlight_yellow,
            self.page.renderer.prefs.highlight_green,
            self.page.renderer.prefs.highlight_pink,
            self.page.renderer.prefs.blue,
            self.page.renderer.prefs.red,
            self.page.renderer.prefs.highlight_gray
        ]

        # Set this from the calling func
        self.strokes = None

        # Store PDF annotations with the layer, in case actual
        # PDF layers are ever implemented.
        self.annot_paths = []

        # Find snap highlights (introduced in 2.7)
        self.highlights = []
        try:
            self.highlights = self.page.highlights[self.index]
        except:
            pass

    def get_grouped_annotations(self):
        # return: (LayerName, [(AnnotType, minX, minY, maxX, maxY)])

        def group_nearby_pathsets(pathset):
            # Compare all the annot_paths to each other. If any overlap,
            # they will be grouped together. This is done recursively.
            newset = []

            for p in pathset:
                annotype = p[0]
                offset_path = p[1]
                text = p[2]
                real_path = p[3]
                all_real_rects = p[4]

                # # Notice: stubbed this out because most PDF clients
                # # and Zotfile will extract comments text themselves.
                # # skip annotations with text (to preserve)
                # if p[2]:
                #     newset.append(p)
                #     continue
                
                found_fit = False
                for i, g in enumerate(newset):
                    gannotype = g[0]
                    g_offset_path = g[1]
                    g_text = g[2] # not used !!!
                    g_real_path = g[3]
                    g_all_real_rects = g[4]
                    # Only compare annotations of the same type
                    if gannotype != annotype:
                        continue
                    if offset_path.intersects(g_offset_path):
                        found_fit = True
                        g_all_real_rects += [real_path.boundingRect()]
                        newset[i] = (annotype, g_offset_path.united(offset_path), None, g_real_path.united(real_path), g_all_real_rects)
                        break
                if not found_fit:
                    # Didn't fit, so place into a new group
                    newset.append(p)

            if len(newset) != len(pathset):
                # Might have stuff left to group
                return group_nearby_pathsets(newset)
            else:
                # Nothing was grouped, so done
                return newset

        group_func = lambda x: x # Null func (no grouping)

        if self.page.renderer.prefs.grouped_annots:
            group_func = group_nearby_pathsets

        grouped = group_func(self.annot_paths)

        # Get the bounding rect of each group, which sets the PDF
        # annotation geometry.
        annot_rects = []
        for p in grouped:
            annotype = p[0]
            text = p[2]
            master_rect = p[3].boundingRect()
            sub_rects = p[4]
            annot = (annotype,
                     master_rect,
                     text,
                     sub_rects)
            annot_rects.append(annot)
        return (self.name, annot_rects)

    def get_snap_highlights_as_strokes(self):
        # Casts snap-highlights to ordinary strokes, so they can be
        # easily painted with the HighlighterPen. Saves annotation
        # geometries in to self.annot_paths just like prior code.

        strokes = [] # Target
        res_mod = self.page.renderer.prefs.res_mod

        for hl in self.highlights:
            if 'color' in hl:
                # Highlighter colors used to be in the range of 0..2,
                # but now (as of 2.12) appear in the range of 3..5, and
                # the 3.x firmware introduced a fourth 'gray'/overlapping
                # highlighter (a retro rendering of old reMarkable days), and
                # I haven't investigated how to handle that yet.
                if hl['color'] <= 2:
                    color = hl['color'] + 3
                else:
                    color = int(hl['color'])
            else:
                color = 3
            # Special handling of pre-2.11 highlight colors: if the
            # color==1, set the color to 3 (yellow).
            if 1 == color:
                color = 3
            opath = QPainterPath()
            for r in hl['rects']:
                rect = QRectF(r['x'] * res_mod,
                              r['y'] * res_mod,
                              r['width'] * res_mod,
                              r['height'] * res_mod)
                opath.addRect(rect)
                # Easiest to always assume left-to-right stroke. It
                # shouldn't matter once it's rendered.
                stroke_width = abs(rect.height())
                pen_i = self.pen_lookup.index(HighlighterPen)
                stroke = lines.Stroke(pen=pen_i,
                                      color=color,
                                      unk1=0,
                                      width=stroke_width,
                                      unk2=0,
                                      segments=[
                                          lines.Segment(x=rect.left(),
                                                        y=rect.center().y(),
                                                        speed=0,
                                                        direction=0,
                                                        width=stroke_width,
                                                        pressure=0),
                                          lines.Segment(x=rect.right(),
                                                        y=rect.center().y(),
                                                        speed=0,
                                                        direction=0,
                                                        width=stroke_width,
                                                        pressure=0)])
                strokes.append(stroke)
            # if self.page.renderer.prefs.annotated:
                # self.annot_paths.append(('Highlight', opath, hl['text']))
        return strokes

    def get_stroke_groups(self):
        # Segment strokes into groups, so that different graphics states
        # can be applied in the rendered PDF. If a Pen supports this, it
        # will have a 'pdf_gs' attribute.
        stroke_groups = [[]]
        for stroke in self.strokes:
            pen_i, color, unk1, width, unk2, segments = stroke
            try:
                pen_class = self.pen_lookup[pen_i]
                assert pen_class is not None
            except:
                log.error('unknown pen code %d' % pen_i)
                pen_class = GenericPen
            qpen = pen_class(pencil_textures=self.pencil_textures,
                             vector=self.page.renderer.prefs.vector,
                             layer=self)
            # If the pen changed between highlighter/non-highlighter,
            # set a new stroke_group.
            first_stroke = 0 == len(stroke_groups[0])
            if not first_stroke:
                last_pen_class = self.pen_lookup[stroke_groups[-1][-1][0]]
                # If the pen changed and one of them had a specific
                # graphics state, start a new group.
                if last_pen_class is not pen_class \
                   and pen_class is not EraserPen:
                    if hasattr(last_pen_class, 'pdf_gs') \
                       or hasattr(pen_class, 'pdf_gs'):
                        # Use the new pen's graphics state
                        stroke_groups.append([])
            # Add this stroke to the current stroke group.
            stroke_groups[-1].append(stroke)
        return stroke_groups
    
    def render_marks(self):
        # Render all marks directly to the pdf_page/base_pdf as
        # set in DocumentPage.

        # Separate the strokes into stroke groups, where each group is
        # usually of a specific pen type/rendering style. If the old
        # and new pens have different PDF graphics states specified
        # in their class, then a new stroke group is started. An example
        # of this being used is for HighlighterPen, which uses a
        # /Multiply blend mode.
        if self.page.renderer.prefs.layered:
            stroke_groups = self.get_stroke_groups()
        else:
            # Not chosing the Layered PDF export option will render
            # everything to a few XObjects, which will receive the
            # /GSHlt (/Multiply) graphics state. This will result
            # in a smaller PDF filesize and faster on-demand rendering
            # in clients at the expense of ink colors bleeding through.
            stroke_groups = [self.strokes]

        # Add snap-highlight stroke groups. These are supposed to render
        # beneath all other art.
        hlt_strokes = self.get_snap_highlights_as_strokes()
        if len(hlt_strokes):
            stroke_groups = [hlt_strokes] + stroke_groups

        # Render each stroke group.
        rendered_anything = False
        for s_group_i, s_group in enumerate(stroke_groups):
            # Generate a new XObject.
            xobj_id = '/ImPage{}Layer{}Sg{}'.format(
                self.page.num, self.index, s_group_i)
            ret = self.strokes_as_pdf_xobj(xobj_id, s_group)
            if -1 != ret and not rendered_anything:
                rendered_anything = True
            # Clear the annot_paths. This is a bit of a hack, since
            # there is some shared state here when there shouldn't
            # be. The HighlighterPen will write into annot_paths, but
            # this variable is accessed for each stroke group. Clearing
            # it here prevents the first synthesized highlights, from
            # Snap Highlights, from leaking into later stroke groups.
            self.annot_paths = []

        if not rendered_anything:
            return -1

    def strokes_as_pdf_xobj(self, xobj_id, strokes):
        # Avoid creating XObject for blank stroke group.
        if 0 >= len(strokes):
            return -1

        pdf_page = self.page.pdf_page
        base_pdf = self.page.base_pdf

        # This feature, while it works, has not been added to user-
        # configurable preferences. It actually inflates filesize,
        # and I can't notice an improvement in rendering speed in my
        # PDF clients on GNU/Linux.
        as_jpg = False
        
        # Assemble the XObject.
        if not self.page.renderer.prefs.vector:
            if not as_jpg:
                opaque, alpha, size = self.render_strokes_as_rgb8(strokes)
            else:
                opaque, alpha, size = self.rgb8_to_jpg((opaque, alpha, size))

            # pikepdf will automatically convert the opaque and alpha
            # streams to /FlateDecode filter.

            # Opaque
            xobj = pikepdf.Stream(self.page.base_pdf, opaque)
            xobj.Type = pikepdf.Name('/XObject')
            xobj.Subtype = pikepdf.Name('/Image')
            xobj.ColorSpace = pikepdf.Name('/DeviceRGB')
            xobj.BitsPerComponent = 8
            xobj.Width, xobj.Height = size
            xobj.Interpolate = False

            if as_jpg:
                xobj.Filter = pikepdf.Name('/DCTDecode')

            # Alpha mask
            smask = pikepdf.Stream(self.page.base_pdf, alpha)
            smask.Type = pikepdf.Name('/XObject')
            smask.Subtype = pikepdf.Name('/Image')
            smask.ColorSpace = pikepdf.Name('/DeviceGray')
            smask.BitsPerComponent = 8
            smask.Width, smask.Height = size
            smask.Interpolate = False
            xobj.SMask = smask
        else:
            stream_s, bbox, size = \
                self.render_strokes_as_pdf_stream(strokes)
            xobj = pikepdf.Stream(self.page.base_pdf, stream_s.encode('utf-8'))
            xobj.Type = pikepdf.Name('/XObject')
            xobj.Subtype = pikepdf.Name('/Form')
            xobj.BBox = bbox
            xobj.ColorSpace = pikepdf.Name('/DeviceRGB')

        # Assemble the stream.
        boundbox = pdf_page.CropBox
        page_width = boundbox[2] - boundbox[0]
        page_height = boundbox[3] - boundbox[1]

        # Stroke groups are defined by a single pen class. If that
        # class has defined a graphics state, use it for this
        # XObject (only if using layered output).
        use_graphics_state = '/GSa'  # Default
        is_highlight = False

        # The following logic used to be sequenced by if-layered or not.
        # This didn't really work, since non-layered PDFs (where the
        # intent is to render a single Xobject) became opaque. The
        # is only really a problem for the HighlighterPen, which needs
        # a special blend mode to appear underneath darker colors (often
        # text). Now, a graphics state will be applied to any Xobject,
        # not just the layered ones. If it's a single Xobject being
        # created, it will take its blend mode from HighlighterPen.

        def make_extgstate_dict(gs_id, adict):
            if not gs_id in pdf_page.Resources.ExtGState:
                gs_dict = pikepdf.Dictionary(
                    Type=pikepdf.Name('/ExtGState'))
                for key in adict:
                    gs_dict[key] = pikepdf.Name(adict[key])
                pdf_page.Resources.ExtGState[gs_id] = gs_dict

        # !!!
        # TODO: Look at this. I don't think this is supposed to be how
        # it works, and this logic doesn't make sense. I think this was
        # supposed to use the 'multiply' blend mode, or something, but
        # does this have side-effects for other logic that hits on
        # HighlighterPen? It would be better to find another class of
        # pen to synthesizee the graphics state (GS) from.
        # !!!
        if self.page.renderer.prefs.layered:
            pen_class = self.pen_lookup[strokes[0][0]]
        else:
            pen_class = HighlighterPen

        if hasattr(pen_class, 'pdf_gs'):
            gs_dict = None
            gs_id = None
            if not self.page.renderer.prefs.vector:
                if 'bitmap' in pen_class.pdf_gs:
                    gs_dict = pen_class.pdf_gs['bitmap']
                    gs_id = '/GS' + pen_class.__name__ + 'B'
            else:
                if 'vector' in pen_class.pdf_gs:
                    gs_dict = pen_class.pdf_gs['vector']
                    gs_id = '/GS' + pen_class.__name__ + 'V'
            if gs_dict is not None:
                make_extgstate_dict(gs_id, gs_dict)
                use_graphics_state += ' ' + gs_id
                
        if not self.page.renderer.prefs.vector:  
            stream_s = 'q' + '\n'
            stream_s += use_graphics_state + ' gs \n'
            # Translate
            stream_s += '1 0 0 1 {} {} cm'.format(
                round(boundbox[0], 5),
                round(boundbox[1], 5)) + '\n'
            if self.page.xobj_flip:
                # Rotate
                stream_s += '-1 0 0 -1 0 0 cm \n' + '\n'
                # Translate back
                stream_s += '1 0 0 1 {} {} cm\n'.format(
                    -page_width, -page_height) + '\n'
            # Scale
            stream_s += '{} 0 0 {} 0 0 cm'.format( # Scale
                page_width, page_height) + '\n'
            # Draw
            stream_s += '{} Do'.format(xobj_id) + '\n'
            stream_s += 'Q' + '\n'
        else:
            # A vector rendered with Qt PdfPrinter will contain these
            # properties. Copy them to give the ink color.
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
            
            stream_s = 'q' + '\n'
            stream_s += use_graphics_state + ' gs \n'
            # Translate
            stream_s += '1 0 0 1 {} {} cm'.format(
                round(boundbox[0], 5),
                round(boundbox[1], 5)) + '\n'
            if self.page.xobj_flip:
                # Rotate
                stream_s += '-1 0 0 -1 0 0 cm \n' + '\n'
                # Translate back
                stream_s += '1 0 0 1 {} {} cm\n'.format(
                    -page_width, -page_height) + '\n'
            # Scale
            factor = float(page_width) / float(bbox[2]-bbox[0])
            stream_s += '{} 0 0 {} 0 0 cm'.format( # Scale
                factor, factor) + '\n'
            # Draw
            stream_s += '{} Do'.format(xobj_id) + '\n'
            stream_s += 'Q' + '\n'

            # s = xobj.read_bytes().decode('utf-8')
            # s = 'q\n' + use_graphics_state + ' gs\n' + s + 'Q\n'
            # xobj.write(s.encode('utf-8'))

        
        # Basic stream done. Add OCG tags if necessary.
        used_ocg_prop = None
        if self.page.renderer.prefs.layered:
            ocg_id = '/OcgPage{}Layer{}'.format(self.page.num,
                                                self.index)
            ocg_title = 'Layer {}'.format(self.index + 1)
            if ocg_id in pdf_page.Resources.Properties:
                ocg_prop = pdf_page.Resources.Properties[ocg_id]
            else:
                ocg_prop = pikepdf.Pdf.make_indirect(
                    base_pdf, pikepdf.Dictionary(
                        Type=pikepdf.Name('/OCG'),
                        Name=ocg_title))
                pdf_page.Resources.Properties[ocg_id] = ocg_prop
                base_pdf.Root.OCProperties.OCGs.append(ocg_prop)
                base_pdf.Root.OCProperties.D.Order[-1].append(ocg_prop)
            stream_s = '/OC {} BDC\n'.format(ocg_id) + stream_s + 'EMC\n'
            used_ocg_prop = ocg_prop

        # Add highlight annotations if necessary. These might belong to
        # an OCG.
        if self.page.renderer.prefs.annotated:
            if not '/Annots' in pdf_page:
                pdf_page.Annots = pikepdf.Array()

            new_annots = self.get_grouped_annotations()[1]

            for atype, a_mrect, atext, a_subrects in new_annots:
                author = self.page.doc.model.device_info['rcuname']

                # This function, tranform_points(), is kind of a hack
                # to handle annotations that are both a single rect,
                # and also ones that have multiple sub rectangles. An
                # example of the latter is when multiple lines of
                # text are highlighted, which can become grouped
                # together. Each of those lines/highlights should have
                # their own definitive quadpoints so the text becomes
                # extracted properly in clients like Preview.app.
                # These annotations should also have a singular master
                # rectangle. Using this transform_points function is
                # just a generic way of converting a rectangle to
                # the proper coordinates.
                def transform_points(arect, page_size, boundbox):
                    trect = [0, 0, 0, 0]

                    page_width = float(page_size[0])
                    page_height = float(page_size[1])

                    # Default page boundbox (no transforms)
                    boundbox = [float(boundbox[0]),
                                float(boundbox[1]),
                                float(boundbox[2]),
                                float(boundbox[3])]
                    if not self.page.is_landscape:
                        x_scale = page_width / size[0]
                        y_scale = page_height / size[1]
                        tsfm = self.page.doc.get_tsfm()
                        real_transform = QTransform(
                            tsfm['m11'], tsfm['m12'], tsfm['m13'],
                            tsfm['m21'], tsfm['m22'], tsfm['m23'],
                            tsfm['m31']*size[0],
                            tsfm['m32']*size[1],
                            tsfm['m33'])
                        arect = real_transform.mapRect(arect)
                        if not self.page.xobj_flip:
                            # Verified proper left/bottom/right/top good!
                            trect = [boundbox[0] + arect.left()*x_scale,
                                     boundbox[3] - arect.bottom()*y_scale,
                                     boundbox[0] + arect.right()*x_scale,
                                     boundbox[3] - arect.top()*y_scale]
                        else:
                            # Verified proper left/bottom/right/top good!
                            trect = [boundbox[2] - arect.right()*x_scale,
                                     boundbox[1] + arect.top()*y_scale,
                                     boundbox[2] - arect.left()*x_scale,
                                     boundbox[1] + arect.bottom()*y_scale]
                    else:
                        x_scale = page_height / size[1]
                        y_scale = page_width / size[0]
                        tsfm = self.page.doc.get_tsfm()
                        real_transform = QTransform(
                            tsfm['m11'], tsfm['m12'], tsfm['m13'],
                            tsfm['m21'], tsfm['m22'], tsfm['m23'],
                            tsfm['m31']*size[1],
                            tsfm['m32']*size[0],
                            tsfm['m33'])
                        arect = real_transform.mapRect(arect)
                        if not self.page.xobj_flip:
                            # Verified proper left/bottom/right/top good!
                            trect = [boundbox[2] - arect.bottom()*x_scale,
                                     boundbox[3] - arect.right()*y_scale,
                                     boundbox[2] - arect.top()*x_scale,
                                     boundbox[3] - arect.left()*y_scale]
                        else:
                            # Verified proper left/bottom/right/top good!
                            trect = [boundbox[0] + arect.top()*x_scale,
                                     boundbox[1] + arect.left()*y_scale,
                                     boundbox[0] + arect.bottom()*x_scale,
                                     boundbox[1] + arect.right()*y_scale]

                    # By the PDF spec, the proper QuadPoints should be
                    # [x0,y0,x1,y1,x2,y2,x3,y3], where (x0,y0) is the lower-
                    # lefthand corner. (PDF 1.6 Spec p. 596, Table 8.26.)
                    # real_quadpoints = [trect[0], trect[1],  # LeftBottom
                    #                    trect[2], trect[1],  # RightBottom
                    #                    trect[2], trect[3],  # RightTop
                    #                    trect[0], trect[3]]  # LeftTop
                    # HOWEVER, PDF clients do NOT respect this spec,
                    # including Adobe Acrobat!
                    # See: https://stackoverflow.com/a/10729881
                    quadpoints = [trect[0], trect[3],  # LeftTop
                                  trect[2], trect[3],  # RightTop
                                  trect[0], trect[1],  # LeftBottom
                                  trect[2], trect[1]]  # RightBottom
                    return (trect, quadpoints)

                # Becomes the master bounding rectangle
                master_trect = transform_points(
                    a_mrect,
                    (page_width, page_height),
                    boundbox)[0]

                # Becomes the sub rectangles (one for each
                # line of highlighted text).
                sub_rect_quads = []
                for a_subrect in a_subrects:
                    sub_rect_quads += transform_points(
                        a_subrect,
                        (page_width, page_height),
                        boundbox)[1]

                # Write the annotation
                a_dict = base_pdf.make_indirect(
                    pikepdf.Dictionary(
                        Type=pikepdf.Name('/Annot'),
                        Rect=master_trect,
                        T=author,
                        ANN='pdfmark',
                        Subtype=pikepdf.Name(atype),
                        P=pdf_page.obj,
                        CA=0.0,
                        C=[1.0, 1.0, 1.0],
                        QuadPoints=sub_rect_quads))
                if used_ocg_prop is not None:
                    a_dict.OC = used_ocg_prop
                pdf_page.Annots.append(a_dict)

                if DEBUG_MARKS:
                    # Show annot with blue outline.
                    a_dict = base_pdf.make_indirect(
                        pikepdf.Dictionary(
                            Type=pikepdf.Name('/Annot'),
                            Rect=master_trect,
                            ANN='pdfmark',
                            Subtype=pikepdf.Name('/Square'),
                            P=pdf_page.obj,
                            CA=1.0,
                            C=[0, 0, 1.0]))
                    if used_ocg_prop is not None:
                        a_dict.OC = used_ocg_prop
                    pdf_page.Annots.append(a_dict)

                # # Cross-ref: pdfminer.debug.chars
                # draw_boxes = []
                # for box in draw_boxes:
                #     a_dict = pikepdf.Dictionary(
                #         Type=pikepdf.Name('/Annot'),
                #         Rect=box,
                #         ANN='pdfmark',
                #         Subtype=pikepdf.Name('/Square'),
                #         P=pdf_page.obj,
                #         CA=1.0,
                #         C=[0, 0, 1.0])
                #     pdf_page.Annots.append(a_dict)

        # # Debug pencil
        # if pen_class is PencilPen:
        #     # xobj.Group = pikepdf.Dictionary(
        #     #     Type=pikepdf.Name('/Group'),
        #     #     S=pikepdf.Name('/Transparency'),
        #     #     I=True, # isolated
        #     #     K=False) # knockout
        #     # xobj.BM = pikepdf.Name('/Normal')
        #     print(pen_class)
            
        # Write out XObject and Stream to PDF.
        pdf_page.Resources.XObject[pikepdf.Name(xobj_id)] = \
            xobj
        stream = pikepdf.Stream(self.page.base_pdf,
                                data=stream_s.encode('utf-8'))
        self.page.pdf_page.Contents.append(stream)

    def render_strokes_to_painter(self, strokes, painter, size, no_annot=False):
        width, height = size
        tsfm = self.page.doc.get_tsfm()
        transform = QTransform(tsfm['m11'], tsfm['m12'], tsfm['m13'],
                               tsfm['m21'], tsfm['m22'], tsfm['m23'],
                               tsfm['m31'] * width,
                               tsfm['m32'] * height,
                               tsfm['m33'])
        o_transform = painter.transform()
        painter.setTransform(transform)
        
        # Paint strokes
        for stroke in strokes:
            pen_i, color, unk1, width, unk2, segments = stroke
            try:
                pen_class = self.pen_lookup[pen_i]
                assert pen_class != None
            except:
                log.error('unknown pen code %d' % pen_i)
                pen_class = GenericPen
            qpen = pen_class(pencil_textures=self.pencil_textures,
                             vector=self.page.renderer.prefs.vector,
                             layer=self)
            # Special handling of pre-2.11 highlight colors: if the
            # color==1, set the color to 3 (yellow). THIS IS BROKEN
            # BECAUSE REMARKABLE BROKE THEIR OWN FORMAT. Only guaranteed
            # to render on later (2.12+) firmwares.
            if HighlighterPen == pen_class and 1 == color:
                color = 3  # Shift 2 for really early rM versions
            elif HighlighterPen == pen_class and color <= 2:
                color += 3 # Shift for later rM versions, 2.12+
            qpen.setColor(self.colors[color])
            if no_annot:
                # TODO: Find a classier (har) way of doing this. This is
                # a hack for the HighlighterPen not to write annots back
                # to the page.annot_paths when drawing the rgb8 alpha
                # mask, otherwise those annots get written out twice.
                qpen.annotate = False
            qpen.paint_stroke(painter, stroke)

        painter.setTransform(o_transform)

    def render_strokes_as_rgb8(self, strokes):
        # Returns (opaque, alpha, size)
        
        # I was having problems with QImage corruption (garbage data)
        # and memory leaking on large notebooks. I fixed this by giving
        # the QImage a reference array to pre-allocate RAM, then reset
        # the reference count after I'm done with it, so that it gets
        # cleaned up by the python garbage collector.
        
        # Transform according to the document metadata
        res_mod = self.page.renderer.prefs.res_mod
        s_size = self.page.display.portrait_size
        width = s_size[0] * res_mod
        height = s_size[1] * res_mod
        devpx = width * height
        bytepp = 4  # ARGB32
        # This is the primary image buffer. It needs to be pre-allocated
        # to prevent memory access errors in PySide2. See:
        # https://github.com/matplotlib/matplotlib/issues/4283#issuecomment-95950441
        image_ref = QByteArray()
        image_ref.fill('\0', devpx * bytepp)
        qimage = QImage(image_ref, width, height, QImage.Format_ARGB32)
        ctypes.c_long.from_address(id(image_ref)).value=1

        p = QPainter(qimage)
        p.setRenderHint(QPainter.LosslessImageRendering)
        self.render_strokes_to_painter(strokes, p, (width, height))
        p.end()
        
        if not self.page.is_landscape:
            # This used to be a combined statement, but it was crashing
            # ONLY when rendering an RMN via CLI on Trisquel 9 (Py3.6).
            # Breaking it apart appeases the garbage collector.
            qi2 = qimage.convertToFormat(QImage.Format_Alpha8)
            alpha = bytes(qi2.bits())
        else:
            # See note above.
            qi2 = qimage.transformed(QTransform().rotate(90)).convertToFormat(QImage.Format_Alpha8)
            alpha = bytes(qi2.bits())
        del p
        del qimage
        # Re-use imageref buffer, doesn't matter if it's larger than
        # the new devpp=3 for rgb888.
        flat_qimage = QImage(image_ref, width, height, QImage.Format_RGB888)
        flat_qimage.fill(Qt.white)
        
        p = QPainter(flat_qimage)
        p.setRenderHint(QPainter.LosslessImageRendering)
        self.render_strokes_to_painter(strokes, p, (width, height), True)
        p.end()

        o = None
        opaque = None
        if not self.page.is_landscape:
            opaque = bytes(flat_qimage.bits())
        else:
            # For some reason, this sometimes segfaults if it was all on
            # a single line, but only for some documents. ???
            # Test doc: trackreport_DR200km_gpx (2023-05-29)
            o = flat_qimage.transformed(QTransform().rotate(90))
            opaque = bytes(o.bits())
        del p
        del flat_qimage
        del image_ref
        del o
        gc.collect()
        size = (width, height)
        if self.page.is_landscape:
            size = (height, width)
        return (opaque, alpha, size)

    def rgb8_to_jpg(self, ):
        # accepts output from render_strokes_as_rgb8, then converts
        # (inefficiently). Returns in same format.
        opaque, alpha, size = tup
        newimage = QImage(opaque, *size, QImage.Format_RGB888)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        newimage.save(buf, 'JPG')
        opaque_data = bytes(ba.data())
        return (opaque_data, alpha, size)
        

    def render_strokes_as_pdf_stream(self, strokes):
        # It doesn't really matter what the canvas size is, since the
        # stream that is returned will be scaled via XObject properties.
        # The only thing that matters is the ratio.
        res = self.page.display.dpi
        width, height = self.page.display.portrait_size
        # Qt docs say 1 pt is always 1/72 inch
        # Multiply ptperpx by pixels to convert to PDF units
        res_mod = self.page.renderer.prefs.res_mod
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
        qpdfprinter.setResolution(res*res_mod)
        qpdfprinter.setPageMargins(0, 0, 0, 0, QPrinter.Inch)
        qpdfprinter.setOutputFileName(str(tmp_pdf))

        painter = QPainter(qpdfprinter)

        # Render to painter
        self.render_strokes_to_painter(
            strokes, painter, (width*res_mod, height*res_mod))
        painter.end()

        # Read the stream from the temppdf
        f = pikepdf.open(tmp_pdf)
        stream = f.pages[0].Contents.read_bytes().decode('utf-8')
        # stream = 'q\n/GSDarken gs\n' + stream + 'Q\n'
        bbox = f.pages[0].MediaBox
        f.close()
        tmp_pdf.unlink()

        # Rotate the stream if landscape bpage
        # ...
        size = (width*res_mod, height*res_mod)
        if self.page.is_landscape:
            stream2 = 'q\n'
            # Rotate 90
            stream2 += '0 -1 1 0 0 0 cm\n'
            # Resize
            ratio = p_width / p_height
            stream2 += '{} 0 0 {} 0 0 cm\n'.format(ratio, ratio)
            # Translate
            stream2 += '1 0 0 1 {} 0 cm\n'.format(-p_width)
            stream2 += stream + 'Q\n'
            stream = stream2
            size = (height*res_mod, width*res_mod)

        # Debug test for sample

        
        return (stream, bbox, size)
