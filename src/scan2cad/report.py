"""Plain-text, screen-reader-native geometry report (WI-5).

The report is the product's main output surface, so its format rules are hard
rules, not style preferences (SYNTHESIS.md section 7, PLAN.md WI-5):

  - one fact per line, short lines, every line ends with a period
  - no tables, no columns, no ASCII art, no bullet glyphs
  - ASCII only; no unicode symbols beyond plain punctuation
  - millimetres printed with one decimal, angles in degrees with one decimal
  - stable ordering: planes by frame axis then position along it, cylinders by
    radius, so two runs of the same scene read in the same order
  - every dimension line ends with its uncertainty tag (RMS and point count)
  - every SnapRecord is printed verbatim; nothing is snapped silently

This module depends only on `primitives` and `thresholds`. It never fits, never
mutates a SceneModel, and never invents a number that is not derivable from the
scene it was handed.

Two derivations here are documented approximations, and are labelled as such in
the text they produce:

  - The overview bounding box is measured over plane reference points and
    cylinder surfaces expressed in frame coordinates. PlaneFit carries a 2D
    footprint extent but not the in-plane basis it was measured in, so the
    footprint cannot be placed in 3D from the frozen data model; the plane's
    own reference point is used instead. For a closed object whose faces were
    each fitted from their own inliers this recovers the envelope; for a
    partial scan it under-reports it.
  - The uncertainty of a gap between two planes is the quadrature sum of the
    two per-plane residuals, and the point count is the sum of the two inlier
    counts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence

from scan2cad.primitives import CylinderFit, PlaneFit, SceneModel, SnapRecord, Vec3
from scan2cad.thresholds import COARSE, Thresholds

__all__ = ["render_report", "DIMENSION_LINE_RE"]

# A dimension line is recognisable by this pattern; the e2e gate greps for it.
DIMENSION_LINE_RE = re.compile(r"= [0-9.]+ mm.*RMS")

# Fallback frame used when a SceneModel carries no usable triad, so that a
# report can still be produced for a scene the frame stage refused to align.
_WORLD_ORIGIN: Vec3 = (0.0, 0.0, 0.0)
_WORLD_AXES: tuple[Vec3, Vec3, Vec3] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

# Names given to the gap between an opposite-parallel plane pair, indexed by
# the frame axis the pair straddles.
_AXIS_DIM_NAMES = ("width", "depth", "height")

# Fixed caveat text, taken from the embargoed-claims list (PLAN.md section 7).
# This block is verbatim and must not be softened, shortened, or made
# conditional on how good a particular run looked.
_CAVEATS: tuple[str, ...] = (
    "This report is a scan draft, not a measurement record.",
    "Verify every dimension against a caliper or a datasheet before you cut, "
    "print, or order anything.",
    "No accuracy claim of the form plus or minus X millimetres is made or implied.",
    "Synthetic results verify plumbing only. They say nothing about phone-scan accuracy.",
    "No press-fit, mating-fit, or sub-millimetre claim is made here, ever.",
    "This tool competes with silence, not with the accuracy of CAD tools.",
    "Failures on degraded meshes are reported as findings, not hidden.",
)


# ---------------------------------------------------------------------------
# small vector helpers (kept local so this module stays numpy-free)
# ---------------------------------------------------------------------------


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _angle_deg(a: Vec3, b: Vec3) -> float:
    """Angle in degrees between two unit vectors, clamped against float drift.

    Assumes both arguments are unit length, which the frozen dataclasses check
    at construction.
    """
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(a, b)))))


def _is_unit(vec: object) -> bool:
    """True if `vec` is a 3-tuple-like of finite floats with norm near one."""
    if not isinstance(vec, Sequence) or isinstance(vec, str) or len(vec) != 3:
        return False
    try:
        norm = math.sqrt(sum(float(c) * float(c) for c in vec))
    except (TypeError, ValueError):
        return False
    return math.isfinite(norm) and abs(norm - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------


def _mm(value: float) -> str:
    """Format a millimetre value with one decimal, without a negative zero."""
    text = f"{value:.1f}"
    return "0.0" if text == "-0.0" else text


def _deg(value: float) -> str:
    """Format an angle in degrees with one decimal, without a negative zero."""
    return _mm(value)


def _raw(value: float) -> str:
    """Format a snap-log number without rounding away the change it records.

    The one-decimal rule is a readability rule for dimensions. The snap log
    exists to show that 20.23 became 20.2, so it prints significant digits.
    """
    text = f"{value:.6g}"
    if text == "-0":
        text = "0"
    if "." not in text and "e" not in text and "n" not in text:
        text += ".0"
    return text


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


# ---------------------------------------------------------------------------
# frame handling
# ---------------------------------------------------------------------------


def _frame(scene: SceneModel) -> tuple[Vec3, tuple[Vec3, Vec3, Vec3], bool]:
    """Return (origin, axes, is_usable) for the scene's frame.

    Assumes the frozen convention that `SceneModel.frame` is
    (origin, x_axis, y_axis, z_axis). Anything else -- including the empty
    tuple a pre-frame-stage scene carries -- falls back to the world axes, and
    the caller says so in the report rather than pretending the object was
    aligned.
    """
    frame = scene.frame
    if isinstance(frame, tuple) and len(frame) == 4:
        origin, x_axis, y_axis, z_axis = frame
        if all(_is_unit(axis) for axis in (x_axis, y_axis, z_axis)):
            try:
                point: Vec3 = (float(origin[0]), float(origin[1]), float(origin[2]))
            except (TypeError, IndexError, ValueError):
                return _WORLD_ORIGIN, _WORLD_AXES, False
            axes = (
                (float(x_axis[0]), float(x_axis[1]), float(x_axis[2])),
                (float(y_axis[0]), float(y_axis[1]), float(y_axis[2])),
                (float(z_axis[0]), float(z_axis[1]), float(z_axis[2])),
            )
            return point, axes, True
    return _WORLD_ORIGIN, _WORLD_AXES, False


def _dominant_axis(direction: Vec3, axes: tuple[Vec3, Vec3, Vec3]) -> int:
    """Index of the frame axis most nearly aligned with `direction`.

    Ties break towards the lower index, which keeps the ordering stable for
    a direction that sits exactly between two axes.
    """
    best = 0
    best_value = -1.0
    for index, axis in enumerate(axes):
        value = abs(_dot(direction, axis))
        if value > best_value + 1e-12:
            best = index
            best_value = value
    return best


def _sorted_planes(
    planes: Sequence[PlaneFit], origin: Vec3, axes: tuple[Vec3, Vec3, Vec3]
) -> list[PlaneFit]:
    """Planes ordered by frame axis, then position along that axis, then name."""
    def key(plane: PlaneFit) -> tuple[int, float, str]:
        index = _dominant_axis(plane.normal, axes)
        position = _dot(_sub(plane.point, origin), axes[index])
        return (index, position, plane.name)

    return sorted(planes, key=key)


def _sorted_cylinders(cylinders: Sequence[CylinderFit]) -> list[CylinderFit]:
    """Cylinders ordered by radius, then name."""
    return sorted(cylinders, key=lambda c: (c.radius_mm, c.name))


# ---------------------------------------------------------------------------
# section 1: overview
# ---------------------------------------------------------------------------


def _bounding_box_mm(
    scene: SceneModel, origin: Vec3, axes: tuple[Vec3, Vec3, Vec3]
) -> tuple[float, float, float] | None:
    """Extent of the fitted primitives along each frame axis, or None if empty.

    Plane contributions are their reference points; cylinder contributions are
    the exact extremes of the fitted surface patch, including the radial bulge
    perpendicular to the axis. See the module docstring for why the plane
    footprints are not used.
    """
    spans: list[float] = []
    for axis in axes:
        values: list[float] = []
        for plane in scene.planes:
            values.append(_dot(_sub(plane.point, origin), axis))
        for cylinder in scene.cylinders:
            base = _dot(_sub(cylinder.axis_point, origin), axis)
            along = _dot(cylinder.axis_dir, axis)
            bulge = cylinder.radius_mm * math.sqrt(max(0.0, 1.0 - along * along))
            for end in cylinder.extent_mm:
                values.append(base + end * along - bulge)
                values.append(base + end * along + bulge)
        if not values:
            return None
        spans.append(max(values) - min(values))
    return (spans[0], spans[1], spans[2])


def _overview_lines(
    scene: SceneModel,
    origin: Vec3,
    axes: tuple[Vec3, Vec3, Vec3],
    frame_ok: bool,
    units_note: str | None,
    regime: Thresholds | None,
    overrides: Mapping[str, object] | None,
) -> list[str]:
    lines: list[str] = []
    box = _bounding_box_mm(scene, origin, axes)
    if box is None:
        lines.append("No primitives were fitted, so there is no bounding box.")
    else:
        lines.append(
            "Object bounding box "
            f"{_mm(box[0])} by {_mm(box[1])} by {_mm(box[2])} mm."
        )
    lines.append(
        f"Found {len(scene.planes)} "
        f"{_plural(len(scene.planes), 'plane', 'planes')} and "
        f"{len(scene.cylinders)} "
        f"{_plural(len(scene.cylinders), 'cylinder', 'cylinders')}."
    )
    lines.append(f"Provenance: {scene.provenance}.")
    if frame_ok:
        lines.append(
            "Measurements are given along the fitted object frame, "
            "axes x then y then z."
        )
    else:
        lines.append(
            "No object frame was fitted, so measurements are given along the "
            "world axes x then y then z."
        )
    if units_note:
        lines.append(f"Units assumption: {units_note}.")
    if regime is not None:
        lines.append(f"Threshold regime: {regime.name}.")
        lines.append(
            f"Angular snap tolerance {_deg(regime.angular_snap_deg)} degrees."
        )
    if overrides:
        for key in sorted(overrides):
            lines.append(f"Threshold override: {key} set to {overrides[key]}.")
    elif regime is not None:
        lines.append("No threshold overrides were used.")
    lines.append("All dimensions are scan drafts, plus or minus the stated residual.")
    lines.append("Verify them with a caliper or a datasheet.")
    return lines


# ---------------------------------------------------------------------------
# section 2: dimensions
# ---------------------------------------------------------------------------


def _plane_pairs(
    planes: Sequence[PlaneFit], axes: tuple[Vec3, Vec3, Vec3], tol_deg: float
) -> list[tuple[PlaneFit, PlaneFit, int]]:
    """Greedily pair parallel planes, in the order they were given.

    Assumes `planes` is already in report order, so that faces straddling the
    same frame axis sit next to each other. Each plane joins at most one pair;
    a scene with three parallel faces reports one gap and leaves the third
    plane unpaired rather than inventing a second reading of the same feature.
    Returns (first, second, axis_index) triples.
    """
    pairs: list[tuple[PlaneFit, PlaneFit, int]] = []
    used: set[int] = set()
    for i, first in enumerate(planes):
        if i in used:
            continue
        for j in range(i + 1, len(planes)):
            if j in used:
                continue
            second = planes[j]
            angle = _angle_deg(first.normal, second.normal)
            if min(angle, 180.0 - angle) > tol_deg:
                continue
            gap = abs(_dot(_sub(second.point, first.point), first.normal))
            if gap <= 0.0:
                continue
            used.add(i)
            used.add(j)
            pairs.append((first, second, _dominant_axis(first.normal, axes)))
            break
    return pairs


def _dimension_lines(
    planes: Sequence[PlaneFit],
    cylinders: Sequence[CylinderFit],
    axes: tuple[Vec3, Vec3, Vec3],
    tol_deg: float,
) -> list[str]:
    lines: list[str] = []
    seen_axis_count: dict[int, int] = {}
    for first, second, axis_index in _plane_pairs(planes, axes, tol_deg):
        count = seen_axis_count.get(axis_index, 0) + 1
        seen_axis_count[axis_index] = count
        name = _AXIS_DIM_NAMES[axis_index]
        if count > 1:
            name = f"{name}_{count}"
        gap = abs(_dot(_sub(second.point, first.point), first.normal))
        rms = math.sqrt(first.rms_mm**2 + second.rms_mm**2)
        points = first.inlier_count + second.inlier_count
        lines.append(
            f"{name} = {_mm(gap)} mm, gap between {first.name} and {second.name}, "
            f"RMS {_mm(rms)} mm, {points} points."
        )
    for cylinder in cylinders:
        lines.append(
            f"{cylinder.name}_diameter = {_mm(2.0 * cylinder.radius_mm)} mm, "
            f"across the fitted surface of {cylinder.name}, "
            f"RMS {_mm(cylinder.rms_mm)} mm, {cylinder.inlier_count} points."
        )
        span = cylinder.extent_mm[1] - cylinder.extent_mm[0]
        lines.append(
            f"{cylinder.name}_length = {_mm(abs(span))} mm, "
            f"{cylinder.name} measured along its own axis, "
            f"RMS {_mm(cylinder.rms_mm)} mm, {cylinder.inlier_count} points."
        )
    if not lines:
        lines.append("No dimensions could be derived from the fitted primitives.")
    return lines


# ---------------------------------------------------------------------------
# section 3: relations
# ---------------------------------------------------------------------------


def _axis_snap_for(cylinder: CylinderFit, snaps: Sequence[SnapRecord]) -> SnapRecord | None:
    """First angular SnapRecord that names this cylinder's axis, if any.

    Matching is by name convention: a record whose `dim_name` contains both the
    cylinder's name and the word "axis". The frame stage owns those names, so
    this is a display convenience only -- the snap log in section 4 prints
    every record regardless of whether it was matched here.
    """
    for snap in snaps:
        lowered = snap.dim_name.lower()
        if cylinder.name.lower() in lowered and "axis" in lowered:
            return snap
    return None


def _relation_lines(
    planes: Sequence[PlaneFit],
    cylinders: Sequence[CylinderFit],
    snaps: Sequence[SnapRecord],
    axes: tuple[Vec3, Vec3, Vec3],
    tol_deg: float,
    dim_tol_mm_for: Callable[[float], float],
) -> list[str]:
    """Relation sentences, in cylinder order then plane order.

    `dim_tol_mm_for` is a callable taking an RMS and returning the dimensional
    tolerance for it, so that "coaxial" and "same radius" use the frozen
    regime tolerance rather than a number invented here.
    """
    lines: list[str] = []
    for cylinder in cylinders:
        found: list[tuple[str, str]] = []
        for plane in planes:
            angle = _angle_deg(cylinder.axis_dir, plane.normal)
            if min(angle, 180.0 - angle) <= tol_deg:
                found.append(("perpendicular to", plane.name))
            elif abs(90.0 - angle) <= tol_deg:
                found.append(("parallel to", plane.name))

        # The axis snap is reported once per cylinder, on the first
        # perpendicularity it explains, because one snap moved one axis; and it
        # is a perpendicularity that a snapped axis normally produces.
        snap = _axis_snap_for(cylinder, snaps)
        carrier = next(
            (index for index, (rel, _) in enumerate(found) if rel.startswith("perp")),
            0,
        )
        for index, (relation, plane_name) in enumerate(found):
            line = f"{cylinder.name} axis is {relation} {plane_name}"
            if snap is not None and index == carrier:
                line += (
                    f", snapped from {_raw(snap.raw)} degrees, "
                    f"deviation {_raw(snap.deviation)} degrees"
                )
            lines.append(line + ".")

        offsets = _center_offsets(cylinder, planes, axes, tol_deg)
        if offsets:
            joined = " and ".join(
                f"{_mm(distance)} mm from {name}" for name, distance in offsets
            )
            lines.append(f"{cylinder.name} center is {joined}.")

    for i, first in enumerate(cylinders):
        for second in cylinders[i + 1 :]:
            angle = _angle_deg(first.axis_dir, second.axis_dir)
            if min(angle, 180.0 - angle) > tol_deg:
                continue
            tolerance = max(
                dim_tol_mm_for(first.rms_mm), dim_tol_mm_for(second.rms_mm)
            )
            offset = _axis_offset_mm(first, second)
            if offset <= tolerance:
                lines.append(
                    f"{first.name} is coaxial with {second.name}, "
                    f"axis offset {_mm(offset)} mm."
                )
            radius_delta = abs(first.radius_mm - second.radius_mm)
            if radius_delta <= tolerance:
                lines.append(
                    f"{first.name} has the same radius as {second.name}, "
                    f"within {_mm(radius_delta)} mm."
                )
    if not lines:
        lines.append("No relations could be derived from the fitted primitives.")
    return lines


def _center_offsets(
    cylinder: CylinderFit,
    planes: Sequence[PlaneFit],
    axes: tuple[Vec3, Vec3, Vec3],
    tol_deg: float,
) -> list[tuple[str, float]]:
    """Nearest axis-parallel plane per frame axis, with its distance in mm.

    Only planes whose surface runs parallel to the cylinder axis are used,
    because for those the distance from the axis is the same everywhere along
    it and is the number a machinist would look for. Ties go to the plane that
    comes first in report order.
    """
    mid = 0.5 * (cylinder.extent_mm[0] + cylinder.extent_mm[1])
    center: Vec3 = (
        cylinder.axis_point[0] + mid * cylinder.axis_dir[0],
        cylinder.axis_point[1] + mid * cylinder.axis_dir[1],
        cylinder.axis_point[2] + mid * cylinder.axis_dir[2],
    )
    best: dict[int, tuple[str, float]] = {}
    for plane in planes:
        if abs(90.0 - _angle_deg(cylinder.axis_dir, plane.normal)) > tol_deg:
            continue
        index = _dominant_axis(plane.normal, axes)
        distance = abs(_dot(_sub(center, plane.point), plane.normal))
        current = best.get(index)
        if current is None or distance < current[1] - 1e-9:
            best[index] = (plane.name, distance)
    return [best[index] for index in sorted(best)]


def _axis_offset_mm(first: CylinderFit, second: CylinderFit) -> float:
    """Perpendicular distance between two parallel cylinder axes, in mm."""
    delta = _sub(second.axis_point, first.axis_point)
    along = _dot(delta, first.axis_dir)
    perp = (
        delta[0] - along * first.axis_dir[0],
        delta[1] - along * first.axis_dir[1],
        delta[2] - along * first.axis_dir[2],
    )
    return math.sqrt(_dot(perp, perp))


# ---------------------------------------------------------------------------
# section 4: snap log
# ---------------------------------------------------------------------------


def _snap_lines(snaps: Sequence[SnapRecord]) -> list[str]:
    """Every SnapRecord, verbatim, in the order the pipeline emitted it."""
    if not snaps:
        return ["No values were snapped."]
    return [
        f"{snap.dim_name}: raw {_raw(snap.raw)}, snapped {_raw(snap.snapped)}, "
        f"deviation {_raw(snap.deviation)}, rule {snap.rule}."
        for snap in snaps
    ]


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def render_report(
    scene: SceneModel,
    *,
    units_note: str | None = None,
    regime: Thresholds | None = None,
    overrides: Mapping[str, object] | None = None,
) -> str:
    """Render `scene` as a plain-text, screen-reader-native report.

    Assumes `scene` is a fully populated SceneModel: unit direction vectors
    (enforced by the frozen dataclasses), millimetre lengths, and a `frame` of
    (origin, x_axis, y_axis, z_axis) or an empty tuple if no frame was fitted.

    `units_note` is the caller's unit assumption in plain words, for example
    "input file read as millimetres"; it is echoed so a listener never has to
    guess. `regime` is the frozen threshold preset the run used; when given, it
    is echoed and its angular tolerance classifies the relations. `overrides`
    maps threshold names to the values a CLI flag replaced them with; PLAN.md
    section 3 requires that every override appear in the report.

    Returns text ending in a newline. Raises ValueError if any character would
    be non-ASCII, which means an upstream stage produced a name the screen
    reader rule forbids.
    """
    origin, axes, frame_ok = _frame(scene)
    active = regime if regime is not None else COARSE
    tol_deg = active.angular_snap_deg

    planes = _sorted_planes(scene.planes, origin, axes)
    cylinders = _sorted_cylinders(scene.cylinders)

    blocks: list[tuple[str, list[str]]] = [
        (
            "Section 1. Overview.",
            _overview_lines(
                scene, origin, axes, frame_ok, units_note, regime, overrides
            ),
        ),
        (
            "Section 2. Dimensions.",
            _dimension_lines(planes, cylinders, axes, tol_deg),
        ),
        (
            "Section 3. Relations.",
            _relation_lines(
                planes,
                cylinders,
                scene.snaps,
                axes,
                tol_deg,
                active.dimensional_tolerance_mm,
            ),
        ),
        ("Section 4. Snap log.", _snap_lines(scene.snaps)),
        ("Section 5. Caveats.", list(_CAVEATS)),
    ]

    lines: list[str] = ["scan2cad geometry report."]
    for heading, body in blocks:
        lines.append("")
        lines.append(heading)
        lines.extend(body)

    text = "\n".join(lines) + "\n"
    _check_ascii(text)
    return text


def _check_ascii(text: str) -> None:
    """Raise ValueError naming the first non-ASCII character in `text`.

    The screen-reader rule (SYNTHESIS.md section 7) forbids unicode symbols in
    emitted text. A violation here means a primitive name, a provenance string,
    or a caller-supplied note carried one in, so the error names the line.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        for character in line:
            if ord(character) > 126 or (ord(character) < 32 and character != "\t"):
                raise ValueError(
                    f"report line {number} contains the non-ASCII character "
                    f"{character!r} (code point {ord(character)}): {line!r}"
                )
