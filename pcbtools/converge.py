#!/usr/bin/env python3
"""DRC-driven routing convergence loop.

Each round, in this order — the ordering is the whole point:

  1. measure   kicad-cli DRC → error count + airwire list
  2. dump      fresh geometry from the board
  3. route     the airwires against exactly that geometry
  4. apply     the verified routes immediately
  5. refill    zones

A route can therefore never be applied to a board different from the one
it was computed against (applying stale route files to a changed board is
the classic way a "clean" plan turns into a pile of shorts). Stops on
zero unconnected, or when a round makes no progress.

    python converge.py BOARD.kicad_pcb [--rounds 6] [--cell 0.05]
        [--layers F.Cu,In2.Cu,B.Cu] [--classes 0.2:0.5,0.127:0.4]
        [--exempt-gfx-nets NETA,NETB]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_env import kicad_python
import drc as drc_mod


def sh(script, *args):
    py = kicad_python() or sys.executable
    return subprocess.run([py, os.path.join(HERE, script), *args],
                          capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--cell", type=float, default=0.05)
    ap.add_argument("--layers", default=None)
    ap.add_argument("--classes", default="0.2:0.5,0.15:0.45,0.127:0.4")
    ap.add_argument("--restarts", type=int, default=2)
    ap.add_argument("--exempt-gfx-nets", default="")
    args = ap.parse_args()

    work = tempfile.mkdtemp(prefix="pcbtools-")
    geo = os.path.join(work, "geometry.json")
    air = os.path.join(work, "airwires.json")
    routes = os.path.join(work, "routes.json")
    prev = None

    for rnd in range(1, args.rounds + 1):
        print("=== round %d ===" % rnd)
        cp = sh("dump_board.py", args.board, "-o", geo)
        if "DUMP_OK" not in cp.stdout:
            sys.exit("dump failed: %s%s" % (cp.stdout, cp.stderr))
        origin = tuple(json.load(open(geo))["origin_abs_mm"])
        s = drc_mod.summarize(drc_mod.run_drc(args.board), origin)
        print("  errors:", s["errors"] or "NONE",
              "| unconnected:", s["unconnected"])
        if s["unconnected"] == 0:
            print("CONVERGED (%d DRC errors remain)" % s["error_count"])
            break
        if prev is not None and s["unconnected"] >= prev:
            print("NO PROGRESS (was %d)" % prev)
            break
        prev = s["unconnected"]
        json.dump(s["airwires"], open(air, "w"))

        route_args = [sys.executable, os.path.join(HERE, "route.py"),
                      geo, air, "-o", routes,
                      "--cell", str(args.cell),
                      "--classes", args.classes,
                      "--restarts", str(args.restarts)]
        if args.layers:
            route_args += ["--layers", args.layers]
        if args.exempt_gfx_nets:
            route_args += ["--exempt-gfx-nets", args.exempt_gfx_nets]
        cp = subprocess.run(route_args, capture_output=True, text=True)
        for line in cp.stdout.splitlines():
            print("  " + line)
        if not os.path.exists(routes):
            sys.exit("router failed: %s" % cp.stderr)

        cp = sh("write_board.py", args.board, routes, "-g", geo)
        print("  " + (cp.stdout.strip().splitlines() or ["?"])[-1])

    s = drc_mod.summarize(drc_mod.run_drc(args.board))
    print("FINAL: errors %s | unconnected %d"
          % (s["errors"] or "NONE", s["unconnected"]))


if __name__ == "__main__":
    main()
