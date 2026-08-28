#!/usr/bin/env python3
"""Apply routed elements (and small edit ops) to a KiCad board.

Consumes the JSON emitted by :mod:`route` and writes tracks/vias into the
board, then refills zones and saves. Runs under KiCad's Python (bootstraps
itself via :mod:`kicad_env`).

SWIG survival rules this script obeys — KiCad 10's Python bindings corrupt
their proxy containers once the board is mutated:
  1. read everything needed into plain Python data FIRST,
  2. then mutate,
  3. never call GetTracks()/GetDrawings()/Zones()/Pads() again afterwards,
  4. do zone refills in this same single pass, before saving.

    python write_board.py BOARD.kicad_pcb routes.json [-g geometry.json]
    python write_board.py BOARD.kicad_pcb --fill-only

Supported ops (optional "ops" list in the JSON):
  {"op": "rip_track", "net": N, "layer": L?, "near": [x, y], "radius": r?}
  {"op": "move_footprint", "ref": R, "to": [x, y], "rot": deg?, "side": "F"|"B"?}
  {"op": "add_via", "net": N, "to": [x, y], "dia": d?}
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_env import ensure_pcbnew

pcbnew = ensure_pcbnew()

LAY = {"F": "F.Cu", "B": "B.Cu"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("routes", nargs="?", default=None)
    ap.add_argument("-g", "--geometry", default=None)
    ap.add_argument("--fill-only", action="store_true")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(os.path.abspath(args.board))
    mm = pcbnew.FromMM

    if args.fill_only:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(os.path.abspath(args.board), board)
        print("FILLED_OK")
        return

    plan = json.load(open(args.routes))
    if args.geometry:
        ox, oy = json.load(open(args.geometry))["origin_abs_mm"]
    else:
        bb = board.GetBoardEdgesBoundingBox()
        ox = pcbnew.ToMM(bb.GetLeft() + bb.GetWidth() // 2)
        oy = pcbnew.ToMM(bb.GetTop() + bb.GetHeight() // 2)

    def vec(x, y):
        return pcbnew.VECTOR2I(mm(ox + x), mm(oy + y))

    name_to_id = {board.GetLayerName(l): int(l)
                  for l in board.GetEnabledLayers().CuStack()}

    def layer_id(name):
        return name_to_id.get(LAY.get(name, name),
                              name_to_id.get(name, pcbnew.F_Cu))

    nets = board.GetNetsByName()

    def netcode(name):
        return nets[name].GetNetCode() if name in nets else 0

    # phase 1: snapshots
    ALL_TRACKS = list(board.GetTracks())
    FPS = {fp.GetReference(): fp for fp in board.GetFootprints()}
    REMOVED = set()

    # phase 2: ops then routes
    ripped = moved = added = 0
    for op in plan.get("ops", []):
        kind = op["op"]
        if kind == "rip_track" and "near" in op:
            nx, ny = op["near"]
            rad = op.get("radius", 0.45)
            for t in ALL_TRACKS:
                if id(t) in REMOVED or t.GetClass() == "PCB_VIA":
                    continue
                if op.get("net") and t.GetNetname() != op["net"]:
                    continue
                if op.get("layer") and \
                        t.GetLayer() != layer_id(op["layer"]):
                    continue
                x1 = pcbnew.ToMM(t.GetStart().x) - ox
                y1 = pcbnew.ToMM(t.GetStart().y) - oy
                x2 = pcbnew.ToMM(t.GetEnd().x) - ox
                y2 = pcbnew.ToMM(t.GetEnd().y) - oy
                dx, dy = x2 - x1, y2 - y1
                l2 = dx * dx + dy * dy
                u = 0 if l2 == 0 else max(0.0, min(
                    1.0, ((nx - x1) * dx + (ny - y1) * dy) / l2))
                if math.hypot(nx - (x1 + u * dx), ny - (y1 + u * dy)) < rad:
                    board.Remove(t)
                    REMOVED.add(id(t))
                    ripped += 1
        elif kind == "move_footprint" and op.get("ref") in FPS:
            fp = FPS[op["ref"]]
            want = op.get("side")
            if want == "F" and fp.GetLayer() == pcbnew.B_Cu:
                fp.Flip(fp.GetPosition(), False)
            if want == "B" and fp.GetLayer() == pcbnew.F_Cu:
                fp.Flip(fp.GetPosition(), False)
            if op.get("rot") is not None:
                fp.SetOrientationDegrees(op["rot"])
            fp.SetPosition(vec(op["to"][0], op["to"][1]))
            moved += 1
        elif kind == "add_via" and "to" in op:
            d = op.get("dia", 0.5)
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(vec(op["to"][0], op["to"][1]))
            v.SetDrill(mm(round(d - 0.2, 3)))
            v.SetWidth(mm(d))
            v.SetNetCode(netcode(op.get("net", "")))
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            board.Add(v)
            added += 1

    for r in plan.get("routes", []):
        nc = netcode(r["net"])
        for e in r["elements"]:
            if e["type"] == "track":
                tr = pcbnew.PCB_TRACK(board)
                tr.SetStart(vec(e["x1"], e["y1"]))
                tr.SetEnd(vec(e["x2"], e["y2"]))
                tr.SetWidth(mm(e.get("w", 0.2)))
                tr.SetLayer(layer_id(e["layer"]))
                tr.SetNetCode(nc)
                board.Add(tr)
            else:
                d = e.get("dia", 0.5)
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(vec(e["x"], e["y"]))
                v.SetDrill(mm(round(d - 0.2, 3)))
                v.SetWidth(mm(d))
                v.SetNetCode(nc)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                board.Add(v)
            added += 1

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(os.path.abspath(args.board), board)
    print("WRITE_OK ripped=%d moved=%d added=%d" % (ripped, moved, added))


if __name__ == "__main__":
    main()
