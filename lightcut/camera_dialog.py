"""Camera dialog: capture the bed, auto-detect the sheet, and place it as a reference photo."""
import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout,
)

from . import vision


class CameraDialog(QDialog):
    """After a successful capture, result_pil holds the top-down grayscale sheet
    and sheet_w / sheet_h hold its size in mm."""

    def __init__(self, parent, bed_w, bed_h):
        super().__init__(parent)
        self.setWindowTitle("Camera: scan material")
        self.resize(640, 560)
        self.cap = None
        self.result_pil = None
        self.sheet_w = bed_w
        self.sheet_h = bed_h

        self.cam_index = QSpinBox()
        self.cam_index.setRange(0, 10)
        self.sheet_w_spin = QDoubleSpinBox()
        self.sheet_w_spin.setRange(10, 3000)
        self.sheet_w_spin.setValue(bed_w)
        self.sheet_w_spin.setSuffix(" mm")
        self.sheet_h_spin = QDoubleSpinBox()
        self.sheet_h_spin.setRange(10, 3000)
        self.sheet_h_spin.setValue(bed_h)
        self.sheet_h_spin.setSuffix(" mm")
        form = QFormLayout()
        form.addRow("Camera index", self.cam_index)
        form.addRow("Sheet width", self.sheet_w_spin)
        form.addRow("Sheet height", self.sheet_h_spin)

        self.preview = QLabel("Press Capture to photograph the bed.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(560, 360)
        self.preview.setStyleSheet("background:#222;color:#aaa;")

        self.capture_btn = QPushButton("Capture and detect sheet")
        self.capture_btn.clicked.connect(self.capture)
        self.add_btn = QPushButton("Place on canvas")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.accept)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        for b in (self.capture_btn, self.add_btn, close_btn):
            buttons.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview, 1)
        layout.addLayout(buttons)

    def _release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def capture(self):
        try:
            if self.cap is None:
                self.cap = vision.open_camera(self.cam_index.value())
            frame = vision.grab_frame(self.cap)
            corners = vision.find_sheet_corners(frame)
            self.sheet_w = self.sheet_w_spin.value()
            self.sheet_h = self.sheet_h_spin.value()
            warped = vision.warp_to_sheet(frame, corners, self.sheet_w, self.sheet_h)
            self.result_pil = vision.bgr_to_pil_gray(warped)
        except Exception as exc:
            QMessageBox.warning(self, "Scan failed", str(exc))
            return
        self._show(warped)
        self.add_btn.setEnabled(True)

    def _show(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(
            self.preview.width(), self.preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def closeEvent(self, event):
        self._release()
        super().closeEvent(event)

    def reject(self):
        self._release()
        super().reject()

    def accept(self):
        self._release()
        super().accept()
