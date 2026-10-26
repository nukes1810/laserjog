"""Read firmware version and settings from a GRBL or FluidNC controller.

$I reports the firmware version and $$ lists settings such as:
  $30  maximum spindle (laser) S value
  $130 X maximum travel (mm), $131 Y maximum travel (mm)
"""
import re
import time

import serial

_SETTING = re.compile(r"^\$(\d+)=([-+]?[\d.]+)")
_VERSION = re.compile(r"\[VER:([^\]]*)\]")


def parse_settings(lines):
    settings = {}
    for ln in lines:
        m = _SETTING.match(ln.strip())
        if m:
            settings[int(m.group(1))] = float(m.group(2))
    return settings


def parse_version(lines):
    for ln in lines:
        m = _VERSION.search(ln)
        if m:
            return m.group(1).strip(": ")
    return ""


def _collect(ser, timeout=5.0):
    lines = []
    end = time.time() + timeout
    while time.time() < end:
        raw = ser.readline()
        if not raw:
            continue
        ln = raw.decode(errors="replace").strip()
        if ln == "ok":
            break
        if ln.lower().startswith("error"):
            raise RuntimeError(f"Controller returned {ln}")
        lines.append(ln)
    return lines


def read_controller(port, baud=115200):
    """Return {'version': str, 'settings': {id: value}}."""
    with serial.Serial(port, baud, timeout=0.3) as ser:
        time.sleep(2.0)                # GRBL resets when the port opens
        ser.reset_input_buffer()
        ser.write(b"$I\n")
        info_lines = _collect(ser)
        ser.write(b"$$\n")
        setting_lines = _collect(ser)
    return {
        "version": parse_version(info_lines),
        "settings": parse_settings(setting_lines),
    }
