"""Render embedded Lucide SVG icons as Qt icons, tinted to the interface colour."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .icon_data import ICONS

ICON_COLOR = "#cfcfcf"
_cache = {}


def icon(name, color=ICON_COLOR, size=18):
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    svg = ICONS.get(name)
    result = QIcon()
    if svg is not None:
        data = QByteArray(svg.replace("currentColor", color).encode("utf-8"))
        renderer = QSvgRenderer(data)
        for scale in (1, 2):
            px = size * scale
            pm = QPixmap(px, px)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            renderer.render(painter, QRectF(0, 0, px, px))
            painter.end()
            result.addPixmap(pm)
    _cache[key] = result
    return result
