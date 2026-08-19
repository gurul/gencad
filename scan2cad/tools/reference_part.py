"""Build the morning ground-truth reference part (WI-12).

This is not a pipeline stage. It is a standalone build123d model of the one
physical object the user prints in the morning so that the project can have,
for the first time, a real accuracy number: print it, caliper it, scan it,
and compare the scan2cad report against the caliper sheet.

The part is deliberately made of exactly the primitives scan2cad can fit,
planes and cylinders, and nothing else. Six flat faces give the three block
dimensions as opposite-plane gaps, the through-bore gives one cylinder, and
the boss gives another. There are no fillets, no chamfers, no draft, and no
organic surfaces, because a feature the fitter cannot see is a feature that
cannot be audited.

Geometry, all millimetres, block corner at the origin:

    block          60.0 long in X, 40.0 wide in Y, 20.0 tall in Z
    through-bore   12.5 diameter, centred at X 15.0, Y 20.0, cut through Z
    boss            8.0 outer diameter, 5.0 tall, centred at X 45.0, Y 20.0,
                    standing on the top face so it spans Z 20.0 to 25.0

Assumes build123d 0.11.1 from the project venv (see docs/STACK_NOTES.md).
Run it with the venv interpreter, never a bare python3:

    .venv/bin/python tools/reference_part.py

Outputs out/reference_part.stl for the slicer and out/reference_part.step for
inspection, then prints the five named ground-truth dimensions that go on the
morning caliper sheet.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from build123d import Align, Box, Cylinder, Part, Pos, export_step, export_stl

# --- Construction values. These are the ground truth. -----------------------
# Every number printed by this script is derived from these five plus the boss
# height, so the printed sheet cannot drift away from the exported solid.

BLOCK_LENGTH_MM = 60.0  # X
BLOCK_WIDTH_MM = 40.0  # Y
BLOCK_HEIGHT_MM = 20.0  # Z
BORE_DIAMETER_MM = 12.5
BOSS_DIAMETER_MM = 8.0
BOSS_HEIGHT_MM = 5.0

BORE_CENTRE_XY_MM = (15.0, 20.0)  # from the block corner at the origin
BOSS_CENTRE_XY_MM = (45.0, 20.0)

# Tolerance for the self-check below. This is a check that the solid OCCT
# built matches the arithmetic we printed, not a manufacturing tolerance;
# 0.01 mm on lengths and 0.05 percent on volume are far tighter than anything
# a printer or a caliper will see, and generous against tessellation noise.
_LENGTH_TOL_MM = 0.01
_VOLUME_REL_TOL = 5e-4

_MIN_CORNER = (Align.MIN, Align.MIN, Align.MIN)
_BORE_OVERSHOOT_MM = 5.0  # cutter extends past both faces, for a clean cut


def build_reference_part() -> Part:
    """Return the reference part as a single build123d solid.

    Assumes millimetre units throughout and places the block's minimum corner
    at the origin, so a coordinate read off the model is also the distance
    from that corner, which is how the caliper sheet is worded.
    """
    bore_radius = BORE_DIAMETER_MM / 2.0
    boss_radius = BOSS_DIAMETER_MM / 2.0

    part = Box(
        BLOCK_LENGTH_MM, BLOCK_WIDTH_MM, BLOCK_HEIGHT_MM, align=_MIN_CORNER
    )

    cutter = Pos(
        BORE_CENTRE_XY_MM[0], BORE_CENTRE_XY_MM[1], -_BORE_OVERSHOOT_MM
    ) * Cylinder(
        radius=bore_radius,
        height=BLOCK_HEIGHT_MM + 2.0 * _BORE_OVERSHOOT_MM,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    part = part - cutter

    boss = Pos(
        BOSS_CENTRE_XY_MM[0], BOSS_CENTRE_XY_MM[1], BLOCK_HEIGHT_MM
    ) * Cylinder(
        radius=boss_radius,
        height=BOSS_HEIGHT_MM,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    part = part + boss

    return part


def expected_volume_mm3() -> float:
    """Analytic volume of the part, from the construction constants alone.

    Assumes the bore is fully inside the block footprint and the boss stands
    entirely on the top face, both of which hold for the constants above.
    """
    block = BLOCK_LENGTH_MM * BLOCK_WIDTH_MM * BLOCK_HEIGHT_MM
    bore = math.pi * (BORE_DIAMETER_MM / 2.0) ** 2 * BLOCK_HEIGHT_MM
    boss = math.pi * (BOSS_DIAMETER_MM / 2.0) ** 2 * BOSS_HEIGHT_MM
    return block - bore + boss


def check_part(part: Part) -> list[str]:
    """Return a list of plain-language failure messages; empty means it passed.

    Assumes `part` came from build_reference_part(). Checks the built solid's
    bounding box and volume against the construction constants, so that the
    printed caliper sheet is verified against the exported geometry rather
    than merely echoing the constants back.
    """
    problems: list[str] = []
    box = part.bounding_box()

    expected_span = (
        BLOCK_LENGTH_MM,
        BLOCK_WIDTH_MM,
        BLOCK_HEIGHT_MM + BOSS_HEIGHT_MM,
    )
    actual_span = (box.size.X, box.size.Y, box.size.Z)
    for axis, want, got in zip("XYZ", expected_span, actual_span):
        if abs(got - want) > _LENGTH_TOL_MM:
            problems.append(
                f"bounding box {axis} span is {got:.4f} mm, expected {want:.4f} mm"
            )

    for axis, got in zip("XYZ", (box.min.X, box.min.Y, box.min.Z)):
        if abs(got) > _LENGTH_TOL_MM:
            problems.append(
                f"bounding box {axis} minimum is {got:.4f} mm, expected 0.0000 mm"
            )

    want_volume = expected_volume_mm3()
    got_volume = part.volume
    if abs(got_volume - want_volume) > _VOLUME_REL_TOL * want_volume:
        problems.append(
            f"volume is {got_volume:.3f} cubic mm, expected {want_volume:.3f}"
        )

    return problems


def ground_truth_dims() -> list[tuple[str, float, str]]:
    """Return the five named caliper-sheet dimensions.

    Each entry is (name, value in mm, how to measure it). These five are
    chosen because scan2cad can produce all five from planes and cylinders
    alone: three opposite-plane gaps and two fitted cylinder radii.
    """
    return [
        (
            "block_length",
            BLOCK_LENGTH_MM,
            "longest edge of the block, across the two end faces",
        ),
        (
            "block_width",
            BLOCK_WIDTH_MM,
            "shorter horizontal edge, across the two side faces",
        ),
        (
            "block_height",
            BLOCK_HEIGHT_MM,
            "top face to bottom face, away from the boss",
        ),
        (
            "bore_diameter",
            BORE_DIAMETER_MM,
            "inside the through hole, caliper jaws opened across it",
        ),
        (
            "boss_diameter",
            BOSS_DIAMETER_MM,
            "outside of the round post on the top face",
        ),
    ]


def print_caliper_sheet(stl_path: Path, step_path: Path) -> None:
    """Print the morning caliper sheet to stdout, ASCII only, one fact a line.

    Assumes the files at the given paths have already been written. The
    wording is meant to be read aloud by a screen reader, so there are no
    tables, no columns, and no symbols beyond plain punctuation.
    """
    print("scan2cad reference part")
    print("Wrote STL to " + str(stl_path))
    print("Wrote STEP to " + str(step_path))
    print("")
    print("Print the STL solid, no supports needed, flat on the bottom face.")
    print("")
    print("Five named ground truth dimensions for the caliper sheet.")
    for name, value, how in ground_truth_dims():
        print(f"{name} = {value:.1f} mm, {how}")
    print("")
    print("Supporting construction values, not on the caliper sheet.")
    print(f"boss_height = {BOSS_HEIGHT_MM:.1f} mm, top of boss above top face")
    print(
        "bore centre is "
        f"{BORE_CENTRE_XY_MM[0]:.1f} mm and {BORE_CENTRE_XY_MM[1]:.1f} mm "
        "from the block corner"
    )
    print(
        "boss centre is "
        f"{BOSS_CENTRE_XY_MM[0]:.1f} mm and {BOSS_CENTRE_XY_MM[1]:.1f} mm "
        "from the block corner"
    )
    print(
        "bore centre to boss centre is "
        f"{BOSS_CENTRE_XY_MM[0] - BORE_CENTRE_XY_MM[0]:.1f} mm"
    )
    print("")
    print("After printing, measure each of the five and write the measured")
    print("values into out/ground_truth.txt, one name and value per line.")
    print("Those measured values, not the numbers above, are the truth.")
    print("The printer will miss nominal by a few tenths of a millimetre and")
    print("that miss is real geometry, so the scan must be judged against the")
    print("caliper reading rather than against the design intent.")


def main(argv: list[str] | None = None) -> int:
    """Build, verify, export, and print. Returns a process exit code.

    Assumes it can create the output directory. Returns 1 without exporting
    if the built solid disagrees with the construction constants, because a
    caliper sheet that does not describe the exported file is worse than none.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Build the scan2cad morning reference part and print its five "
            "named ground truth dimensions."
        )
    )
    parser.add_argument(
        "--out-dir",
        default="out",
        help="directory for reference_part.stl and reference_part.step",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify the model against the construction constants, export nothing",
    )
    args = parser.parse_args(argv)

    part = build_reference_part()

    problems = check_part(part)
    if problems:
        print("Reference part self check FAILED.", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        return 1

    if args.check_only:
        print("Reference part self check passed. Nothing exported.")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stl_path = out_dir / "reference_part.stl"
    step_path = out_dir / "reference_part.step"

    export_stl(part, stl_path)
    export_step(part, step_path)

    print_caliper_sheet(stl_path, step_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
