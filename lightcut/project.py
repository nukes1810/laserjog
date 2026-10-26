"""Save and open LightCut project files (.lcproj, JSON)."""
import base64
import io
import json

from PIL import Image
from PySide6.QtGui import QPainterPath

from . import raster
from .document import Document, Layer, MachineSettings, Shape
from .geometry import flatten, rect_path

VERSION = 2


def save(path, doc, machine):
    data = {
        "version": VERSION,
        "machine": vars(machine),
        "layers": [vars(layer) for layer in doc.layers],
        "shapes": [],
    }
    for s in doc.shapes:
        item = {"layer": s.layer, "name": s.name, "kind": s.kind}
        if s.kind == "image":
            b = s.path.boundingRect()
            buf = io.BytesIO()
            s.image["src"].save(buf, "PNG")
            item["rect"] = [b.x(), b.y(), b.width(), b.height()]
            item["image"] = {k: v for k, v in s.image.items() if k not in ("src", "qimg")}
            item["src_png"] = base64.b64encode(buf.getvalue()).decode("ascii")
        else:
            item["polylines"] = flatten(s.path)
        data["shapes"].append(item)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def load(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    machine = MachineSettings(**data["machine"])
    doc = Document(layers=[Layer(**layer) for layer in data["layers"]], shapes=[])
    for it in data["shapes"]:
        if it["kind"] == "image":
            src = Image.open(io.BytesIO(base64.b64decode(it["src_png"]))).convert("L")
            settings = raster.fit_settings(it.get("image"))
            settings["src"] = src
            settings["qimg"] = None
            x, y, w, h = it["rect"]
            doc.shapes.append(Shape(rect_path(x, y, w, h), it["layer"], it["name"],
                                    False, "image", settings))
        else:
            p = QPainterPath()
            for pts in it["polylines"]:
                p.moveTo(*pts[0])
                for q in pts[1:]:
                    p.lineTo(*q)
                if len(pts) > 2 and pts[0] == pts[-1]:
                    p.closeSubpath()
            doc.shapes.append(Shape(p, it["layer"], it["name"], False, it.get("kind", "vector"), None))
    return doc, machine
