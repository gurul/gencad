"""Emit an editable, named-dimension build123d skeleton from a SceneModel.

This is the "draft" half of describe-and-draft (PLAN.md WI-6). It turns a
`SceneModel` into a standalone Python script that:

  a. opens with a docstring carrying the two-channel disclaimer and provenance,
  b. declares every scan-derived number as a NAMED DIMENSION with its raw fit,
     its snapped value, the deviation, the residual and the inlier count,
  c. builds build123d datums -- one `Plane` per fitted plane, one `Axis` per
     fitted cylinder,
  d. builds bounded reference surfaces on those datums, sized to the observed
     inlier footprint, labelled per primitive and collected into a `Compound`,
  e. exports that compound to STEP -- reference surfaces for inspection, not a
     solid and not printable,
  f. ends with assembly hints as COMMENTS ONLY. No solid, no Boolean and no
     extrude is ever emitted as executable code (PLAN.md ground rule 5).

The emitted script imports build123d and the standard library `sys` and
nothing else, so it runs under the project venv with no scan2cad on the path.
That is deliberate: the user is meant to keep, edit and rerun the script long
after the scan that produced it is gone.

Every emitted length is millimetres and every emitted angle is degrees, the
same convention as `primitives.py`. Output is ASCII only, per SYNTHESIS.md
ruling 7; `emit_script` raises if that is ever violated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .primitives import CylinderFit, PlaneFit, SceneModel, SnapRecord

Vec3 = tuple[float, float, float]

DEFAULT_STEP_NAME = "part_ref.step"

# Presentation-only constant. Two plane normals whose dot product is below this
# are called "parallel and opposing" when writing the gap hints and the gap
# named dimensions. It is NOT a snapping threshold and it never changes a
# fitted number -- snapping lives in frame.py against the frozen thresholds
# (SYNTHESIS.md ruling 6). It only decides which comment lines get written.
HINT_ANTIPARALLEL_DOT = -0.99

# The marker every scan-derived dimension line carries (PLAN.md ground rule 1).
VERIFY_MARKER = "-- VERIFY WITH CALIPER"

_ASCII_ERROR = (
    "emitted script contains a non-ASCII character; all scan2cad output is "
    "ASCII only so that a screen reader never has to guess (SYNTHESIS.md 7)"
)


# --------------------------------------------------------------------------
# small vector helpers (kept local so this module stays numpy-free)
# --------------------------------------------------------------------------


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(a: Vec3) -> Vec3:
    """Return `a` scaled to unit length.

    Assumes `a` is not the zero vector; raises ValueError if it is, because a
    zero direction here means an upstream fit produced a degenerate primitive.
    """
    norm = math.sqrt(_dot(a, a))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError(f"cannot normalise degenerate direction {a}")
    return (a[0] / norm, a[1] / norm, a[2] / norm)


_WORLD_AXES: tuple[Vec3, Vec3, Vec3] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def plane_uv_basis(normal: Vec3) -> tuple[Vec3, Vec3]:
    """Return the (u, v) in-plane basis this project uses for `PlaneFit.extent`.

    `PlaneFit.extent` is (u_min, u_max, v_min, v_max) in "plane coordinates",
    and plane coordinates are only meaningful if every stage picks the same u
    and v. This function is that shared convention, and the fitter that fills
    `extent` must use it too:

      helper = the world axis least aligned with the normal
      u      = normalize(helper x normal)
      v      = normal x u

    so that (u, v, normal) is right-handed. The choice of helper is a pure
    function of the normal, with ties broken by axis order, so the basis is
    deterministic. Assumes `normal` is unit length.
    """
    helper = min(_WORLD_AXES, key=lambda axis: abs(_dot(axis, normal)))
    u = _normalize(_cross(helper, normal))
    v = _cross(normal, u)
    return u, v


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------


def _num(value: float, sig: int = 6) -> str:
    """Format a float for the emitted script, ASCII and round-trip readable.

    Assumes `value` is finite. `%g` is used so that a tidy snapped value like
    20.2 prints as "20.2" rather than "20.200000", which matters because these
    literals are meant to be read aloud and edited by hand.
    """
    if not math.isfinite(value):
        raise ValueError(f"cannot emit non-finite number {value!r}")
    text = f"{value:.{sig}g}"
    # Avoid "-0" and exponent forms that read badly aloud for near-zero values.
    if text in ("-0", "0"):
        return "0.0"
    if "e" in text or "." in text:
        return text
    return text + ".0"


def _vec(vec: Sequence[float], sig: int = 10) -> str:
    """Format a 3-vector as a Python tuple literal at coordinate precision."""
    return "(" + ", ".join(_num(float(component), sig) for component in vec) + ")"


def _ident(name: str) -> str:
    """Turn a primitive or dimension name into a safe Python identifier.

    Assumes `name` is short and human-chosen (for example "plane_top" or
    "cyl_bore_1"). Anything that is not a letter, digit or underscore becomes
    an underscore, and a leading digit is prefixed, so that an unusual name
    from the frame stage can never emit a script that fails to parse.
    """
    cleaned = "".join(char if (char.isalnum() and char.isascii()) else "_" for char in name)
    cleaned = cleaned.strip("_") or "unnamed"
    if cleaned[0].isdigit():
        cleaned = "d_" + cleaned
    return cleaned


# --------------------------------------------------------------------------
# named dimensions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NamedDimension:
    """One `name = value  # provenance comment` line of the emitted script."""

    ident: str
    value: float
    comment: str


def _residual_note(rms_mm: float | None, inlier_count: int | None) -> str:
    """Return the ", RMS x mm, N pts" tail of a dimension comment, or ""."""
    parts: list[str] = []
    if rms_mm is not None:
        parts.append(f"RMS {_num(rms_mm)} mm")
    if inlier_count is not None:
        parts.append(f"{inlier_count} pts")
    return (", " + ", ".join(parts)) if parts else ""


def _owner_of(dim_name: str, scene: SceneModel) -> PlaneFit | CylinderFit | None:
    """Return the primitive a snap record's dimension belongs to, if obvious.

    `SnapRecord` carries no back-pointer, so the association is by name: a
    record called "cyl_bore_1_radius" belongs to the primitive named
    "cyl_bore_1". A prefix match is preferred; failing that, a primitive named
    anywhere inside the dimension name is accepted, which catches names like
    "gap_plane_top_plane_bottom". The longest matching primitive name wins, so
    "plane_top" does not steal a dimension of "plane_top_left".

    Returns None when no primitive is named at all -- a record called "height"
    could belong to any pair of faces. In that case the emitted comment omits
    the residual and the point count instead of attributing someone else's.
    """
    candidates: list[PlaneFit | CylinderFit] = [*scene.planes, *scene.cylinders]
    matches = [prim for prim in candidates if dim_name.startswith(prim.name)]
    if not matches:
        matches = [prim for prim in candidates if prim.name in dim_name]
    if not matches:
        return None
    return max(matches, key=lambda prim: len(prim.name))


def _snap_dimension(snap: SnapRecord, scene: SceneModel) -> NamedDimension:
    """Build the named dimension line for one SnapRecord.

    Assumes `snap.snapped` is the value the rest of the model already uses --
    the snapping stage rebuilds its primitives, so the emitted geometry and the
    emitted dimension agree by construction.
    """
    owner = _owner_of(snap.dim_name, scene)
    rms = owner.rms_mm if owner is not None else None
    pts = owner.inlier_count if owner is not None else None
    comment = (
        f"fitted {_num(snap.raw)}, snapped {_num(snap.snapped)} "
        f"(dev {_num(snap.deviation)}), rule {snap.rule}"
        f"{_residual_note(rms, pts)} {VERIFY_MARKER}"
    )
    return NamedDimension(_ident(snap.dim_name), snap.snapped, comment)


def _plane_gaps(planes: Sequence[PlaneFit]) -> list[tuple[PlaneFit, PlaneFit, float]]:
    """Return (plane_a, plane_b, gap_mm) for every parallel opposing pair.

    "Opposing" means the two unit normals point away from each other, which is
    what a pair of outer faces of a block looks like after fitting. The gap is
    the distance from plane_b's point to plane_a, which is the thickness the
    user would type into a Box. Pairs are returned in index order so the output
    is deterministic. See HINT_ANTIPARALLEL_DOT: this is presentation only.
    """
    pairs: list[tuple[PlaneFit, PlaneFit, float]] = []
    for i, first in enumerate(planes):
        for second in planes[i + 1 :]:
            if _dot(first.normal, second.normal) > HINT_ANTIPARALLEL_DOT:
                continue
            gap = abs(_dot(_sub(second.point, first.point), first.normal))
            pairs.append((first, second, gap))
    return pairs


def _collect_dimensions(scene: SceneModel) -> tuple[list[NamedDimension], list[str]]:
    """Return the named dimensions plus any honesty notes about collisions.

    Order is fixed so the emitted file is byte-stable for a given SceneModel:
    snap-log dimensions first (they are the audited ones), then per-primitive
    dimensions in scene order, then derived gaps between opposing planes.

    A generated name that collides with a snap-log name is dropped rather than
    silently renamed, and a note is returned naming both values when they
    disagree -- there is no silent anything in this pipeline.
    """
    dims: list[NamedDimension] = []
    notes: list[str] = []
    seen: dict[str, float] = {}

    def add(dim: NamedDimension) -> None:
        previous = seen.get(dim.ident)
        if previous is not None:
            if abs(previous - dim.value) > 1e-9:
                notes.append(
                    f"dimension name {dim.ident} was defined twice with different "
                    f"values: kept {_num(previous)}, dropped {_num(dim.value)}"
                )
            return
        seen[dim.ident] = dim.value
        dims.append(dim)

    for snap in scene.snaps:
        add(_snap_dimension(snap, scene))

    for plane in scene.planes:
        base = _ident(plane.name)
        u_min, u_max, v_min, v_max = plane.extent
        tail = _residual_note(plane.rms_mm, plane.inlier_count)
        add(
            NamedDimension(
                f"{base}_width",
                u_max - u_min,
                f"observed footprint across the plane, not a part dimension"
                f"{tail} {VERIFY_MARKER}",
            )
        )
        add(
            NamedDimension(
                f"{base}_height",
                v_max - v_min,
                f"observed footprint across the plane, not a part dimension"
                f"{tail} {VERIFY_MARKER}",
            )
        )

    for cylinder in scene.cylinders:
        base = _ident(cylinder.name)
        t_min, t_max = cylinder.extent_mm
        tail = _residual_note(cylinder.rms_mm, cylinder.inlier_count)
        add(
            NamedDimension(
                f"{base}_radius",
                cylinder.radius_mm,
                f"fitted radius, diameter {_num(2.0 * cylinder.radius_mm)}"
                f"{tail} {VERIFY_MARKER}",
            )
        )
        add(
            NamedDimension(
                f"{base}_length",
                t_max - t_min,
                f"observed span along the axis, not necessarily the true depth"
                f"{tail} {VERIFY_MARKER}",
            )
        )

    for first, second, gap in _plane_gaps(scene.planes):
        worst_rms = max(first.rms_mm, second.rms_mm)
        add(
            NamedDimension(
                f"gap_{_ident(first.name)}_{_ident(second.name)}",
                gap,
                f"distance between opposing planes {first.name} and {second.name}, "
                f"RMS {_num(worst_rms)} mm (worse of the pair) {VERIFY_MARKER}",
            )
        )

    return dims, notes


# --------------------------------------------------------------------------
# geometry placement
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlanePlacement:
    """Where a plane's bounded reference face sits in world coordinates."""

    origin: Vec3  # centre of the observed footprint
    x_dir: Vec3  # the u basis vector from plane_uv_basis
    z_dir: Vec3  # the plane normal
    width: float  # u extent
    height: float  # v extent


def _place_plane(plane: PlaneFit) -> _PlanePlacement:
    """Resolve a PlaneFit into a centred build123d Plane plus a face size.

    Assumes `plane.extent` was measured in the basis returned by
    `plane_uv_basis`. The emitted datum is put at the centre of the observed
    footprint rather than at the raw fit point: it is the same infinite plane
    either way, and a centred origin is what `Face.make_rect` wants, so the
    datum and the reference face cannot drift apart when the user edits one.
    Raises ValueError on a zero-area footprint, which means a broken fit.
    """
    u_min, u_max, v_min, v_max = plane.extent
    width = u_max - u_min
    height = v_max - v_min
    if width <= 0.0 or height <= 0.0:
        raise ValueError(
            f"plane {plane.name!r} has a degenerate footprint "
            f"{plane.extent}; cannot emit a bounded reference face"
        )
    u, v = plane_uv_basis(plane.normal)
    centre = _add(
        plane.point,
        _add(_scale(u, 0.5 * (u_min + u_max)), _scale(v, 0.5 * (v_min + v_max))),
    )
    return _PlanePlacement(centre, u, plane.normal, width, height)


def _cylinder_start(cylinder: CylinderFit) -> Vec3:
    """Return the world point where the cylinder's inlier span begins.

    Assumes `extent_mm` is (t_min, t_max), the span of the inlier projections
    onto the axis measured from `axis_point`. Raises ValueError on a zero-length
    span, which means a broken fit rather than a short feature.
    """
    t_min, t_max = cylinder.extent_mm
    if t_max - t_min <= 0.0:
        raise ValueError(
            f"cylinder {cylinder.name!r} has a degenerate axial extent "
            f"{cylinder.extent_mm}; cannot emit a bounded reference face"
        )
    return _add(cylinder.axis_point, _scale(cylinder.axis_dir, t_min))


# --------------------------------------------------------------------------
# the emitter
# --------------------------------------------------------------------------


def _header(
    scene: SceneModel,
    source: str,
    overrides: Mapping[str, object] | None,
    generated_at: str | None,
) -> list[str]:
    """Build the module docstring: disclaimer, provenance, threshold echo."""
    lines = [
        '"""Editable build123d skeleton drafted by scan2cad.',
        "",
        "Every number in this file is a SCAN DRAFT, not a measurement.",
        "The scan is the draft; the caliper or the datasheet is the truth.",
        "Each named dimension below carries its raw fit, its snapped value, the",
        "residual and the inlier count, and is marked VERIFY WITH CALIPER.",
        "Overwrite a value from a caliper or a datasheet and rerun this file.",
        "",
        f"Provenance: {scene.provenance}.",
        f"Source: {source}.",
    ]
    if generated_at is not None:
        lines.append(f"Drafted at: {generated_at}.")
    if scene.provenance == "synthetic":
        lines += [
            "",
            "This model came from synthetic data. It verifies that the code path",
            "runs. It says nothing about the accuracy of a real phone scan.",
        ]
    lines += [
        "",
        f"Fitted primitives: {len(scene.planes)} planes and "
        f"{len(scene.cylinders)} cylinders.",
        f"Snapping actions recorded: {len(scene.snaps)}.",
    ]
    if overrides:
        lines.append("")
        lines.append("Thresholds were overridden on the command line for this run:")
        for key in sorted(overrides):
            lines.append(f"  {key} = {overrides[key]}")
    else:
        lines.append("Thresholds: frozen defaults, no command-line overrides.")
    lines += [
        "",
        "The STEP this script writes holds REFERENCE SURFACES only.",
        "It is NOT a solid and NOT printable. It exists so that a sighted",
        "reviewer or a CAD kernel can look at the fitted faces directly.",
        '"""',
    ]
    return lines


def _dimension_block(dims: Sequence[NamedDimension], notes: Sequence[str]) -> list[str]:
    """Build the NAMED DIMENSIONS section."""
    lines = [
        "# ---------------------------------------------------------------------",
        "# NAMED DIMENSIONS -- all millimetres. Edit these, not the geometry.",
        "# ---------------------------------------------------------------------",
    ]
    for note in notes:
        lines.append(f"# NOTE: {note}")
    if not dims:
        lines.append("# No dimensions were recovered from this scan.")
    for dim in dims:
        lines.append(f"{dim.ident} = {_num(dim.value)}  # {dim.comment}")
    lines.append("")
    return lines


def _datum_block(scene: SceneModel) -> list[str]:
    """Build the datum section: one Plane per plane, one Axis per cylinder."""
    lines = [
        "# ---------------------------------------------------------------------",
        "# DATUMS -- the fitted frame, one Plane per fitted plane, one Axis per",
        "# fitted cylinder. Plane origins sit at the centre of the observed",
        "# footprint; the plane itself is unbounded.",
        "# ---------------------------------------------------------------------",
    ]
    if len(scene.frame) >= 4:
        origin, x_dir, _y_dir, z_dir = scene.frame[0], scene.frame[1], scene.frame[2], scene.frame[3]
        lines.append(
            f"datum_frame = Plane(origin={_vec(origin)}, "
            f"x_dir={_vec(x_dir)}, z_dir={_vec(z_dir)})"
        )
        lines.append("# datum_frame is the dominant orthogonal frame recovered from the scan.")
    else:
        lines.append("datum_frame = Plane.XY  # no dominant frame was recovered; world axes used")

    for plane in scene.planes:
        placement = _place_plane(plane)
        ident = _ident(plane.name)
        lines.append(
            f"datum_{ident} = Plane(origin={_vec(placement.origin)}, "
            f"x_dir={_vec(placement.x_dir)}, z_dir={_vec(placement.z_dir)})"
        )
    for cylinder in scene.cylinders:
        ident = _ident(cylinder.name)
        lines.append(
            f"axis_{ident} = Axis({_vec(_cylinder_start(cylinder))}, "
            f"{_vec(cylinder.axis_dir)})"
        )
    lines.append("")
    return lines


def _surface_block(scene: SceneModel) -> list[str]:
    """Build the reference-surface section and the labelled Compound."""
    lines = [
        "# ---------------------------------------------------------------------",
        "# REFERENCE SURFACES -- bounded faces sized to the observed inliers.",
        "# These are surfaces, NOT a solid. Nothing here is printable.",
        "# ---------------------------------------------------------------------",
        "reference_faces = []",
    ]
    for plane in scene.planes:
        ident = _ident(plane.name)
        lines += [
            "",
            f"face_{ident} = Face.make_rect({ident}_width, {ident}_height, datum_{ident})",
            f'face_{ident}.label = "{plane.name}"',
            f"reference_faces.append(face_{ident})",
        ]
    for cylinder in scene.cylinders:
        ident = _ident(cylinder.name)
        lines += [
            "",
            f"_solid_{ident} = Solid.make_cylinder(",
            f"    {ident}_radius,",
            f"    {ident}_length,",
            f"    Plane(origin=axis_{ident}.position, z_dir=axis_{ident}.direction),",
            ")",
            f"face_{ident} = _solid_{ident}.faces().filter_by(GeomType.CYLINDER)[0]",
            f'face_{ident}.label = "{cylinder.name}"',
            f"reference_faces.append(face_{ident})",
        ]
    lines += [
        "",
        "reference_surfaces = Compound(children=reference_faces)",
        'reference_surfaces.label = "scan2cad_reference_surfaces"',
        "",
    ]
    return lines


def _export_block() -> list[str]:
    """Build the STEP export section and the plain-language confirmation."""
    return [
        "# ---------------------------------------------------------------------",
        "# STEP EXPORT -- reference surfaces only. NOT a solid, NOT printable.",
        "# ---------------------------------------------------------------------",
        "export_step(reference_surfaces, STEP_PATH)",
        'print("scan2cad reference surfaces written to " + STEP_PATH)',
        'print("face count " + str(len(reference_faces)) + '
        '" -- reference surfaces only, not a solid, not printable")',
        "",
    ]


def _hint_block(scene: SceneModel) -> list[str]:
    """Build the assembly hints. Comments only; nothing here executes."""
    lines = [
        "# ---------------------------------------------------------------------",
        "# ASSEMBLY HINTS -- comments only. scan2cad never emits a solid, an",
        "# extrude or a Boolean as running code (PLAN.md ground rule 5), because",
        "# guessing which face is a wall and which is a pocket is your call.",
        "# ---------------------------------------------------------------------",
    ]
    gaps = _plane_gaps(scene.planes)
    for first, second, gap in gaps:
        ident = f"gap_{_ident(first.name)}_{_ident(second.name)}"
        lines.append(
            f"# HINT: {first.name} parallel {second.name}, gap {_num(gap)} "
            f"-> a box thickness? Uncomment and edit:"
        )
        lines.append(f"# part = Box(width, depth, {ident})")
    for cylinder in scene.cylinders:
        ident = _ident(cylinder.name)
        lines.append(
            f"# HINT: {cylinder.name} radius {_num(cylinder.radius_mm)}, axis "
            f"{_vec(cylinder.axis_dir, 4)} -> a bore or a boss? Uncomment and edit:"
        )
        lines.append(
            f"# part = part - Cylinder({ident}_radius, {ident}_length).located("
            f"Location(axis_{ident}.position))"
        )
    if not gaps and not scene.cylinders:
        lines.append("# No parallel plane pairs and no cylinders: nothing to hint at.")
    lines.append("# HINT: whichever solid you build, verify its dimensions with a caliper.")
    lines.append("")
    return lines


def emit_script(
    scene: SceneModel,
    *,
    source: str = "unknown input",
    step_path: str = DEFAULT_STEP_NAME,
    overrides: Mapping[str, object] | None = None,
    generated_at: str | None = None,
) -> str:
    """Return the full text of a standalone build123d skeleton for `scene`.

    Assumes `scene` is the post-snapping model: every value in it is already
    the value the user should see, and every change made to reach it appears in
    `scene.snaps`. Assumes plane extents were measured in the basis returned by
    `plane_uv_basis`.

    `source` names the input file for the header. `step_path` is the default
    STEP destination baked into the script; the script's first command-line
    argument overrides it at run time. `overrides` is echoed verbatim in the
    header so a reader can tell the run did not use frozen thresholds.
    `generated_at` is optional and omitted by default, which keeps the output
    byte-stable for a given SceneModel so golden tests stay meaningful.

    Raises ValueError if a primitive has a degenerate footprint or span, or if
    the result would contain a non-ASCII character.
    """
    dims, notes = _collect_dimensions(scene)

    lines: list[str] = []
    lines += _header(scene, source, overrides, generated_at)
    lines += [
        "",
        "import sys",
        "",
        "from build123d import (",
        "    Axis,",
        "    Compound,",
        "    Face,",
        "    GeomType,",
        "    Plane,",
        "    Solid,",
        "    export_step,",
        ")",
        "",
        "# STEP destination: first command-line argument wins, else this default.",
        f"STEP_PATH = sys.argv[1] if len(sys.argv) > 1 else {step_path!r}",
        "",
    ]
    lines += _dimension_block(dims, notes)
    lines += _datum_block(scene)
    lines += _surface_block(scene)
    lines += _export_block()
    lines += _hint_block(scene)

    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(_ASCII_ERROR) from exc
    return text


def write_script(
    scene: SceneModel,
    path: str | Path,
    *,
    source: str = "unknown input",
    step_path: str = DEFAULT_STEP_NAME,
    overrides: Mapping[str, object] | None = None,
    generated_at: str | None = None,
) -> Path:
    """Write the skeleton for `scene` to `path` and return the resolved path.

    Assumes the parent directory exists or can be created. The file is written
    as ASCII with UNIX line endings so it reads the same in every editor.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        emit_script(
            scene,
            source=source,
            step_path=step_path,
            overrides=overrides,
            generated_at=generated_at,
        ),
        encoding="ascii",
        newline="\n",
    )
    return target.resolve()
