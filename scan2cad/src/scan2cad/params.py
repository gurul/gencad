"""Parser for CGAL Efficient RANSAC shape info strings.

The installed binding (`CGAL.CGAL_Shape_detection.efficient_RANSAC`, cgal
6.0.1.post202410241521) returns a plain Python list of one info string per
detected shape. There is no structured accessor: the string is the only
description of the fitted parameters, so this module is the sole place in
scan2cad that knows their text format. See docs/STACK_NOTES.md.

Real strings from this wheel, captured 2026-08-19:

    Type: plane (-0.00247502, 0.00212651, 0.999995)x - -4.97749= 0 #Pts: 593
    Type: cylinder center: (-0.0686792, 0.0335444, 6.52789) axis: (-0, 0, 1) radius:12.5214 #Pts: 800

Format facts this parser is built around, all verified live:

* Whitespace is not uniform. There is no space after "radius:" and no space
  before "=" in the plane string, so the parser tolerates optional whitespace
  everywhere rather than matching a fixed layout.
* Components may be negative, may be "-0", and may be printed in scientific
  notation such as "1.77636e-15".
* The plane string carries no "normal:" label. The parenthesised triple is the
  plane normal and the trailing scalar is CGAL's plane coefficient d.
* The plane sign convention is `normal . x + d = 0`, NOT the `- d = 0` that the
  text appears to say. Verified against exact synthetic planes: a plane through
  z = +10 with normal (0.6, 0, 0.8) prints "- -8= 0", and 0.8 * 10 - 8 = 0 only
  under the plus convention. The closest point to the origin is therefore
  `-d * normal`, which is what `PlaneFit.point` receives.
* When the signed offset is negative the text shows a double negative,
  "x - -4.97749= 0".

Two fields cannot come from the string and are left unset here: `rms_mm` and
the extents. They are NaN placeholders that WI-3 (`ransac_cgal.py`) overwrites
with `dataclasses.replace` once it has the inlier indices from the shape map.
NaN, not zero, so a stage that forgets to fill them produces a visibly broken
report instead of a plausible-looking wrong number.

Units: the parser is unit-agnostic. The numbers come out in whatever unit the
point set went in with, which everywhere in scan2cad is millimetres.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import replace
from typing import NoReturn

from .primitives import CylinderFit, PlaneFit, Vec3

# Shapes this project fits. Everything else is detected only if a caller asks
# CGAL for it, which scan2cad never does (PLAN.md ground rule 5: planes and
# cylinders only).
SUPPORTED_KINDS = ("plane", "cylinder")

# Shapes the binding can emit that scan2cad deliberately does not model. They
# get a clear typed error instead of a crash, so a caller can skip them.
UNSUPPORTED_KINDS = ("sphere", "cone", "torus")

# Default base names. The frame stage (WI-4) renames planes semantically.
PLANE_NAME_PREFIX = "plane"
CYLINDER_NAME_PREFIX = "cylinder"

# Placeholders for the fields the info string does not carry.
UNSET_RMS_MM = float("nan")
UNSET_PLANE_EXTENT = (float("nan"), float("nan"), float("nan"), float("nan"))
UNSET_AXIAL_EXTENT = (float("nan"), float("nan"))

# A direction is printed with about six significant digits, so its recovered
# norm can miss 1.0 by roughly 1e-6 -- enough to trip the unit-vector check in
# primitives.py. Renormalising that is repairing a printing artefact, not
# hiding a fitting bug, so it is allowed within this tight band and refused
# outside it.
_DIRECTION_NORM_TOL = 1e-3

# One signed decimal or scientific-notation number, e.g. "-0", "12.5214",
# "1.77636e-15", ".5", "+3.".
_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

_KIND_RE = re.compile(r"^\s*Type:\s*(?P<kind>[A-Za-z_]+)")

_PLANE_RE = re.compile(
    rf"""^\s*Type:\s*plane\s*
    \(\s*(?P<nx>{_NUM})\s*,\s*(?P<ny>{_NUM})\s*,\s*(?P<nz>{_NUM})\s*\)\s*
    x\s*-\s*(?P<d>{_NUM})\s*=\s*0\s*
    \#\s*Pts:\s*(?P<pts>\d+)\s*$""",
    re.VERBOSE,
)

_CYLINDER_RE = re.compile(
    rf"""^\s*Type:\s*cylinder\s*center:\s*
    \(\s*(?P<cx>{_NUM})\s*,\s*(?P<cy>{_NUM})\s*,\s*(?P<cz>{_NUM})\s*\)\s*
    axis:\s*
    \(\s*(?P<ax>{_NUM})\s*,\s*(?P<ay>{_NUM})\s*,\s*(?P<az>{_NUM})\s*\)\s*
    radius:\s*(?P<radius>{_NUM})\s*
    \#\s*Pts:\s*(?P<pts>\d+)\s*$""",
    re.VERBOSE,
)


class ShapeParseError(ValueError):
    """A shape info string could not be turned into a fitted primitive."""


class UnsupportedShapeError(ShapeParseError):
    """The string describes a shape kind scan2cad does not model.

    Raised for sphere, cone and torus. It is a subclass of ShapeParseError so
    that a caller who does not care about the distinction can catch one type,
    while `ransac_cgal.py` can catch this one alone and skip the shape.
    """


def shape_kind(info: str) -> str:
    """Return the lowercase shape kind named by `info`, e.g. "plane".

    Assumes `info` is one string as returned by `efficient_RANSAC`. Raises
    ShapeParseError if the string does not start with a "Type:" token, which
    is the signal that the upstream format has drifted.
    """
    match = _KIND_RE.match(info)
    if match is None:
        raise ShapeParseError(f"no 'Type:' token in shape info string: {info!r}")
    return match.group("kind").lower()


def _unit(raw: Vec3, label: str, info: str) -> tuple[Vec3, float]:
    """Return (`raw` renormalised to unit length, its original norm).

    Assumes `raw` came from decimal text, so only printing-scale deviation
    from unit length is tolerated; anything larger is reported as a parse
    failure rather than silently rescaled.
    """
    norm = math.sqrt(raw[0] * raw[0] + raw[1] * raw[1] + raw[2] * raw[2])
    if not math.isfinite(norm) or abs(norm - 1.0) > _DIRECTION_NORM_TOL:
        raise ShapeParseError(
            f"{label} {raw} has norm {norm!r}, which is not unit length "
            f"within {_DIRECTION_NORM_TOL}, in shape info string: {info!r}"
        )
    return (raw[0] / norm, raw[1] / norm, raw[2] / norm), norm


def parse_plane(info: str, name: str) -> PlaneFit:
    """Parse one plane info string into a PlaneFit named `name`.

    Assumes the plus sign convention documented in this module: the returned
    `point` is the plane point closest to the origin, `-d * normal`. `rms_mm`
    and `extent` come back unset (NaN) for WI-3 to fill from the inliers.
    """
    match = _PLANE_RE.match(info)
    if match is None:
        _reject(info, "plane")
    normal, norm = _unit(
        (float(match["nx"]), float(match["ny"]), float(match["nz"])),
        "plane normal",
        info,
    )
    # d is stated against the printed, near-unit normal; dividing by the same
    # norm keeps the point exactly on the plane after renormalisation.
    offset = -float(match["d"]) / norm
    return PlaneFit(
        name=name,
        point=(normal[0] * offset, normal[1] * offset, normal[2] * offset),
        normal=normal,
        inlier_count=int(match["pts"]),
        rms_mm=UNSET_RMS_MM,
        extent=UNSET_PLANE_EXTENT,
    )


def parse_cylinder(info: str, name: str) -> CylinderFit:
    """Parse one cylinder info string into a CylinderFit named `name`.

    Assumes CGAL's "center:" is an arbitrary point on the axis, not a midpoint
    of the inliers, so it is stored as `axis_point` and the axial span stays
    unset (NaN) until WI-3 projects the inliers onto the axis. `rms_mm` is
    likewise unset. A non-positive radius is a parse failure.
    """
    match = _CYLINDER_RE.match(info)
    if match is None:
        _reject(info, "cylinder")
    axis_dir, _ = _unit(
        (float(match["ax"]), float(match["ay"]), float(match["az"])),
        "cylinder axis",
        info,
    )
    radius = float(match["radius"])
    if not math.isfinite(radius) or radius <= 0.0:
        raise ShapeParseError(
            f"cylinder radius must be positive and finite, got {radius!r} "
            f"in shape info string: {info!r}"
        )
    return CylinderFit(
        name=name,
        axis_point=(float(match["cx"]), float(match["cy"]), float(match["cz"])),
        axis_dir=axis_dir,
        radius_mm=radius,
        extent_mm=UNSET_AXIAL_EXTENT,
        inlier_count=int(match["pts"]),
        rms_mm=UNSET_RMS_MM,
    )


def _reject(info: str, expected: str) -> NoReturn:
    """Raise the most informative error available for an unmatched `info`.

    Assumes the caller already knows which kind it expected. Always raises.
    """
    kind = shape_kind(info)
    if kind in UNSUPPORTED_KINDS:
        raise UnsupportedShapeError(
            f"shape kind {kind!r} is detected but not modelled by scan2cad; "
            f"only {', '.join(SUPPORTED_KINDS)} are fitted: {info!r}"
        )
    if kind != expected:
        raise ShapeParseError(
            f"expected a {expected} info string, got kind {kind!r}: {info!r}"
        )
    raise ShapeParseError(
        f"malformed {expected} info string, the CGAL text format may have "
        f"drifted from docs/STACK_NOTES.md: {info!r}"
    )


def parse_shape(info: str, name: str) -> PlaneFit | CylinderFit:
    """Parse one info string of either supported kind into a fit named `name`.

    Raises UnsupportedShapeError for sphere, cone and torus strings, and
    ShapeParseError for anything unrecognised or malformed.
    """
    kind = shape_kind(info)
    if kind == "plane":
        return parse_plane(info, name)
    if kind == "cylinder":
        return parse_cylinder(info, name)
    if kind in UNSUPPORTED_KINDS:
        raise UnsupportedShapeError(
            f"shape kind {kind!r} is detected but not modelled by scan2cad; "
            f"only {', '.join(SUPPORTED_KINDS)} are fitted: {info!r}"
        )
    raise ShapeParseError(f"unknown shape kind {kind!r}: {info!r}")


def parse_shapes(
    infos: Iterable[str], skip_unsupported: bool = True
) -> tuple[list[PlaneFit], list[CylinderFit]]:
    """Parse a whole `efficient_RANSAC` return list into planes and cylinders.

    Names are assigned per kind in input order: plane_0, plane_1, cylinder_0.
    Assumes the caller keeps the input order, because WI-3 matches these names
    back to shape indices in the CGAL shape map, where index i is the i-th
    string in `infos`, planes and cylinders interleaved.

    With `skip_unsupported` true, sphere, cone and torus strings are dropped
    silently -- they can only appear if a caller enabled those shape kinds,
    which scan2cad does not. With it false they raise UnsupportedShapeError.
    Malformed strings always raise.
    """
    planes: list[PlaneFit] = []
    cylinders: list[CylinderFit] = []
    for info in infos:
        try:
            fit = parse_shape(info, name="")
        except UnsupportedShapeError:
            if skip_unsupported:
                continue
            raise
        if isinstance(fit, PlaneFit):
            planes.append(replace(fit, name=f"{PLANE_NAME_PREFIX}_{len(planes)}"))
        else:
            cylinders.append(
                replace(fit, name=f"{CYLINDER_NAME_PREFIX}_{len(cylinders)}")
            )
    return planes, cylinders
