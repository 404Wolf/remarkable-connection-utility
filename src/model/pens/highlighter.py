'''
highlighter.py
This is the model for a Highlighter QPen.

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

from PySide2.QtCore import Qt
from PySide2.QtGui import QPen, QColor, QPainterPath, QPainter, \
    QPainterPathStroker

class HighlighterPen(QPen):
    # A PDF graphics state to be used during renders.
    pdf_gs = {'bitmap': {'/BM': '/Multiply'},
              'vector': {'/BM': '/Multiply'}}
    
    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)

        self.layer = kwargs.get('layer')
        self.annotate = self.layer.page.renderer.prefs.annotated
        
        self.setCapStyle(Qt.FlatCap)
        self.setJoinStyle(Qt.BevelJoin)
        self.setStyle(Qt.SolidLine)

        super(type(self), self)

    def setColor(self, color):
        # Since 2.11, reMarkable no longer shows overlapping highlights
        # with transparency (the color is alway absolute). So, if we
        # pass a color in here, ignore the alpha.
        color.setAlphaF(1.0)
        super(type(self), self).setColor(color)
    
    def paint_stroke(self, painter, stroke):
        path = QPainterPath()
        path.moveTo(stroke.segments[0].x, stroke.segments[0].y)

        for i, segment in enumerate(stroke.segments, 1):
            path.lineTo(segment.x, segment.y)

        self.setWidthF(stroke.width)
        painter.setPen(self)
        old_comp = painter.compositionMode()
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        painter.drawPath(path)
        painter.setCompositionMode(old_comp)

        if self.annotate:
            # Create outline of the path. Annotations that are close to
            # each other get groups. This is determined by overlapping
            # paths. In order to fuzz this, we'll ~double~ 1X the normal
            # width and extend the end caps.
            real_path = QPainterPathStroker(self).createStroke(path)
            self.setWidthF(self.widthF() * 2)  # expand outline by 2x
            self.setCapStyle(Qt.SquareCap)
            offset_path = QPainterPathStroker(self).createStroke(path)
            # The annotation type is carried all the way through. This
            # is the type specified in the PDF spec.
            self.layer.annot_paths.append(
                ('/Highlight',
                 offset_path,
                 None,
                 real_path,
                 [real_path.boundingRect()]))
