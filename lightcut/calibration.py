"""Calibration: burn a 5 x 5 test grid of power and speed, then save the best square.

Rows are speed (A to E, top to bottom) and columns are power (1 to 5, left to right).
Each square is labelled with its code, engraved beside it at a low fixed power, so the
result can be matched to a saved profile.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from . import materials
from .geometry import flatten, hatch, rect_path, text_path
from .gcode import _axes, _home
from .icons import icon

CELL = 10.0            # mm
PITCH = 14.0           # mm between square origins
ORIGIN = (20.0, 30.0)  # canvas position of the top-left square
POWER_FACTORS = [0.7, 0.85, 1.0, 1.15, 1.3]
SPEED_FACTORS = [0.6, 0.8, 1.0, 1.25, 1.5]
ROW_LABELS = "ABCDE"
LABEL_POWER = 20.0     # % used for the square labels
LABEL_SPEED = 300.0    # mm/s used for the square labels


def grid_values(rec):
    powers = [min(100.0, round(rec["power"] * f, 1)) for f in POWER_FACTORS]
    speeds = [round(rec["speed"] * f, 1) for f in SPEED_FACTORS]
    return powers, speeds


def _emit(polys, s_val, feed, m):
    out = []
    for pts in polys:
        x, y = pts[0]
        out += ["M5", f"G0 {_axes(x, y, m)}", f"M4 S{s_val}"]
        for x, y in pts[1:]:
            out.append(f"G1 {_axes(x, y, m)} F{feed:.0f}")
        out.append("M5")
    return out


def grid_gcode(m, operation, rec):
    """G-code for the test grid. m is the MachineSettings in use."""
    powers, speeds = grid_values(rec)
    out = ["; LightCut calibration grid", "G21", "G90", "M5"]
    label_s = round(m.s_max * LABEL_POWER / 100.0)
    label_feed = LABEL_SPEED * 60.0
    for i, sp in enumerate(speeds):
        for j, pw in enumerate(powers):
            x0 = ORIGIN[0] + j * PITCH
            y0 = ORIGIN[1] + i * PITCH
            s_val = round(m.s_max * pw / 100.0)
            feed = max(1.0, sp * 60.0)
            if operation == "Cut":
                segs = [[(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL),
                         (x0, y0 + CELL), (x0, y0)]]
            else:
                segs = hatch(rect_path(x0, y0, CELL, CELL), rec["interval"])
            out += _emit(segs, s_val, feed, m)
            label = f"{ROW_LABELS[i]}{j + 1}"
            out += _emit(flatten(text_path(label, x0, y0 + CELL + 4.0, 3.0)),
                         label_s, label_feed, m)
    out += ["M5", _home(m)]
    return out


class CalibrationDialog(QDialog):
    def __init__(self, parent, machine, material, operation, send_fn, on_saved):
        super().__init__(parent)
        self.setWindowTitle("Calibration")
        self.resize(680, 520)
        self.machine = machine
        self.material = material
        self.operation = operation
        self.send_fn = send_fn
        self.on_saved = on_saved

        self.rec, source = materials.recommend(machine.laser_type, machine.laser_watts,
                                               material, operation)
        title = QLabel(f"{material}  |  {operation}  |  {machine.laser_type} "
                       f"{machine.laser_watts:g} W")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout = QVBoxLayout(self)
        layout.addWidget(title)

        if self.rec is None:
            msg = QLabel(f"{material} has no preset for {operation.lower()}, "
                         "so there is no test grid. Choose another material or operation.")
            msg.setWordWrap(True)
            layout.addWidget(msg)
            close = QPushButton("Close")
            close.clicked.connect(self.reject)
            layout.addWidget(close)
            return

        source_text = ("Source: saved calibration" if source == "calibrated"
                       else "Source: estimate. Run the grid to replace it with your result.")
        layout.addWidget(QLabel(source_text))

        self.powers, self.speeds = grid_values(self.rec)
        self.table = QTableWidget(5, 5)
        self.table.setHorizontalHeaderLabels([f"{p:g}%" for p in self.powers])
        self.table.setVerticalHeaderLabels([f"{s:g} mm/s" for s in self.speeds])
        for i in range(5):
            for j in range(5):
                item = QTableWidgetItem(f"{ROW_LABELS[i]}{j + 1}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, j, item)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        pick = QHBoxLayout()
        pick.addWidget(QLabel("Best square: speed row"))
        self.row_combo = QComboBox()
        self.row_combo.addItems(list(ROW_LABELS))
        pick.addWidget(self.row_combo)
        pick.addWidget(QLabel("power column"))
        self.col_combo = QComboBox()
        self.col_combo.addItems([str(n) for n in range(1, 6)])
        pick.addWidget(self.col_combo)
        pick.addStretch(1)
        layout.addLayout(pick)

        buttons = QHBoxLayout()
        send = QPushButton(icon("play"), "Burn test grid")
        send.clicked.connect(self.burn_grid)
        save = QPushButton(icon("save"), "Save best square as profile")
        save.clicked.connect(self.save_best)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(send)
        buttons.addWidget(save)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def burn_grid(self):
        self.send_fn(grid_gcode(self.machine, self.operation, self.rec))

    def save_best(self):
        i = self.row_combo.currentIndex()
        j = self.col_combo.currentIndex()
        materials.save_profile(self.machine.laser_type, self.machine.laser_watts,
                               self.material, self.operation,
                               speed=self.speeds[i], power=self.powers[j],
                               passes=self.rec["passes"], interval=self.rec["interval"])
        self.on_saved()
        QMessageBox.information(
            self, "Saved",
            f"Saved {self.speeds[i]:g} mm/s at {self.powers[j]:g}% for {self.material} "
            f"({self.operation}). This laser will use it from now on.")
        self.accept()
