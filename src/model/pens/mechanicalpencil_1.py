'''
mechanicalpencil_1.py
This is the model for a Mechanical Pencil QPen (for system software
1.7 and below).

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

from PySide2.QtCore import Qt, QLineF
from PySide2.QtGui import QPen, QBrush, QColor
from pathlib import Path

class MechanicalPencilPen1(QPen):
    # A PDF graphics state to be used during renders.
    pdf_gs = {'vector': {'/BM': '/Darken'}}
    
    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.pencil_textures = kwargs.get('pencil_textures', None)
        self.vector = kwargs.get('vector', False)
        self.setCapStyle(Qt.RoundCap)
        self.setJoinStyle(Qt.MiterJoin)
        self.setStyle(Qt.SolidLine)

        self.ocolor = None

        # Load textures
        self.textures = self.pencil_textures
    
    def paint_stroke(self, painter, stroke):
        brush = QBrush()
        
        for i, segment in enumerate(stroke.segments):
            if i+1 >= len(stroke.segments):
                # no next segment, last 'to' point
                continue
            
            nextsegment = stroke.segments[i+1]

            # Set the width
            self.setWidthF(segment.width / 1.25)

            # Set the brush/pattern
            if self.vector:
                if not self.ocolor:
                    self.ocolor = self.color()
                ncolor = QColor()
                ncolor.setRedF(1 - ((1 - self.ocolor.redF()) * segment.pressure))
                ncolor.setGreenF(1 - ((1 - self.ocolor.greenF()) * segment.pressure))
                ncolor.setBlueF(1 - ((1 - self.ocolor.blueF()) * segment.pressure))
                self.setColor(ncolor)
            else:
                brush.setColor(self.color())
                texture = self.textures.get_linear(0.00)
                pressure_textures = [
                    self.textures.get_linear(0.40),
                    self.textures.get_linear(0.40),
                    self.textures.get_linear(0.50),
                    self.textures.get_linear(0.60),
                    self.textures.get_linear(0.70),
                    self.textures.get_linear(0.80),
                    self.textures.get_linear(0.90),
                    self.textures.get_linear(0.95)
                ]
                for n, tex in enumerate(pressure_textures):
                    threshold = n / len(pressure_textures)
                    if segment.pressure*10 >= threshold:
                        texture = tex
                brush.setTexture(texture)
                self.setBrush(brush)

            painter.setPen(self)
            painter.drawLine(QLineF(segment.x, segment.y,
                                    nextsegment.x, nextsegment.y))
