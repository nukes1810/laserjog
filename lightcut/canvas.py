"""Interactive design canvas: select, move, draw shapes, text, and image placement."""
from PIL import ImageOps
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import QInputDialog, QWidget

from . import raster
from .geometry import ellipse_path, line_path, rect_path, text_path


def _same(a, items):
    return any(a is x for x in items)


class Canvas(QWidget):
    changed = Signal()
    selectionChanged = Signal()

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.bed_w = 400.0
        self.bed_h = 300.0
        self.text_size = 10.0
        self.current_layer = 0
        self.tool = "select"
        self.selected = []
        self.zoom = 3.0                       # widget pixels per mm
        self.origin = QPointF(60, 40)         # widget position of canvas (0, 0)
        self.before_change = lambda: None     # undo hook, set by the main window
        self._drag = None
        self._pan_last = None
        self._preview = None                  # (kind, start, end) while drawing
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(480, 320)

    # ---- coordinates -------------------------------------------------
    def to_scene(self, p):
        return QPointF((p.x() - self.origin.x()) / self.zoom,
                       (p.y() - self.origin.y()) / self.zoom)

    def fit_bed(self):
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return
        self.zoom = max(0.5, min((w - 80) / self.bed_w, (h - 80) / self.bed_h))
        self.origin = QPointF((w - self.bed_w * self.zoom) / 2,
                              (h - self.bed_h * self.zoom) / 2)
        self.update()

    # ---- selection and editing --------------------------------------
    def set_selection(self, shapes):
        self.selected = list(shapes)
        for s in self.doc.shapes:
            s.selected = _same(s, self.selected)
        self.selectionChanged.emit()
        self.update()

    def select_all(self):
        self.set_selection(self.doc.shapes)

    def delete_selected(self):
        if not self.selected:
            return
        self.before_change()
        self.doc.shapes[:] = [s for s in self.doc.shapes if not _same(s, self.selected)]
        self.set_selection([])
        self.changed.emit()

    def translate_selected(self, dx, dy):
        if not self.selected:
            return
        move = QTransform().translate(dx, dy)
        for s in self.selected:
            s.path = move.map(s.path)
        self.changed.emit()
        self.update()

    def nudge(self, dx, dy):
        if not self.selected:
            return
        self.before_change()
        self.translate_selected(dx, dy)

    def duplicate_selected(self):
        if not self.selected:
            return
        self.before_change()
        copies = []
        for s in self.selected:
            path = QTransform().translate(5, 5).map(s.path)
            img = dict(s.image) if s.image else None
            copies.append(self.doc.add_shape(path, s.layer, s.name, s.kind, img))
        self.set_selection(copies)
        self.changed.emit()

    def flip_selected(self, horizontal=True):
        if not self.selected:
            return
        self.before_change()
        x0 = min(s.path.boundingRect().left() for s in self.selected)
        x1 = max(s.path.boundingRect().right() for s in self.selected)
        y0 = min(s.path.boundingRect().top() for s in self.selected)
        y1 = max(s.path.boundingRect().bottom() for s in self.selected)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if horizontal:
            t = QTransform().translate(cx, cy).scale(-1, 1).translate(-cx, -cy)
        else:
            t = QTransform().translate(cx, cy).scale(1, -1).translate(-cx, -cy)
        for s in self.selected:
            s.path = t.map(s.path)
            if s.kind == "image":
                key = "flip_h" if horizontal else "flip_v"
                s.image[key] = not s.image[key]
                s.image["qimg"] = None
        self.changed.emit()
        self.update()

    def hit(self, sp):
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * 4.0 / self.zoom)   # ~4 px tolerance
        for s in reversed(self.doc.shapes):
            if stroker.createStroke(s.path).contains(sp) or s.path.contains(sp):
                return s
        return None

    # ---- painting ----------------------------------------------------
    @staticmethod
    def _make_path(kind, a, b):
        x0, y0 = min(a.x(), b.x()), min(a.y(), b.y())
        w, h = abs(b.x() - a.x()), abs(b.y() - a.y())
        if kind == "rect":
            return rect_path(x0, y0, w, h)
        if kind == "ellipse":
            return ellipse_path(x0, y0, w, h)
        if kind == "line":
            return line_path(a.x(), a.y(), b.x(), b.y())
        return None

    @staticmethod
    def _image_preview(s):
        if s.image.get("qimg") is None:
            b = s.path.boundingRect()
            img = s.image
            if img.get("reference"):
                # Reference photos show the picture itself; they are never engraved.
                from PIL import ImageOps
                src = img["src"]
                if img["flip_h"]:
                    src = ImageOps.mirror(src)
                if img["flip_v"]:
                    src = ImageOps.flip(src)
                img["qimg"] = raster.to_qimage(src)
            else:
                burn = raster.burn_map(img["src"], b.width(), b.height(), img["interval"],
                                       img["negative"], img["mode"], img["threshold"],
                                       img["flip_h"], img["flip_v"])
                img["qimg"] = raster.preview_qimage(burn)
        return s.image["qimg"]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#2b2b2b"))
        p.setTransform(QTransform(self.zoom, 0, 0, self.zoom,
                                  self.origin.x(), self.origin.y()))

        p.fillRect(QRectF(0, 0, self.bed_w, self.bed_h), QColor("#f4f4f4"))
        grid = QPen(QColor("#d0d0d0"))
        grid.setCosmetic(True)
        p.setPen(grid)
        for x in range(0, int(self.bed_w) + 1, 10):
            p.drawLine(QPointF(x, 0), QPointF(x, self.bed_h))
        for y in range(0, int(self.bed_h) + 1, 10):
            p.drawLine(QPointF(0, y), QPointF(self.bed_w, y))
        border = QPen(QColor("#555555"))
        border.setCosmetic(True)
        p.setPen(border)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0, 0, self.bed_w, self.bed_h))

        for s in self.doc.shapes:
            if s.kind == "image":
                p.drawImage(s.path.boundingRect(), self._image_preview(s))
                edge = QPen(QColor(self.doc.layers[s.layer].color))
                edge.setCosmetic(True)
                edge.setWidthF(2.0 if s.selected else 1.0)
                p.setPen(edge)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(s.path.boundingRect())
            else:
                pen = QPen(QColor(self.doc.layers[s.layer].color))
                pen.setCosmetic(True)
                pen.setWidthF(2.0 if s.selected else 1.2)
                p.setPen(pen)
                p.drawPath(s.path)
            if s.selected:
                dash = QPen(QColor("#0a84ff"))
                dash.setCosmetic(True)
                dash.setStyle(Qt.PenStyle.DashLine)
                p.setPen(dash)
                p.drawRect(s.path.boundingRect())

        if self._preview:
            kind, a, b = self._preview
            pv = QPen(QColor("#222222"))
            pv.setCosmetic(True)
            pv.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pv)
            path = self._make_path(kind, a, b)
            if path is not None:
                p.drawPath(path)
        p.end()

    # ---- mouse and keyboard -----------------------------------------
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_last = e.position()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        sp = self.to_scene(e.position())
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if self.tool == "select":
            hit = self.hit(sp)
            if hit is None:
                if not shift:
                    self.set_selection([])
                self._drag = {"last": sp, "hit": None, "moved": False, "pushed": False}
            else:
                if shift:
                    if _same(hit, self.selected):
                        self.set_selection([x for x in self.selected if x is not hit])
                    else:
                        self.set_selection(self.selected + [hit])
                elif not _same(hit, self.selected):
                    self.set_selection([hit])
                self._drag = {"last": sp, "hit": hit, "moved": False, "pushed": False}
        elif self.tool == "text":
            text, ok = QInputDialog.getText(self, "Add text", "Text:")
            if ok and text.strip():
                self.before_change()
                shape = self.doc.add_shape(
                    text_path(text, sp.x(), sp.y(), self.text_size),
                    self.current_layer, text)
                self.set_selection([shape])
                self.changed.emit()
        else:
            self._preview = (self.tool, sp, sp)
            self._drag = {"start": sp}
        self.update()

    def mouseMoveEvent(self, e):
        if self._pan_last is not None:
            d = e.position() - self._pan_last
            self.origin = self.origin + d
            self._pan_last = e.position()
            self.update()
            return
        if self._drag is None:
            return
        sp = self.to_scene(e.position())
        if self.tool == "select":
            if self._drag.get("hit") is None:
                return
            last = self._drag["last"]
            dx, dy = sp.x() - last.x(), sp.y() - last.y()
            if dx or dy:
                if not self._drag["pushed"]:
                    self.before_change()
                    self._drag["pushed"] = True
                self.translate_selected(dx, dy)
                self._drag["last"] = sp
        elif self._preview:
            kind, a, _ = self._preview
            self._preview = (kind, a, sp)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._pan_last is not None:
            self._pan_last = None
            return
        if self._drag is None:
            return
        if self.tool == "select":
            if self._drag.get("moved") or self._drag.get("pushed"):
                self.changed.emit()
        elif self._preview:
            kind, a, b = self._preview
            if abs(b.x() - a.x()) > 0.5 or abs(b.y() - a.y()) > 0.5:
                self.before_change()
                path = self._make_path(kind, a, b)
                shape = self.doc.add_shape(path, self.current_layer, kind.capitalize())
                self.set_selection([shape])
                self.changed.emit()
            self._preview = None
        self._drag = None
        self.update()

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        pos = e.position()
        sp = self.to_scene(pos)
        self.zoom = max(0.2, min(60.0, self.zoom * f))
        self.origin = QPointF(pos.x() - sp.x() * self.zoom, pos.y() - sp.y() * self.zoom)
        self.update()

    def keyPressEvent(self, e):
        step = 10.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        keys = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif e.key() == Qt.Key.Key_Escape:
            self.set_selection([])
        elif e.key() in keys:
            self.nudge(*keys[e.key()])
        else:
            super().keyPressEvent(e)
