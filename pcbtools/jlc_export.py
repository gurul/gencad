#!/usr/bin/env python3
"""Export JLCPCB-format BOM and CPL files from a KiCad board.

CPL comes from ``kicad-cli pcb export pos`` reshaped to JLC's columns
(Designator, Mid X, Mid Y, Layer, Rotation). The BOM maps designators to
an LCSC part number per group, taken from a simple mapping CSV you
provide (columns: refs, mpn, lcsc — refs comma-separated) or from a
``--lcsc-field`` already present in the board's footprint fields.

    python jlc_export.py BOARD.kicad_pcb --map parts.csv \
        [--dnp REF1,REF2] [-o outdir]
"""
import argparse
import csv
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_env import kicad_cli


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--map", dest="mapping", default=None,
                    help="CSV with refs,mpn,lcsc columns")
    ap.add_argument("--dnp", default="",
                    help="comma list of refs to exclude everywhere")
    ap.add_argument("-o", "--outdir", default=".")
    args = ap.parse_args()
    dnp = {r for r in args.dnp.split(",") if r}

    # ---- CPL ---------------------------------------------------------------
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        pos = f.name
    subprocess.run([kicad_cli(), "pcb", "export", "pos", "--format", "csv",
                    "--units", "mm", "--side", "both", "--output", pos,
                    args.board], capture_output=True, check=True)
    cpl_path = os.path.join(args.outdir, "jlc-cpl.csv")
    n = 0
    with open(pos) as f, open(cpl_path, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for row in csv.DictReader(f):
            ref = row["Ref"].strip('"')
            if ref in dnp:
                continue
            w.writerow([ref, "%.4fmm" % float(row["PosX"]),
                        "%.4fmm" % float(row["PosY"]),
                        "Top" if row["Side"] == "top" else "Bottom",
                        row["Rot"]])
            n += 1
    os.unlink(pos)
    print("jlc-cpl.csv: %d placements" % n)

    # ---- BOM ---------------------------------------------------------------
    if args.mapping:
        bom_path = os.path.join(args.outdir, "jlc-bom.csv")
        rows = 0
        with open(args.mapping) as f, open(bom_path, "w", newline="") as out:
            w = csv.writer(out)
            w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
            for row in csv.DictReader(f):
                refs = [r.strip() for r in row["refs"].split(",")
                        if r.strip() and r.strip() not in dnp]
                if not refs:
                    continue
                w.writerow([row.get("mpn", ""), ",".join(refs), "",
                            row.get("lcsc", "")])
                rows += 1
        print("jlc-bom.csv: %d lines" % rows)
    else:
        print("no --map given: BOM skipped (CPL only)")


if __name__ == "__main__":
    main()
