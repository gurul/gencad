"""Synthetic geometry dicts shaped like dump_board output."""


def board_geo(**extra):
    geo = {
        "outline": {"type": "rect", "box": [-20.0, -15.0, 20.0, 15.0]},
        "layers": ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"],
        "rules": {"clearance": 0.1, "edge_clearance": 0.3,
                  "hole_clearance": 0.2},
        "pads": [], "holes": [], "tracks": [], "vias": [],
        "keepouts": [], "zones": [], "copper_gfx": [],
    }
    geo.update(extra)
    return geo


def th_pad(net="GND", x=0.0, y=0.0, inner=("In1.Cu", "In2.Cu")):
    """Through-hole pad as dump_board now records it (inner layers named)."""
    return {"ref": "J1", "num": "1", "net": net,
            "layers": ["F", "B"] + list(inner),
            "box": [x - 0.85, y - 0.85, x + 0.85, y + 0.85],
            "size": [1.7, 1.7], "smd": False}


def smd_pad(net="GND", x=0.0, y=0.0):
    return {"ref": "R1", "num": "1", "net": net, "layers": ["F"],
            "box": [x - 0.4, y - 0.4, x + 0.4, y + 0.4],
            "size": [0.8, 0.8], "smd": True}


# 4 mm square keep-out spanning x,y in [-2, 2] on every copper layer
SQUARE_KO = {"layers": ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"],
             "no_tracks": True, "no_vias": True,
             "poly": [[-2.0, -2.0], [2.0, -2.0], [2.0, 2.0], [-2.0, 2.0]]}
