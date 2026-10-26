"""Photo and image processing for engraving.

process() turns a picture into a grid of burn values, one per scan line cell:
255 means full laser power and 0 means laser off. Dark areas burn by default;
Negative burns the light areas instead.

Pipeline: resize to the scan grid, optional sharpening, flip, auto levels,
brightness, contrast, gamma, then dithering to on/off cells.
"""
import numpy as np
from PIL import Image, ImageFilter
from PySide6.QtGui import QImage

DITHERS = ["Atkinson", "Floyd-Steinberg", "Jarvis", "Halftone", "Threshold"]

DEFAULTS = {
    "negative": False,
    "dither": "Atkinson",
    "threshold": 128,
    "interval": 0.1,
    "auto_levels": True,
    "brightness": 0,
    "contrast": 0,
    "gamma": 1.0,
    "sharpen": 0,
    "flip_h": False,
    "flip_v": False,
}

# Largest scan grid we process; bigger images are resampled to fit.
MAX_CELLS = 2_500_000

# Error diffusion kernels: (dx, dy, weight) with a shared divisor.
_FLOYD = [(1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)]
_FLOYD_DIV = 16
# Atkinson spreads 6/8 of the error, which keeps highlights clean.
_ATKINSON = [(1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)]
_ATKINSON_DIV = 8
_JARVIS = [(1, 0, 7), (2, 0, 5), (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5),
           (2, 1, 3), (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1)]
_JARVIS_DIV = 48

# 4x4 clustered-dot matrix: dots grow in clumps, which survives laser spot size.
_CLUSTER = (np.array([[12, 5, 6, 13], [4, 0, 1, 7], [11, 3, 2, 8], [15, 10, 9, 14]],
                     np.float64) + 0.5) / 16.0


def fit_settings(settings):
    """Merge saved settings over the defaults so older files still load."""
    return {**DEFAULTS, **(settings or {})}


def grid_size(width_mm, height_mm, interval):
    interval = max(0.02, float(interval))
    cols = max(1, round(width_mm / interval))
    rows = max(1, round(height_mm / interval))
    if cols * rows > MAX_CELLS:
        scale = (cols * rows / MAX_CELLS) ** 0.5
        cols = max(1, int(cols / scale))
        rows = max(1, int(rows / scale))
    return cols, rows


def _diffuse(burn, kernel, divisor):
    rows, cols = burn.shape
    a = burn.astype(np.float64).ravel().tolist()
    out = [0.0] * (rows * cols)
    for r in range(rows):
        base = r * cols
        for c in range(cols):
            i = base + c
            old = a[i]
            new = 1.0 if old >= 0.5 else 0.0
            out[i] = new
            err = old - new
            if err == 0.0:
                continue
            for dx, dy, w in kernel:
                nr = r + dy
                nc = c + dx
                if 0 <= nr < rows and 0 <= nc < cols:
                    a[nr * cols + nc] += err * w / divisor
    return np.array(out, np.float64).reshape(rows, cols)


def process(src, width_mm, height_mm, settings):
    """Return (power, preview).

    power is a uint8 array (rows x cols) of burn values, 0 or 255 in most modes.
    preview is a QImage where dark means burned, as it looks on the material.
    """
    s = fit_settings(settings)
    cols, rows = grid_size(width_mm, height_mm, s["interval"])
    img = src.convert("L").resize((cols, rows), Image.Resampling.LANCZOS)
    if s["sharpen"] > 0:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=int(s["sharpen"]), threshold=2))
    g = np.asarray(img, np.float64) / 255.0
    if s["flip_h"]:
        g = g[:, ::-1]
    if s["flip_v"]:
        g = g[::-1, :]
    g = np.ascontiguousarray(g)
    if s["auto_levels"]:
        lo, hi = np.percentile(g, [1, 99])
        if hi - lo > 1e-3:
            g = np.clip((g - lo) / (hi - lo), 0.0, 1.0)
    if s["brightness"]:
        g = np.clip(g + s["brightness"] / 100.0, 0.0, 1.0)
    if s["contrast"]:
        k = 1.0 + s["contrast"] / 100.0
        g = np.clip((g - 0.5) * k + 0.5, 0.0, 1.0)
    if s["gamma"] != 1.0:
        g = np.power(g, s["gamma"])

    burn = g if s["negative"] else 1.0 - g
    kind = s["dither"]
    if kind == "Floyd-Steinberg":
        on = _diffuse(burn, _FLOYD, _FLOYD_DIV)
    elif kind == "Jarvis":
        on = _diffuse(burn, _JARVIS, _JARVIS_DIV)
    elif kind == "Halftone":
        tile = np.tile(_CLUSTER, (rows // 4 + 1, cols // 4 + 1))[:rows, :cols]
        on = (burn >= tile).astype(np.float64)
    elif kind == "Threshold":
        on = (burn >= s["threshold"] / 255.0).astype(np.float64)
    else:
        on = _diffuse(burn, _ATKINSON, _ATKINSON_DIV)

    power = (on * 255).astype(np.uint8)
    return power, to_qimage(255 - power)


def to_qimage(arr):
    """uint8 2-D array -> grayscale QImage."""
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape
    return QImage(arr.tobytes(), w, h, w, QImage.Format.Format_Grayscale8).copy()


def pil_to_qimage(img):
    return to_qimage(np.asarray(img.convert("L"), np.uint8))
