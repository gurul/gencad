#!/usr/bin/env python3
"""Export JLCPCB-format BOM and CPL files from a KiCad board.

CPL comes from ``kicad-cli pcb export pos`` reshaped to JLC's columns
(Designator, Mid X, Mid Y, Layer, Rotation). The BOM maps designators to
an LCSC part number per group, taken from a simple mapping CSV you
provide (columns: refs, mpn, lcsc — refs comma-separated) or from a
footprint field already present on the board (``--lcsc-field LCSC``; the
BOM groups by value, footprint and part number, and needs pcbnew).

    python jlc_export.py BOARD.kicad_pcb --map parts.csv \
        [--dnp REF1,REF2] [-o outdir]
    python jlc_export.py BOARD.kicad_pcb --lcsc-field LCSC \
        [--dnp REF1,REF2] [-o outdir]
"""
import argparse
import csv
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_env import kicad_cli, ensure_pcbnew


def bom_from_field(board_path, field, dnp):
    """BOM rows [value, refs, footprint, lcsc] grouped from footprint fields.

    Skips refs in ``dnp`` and footprints excluded from the BOM. A footprint
    without the field keeps an empty part number and is named on stderr."""
    pcbnew = ensure_pcbnew()
    board = pcbnew.LoadBoard(os.path.abspath(board_path))
    groups, missing = {}, []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref in dnp or fp.IsExcludedFromBOM():
            continue
        lcsc = fp.GetFieldText(field).strip() if fp.HasField(field) else ""
        if not lcsc:
            missing.append(ref)
        key = (fp.GetValue(), str(fp.GetFPID().GetLibItemName()), lcsc)
        groups.setdefault(key, []).append(ref)
    if missing:
        sys.stderr.write("jlc_export: WARNING no %r value on %s\n"
                         % (field, ",".join(sorted(missing))))
    return [[val, ",".join(sorted(refs)), fpn, lcsc]
            for (val, fpn, lcsc), refs in sorted(groups.items())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--map", dest="mapping", default=None,
                     help="CSV with refs,mpn,lcsc columns")
    src.add_argument("--lcsc-field", default=None,
                     help="footprint field holding the LCSC part number")
    ap.add_argument("--dnp", default="",
                    help="comma list of refs to exclude everywhere")
    ap.add_argument("-o", "--outdir", default=".")
    args = ap.parse_args()
    dnp = {r for r in args.dnp.split(",") if r}
    # read the board first: ensure_pcbnew may re-exec this script
    field_bom = bom_from_field(args.board, args.lcsc_field, dnp) \
        if args.lcsc_field else None

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
    elif field_bom is not None:
        bom_path = os.path.join(args.outdir, "jlc-bom.csv")
        with open(bom_path, "w", newline="") as out:
            w = csv.writer(out)
            w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
            w.writerows(field_bom)
        print("jlc-bom.csv: %d lines (field %r)"
              % (len(field_bom), args.lcsc_field))
    else:
        print("no --map given: BOM skipped (CPL only)")


if __name__ == "__main__":
    main()
