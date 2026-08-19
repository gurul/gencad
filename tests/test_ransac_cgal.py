"""Unit and acceptance tests for the CGAL RANSAC wrapper (WI-3).

Three layers:

1. Convention tests. The (u, v) plane basis is duplicated in `ransac_cgal.py`
   and `emit_build123d.py` on purpose (the fitter must not depend on the
   emitter), so one test asserts the two implementations agree. If that test
   ever fails, every plane extent in every emitted script is silently wrong.
2. Refit tests. `refit_plane` and `refit_cylinder` are exercised directly on
   hand-built inlier sets with exactly known answers. These need no CGAL.
3. Live acceptance. The WI-3 acceptance case from PLAN.md -- a 12.5 mm
   cylinder at 0.1 mm noise recovered to better than 1 percent -- plus a
   six-face block with a through-bore, both run through the real wheel with
   the frozen coarse thresholds.

All geometry here is in millimetres, matching the rest of the project.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scan2cad.primitives import CylinderFit, PlaneFit
from scan2cad.ransac_cgal import (
    DEFAULT_PROBABILITY,
    FitError,
    RansacResult,
    fit_primitives,
    plane_uv_basis,
    refit_cylinder,
    refit_plane,
)
from scan2cad.thresholds import COARSE

SEED = 1337

# The acceptance case named in PLAN.md WI-3.
ACCEPT_RADIUS_MM = 12.5
ACCEPT_SIGMA_MM = 0.1
ACCEPT_HEIGHT_MM = 30.0
# Enough points that the sample spacing stays well inside the frozen coarse
# cluster_epsilon of 2.0 mm. Point count is a sampling choice, not a threshold.
ACCEPT_POINT_COUNT = 4000

# Block used for the multi-primitive test.
BLOCK = (60.0, 40.0, 20.0)
BORE_RADIUS_MM = 6.25
BORE_CENTRE_XY = (15.0, 20.0)


# --------------------------------------------------------------------------
# synthetic samplers (local to this test; WI-9 owns the real generator)
# --------------------------------------------------------------------------


def _cylinder_cloud(
    radius: float,
    height: float,
    count: int,
    sigma: float,
    rng: np.random.Generator,
    centre_xy: tuple[float, float] = (0.0, 0.0),
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a z-axis cylinder wall, with outward normals and radial noise."""
    theta = rng.uniform(0.0, 2.0 * math.pi, count)
    normals = np.column_stack([np.cos(theta), np.sin(theta), np.zeros(count)])
    points = np.column_stack(
        [
            centre_xy[0] + radius * np.cos(theta),
            centre_xy[1] + radius * np.sin(theta),
            rng.uniform(0.0, height, count),
        ]
    )
    if sigma > 0.0:
        points = points + normals * rng.normal(0.0, sigma, (count, 1))
    return points, normals


def _rect_face(
    origin: np.ndarray,
    edge_u: np.ndarray,
    edge_v: np.ndarray,
    normal: np.ndarray,
    count: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a rectangle spanned by `edge_u` and `edge_v` from `origin`."""
    a = rng.uniform(0.0, 1.0, (count, 1))
    b = rng.uniform(0.0, 1.0, (count, 1))
    points = origin + a * edge_u + b * edge_v
    normals = np.tile(normal, (count, 1))
    return points, normals


def _block_with_bore(
    rng: np.random.Generator, per_mm2: float = 4.0
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a BLOCK-sized box with one through-bore along z.

    Points on the top and bottom faces that fall inside the bore are removed,
    so the bore is a real hole rather than a cylinder drawn over solid faces.
    Normals point out of the material, which means they point *inwards* on the
    bore wall -- the same sign convention a scan of the real part would have.
    """
    width, depth, height = BLOCK
    origin = np.zeros(3)
    ex = np.array([width, 0.0, 0.0])
    ey = np.array([0.0, depth, 0.0])
    ez = np.array([0.0, 0.0, height])

    faces = [
        (origin + ez, ex, ey, np.array([0.0, 0.0, 1.0])),  # top
        (origin, ex, ey, np.array([0.0, 0.0, -1.0])),  # bottom
        (origin, ey, ez, np.array([-1.0, 0.0, 0.0])),  # left
        (origin + ex, ey, ez, np.array([1.0, 0.0, 0.0])),  # right
        (origin, ex, ez, np.array([0.0, -1.0, 0.0])),  # front
        (origin + ey, ex, ez, np.array([0.0, 1.0, 0.0])),  # back
    ]
    all_points: list[np.ndarray] = []
    all_normals: list[np.ndarray] = []
    for face_origin, edge_u, edge_v, normal in faces:
        area = float(np.linalg.norm(edge_u) * np.linalg.norm(edge_v))
        points, normals = _rect_face(
            face_origin, edge_u, edge_v, normal, int(area * per_mm2), rng
        )
        if abs(normal[2]) > 0.5:
            radial = np.hypot(
                points[:, 0] - BORE_CENTRE_XY[0], points[:, 1] - BORE_CENTRE_XY[1]
            )
            keep = radial > BORE_RADIUS_MM + 0.5
            points, normals = points[keep], normals[keep]
        all_points.append(points)
        all_normals.append(normals)

    wall_area = 2.0 * math.pi * BORE_RADIUS_MM * height
    bore_points, bore_normals = _cylinder_cloud(
        BORE_RADIUS_MM,
        height,
        int(wall_area * per_mm2),
        0.0,
        rng,
        centre_xy=BORE_CENTRE_XY,
    )
    all_points.append(bore_points)
    all_normals.append(-bore_normals)  # material is outside the bore

    return np.vstack(all_points), np.vstack(all_normals)


# --------------------------------------------------------------------------
# 1. shared conventions
# --------------------------------------------------------------------------

_NORMALS = [
    (0.0, 0.0, 1.0),
    (0.0, 0.0, -1.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.6, 0.0, 0.8),
    (0.5773502691896258, 0.5773502691896258, 0.5773502691896258),
]


@pytest.mark.parametrize("normal", _NORMALS)
def test_plane_basis_matches_the_emitter(normal: tuple[float, float, float]) -> None:
    """The fitter and the emitter must agree or every extent is meaningless."""
    from scan2cad.emit_build123d import plane_uv_basis as emitter_basis

    mine_u, mine_v = plane_uv_basis(normal)
    theirs_u, theirs_v = emitter_basis(normal)
    assert mine_u == pytest.approx(theirs_u, abs=1e-12)
    assert mine_v == pytest.approx(theirs_v, abs=1e-12)


@pytest.mark.parametrize("normal", _NORMALS)
def test_plane_basis_is_orthonormal_and_right_handed(
    normal: tuple[float, float, float]
) -> None:
    u, v = (np.asarray(x) for x in plane_uv_basis(normal))
    n = np.asarray(normal)
    assert float(np.linalg.norm(u)) == pytest.approx(1.0)
    assert float(np.linalg.norm(v)) == pytest.approx(1.0)
    assert float(u @ v) == pytest.approx(0.0, abs=1e-12)
    assert float(u @ n) == pytest.approx(0.0, abs=1e-12)
    assert np.cross(u, v) == pytest.approx(n, abs=1e-12)


# --------------------------------------------------------------------------
# 2. refits, exact answers, no CGAL needed
# --------------------------------------------------------------------------


def _plane_seed() -> PlaneFit:
    """A deliberately wrong seed: the refit must not depend on it."""
    return PlaneFit(
        name="shape_0",
        point=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        inlier_count=0,
        rms_mm=float("nan"),
        extent=(float("nan"),) * 4,
    )


def _cylinder_seed() -> CylinderFit:
    return CylinderFit(
        name="shape_0",
        axis_point=(0.0, 0.0, 0.0),
        axis_dir=(0.0, 0.0, 1.0),
        radius_mm=1.0,
        extent_mm=(float("nan"), float("nan")),
        inlier_count=0,
        rms_mm=float("nan"),
    )


def test_refit_plane_recovers_an_exact_plane() -> None:
    """Noise-free plane at z = 5 spanning 40 by 30 mm, normals facing up."""
    rng = np.random.default_rng(SEED)
    points, normals = _rect_face(
        np.array([-20.0, -15.0, 5.0]),
        np.array([40.0, 0.0, 0.0]),
        np.array([0.0, 30.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        4000,
        rng,
    )
    fit = refit_plane(_plane_seed(), points, normals)

    assert fit.normal == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)
    assert fit.point[2] == pytest.approx(5.0, abs=1e-9)
    assert fit.rms_mm == pytest.approx(0.0, abs=1e-9)
    assert fit.inlier_count == points.shape[0]
    # The extent is a bounding box in plane coords, so its side lengths are the
    # rectangle's sides regardless of which of u and v got which.
    u_min, u_max, v_min, v_max = fit.extent
    sides = sorted([u_max - u_min, v_max - v_min])
    assert sides[0] == pytest.approx(30.0, abs=0.3)
    assert sides[1] == pytest.approx(40.0, abs=0.3)


def test_refit_plane_takes_its_normal_sign_from_the_inliers() -> None:
    """The seed says +z; the inlier normals say -z, and the inliers win."""
    rng = np.random.default_rng(SEED)
    points, _ = _rect_face(
        np.array([-20.0, -15.0, 5.0]),
        np.array([40.0, 0.0, 0.0]),
        np.array([0.0, 30.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        1000,
        rng,
    )
    normals = np.tile([0.0, 0.0, -1.0], (points.shape[0], 1))
    fit = refit_plane(_plane_seed(), points, normals)
    assert fit.normal == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)


def test_refit_plane_rms_matches_the_injected_noise() -> None:
    rng = np.random.default_rng(SEED)
    points, normals = _rect_face(
        np.array([-20.0, -15.0, 5.0]),
        np.array([40.0, 0.0, 0.0]),
        np.array([0.0, 30.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        20000,
        rng,
    )
    sigma = 0.2
    points = points + normals * rng.normal(0.0, sigma, (points.shape[0], 1))
    fit = refit_plane(_plane_seed(), points, normals)
    assert fit.rms_mm == pytest.approx(sigma, rel=0.05)
    assert fit.point[2] == pytest.approx(5.0, abs=0.01)


def test_refit_cylinder_recovers_an_exact_cylinder() -> None:
    rng = np.random.default_rng(SEED)
    points, normals = _cylinder_cloud(
        ACCEPT_RADIUS_MM, ACCEPT_HEIGHT_MM, 3000, 0.0, rng, centre_xy=(3.0, -7.0)
    )
    fit = refit_cylinder(_cylinder_seed(), points, normals)

    assert fit.radius_mm == pytest.approx(ACCEPT_RADIUS_MM, abs=1e-6)
    assert fit.axis_dir == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)
    assert fit.axis_point[0] == pytest.approx(3.0, abs=1e-6)
    assert fit.axis_point[1] == pytest.approx(-7.0, abs=1e-6)
    assert fit.rms_mm == pytest.approx(0.0, abs=1e-6)
    # The span straddles zero because axis_point sits at the inlier centroid.
    t_min, t_max = fit.extent_mm
    assert t_min < 0.0 < t_max
    assert t_max - t_min == pytest.approx(ACCEPT_HEIGHT_MM, abs=0.2)


def test_refit_cylinder_recovers_a_tilted_axis() -> None:
    """Seeded with the z axis; the truth is tilted 20 degrees away from it."""
    rng = np.random.default_rng(SEED)
    points, normals = _cylinder_cloud(8.0, 40.0, 4000, 0.0, rng)
    angle = math.radians(20.0)
    rotation = np.array(
        [
            [math.cos(angle), 0.0, math.sin(angle)],
            [0.0, 1.0, 0.0],
            [-math.sin(angle), 0.0, math.cos(angle)],
        ]
    )
    points = points @ rotation.T
    normals = normals @ rotation.T
    fit = refit_cylinder(_cylinder_seed(), points, normals)

    assert fit.radius_mm == pytest.approx(8.0, abs=1e-6)
    expected_axis = rotation @ np.array([0.0, 0.0, 1.0])
    assert abs(float(np.asarray(fit.axis_dir) @ expected_axis)) == pytest.approx(
        1.0, abs=1e-6
    )


def test_refit_cylinder_works_on_a_half_arc() -> None:
    """Top-hemisphere coverage is a real degradation case; the fit must hold.

    An algebraic circle fit is biased on partial arcs, which is why the refit
    finishes with geometric Gauss-Newton rather than stopping at the seed.
    """
    rng = np.random.default_rng(SEED)
    count = 3000
    theta = rng.uniform(0.0, math.pi, count)
    normals = np.column_stack([np.cos(theta), np.sin(theta), np.zeros(count)])
    points = np.column_stack(
        [10.0 * np.cos(theta), 10.0 * np.sin(theta), rng.uniform(0.0, 25.0, count)]
    )
    fit = refit_cylinder(_cylinder_seed(), points, normals)
    assert fit.radius_mm == pytest.approx(10.0, abs=1e-5)


def test_refit_cylinder_axis_sign_is_canonical() -> None:
    """Flipping every input normal must not flip the reported axis."""
    rng = np.random.default_rng(SEED)
    points, normals = _cylinder_cloud(5.0, 20.0, 1500, 0.0, rng)
    forward = refit_cylinder(_cylinder_seed(), points, normals)
    flipped = refit_cylinder(_cylinder_seed(), points[::-1], -normals[::-1])
    assert flipped.axis_dir == pytest.approx(forward.axis_dir, abs=1e-9)


def test_refit_cylinder_rms_matches_the_injected_noise() -> None:
    rng = np.random.default_rng(SEED)
    points, normals = _cylinder_cloud(
        ACCEPT_RADIUS_MM, ACCEPT_HEIGHT_MM, 20000, ACCEPT_SIGMA_MM, rng
    )
    fit = refit_cylinder(_cylinder_seed(), points, normals)
    assert fit.rms_mm == pytest.approx(ACCEPT_SIGMA_MM, rel=0.05)
    assert fit.radius_mm == pytest.approx(ACCEPT_RADIUS_MM, abs=0.01)


# --------------------------------------------------------------------------
# 3. input checking
# --------------------------------------------------------------------------


def test_fit_rejects_wrong_shaped_points() -> None:
    with pytest.raises(FitError, match=r"\(N, 3\)"):
        fit_primitives(np.zeros((10, 2)), np.zeros((10, 2)))


def test_fit_rejects_mismatched_normals() -> None:
    with pytest.raises(FitError, match="does not match"):
        fit_primitives(np.zeros((10, 3)), np.zeros((9, 3)))


def test_fit_rejects_non_unit_normals() -> None:
    points = np.zeros((10, 3))
    with pytest.raises(FitError, match="unit length"):
        fit_primitives(points, np.zeros((10, 3)))


def test_fit_error_messages_are_ascii() -> None:
    """CLI prints these straight to a screen reader (SYNTHESIS.md ruling 7)."""
    with pytest.raises(FitError) as excinfo:
        fit_primitives(np.zeros((2, 3)), np.zeros((2, 3)))
    assert str(excinfo.value).isascii()


# --------------------------------------------------------------------------
# 4. live acceptance against the installed CGAL wheel
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_cylinder() -> RansacResult:
    """PLAN.md WI-3 acceptance case, run with the frozen coarse thresholds."""
    pytest.importorskip("CGAL.CGAL_Shape_detection")
    rng = np.random.default_rng(SEED)
    points, normals = _cylinder_cloud(
        ACCEPT_RADIUS_MM, ACCEPT_HEIGHT_MM, ACCEPT_POINT_COUNT, ACCEPT_SIGMA_MM, rng
    )
    return fit_primitives(points, normals, thresholds=COARSE)


def test_acceptance_radius_within_one_percent(acceptance_cylinder: RansacResult) -> None:
    """The WI-3 acceptance bar: 12.5 mm cylinder, 0.1 mm noise, under 1 percent."""
    assert len(acceptance_cylinder.cylinders) == 1
    fit = acceptance_cylinder.cylinders[0]
    error_pct = abs(fit.radius_mm - ACCEPT_RADIUS_MM) / ACCEPT_RADIUS_MM * 100.0
    assert error_pct < 1.0, f"radius {fit.radius_mm} mm, error {error_pct} percent"


def test_acceptance_returns_typed_dataclasses_only(
    acceptance_cylinder: RansacResult,
) -> None:
    assert isinstance(acceptance_cylinder, RansacResult)
    assert all(isinstance(p, PlaneFit) for p in acceptance_cylinder.planes)
    assert all(isinstance(c, CylinderFit) for c in acceptance_cylinder.cylinders)


def test_acceptance_fills_every_field(acceptance_cylinder: RansacResult) -> None:
    """No NaN may survive: params.py leaves rms and extents unset on purpose."""
    fit = acceptance_cylinder.cylinders[0]
    assert math.isfinite(fit.rms_mm)
    assert fit.rms_mm == pytest.approx(ACCEPT_SIGMA_MM, rel=0.2)
    assert all(math.isfinite(v) for v in fit.extent_mm)
    assert fit.extent_mm[1] - fit.extent_mm[0] == pytest.approx(
        ACCEPT_HEIGHT_MM, abs=0.5
    )
    assert fit.inlier_count >= COARSE.ransac_min_points
    assert fit.name == "cylinder_0"


def test_acceptance_params_echo_is_ascii_one_fact_per_line(
    acceptance_cylinder: RansacResult,
) -> None:
    echo = acceptance_cylinder.params_echo
    assert echo.isascii()
    lines = echo.splitlines()
    assert len(lines) == 7
    assert all(line.endswith(".") for line in lines)
    assert "epsilon: 0.5 mm" in echo
    assert f"probability: {DEFAULT_PROBABILITY}" in echo


@pytest.fixture(scope="module")
def block_result() -> RansacResult:
    """A 60 by 40 by 20 mm block with a 12.5 mm through-bore, noise free."""
    pytest.importorskip("CGAL.CGAL_Shape_detection")
    rng = np.random.default_rng(SEED)
    points, normals = _block_with_bore(rng)
    return fit_primitives(points, normals, thresholds=COARSE)


def test_block_finds_six_planes_and_one_cylinder(block_result: RansacResult) -> None:
    assert len(block_result.planes) == 6
    assert len(block_result.cylinders) == 1
    assert block_result.primitive_count == 7
    assert block_result.dropped == []


def test_block_names_are_dense_and_ordered(block_result: RansacResult) -> None:
    assert [p.name for p in block_result.planes] == [f"plane_{i}" for i in range(6)]
    assert [c.name for c in block_result.cylinders] == ["cylinder_0"]


def test_block_plane_offsets_match_the_construction(block_result: RansacResult) -> None:
    """Each face must come back at its true signed offset from the origin."""
    width, depth, height = BLOCK
    expected = {
        (0.0, 0.0, 1.0): height,
        (0.0, 0.0, -1.0): 0.0,
        (1.0, 0.0, 0.0): width,
        (-1.0, 0.0, 0.0): 0.0,
        (0.0, 1.0, 0.0): depth,
        (0.0, -1.0, 0.0): 0.0,
    }
    seen: dict[tuple[float, float, float], float] = {}
    for plane in block_result.planes:
        normal = np.asarray(plane.normal)
        key = tuple(float(round(c)) for c in normal)
        assert key in expected, f"unexpected plane normal {plane.normal}"
        assert normal == pytest.approx(np.asarray(key), abs=1e-6)
        seen[key] = float(np.asarray(plane.point) @ np.asarray(key))
    assert set(seen) == set(expected)
    for key, offset in expected.items():
        assert seen[key] == pytest.approx(offset, abs=1e-6)
        assert math.isfinite(offset)


def test_block_plane_extents_match_the_face_sizes(block_result: RansacResult) -> None:
    width, depth, height = BLOCK
    expected_sides = {
        (0.0, 0.0, 1.0): sorted([width, depth]),
        (0.0, 0.0, -1.0): sorted([width, depth]),
        (1.0, 0.0, 0.0): sorted([depth, height]),
        (-1.0, 0.0, 0.0): sorted([depth, height]),
        (0.0, 1.0, 0.0): sorted([width, height]),
        (0.0, -1.0, 0.0): sorted([width, height]),
    }
    for plane in block_result.planes:
        key = tuple(float(round(c)) for c in plane.normal)
        u_min, u_max, v_min, v_max = plane.extent
        sides = sorted([u_max - u_min, v_max - v_min])
        assert sides == pytest.approx(expected_sides[key], abs=0.5), plane.name


def test_block_bore_radius_and_position(block_result: RansacResult) -> None:
    bore = block_result.cylinders[0]
    assert bore.radius_mm == pytest.approx(BORE_RADIUS_MM, abs=0.02)
    assert bore.axis_dir == pytest.approx((0.0, 0.0, 1.0), abs=1e-4)
    assert bore.axis_point[0] == pytest.approx(BORE_CENTRE_XY[0], abs=0.02)
    assert bore.axis_point[1] == pytest.approx(BORE_CENTRE_XY[1], abs=0.02)
    assert bore.extent_mm[1] - bore.extent_mm[0] == pytest.approx(BLOCK[2], abs=0.5)


def test_block_rms_is_small_and_finite(block_result: RansacResult) -> None:
    for fit in [*block_result.planes, *block_result.cylinders]:
        assert math.isfinite(fit.rms_mm)
        assert fit.rms_mm < 0.05, f"{fit.name} rms {fit.rms_mm}"


def test_block_point_accounting(block_result: RansacResult) -> None:
    assigned = sum(
        fit.inlier_count for fit in [*block_result.planes, *block_result.cylinders]
    )
    assert assigned == block_result.assigned_point_count
    assert 0 < block_result.assigned_point_count <= block_result.point_count


def test_fitting_is_reproducible_on_the_same_cloud() -> None:
    """The refit, not CGAL, is what makes the e2e gate reproducible."""
    pytest.importorskip("CGAL.CGAL_Shape_detection")
    rng = np.random.default_rng(SEED)
    points, normals = _cylinder_cloud(
        ACCEPT_RADIUS_MM, ACCEPT_HEIGHT_MM, ACCEPT_POINT_COUNT, 0.0, rng
    )
    first = fit_primitives(points, normals, thresholds=COARSE)
    second = fit_primitives(points, normals, thresholds=COARSE)
    assert first.cylinders == second.cylinders
    assert first.planes == second.planes


def test_planes_can_be_switched_off() -> None:
    """Cylinder-only detection is used by the parser's live fixtures too."""
    pytest.importorskip("CGAL.CGAL_Shape_detection")
    rng = np.random.default_rng(SEED)
    points, normals = _block_with_bore(rng)
    result = fit_primitives(
        points, normals, thresholds=COARSE, detect_planes=False, detect_cylinders=True
    )
    assert result.planes == []
    assert "Shapes fitted: cylinders." in result.params_echo
