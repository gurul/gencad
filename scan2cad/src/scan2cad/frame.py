"""Dominant frame, snapping and merging (WI-4).

This is the stage that turns a bag of independently fitted primitives into one
object description: it finds the orthogonal frame the object is built on, pulls
nearly-axis-aligned faces and bores onto that frame, harmonises radii that are
the same feature measured twice, and rounds the surviving dimensions onto a
0.1 mm grid -- but only ever inside the frozen tolerances of `thresholds.py`.

Two rules govern everything here.

  1. No silent snapping (PLAN.md ground rule 6). Every value this module
     changes produces exactly one `SnapRecord` naming the dimension, the raw
     fitted number, the snapped number, the deviation and the rule that allowed
     it. The report prints all of them verbatim. If a mutation is not worth a
     record, it is not worth making.
  2. Nothing is snapped outside tolerance. A face 8 degrees off axis in the
     coarse regime stays 8 degrees off axis and is reported that way. Tidiness
     is never bought with a number the fit does not support.

Explicitly out of scope (PLAN.md WI-4): pairwise constraint graphs, any solver,
trimming, sewing. This module does local, individually justified moves.

Conventions
-----------
Lengths are millimetres and angles are degrees, as everywhere else.

`SceneModel.frame` is `(origin, x_axis, y_axis, z_axis)` -- the convention
`report.py` and `emit_build123d.py` already read. The origin is the centroid of
the fitted primitive reference points; only differences from it are ever used
downstream, so it carries no meaning beyond "somewhere inside the object".

The triad is right-handed, and each axis is sign-canonicalised to point along
the world axis it is most nearly aligned with. That keeps two runs of the same
scene, and two scenes of the same object, reading the same way.

The frame is the object's, not the world's: PLAN.md WI-4 fixes Z as the largest
normal cluster and X as the best near-perpendicular one, so on a 60 by 40 by
20 mm block the 60 by 20 faces are the second largest cluster and become the
frame's X, whichever world axis they happen to lie on. Face labels and the
report's width, depth and height are therefore frame-relative and internally
consistent, not promises about world X, Y and Z. Anything comparing a reported
dimension against a ground-truth table must match through the geometry, not by
assuming the frame's width is the world's X.

Snap record dimension names follow the convention `emit_build123d._owner_of`
matches on, so a record can always be traced back to the primitive it moved:

  plane_top_normal            plane normal pulled onto a frame axis
  cylinder_0_axis             cylinder axis pulled onto a frame axis
  cylinder_0_diameter         diameter rounded onto the 0.1 mm grid
  cylinder_0_radius           radius pulled onto a shared radius cluster
  cylinder_0_axis_offset      a concentric neighbour merged onto this axis
  gap_plane_top_plane_bottom  face-to-face gap rounded onto the 0.1 mm grid

Angular records carry the misalignment angle itself: `raw` is the angle between
the fitted direction and the frame axis it was pulled onto, and `snapped` is
0.0. `deviation` is always `snapped - raw`, in millimetres for lengths and in
degrees for angles, matching the frozen `SnapRecord` docstring.

Documented approximations
-------------------------
`PlaneFit.extent` is a 2D footprint measured in a basis derived from the
pre-snap normal, and this stage has no access to the inlier points, so a
rotated plane keeps its old footprint numbers. The rotation involved is at most
the angular tolerance (5 degrees coarse), and the footprint is only ever used
to size reference faces for inspection, never as a dimension.

Semantic face names assume outward-facing normals, which is what `io_mesh`'s
consistent orientation and `ransac_cgal`'s mean-normal sign rule produce on a
closed scan. On an unoriented cloud the labels can come out inverted; they are
a convenience for reading, and every dimension is stated between two named
planes, so an inverted label costs nothing but a little confusion.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from .primitives import CylinderFit, PlaneFit, SceneModel, SnapRecord, Vec3
from .thresholds import COARSE, SNAP_ROUND_MM, Thresholds

__all__ = [
    "FrameError",
    "ObjectFrame",
    "align_and_snap",
    "cluster_plane_normals",
    "dominant_frame",
]

# Below these an angle or a length is not a change at all, just float dust, and
# emitting a SnapRecord for it would bury the real snaps in noise.
_ANGLE_EPS_DEG = 1e-9
_LENGTH_EPS_MM = 1e-9

_WORLD_AXES = np.eye(3, dtype=np.float64)

# Face labels per frame axis, as (negative direction, positive direction).
_AXIS_LABELS: tuple[tuple[str, str], ...] = (
    ("left", "right"),
    ("front", "back"),
    ("bottom", "top"),
)


class FrameError(ValueError):
    """The frame stage was handed primitives it cannot work with.

    Raised for a non-ASCII or empty primitive name, a duplicated name, or a
    non-finite number. Not raised for a scene that simply has no frame in it:
    an unalignable pile of primitives is a legitimate answer about a bad scan
    and comes back as a SceneModel with an empty frame.
    """


# ---------------------------------------------------------------------------
# small vector helpers
# ---------------------------------------------------------------------------


def _arr(vec: Sequence[float]) -> np.ndarray:
    return np.asarray(vec, dtype=np.float64)


def _tuple3(vec: np.ndarray) -> Vec3:
    return (float(vec[0]), float(vec[1]), float(vec[2]))


def _unit(vec: np.ndarray) -> np.ndarray:
    """Return `vec` scaled to unit length.

    Assumes `vec` is not the zero vector; callers guard that, because a zero
    direction here means an upstream fitting bug.
    """
    norm = float(np.linalg.norm(vec))
    if not math.isfinite(norm) or norm <= 0.0:
        raise FrameError(f"cannot normalise the direction {vec!r}")
    return vec / norm


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Angle in degrees between two unit vectors, in [0, 180]."""
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a, b))))))


def _undirected_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Angle in degrees between two unit directions ignoring sign, in [0, 90]."""
    angle = _angle_deg(a, b)
    return min(angle, 180.0 - angle)


# ---------------------------------------------------------------------------
# input checking
# ---------------------------------------------------------------------------


def _check_names(planes: Sequence[PlaneFit], cylinders: Sequence[CylinderFit]) -> None:
    """Fail loudly on names this stage cannot carry into the report.

    Assumes primitive names come from `ransac_cgal` (plane_0, cylinder_0, ...).
    Names are checked rather than cleaned because the report is ASCII-only by
    decree (SYNTHESIS.md ruling 7) and a silently rewritten name would break
    the link between a snap record and the primitive it describes.
    """
    seen: set[str] = set()
    for primitive in (*planes, *cylinders):
        name = primitive.name
        if not name or not name.isascii() or name.strip() != name:
            raise FrameError(
                f"primitive name {name!r} must be non-empty printable ASCII"
            )
        if name in seen:
            raise FrameError(f"duplicate primitive name {name!r}")
        seen.add(name)


# ---------------------------------------------------------------------------
# normal clustering
# ---------------------------------------------------------------------------


def cluster_plane_normals(
    planes: Sequence[PlaneFit], tol_deg: float
) -> list[list[int]]:
    """Group plane indices whose normals point the same way, sign ignored.

    Agglomerative with complete linkage: two clusters merge only if *every*
    cross pair is within `tol_deg`, so a chain of planes each 4 degrees from
    the last never becomes one 20-degree cluster. Assumes `planes` is short
    (a handful of fitted faces), which the O(n^3) loop relies on.

    Sign is ignored because the two faces of a slab are one direction observed
    twice. Clusters come back ordered by total inlier count, largest first,
    with ties broken by first index so the result is deterministic.
    """
    normals = [_arr(plane.normal) for plane in planes]
    clusters: list[list[int]] = [[i] for i in range(len(planes))]

    def linkage(a: list[int], b: list[int]) -> float:
        return max(
            _undirected_angle_deg(normals[i], normals[j]) for i in a for j in b
        )

    while len(clusters) > 1:
        best: tuple[float, int, int] | None = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                distance = linkage(clusters[i], clusters[j])
                if best is None or distance < best[0] - 1e-12:
                    best = (distance, i, j)
        if best is None or best[0] > tol_deg:
            break
        _distance, i, j = best
        clusters[i] = sorted(clusters[i] + clusters[j])
        del clusters[j]

    clusters.sort(
        key=lambda members: (
            -sum(planes[i].inlier_count for i in members),
            min(members),
        )
    )
    return clusters


def _cluster_direction(planes: Sequence[PlaneFit], members: Sequence[int]) -> np.ndarray:
    """Inlier-weighted mean direction of one normal cluster, as a unit vector.

    Members are flipped to agree with the highest-inlier member before
    averaging, because the cluster ignores sign. Assumes `members` is non-empty
    and its normals are within the clustering tolerance of each other, so the
    weighted sum cannot cancel to zero.
    """
    ordered = sorted(members, key=lambda i: (-planes[i].inlier_count, i))
    reference = _arr(planes[ordered[0]].normal)
    total = np.zeros(3, dtype=np.float64)
    for index in ordered:
        normal = _arr(planes[index].normal)
        if float(np.dot(normal, reference)) < 0.0:
            normal = -normal
        total += max(planes[index].inlier_count, 1) * normal
    return _unit(total)


# ---------------------------------------------------------------------------
# the dominant frame
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectFrame:
    """The orthogonal frame an object appears to be built on.

    `supported` says, per axis in (x, y, z) order, whether that axis was
    derived from fitted geometry or merely completed to make a triad. Only
    supported axes are ever snapped to: an axis invented to fill out the triad
    of a single-face scan has no claim on anybody's normal, and snapping to it
    would manufacture structure the scan never showed.
    """

    origin: Vec3
    x_axis: Vec3
    y_axis: Vec3
    z_axis: Vec3
    supported: tuple[bool, bool, bool]

    def as_tuple(self) -> tuple[Vec3, Vec3, Vec3, Vec3]:
        """The (origin, x, y, z) tuple stored in `SceneModel.frame`."""
        return (self.origin, self.x_axis, self.y_axis, self.z_axis)

    def axes(self) -> tuple[Vec3, Vec3, Vec3]:
        """The triad alone, in (x, y, z) order."""
        return (self.x_axis, self.y_axis, self.z_axis)


def _canonical_sign(axis: np.ndarray) -> np.ndarray:
    """Flip `axis` so its largest-magnitude component is positive.

    A face normal cluster has a sign, but which sign depends on which face of
    the slab won the inlier count, and that is not a property of the object.
    Tying the sign to the world axes instead makes the frame reproducible.
    """
    dominant = int(np.argmax(np.abs(axis)))
    return -axis if axis[dominant] < 0.0 else axis


def _any_perpendicular(axis: np.ndarray) -> np.ndarray:
    """A deterministic unit vector perpendicular to `axis`."""
    helper = _WORLD_AXES[int(np.argmin(np.abs(axis)))]
    return _unit(np.cross(helper, axis))


def _origin(planes: Sequence[PlaneFit], cylinders: Sequence[CylinderFit]) -> Vec3:
    """Centroid of the primitive reference points.

    Assumes at least one primitive. Only used as the datum origin; every
    downstream number is a difference, so its exact placement carries no claim.
    """
    points = [_arr(plane.point) for plane in planes]
    points += [_arr(cylinder.axis_point) for cylinder in cylinders]
    return _tuple3(np.mean(np.vstack(points), axis=0))


def dominant_frame(
    planes: Sequence[PlaneFit],
    cylinders: Sequence[CylinderFit],
    thresholds: Thresholds = COARSE,
) -> ObjectFrame | None:
    """Recover the object's dominant orthogonal frame, or None if there is none.

    The rule (PLAN.md WI-4): the largest normal cluster defines Z; the best
    near-perpendicular cluster defines X; Y is Z cross X, and X is
    re-orthogonalised against Z first so the triad is exact.

    "Best" is the largest remaining cluster whose deviation from perpendicular
    to Z is inside the angular tolerance. A cluster further off than that is
    not treated as an axis at all: forcing it perpendicular would move it by
    more than the regime allows, which is exactly the silent snapping this
    project forbids, so X is completed arbitrarily instead and marked
    unsupported.

    With no planes at all the largest cylinder's axis defines Z, so a scan of
    a boss or a bore still gets an axis to align to. With no primitives, or
    with a degenerate direction, this returns None and the caller reports that
    no frame was fitted.
    """
    if not planes and not cylinders:
        return None

    z_supported = True
    if planes:
        clusters = cluster_plane_normals(planes, thresholds.angular_snap_deg)
        z_dir = _cluster_direction(planes, clusters[0])
        candidates = clusters[1:]
        x_seed: np.ndarray | None = None
        for members in candidates:
            direction = _cluster_direction(planes, members)
            if 90.0 - _undirected_angle_deg(z_dir, direction) <= thresholds.angular_snap_deg:
                x_seed = direction
                break
    else:
        largest = max(cylinders, key=lambda c: (c.inlier_count, c.name))
        z_dir = _arr(largest.axis_dir)
        x_seed = None

    z_dir = _canonical_sign(_unit(z_dir))

    if x_seed is None:
        x_supported = False
        x_dir = _any_perpendicular(z_dir)
    else:
        residual = x_seed - float(np.dot(x_seed, z_dir)) * z_dir
        if float(np.linalg.norm(residual)) <= 1e-9:  # pragma: no cover - defensive
            x_supported = False
            x_dir = _any_perpendicular(z_dir)
        else:
            x_supported = True
            x_dir = _unit(residual)

    x_dir = _canonical_sign(x_dir)
    # Y is not observed directly: on a box the third normal cluster lands on it,
    # but it is defined here by the cross product so the triad is exactly
    # orthonormal. It is supported exactly when X and Z both are.
    y_dir = _unit(np.cross(z_dir, x_dir))

    return ObjectFrame(
        origin=_origin(planes, cylinders),
        x_axis=_tuple3(x_dir),
        y_axis=_tuple3(y_dir),
        z_axis=_tuple3(z_dir),
        supported=(x_supported, x_supported, z_supported),
    )


# ---------------------------------------------------------------------------
# rule labels
# ---------------------------------------------------------------------------


def _tolerance_label(thresholds: Thresholds) -> str:
    """Short ASCII name of the regime's dimensional tolerance, for rule text.

    Assumes the frozen `Thresholds` invariant that exactly one of the two
    dimensional fields is set.
    """
    if thresholds.dim_snap_mm is not None:
        return f"{thresholds.dim_snap_mm:g}mm"
    return f"{thresholds.dim_snap_rms_factor:g}xRMS"


def _angle_rule(thresholds: Thresholds) -> str:
    return f"axis-align {thresholds.angular_snap_deg:g}deg"


# ---------------------------------------------------------------------------
# angular snapping
# ---------------------------------------------------------------------------


def _nearest_axis(
    direction: np.ndarray, frame: ObjectFrame
) -> tuple[np.ndarray, float, int] | None:
    """Nearest signed supported frame axis to `direction`, with its angle.

    Returns (axis, angle_deg, axis_index), or None when no axis of the frame is
    supported by fitted geometry. Both signs of each axis are candidates, so a
    normal keeps the outward sense it was fitted with.
    """
    best: tuple[np.ndarray, float, int] | None = None
    for index, axis_tuple in enumerate(frame.axes()):
        if not frame.supported[index]:
            continue
        axis = _arr(axis_tuple)
        for signed in (axis, -axis):
            angle = _angle_deg(direction, signed)
            if best is None or angle < best[1] - 1e-12:
                best = (signed, angle, index)
    return best


def _snap_plane_normals(
    planes: Sequence[PlaneFit], frame: ObjectFrame, thresholds: Thresholds
) -> tuple[list[PlaneFit], list[SnapRecord]]:
    """Pull each plane normal onto a frame axis when it is inside tolerance.

    Assumes `frame` is orthonormal. A plane already exactly on axis is left
    alone and emits no record: there was no mutation to disclose. The plane's
    reference point and footprint extent are untouched (see module docstring).
    """
    snapped: list[PlaneFit] = []
    records: list[SnapRecord] = []
    rule = _angle_rule(thresholds)
    for plane in planes:
        nearest = _nearest_axis(_arr(plane.normal), frame)
        if nearest is None:
            snapped.append(plane)
            continue
        axis, angle, _index = nearest
        if angle > thresholds.angular_snap_deg or angle <= _ANGLE_EPS_DEG:
            snapped.append(plane)
            continue
        snapped.append(replace(plane, normal=_tuple3(_unit(axis))))
        records.append(
            SnapRecord(
                dim_name=f"{plane.name}_normal",
                raw=angle,
                snapped=0.0,
                deviation=-angle,
                rule=rule,
            )
        )
    return snapped, records


def _snap_cylinder_axes(
    cylinders: Sequence[CylinderFit], frame: ObjectFrame, thresholds: Thresholds
) -> tuple[list[CylinderFit], list[SnapRecord]]:
    """Pull each cylinder axis onto a frame axis when it is inside tolerance.

    The axial extent is carried over unchanged: rotating an axis by at most the
    angular tolerance shortens the projected span by a factor of cos(tolerance),
    which is 0.4 percent at 5 degrees and far inside the residual the extent is
    reported with.
    """
    snapped: list[CylinderFit] = []
    records: list[SnapRecord] = []
    rule = _angle_rule(thresholds)
    for cylinder in cylinders:
        nearest = _nearest_axis(_arr(cylinder.axis_dir), frame)
        if nearest is None:
            snapped.append(cylinder)
            continue
        axis, angle, _index = nearest
        if angle > thresholds.angular_snap_deg or angle <= _ANGLE_EPS_DEG:
            snapped.append(cylinder)
            continue
        snapped.append(replace(cylinder, axis_dir=_tuple3(_unit(axis))))
        records.append(
            SnapRecord(
                dim_name=f"{cylinder.name}_axis",
                raw=angle,
                snapped=0.0,
                deviation=-angle,
                rule=rule,
            )
        )
    return snapped, records


# ---------------------------------------------------------------------------
# radius clustering and concentric merging
# ---------------------------------------------------------------------------


def _pair_tolerance_mm(
    a: PlaneFit | CylinderFit, b: PlaneFit | CylinderFit, thresholds: Thresholds
) -> float:
    """Dimensional tolerance for a statement about two primitives.

    The larger of the two per-primitive tolerances, which is the same rule
    `report.py` uses when it calls two cylinders coaxial or equal-radius. The
    two stages must agree: a report that says "same radius" about primitives
    the frame stage refused to cluster would be reporting two different models.
    """
    return max(
        thresholds.dimensional_tolerance_mm(a.rms_mm),
        thresholds.dimensional_tolerance_mm(b.rms_mm),
    )


def _cluster_radii(
    cylinders: Sequence[CylinderFit], thresholds: Thresholds
) -> list[list[int]]:
    """Group cylinder indices whose radii agree inside tolerance.

    Complete linkage again: a group is only formed if its full radius spread
    stays inside the tolerance of its members, so five bores drifting 0.1 mm
    apart each never collapse into one 0.5 mm-wide claim. Assumes a short list.
    """
    clusters: list[list[int]] = [[i] for i in range(len(cylinders))]

    def spread(members: Sequence[int]) -> float:
        radii = [cylinders[i].radius_mm for i in members]
        return max(radii) - min(radii)

    def allowed(members: Sequence[int]) -> float:
        return max(
            thresholds.dimensional_tolerance_mm(cylinders[i].rms_mm) for i in members
        )

    while len(clusters) > 1:
        best: tuple[float, int, int] | None = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                union = clusters[i] + clusters[j]
                value = spread(union)
                if value > allowed(union):
                    continue
                if best is None or value < best[0] - 1e-12:
                    best = (value, i, j)
        if best is None:
            break
        _value, i, j = best
        clusters[i] = sorted(clusters[i] + clusters[j])
        del clusters[j]

    clusters.sort(key=lambda members: (cylinders[members[0]].radius_mm, min(members)))
    return clusters


def _weighted_mean(values: Sequence[float], weights: Sequence[int]) -> float:
    total = float(sum(max(w, 1) for w in weights))
    return float(sum(v * max(w, 1) for v, w in zip(values, weights)) / total)


def _apply_radius_clusters(
    cylinders: Sequence[CylinderFit], thresholds: Thresholds
) -> tuple[list[CylinderFit], list[SnapRecord]]:
    """Give every cylinder in a radius cluster the cluster's weighted mean radius.

    This is the "equal-radius clustering" half of the thin middle: four bores
    drilled with one tool are one dimension measured four times, and the user
    wants one number to edit. Cylinders that cluster alone are untouched.
    """
    clusters = _cluster_radii(cylinders, thresholds)
    result = list(cylinders)
    records: list[SnapRecord] = []
    label = _tolerance_label(thresholds)
    for members in clusters:
        if len(members) < 2:
            continue
        radius = _weighted_mean(
            [cylinders[i].radius_mm for i in members],
            [cylinders[i].inlier_count for i in members],
        )
        for index in members:
            original = cylinders[index]
            if abs(radius - original.radius_mm) <= _LENGTH_EPS_MM:
                continue
            result[index] = replace(result[index], radius_mm=radius)
            records.append(
                SnapRecord(
                    dim_name=f"{original.name}_radius",
                    raw=original.radius_mm,
                    snapped=radius,
                    deviation=radius - original.radius_mm,
                    rule=f"radius-cluster {label}",
                )
            )
    return result, records


def _axis_offset_mm(first: CylinderFit, second: CylinderFit) -> float:
    """Perpendicular distance between two nearly parallel cylinder axes."""
    delta = _arr(second.axis_point) - _arr(first.axis_point)
    direction = _arr(first.axis_dir)
    perpendicular = delta - float(np.dot(delta, direction)) * direction
    return float(np.linalg.norm(perpendicular))


def _merge_group(members: Sequence[CylinderFit]) -> CylinderFit:
    """Fuse concentric equal-radius cylinder patches into one cylinder.

    Assumes the members are already known to be parallel, coaxial and
    equal-radius inside tolerance. The merged axis is the inlier-weighted mean
    direction, the merged radius the inlier-weighted mean radius, and the
    merged axial extent the union of the members' extents projected onto that
    axis -- so a bore seen as two patches with a gap in the middle comes back
    as one bore spanning both, which is what the object actually has.

    The merged residual is the inlier-weighted quadrature mean, and the merged
    name is the largest member's, so the busiest patch keeps its identity.
    """
    ordered = sorted(members, key=lambda c: (-c.inlier_count, c.name))
    reference = _arr(ordered[0].axis_dir)
    weights = [max(c.inlier_count, 1) for c in ordered]

    total = np.zeros(3, dtype=np.float64)
    for cylinder, weight in zip(ordered, weights):
        direction = _arr(cylinder.axis_dir)
        if float(np.dot(direction, reference)) < 0.0:
            direction = -direction
        total += weight * direction
    axis = _unit(total)

    base = np.zeros(3, dtype=np.float64)
    for cylinder, weight in zip(ordered, weights):
        base += weight * _arr(cylinder.axis_point)
    base /= float(sum(weights))

    projections: list[float] = []
    for cylinder in ordered:
        point = _arr(cylinder.axis_point)
        direction = _arr(cylinder.axis_dir)
        for end in cylinder.extent_mm:
            projections.append(float(np.dot(point + end * direction - base, axis)))
    low, high = min(projections), max(projections)
    middle = 0.5 * (low + high)
    axis_point = base + middle * axis

    inliers = sum(c.inlier_count for c in ordered)
    weight_total = float(sum(weights))
    rms = math.sqrt(
        sum(w * c.rms_mm * c.rms_mm for c, w in zip(ordered, weights)) / weight_total
    )
    return CylinderFit(
        name=ordered[0].name,
        axis_point=_tuple3(axis_point),
        axis_dir=_tuple3(axis),
        radius_mm=_weighted_mean([c.radius_mm for c in ordered], weights),
        extent_mm=(low - middle, high - middle),
        inlier_count=int(inliers),
        rms_mm=rms,
    )


def _merge_concentric(
    cylinders: Sequence[CylinderFit], thresholds: Thresholds
) -> tuple[list[CylinderFit], list[SnapRecord]]:
    """Merge cylinders that are the same feature fitted more than once.

    Two cylinders join when their axes are parallel inside the angular
    tolerance, their axes are closer than the dimensional tolerance, and their
    radii agree inside it. Groups are transitive (a chain of patches down one
    long bore becomes one bore). Order is preserved by keeping each group at
    the position of its first member.

    Each absorbed cylinder emits one record naming how far its axis moved, so
    the merge is never invisible. Records emitted for an absorbed cylinder
    earlier in the pipeline keep its original name and are left in the log: the
    merge record names the absorbed cylinder in its rule text, so the trail
    from "cylinder_1_axis was snapped" to "cylinder_1 was absorbed into
    cylinder_0" stays readable. Rewriting those names to the survivor would
    attribute one patch's raw fitted numbers to another patch, which is worse.
    """
    count = len(cylinders)
    parent = list(range(count))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(count):
        for j in range(i + 1, count):
            first, second = cylinders[i], cylinders[j]
            angle = _undirected_angle_deg(_arr(first.axis_dir), _arr(second.axis_dir))
            if angle > thresholds.angular_snap_deg:
                continue
            tolerance = _pair_tolerance_mm(first, second, thresholds)
            if _axis_offset_mm(first, second) > tolerance:
                continue
            if abs(first.radius_mm - second.radius_mm) > tolerance:
                continue
            root_i, root_j = find(i), find(j)
            if root_i != root_j:
                parent[max(root_i, root_j)] = min(root_i, root_j)

    groups: dict[int, list[int]] = {}
    for i in range(count):
        groups.setdefault(find(i), []).append(i)

    result: list[CylinderFit] = []
    records: list[SnapRecord] = []
    label = _tolerance_label(thresholds)
    for root in sorted(groups):
        members = [cylinders[i] for i in groups[root]]
        if len(members) == 1:
            result.append(members[0])
            continue
        merged = _merge_group(members)
        result.append(merged)
        for member in members:
            if member.name == merged.name:
                continue
            offset = _axis_offset_mm(merged, member)
            records.append(
                SnapRecord(
                    dim_name=f"{merged.name}_axis_offset",
                    raw=offset,
                    snapped=0.0,
                    deviation=-offset,
                    rule=f"concentric-merge {label}, absorbed {member.name}",
                )
            )
    return result, records


# ---------------------------------------------------------------------------
# rounding onto the 0.1 mm grid
# ---------------------------------------------------------------------------


def _round_mm(value: float) -> float:
    """Round a length onto the frozen 0.1 mm grid."""
    return round(value / SNAP_ROUND_MM) * SNAP_ROUND_MM


def _round_diameters(
    cylinders: Sequence[CylinderFit], thresholds: Thresholds
) -> tuple[list[CylinderFit], list[SnapRecord]]:
    """Round each cylinder's diameter onto the 0.1 mm grid, inside tolerance.

    The diameter is rounded rather than the radius because the diameter is the
    dimension the object has and the report states: a 12.5 mm bore fits the
    grid at 6.25 mm radius, and rounding the radius instead would move it to
    6.2 and quietly turn the bore into a 12.4 mm one.

    The move is only made when it is inside the primitive's own dimensional
    tolerance, so a badly fitted cylinder keeps its untidy number.
    """
    result: list[CylinderFit] = []
    records: list[SnapRecord] = []
    label = _tolerance_label(thresholds)
    for cylinder in cylinders:
        diameter = 2.0 * cylinder.radius_mm
        target = _round_mm(diameter)
        radius = 0.5 * target
        shift = abs(radius - cylinder.radius_mm)
        tolerance = thresholds.dimensional_tolerance_mm(cylinder.rms_mm)
        if shift <= _LENGTH_EPS_MM or shift > tolerance or radius <= 0.0:
            result.append(cylinder)
            continue
        result.append(replace(cylinder, radius_mm=radius))
        records.append(
            SnapRecord(
                dim_name=f"{cylinder.name}_diameter",
                raw=diameter,
                snapped=target,
                deviation=target - diameter,
                rule=f"length-round {SNAP_ROUND_MM:g}mm within {label}",
            )
        )
    return result, records


def _opposite_pairs(
    planes: Sequence[PlaneFit], thresholds: Thresholds
) -> list[tuple[int, int]]:
    """Greedily pair opposite-facing parallel planes, in the given order.

    "Opposite" means the outward normals point away from each other, which is
    what the two faces of a slab look like. Each plane joins at most one pair.
    This mirrors `report._plane_pairs` so the gaps this stage rounds are the
    gaps the report goes on to name; assumes `planes` is already in report
    order (by frame axis, then position along it).
    """
    pairs: list[tuple[int, int]] = []
    used: set[int] = set()
    for i, first in enumerate(planes):
        if i in used:
            continue
        for j in range(i + 1, len(planes)):
            if j in used:
                continue
            angle = _angle_deg(_arr(first.normal), _arr(planes[j].normal))
            if abs(180.0 - angle) > thresholds.angular_snap_deg:
                continue
            used.add(i)
            used.add(j)
            pairs.append((i, j))
            break
    return pairs


def _round_gaps(
    planes: Sequence[PlaneFit], thresholds: Thresholds
) -> tuple[list[PlaneFit], list[SnapRecord]]:
    """Round face-to-face gaps onto the 0.1 mm grid, inside tolerance.

    Both faces move by half the correction along their own normals, so the
    object's centre stays put and neither face is privileged. The tolerance is
    the pair tolerance, and the residual used for it is the quadrature sum of
    the two faces' residuals -- the same combination the report prints with the
    gap, so a gap that was rounded is a gap whose stated uncertainty covers it.
    """
    result = list(planes)
    records: list[SnapRecord] = []
    label = _tolerance_label(thresholds)
    for i, j in _opposite_pairs(planes, thresholds):
        first, second = result[i], result[j]
        normal_a = _arr(first.normal)
        normal_b = _arr(second.normal)
        signed = float(np.dot(_arr(second.point) - _arr(first.point), normal_a))
        gap = abs(signed)
        if gap <= _LENGTH_EPS_MM:
            continue
        target = _round_mm(gap)
        if abs(target - gap) <= _LENGTH_EPS_MM or target <= 0.0:
            continue
        combined_rms = math.sqrt(first.rms_mm**2 + second.rms_mm**2)
        if abs(target - gap) > thresholds.dimensional_tolerance_mm(combined_rms):
            continue
        # Solve for the half-step t that makes the gap exactly `target`:
        # moving a by t*n_a and b by t*n_b changes the signed gap by t*(c - 1),
        # where c is n_a dot n_b and is close to -1 for an opposing pair.
        cosine = float(np.dot(normal_a, normal_b))
        if abs(1.0 - cosine) < 1e-9:  # pragma: no cover - excluded by the pairing test
            continue
        sign = 1.0 if signed >= 0.0 else -1.0
        step = (signed - sign * target) / (1.0 - cosine)
        result[i] = replace(first, point=_tuple3(_arr(first.point) + step * normal_a))
        result[j] = replace(second, point=_tuple3(_arr(second.point) + step * normal_b))
        records.append(
            SnapRecord(
                dim_name=f"gap_{first.name}_{second.name}",
                raw=gap,
                snapped=target,
                deviation=target - gap,
                rule=f"length-round {SNAP_ROUND_MM:g}mm within {label}",
            )
        )
    return result, records


# ---------------------------------------------------------------------------
# ordering and semantic names
# ---------------------------------------------------------------------------


def _dominant_axis(direction: Vec3, axes: tuple[Vec3, Vec3, Vec3]) -> int:
    """Index of the frame axis most nearly aligned with `direction`.

    Ties break towards the lower index. Matches `report._dominant_axis`, so the
    order this stage fixes is the order the report reads back.
    """
    best = 0
    best_value = -1.0
    for index, axis in enumerate(axes):
        value = abs(float(np.dot(_arr(direction), _arr(axis))))
        if value > best_value + 1e-12:
            best = index
            best_value = value
    return best


def _sorted_planes(planes: Sequence[PlaneFit], frame: ObjectFrame) -> list[PlaneFit]:
    """Planes in report order: by frame axis, then position along it, then name."""
    axes = frame.axes()
    origin = _arr(frame.origin)

    def key(plane: PlaneFit) -> tuple[int, float, str]:
        index = _dominant_axis(plane.normal, axes)
        position = float(np.dot(_arr(plane.point) - origin, _arr(axes[index])))
        return (index, position, plane.name)

    return sorted(planes, key=key)


def _semantic_names(
    planes: Sequence[PlaneFit], frame: ObjectFrame, thresholds: Thresholds
) -> dict[str, str]:
    """Map fitted plane names to plane_top/bottom/left/right/front/back.

    A plane earns a semantic name only when it is unambiguous: its normal must
    sit inside the angular tolerance of one signed frame axis, that axis must
    be supported by fitted geometry, and no other plane may claim the same
    label. A scan with two upward faces at different heights keeps plane_0 and
    plane_1 for both, because calling one of them "the top" would be a guess.

    Returns only the renamings; planes not in the map keep their index names.
    """
    claims: dict[str, list[str]] = {}
    for plane in planes:
        nearest = _nearest_axis(_arr(plane.normal), frame)
        if nearest is None:
            continue
        axis, angle, index = nearest
        if angle > thresholds.angular_snap_deg:
            continue
        positive = float(np.dot(axis, _arr(frame.axes()[index]))) > 0.0
        label = f"plane_{_AXIS_LABELS[index][1 if positive else 0]}"
        claims.setdefault(label, []).append(plane.name)
    return {
        names[0]: label for label, names in claims.items() if len(names) == 1
    }


def _rename_records(
    records: Sequence[SnapRecord], renames: dict[str, str]
) -> list[SnapRecord]:
    """Rewrite primitive names inside snap dimension names after renaming.

    Records are emitted while the primitives still carry index names, but the
    report and the emitter tie a record to its primitive by name, so the names
    must agree in the end. Replacement is anchored so that renaming `plane_1`
    never touches a record belonging to `plane_10`.
    """
    if not renames:
        return list(records)
    pattern = re.compile(
        "(" + "|".join(re.escape(old) for old in sorted(renames, key=len, reverse=True)) + ")(?![0-9])"
    )
    return [
        replace(
            record,
            dim_name=pattern.sub(lambda m: renames[m.group(1)], record.dim_name),
        )
        for record in records
    ]


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def align_and_snap(
    planes: Sequence[PlaneFit],
    cylinders: Sequence[CylinderFit],
    *,
    thresholds: Thresholds = COARSE,
    provenance: str = "synthetic",
) -> SceneModel:
    """Align fitted primitives to their dominant frame and return a SceneModel.

    Assumes `planes` and `cylinders` come from `ransac_cgal.fit_primitives`:
    unit directions, millimetre lengths, unique ASCII names, per-primitive RMS
    residuals and inlier counts already filled in. `thresholds` is a frozen
    regime preset, or a `dataclasses.replace` of one carrying CLI overrides, in
    which case the caller echoes that fact in the report.

    The order of operations is fixed, because each step depends on the last:

      1. recover the dominant frame from the plane normal clusters
      2. snap plane normals and cylinder axes onto supported frame axes
      3. cluster radii, then merge concentric equal-radius cylinders
      4. round diameters onto the 0.1 mm grid
      5. put the planes in report order and give them semantic names
      6. round face-to-face gaps onto the 0.1 mm grid

    Every mutation in steps 2 to 4 and 6 emits one SnapRecord, and records
    emitted before step 5 have their dimension names rewritten to the semantic
    plane names, so the snap log and the primitive list always agree.

    Raises FrameError on unusable names. An empty input is not an error: it
    returns a SceneModel with an empty frame and empty lists, which the report
    renders as "no frame was fitted".
    """
    _check_names(planes, cylinders)
    frame = dominant_frame(planes, cylinders, thresholds)
    if frame is None:
        return SceneModel(
            frame=(),
            planes=list(planes),
            cylinders=list(cylinders),
            snaps=[],
            provenance=provenance,
        )

    records: list[SnapRecord] = []

    aligned_planes, plane_records = _snap_plane_normals(planes, frame, thresholds)
    records.extend(plane_records)

    aligned_cylinders, cylinder_records = _snap_cylinder_axes(
        cylinders, frame, thresholds
    )
    records.extend(cylinder_records)

    aligned_cylinders, radius_records = _apply_radius_clusters(
        aligned_cylinders, thresholds
    )
    records.extend(radius_records)

    aligned_cylinders, merge_records = _merge_concentric(aligned_cylinders, thresholds)
    records.extend(merge_records)

    aligned_cylinders, diameter_records = _round_diameters(
        aligned_cylinders, thresholds
    )
    records.extend(diameter_records)

    ordered_planes = _sorted_planes(aligned_planes, frame)
    renames = _semantic_names(ordered_planes, frame, thresholds)
    ordered_planes = [
        replace(plane, name=renames[plane.name]) if plane.name in renames else plane
        for plane in ordered_planes
    ]
    records = _rename_records(records, renames)

    ordered_planes, gap_records = _round_gaps(ordered_planes, thresholds)
    records.extend(gap_records)

    ordered_cylinders = sorted(aligned_cylinders, key=lambda c: (c.radius_mm, c.name))

    return SceneModel(
        frame=frame.as_tuple(),
        planes=ordered_planes,
        cylinders=ordered_cylinders,
        snaps=records,
        provenance=provenance,
    )
