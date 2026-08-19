"""Frozen shared data model for scan2cad.

Every stage of the pipeline speaks in these dataclasses and nothing else.
They are frozen in two senses: `@dataclass(frozen=True)` (immutable at
runtime) and frozen by decree (PLAN.md section 3) -- no later work item may
add, rename, or retype a field, because every downstream stage was written
against this exact shape.

Units: all lengths are millimetres, all angles are degrees, all direction
vectors are unit length. Callers are responsible for supplying unit vectors;
these classes validate but do not silently renormalise, because a non-unit
normal arriving here means an upstream fitting bug that must surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]

# Tolerance used when checking that a supplied direction is unit length.
# Generous on purpose: it catches "this is a raw un-normalised vector" bugs
# without tripping on ordinary float accumulation from a least-squares fit.
_UNIT_TOL = 1e-6


def _check_unit(vec: Vec3, field: str, owner: str) -> None:
    """Raise ValueError if `vec` is not a unit vector.

    Assumes `vec` is a 3-tuple of finite floats. Called from __post_init__ of
    the fit dataclasses so that a bad direction fails at construction, next to
    the fitting code that produced it, rather than deep inside the frame stage.
    """
    norm = math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])
    if not math.isfinite(norm) or abs(norm - 1.0) > _UNIT_TOL:
        raise ValueError(
            f"{owner}.{field} must be a unit vector, got {vec} with norm {norm!r}"
        )


@dataclass(frozen=True)
class PlaneFit:
    """One fitted planar primitive.

    Assumes `normal` is unit length and `extent` is expressed in the plane's
    own 2D coordinate system as (u_min, u_max, v_min, v_max), derived from the
    inlier points only -- it is the observed footprint, not an infinite plane.
    `rms_mm` is the root-mean-square point-to-plane residual over the inliers.
    """

    name: str  # "plane_0"; renamed to plane_top/bottom/... in the frame stage
    point: Vec3
    normal: Vec3  # unit
    inlier_count: int
    rms_mm: float
    extent: tuple[float, float, float, float]  # (u_min, u_max, v_min, v_max)

    def __post_init__(self) -> None:
        _check_unit(self.normal, "normal", "PlaneFit")


@dataclass(frozen=True)
class CylinderFit:
    """One fitted cylindrical primitive.

    Assumes `axis_dir` is unit length and `extent_mm` is the (min, max) span of
    the inlier projections onto the axis, measured relative to `axis_point`.
    A cylinder here is a surface patch, never a solid: nothing downstream may
    infer from it whether the feature is a bore or a boss without also
    consulting the surrounding planes.
    """

    name: str
    axis_point: Vec3
    axis_dir: Vec3  # unit
    radius_mm: float
    extent_mm: tuple[float, float]  # inlier span along the axis
    inlier_count: int
    rms_mm: float

    def __post_init__(self) -> None:
        _check_unit(self.axis_dir, "axis_dir", "CylinderFit")


@dataclass(frozen=True)
class SnapRecord:
    """One audit entry for a value that was changed by the snapping stage.

    There is no silent snapping in this pipeline (PLAN.md ground rule 6): any
    stage that replaces a fitted number with a tidier one must emit exactly one
    of these, and the report prints all of them verbatim.

    `deviation` is `snapped - raw` in the natural unit of the dimension (mm for
    lengths, degrees for angles); `rule` names the threshold that permitted the
    change, for example "axis-align 5deg" or "radius-cluster 2xRMS".
    """

    dim_name: str
    raw: float
    snapped: float
    deviation: float
    rule: str


@dataclass(frozen=True)
class SceneModel:
    """The complete scan-derived description of one object.

    `frame` is (origin, x_axis, y_axis, z_axis) -- a point plus an orthonormal
    triad -- kept as a plain tuple so this module stays dependency-free.
    `provenance` is "synthetic" or "photogrammetry-mesh"; it is carried all the
    way into the report and the emitted script because a synthetic result may
    never be presented as evidence about real capture accuracy.

    The list fields are mutable objects inside a frozen dataclass: treat them
    as read-only. Stages build a new SceneModel rather than editing one.
    """

    frame: tuple
    planes: list[PlaneFit]
    cylinders: list[CylinderFit]
    snaps: list[SnapRecord]
    provenance: str
