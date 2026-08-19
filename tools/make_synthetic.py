"""Synthetic ground-truth point clouds for scan2cad (WI-9).

Three virtual parts with exactly known dimensions, sampled as oriented point
clouds and returned together with a truth dictionary:

  bracket   60 x 40 x 20 mm block, one 12.5 mm through-bore
            6 planes, 1 cylinder
  lbracket  two orthogonal 50 x 30 x 4 mm plates, two 5 mm bores
            8 planes, 2 cylinders
  bossbox   80 x 50 x 25 mm shell exterior, one 8 mm outer-diameter boss
            7 planes, 1 cylinder

What this module is for: proving the fitting, snapping, report and emitter code
paths run and are not knife-edge fragile. It is NOT a sensor model. Results
obtained from it say nothing about phone-capture accuracy (PLAN.md ground rule
7, section 7 embargo list).

PROHIBITED TODOs -- do not add these, per docs/DECISIONS.md and PLAN.md ground
rule 8. There is deliberately no simulation of: hallucinated depth between
sparse real returns; correlated low-frequency surface warp; camera pose drift
or relocalisation jumps; intrinsics or focus jitter. Modelling those would
manufacture the appearance of sensor realism that the evidence base says we
cannot validate before a real capture exists. The only degradations offered
here are honest, clearly labelled, uncorrelated ones: along-normal Gaussian
noise, a constant along-normal bias, normal sign damage, spherical dropouts,
and a one-sided coverage mask.

Geometry conventions. All lengths are millimetres. Points lie exactly on the
nominal surface before noise. Normals are the exact outward surface normals
(outward = out of the solid material, so a bore's normals point at its axis and
a boss's point away from it). The sampler never perturbs a normal's direction,
only its sign: direction estimation is io_mesh.py's job, and a synthetic
direction-error model would be one of the prohibited simulators above.

Density note. Points are allocated across faces in proportion to area, so the
smallest face sets the floor. That face is the bossbox boss top, 50.3 mm2,
which receives about 275 points at the default 80000 total. Below about 60000
total points it falls under the coarse RANSAC min_points of 200 and stops being
detectable; raise n_points rather than lowering that threshold.

Determinism. Everything is drawn from one numpy Generator seeded by
`SamplerParams.seed`, in a fixed order, so a given (model, params) pair always
produces byte-identical arrays.

Run as a script to write PLY files into out/ for manual poking:

    .venv/bin/python tools/make_synthetic.py
    .venv/bin/python tools/make_synthetic.py --model bracket --seed 1337 \
        --out out/bracket.ply
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

MODEL_NAMES: tuple[str, ...] = ("bracket", "lbracket", "bossbox")
COVERAGE_MODES: tuple[str, ...] = ("full", "top-hemisphere-only")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "out"

Vec3 = tuple[float, float, float]


# --------------------------------------------------------------------------
# small vector helpers
# --------------------------------------------------------------------------


def _unit(vec) -> np.ndarray:
    """Return `vec` as a unit-length float64 array.

    Assumes `vec` is a 3-sequence with non-zero length; a zero vector is a
    construction bug in a model builder, so it raises rather than returning
    something arbitrary.
    """
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        raise ValueError(f"cannot normalise the zero vector {vec!r}")
    return arr / norm


def _basis(normal) -> tuple[np.ndarray, np.ndarray]:
    """Return two unit vectors spanning the plane perpendicular to `normal`.

    The choice is arbitrary but deterministic: the same normal always yields
    the same pair, which is what keeps disc and cylinder sampling repeatable.
    """
    n = _unit(normal)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = _unit(np.cross(helper, n))
    v = np.cross(n, u)
    return u, v


# --------------------------------------------------------------------------
# surface patches
# --------------------------------------------------------------------------
#
# A patch is one sampleable piece of surface. Several patches may belong to the
# same truth primitive: an L-bracket side face is one plane made of two
# rectangles, and that plane is counted once in the truth dictionary.


@dataclass(frozen=True)
class _RectPatch:
    """A planar rectangle, optionally with circular holes punched out of it.

    Assumes `u_dir` and `v_dir` are unit, mutually perpendicular and both
    perpendicular to `normal`, and that holes lie wholly inside the rectangle
    (overlapping holes would make the area wrong). `origin` is the (u=0, v=0)
    corner in world coordinates; holes are given as (u_centre, v_centre,
    radius) in the patch's own 2D coordinates.
    """

    primitive: str
    origin: Vec3
    u_dir: Vec3
    v_dir: Vec3
    u_len: float
    v_len: float
    normal: Vec3
    holes: tuple[tuple[float, float, float], ...] = ()

    @property
    def area_mm2(self) -> float:
        """Rectangle area less the punched holes."""
        return self.u_len * self.v_len - sum(math.pi * r * r for _, _, r in self.holes)

    def sample(self, rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Draw `n` uniformly distributed points, rejecting any inside a hole."""
        u_out = np.empty(n, dtype=np.float64)
        v_out = np.empty(n, dtype=np.float64)
        got = 0
        while got < n:
            batch = max(int((n - got) * 1.3) + 32, 64)
            cand_u = rng.random(batch) * self.u_len
            cand_v = rng.random(batch) * self.v_len
            keep = np.ones(batch, dtype=bool)
            for hole_u, hole_v, hole_r in self.holes:
                keep &= (cand_u - hole_u) ** 2 + (cand_v - hole_v) ** 2 >= hole_r * hole_r
            cand_u = cand_u[keep]
            cand_v = cand_v[keep]
            take = min(cand_u.size, n - got)
            u_out[got : got + take] = cand_u[:take]
            v_out[got : got + take] = cand_v[:take]
            got += take
        points = (
            np.asarray(self.origin, dtype=np.float64)
            + np.asarray(self.u_dir, dtype=np.float64) * u_out[:, None]
            + np.asarray(self.v_dir, dtype=np.float64) * v_out[:, None]
        )
        normals = np.tile(np.asarray(self.normal, dtype=np.float64), (n, 1))
        return points, normals


@dataclass(frozen=True)
class _DiskPatch:
    """A planar disc or annulus, used for the top face of a boss.

    Assumes `r_inner` < `r_outer`; `r_inner` of 0 gives a full disc.
    """

    primitive: str
    centre: Vec3
    normal: Vec3
    r_outer: float
    r_inner: float = 0.0

    @property
    def area_mm2(self) -> float:
        """Annulus area."""
        return math.pi * (self.r_outer**2 - self.r_inner**2)

    def sample(self, rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Draw `n` points uniform in area (radius drawn as sqrt of uniform)."""
        u, v = _basis(self.normal)
        radius = np.sqrt(rng.uniform(self.r_inner**2, self.r_outer**2, n))
        theta = rng.uniform(0.0, 2.0 * math.pi, n)
        points = (
            np.asarray(self.centre, dtype=np.float64)
            + u * (radius * np.cos(theta))[:, None]
            + v * (radius * np.sin(theta))[:, None]
        )
        normals = np.tile(_unit(self.normal), (n, 1))
        return points, normals


@dataclass(frozen=True)
class _CylPatch:
    """The lateral surface of a cylinder, between two axial stations.

    `t_min` and `t_max` are measured along `axis_dir` from `axis_point`.
    `outward` says which way the material lies: True for a boss (normals point
    away from the axis), False for a bore (normals point at the axis).
    """

    primitive: str
    axis_point: Vec3
    axis_dir: Vec3
    radius: float
    t_min: float
    t_max: float
    outward: bool

    @property
    def area_mm2(self) -> float:
        """Lateral area of the sampled band."""
        return 2.0 * math.pi * self.radius * (self.t_max - self.t_min)

    def sample(self, rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Draw `n` points uniform in (angle, axial position)."""
        axis = _unit(self.axis_dir)
        u, v = _basis(axis)
        theta = rng.uniform(0.0, 2.0 * math.pi, n)
        t = rng.uniform(self.t_min, self.t_max, n)
        radial = u * np.cos(theta)[:, None] + v * np.sin(theta)[:, None]
        points = (
            np.asarray(self.axis_point, dtype=np.float64)
            + radial * self.radius
            + axis * t[:, None]
        )
        normals = radial if self.outward else -radial
        return points, normals


_Patch = _RectPatch | _DiskPatch | _CylPatch


# --------------------------------------------------------------------------
# model definitions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Model:
    """One virtual part: its surface patches plus its exact construction truth."""

    name: str
    patches: tuple[_Patch, ...]
    planes: tuple[dict, ...]
    cylinders: tuple[dict, ...]
    dims_mm: dict[str, float]
    bbox_mm: Vec3
    description: str


def _plane(name: str, point: Vec3, normal: Vec3) -> dict:
    """Truth record for one plane, as plain JSON-safe values."""
    return {"name": name, "point": tuple(float(c) for c in point),
            "normal": tuple(float(c) for c in _unit(normal))}


def _cylinder(
    name: str, axis_point: Vec3, axis_dir: Vec3, radius_mm: float, extent_mm: tuple[float, float]
) -> dict:
    """Truth record for one cylinder; `extent_mm` is along the axis from `axis_point`."""
    return {
        "name": name,
        "axis_point": tuple(float(c) for c in axis_point),
        "axis_dir": tuple(float(c) for c in _unit(axis_dir)),
        "radius_mm": float(radius_mm),
        "extent_mm": (float(extent_mm[0]), float(extent_mm[1])),
    }


def build_bracket() -> _Model:
    """60 x 40 x 20 mm block with a 12.5 mm bore through the height at (15, 20).

    Bore position matches tools/reference_part.py so the synthetic bracket and
    the printed morning part carry the same named dimensions.
    """
    w, d, h = 60.0, 40.0, 20.0
    bore_r = 6.25
    bx, by = 15.0, 20.0

    patches: list[_Patch] = [
        # bottom, z = 0, outward normal -Z; patch u is +X, v is +Y
        _RectPatch("plane_bottom", (0.0, 0.0, 0.0), (1, 0, 0), (0, 1, 0), w, d,
                   (0, 0, -1), ((bx, by, bore_r),)),
        _RectPatch("plane_top", (0.0, 0.0, h), (1, 0, 0), (0, 1, 0), w, d,
                   (0, 0, 1), ((bx, by, bore_r),)),
        _RectPatch("plane_left", (0.0, 0.0, 0.0), (0, 1, 0), (0, 0, 1), d, h, (-1, 0, 0)),
        _RectPatch("plane_right", (w, 0.0, 0.0), (0, 1, 0), (0, 0, 1), d, h, (1, 0, 0)),
        _RectPatch("plane_front", (0.0, 0.0, 0.0), (1, 0, 0), (0, 0, 1), w, h, (0, -1, 0)),
        _RectPatch("plane_back", (0.0, d, 0.0), (1, 0, 0), (0, 0, 1), w, h, (0, 1, 0)),
        _CylPatch("cyl_bore_1", (bx, by, 0.0), (0, 0, 1), bore_r, 0.0, h, outward=False),
    ]
    planes = (
        _plane("plane_bottom", (w / 2, d / 2, 0.0), (0, 0, -1)),
        _plane("plane_top", (w / 2, d / 2, h), (0, 0, 1)),
        _plane("plane_left", (0.0, d / 2, h / 2), (-1, 0, 0)),
        _plane("plane_right", (w, d / 2, h / 2), (1, 0, 0)),
        _plane("plane_front", (w / 2, 0.0, h / 2), (0, -1, 0)),
        _plane("plane_back", (w / 2, d, h / 2), (0, 1, 0)),
    )
    cylinders = (_cylinder("cyl_bore_1", (bx, by, 0.0), (0, 0, 1), bore_r, (0.0, h)),)
    dims = {
        "width": w,
        "depth": d,
        "height": h,
        "bore_diameter": 2 * bore_r,
        "bore_centre_from_left": bx,
        "bore_centre_from_front": by,
    }
    return _Model("bracket", tuple(patches), planes, cylinders, dims, (w, d, h),
                  "block with one through-bore")


def build_lbracket() -> _Model:
    """Two orthogonal 50 x 30 x 4 mm plates with one 5 mm bore in each.

    The base plate lies flat over x 0 to 50, y 0 to 30, z 0 to 4. The upright
    plate stands on its front edge over x 0 to 50, y 0 to 4, z 4 to 34. The two
    front faces are coplanar at y = 0 and are counted as one plane, which is
    why the truth plane count is 8 rather than 9.
    """
    length = 50.0
    plate_w = 30.0
    thick = 4.0
    top_z = thick + plate_w  # 34.0
    bore_r = 2.5
    a_x, a_y = 37.0, 20.0  # base-plate bore, axis along +Z
    b_x, b_z = 25.0, 22.0  # upright-plate bore, axis along +Y

    patches: list[_Patch] = [
        _RectPatch("plane_a_bottom", (0.0, 0.0, 0.0), (1, 0, 0), (0, 1, 0), length, plate_w,
                   (0, 0, -1), ((a_x, a_y, bore_r),)),
        # top of the base plate is exposed only beyond the upright's footprint
        _RectPatch("plane_a_top", (0.0, thick, thick), (1, 0, 0), (0, 1, 0), length,
                   plate_w - thick, (0, 0, 1), ((a_x, a_y - thick, bore_r),)),
        _RectPatch("plane_b_top", (0.0, 0.0, top_z), (1, 0, 0), (0, 1, 0), length, thick,
                   (0, 0, 1)),
        # single coplanar front face spanning both plates, pierced by the upright bore
        _RectPatch("plane_front", (0.0, 0.0, 0.0), (1, 0, 0), (0, 0, 1), length, top_z,
                   (0, -1, 0), ((b_x, b_z, bore_r),)),
        _RectPatch("plane_b_back", (0.0, thick, thick), (1, 0, 0), (0, 0, 1), length,
                   plate_w, (0, 1, 0), ((b_x, b_z - thick, bore_r),)),
        _RectPatch("plane_a_back", (0.0, plate_w, 0.0), (1, 0, 0), (0, 0, 1), length, thick,
                   (0, 1, 0)),
        # the two L-shaped end faces, each built from two rectangles
        _RectPatch("plane_left", (0.0, 0.0, 0.0), (0, 1, 0), (0, 0, 1), plate_w, thick,
                   (-1, 0, 0)),
        _RectPatch("plane_left", (0.0, 0.0, thick), (0, 1, 0), (0, 0, 1), thick, plate_w,
                   (-1, 0, 0)),
        _RectPatch("plane_right", (length, 0.0, 0.0), (0, 1, 0), (0, 0, 1), plate_w, thick,
                   (1, 0, 0)),
        _RectPatch("plane_right", (length, 0.0, thick), (0, 1, 0), (0, 0, 1), thick, plate_w,
                   (1, 0, 0)),
        _CylPatch("cyl_bore_a", (a_x, a_y, 0.0), (0, 0, 1), bore_r, 0.0, thick, outward=False),
        _CylPatch("cyl_bore_b", (b_x, 0.0, b_z), (0, 1, 0), bore_r, 0.0, thick, outward=False),
    ]
    planes = (
        _plane("plane_a_bottom", (length / 2, plate_w / 2, 0.0), (0, 0, -1)),
        _plane("plane_a_top", (length / 2, (plate_w + thick) / 2, thick), (0, 0, 1)),
        _plane("plane_b_top", (length / 2, thick / 2, top_z), (0, 0, 1)),
        _plane("plane_front", (length / 2, 0.0, top_z / 2), (0, -1, 0)),
        _plane("plane_b_back", (length / 2, thick, (thick + top_z) / 2), (0, 1, 0)),
        _plane("plane_a_back", (length / 2, plate_w, thick / 2), (0, 1, 0)),
        _plane("plane_left", (0.0, thick / 2, thick / 2), (-1, 0, 0)),
        _plane("plane_right", (length, thick / 2, thick / 2), (1, 0, 0)),
    )
    cylinders = (
        _cylinder("cyl_bore_a", (a_x, a_y, 0.0), (0, 0, 1), bore_r, (0.0, thick)),
        _cylinder("cyl_bore_b", (b_x, 0.0, b_z), (0, 1, 0), bore_r, (0.0, thick)),
    )
    dims = {
        "plate_length": length,
        "plate_width": plate_w,
        "plate_thickness": thick,
        "overall_height": top_z,
        "bore_a_diameter": 2 * bore_r,
        "bore_b_diameter": 2 * bore_r,
        "bore_a_from_left": a_x,
        "bore_a_from_back": plate_w - a_y,
        "bore_b_from_left": b_x,
        "bore_b_from_base": b_z,
    }
    return _Model("lbracket", tuple(patches), planes, cylinders, dims,
                  (length, plate_w, top_z), "two orthogonal plates with one bore each")


def build_bossbox() -> _Model:
    """80 x 50 x 25 mm shell exterior with an 8 mm outer-diameter boss on top.

    Only the exterior surface exists: there is no inner wall and therefore no
    wall-thickness dimension. The boss is 6 mm tall, centred at (55, 25), and
    contributes one cylinder plus its own top plane.
    """
    w, d, h = 80.0, 50.0, 25.0
    boss_r = 4.0
    boss_h = 6.0
    bx, by = 55.0, 25.0

    patches: list[_Patch] = [
        _RectPatch("plane_bottom", (0.0, 0.0, 0.0), (1, 0, 0), (0, 1, 0), w, d, (0, 0, -1)),
        _RectPatch("plane_top", (0.0, 0.0, h), (1, 0, 0), (0, 1, 0), w, d,
                   (0, 0, 1), ((bx, by, boss_r),)),
        _RectPatch("plane_left", (0.0, 0.0, 0.0), (0, 1, 0), (0, 0, 1), d, h, (-1, 0, 0)),
        _RectPatch("plane_right", (w, 0.0, 0.0), (0, 1, 0), (0, 0, 1), d, h, (1, 0, 0)),
        _RectPatch("plane_front", (0.0, 0.0, 0.0), (1, 0, 0), (0, 0, 1), w, h, (0, -1, 0)),
        _RectPatch("plane_back", (0.0, d, 0.0), (1, 0, 0), (0, 0, 1), w, h, (0, 1, 0)),
        _DiskPatch("plane_boss_top", (bx, by, h + boss_h), (0, 0, 1), boss_r),
        _CylPatch("cyl_boss_1", (bx, by, h), (0, 0, 1), boss_r, 0.0, boss_h, outward=True),
    ]
    planes = (
        _plane("plane_bottom", (w / 2, d / 2, 0.0), (0, 0, -1)),
        _plane("plane_top", (w / 2, d / 2, h), (0, 0, 1)),
        _plane("plane_left", (0.0, d / 2, h / 2), (-1, 0, 0)),
        _plane("plane_right", (w, d / 2, h / 2), (1, 0, 0)),
        _plane("plane_front", (w / 2, 0.0, h / 2), (0, -1, 0)),
        _plane("plane_back", (w / 2, d, h / 2), (0, 1, 0)),
        _plane("plane_boss_top", (bx, by, h + boss_h), (0, 0, 1)),
    )
    cylinders = (_cylinder("cyl_boss_1", (bx, by, h), (0, 0, 1), boss_r, (0.0, boss_h)),)
    dims = {
        "width": w,
        "depth": d,
        "height": h,
        "boss_diameter": 2 * boss_r,
        "boss_height": boss_h,
        "boss_centre_from_left": bx,
        "boss_centre_from_front": by,
    }
    return _Model("bossbox", tuple(patches), planes, cylinders, dims, (w, d, h + boss_h),
                  "box shell exterior with one boss")


_BUILDERS = {
    "bracket": build_bracket,
    "lbracket": build_lbracket,
    "bossbox": build_bossbox,
}


def build_model(name: str) -> _Model:
    """Return the noiseless model definition called `name`.

    Raises ValueError listing the valid names rather than KeyError, so a CLI
    typo produces a plain-language message.
    """
    try:
        return _BUILDERS[name]()
    except KeyError:
        raise ValueError(
            f"unknown model {name!r}; available models are: " + ", ".join(MODEL_NAMES)
        ) from None


# --------------------------------------------------------------------------
# sampler
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SamplerParams:
    """Every knob the sampler has. Defaults give a clean, fully covered cloud.

    n_points        target sample count before dropouts and coverage masking
    sigma_mm        standard deviation of iid Gaussian displacement along the
                    true surface normal
    bias_mm         constant displacement along the true surface normal, applied
                    to every point (an honest systematic offset, nothing more)
    flip_frac       fraction of normals whose sign is reversed, chosen at random
    unoriented      if True, every normal gets an independent random sign; this
                    overrides flip_frac and models a cloud whose normals were
                    never consistently oriented
    hole_count      number of spherical dropouts punched into the cloud
    hole_radius_mm  radius of each dropout
    coverage        "full", or "top-hemisphere-only" to drop every point whose
                    outward normal points into the lower half space, which is
                    what a scan taken only from above would miss
    seed            seeds the single Generator that drives everything
    """

    n_points: int = 80_000
    sigma_mm: float = 0.0
    bias_mm: float = 0.0
    flip_frac: float = 0.0
    unoriented: bool = False
    hole_count: int = 0
    hole_radius_mm: float = 3.0
    coverage: str = "full"
    seed: int = 1337

    def __post_init__(self) -> None:
        if self.n_points < 1:
            raise ValueError(f"n_points must be at least 1, got {self.n_points}")
        if self.sigma_mm < 0.0:
            raise ValueError(f"sigma_mm must not be negative, got {self.sigma_mm}")
        if not 0.0 <= self.flip_frac <= 1.0:
            raise ValueError(f"flip_frac must be between 0 and 1, got {self.flip_frac}")
        if self.hole_count < 0:
            raise ValueError(f"hole_count must not be negative, got {self.hole_count}")
        if self.hole_radius_mm < 0.0:
            raise ValueError(
                f"hole_radius_mm must not be negative, got {self.hole_radius_mm}"
            )
        if self.coverage not in COVERAGE_MODES:
            raise ValueError(
                f"unknown coverage {self.coverage!r}; available modes are: "
                + ", ".join(COVERAGE_MODES)
            )


def _allocate(areas: list[float], n: int) -> list[int]:
    """Split `n` samples across patches in proportion to area.

    Uses largest-remainder rounding so the counts sum to exactly `n` and are a
    pure function of the areas, with no random draw involved.
    """
    total = sum(areas)
    if total <= 0.0:
        raise ValueError("model has no surface area")
    exact = [area / total * n for area in areas]
    counts = [int(math.floor(value)) for value in exact]
    remainder = n - sum(counts)
    order = sorted(range(len(areas)), key=lambda i: (-(exact[i] - counts[i]), i))
    for i in order[:remainder]:
        counts[i] += 1
    return counts


def sample_model(
    model: _Model, params: SamplerParams
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample `model` under `params`, returning (points, normals, primitive_index).

    `primitive_index` gives, per point, the index of the patch it came from, so
    callers can tell which truth primitive each point belongs to. Stage order is
    fixed and matters: sample the exact surface, apply the coverage mask, punch
    dropouts, displace along the true normal (bias then Gaussian), then damage
    the normal signs, then shuffle. Noise therefore uses the true normal
    direction even when the reported sign is later flipped.
    """
    rng = np.random.default_rng(params.seed)
    areas = [patch.area_mm2 for patch in model.patches]
    counts = _allocate(areas, params.n_points)

    point_blocks: list[np.ndarray] = []
    normal_blocks: list[np.ndarray] = []
    index_blocks: list[np.ndarray] = []
    for index, (patch, count) in enumerate(zip(model.patches, counts)):
        if count == 0:
            continue
        pts, nrm = patch.sample(rng, count)
        point_blocks.append(pts)
        normal_blocks.append(nrm)
        index_blocks.append(np.full(count, index, dtype=np.int32))

    points = np.concatenate(point_blocks, axis=0)
    normals = np.concatenate(normal_blocks, axis=0)
    patch_index = np.concatenate(index_blocks, axis=0)

    if params.coverage == "top-hemisphere-only":
        keep = normals[:, 2] >= 0.0
        points, normals, patch_index = points[keep], normals[keep], patch_index[keep]

    if params.hole_count > 0 and points.shape[0] > 0:
        centre_ids = rng.choice(points.shape[0], size=params.hole_count, replace=False)
        centres = points[centre_ids]
        keep = np.ones(points.shape[0], dtype=bool)
        for centre in centres:
            keep &= np.sum((points - centre) ** 2, axis=1) > params.hole_radius_mm**2
        points, normals, patch_index = points[keep], normals[keep], patch_index[keep]

    if points.shape[0] == 0:
        raise ValueError(
            "the sampler produced no points; the dropouts or the coverage mask "
            "removed the whole cloud"
        )

    offset = np.full(points.shape[0], params.bias_mm, dtype=np.float64)
    if params.sigma_mm > 0.0:
        offset = offset + rng.normal(0.0, params.sigma_mm, points.shape[0])
    if params.bias_mm != 0.0 or params.sigma_mm > 0.0:
        points = points + normals * offset[:, None]

    if params.unoriented:
        signs = rng.choice(np.array([-1.0, 1.0]), size=points.shape[0])
        normals = normals * signs[:, None]
    elif params.flip_frac > 0.0:
        flip = rng.random(points.shape[0]) < params.flip_frac
        normals = np.where(flip[:, None], -normals, normals)

    order = rng.permutation(points.shape[0])
    return points[order], normals[order], patch_index[order]


def make_model(
    name: str, params: SamplerParams | None = None
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Build, sample and describe one synthetic model.

    Returns (points, normals, truth). `points` and `normals` are float64 arrays
    of shape (N, 3); N equals `params.n_points` unless dropouts or the coverage
    mask removed points. `truth` is JSON-safe and documented in `_truth_dict`.
    """
    params = params or SamplerParams()
    model = build_model(name)
    points, normals, patch_index = sample_model(model, params)
    return points, normals, _truth_dict(model, params, points, patch_index)


def _truth_dict(
    model: _Model, params: SamplerParams, points: np.ndarray, patch_index: np.ndarray
) -> dict:
    """Assemble the ground-truth dictionary for one sampled model.

    Keys:
      model, description, units, provenance   identification
      dims_mm         the named dimensions a report or skeleton must reproduce
      bbox_mm         nominal bounding box of the noiseless part
      n_planes,
      n_cylinders     construction truth: what a perfect fitter would find on a
                      fully covered cloud
      planes,
      cylinders       per-primitive truth records (point, normal, radius, ...)
      n_points        points actually returned
      planes_sampled,
      cylinders_sampled
                      how many of those primitives still carry at least one
                      point after the coverage mask and the dropouts; under
                      degraded settings these are lower than the construction
                      counts, and that is a finding to report, not a bug
      sampler         the exact parameters used, so a cloud can be regenerated
    """
    present = {model.patches[i].primitive for i in np.unique(patch_index)}
    return {
        "model": model.name,
        "description": model.description,
        "units": "mm",
        "provenance": "synthetic",
        "dims_mm": dict(model.dims_mm),
        "bbox_mm": tuple(float(c) for c in model.bbox_mm),
        "n_planes": len(model.planes),
        "n_cylinders": len(model.cylinders),
        "planes": [dict(p) for p in model.planes],
        "cylinders": [dict(c) for c in model.cylinders],
        "n_points": int(points.shape[0]),
        "planes_sampled": sum(1 for p in model.planes if p["name"] in present),
        "cylinders_sampled": sum(1 for c in model.cylinders if c["name"] in present),
        "sampler": asdict(params),
    }


# --------------------------------------------------------------------------
# PLY output (script mode only; the library path returns arrays)
# --------------------------------------------------------------------------


def write_ply(path: Path, points: np.ndarray, normals: np.ndarray) -> None:
    """Write an oriented point cloud as a binary little-endian PLY.

    Assumes `points` and `normals` are (N, 3) and the same length. Coordinates
    are stored as float32, which quantises a 60 mm coordinate at about 4e-6 mm
    -- four orders below the tightest tolerance in thresholds.py, so nothing
    downstream can notice, but worth knowing before chasing a last-digit
    difference between an in-memory array and a reloaded file.
    """
    if points.shape != normals.shape or points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(
            f"points and normals must both be (N, 3); got {points.shape} and {normals.shape}"
        )
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment generated by scan2cad tools/make_synthetic.py\n"
        f"element vertex {points.shape[0]}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property float nx\n"
        "property float ny\n"
        "property float nz\n"
        "end_header\n"
    )
    payload = np.empty((points.shape[0], 6), dtype="<f4")
    payload[:, 0:3] = points
    payload[:, 3:6] = normals
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(header.encode("ascii"))
        handle.write(payload.tobytes())


# --------------------------------------------------------------------------
# script entry point
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Command line for manual poking: write one or all models to out/ as PLY."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate synthetic ground-truth point clouds for scan2cad. "
            "Plumbing verification only; these clouds say nothing about "
            "phone-capture accuracy."
        )
    )
    parser.add_argument("--model", default="all", choices=(*MODEL_NAMES, "all"),
                        help="model to generate (default: all three)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output PLY path; requires a single --model")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUT_DIR,
                        help="directory for <model>.ply when --out is not given")
    parser.add_argument("--points", type=int, default=SamplerParams.n_points,
                        help="target sample count")
    parser.add_argument("--sigma-mm", type=float, default=SamplerParams.sigma_mm,
                        help="along-normal Gaussian noise, standard deviation in mm")
    parser.add_argument("--bias-mm", type=float, default=SamplerParams.bias_mm,
                        help="constant along-normal offset in mm")
    parser.add_argument("--flip-frac", type=float, default=SamplerParams.flip_frac,
                        help="fraction of normals to reverse")
    parser.add_argument("--unoriented", action="store_true",
                        help="give every normal an independent random sign")
    parser.add_argument("--holes", type=int, default=SamplerParams.hole_count,
                        help="number of spherical dropouts")
    parser.add_argument("--hole-radius-mm", type=float,
                        default=SamplerParams.hole_radius_mm,
                        help="radius of each dropout in mm")
    parser.add_argument("--coverage", default=SamplerParams.coverage,
                        choices=COVERAGE_MODES,
                        help="surface coverage of the virtual capture")
    parser.add_argument("--seed", type=int, default=SamplerParams.seed,
                        help="random seed; the same seed always gives the same cloud")
    parser.add_argument("--no-truth", action="store_true",
                        help="do not write the <model>.truth.json file")
    return parser


def _report(truth: dict, ply_path: Path, truth_path: Path | None) -> None:
    """Print one fact per line, plain ASCII, per the screen-reader rule."""
    print(f"Model {truth['model']}: {truth['description']}.")
    print(f"Wrote {truth['n_points']} points to {ply_path}.")
    if truth_path is not None:
        print(f"Wrote ground truth to {truth_path}.")
    print(f"Planes by construction: {truth['n_planes']}.")
    print(f"Cylinders by construction: {truth['n_cylinders']}.")
    if truth["planes_sampled"] != truth["n_planes"]:
        print(f"Planes still carrying points: {truth['planes_sampled']}.")
    if truth["cylinders_sampled"] != truth["n_cylinders"]:
        print(f"Cylinders still carrying points: {truth['cylinders_sampled']}.")
    for dim_name, value in truth["dims_mm"].items():
        print(f"{dim_name} = {value:.1f} mm, exact by construction.")
    sampler = truth["sampler"]
    print(
        "Sampler: seed {seed}, sigma {sigma_mm} mm, bias {bias_mm} mm, "
        "flip fraction {flip_frac}, unoriented {unoriented}, holes {hole_count} "
        "of radius {hole_radius_mm} mm, coverage {coverage}.".format(**sampler)
    )
    print("Synthetic data: plumbing verification only, not evidence about capture accuracy.")


def main(argv: list[str] | None = None) -> int:
    """Write the selected models to disk and describe them on stdout."""
    args = _build_parser().parse_args(argv)
    names = MODEL_NAMES if args.model == "all" else (args.model,)
    if args.out is not None and len(names) != 1:
        print(
            "scan2cad: --out names a single file, so it needs a single --model.",
            file=sys.stderr,
        )
        return 2

    params = SamplerParams(
        n_points=args.points,
        sigma_mm=args.sigma_mm,
        bias_mm=args.bias_mm,
        flip_frac=args.flip_frac,
        unoriented=args.unoriented,
        hole_count=args.holes,
        hole_radius_mm=args.hole_radius_mm,
        coverage=args.coverage,
        seed=args.seed,
    )

    for position, name in enumerate(names):
        if position:
            print("")
        points, normals, truth = make_model(name, params)
        ply_path = args.out if args.out is not None else args.outdir / f"{name}.ply"
        write_ply(ply_path, points, normals)
        truth_path = None
        if not args.no_truth:
            truth_path = ply_path.with_suffix(".truth.json")
            truth_path.write_text(json.dumps(truth, indent=2) + "\n", encoding="ascii")
        _report(truth, ply_path, truth_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
