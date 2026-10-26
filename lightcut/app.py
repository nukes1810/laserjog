"""LightCut main window and entry point."""
import os
import sys

import serial.tools.list_ports
from PIL import Image
from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QGuiApplication, QIcon, QKeySequence, QPainterPath,
    QPalette, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QToolBar, QVBoxLayout,
    QWidget,
)

from . import gcode, machine_info, materials, project, raster, vision
from .calibration import CalibrationDialog
from .camera_dialog import CameraDialog
from .canvas import Canvas
from .document import OPERATIONS, Document, MachineSettings, Shape
from .geometry import rect_path, svg_to_path
from .icons import icon
from .sender import GrblSender

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"
LASER_TYPES = ["Diode", "CO2"]


def _dspin(lo, hi, value, suffix="", decimals=2, step=1.0):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    w.setValue(value)
    return w


def _ispin(lo, hi, value, suffix=""):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(value)
    w.setSuffix(suffix)
    return w


def _button(text, icon_name, slot=None):
    b = QPushButton(icon(icon_name), text)
    if slot is not None:
        b.clicked.connect(slot)
    return b


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LightCut")
        self.resize(1320, 840)
        self.doc = Document()
        self.machine = MachineSettings()
        self.canvas = Canvas(self.doc)
        self.canvas.before_change = self.push_undo
        self.setCentralWidget(self.canvas)
        self.sender = None
        self.undo_stack = []
        self.redo_stack = []
        self.project_path = None
        self._img_undo_pushed = False

        self._build_toolbar()
        self._build_menu()
        self._build_layers_dock()
        self._build_image_dock()
        self._build_machine_dock()
        self._build_laser_dock()

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

    # ---- toolbar and menus ------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("Tools")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(tb)

        group = QActionGroup(self)
        group.setExclusive(True)
        tools = [("select", "Select (V)", "V", "mouse-pointer"),
                 ("rect", "Rectangle (R)", "R", "square"),
                 ("ellipse", "Ellipse (E)", "E", "circle"),
                 ("line", "Line (L)", "L", "slash"),
                 ("text", "Text (T)", "T", "type")]
        for name, label, key, ic in tools:
            act = QAction(icon(ic), label, self)
            act.setCheckable(True)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(lambda _=False, n=name: self.set_tool(n))
            group.addAction(act)
            tb.addAction(act)
            if name == "select":
                act.setChecked(True)
        tb.addSeparator()

        actions = [
            ("Undo (Ctrl+Z)", "undo-2", self.undo),
            ("Redo (Ctrl+Y)", "redo-2", self.redo),
            ("Duplicate (Ctrl+D)", "copy", self.canvas.duplicate_selected),
            ("Flip horizontal", "flip-horizontal", lambda: self.canvas.flip_selected(True)),
            ("Flip vertical", "flip-vertical", lambda: self.canvas.flip_selected(False)),
            ("Delete", "trash-2", self.canvas.delete_selected),
        ]
        for label, ic, fn in actions:
            act = QAction(icon(ic), label, self)
            act.triggered.connect(fn)
            tb.addAction(act)
        tb.addSeparator()

        imports = [
            ("Import image", "image", self.import_image),
            ("Import SVG", "file-input", self.import_svg),
            ("Scan material with camera", "camera", self.scan_camera),
            ("AI trace selected photo", "sparkles", self.trace_selected),
        ]
        for label, ic, fn in imports:
            act = QAction(icon(ic), label, self)
            act.triggered.connect(fn)
            tb.addAction(act)
        tb.addSeparator()

        for label, ic, fn in [("Select all (Ctrl+A)", "grid-3x3", self.canvas.select_all),
                              ("Fit to bed", "maximize", self.canvas.fit_bed)]:
            act = QAction(icon(ic), label, self)
            act.triggered.connect(fn)
            tb.addAction(act)

    def _build_menu(self):
        def add(menu, label, fn, shortcut=None, ic=None):
            act = QAction(icon(ic) if ic else QIcon(), label, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(fn)
            menu.addAction(act)
            return act

        file_menu = self.menuBar().addMenu("File")
        add(file_menu, "Open project...", self.open_project, "Ctrl+O", "folder-open")
        add(file_menu, "Save project...", self.save_project, "Ctrl+S", "save")
        file_menu.addSeparator()
        add(file_menu, "Import image...", self.import_image, "Ctrl+Shift+I", "image")
        add(file_menu, "Import SVG...", self.import_svg, "Ctrl+I", "file-input")
        add(file_menu, "Export G-code...", self.export_gcode, "Ctrl+E", "download")
        file_menu.addSeparator()
        add(file_menu, "Quit", self.close, "Ctrl+Q")

        edit_menu = self.menuBar().addMenu("Edit")
        add(edit_menu, "Undo", self.undo, "Ctrl+Z", "undo-2")
        add(edit_menu, "Redo", self.redo, "Ctrl+Y", "redo-2")
        edit_menu.addSeparator()
        add(edit_menu, "Duplicate", self.canvas.duplicate_selected, "Ctrl+D", "copy")
        add(edit_menu, "Select all", self.canvas.select_all, "Ctrl+A", "grid-3x3")
        add(edit_menu, "Delete", self.canvas.delete_selected, None, "trash-2")
        edit_menu.addSeparator()
        add(edit_menu, "Flip horizontal", lambda: self.canvas.flip_selected(True), None,
            "flip-horizontal")
        add(edit_menu, "Flip vertical", lambda: self.canvas.flip_selected(False), None,
            "flip-vertical")

        laser_menu = self.menuBar().addMenu("Laser")
        add(laser_menu, "Read settings from controller", self.read_controller, None, "cpu")
        add(laser_menu, "Calibrate material...", self.open_calibration, None, "crosshair")
        add(laser_menu, "Apply recommended settings to layer", self.apply_recommendation,
            None, "sparkles")

        ai_menu = self.menuBar().addMenu("AI")
        add(ai_menu, "Scan material with camera...", self.scan_camera, "Ctrl+K", "camera")
        add(ai_menu, "Trace selected photo to cut paths...", self.trace_selected, None,
            "sparkles")
        add(ai_menu, "Toggle reference (not engraved)", self.toggle_reference, None, "eye")

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
        v.addWidget(_button("Add layer", "plus", self.add_layer))

        form = QFormLayout()
        self.material_combo = QComboBox()
        self.material_combo.addItems(materials.material_names())
        self.op_combo = QComboBox()
        self.op_combo.addItems(OPERATIONS)
        self.power_spin = _dspin(0, 100, 50, " %", 1, 1)
        self.speed_spin = _dspin(1, 2000, 100, " mm/s", 1, 10)
        self.passes_spin = _ispin(1, 99, 1)
        self.interval_spin = _dspin(0.01, 5, 0.1, " mm", 2, 0.01)
        self.z_spin = _dspin(-50, 50, 0, " mm", 2, 0.1)
        self.output_chk = QCheckBox("Include in output")
        form.addRow("Material", self.material_combo)
        form.addRow("Operation", self.op_combo)
        form.addRow("Power", self.power_spin)
        form.addRow("Speed", self.speed_spin)
        form.addRow("Passes", self.passes_spin)
        form.addRow("Line spacing", self.interval_spin)
        form.addRow("Z offset", self.z_spin)
        form.addRow("", self.output_chk)
        v.addLayout(form)

        self.op_hint = QLabel("")
        self.op_hint.setWordWrap(True)
        self.op_hint.setStyleSheet("color:#9a9a9a;")
        v.addWidget(self.op_hint)

        row = QHBoxLayout()
        row.addWidget(_button("Recommend", "sparkles", self.apply_recommendation))
        row.addWidget(_button("Calibrate", "crosshair", self.open_calibration))
        v.addLayout(row)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.layer_list.currentRowChanged.connect(self._on_layer_row)
        self.material_combo.currentIndexChanged.connect(self._on_material_or_op)
        self.op_combo.currentIndexChanged.connect(self._on_material_or_op)
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

    def _load_layer_fields(self, layer):
        widgets = [self.material_combo, self.op_combo, self.power_spin, self.speed_spin,
                   self.passes_spin, self.interval_spin, self.z_spin, self.output_chk]
        blockers = [QSignalBlocker(w) for w in widgets]
        if self.material_combo.findText(layer.material) < 0:
            self.material_combo.addItem(layer.material)
        self.material_combo.setCurrentText(layer.material)
        self.op_combo.setCurrentText(layer.operation)
        self.power_spin.setValue(layer.power)
        self.speed_spin.setValue(layer.speed)
        self.passes_spin.setValue(layer.passes)
        self.interval_spin.setValue(layer.interval)
        self.z_spin.setValue(layer.z)
        self.output_chk.setChecked(layer.output)
        del blockers
        self._update_op_hint(layer)

    def _update_op_hint(self, layer):
        rec, source = materials.recommend(self.machine.laser_type, self.machine.laser_watts,
                                          layer.material, layer.operation)
        if rec is None:
            self.op_hint.setText(f"No preset for {layer.material} ({layer.operation.lower()}). "
                                 "Set the power and speed by hand or run a calibration.")
        elif source == "calibrated":
            self.op_hint.setText("Using your saved calibration for this laser.")
        else:
            self.op_hint.setText("Estimate for this laser. Run a calibration to refine it.")

    def _on_layer_row(self, row):
        if row < 0 or row >= len(self.doc.layers):
            return
        self.canvas.current_layer = row
        self._load_layer_fields(self.doc.layers[row])

    def _apply_layer_form(self, *_):
        row = self.layer_list.currentRow()
        if row < 0:
            return
        layer = self.doc.layers[row]
        layer.material = self.material_combo.currentText()
        layer.operation = self.op_combo.currentText()
        layer.mode = "Fill" if layer.operation == "Engrave" else "Line"
        layer.power = self.power_spin.value()
        layer.speed = self.speed_spin.value()
        layer.passes = self.passes_spin.value()
        layer.interval = self.interval_spin.value()
        layer.z = self.z_spin.value()
        layer.output = self.output_chk.isChecked()
        self._update_op_hint(layer)
        self.canvas.update()

    def _on_material_or_op(self, *_):
        self._apply_layer_form()
        self.apply_recommendation(show=False)

    def apply_recommendation(self, show=True):
        row = self.layer_list.currentRow()
        if row < 0:
            return
        layer = self.doc.layers[row]
        rec, source = materials.recommend(self.machine.laser_type, self.machine.laser_watts,
                                          layer.material, layer.operation)
        if rec is None:
            if show:
                self.statusBar().showMessage(
                    f"{layer.material} has no preset for {layer.operation.lower()}")
            return
        layer.power = rec["power"]
        layer.speed = rec["speed"]
        layer.passes = rec["passes"]
        layer.interval = rec["interval"]
        self._load_layer_fields(layer)
        self.canvas.update()
        if show:
            if source == "calibrated":
                self.statusBar().showMessage("Applied your saved calibration")
            else:
                self.statusBar().showMessage(
                    f"Estimate for a {self.machine.laser_watts:g} W {self.machine.laser_type} "
                    "laser. Run a calibration to refine it.")

    def add_layer(self):
        idx = self.doc.add_layer()
        self.refresh_layers()
        self.layer_list.setCurrentRow(idx)

    def _on_selection(self):
        if self.canvas.selected:
            self.layer_list.setCurrentRow(self.canvas.selected[0].layer)
        self._refresh_image_panel()

    # ---- photo engraving --------------------------------------------
    def _build_image_dock(self):
        dock = QDockWidget("Photo engraving", self)
        w = QWidget()
        form = QFormLayout(w)
        self.img_dither = QComboBox()
        self.img_dither.addItems(raster.DITHERS)
        self.img_neg = QCheckBox("Negative (burn light areas)")
        self.img_thr = _ispin(0, 255, 128)
        self.img_interval = _dspin(0.02, 2, 0.1, " mm", 2, 0.01)
        self.img_width = _dspin(1, 2000, 100, " mm", 1, 1)
        self.img_auto = QCheckBox("Auto levels")
        self.img_bright = _ispin(-100, 100, 0)
        self.img_contrast = _ispin(-100, 100, 0)
        self.img_gamma = _dspin(0.2, 3.0, 1.0, "", 2, 0.05)
        self.img_sharpen = _ispin(0, 500, 0, " %")
        form.addRow("Dithering", self.img_dither)
        form.addRow(self.img_neg)
        form.addRow("Threshold", self.img_thr)
        form.addRow("Line spacing", self.img_interval)
        form.addRow("Width", self.img_width)
        form.addRow(self.img_auto)
        form.addRow("Brightness", self.img_bright)
        form.addRow("Contrast", self.img_contrast)
        form.addRow("Gamma", self.img_gamma)
        form.addRow("Sharpen", self.img_sharpen)
        self.img_note = QLabel("Layer power and speed set the engraving strength. "
                               "Finer line spacing gives more detail but takes longer.")
        self.img_note.setWordWrap(True)
        self.img_note.setStyleSheet("color:#9a9a9a;")
        form.addRow(self.img_note)
        dock.setWidget(w)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.image_dock = dock
        self._img_widgets = [self.img_dither, self.img_neg, self.img_thr, self.img_interval,
                             self.img_width, self.img_auto, self.img_bright,
                             self.img_contrast, self.img_gamma, self.img_sharpen]
        for widget in self._img_widgets:
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._apply_image_panel)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._apply_image_panel)
            else:
                widget.valueChanged.connect(self._apply_image_panel)
        self._refresh_image_panel()

    def _current_image(self):
        for s in self.canvas.selected:
            if s.kind == "image":
                return s
        return None

    def _refresh_image_panel(self):
        self._img_undo_pushed = False
        s = self._current_image()
        for w in self._img_widgets:
            w.setEnabled(s is not None)
        self.img_note.setEnabled(s is not None)
        if s is None:
            return
        img = raster.fit_settings(s.image)
        blockers = [QSignalBlocker(w) for w in self._img_widgets]
        self.img_dither.setCurrentText(img["dither"])
        self.img_neg.setChecked(img["negative"])
        self.img_thr.setValue(img["threshold"])
        self.img_interval.setValue(img["interval"])
        self.img_width.setValue(s.path.boundingRect().width())
        self.img_auto.setChecked(img["auto_levels"])
        self.img_bright.setValue(img["brightness"])
        self.img_contrast.setValue(img["contrast"])
        self.img_gamma.setValue(img["gamma"])
        self.img_sharpen.setValue(img["sharpen"])
        del blockers

    def _apply_image_panel(self, *_):
        s = self._current_image()
        if s is None:
            return
        if not self._img_undo_pushed:
            self.push_undo()
            self._img_undo_pushed = True
        img = s.image
        img["dither"] = self.img_dither.currentText()
        img["negative"] = self.img_neg.isChecked()
        img["threshold"] = self.img_thr.value()
        img["interval"] = self.img_interval.value()
        img["auto_levels"] = self.img_auto.isChecked()
        img["brightness"] = self.img_bright.value()
        img["contrast"] = self.img_contrast.value()
        img["gamma"] = self.img_gamma.value()
        img["sharpen"] = self.img_sharpen.value()
        b = s.path.boundingRect()
        new_w = self.img_width.value()
        new_h = new_w * img["src"].height / img["src"].width
        if abs(new_w - b.width()) > 1e-6 or abs(new_h - b.height()) > 1e-6:
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
        settings = dict(raster.DEFAULTS, src=src, qimg=None)
        shape = self.doc.add_shape(rect_path(20, 20, width, height), self.canvas.current_layer,
                                   os.path.basename(path), "image", settings)
        self.canvas.set_selection([shape])
        self.canvas.changed.emit()

    def toggle_reference(self):
        s = self._current_image()
        if s is None:
            QMessageBox.information(self, "No image", "Select an image first.")
            return
        self.push_undo()
        s.image["reference"] = not s.image.get("reference", False)
        s.image["qimg"] = None
        self.canvas.update()
        self.statusBar().showMessage("Reference only (not engraved)" if s.image["reference"]
                                     else "Image will be engraved")

    # ---- camera and AI ----------------------------------------------
    def scan_camera(self):
        dlg = CameraDialog(self, self.machine.bed_width, self.machine.bed_height)
        if dlg.exec() != CameraDialog.DialogCode.Accepted or dlg.result_pil is None:
            return
        self.push_undo()
        settings = dict(raster.DEFAULTS, src=dlg.result_pil, qimg=None, reference=True)
        shape = self.doc.add_shape(rect_path(0, 0, dlg.sheet_w, dlg.sheet_h),
                                   self.canvas.current_layer, "Camera scan", "image", settings)
        self.canvas.set_selection([shape])
        self.canvas.changed.emit()
        self.statusBar().showMessage("Sheet placed as a reference. Use AI > Trace for cut paths.")

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
            QMessageBox.information(self, "Nothing found",
                                    "No outlines were found. Try a higher-contrast photo.")
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
        self.statusBar().showMessage(
            f"Traced {len(shapes)} outlines onto {self.doc.layers[self.canvas.current_layer].name}")

    # ---- machine ----------------------------------------------------
    def _build_machine_dock(self):
        dock = QDockWidget("Machine", self)
        w = QWidget()
        form = QFormLayout(w)
        self.laser_combo = QComboBox()
        self.laser_combo.addItems(LASER_TYPES)
        self.watts_spin = _dspin(0.5, 200, 10, " W", 1, 0.5)
        self.bed_w_spin = _dspin(50, 3000, 400, " mm", 0, 10)
        self.bed_h_spin = _dspin(50, 3000, 300, " mm", 0, 10)
        self.smax_spin = _ispin(1, 100000, 1000)
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["Bottom-left (GRBL)", "Top-left"])
        self.text_size_spin = _dspin(1, 200, 10, " mm", 1, 1)
        self.z_chk = QCheckBox("Z adjustment axis")
        self.roller_chk = QCheckBox("Roller on U axis")
        self.roller_d_spin = _dspin(1, 1000, 50, " mm", 1, 1)
        form.addRow("Laser type", self.laser_combo)
        form.addRow("Output power", self.watts_spin)
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
                       self.text_size_spin, self.roller_d_spin, self.watts_spin):
            widget.valueChanged.connect(self._apply_machine)
        self.laser_combo.currentIndexChanged.connect(self._apply_machine)
        self.origin_combo.currentIndexChanged.connect(self._apply_machine)
        self.z_chk.toggled.connect(self._apply_machine)
        self.roller_chk.toggled.connect(self._apply_machine)

    def _apply_machine(self, *_):
        m = self.machine
        m.laser_type = self.laser_combo.currentText()
        m.laser_watts = self.watts_spin.value()
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
        if hasattr(self, "op_hint"):
            row = self.layer_list.currentRow()
            if row >= 0:
                self._update_op_hint(self.doc.layers[row])

    def _apply_machine_values(self, m):
        """Push a loaded MachineSettings into the machine panel."""
        for widget, value in ((self.bed_w_spin, m.bed_width), (self.bed_h_spin, m.bed_height),
                              (self.smax_spin, m.s_max), (self.text_size_spin, m.text_size),
                              (self.roller_d_spin, m.roller_diameter),
                              (self.watts_spin, m.laser_watts)):
            widget.setValue(value)
        self.laser_combo.setCurrentText(m.laser_type)
        self.origin_combo.setCurrentIndex(0 if m.bottom_left else 1)
        self.z_chk.setChecked(m.z_enabled)
        self.roller_chk.setChecked(m.roller_enabled)
        self._apply_machine()

    # ---- laser connection and jobs ----------------------------------
    def _build_laser_dock(self):
        dock = QDockWidget("Laser", self)
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.port_combo = QComboBox()
        refresh = QPushButton(icon("rotate-cw"), "")
        refresh.setToolTip("Refresh ports")
        refresh.clicked.connect(self.refresh_ports)
        row.addWidget(self.port_combo, 1)
        row.addWidget(refresh)
        v.addLayout(row)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "250000"])
        v.addWidget(self.baud_combo)
        v.addWidget(_button("Read settings from controller", "cpu", self.read_controller))
        self.info_label = QLabel("Not connected")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#9a9a9a;")
        v.addWidget(self.info_label)

        btns = QHBoxLayout()
        self.frame_btn = _button("Frame", "crop", self.frame)
        self.send_btn = _button("Send", "play", self.send)
        self.stop_btn = _button("Stop", "circle-stop", self.stop)
        self.stop_btn.setEnabled(False)
        for b in (self.frame_btn, self.send_btn, self.stop_btn):
            btns.addWidget(b)
        v.addLayout(btns)
        v.addWidget(_button("Export G-code", "download", self.export_gcode))
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

    def read_controller(self):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "No port", "Select the laser's serial port first.")
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = machine_info.read_controller(port, int(self.baud_combo.currentText()))
        except Exception as exc:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Could not read controller", str(exc))
            return
        QGuiApplication.restoreOverrideCursor()
        st = info["settings"]
        if 30 in st:
            self.smax_spin.setValue(int(st[30]))
        if 130 in st:
            self.bed_w_spin.setValue(st[130])
        if 131 in st:
            self.bed_h_spin.setValue(st[131])
        self._apply_machine()
        parts = [info.get("version") or "firmware not identified"]
        if 30 in st:
            parts.append(f"max S {int(st[30])}")
        if 130 in st and 131 in st:
            parts.append(f"travel {st[130]:.0f} x {st[131]:.0f} mm")
        self.info_label.setText(" | ".join(parts))
        self.statusBar().showMessage("Read settings from the controller")

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
                                    "Add shapes to the layers that are included in the output.")
            return
        self._start(lines)

    def stop(self):
        if self.sender:
            self.sender.stop()

    def open_calibration(self):
        row = self.layer_list.currentRow()
        if row < 0:
            return
        layer = self.doc.layers[row]
        dlg = CalibrationDialog(self, self.machine, layer.material, layer.operation,
                                self._start, lambda: self.apply_recommendation(show=True))
        dlg.exec()

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
        shape = self.doc.add_shape(geom, self.canvas.current_layer, os.path.basename(path), "svg")
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
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "",
                                              "LightCut project (*.lcproj)")
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


def apply_theme(app):
    """Neutral dark theme with the Fusion style, no decorative colour."""
    app.setStyle("Fusion")
    pal = QPalette()
    window = QColor("#252526")
    base = QColor("#1e1e1e")
    text = QColor("#d4d4d4")
    muted = QColor("#6e6e6e")
    button = QColor("#333333")
    accent = QColor("#2f6fb0")
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, window)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, button)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, muted)
    app.setPalette(pal)
    app.setStyleSheet(
        "QDockWidget::title { background:#2a2a2a; padding:5px 8px; }"
        "QPushButton { padding:5px 10px; border:1px solid #444; border-radius:3px;"
        " background:#333; }"
        "QPushButton:hover { background:#3c3c3c; }"
        "QPushButton:disabled { color:#6e6e6e; }"
        "QToolBar { spacing:2px; border:none; background:#2a2a2a; padding:3px; }"
        "QStatusBar { background:#2a2a2a; color:#9a9a9a; }"
        "QToolButton { padding:4px; border-radius:3px; }"
        "QToolButton:hover { background:#3c3c3c; }"
        "QToolButton:checked { background:#2f6fb0; }"
    )


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
