"""LightCut main window and entry point."""
import os
import sys

import serial.tools.list_ports
from PIL import Image
from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from . import gcode, project
from .camera_dialog import CameraDialog
from .canvas import Canvas
from .document import Document, MachineSettings, Shape
from .geometry import rect_path, svg_to_path
from .sender import GrblSender
from . import vision

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"


def _dspin(lo, hi, value, suffix="", decimals=2, step=1.0):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    w.setValue(value)
    return w


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LightCut")
        self.resize(1300, 820)
        self.doc = Document()
        self.machine = MachineSettings()
        self.canvas = Canvas(self.doc)
        self.canvas.before_change = self.push_undo
        self.setCentralWidget(self.canvas)
        self.sender = None
        self.undo_stack = []
        self.redo_stack = []
        self.project_path = None

        self._build_toolbar()
        self._build_menu()
        self._build_layers_dock()
        self._build_image_dock()
        self._build_machine_dock()
        self._build_send_dock()

        self.canvas.selectionChanged.connect(self._on_selection)
        self.canvas.changed.connect(self.canvas.update)
        self.refresh_layers()
        self._apply_machine()
        self.refresh_ports()
        self.statusBar().showMessage("Ready")
        QTimer.singleShot(0, self.canvas.fit_bed)

    # ---- undo / redo ------------------------------------------------
    def _snapshot(self):
        return [(QPainterPath(s.path), s.layer, s.name, s.kind,
                 dict(s.image) if s.image else None) for s in self.doc.shapes]

    def _restore(self, snap):
        self.doc.shapes[:] = [
            Shape(QPainterPath(p), layer, name, False, kind, dict(img) if img else None)
            for p, layer, name, kind, img in snap
        ]
        self.canvas.set_selection([])
        self.canvas.update()

    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            self.statusBar().showMessage("Nothing to undo")
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack:
            self.statusBar().showMessage("Nothing to redo")
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())

    # ---- toolbar and menu -------------------------------------------
    def _build_toolbar(self):
        tb = self.addToolBar("Tools")
        tb.setMovable(False)
        group = QActionGroup(self)
        group.setExclusive(True)
        tools = [("select", "Select", "V"), ("rect", "Rectangle", "R"),
                 ("ellipse", "Ellipse", "E"), ("line", "Line", "L"), ("text", "Text", "T")]
        for name, label, key in tools:
            act = QAction(label, self, checkable=True)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(lambda _=False, n=name: self.set_tool(n))
            group.addAction(act)
            tb.addAction(act)
            if name == "select":
                act.setChecked(True)
        tb.addSeparator()
        buttons = [("Undo", self.undo), ("Redo", self.redo),
                   ("Duplicate", self.canvas.duplicate_selected),
                   ("Flip H", lambda: self.canvas.flip_selected(True)),
                   ("Flip V", lambda: self.canvas.flip_selected(False)),
                   ("Import image", self.import_image), ("Import SVG", self.import_svg),
                   ("Camera scan", self.scan_camera), ("AI trace", self.trace_selected),
                   ("Select all", self.canvas.select_all),
                   ("Delete", self.canvas.delete_selected), ("Fit view", self.canvas.fit_bed)]
        for label, fn in buttons:
            act = QAction(label, self)
            act.triggered.connect(fn)
            tb.addAction(act)

    def _build_menu(self):
        def add(menu, label, fn, shortcut=None):
            act = QAction(label, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(fn)
            menu.addAction(act)
            return act

        file_menu = self.menuBar().addMenu("File")
        add(file_menu, "Open project...", self.open_project, "Ctrl+O")
        add(file_menu, "Save project...", self.save_project, "Ctrl+S")
        file_menu.addSeparator()
        add(file_menu, "Import image...", self.import_image, "Ctrl+Shift+I")
        add(file_menu, "Import SVG...", self.import_svg, "Ctrl+I")
        add(file_menu, "Scan material with camera...", self.scan_camera, "Ctrl+K")
        add(file_menu, "Export G-code...", self.export_gcode, "Ctrl+E")
        file_menu.addSeparator()
        add(file_menu, "Quit", self.close, "Ctrl+Q")

        ai_menu = self.menuBar().addMenu("AI")
        add(ai_menu, "Trace selected photo to vectors...", self.trace_selected)
        add(ai_menu, "Mark selected image as reference (not engraved)", self.toggle_reference)

        edit_menu = self.menuBar().addMenu("Edit")
        add(edit_menu, "Undo", self.undo, "Ctrl+Z")
        add(edit_menu, "Redo", self.redo, "Ctrl+Y")
        edit_menu.addSeparator()
        add(edit_menu, "Duplicate", self.canvas.duplicate_selected, "Ctrl+D")
        add(edit_menu, "Select all", self.canvas.select_all, "Ctrl+A")
        add(edit_menu, "Delete", self.canvas.delete_selected)
        edit_menu.addSeparator()
        add(edit_menu, "Flip horizontal", lambda: self.canvas.flip_selected(True))
        add(edit_menu, "Flip vertical", lambda: self.canvas.flip_selected(False))

    def set_tool(self, name):
        self.canvas.tool = name
        self.statusBar().showMessage(f"Tool: {name}")

    # ---- layers -----------------------------------------------------
    def _build_layers_dock(self):
        dock = QDockWidget("Layers", self)
        w = QWidget()
        v = QVBoxLayout(w)
        self.layer_list = QListWidget()
        v.addWidget(self.layer_list)
        add = QPushButton("Add layer")
        add.clicked.connect(self.add_layer)
        v.addWidget(add)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Line", "Fill"])
        self.power_spin = _dspin(0, 100, 50, " %", 1, 1)
        self.speed_spin = _dspin(1, 2000, 100, " mm/s", 1, 10)
        self.passes_spin = QSpinBox()
        self.passes_spin.setRange(1, 99)
        self.interval_spin = _dspin(0.01, 5, 0.1, " mm", 2, 0.01)
        self.z_spin = _dspin(-50, 50, 0, " mm", 2, 0.1)
        self.output_chk = QCheckBox("Output this layer")
        form.addRow("Mode", self.mode_combo)
        form.addRow("Power", self.power_spin)
        form.addRow("Speed", self.speed_spin)
        form.addRow("Passes", self.passes_spin)
        form.addRow("Hatch spacing", self.interval_spin)
        form.addRow("Z offset", self.z_spin)
        form.addRow("", self.output_chk)
        v.addLayout(form)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.layer_list.currentRowChanged.connect(self._on_layer_row)
        self.mode_combo.currentIndexChanged.connect(self._apply_layer_form)
        for spin in (self.power_spin, self.speed_spin, self.passes_spin,
                     self.interval_spin, self.z_spin):
            spin.valueChanged.connect(self._apply_layer_form)
        self.output_chk.toggled.connect(self._apply_layer_form)

    def refresh_layers(self):
        current = max(0, self.layer_list.currentRow())
        self.layer_list.clear()
        for layer in self.doc.layers:
            item = QListWidgetItem(layer.name)
            pix = QPixmap(14, 14)
            pix.fill(QColor(layer.color))
            item.setIcon(QIcon(pix))
            self.layer_list.addItem(item)
        self.layer_list.setCurrentRow(min(current, len(self.doc.layers) - 1))

    def _on_layer_row(self, row):
        if row < 0 or row >= len(self.doc.layers):
            return
        self.canvas.current_layer = row
        layer = self.doc.layers[row]
        widgets = [self.mode_combo, self.power_spin, self.speed_spin, self.passes_spin,
                   self.interval_spin, self.z_spin, self.output_chk]
        blockers = [QSignalBlocker(w) for w in widgets]
        self.mode_combo.setCurrentText(layer.mode)
        self.power_spin.setValue(layer.power)
        self.speed_spin.setValue(layer.speed)
        self.passes_spin.setValue(layer.passes)
        self.interval_spin.setValue(layer.interval)
        self.z_spin.setValue(layer.z)
        self.output_chk.setChecked(layer.output)
        del blockers

    def _apply_layer_form(self, *_):
        row = self.layer_list.currentRow()
        if row < 0:
            return
        layer = self.doc.layers[row]
        layer.mode = self.mode_combo.currentText()
        layer.power = self.power_spin.value()
        layer.speed = self.speed_spin.value()
        layer.passes = self.passes_spin.value()
        layer.interval = self.interval_spin.value()
        layer.z = self.z_spin.value()
        layer.output = self.output_chk.isChecked()
        self.canvas.update()

    def add_layer(self):
        idx = self.doc.add_layer()
        self.refresh_layers()
        self.layer_list.setCurrentRow(idx)

    def _on_selection(self):
        if self.canvas.selected:
            self.layer_list.setCurrentRow(self.canvas.selected[0].layer)
        self._refresh_image_panel()

    # ---- image settings ---------------------------------------------
    def _build_image_dock(self):
        dock = QDockWidget("Image", self)
        w = QWidget()
        form = QFormLayout(w)
        self.img_neg = QCheckBox("Negative (burn light areas)")
        self.img_mode = QComboBox()
        self.img_mode.addItems(["Dither", "Threshold"])
        self.img_thr = QSpinBox()
        self.img_thr.setRange(0, 255)
        self.img_thr.setValue(128)
        self.img_interval = _dspin(0.02, 2, 0.1, " mm", 2, 0.01)
        self.img_width = _dspin(1, 2000, 100, " mm", 1, 1)
        self.img_hint = QCheckBox("Layer power and speed apply to images")
        self.img_hint.setEnabled(False)
        form.addRow(self.img_neg)
        form.addRow("Mode", self.img_mode)
        form.addRow("Threshold", self.img_thr)
        form.addRow("Line spacing", self.img_interval)
        form.addRow("Width", self.img_width)
        form.addRow(self.img_hint)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.image_dock = dock
        for widget in (self.img_neg.toggled, self.img_mode.currentIndexChanged,
                       self.img_thr.valueChanged, self.img_interval.valueChanged,
                       self.img_width.valueChanged):
            widget.connect(self._apply_image_panel)
        self._refresh_image_panel()

    def _current_image(self):
        for s in self.canvas.selected:
            if s.kind == "image":
                return s
        return None

    def _refresh_image_panel(self):
        s = self._current_image()
        enabled = s is not None
        for w in (self.img_neg, self.img_mode, self.img_thr, self.img_interval, self.img_width):
            w.setEnabled(enabled)
        if s is None:
            return
        blockers = [QSignalBlocker(w) for w in (self.img_neg, self.img_mode, self.img_thr,
                                                self.img_interval, self.img_width)]
        self.img_neg.setChecked(s.image["negative"])
        self.img_mode.setCurrentText(s.image["mode"])
        self.img_thr.setValue(s.image["threshold"])
        self.img_interval.setValue(s.image["interval"])
        self.img_width.setValue(s.path.boundingRect().width())
        del blockers

    def _apply_image_panel(self, *_):
        s = self._current_image()
        if s is None:
            return
        self.push_undo()
        img = s.image
        img["negative"] = self.img_neg.isChecked()
        img["mode"] = self.img_mode.currentText()
        img["threshold"] = self.img_thr.value()
        img["interval"] = self.img_interval.value()
        b = s.path.boundingRect()
        new_w = self.img_width.value()
        new_h = new_w * img["src"].height / img["src"].width
        s.path = rect_path(b.x(), b.y(), new_w, new_h)
        img["qimg"] = None
        self.canvas.update()

    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import image", "", IMAGE_FILTER)
        if not path:
            return
        try:
            src = Image.open(path).convert("L")
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.push_undo()
        width = min(100.0, self.machine.bed_width - 40)
        height = width * src.height / src.width
        settings = {"src": src, "negative": False, "mode": "Dither", "threshold": 128,
                    "interval": 0.1, "flip_h": False, "flip_v": False, "qimg": None}
        shape = self.doc.add_shape(rect_path(20, 20, width, height), self.canvas.current_layer,
                                   os.path.basename(path), "image", settings)
        self.canvas.set_selection([shape])
        self.canvas.changed.emit()


    # ---- camera and AI ----------------------------------------------
    def scan_camera(self):
        dlg = CameraDialog(self, self.machine.bed_width, self.machine.bed_height)
        if dlg.exec() != CameraDialog.DialogCode.Accepted or dlg.result_pil is None:
            return
        self.push_undo()
        settings = {"src": dlg.result_pil, "negative": False, "mode": "Dither", "threshold": 128,
                    "interval": 0.5, "flip_h": False, "flip_v": False, "qimg": None,
                    "reference": True}
        shape = self.doc.add_shape(rect_path(0, 0, dlg.sheet_w, dlg.sheet_h),
                                   self.canvas.current_layer, "Camera scan", "image", settings)
        self.canvas.set_selection([shape])
        self.canvas.changed.emit()
        self.statusBar().showMessage("Sheet placed as a reference photo. Use AI > Trace to make cut paths.")

    def toggle_reference(self):
        s = self._current_image()
        if s is None:
            QMessageBox.information(self, "No image", "Select an image first.")
            return
        self.push_undo()
        s.image["reference"] = not s.image.get("reference", False)
        s.image["qimg"] = None
        self.canvas.update()
        self.statusBar().showMessage("Reference (not engraved)" if s.image["reference"]
                                     else "Engraved image")

    def trace_selected(self):
        s = self._current_image()
        if s is None:
            QMessageBox.information(self, "No image", "Select a photo or scan first.")
            return
        ai = QMessageBox.question(
            self, "Trace photo",
            "Use AI subject detection (GrabCut)?\n\nYes: separates the subject from the background.\n"
            "No: simple brightness threshold, faster for high-contrast drawings.",
        ) == QMessageBox.StandardButton.Yes
        b = s.path.boundingRect()
        try:
            polys = vision.trace_pil(s.image["src"], b.width(), ai)
        except Exception as exc:
            QMessageBox.warning(self, "Trace failed", str(exc))
            return
        if not polys:
            QMessageBox.information(self, "Nothing found", "No outlines were found. Try again with a higher-contrast photo.")
            return
        self.push_undo()
        shapes = []
        for pts in polys:
            path = QPainterPath()
            path.moveTo(b.x() + pts[0][0], b.y() + pts[0][1])
            for x, y in pts[1:]:
                path.lineTo(b.x() + x, b.y() + y)
            path.closeSubpath()
            shapes.append(self.doc.add_shape(path, self.canvas.current_layer, "Traced"))
        self.canvas.set_selection(shapes)
        self.canvas.changed.emit()
        self.statusBar().showMessage(f"Traced {len(shapes)} outlines onto {self.doc.layers[self.canvas.current_layer].name}")

    # ---- machine ----------------------------------------------------
    def _build_machine_dock(self):
        dock = QDockWidget("Machine", self)
        w = QWidget()
        form = QFormLayout(w)
        self.bed_w_spin = _dspin(50, 3000, 400, " mm", 0, 10)
        self.bed_h_spin = _dspin(50, 3000, 300, " mm", 0, 10)
        self.smax_spin = QSpinBox()
        self.smax_spin.setRange(1, 100000)
        self.smax_spin.setValue(1000)
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["Bottom-left (GRBL)", "Top-left"])
        self.text_size_spin = _dspin(1, 200, 10, " mm", 1, 1)
        self.z_chk = QCheckBox("Z adjustment axis")
        self.roller_chk = QCheckBox("Roller on U axis")
        self.roller_d_spin = _dspin(1, 1000, 50, " mm", 1, 1)
        form.addRow("Bed width", self.bed_w_spin)
        form.addRow("Bed height", self.bed_h_spin)
        form.addRow("Max S value", self.smax_spin)
        form.addRow("Origin", self.origin_combo)
        form.addRow("Text height", self.text_size_spin)
        form.addRow(self.z_chk)
        form.addRow(self.roller_chk)
        form.addRow("Roller diameter", self.roller_d_spin)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        for widget in (self.bed_w_spin, self.bed_h_spin, self.smax_spin,
                       self.text_size_spin, self.roller_d_spin):
            widget.valueChanged.connect(self._apply_machine)
        self.origin_combo.currentIndexChanged.connect(self._apply_machine)
        self.z_chk.toggled.connect(self._apply_machine)
        self.roller_chk.toggled.connect(self._apply_machine)

    def _apply_machine(self, *_):
        m = self.machine
        m.bed_width = self.bed_w_spin.value()
        m.bed_height = self.bed_h_spin.value()
        m.s_max = self.smax_spin.value()
        m.bottom_left = self.origin_combo.currentIndex() == 0
        m.text_size = self.text_size_spin.value()
        m.z_enabled = self.z_chk.isChecked()
        m.roller_enabled = self.roller_chk.isChecked()
        m.roller_diameter = self.roller_d_spin.value()
        self.canvas.bed_w = m.bed_width
        self.canvas.bed_h = m.bed_height
        self.canvas.text_size = m.text_size
        self.canvas.update()

    def _apply_machine_values(self, m):
        """Push a loaded MachineSettings into the machine panel."""
        for widget, value in ((self.bed_w_spin, m.bed_width), (self.bed_h_spin, m.bed_height),
                              (self.smax_spin, m.s_max), (self.text_size_spin, m.text_size),
                              (self.roller_d_spin, m.roller_diameter)):
            widget.setValue(value)
        self.origin_combo.setCurrentIndex(0 if m.bottom_left else 1)
        self.z_chk.setChecked(m.z_enabled)
        self.roller_chk.setChecked(m.roller_enabled)
        self._apply_machine()

    # ---- sending to the laser ---------------------------------------
    def _build_send_dock(self):
        dock = QDockWidget("Laser", self)
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.port_combo = QComboBox()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_ports)
        row.addWidget(self.port_combo, 1)
        row.addWidget(refresh)
        v.addLayout(row)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "250000"])
        v.addWidget(self.baud_combo)

        btns = QHBoxLayout()
        self.frame_btn = QPushButton("Frame")
        self.send_btn = QPushButton("Send")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.frame_btn.clicked.connect(self.frame)
        self.send_btn.clicked.connect(self.send)
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.frame_btn, self.send_btn, self.stop_btn):
            btns.addWidget(b)
        v.addLayout(btns)
        export = QPushButton("Export G-code...")
        export.clicked.connect(self.export_gcode)
        v.addWidget(export)
        self.progress = QProgressBar()
        v.addWidget(self.progress)
        v.addStretch(1)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItems([p.device for p in serial.tools.list_ports.comports()])
        idx = self.port_combo.findText(current)
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)

    def build_lines(self, frame=False):
        if frame:
            return gcode.generate_frame(self.doc, self.machine)
        return gcode.generate(self.doc, self.machine)

    def _start(self, lines):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "No port", "Select a serial port first.")
            return
        self.sender = GrblSender(port, int(self.baud_combo.currentText()), lines, self)
        self.sender.progress.connect(self._on_progress)
        self.sender.log.connect(lambda s: self.statusBar().showMessage(s))
        self.sender.done.connect(self._on_done)
        self.progress.setRange(0, max(1, len(self.sender.lines)))
        self.progress.setValue(0)
        self._set_busy(True)
        self.sender.start()

    def frame(self):
        self._start(self.build_lines(frame=True))

    def send(self):
        lines = self.build_lines()
        if not any(ln.startswith("G1") for ln in lines):
            QMessageBox.information(self, "Nothing to send",
                                    "Add shapes to the layers that are enabled for output.")
            return
        self._start(lines)

    def stop(self):
        if self.sender:
            self.sender.stop()

    def _on_progress(self, done, total):
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _on_done(self, ok, msg):
        self._set_busy(False)
        self.statusBar().showMessage(msg)
        if not ok and msg != "Stopped by user":
            QMessageBox.warning(self, "Send failed", msg)

    def _set_busy(self, busy):
        self.send_btn.setEnabled(not busy)
        self.frame_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    # ---- files ------------------------------------------------------
    def import_svg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import SVG", "", "SVG files (*.svg)")
        if not path:
            return
        try:
            geom = svg_to_path(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        if geom.isEmpty():
            QMessageBox.warning(self, "Import failed", "No drawable shapes found in that SVG.")
            return
        self.push_undo()
        shape = self.doc.add_shape(geom, self.canvas.current_layer, os.path.basename(path))
        self.canvas.set_selection([shape])
        self.canvas.changed.emit()

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project",
                                              self.project_path or "design.lcproj",
                                              "LightCut project (*.lcproj)")
        if not path:
            return
        try:
            project.save(path, self.doc, self.machine)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self.project_path = path
        self.statusBar().showMessage(f"Saved {path}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "LightCut project (*.lcproj)")
        if not path:
            return
        try:
            doc, machine = project.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", str(exc))
            return
        self.doc.layers[:] = doc.layers
        self.doc.shapes[:] = doc.shapes
        self.machine = machine
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.refresh_layers()
        self._apply_machine_values(machine)
        self.canvas.set_selection([])
        self.canvas.fit_bed()
        self.project_path = path
        self.statusBar().showMessage(f"Opened {path}")

    def export_gcode(self):
        lines = self.build_lines()
        path, _ = QFileDialog.getSaveFileName(self, "Export G-code", "design.gcode",
                                              "G-code (*.gcode *.nc *.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        self.statusBar().showMessage(f"Saved {path}")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
