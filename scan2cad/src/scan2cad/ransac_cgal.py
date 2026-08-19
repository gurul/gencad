"""CGAL Efficient RANSAC wrapper, restricted to planes and cylinders (WI-3).

This module is the only place in scan2cad that talks to CGAL. It takes the
millimetre point cloud and unit normals produced by `io_mesh.py`, runs Efficient
RANSAC once, and returns frozen `PlaneFit` and `CylinderFit` dataclasses with
every field filled in. Nothing raw -- no CGAL handles, no info strings, no index
arrays -- escapes this module.

Only planes and cylinders are requested (PLAN.md ground rule 5: thin middle
only). Spheres, cones and tori are never enabled; if a future caller enables
them anyway, `params.py` reports them as unsupported and they are skipped with
a recorded reason rather than crashing the run.

Why the fitted parameters are recomputed here
---------------------------------------------
CGAL reports minimal-sample fits, not least-squares refits (docs/STACK_NOTES.md,
WI-1 addendum). A 600-point plane at z = 5 mm with 0.05 mm noise came back at
4.937 mm -- an error far larger than a least-squares fit of the same points
would give. So the parsed parameters are used only as a seed and a sanity check:
this module recomputes every plane and every cylinder from its inlier set in
numpy, and the returned numbers, residuals and extents all come from that refit.

What is and is not reproducible
------------------------------
Say this exactly, because an overstated claim here would be a claim about the
one assertion the CI gate rests on. CGAL's Efficient RANSAC draws from a
generator this project cannot seed. Its seed fits wobble run to run, and so
does its inlier partition: on the noiseless synthetic L-bracket, repeated
identical calls were measured returning 8 planes and 2 cylinders, 7 and 3, and
6 and 5 (WI-10 diagnosis, 2026-08-19). Nothing in this module makes CGAL
deterministic and nothing claims to.

What this module does instead is remove the difference between those partitions
before anything downstream sees them. A least-squares refit of a fixed inlier
set is exactly reproducible, and the consolidation pass below converts the
partitions that differ into the same answer -- because every one of those
differences was a shape the points did not support. After it, 60 repeated fits
of each of the three synthetic models, read through the PLY and the normal
estimator exactly as the gate reads them, returned the construction counts
every time, and the whole measurement was then repeated: 360 fits, 360
matches. `scripts/gate_repeat.py` is that measurement, `out/gate_repeat.txt` is
its output, and `tests/test_ransac_cgal.py` reruns a short version of it.
That is evidence about three synthetic parts, not a guarantee, and the report's
caveats tell the user in plain words that the last digits of a fit can move
between runs.

Units and conventions
---------------------
All lengths are millimetres, matching `io_mesh.load_cloud` output.

Plane normals are oriented to agree with the mean of their inlier normals, so a
closed scan gets outward-facing plane normals. Cylinder axis directions have no
meaningful sign, so they are canonicalised (see `_canonical_axis`) purely to
make repeated runs return identical numbers.

`PlaneFit.extent` is measured in the shared (u, v) plane basis defined by
`plane_uv_basis` below, which is the same convention `emit_build123d.py`
documents. The basis is duplicated rather than imported so that the fitter does
not depend on the emitter; `tests/test_ransac_cgal.py` asserts the two agree.

`CylinderFit.extent_mm` is the (min, max) span of the inlier projections onto
the axis, measured relative to `axis_point`, and `axis_point` is placed at the
projection of the inlier centroid onto the axis, so the span straddles zero.

Consolidation: shapes CGAL reports that are not findings
--------------------------------------------------------
Efficient RANSAC scores a hypothesis by inlier count, not by how much of the
surface it explains, so on a boxy part it sometimes returns shapes that are not
features of the object at all. Every case below was measured on the noiseless
synthetic parts (WI-10 diagnosis, 2026-08-19) and each is removed here by a
consolidation pass whose only inputs are the frozen RANSAC parameters and the
shapes' own residuals:

  1. A flat face comes back as a cylinder. Two shapes of this kind were
     measured. One is enormous -- 69,334 mm and 44,135 mm radius on a 60 mm
     part, in 2 runs out of 6 -- and bends away from its own tangent plane by
     about 0.003 mm across the face it covers, 150 times below the RANSAC
     epsilon of 0.5 mm: the points cannot tell the two hypotheses apart, so
     calling it a cylinder is not a reading of the data. `_observed_sagitta_mm`
     measures that bend over the arc the inliers actually cover, and any
     cylinder that bends less than epsilon is refitted as a plane.

     The other is small and simply wrong: the L-bracket's 50 by 4 mm top strip
     came back as a cylinder of radius 1.0 mm lying in the strip, whose own
     inliers sat 0.57 mm from it on average -- further than the 0.5 mm epsilon
     that admitted them. So the plane hypothesis is refitted from the same
     inliers and compared, and the plane wins any tie: a shape is not called
     curved when a flat reading of the same points fits them at least as well.
     Both hypotheses see the same noise, so this stays correct on a noisy cloud
     and cannot quietly flatten a real bore, whose full wrap no plane can
     follow.

  2. A sliver shape appears along a sharp edge -- radius 0.736 mm, 356 points,
     spanning the full 40 mm depth. `io_mesh` estimates normals over a
     neighbourhood a few tenths of a millimetre wide, so points within that
     distance of an edge get normals blurred between the two faces, and RANSAC
     fits the blur as a fillet that the part does not have. Every one of those
     points lies within epsilon of a face already accepted, so the shape
     explains no surface that is not already explained; it is dropped, with a
     reason recorded in `dropped`.

  3. One flat face comes back as two shapes. RANSAC has no global view, and on
     the synthetic L-bracket it splits a single face into two strips in about
     one run in three, which would report nine faces on an eight-faced part.
     Plane shapes that face the same way, that lie within epsilon of each
     other, and whose footprints touch within the cluster epsilon, are merged
     and refitted as one face. See `_same_plane` for why the coplanarity test
     compares the two fitted surfaces rather than every point against the other
     surface.

No rule introduces a tunable number: they compare against `ransac_epsilon_mm`
and `ransac_cluster_epsilon_mm`, both frozen in `thresholds.py`, or against the
residual of the competing hypothesis on the same points. Rule 1 is skipped when
the caller asked for cylinders without planes, since there is then no plane
hypothesis to prefer.

These rules were written after watching the fitter fail, which is the honest
order to write them in; what SYNTHESIS.md ruling 6 forbids is moving a frozen
number to make a run pass, and no threshold has been touched since the freeze.
Every removal is disclosed in `RansacResult.notes` or `RansacResult.dropped`
and reaches the user's report.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from .params import (
    CYLINDER_NAME_PREFIX,
    PLANE_NAME_PREFIX,
    ShapeParseError,
    UnsupportedShapeError,
    parse_shape,
)
from .primitives import CylinderFit, PlaneFit, Vec3
from .thresholds import COARSE, Thresholds

# CGAL's stopping probability: the chance of missing a shape larger than
# min_points. Lower is slower and more thorough. 0.01 is the binding's own
# default and is not a frozen threshold, so it stays a plain argument here
# rather than moving into thresholds.py.
DEFAULT_PROBABILITY = 0.01

# Value the CGAL shape map holds for a point that was not assigned to any
# shape. Verified against the installed wheel on 2026-08-19.
UNASSIGNED = -1

# Smallest inlier set a refit can use at all. Below these the least-squares
# problem is underdetermined and the primitive is dropped with a reason.
MIN_PLANE_INLIERS = 3
MIN_CYLINDER_INLIERS = 5

# Gauss-Newton settings for the cylinder refit. The residual is a distance in
# millimetres, so the convergence test is an absolute millimetre step.
_CYL_MAX_ITERATIONS = 30
_CYL_STEP_TOL_MM = 1e-9


@dataclass(frozen=True)
class RansacResult:
    """Everything one Efficient RANSAC run produced, in typed form.

    Assumes the caller treats the lists as read-only. `planes` and `cylinders`
    are ordered by CGAL's detection order, which is largest shape first, and
    are renamed to plane_0, plane_1, cylinder_0 ... after dropped shapes have
    been removed, so the names are always dense.

    `dropped` holds one plain ASCII sentence per shape that CGAL found and this
    module discarded, `notes` one sentence per shape it kept but changed its
    mind about (a flat cylinder refitted as a plane), and `params_echo` is a
    newline-separated block of one fact per line naming the parameters the run
    actually used. All three exist so the report can be honest about what was
    thrown away, what was reinterpreted, and under what settings, per the
    no-silent-behaviour rule (PLAN.md ground rule 6).
    """

    planes: list[PlaneFit]
    cylinders: list[CylinderFit]
    point_count: int
    assigned_point_count: int
    dropped: list[str]
    params_echo: str
    notes: list[str] = field(default_factory=list)
    # Points that ended up inside a returned primitive. This is at most
    # `assigned_point_count`, and is smaller whenever a shape was dropped by the
    # consolidation rules. The gap between the two is how many points CGAL
    # claimed for a shape that this module would not report.
    fitted_point_count: int = 0

    @property
    def primitive_count(self) -> int:
        """Number of primitives that survived the drop rules."""
        return len(self.planes) + len(self.cylinders)


class FitError(RuntimeError):
    """Fitting could not be run at all.

    Raised for bad input (mismatched or too-small arrays, non-unit normals) and
    for a missing CGAL install. Not raised when a run simply finds nothing:
    an empty result is a legitimate answer about a bad scan, and the CLI turns
    it into a plain-language exit message.
    """


# --------------------------------------------------------------------------
# shared plane basis
# --------------------------------------------------------------------------

_WORLD_AXES = np.eye(3, dtype=np.float64)


def plane_uv_basis(normal: Vec3) -> tuple[Vec3, Vec3]:
    """Return the (u, v) in-plane basis used to express `PlaneFit.extent`.

    Plane coordinates only mean something if the stage that measures them and
    the stage that rebuilds geometry from them pick the same axes. That shared
    convention is:

      helper = the world axis least aligned with the normal
      u      = normalize(helper x normal)
      v      = normal x u

    so (u, v, normal) is right-handed, and the basis is a pure function of the
    normal with ties broken by axis order. Assumes `normal` is unit length.
    `emit_build123d.plane_uv_basis` documents and implements the same rule.
    """
    vec = np.asarray(normal, dtype=np.float64)
    helper = _WORLD_AXES[int(np.argmin(np.abs(vec)))]
    u = np.cross(helper, vec)
    u /= np.linalg.norm(u)
    v = np.cross(vec, u)
    return (float(u[0]), float(u[1]), float(u[2])), (float(v[0]), float(v[1]), float(v[2]))


# --------------------------------------------------------------------------
# input checking
# --------------------------------------------------------------------------


def _check_input(points: np.ndarray, normals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (points, normals) as float64 (N, 3) arrays, validated.

    Assumes the caller got these from `io_mesh.load_cloud`, which already
    guarantees the shape and unit length; the checks are here so that a
    hand-built array in a test or a future source backend fails at the door
    with a sentence naming the problem instead of deep inside CGAL.
    """
    pts = np.asarray(points, dtype=np.float64)
    nrm = np.asarray(normals, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise FitError(f"points must be an (N, 3) array, got shape {pts.shape}")
    if nrm.shape != pts.shape:
        raise FitError(
            f"normals shape {nrm.shape} does not match points shape {pts.shape}"
        )
    if pts.shape[0] < MIN_PLANE_INLIERS:
        raise FitError(
            f"need at least {MIN_PLANE_INLIERS} points to fit anything, got {pts.shape[0]}"
        )
    if not np.all(np.isfinite(pts)) or not np.all(np.isfinite(nrm)):
        raise FitError("points and normals must all be finite")
    lengths = np.linalg.norm(nrm, axis=1)
    if np.max(np.abs(lengths - 1.0)) > 1e-6:
        raise FitError(
            "normals must be unit length; run io_mesh.estimate_and_orient_normals first"
        )
    return pts, nrm


# --------------------------------------------------------------------------
# CGAL call
# --------------------------------------------------------------------------


def _detect(
    points: np.ndarray,
    normals: np.ndarray,
    thresholds: Thresholds,
    probability: float,
    detect_planes: bool,
    detect_cylinders: bool,
) -> tuple[list[str], np.ndarray]:
    """Run Efficient RANSAC and return (info strings, per-point shape index).

    Assumes `points` and `normals` are validated float64 (N, 3) arrays in
    millimetres. The returned index array holds `UNASSIGNED` for points that
    joined no shape, and otherwise the position of the point's shape in the
    info-string list.

    CGAL is imported inside this function so that every other function in the
    module, and most of the test suite, works on a machine without the wheel.
    """
    try:
        from CGAL.CGAL_Kernel import Point_3, Vector_3
        from CGAL.CGAL_Point_set_3 import Point_set_3
        from CGAL.CGAL_Shape_detection import efficient_RANSAC
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise FitError(
            "CGAL is not importable; scan2cad needs the cgal wheel in its venv"
        ) from exc

    point_set = Point_set_3()
    point_set.add_normal_map()
    for point, normal in zip(points, normals):
        point_set.insert(
            Point_3(float(point[0]), float(point[1]), float(point[2])),
            Vector_3(float(normal[0]), float(normal[1]), float(normal[2])),
        )
    shape_map = point_set.add_int_map("shape")

    infos = list(
        efficient_RANSAC(
            point_set,
            shape_map,
            min_points=int(thresholds.ransac_min_points),
            epsilon=float(thresholds.ransac_epsilon_mm),
            cluster_epsilon=float(thresholds.ransac_cluster_epsilon_mm),
            normal_threshold=float(thresholds.ransac_normal_threshold),
            probability=float(probability),
            planes=bool(detect_planes),
            cylinders=bool(detect_cylinders),
            cones=False,
            spheres=False,
            tori=False,
        )
    )
    assignment = np.fromiter(
        (shape_map.get(i) for i in range(points.shape[0])), dtype=np.int64, count=points.shape[0]
    )
    return infos, assignment


# --------------------------------------------------------------------------
# refitting
# --------------------------------------------------------------------------


def refit_plane(
    seed: PlaneFit, inlier_points: np.ndarray, inlier_normals: np.ndarray
) -> PlaneFit:
    """Least-squares refit of `seed` to its inliers, with residual and extent.

    Assumes at least MIN_PLANE_INLIERS inliers. The plane passes through the
    inlier centroid and its normal is the eigenvector of the smallest
    eigenvalue of the inlier covariance -- the total-least-squares plane.

    The normal's sign is taken from the mean inlier normal, so on a closed scan
    the plane faces outward. When the inlier normals cancel out (an unoriented
    cloud), the sign falls back to CGAL's, which is arbitrary but stable.

    `rms_mm` is the root-mean-square point-to-plane distance. `extent` is the
    axis-aligned bounding box of the inliers in the `plane_uv_basis` frame,
    measured relative to the returned `point`.
    """
    centroid = inlier_points.mean(axis=0)
    centered = inlier_points - centroid
    # eigh on the 3x3 covariance rather than an SVD of the full (N, 3) matrix:
    # same answer, and it does not build an N-sized factorisation for 80k rows.
    _values, vectors = np.linalg.eigh(centered.T @ centered)
    normal = vectors[:, 0]

    mean_normal = inlier_normals.mean(axis=0)
    if float(np.linalg.norm(mean_normal)) > 1e-6:
        reference = mean_normal
    else:
        reference = np.asarray(seed.normal, dtype=np.float64)
    if float(np.dot(normal, reference)) < 0.0:
        normal = -normal
    normal = normal / float(np.linalg.norm(normal))

    residuals = centered @ normal
    rms_mm = float(np.sqrt(np.mean(residuals * residuals)))

    point = tuple(float(c) for c in centroid)
    u, v = plane_uv_basis((float(normal[0]), float(normal[1]), float(normal[2])))
    u_coords = centered @ np.asarray(u, dtype=np.float64)
    v_coords = centered @ np.asarray(v, dtype=np.float64)
    extent = (
        float(u_coords.min()),
        float(u_coords.max()),
        float(v_coords.min()),
        float(v_coords.max()),
    )

    return replace(
        seed,
        point=point,  # type: ignore[arg-type]
        normal=(float(normal[0]), float(normal[1]), float(normal[2])),
        inlier_count=int(inlier_points.shape[0]),
        rms_mm=rms_mm,
        extent=extent,
    )


def _canonical_axis(axis: np.ndarray) -> np.ndarray:
    """Return `axis` with a deterministic sign.

    A cylinder axis has no intrinsic direction, so CGAL's sign is arbitrary and
    would otherwise leak run-to-run noise into the report and the emitted
    script. The rule: the component of largest magnitude is made positive, ties
    broken by axis order. Assumes `axis` is a non-zero 3-vector.
    """
    dominant = int(np.argmax(np.abs(axis)))
    return -axis if axis[dominant] < 0.0 else axis


def _perpendicular_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two unit vectors spanning the plane perpendicular to `axis`."""
    helper = _WORLD_AXES[int(np.argmin(np.abs(axis)))]
    u = np.cross(helper, axis)
    u /= np.linalg.norm(u)
    return u, np.cross(axis, u)


def _seed_axis(inlier_normals: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Estimate a cylinder axis from its inlier normals.

    On a cylinder every surface normal is perpendicular to the axis, so the
    axis is the least-represented direction in the normal covariance. Assumes
    the inliers cover enough of the circumference for that direction to be
    well determined; when they do not (all normals nearly parallel, which is a
    near-planar patch mislabelled as a cylinder) the eigenvalue gap vanishes
    and `fallback`, CGAL's own axis, is used instead.
    """
    values, vectors = np.linalg.eigh(inlier_normals.T @ inlier_normals)
    # values are ascending; a genuine cylinder has one small and two large.
    if values[1] <= 0.0 or values[0] / values[1] > 0.5:
        return fallback / np.linalg.norm(fallback)
    axis = vectors[:, 0]
    return axis / float(np.linalg.norm(axis))


def _kasa_circle(coords: np.ndarray) -> tuple[np.ndarray, float]:
    """Algebraic circle fit of 2D `coords`, returning (centre, radius).

    Assumes at least three non-collinear points. This is Kasa's linear fit; it
    is biased on short arcs, so it is used only as the starting point for the
    geometric Gauss-Newton refinement below, never as the reported answer.
    """
    design = np.column_stack([2.0 * coords, np.ones(coords.shape[0])])
    rhs = np.sum(coords * coords, axis=1)
    solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    centre = solution[:2]
    radius_squared = solution[2] + float(centre @ centre)
    if not np.isfinite(radius_squared) or radius_squared <= 0.0:
        raise ValueError("algebraic circle fit produced a non-positive radius")
    return centre, float(np.sqrt(radius_squared))


def refit_cylinder(
    seed: CylinderFit, inlier_points: np.ndarray, inlier_normals: np.ndarray
) -> CylinderFit:
    """Least-squares refit of `seed` to its inliers, with residual and extent.

    Assumes at least MIN_CYLINDER_INLIERS inliers. Minimises the sum of squared
    geometric residuals -- distance from the point to the cylinder surface --
    over five parameters: two for the axis direction, two for the axis position
    in the perpendicular plane, and the radius. The axial position of the axis
    point is not a parameter because sliding along the axis leaves an infinite
    cylinder unchanged; it is fixed afterwards at the inlier centroid.

    Gauss-Newton is used with an analytic Jacobian, seeded from the inlier
    normals and an algebraic circle fit. It converges in a handful of
    iterations on real inlier sets; if a step ever fails to solve, the last
    good estimate is returned rather than raising, because a slightly worse
    cylinder is still a usable draft and the RMS reported will show it.

    Raises ValueError if the seed itself is degenerate (collinear inliers,
    non-positive radius), which the caller turns into a dropped-shape reason.
    """
    axis = _seed_axis(inlier_normals, np.asarray(seed.axis_dir, dtype=np.float64))
    centroid = inlier_points.mean(axis=0)
    u, v = _perpendicular_basis(axis)
    local = np.column_stack([(inlier_points - centroid) @ u, (inlier_points - centroid) @ v])
    centre2d, radius = _kasa_circle(local)
    centre = centroid + centre2d[0] * u + centre2d[1] * v

    for _ in range(_CYL_MAX_ITERATIONS):
        u, v = _perpendicular_basis(axis)
        offset = inlier_points - centre
        along = offset @ axis
        perpendicular = offset - np.outer(along, axis)
        distance = np.linalg.norm(perpendicular, axis=1)
        if np.any(distance < 1e-12):
            # A point exactly on the axis makes the residual non-differentiable.
            break
        direction = perpendicular / distance[:, None]
        residual = distance - radius

        e_u = direction @ u
        e_v = direction @ v
        jacobian = np.column_stack(
            [
                -e_u,  # move the axis point along u
                -e_v,  # move the axis point along v
                -along * e_u,  # tilt the axis towards u
                -along * e_v,  # tilt the axis towards v
                -np.ones(distance.shape[0]),  # change the radius
            ]
        )
        try:
            step, *_ = np.linalg.lstsq(jacobian, -residual, rcond=None)
        except np.linalg.LinAlgError:  # pragma: no cover - defensive
            break
        if not np.all(np.isfinite(step)):  # pragma: no cover - defensive
            break

        centre = centre + step[0] * u + step[1] * v
        axis = axis + step[2] * u + step[3] * v
        axis = axis / float(np.linalg.norm(axis))
        radius = radius + float(step[4])
        if radius <= 0.0:
            raise ValueError("cylinder refit collapsed to a non-positive radius")
        if float(np.max(np.abs(step))) < _CYL_STEP_TOL_MM:
            break

    axis = _canonical_axis(axis)
    offset = inlier_points - centre
    along = offset @ axis
    # Slide the axis point to the inlier centroid so the axial span straddles
    # zero and the reported point sits inside the observed patch.
    axis_point = centre + float(along.mean()) * axis
    along = (inlier_points - axis_point) @ axis
    distance = np.linalg.norm((inlier_points - axis_point) - np.outer(along, axis), axis=1)
    residual = distance - radius
    rms_mm = float(np.sqrt(np.mean(residual * residual)))

    return replace(
        seed,
        axis_point=(float(axis_point[0]), float(axis_point[1]), float(axis_point[2])),
        axis_dir=(float(axis[0]), float(axis[1]), float(axis[2])),
        radius_mm=float(radius),
        extent_mm=(float(along.min()), float(along.max())),
        inlier_count=int(inlier_points.shape[0]),
        rms_mm=rms_mm,
    )


# --------------------------------------------------------------------------
# consolidation: shapes CGAL reports that are not features of the object
# --------------------------------------------------------------------------


def _observed_sagitta_mm(fit: CylinderFit, inlier_points: np.ndarray) -> float:
    """Return how far the fitted cylinder bends away from its tangent plane.

    Assumes `inlier_points` are the cylinder's own inliers. The bend is measured
    over the arc the inliers actually cover, because that is all the evidence
    there is: a 5 degree sliver of a 60 mm cylinder is as flat as a plane, and a
    full wrap of a 6 mm bore is unmistakably round.

    The arc span is the circle minus the widest empty angular gap between
    consecutive inliers, so a patch that wraps the whole circumference gives a
    span of about 2 pi and a patch on one side gives its true opening angle. The
    sagitta of an arc of span `theta` on radius `R` is `R * (1 - cos(theta/2))`,
    capped at half a turn, beyond which the surface curves away in both
    directions and no plane can follow it.
    """
    axis = np.asarray(fit.axis_dir, dtype=np.float64)
    u, v = _perpendicular_basis(axis)
    offset = inlier_points - np.asarray(fit.axis_point, dtype=np.float64)
    angles = np.sort(np.arctan2(offset @ v, offset @ u))
    if angles.size < 2:
        return 0.0
    gaps = np.diff(angles)
    wrap = (angles[0] + 2.0 * np.pi) - angles[-1]
    largest_gap = float(max(float(gaps.max()), float(wrap)))
    span = min(2.0 * np.pi - largest_gap, np.pi)
    return float(fit.radius_mm * (1.0 - np.cos(0.5 * span)))


def _surface_distance_mm(
    primitive: PlaneFit | CylinderFit, points: np.ndarray, margin_mm: float
) -> np.ndarray:
    """Distance from each of `points` to `primitive`, or infinity when off it.

    Assumes `points` is an (N, 3) float64 array. A point that falls outside the
    primitive's observed footprint, grown by `margin_mm`, is reported as
    infinitely far away: the footprint is what the scan saw, and treating a
    fitted face as an unbounded plane would let it swallow a genuine feature
    that happens to be coplanar with it somewhere else on the part.
    """
    if isinstance(primitive, PlaneFit):
        origin = np.asarray(primitive.point, dtype=np.float64)
        normal = np.asarray(primitive.normal, dtype=np.float64)
        offset = points - origin
        distance = np.abs(offset @ normal)
        u, v = plane_uv_basis(primitive.normal)
        u_coord = offset @ np.asarray(u, dtype=np.float64)
        v_coord = offset @ np.asarray(v, dtype=np.float64)
        u_min, u_max, v_min, v_max = primitive.extent
        inside = (
            (u_coord >= u_min - margin_mm)
            & (u_coord <= u_max + margin_mm)
            & (v_coord >= v_min - margin_mm)
            & (v_coord <= v_max + margin_mm)
        )
    else:
        axis = np.asarray(primitive.axis_dir, dtype=np.float64)
        offset = points - np.asarray(primitive.axis_point, dtype=np.float64)
        along = offset @ axis
        radial = np.linalg.norm(offset - np.outer(along, axis), axis=1)
        distance = np.abs(radial - primitive.radius_mm)
        low, high = primitive.extent_mm
        inside = (along >= low - margin_mm) & (along <= high + margin_mm)

    return np.where(inside, distance, np.inf)


def _is_already_explained(
    inlier_points: np.ndarray,
    accepted: list[PlaneFit | CylinderFit],
    thresholds: Thresholds,
) -> bool:
    """True when every one of `inlier_points` already lies on an accepted surface.

    Assumes `accepted` holds the primitives kept so far, largest first, already
    refitted. A shape all of whose points sit within the RANSAC epsilon of
    surfaces the fit has already committed to describes nothing new: at the
    resolution the fitter itself works at, those points are that surface. The
    footprint margin is the RANSAC cluster epsilon, the same distance CGAL uses
    to decide whether two inliers belong to one connected region.

    The test is deliberately all-or-nothing. A shape with even one point that no
    accepted surface reaches is evidence of geometry that is not yet described,
    and is kept.
    """
    if not accepted:
        return False
    remaining = inlier_points
    for primitive in accepted:
        distance = _surface_distance_mm(
            primitive, remaining, thresholds.ransac_cluster_epsilon_mm
        )
        remaining = remaining[distance > thresholds.ransac_epsilon_mm]
        if remaining.shape[0] == 0:
            return True
    return False


def _same_plane(
    first: PlaneFit,
    second: PlaneFit,
    second_points: np.ndarray,
    thresholds: Thresholds,
) -> bool:
    """True when two plane shapes are one surface reported twice.

    Assumes `second_points` holds the second plane's own inliers. Three conditions must all
    hold, and each is read off the frozen RANSAC parameters rather than off a
    new tolerance of this module's invention:

      same side   the two outward normals agree to within the frozen
                  `ransac_normal_threshold`, the same bound the fitter uses to
                  decide two normals point the same way. Plane normals are
                  oriented from their inlier normals, so the two faces of a
                  4 mm plate face opposite ways and can never be merged into
                  one face no matter how close together they are.

      coplanar    each plane's reference point is within `ransac_epsilon_mm` of
                  the other plane. This compares the two fitted surfaces, not
                  their point clouds, and that is deliberate. An earlier version
                  asked whether every inlier of each shape lay within epsilon of
                  the other plane, which sounds stricter and is in fact useless:
                  CGAL admits an inlier when it is within epsilon of a
                  minimal-sample seed, and a tilted seed leaves a handful of
                  points far outside epsilon of the least-squares refit -- 2.7 mm
                  out, against an epsilon of 0.5 mm, on an L-bracket end face of
                  1980 points whose RMS was 0.08 mm. One such wild point was
                  enough to stop the two halves of that face merging, and the
                  part came back with nine faces instead of eight. A
                  least-squares plane is not moved by two wild points; a
                  maximum over its points is nothing but those two points.

      adjacent    some inlier of the second plane falls inside the first plane's
                  observed footprint grown by `ransac_cluster_epsilon_mm`, the
                  distance CGAL itself uses to decide whether two inliers belong
                  to one connected region. Two coplanar faces on opposite ends
                  of a part are left alone.
    """
    epsilon = thresholds.ransac_epsilon_mm
    normal_a = np.asarray(first.normal, dtype=np.float64)
    normal_b = np.asarray(second.normal, dtype=np.float64)
    if float(np.dot(normal_a, normal_b)) < thresholds.ransac_normal_threshold:
        return False
    between = np.asarray(second.point, dtype=np.float64) - np.asarray(
        first.point, dtype=np.float64
    )
    if abs(float(np.dot(between, normal_a))) > epsilon:
        return False
    if abs(float(np.dot(between, normal_b))) > epsilon:
        return False
    touching = _surface_distance_mm(
        first, second_points, thresholds.ransac_cluster_epsilon_mm
    )
    return bool(np.any(np.isfinite(touching)))


def _merge_coplanar_planes(
    accepted: list[tuple[PlaneFit | CylinderFit, np.ndarray, np.ndarray]],
    thresholds: Thresholds,
) -> tuple[list[tuple[PlaneFit | CylinderFit, np.ndarray, np.ndarray]], list[str]]:
    """Fold plane shapes that are the same surface into one, and refit it.

    Assumes `accepted` is in detection order, largest shape first, each entry
    carrying its fit and its inlier points and normals. Efficient RANSAC has no
    global view: it will happily report one flat face as two shapes when its
    sampling happened to grow them separately, and on the synthetic L-bracket it
    splits the single 50 by 34 mm front face in about one run in three. A merged
    plane keeps the position of the earlier, larger shape and is refitted from
    the union of the inlier sets, so its residual and extent describe the whole
    face. Returns the new list and one sentence per merge for `notes`.
    """
    entries = list(accepted)
    notes: list[str] = []
    merged = True
    while merged:
        merged = False
        for i in range(len(entries)):
            first, first_points, first_normals = entries[i]
            if not isinstance(first, PlaneFit):
                continue
            for j in range(i + 1, len(entries)):
                second, second_points, second_normals = entries[j]
                if not isinstance(second, PlaneFit):
                    continue
                if not _same_plane(first, second, second_points, thresholds):
                    continue
                points = np.vstack([first_points, second_points])
                normals = np.vstack([first_normals, second_normals])
                entries[i] = (refit_plane(first, points, normals), points, normals)
                del entries[j]
                notes.append(
                    f"Two flat shapes of {first_points.shape[0]} and "
                    f"{second_points.shape[0]} points were the same plane to "
                    f"within {thresholds.ransac_epsilon_mm} mm and touched, so "
                    "they were merged into one face and refitted."
                )
                merged = True
                break
            if merged:
                break
    return entries, notes


def _plane_seed_from(fit: CylinderFit, inlier_normals: np.ndarray) -> PlaneFit:
    """Build the PlaneFit seed used to refit a not-measurably-curved cylinder.

    Assumes `inlier_normals` are that cylinder's inlier normals. Only the seed's
    `normal` is read by `refit_plane`, and only as a sign reference when the
    inlier normals cancel out, so the mean inlier normal is the natural choice.
    When even that cancels, the seed falls back to a vector perpendicular to the
    axis, which is where the surface of a very shallow cylinder points.
    """
    mean_normal = inlier_normals.mean(axis=0)
    length = float(np.linalg.norm(mean_normal))
    if length > 1e-6:
        direction = mean_normal / length
    else:
        direction = _perpendicular_basis(np.asarray(fit.axis_dir, dtype=np.float64))[0]
    return PlaneFit(
        name=fit.name,
        point=fit.axis_point,
        normal=(float(direction[0]), float(direction[1]), float(direction[2])),
        inlier_count=fit.inlier_count,
        rms_mm=fit.rms_mm,
        extent=(0.0, 0.0, 0.0, 0.0),
    )


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------


def _params_echo(
    thresholds: Thresholds,
    probability: float,
    detect_planes: bool,
    detect_cylinders: bool,
) -> str:
    """Build the ASCII block naming the parameters this run used.

    One fact per line, no symbols, per the screen-reader rule (SYNTHESIS.md
    ruling 7). Assumes the caller prints it verbatim.
    """
    kinds = [
        name
        for name, wanted in (("planes", detect_planes), ("cylinders", detect_cylinders))
        if wanted
    ]
    return "\n".join(
        [
            f"Fitting regime: {thresholds.name}.",
            f"Shapes fitted: {' and '.join(kinds) if kinds else 'none'}.",
            f"RANSAC epsilon: {thresholds.ransac_epsilon_mm} mm.",
            f"RANSAC cluster epsilon: {thresholds.ransac_cluster_epsilon_mm} mm.",
            f"RANSAC normal threshold: {thresholds.ransac_normal_threshold}.",
            f"RANSAC minimum points per shape: {thresholds.ransac_min_points}.",
            f"RANSAC stopping probability: {probability}.",
        ]
    )


def fit_primitives(
    points: np.ndarray,
    normals: np.ndarray,
    *,
    thresholds: Thresholds = COARSE,
    probability: float = DEFAULT_PROBABILITY,
    detect_planes: bool = True,
    detect_cylinders: bool = True,
) -> RansacResult:
    """Fit planes and cylinders to a millimetre point cloud with unit normals.

    Assumes `points` and `normals` are (N, 3) arrays in millimetres as returned
    by `io_mesh.load_cloud`, and that `thresholds` is a frozen preset from
    `thresholds.py` (or a `dataclasses.replace` of one carrying CLI overrides,
    in which case the caller is responsible for echoing that fact).

    Every returned primitive is recomputed from its inliers, not read off
    CGAL's minimal-sample fit, so `radius_mm`, `rms_mm` and the extents are all
    least-squares quantities. Shapes are dropped, with a recorded reason, when
    they carry fewer than `thresholds.ransac_min_points` inliers, when the
    inlier set is too small to refit, or when the refit is degenerate.

    A consolidation pass then removes the three kinds of shape Efficient RANSAC
    reports that are not features of the object: a flat face called a cylinder,
    a shape whose points already lie on surfaces that were kept, and one face
    reported as two. See the module docstring for what each rule tests and why
    it needs no threshold of its own. Every action leaves a sentence in
    `dropped` or in `notes`.

    Raises FitError for unusable input or a missing CGAL install. Finding
    nothing is not an error: the result simply has empty lists.
    """
    pts, nrm = _check_input(points, normals)
    infos, assignment = _detect(
        pts, nrm, thresholds, probability, detect_planes, detect_cylinders
    )

    planes: list[PlaneFit] = []
    cylinders: list[CylinderFit] = []
    dropped: list[str] = []
    notes: list[str] = []
    accepted: list[tuple[PlaneFit | CylinderFit, np.ndarray, np.ndarray]] = []
    min_points = int(thresholds.ransac_min_points)

    for index, info in enumerate(infos):
        try:
            seed = parse_shape(info, name=f"shape_{index}")
        except UnsupportedShapeError:
            dropped.append(
                f"Shape {index} was a kind scan2cad does not model, so it was skipped."
            )
            continue
        except ShapeParseError as exc:
            dropped.append(f"Shape {index} could not be read: {exc}")
            continue

        selected = assignment == index
        count = int(np.count_nonzero(selected))
        if count < min_points:
            dropped.append(
                f"Shape {index} had {count} points, below the minimum of {min_points}."
            )
            continue
        inlier_points = pts[selected]
        inlier_normals = nrm[selected]

        if isinstance(seed, PlaneFit):
            if count < MIN_PLANE_INLIERS:
                dropped.append(
                    f"Plane shape {index} had {count} points, too few to refit."
                )
                continue
            fit: PlaneFit | CylinderFit = refit_plane(seed, inlier_points, inlier_normals)
        else:
            if count < MIN_CYLINDER_INLIERS:
                dropped.append(
                    f"Cylinder shape {index} had {count} points, too few to refit."
                )
                continue
            try:
                fit = refit_cylinder(seed, inlier_points, inlier_normals)
            except (ValueError, np.linalg.LinAlgError) as exc:
                dropped.append(f"Cylinder shape {index} could not be refitted: {exc}")
                continue

            # Rule 1: a cylinder the points cannot tell from a plane is a plane,
            # and so is a cylinder a plane simply describes better.
            if detect_planes and count >= MIN_PLANE_INLIERS:
                alternative = refit_plane(
                    _plane_seed_from(fit, inlier_normals),
                    inlier_points,
                    inlier_normals,
                )
                sagitta = _observed_sagitta_mm(fit, inlier_points)
                if sagitta < thresholds.ransac_epsilon_mm:
                    notes.append(
                        f"Shape {index} was reported as a cylinder of radius "
                        f"{fit.radius_mm:.1f} mm, but over the patch its points "
                        f"cover it bends only {sagitta:.4f} mm away from flat, "
                        f"less than the {thresholds.ransac_epsilon_mm} mm "
                        "fitting tolerance, so it was refitted as a plane."
                    )
                    fit = alternative
                elif alternative.rms_mm <= fit.rms_mm:
                    notes.append(
                        f"Shape {index} was reported as a cylinder of radius "
                        f"{fit.radius_mm:.2f} mm, whose own points sit "
                        f"{fit.rms_mm:.4f} mm from it on average, while a plane "
                        f"through the same points sits {alternative.rms_mm:.4f} mm "
                        "from them. The flat reading is the better one, so it "
                        "was refitted as a plane."
                    )
                    fit = alternative

        # Rule 2: a shape whose every point is already on an accepted surface
        # is a second description of that surface, not a new feature.
        if _is_already_explained(
            inlier_points, [entry[0] for entry in accepted], thresholds
        ):
            dropped.append(
                f"Shape {index} had {count} points that all lie within "
                f"{thresholds.ransac_epsilon_mm} mm of surfaces already fitted, "
                "so it described nothing new and was dropped."
            )
            continue

        accepted.append((fit, inlier_points, inlier_normals))

    # Rule 3: one face reported as two shapes is still one face.
    accepted, merge_notes = _merge_coplanar_planes(accepted, thresholds)
    notes.extend(merge_notes)

    for fit, _inlier_points, _inlier_normals in accepted:
        if isinstance(fit, PlaneFit):
            planes.append(replace(fit, name=f"{PLANE_NAME_PREFIX}_{len(planes)}"))
        else:
            cylinders.append(
                replace(fit, name=f"{CYLINDER_NAME_PREFIX}_{len(cylinders)}")
            )

    return RansacResult(
        planes=planes,
        cylinders=cylinders,
        point_count=int(pts.shape[0]),
        assigned_point_count=int(np.count_nonzero(assignment != UNASSIGNED)),
        fitted_point_count=sum(fit.inlier_count for fit in [*planes, *cylinders]),
        dropped=dropped,
        params_echo=_params_echo(
            thresholds, probability, detect_planes, detect_cylinders
        ),
        notes=notes,
    )
