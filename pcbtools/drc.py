#!/usr/bin/env python3
"""Run KiCad DRC headlessly and report it in machine-usable form.

Wraps ``kicad-cli pcb drc --format json`` and reduces the report to what a
routing loop needs: error counts by type, and the unconnected items as an
airwire list in the same origin frame as :mod:`dump_board`'s geometry (the
origin is read from the geometry file when given, else from Edge.Cuts via
a quick metadata pass).

    python drc.py BOARD.kicad_pcb [-g geometry.json] [--airwires out.json]

Exit code: 0 when there are no errors and nothing unconnected, else 1
(warnings never fail the check).
"""
import argparse
import json
import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_env import run_cli


def run_drc(board_path):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    cp = run_cli("pcb", "drc", "--format", "json", "--output", tmp,
                 board_path)
    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        raise RuntimeError("kicad-cli drc produced no report: %s"
                           % (cp.stderr or cp.stdout))
    rep = json.load(open(tmp))
    os.unlink(tmp)
    return rep


def summarize(rep, origin=(0.0, 0.0)):
    ox, oy = origin
    errs = [v for v in rep.get("violations", [])
            if v.get("severity") == "error"]
    airwires = []
    for u in rep.get("unconnected_items", []):
        items = u.get("items", [])
        if len(items) < 2:
            continue
        desc = items[0].get("description", "")
        net = desc.split("[")[1].split("]")[0] if "[" in desc else "?"
        airwires.append({
            "net": net,
            "a": {"x": round(items[0]["pos"]["x"] - ox, 3),
                  "y": round(items[0]["pos"]["y"] - oy, 3),
                  "desc": items[0].get("description", "")[:80]},
            "b": {"x": round(items[1]["pos"]["x"] - ox, 3),
                  "y": round(items[1]["pos"]["y"] - oy, 3),
                  "desc": items[1].get("description", "")[:80]},
        })
    return {
        "errors": dict(Counter(v["type"] for v in errs)),
        "error_count": len(errs),
        "error_details": [
            {"type": v["type"],
             "pos": [round(v["items"][0]["pos"]["x"] - ox, 3),
                     round(v["items"][0]["pos"]["y"] - oy, 3)]
             if v.get("items") else None,
             "items": [i.get("description", "")[:80]
                       for i in v.get("items", [])]}
            for v in errs],
        "warning_count": len(rep.get("violations", [])) - len(errs),
        "unconnected": len(airwires),
        "airwires": airwires,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("-g", "--geometry", default=None,
                    help="geometry.json (for the origin frame)")
    ap.add_argument("--airwires", default=None,
                    help="write the airwire list here")
    args = ap.parse_args()

    origin = (0.0, 0.0)
    if args.geometry:
        origin = tuple(json.load(open(args.geometry))["origin_abs_mm"])
    s = summarize(run_drc(args.board), origin)
    print("errors:", s["errors"] or "NONE",
          "| warnings:", s["warning_count"],
          "| unconnected:", s["unconnected"])
    for d in s["error_details"][:10]:
        print("  ", d["type"], "|", " / ".join(d["items"]))
    if args.airwires:
        json.dump(s["airwires"], open(args.airwires, "w"), indent=1)
        print("airwires ->", args.airwires)
    sys.exit(0 if s["error_count"] == 0 and s["unconnected"] == 0 else 1)


if __name__ == "__main__":
    main()
