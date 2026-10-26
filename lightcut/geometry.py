"""Geometry helpers: shape construction, SVG import, text, flattening and hatch fill.

All geometry is stored in millimetres. Qt paths are used everywhere so text,
shapes and imported SVG share one representation.
"""
import svgelements as se
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont, QPainterPath, QTransform

# SVG user units are CSS pixels (96 dpi) unless the file says otherwise.
PX_TO_MM = 25.4 / 96.0


def rect_path(x, y, w, h):
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


def ellipse_path(x, y, w, h):
    p = QPainterPath()
    p.addEllipse(QRectF(x, y, w, h))
    return p


def line_path(x1, y1, x2, y2):
    p = QPainterPath()
    p.moveTo(x1, y1)
    p.lineTo(x2, y2)
    return p


def text_path(text, x, y, size_mm):
    """Text whose em height is roughly size_mm, baseline at (x, y)."""
    px = max(1, round(size_mm / PX_TO_MM))
    font = QFont("Sans Serif")
    font.setPixelSize(px)
    p = QPainterPath()
    p.addText(0, 0, font, text)
    t = QTransform().translate(x, y).scale(PX_TO_MM, PX_TO_MM)
    return t.map(p)


def _pt(p):
    return QPointF(p.x * PX_TO_MM, p.y * PX_TO_MM)


def svg_to_path(filename):
    """Load an SVG file into a single QPainterPath in millimetres."""
    svg = se.SVG.parse(filename, reify=True)
    out = QPainterPath()
    for el in svg.elements():
        if not isinstance(el, se.Shape):
            continue
        try:
            p = se.Path(el)
        except Exception:
            continue
        for seg in p:
            if isinstance(seg, se.Move):
                out.moveTo(_pt(seg.end))
            elif isinstance(seg, se.Close):
                out.closeSubpath()
            else:
                n = max(2, min(400, int(seg.length() / 2)))
                for i in range(1, n + 1):
                    out.lineTo(_pt(seg.point(i / n)))
    return out


def flatten(path):
    """Return a list of polylines [(x, y), ...] for every subpath."""
    result = []
    for poly in path.toSubpathPolygons():
        pts = [(q.x(), q.y()) for q in poly]
        if len(pts) >= 2:
            result.append(pts)
    return result


def hatch(path, interval):
    """Horizontal scan lines filling the path (even-odd rule).

    Returns a list of 2-point polylines. Direction alternates every line so the
    head does not waste time returning to the start of each row.
    """
    polys = flatten(path)
    if not polys or interval <= 0:
        return []
    bounds = path.boundingRect()
    segments = []
    y = bounds.top() + interval / 2
    flip = False
    while y < bounds.bottom():
        yy = y + 1e-7
        xs = []
        for pts in polys:
            n = len(pts)
            for i in range(n):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % n]
                if (y1 <= yy < y2) or (y2 <= yy < y1):
                    xs.append(x1 + (yy - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            seg = [(a, y), (b, y)]
            segments.append(seg[::-1] if flip else seg)
        flip = not flip
        y += interval
    return segments
