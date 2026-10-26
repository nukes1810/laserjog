"""G-code generation for GRBL and FluidNC lasers (diode or CO2).

Axes
  X  - always used.
  Y  - used normally. When the roller is enabled, Y is locked (never emitted)
       and the design's vertical position is sent to U as degrees.
  U  - only emitted when the roller is enabled.
  Z  - adjustment axis, emitted only when enabled. Each layer moves to its Z offset.

Canvas coordinates are millimetres with (0, 0) at the top-left. With
bottom_left=True the machine origin is the bottom-left corner (GRBL default).
Photos and image engraving become scan lines using the layer's power and speed.
"""
import math

from . import raster
from .geometry import flatten, hatch


def _axes(x, y, m):
    """Axis words for a canvas point, honouring roller and origin settings."""
    if m.roller_enabled:
        u = y * 360.0 / (math.pi * m.roller_diameter)
        return f"X{x:.3f} U{u:.3f}"
    my = (m.bed_height - y) if m.bottom_left else y
    return f"X{x:.3f} Y{my:.3f}"


def _home(m):
    return "G0 X0 U0" if m.roller_enabled else "G0 X0 Y0"


def layer_polylines(doc, index):
    """Vector paths on a layer as polylines (image shapes are handled separately)."""
    layer = doc.layers[index]
    polys = []
    for shape in doc.shapes:
        if shape.layer != index or shape.kind == "image":
            continue
        if layer.mode == "Fill":
            polys.extend(hatch(shape.path, layer.interval))
        else:
            polys.extend(flatten(shape.path))
    return polys


def _nearest_order(polys):
    """Greedy nearest-neighbour ordering to reduce travel distance."""
    remaining = list(polys)
    ordered = []
    cur = (0.0, 0.0)
    while remaining:
        best = min(
            range(len(remaining)),
            key=lambda k: (remaining[k][0][0] - cur[0]) ** 2 + (remaining[k][0][1] - cur[1]) ** 2,
        )
        pl = remaining.pop(best)
        ordered.append(pl)
        cur = pl[-1]
    return ordered


def raster_lines(shape, layer, m):
    """Scan-line G-code for one image. Rows alternate direction; equal cells are merged."""
    b = shape.path.boundingRect()
    power, _ = raster.process(shape.image["src"], b.width(), b.height(), shape.image)
    rows, cols = power.shape
    cw = b.width() / cols
    ch = b.height() / rows
    feed = max(1.0, layer.speed * 60.0)
    scale = m.s_max * layer.power / 100.0 / 255.0
    out = []
    for r in range(rows):
        y = b.top() + (r + 0.5) * ch
        order = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        vals = [int(power[r, c]) for c in order]
        xs = [b.left() + (c + 0.5) * cw for c in order]
        out += ["M5", f"G0 {_axes(xs[0], y, m)}", "M4"]
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[j + 1] == vals[i]:
                j += 1
            out.append(f"G1 {_axes(xs[j], y, m)} S{round(vals[i] * scale)} F{feed:.0f}")
            i = j + 1
        out.append("M5")
    return out


def generate(doc, m):
    """Return G-code lines for every enabled layer. m is a MachineSettings."""
    out = ["; LightCut export", "G21", "G90", "M5"]
    for li, layer in enumerate(doc.layers):
        if not layer.output:
            continue
        polys = layer_polylines(doc, li)
        images = [s for s in doc.shapes
                  if s.layer == li and s.kind == "image" and not s.image.get("reference")]
        if not polys and not images:
            continue
        s_val = round(m.s_max * layer.power / 100.0)
        feed = max(1.0, layer.speed * 60.0)
        out.append(f"; {layer.name}: {layer.operation}, {layer.power}% power, {layer.speed} mm/s")
        if m.z_enabled:
            out += ["M5", f"G0 Z{layer.z:.3f}"]
        image_lines = []
        for shape in images:
            image_lines += raster_lines(shape, layer, m)
        ordered = _nearest_order(polys)
        for _ in range(max(1, layer.passes)):
            for pts in ordered:
                x0, y0 = pts[0]
                out += ["M5", f"G0 {_axes(x0, y0, m)}", f"M4 S{s_val}"]
                for x, y in pts[1:]:
                    out.append(f"G1 {_axes(x, y, m)} F{feed:.0f}")
                out.append("M5")
            out += image_lines
    out += ["M5", _home(m)]
    return out


def generate_frame(doc, m):
    """Laser-off traversal of the design's bounding box, to check placement."""
    out = ["G21", "G90", "M5"]
    b = doc.bounds()
    if b is None:
        return out + [_home(m)]
    corners = [
        (b.left(), b.top()), (b.right(), b.top()),
        (b.right(), b.bottom()), (b.left(), b.bottom()), (b.left(), b.top()),
    ]
    for x, y in corners:
        out.append(f"G0 {_axes(x, y, m)}")
    out.append(_home(m))
    return out
