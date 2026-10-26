"""Stream G-code to a GRBL controller over serial, one line at a time."""
import time

import serial
from PySide6.QtCore import QThread, Signal


class GrblSender(QThread):
    progress = Signal(int, int)   # lines done, total
    log = Signal(str)             # controller messages
    done = Signal(bool, str)      # success, message

    def __init__(self, port, baud, lines, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.lines = [ln for ln in lines if ln.strip() and not ln.strip().startswith(";")]
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            with serial.Serial(self.port, self.baud, timeout=0.2) as ser:
                time.sleep(2.0)                    # GRBL resets when the port opens
                ser.reset_input_buffer()
                total = len(self.lines)
                for i, line in enumerate(self.lines):
                    if self._stop:
                        ser.write(b"!")            # feed hold
                        ser.write(b"\x18")         # soft reset
                        self.done.emit(False, "Stopped by user")
                        return
                    ser.write((line + "\n").encode())
                    while True:
                        if self._stop:
                            break
                        resp = ser.readline().decode(errors="replace").strip()
                        if not resp:
                            continue
                        if resp == "ok":
                            break
                        if resp.lower().startswith("error"):
                            self.done.emit(False, f"Controller {resp} on line: {line}")
                            return
                        self.log.emit(resp)
                    self.progress.emit(i + 1, total)
                self.done.emit(True, f"Sent {total} lines")
        except Exception as exc:  # serial errors, port busy, etc.
            self.done.emit(False, str(exc))
