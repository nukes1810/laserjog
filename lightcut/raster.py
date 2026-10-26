"""Raster (image) engraving: turn a photo into a scan-ready burn map.

burn_map() returns a grayscale PIL image where 255 means "full laser power"
and 0 means "laser off". Each pixel is one scan cell of `interval` mm.
"""
from PIL import Image, ImageOps
from PySide6.QtGui import QImage


def burn_map(src, width_mm, height_mm, interval, negative=False, mode="Dither",
             threshold=128, flip_h=False, flip_v=False):
    cols = max(1, round(width_mm / interval))
    rows = max(1, round(height_mm / interval))
    img = src.convert("L").resize((cols, rows), Image.Resampling.BOX)
    if flip_h:
        img = ImageOps.mirror(img)
    if flip_v:
        img = ImageOps.flip(img)
    if not negative:
        img = ImageOps.invert(img)          # normal: dark areas burn
    if mode == "Dither":
        img = img.convert("1").convert("L")  # Floyd-Steinberg dithering
    else:
        t = threshold
        img = img.point(lambda v: 255 if v >= t else 0)
    return img


def preview_qimage(burn):
    """QImage preview where dark = burned, matching how the result looks on wood."""
    img = ImageOps.invert(burn.convert("L"))
    return to_qimage(img)


def to_qimage(img):
    img = img.convert("L")
    q = QImage(img.tobytes(), img.width, img.height, img.width,
               QImage.Format.Format_Grayscale8)
    return q.copy()
