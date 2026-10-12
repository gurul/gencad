#!/usr/bin/env python3
"""Dump a KiCad board to a routing-oriented geometry JSON.

Everything downstream (the clearance checker, the routers, the writer)
works from this one file instead of live pcbnew objects, which keeps the
fragile SWIG bindings confined to two scripts (this one and write_board).

Extracted per board:
  origin        auto-detected center of the Edge.Cuts bounding box (mm)
  outline       {"type": "circle", "r": ...} when the edge is a circle,
                else {"type": "rect", "box": [l, t, r, b]}
  layers        enabled copper layer names (KiCad canonical: F.Cu, In1.Cu, ...)
  pads          per-pad net, F/B presence, bounding box, size
  holes         every drilled hole (PTH net or null for NPTH) with radius
  tracks/vias   all existing copper with nets, layers, widths
  keepouts      rule areas: layers + which objects they forbid + polygon
  copper_gfx    footprint copper graphics (coils, logos) as stroked segments
  zones         filled-zone nets and layers (planes)

Coordinates are mm relative to the detected origin, +y down (screen frame).

    python dump_board.py BOARD.kicad_pcb [-o geometry.json]
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_env import ensure_pcbnew

pcbnew = ensure_pcbnew()


CIRCLE_SIDES = 32      # circle outlines are emitted as this many-gon


def gfx_segments(g, ref, layer_name, X, Y, M):
    """Stroked outline segments for one footprint copper PCB_SHAPE.

    Segments and arcs map 1:1 (arcs keep ``arc_mid``); rects emit their four
    sides, circles a CIRCLE_SIDES-gon, polygons every outline edge. Fill is
    not modelled: only the outline obstructs. Raises on an unsupported shape
    so the caller can warn."""
    lay = layer_name[int(g.GetLayer())]
    w = round(max(0.0, M(g.GetWidth())), 3)
    st = g.GetShape()

    def seg(ax, ay, bx, by):
        return {"ref": ref, "layer": lay, "x1": X(ax), "y1": Y(ay),
                "x2": X(bx), "y2": Y(by), "w": w}

    def ring(pts):
        n = len(pts)
        return [seg(pts[i][0], pts[i][1], pts[(i + 1) % n][0],
                    pts[(i + 1) % n][1]) for i in range(n) if n > 1]

    if st in (pcbnew.SHAPE_T_SEGMENT, pcbnew.SHAPE_T_ARC):
        s, e = g.GetStart(), g.GetEnd()
        out = seg(s.x, s.y, e.x, e.y)
        if st == pcbnew.SHAPE_T_ARC:
            m = g.GetArcMid()
            out["arc_mid"] = [X(m.x), Y(m.y)]
        return [out]
    if st == pcbnew.SHAPE_T_RECT:
        return ring([(c.x, c.y) for c in g.GetRectCorners()])
    if st == pcbnew.SHAPE_T_CIRCLE:
        c, r = g.GetCenter(), g.GetRadius()
        return ring([(c.x + r * math.cos(2 * math.pi * k / CIRCLE_SIDES),
                      c.y + r * math.sin(2 * math.pi * k / CIRCLE_SIDES))
                     for k in range(CIRCLE_SIDES)])
    if st == pcbnew.SHAPE_T_POLY:
        ps = g.GetPolyShape()
        out = []
        for oi in range(ps.OutlineCount()):
            ol = ps.COutline(oi)
            out += ring([(ol.CPoint(i).x, ol.CPoint(i).y)
                         for i in range(ol.PointCount())])
        return out
    raise ValueError("unsupported shape type")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()
    out_path = args.out or os.path.splitext(args.board)[0] + ".geometry.json"

    board = pcbnew.LoadBoard(os.path.abspath(args.board))

    def M(v):
        return pcbnew.ToMM(v)

    # ---- origin + outline from Edge.Cuts ------------------------------------
    edges = [d for d in board.GetDrawings()
             if d.GetLayer() == pcbnew.Edge_Cuts]
    circle = None
    if len(edges) == 1 and edges[0].GetClass() == "PCB_SHAPE" and \
            edges[0].GetShape() == pcbnew.SHAPE_T_CIRCLE:
        circle = edges[0]
    if edges:
        bb = edges[0].GetBoundingBox()
        for d in edges[1:]:
            bb.Merge(d.GetBoundingBox())
        cx = M(bb.GetLeft() + bb.GetWidth() // 2)
        cy = M(bb.GetTop() + bb.GetHeight() // 2)
    else:
        bb = board.GetBoardEdgesBoundingBox()
        cx = M(bb.GetLeft() + bb.GetWidth() // 2)
        cy = M(bb.GetTop() + bb.GetHeight() // 2)
    if circle is not None:
        c = circle.GetCenter()
        cx, cy = M(c.x), M(c.y)
        outline = {"type": "circle", "r": round(M(circle.GetRadius()), 3)}
    else:
        outline = {"type": "rect",
                   "box": [round(M(bb.GetLeft()) - cx, 3),
                           round(M(bb.GetTop()) - cy, 3),
                           round(M(bb.GetRight()) - cx, 3),
                           round(M(bb.GetBottom()) - cy, 3)]}

    def X(v):
        return round(M(v) - cx, 3)

    def Y(v):
        return round(M(v) - cy, 3)

    layer_name = {}
    for lid in board.GetEnabledLayers().CuStack():
        layer_name[int(lid)] = board.GetLayerName(lid)
    copper_ids = set(layer_name)
    inner_ids = sorted(lid for lid in copper_ids
                       if lid not in (int(pcbnew.F_Cu), int(pcbnew.B_Cu)))

    pads, holes, copper_gfx = [], [], []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for p in fp.Pads():
            bbp = p.GetBoundingBox()
            sz = p.GetSize()
            entry = {
                "ref": ref, "num": p.GetNumber(), "net": p.GetNetname(),
                # outer faces as "F"/"B"; inner copper by canonical name
                # (through-hole pads carry copper on In*.Cu too)
                "layers": [s for s, lid in (("F", pcbnew.F_Cu),
                                            ("B", pcbnew.B_Cu))
                           if p.IsOnLayer(lid)] +
                          [layer_name[lid] for lid in inner_ids
                           if p.IsOnLayer(lid)],
                "box": [X(bbp.GetLeft()), Y(bbp.GetTop()),
                        X(bbp.GetRight()), Y(bbp.GetBottom())],
                "size": [round(M(sz.x), 3), round(M(sz.y), 3)],
                "smd": p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD,
            }
            # custom pads (e.g. printed coils) have primitive-spanning
            # bboxes; record the anchor separately so checkers can choose
            if p.GetShape() == pcbnew.PAD_SHAPE_CUSTOM:
                pos = p.GetPosition()
                entry["custom"] = True
                entry["anchor"] = [X(pos.x), Y(pos.y)]
            pads.append(entry)
            dr = p.GetDrillSize()
            if dr.x > 0 or dr.y > 0:
                pos = p.GetPosition()
                holes.append({"x": X(pos.x), "y": Y(pos.y),
                              "r": round(max(M(dr.x), M(dr.y)) / 2, 3),
                              "net": p.GetNetname() or None})
        for g in fp.GraphicalItems():
            if not hasattr(g, "GetLayer") or int(g.GetLayer()) not in copper_ids:
                continue
            if g.GetClass() != "PCB_SHAPE":
                continue
            try:
                copper_gfx += gfx_segments(g, ref, layer_name, X, Y, M)
            except Exception as exc:
                sys.stderr.write(
                    "dump_board: WARNING skipped %s copper shape %s on %s: "
                    "%s\n" % (ref, g.ShowShape(),
                              layer_name[int(g.GetLayer())], exc))

    tracks, vias = [], []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            pos = t.GetPosition()
            vias.append({"net": t.GetNetname(), "x": X(pos.x), "y": Y(pos.y),
                         "dia": round(M(t.GetWidth()), 3),
                         "drill": round(M(t.GetDrill()), 3)})
        else:
            tracks.append({"net": t.GetNetname(),
                           "layer": layer_name.get(int(t.GetLayer()), "?"),
                           "x1": X(t.GetStart().x), "y1": Y(t.GetStart().y),
                           "x2": X(t.GetEnd().x), "y2": Y(t.GetEnd().y),
                           "w": round(M(t.GetWidth()), 3)})

    keepouts, zones = [], []
    # footprint-owned rule areas (e.g. a module's antenna keep-out) are not
    # in board.Zones(); add them so checkers and routers honour them
    fp_rule_areas = [z for fp in board.GetFootprints() for z in fp.Zones()
                     if z.GetIsRuleArea()]
    for z in list(board.Zones()) + fp_rule_areas:
        lays = [layer_name[int(l)] for l in z.GetLayerSet().CuStack()
                if int(l) in layer_name]
        if z.GetIsRuleArea():
            poly = []
            o = z.Outline()
            if o.OutlineCount():
                ol = o.COutline(0)
                for i in range(ol.PointCount()):
                    pt = ol.CPoint(i)
                    poly.append([X(pt.x), Y(pt.y)])
            keepouts.append({"layers": lays,
                             "no_tracks": z.GetDoNotAllowTracks(),
                             "no_vias": z.GetDoNotAllowVias(),
                             "poly": poly})
        else:
            zones.append({"net": z.GetNetname(), "layers": lays})

    ds = board.GetDesignSettings()
    out = {
        "source": os.path.abspath(args.board),
        "origin_abs_mm": [round(cx, 3), round(cy, 3)],
        "outline": outline,
        "layers": [layer_name[i] for i in sorted(copper_ids)],
        "rules": {"clearance": round(M(ds.m_MinClearance), 3) or 0.15,
                  "edge_clearance": round(M(ds.m_CopperEdgeClearance), 3) or 0.3,
                  "hole_clearance": round(M(ds.m_HoleClearance), 3) or 0.2},
        "pads": pads, "holes": holes, "tracks": tracks, "vias": vias,
        "keepouts": keepouts, "zones": zones, "copper_gfx": copper_gfx,
    }
    json.dump(out, open(out_path, "w"))
    print("DUMP_OK %s: %d pads, %d holes, %d tracks, %d vias, %d keepouts"
          % (out_path, len(pads), len(holes), len(tracks), len(vias),
             len(keepouts)))


if __name__ == "__main__":
    main()
