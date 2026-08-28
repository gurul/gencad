"""Pure-python clearance oracle over a dumped board geometry.

Independent of pcbnew and of any router: given ``geometry.json`` from
:mod:`dump_board`, answer "would this track segment / via be legal?" with
plain distance math. Routers use it as their acceptance gate; anything it
rejects never reaches the board, and because it shares no code with the
mask-based routers it also catches their bugs.

    from pcbtools.clearance import Board
    b = Board.load("geometry.json")
    b.seg_clear(x1, y1, x2, y2, layer="B.Cu", net="SDA", width=0.2)  # -> []
    b.via_clear(x, y, net="SDA", dia=0.5)                            # -> []
    b.check_path(net, elements)   # elements as emitted by the routers

All coordinates are mm in the dump's origin frame. A non-empty return is a
list of human-readable violation strings.
"""
import json
import math


def _pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _seg_seg(a, b):
    (x1, y1, x2, y2), (x3, y3, x4, y4) = a, b
    def ccw(ax, ay, bx, by, cx, cy):
        return (by - ay) * (cx - ax) - (bx - ax) * (cy - ay)
    d1 = ccw(x3, y3, x4, y4, x1, y1)
    d2 = ccw(x3, y3, x4, y4, x2, y2)
    d3 = ccw(x1, y1, x2, y2, x3, y3)
    d4 = ccw(x1, y1, x2, y2, x4, y4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(_pt_seg(x1, y1, x3, y3, x4, y4),
               _pt_seg(x2, y2, x3, y3, x4, y4),
               _pt_seg(x3, y3, x1, y1, x2, y2),
               _pt_seg(x4, y4, x1, y1, x2, y2))


def _seg_box(seg, box):
    l, t, r, b = box
    if (l <= seg[0] <= r and t <= seg[1] <= b) or \
       (l <= seg[2] <= r and t <= seg[3] <= b):
        return 0.0
    return min(_seg_seg(seg, e) for e in
               ((l, t, r, t), (r, t, r, b), (r, b, l, b), (l, b, l, t)))


def _in_poly(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xin:
                inside = not inside
    return inside


class Board:
    """Clearance oracle. ``hole_margin`` pads the drill radius to stand in
    for the annular ring, which the dump does not model per-layer."""

    def __init__(self, geo, clearance=None, edge_clearance=None,
                 hole_margin=0.3):
        self.g = geo
        r = geo.get("rules", {})
        self.clearance = clearance if clearance is not None \
            else r.get("clearance", 0.15)
        self.edge_clearance = edge_clearance if edge_clearance is not None \
            else r.get("edge_clearance", 0.3)
        self.hole_margin = hole_margin
        self.outline = geo["outline"]
        # layer aliases: accept both "B" and "B.Cu"
        self._alias = {}
        for name in geo["layers"]:
            self._alias[name] = name
            self._alias[name.replace(".Cu", "")] = name

    @classmethod
    def load(cls, path, **kw):
        return cls(json.load(open(path)), **kw)

    def layer(self, name):
        return self._alias.get(name, name)

    # -- primitive predicates -------------------------------------------------
    def _off_board(self, x, y, half):
        if self.outline["type"] == "circle":
            return math.hypot(x, y) + half > \
                self.outline["r"] - self.edge_clearance
        l, t, r, b = self.outline["box"]
        m = self.edge_clearance + half
        return not (l + m <= x <= r - m and t + m <= y <= b - m)

    def _keepout_hit(self, x, y, layer, kind):
        for ko in self.g.get("keepouts", []):
            if not ko.get("no_tracks" if kind == "track" else "no_vias"):
                continue
            if kind == "track" and layer not in ko["layers"]:
                continue
            if ko["poly"] and _in_poly(x, y, ko["poly"]):
                return True
        return False

    def _pad_on_layer(self, p, layer):
        short = layer.replace(".Cu", "")
        if short in ("F", "B"):
            return short in p["layers"]
        return False        # SMD pads never obstruct inner layers; holes do

    def pad_box(self, p):
        if p.get("custom") and "anchor" in p:
            ax, ay = p["anchor"]
            hw = max(p["size"]) / 2 or 0.45
            return [ax - hw, ay - hw, ax + hw, ay + hw]
        return p["box"]

    # -- public checks --------------------------------------------------------
    def seg_clear(self, x1, y1, x2, y2, layer, net, width=0.2,
                  exempt_gfx_nets=()):
        layer = self.layer(layer)
        v = []
        half = width / 2.0
        seg = (x1, y1, x2, y2)
        for px, py in ((x1, y1), (x2, y2)):
            if self._off_board(px, py, half):
                v.append("edge: (%.2f,%.2f)" % (px, py))
                break
        steps = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.25) + 1)
        for k in range(steps + 1):
            px = x1 + (x2 - x1) * k / steps
            py = y1 + (y2 - y1) * k / steps
            if self._keepout_hit(px, py, layer, "track"):
                v.append("keepout: (%.2f,%.2f) on %s" % (px, py, layer))
                break
        for p in self.g["pads"]:
            if p["net"] == net or not self._pad_on_layer(p, layer):
                continue
            d = _seg_box(seg, self.pad_box(p))
            if d < half + self.clearance:
                v.append("pad %s.%s [%s]: %.3f" % (p["ref"], p["num"],
                                                   p["net"], d))
        for t in self.g["tracks"]:
            if t["net"] == net or t["layer"] != layer:
                continue
            d = _seg_seg(seg, (t["x1"], t["y1"], t["x2"], t["y2"]))
            if d < half + t["w"] / 2 + self.clearance:
                v.append("track [%s]: %.3f" % (t["net"], d))
        for via in self.g["vias"]:
            if via["net"] == net:
                continue
            d = _pt_seg(via["x"], via["y"], *seg)
            if d < half + via["dia"] / 2 + self.clearance:
                v.append("via [%s]: %.3f" % (via["net"], d))
        for h in self.g.get("holes", []):
            if h["net"] == net:
                continue
            d = _pt_seg(h["x"], h["y"], *seg)
            if d < half + h["r"] + self.hole_margin + self.clearance:
                v.append("hole [%s]: %.3f" % (h["net"], d))
        for gfx in self.g.get("copper_gfx", []):
            if gfx["layer"] != layer or net in exempt_gfx_nets:
                continue
            d = _seg_seg(seg, (gfx["x1"], gfx["y1"], gfx["x2"], gfx["y2"]))
            if d < half + gfx.get("w", 0.2) / 2 + self.clearance:
                v.append("copper gfx %s: %.3f" % (gfx["ref"], d))
        return v

    def via_clear(self, x, y, net, dia=0.5, exempt_gfx_nets=()):
        v = []
        half = dia / 2.0
        if self._off_board(x, y, half):
            v.append("edge")
        if self._keepout_hit(x, y, "F.Cu", "via"):
            v.append("keepout")
        for p in self.g["pads"]:
            if p["net"] == net:
                continue
            d = _seg_box((x, y, x, y), self.pad_box(p))
            if d < half + self.clearance:
                v.append("pad %s.%s [%s]: %.3f" % (p["ref"], p["num"],
                                                   p["net"], d))
        for t in self.g["tracks"]:
            if t["net"] == net:
                continue
            d = _pt_seg(x, y, t["x1"], t["y1"], t["x2"], t["y2"])
            if d < half + t["w"] / 2 + self.clearance:
                v.append("track [%s] %s: %.3f" % (t["net"], t["layer"], d))
        for via in self.g["vias"]:
            if via["net"] == net:
                continue
            d = math.hypot(x - via["x"], y - via["y"])
            if d < half + via["dia"] / 2 + self.clearance:
                v.append("via [%s]: %.3f" % (via["net"], d))
        for h in self.g.get("holes", []):
            if h["net"] == net:
                continue
            d = math.hypot(x - h["x"], y - h["y"])
            if d < half + h["r"] + self.hole_margin + self.clearance:
                v.append("hole [%s]: %.3f" % (h["net"], d))
        for gfx in self.g.get("copper_gfx", []):
            if net in exempt_gfx_nets:
                continue
            d = _pt_seg(x, y, gfx["x1"], gfx["y1"], gfx["x2"], gfx["y2"])
            if d < half + gfx.get("w", 0.2) / 2 + self.clearance:
                v.append("copper gfx %s: %.3f" % (gfx["ref"], d))
        return v

    def check_path(self, net, elements, **kw):
        out = []
        for e in elements:
            if e["type"] == "track":
                out += ["seg(%s %.2f,%.2f->%.2f,%.2f): %s"
                        % (e["layer"], e["x1"], e["y1"], e["x2"], e["y2"], m)
                        for m in self.seg_clear(e["x1"], e["y1"], e["x2"],
                                                e["y2"], e["layer"], net,
                                                e.get("w", 0.2), **kw)]
            elif e["type"] == "via":
                out += ["via(%.2f,%.2f): %s" % (e["x"], e["y"], m)
                        for m in self.via_clear(e["x"], e["y"], net,
                                                e.get("dia", 0.5), **kw)]
        return out

    # -- mutation (commit accepted routes so later checks see them) -----------
    def commit(self, net, elements):
        for e in elements:
            if e["type"] == "track":
                self.g["tracks"].append({"net": net,
                                         "layer": self.layer(e["layer"]),
                                         "x1": e["x1"], "y1": e["y1"],
                                         "x2": e["x2"], "y2": e["y2"],
                                         "w": e.get("w", 0.2)})
            else:
                self.g["vias"].append({"net": net, "x": e["x"], "y": e["y"],
                                       "dia": e.get("dia", 0.5),
                                       "drill": round(
                                           e.get("dia", 0.5) - 0.2, 3)})
