"""Document model: layers (laser settings), shapes, and machine configuration."""
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtGui import QPainterPath

LAYER_COLORS = ["#ff3b30", "#007aff", "#34c759", "#ff9500",
                "#af52de", "#00c7be", "#ffcc00", "#8e8e93"]


@dataclass(eq=False)
class Layer:
    name: str
    color: str
    mode: str = "Line"      # "Line" = vector cut/outline, "Fill" = hatch scan (vectors only)
    power: float = 50.0     # percent of the machine's maximum S value
    speed: float = 100.0    # mm/s
    passes: int = 1
    interval: float = 0.1   # hatch spacing in mm (Fill mode only)
    z: float = 0.0          # Z adjustment for this layer, mm (used when Z axis is enabled)
    output: bool = True     # include this layer when sending


@dataclass(eq=False)
class Shape:
    path: QPainterPath                 # outline in mm; for images, the placement rectangle
    layer: int = 0
    name: str = "Shape"
    selected: bool = False
    kind: str = "vector"               # "vector" or "image"
    image: Optional[dict] = None       # image settings (only for kind == "image")


@dataclass
class MachineSettings:
    s_max: int = 1000
    bed_width: float = 400.0
    bed_height: float = 300.0
    bottom_left: bool = True        # GRBL convention: origin at bottom-left
    z_enabled: bool = False         # Z adjustment (focus / table height) axis present
    roller_enabled: bool = False    # roller on U axis; when True, Y is locked and U is driven
    roller_diameter: float = 50.0   # mm, used to convert mm of travel to U degrees
    text_size: float = 10.0         # default text height, mm


@dataclass
class Document:
    layers: list = field(default_factory=lambda: [
        Layer("C00 Cut", LAYER_COLORS[0], "Line", 80.0, 20.0),
        Layer("C01 Engrave", LAYER_COLORS[1], "Fill", 30.0, 150.0, interval=0.1),
    ])
    shapes: list = field(default_factory=list)

    def add_layer(self):
        i = len(self.layers)
        self.layers.append(Layer(f"C{i:02d}", LAYER_COLORS[i % len(LAYER_COLORS)]))
        return i

    def add_shape(self, path, layer, name="Shape", kind="vector", image=None):
        shape = Shape(path, layer, name, False, kind, image)
        self.shapes.append(shape)
        return shape

    def bounds(self):
        result = None
        for s in self.shapes:
            r = s.path.boundingRect()
            result = r if result is None else result.united(r)
        return result
