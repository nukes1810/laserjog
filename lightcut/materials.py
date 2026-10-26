"""Material presets, calibrated profiles, and recommended settings.

The built-in values are starting estimates for a 10 W laser. For other powers
the speed is scaled in proportion to output power, and the power percentage is
kept. Calibration results saved for a specific laser and material replace the
estimate. Always run a test grid before a real job.
"""
import json
from pathlib import Path

REF_WATTS = 10.0
MAX_SPEED = 800.0
PROFILE_FILE = Path.home() / ".lightcut" / "profiles.json"

# speed in mm/s, power in %, passes, hatch spacing in mm (reference 10 W laser)
MATERIALS = {
    "Birch plywood": {
        "Engrave": dict(speed=250, power=35, passes=1, interval=0.1),
        "Cut": dict(speed=8, power=100, passes=3, interval=0.1),
    },
    "MDF": {
        "Engrave": dict(speed=250, power=40, passes=1, interval=0.1),
        "Cut": dict(speed=7, power=100, passes=3, interval=0.1),
    },
    "Cardboard": {
        "Engrave": dict(speed=300, power=25, passes=1, interval=0.1),
        "Cut": dict(speed=40, power=60, passes=1, interval=0.1),
    },
    "Acrylic (cast)": {
        "Engrave": dict(speed=150, power=60, passes=1, interval=0.1),
        "Cut": dict(speed=10, power=100, passes=2, interval=0.1),
    },
    "Leather": {
        "Engrave": dict(speed=150, power=25, passes=1, interval=0.1),
        "Cut": dict(speed=20, power=60, passes=2, interval=0.1),
    },
    "Anodized aluminum": {
        "Engrave": dict(speed=100, power=50, passes=1, interval=0.1),
        "Cut": None,
    },
    "Glass (frosting)": {
        "Engrave": dict(speed=200, power=40, passes=1, interval=0.1),
        "Cut": None,
    },
    "Slate": {
        "Engrave": dict(speed=150, power=50, passes=1, interval=0.1),
        "Cut": None,
    },
}


def material_names():
    return list(MATERIALS)


def laser_key(laser_type, watts):
    return f"{laser_type}-{watts:g}W"


def _profile_key(laser_type, watts, material, operation):
    return f"{laser_key(laser_type, watts)}|{material}|{operation}"


def _load():
    try:
        return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_profile(laser_type, watts, material, operation, speed, power, passes, interval):
    data = _load()
    data[_profile_key(laser_type, watts, material, operation)] = {
        "speed": float(speed), "power": float(power),
        "passes": int(passes), "interval": float(interval),
    }
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def recommend(laser_type, watts, material, operation):
    """Return (settings, source). source is 'calibrated' or 'estimate'.

    settings is None when the material has no preset for that operation.
    """
    saved = _load().get(_profile_key(laser_type, watts, material, operation))
    if saved:
        return dict(saved), "calibrated"
    base = MATERIALS.get(material, {}).get(operation)
    if not base:
        return None, "none"
    scale = max(0.1, float(watts)) / REF_WATTS
    return {
        "speed": round(min(MAX_SPEED, base["speed"] * scale), 1),
        "power": float(base["power"]),
        "passes": base["passes"],
        "interval": base["interval"],
    }, "estimate"
