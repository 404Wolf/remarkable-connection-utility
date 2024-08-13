'''
pdf_highlight_extractor.py
Procedures for extracting highlight annotations from PDFs.

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

from pdfminer.layout import LAParams, LTTextContainer, LTChar, \
    LTTextLineHorizontal
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import PDFPageAggregator

from PySide2.QtCore import QRectF, QPointF

import unicodedata


class PdfHighlightTextExtractor:
    @classmethod
    def normalize_string(cls, string):
        string = string.replace('\t', ' ')
        string = string.strip()
        string = unicodedata.normalize('NFKD', string)
        return string

    def __init__(self, pdf_path):
        self.pdf_path = pdf_path

    def as_text(self):
        data = self.get_all_highlighted_text()
        ret = ''
        for p, page in enumerate(data):
            if not len(page):
                continue
            ret += '[Page {}]\n'.format(p + 1)
            for s in page:
                ret += '---> {}\n'.format(s)
        return ret

    def get_all_highlighted_text(self):
        fp = open(self.pdf_path, 'rb')
        rsrcmgr = PDFResourceManager()
        laparams = LAParams()
        device = PDFPageAggregator(rsrcmgr, laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        pages = PDFPage.get_pages(fp)

        all_page_annots = []

        pi = -1
        for page in pages:
            pi += 1
            all_page_annots += [[]]
            
            if not hasattr(page, 'annots'):
                continue

            interpreter.process_page(page)
            layout = device.get_result()

            # Find the (highlight) annots. They are sometimes in a list,
            # and sometimes not.
            annots = None
            try:
                annots = page.annots.resolve()
            except:
                annots = page.annots

            if not annots:
                continue

            # Cache all annotation rects (derive from QuadPoints)
            annot_rect_groups = []
            for af in annots:
                a = af
                if type(af) is not type({}):
                    a = af.resolve()
                if not 'Subtype' in a:
                    continue
                if 'Highlight' not in str(a['Subtype']):
                    continue
                # Assumed to have quadpoints if /Highlight...
                qp = a['QuadPoints']
                # Break apart QuadPoints into seperate rects
                sub_rects = []
                if 8 <= len(qp) and 0 == len(qp) % 8:
                    i = 0
                    while i < len(qp):
                        qp_arr = qp[i:i+7]
                        qp_rect = QRectF(qp_arr[4],
                                         qp_arr[5],
                                         qp_arr[2]-qp_arr[4],
                                         qp_arr[3]-qp_arr[5])
                        sub_rects += [qp_rect]
                        i += 8
                annot_rect_groups += [sub_rects]

            # Cache all characters on the page as one list, so we can
            # iterate over them (for their positions and text) later.
            page_chars = []
            for element in layout:
                if isinstance(element, LTTextContainer):
                    for text_line in element:
                        if isinstance(text_line, LTChar):
                            page_chars += [text_line]
                            continue
                        if isinstance(text_line, LTTextLineHorizontal):
                            for c, char in enumerate(text_line):
                                if isinstance(char, LTChar):
                                    page_chars += [char]
                                # else -- if the 'character' has a _text
                                # attr, put it in anyway. I have noticed
                                # some spaces and \n like this, such as
                                # in the RCU user manaul. -- LTAnno
                                elif hasattr(char, '_text'):
                                    page_chars[-1]._text += char._text


            # There is a bug in pdfminer that improperly computes the
            # location of each char. The bug is that it does not take
            # into account the crop/media boxes, and therefore it could
            # think the char is at a different location. To get around
            # this, compute the difference here, and apply it to each
            # char found on the page.
            if not page.mediabox and page.cropbox:
                page.mediabox = page.cropbox
            if not page.cropbox and page.mediabox:
                page.cropbox = page.mediabox
            mb_rect = QRectF(page.mediabox[0],
                             page.mediabox[1],
                             page.mediabox[2] - page.mediabox[0],
                             page.mediabox[3] - page.mediabox[1])
            cb_rect = QRectF(page.cropbox[0],
                             page.cropbox[1],
                             page.cropbox[2] - page.cropbox[0],
                             page.cropbox[3] - page.cropbox[1])
            boundbox_rect = mb_rect.intersected(cb_rect)

            # Chars could technically belong to more than one rect group,
            # but a rect group can't have two copies of the same char. So,
            # iterate over all the chars for each rect group is the only
            # way to do it, even though it's more inefficient.

            annot_chars = []
            for rect_group in annot_rect_groups:
                annot_group_chars = []
                for sub_rect in rect_group:
                    sub_rect_chars = []
                    for char in page_chars:
                        char_rect = QRectF(char.bbox[0] + boundbox_rect.x(),
                                           char.bbox[1] + boundbox_rect.y(),
                                           char.bbox[2]-char.bbox[0],
                                           char.bbox[3]-char.bbox[1])
                        if sub_rect.contains(char_rect.center()):
                            sub_rect_chars += [char._text]
                    annot_group_chars += [''.join(sub_rect_chars)]
                annot_chars += [type(self).normalize_string(
                    '\n'.join(annot_group_chars))]
            all_page_annots[-1] += annot_chars

            # # Cross-ref: pdfminer.debug.chars
            # # Get the bounding rects of all chars, and paste these into
            # # document_renderer_page.py as draw_boxes[] to draw them.
            # group = []
            # for char in page_chars:
            #     group.append([
            #         char.bbox[0],
            #         char.bbox[1]-24,
            #         char.bbox[2],
            #         char.bbox[3]-24
            #     ])

        fp.close()
        return all_page_annots
