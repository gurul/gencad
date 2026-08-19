"""Unit tests for the CGAL shape info string parser (WI-1).

Two layers, on purpose:

1. Frozen-string fixtures. Every string in FROZEN_* below was captured from
   the installed wheel (cgal 6.0.1.post202410241521) on 2026-08-19 and is
   pasted here verbatim, whitespace included. They pin the parser's behaviour
   and they run without CGAL installed.
2. A live fixture. It builds a 500-point synthetic cylinder and a 600-point
   synthetic plane with numpy and runs Efficient RANSAC in-process, then parses
   whatever comes back. Its job is to fail loudly the day the upstream text
   format drifts, which the frozen strings alone could never notice.

Assumes the parser is unit-agnostic; the synthetic geometry here is in
millimetres, matching the rest of the project.
"""

from __future__ import annotations

import math

import pytest

from scan2cad.params import (
    CYLINDER_NAME_PREFIX,
    PLANE_NAME_PREFIX,
    ShapeParseError,
    UnsupportedShapeError,
    parse_cylinder,
    parse_plane,
    parse_shape,
    parse_shapes,
    shape_kind,
)
from scan2cad.primitives import CylinderFit, PlaneFit

# --------------------------------------------------------------------------
# Frozen strings, captured live from the installed wheel on 2026-08-19.
# --------------------------------------------------------------------------

# 800-point cylinder, true radius 12.5 mm, axis +z, 0.1 mm noise.
FROZEN_CYLINDER = (
    "Type: cylinder center: (-0.0686792, 0.0335444, 6.52789) "
    "axis: (-0, 0, 1) radius:12.5214 #Pts: 800"
)

# 600-point plane at z = 5 mm, 0.05 mm noise. Note the double negative.
FROZEN_PLANE = "Type: plane (-0.00247502, 0.00212651, 0.999995)x - -4.97749= 0 #Pts: 593"

# Noise-free planes, used to pin the sign convention exactly.
FROZEN_PLANE_EXACT_POS = "Type: plane (0, 0, -1)x - 5= 0 #Pts: 600"
FROZEN_PLANE_EXACT_NEG = "Type: plane (0, 0, -1)x - -5= 0 #Pts: 600"
FROZEN_PLANE_TILTED = "Type: plane (0.6, -3.68087e-15, 0.8)x - -8= 0 #Pts: 600"

# Cylinder with scientific notation in the centre.
FROZEN_CYLINDER_SCI = (
    "Type: cylinder center: (1.77636e-15, -4.44089e-16, 20.992) "
    "axis: (0, 0, 1) radius:12.5605 #Pts: 494"
)

# Shape kinds scan2cad does not model. Captured the same way.
FROZEN_SPHERE = "Type: sphere center: (1, 2, 3) radius:10 #Pts: 600"
FROZEN_CONE = (
    "Type: cone apex: (-5.15143e-14, 4.52971e-14, -1.10134e-13) "
    "axis: (-7.15763e-15, 3.42212e-15, 1) angle:0.523599 #Pts: 800"
)
FROZEN_TORUS = (
    "Type: torus center(-1.75571e-15, -1.15671e-15, 1.42109e-14) "
    "axis(5.256e-17, 7.008e-17, 1) major radius = 20 minor radius = 5 #Pts: 998"
)


def _signed_offset(fit: PlaneFit) -> float:
    """Signed distance from the origin to `fit`, along its normal."""
    return sum(a * b for a, b in zip(fit.normal, fit.point))


def _angle_deg(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Unsigned angle in degrees between two unit vectors, direction-agnostic."""
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(math.acos(min(1.0, dot)))


# --------------------------------------------------------------------------
# Kind sniffing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "info,expected",
    [
        (FROZEN_PLANE, "plane"),
        (FROZEN_CYLINDER, "cylinder"),
        (FROZEN_SPHERE, "sphere"),
        (FROZEN_CONE, "cone"),
        (FROZEN_TORUS, "torus"),
    ],
)
def test_shape_kind(info: str, expected: str) -> None:
    assert shape_kind(info) == expected


def test_shape_kind_rejects_non_shape_text() -> None:
    with pytest.raises(ShapeParseError):
        shape_kind("not a shape at all")


# --------------------------------------------------------------------------
# Planes
# --------------------------------------------------------------------------


def test_plane_sign_convention_positive_offset() -> None:
    """normal . x + d = 0, so d = 5 with normal -z puts the plane at z = +5."""
    fit = parse_plane(FROZEN_PLANE_EXACT_POS, "plane_0")
    assert isinstance(fit, PlaneFit)
    assert fit.normal == pytest.approx((0.0, 0.0, -1.0))
    assert fit.point == pytest.approx((0.0, 0.0, 5.0))
    assert _signed_offset(fit) == pytest.approx(-5.0)


def test_plane_sign_convention_negative_offset() -> None:
    fit = parse_plane(FROZEN_PLANE_EXACT_NEG, "plane_0")
    assert fit.point == pytest.approx((0.0, 0.0, -5.0))


def test_plane_tilted_point_lies_on_the_plane() -> None:
    """The tilted fixture came from a plane through (0, 0, 10)."""
    fit = parse_plane(FROZEN_PLANE_TILTED, "plane_0")
    residual = sum(n * (p - t) for n, p, t in zip(fit.normal, (0.0, 0.0, 10.0), fit.point))
    assert residual == pytest.approx(0.0, abs=1e-9)


def test_plane_double_negative_offset_and_noisy_normal() -> None:
    fit = parse_plane(FROZEN_PLANE, "plane_0")
    assert fit.inlier_count == 593
    # "- -4.97749" means d = -4.97749, so the plane sits at +4.97749 mm.
    assert _signed_offset(fit) == pytest.approx(4.97749, abs=1e-4)
    assert _angle_deg(fit.normal, (0.0, 0.0, 1.0)) < 1.0


def test_plane_normal_is_renormalised_to_unit_length() -> None:
    """Six-digit printing leaves the norm off by ~1e-6; PlaneFit demands 1e-6."""
    fit = parse_plane(FROZEN_PLANE, "plane_0")
    norm = math.sqrt(sum(c * c for c in fit.normal))
    assert norm == pytest.approx(1.0, abs=1e-12)


def test_plane_unset_fields_are_nan() -> None:
    """rms_mm and extent belong to WI-3; a forgotten fill must be visible."""
    fit = parse_plane(FROZEN_PLANE, "plane_0")
    assert math.isnan(fit.rms_mm)
    assert all(math.isnan(v) for v in fit.extent)


def test_plane_name_is_passed_through() -> None:
    assert parse_plane(FROZEN_PLANE, "plane_7").name == "plane_7"


# --------------------------------------------------------------------------
# Cylinders
# --------------------------------------------------------------------------


def test_cylinder_fields() -> None:
    fit = parse_cylinder(FROZEN_CYLINDER, "cylinder_0")
    assert isinstance(fit, CylinderFit)
    assert fit.radius_mm == pytest.approx(12.5214)
    assert fit.inlier_count == 800
    assert fit.axis_point == pytest.approx((-0.0686792, 0.0335444, 6.52789))
    # "-0" must parse as a negative-zero component, not blow up.
    assert fit.axis_dir == pytest.approx((0.0, 0.0, 1.0))
    assert math.isnan(fit.rms_mm)
    assert all(math.isnan(v) for v in fit.extent_mm)


def test_cylinder_scientific_notation() -> None:
    fit = parse_cylinder(FROZEN_CYLINDER_SCI, "cylinder_0")
    assert fit.axis_point[0] == pytest.approx(1.77636e-15)
    assert fit.axis_point[1] == pytest.approx(-4.44089e-16)
    assert fit.radius_mm == pytest.approx(12.5605)


def test_cylinder_no_space_after_radius_label() -> None:
    """The wheel prints "radius:12.5214" with no space; a space is fine too."""
    spaced = FROZEN_CYLINDER.replace("radius:", "radius:  ")
    assert parse_cylinder(spaced, "c").radius_mm == pytest.approx(12.5214)


def test_variable_whitespace_is_tolerated() -> None:
    messy = (
        "  Type:   cylinder   center:(-0.0686792,0.0335444,6.52789)  "
        "axis:( -0 , 0 , 1 )   radius: 12.5214   # Pts:  800  "
    )
    fit = parse_cylinder(messy, "c")
    assert fit.radius_mm == pytest.approx(12.5214)
    assert fit.inlier_count == 800


# --------------------------------------------------------------------------
# Rejections: unsupported kinds and malformed text
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "info,kind", [(FROZEN_SPHERE, "sphere"), (FROZEN_CONE, "cone"), (FROZEN_TORUS, "torus")]
)
def test_unsupported_kinds_raise_a_clear_error(info: str, kind: str) -> None:
    """Not fitted, but the parser must name the kind rather than crash."""
    with pytest.raises(UnsupportedShapeError) as excinfo:
        parse_shape(info, "x")
    message = str(excinfo.value)
    assert kind in message
    assert "not modelled" in message
    assert message.isascii()


def test_unsupported_error_is_a_shape_parse_error() -> None:
    assert issubclass(UnsupportedShapeError, ShapeParseError)


@pytest.mark.parametrize(
    "info",
    [
        "",
        "banana",
        "Type: plane",
        "Type: plane (1, 0)x - 5= 0 #Pts: 4",
        "Type: plane (1, 0, 0)x - = 0 #Pts: 4",
        "Type: plane (1, 0, 0)x - 5= 0",
        "Type: plane (1, 0, 0)x - 5= 0 #Pts: many",
        "Type: cylinder center: (0, 0, 0) axis: (0, 0, 1) #Pts: 800",
        "Type: cylinder center: (0, 0, 0) radius:5 #Pts: 800",
        "Type: quadric center: (0, 0, 0) radius:5 #Pts: 800",
    ],
)
def test_malformed_strings_raise_shape_parse_error(info: str) -> None:
    with pytest.raises(ShapeParseError):
        parse_shape(info, "x")


def test_wrong_kind_for_specific_parser_is_reported() -> None:
    with pytest.raises(ShapeParseError, match="expected a plane"):
        parse_plane(FROZEN_CYLINDER, "plane_0")


def test_non_unit_direction_is_refused_not_rescaled() -> None:
    """A badly scaled direction is a fitting bug, not a printing artefact."""
    with pytest.raises(ShapeParseError, match="not unit length"):
        parse_plane("Type: plane (0, 0, 2)x - 5= 0 #Pts: 10", "plane_0")
    with pytest.raises(ShapeParseError, match="not unit length"):
        parse_cylinder(
            "Type: cylinder center: (0, 0, 0) axis: (0, 0, 0) radius:5 #Pts: 10", "c"
        )


@pytest.mark.parametrize("radius", ["0", "-3.5"])
def test_non_positive_radius_is_refused(radius: str) -> None:
    info = f"Type: cylinder center: (0, 0, 0) axis: (0, 0, 1) radius:{radius} #Pts: 10"
    with pytest.raises(ShapeParseError, match="radius"):
        parse_cylinder(info, "c")


# --------------------------------------------------------------------------
# Whole-list parsing
# --------------------------------------------------------------------------


def test_parse_shapes_splits_and_names_by_kind() -> None:
    planes, cylinders = parse_shapes(
        [FROZEN_PLANE, FROZEN_CYLINDER, FROZEN_PLANE_EXACT_POS, FROZEN_CYLINDER_SCI]
    )
    assert [p.name for p in planes] == [f"{PLANE_NAME_PREFIX}_0", f"{PLANE_NAME_PREFIX}_1"]
    assert [c.name for c in cylinders] == [
        f"{CYLINDER_NAME_PREFIX}_0",
        f"{CYLINDER_NAME_PREFIX}_1",
    ]
    assert planes[0].inlier_count == 593
    assert cylinders[1].radius_mm == pytest.approx(12.5605)


def test_parse_shapes_skips_unsupported_by_default() -> None:
    planes, cylinders = parse_shapes([FROZEN_SPHERE, FROZEN_PLANE, FROZEN_TORUS])
    assert len(planes) == 1
    assert cylinders == []


def test_parse_shapes_can_be_told_to_raise_on_unsupported() -> None:
    with pytest.raises(UnsupportedShapeError):
        parse_shapes([FROZEN_PLANE, FROZEN_CONE], skip_unsupported=False)


def test_parse_shapes_on_empty_input() -> None:
    assert parse_shapes([]) == ([], [])


# --------------------------------------------------------------------------
# Live fixture: run Efficient RANSAC in-process and parse the real output.
# --------------------------------------------------------------------------

CYLINDER_TRUE_RADIUS_MM = 12.5
CYLINDER_POINT_COUNT = 500
PLANE_TRUE_Z_MM = 5.0
PLANE_POINT_COUNT = 600
# Sampling noise small enough that the minimal-sample fit CGAL reports is
# stable run to run: measured max radius error 0.16 percent over 20 unseeded
# runs at this sigma, against the 1 percent acceptance bar.
LIVE_SIGMA_MM = 0.01
LIVE_SEED = 1337


def _detect(points, normals, **options) -> list[str]:
    """Run Efficient RANSAC on (N,3) arrays and return the raw info strings.

    Assumes CGAL is importable; the caller skips otherwise. Builds the point
    set the way docs/STACK_NOTES.md records: a Point_set_3 with a normal map,
    plus an int property map that receives the per-point shape index.
    """
    from CGAL.CGAL_Kernel import Point_3, Vector_3
    from CGAL.CGAL_Point_set_3 import Point_set_3
    from CGAL.CGAL_Shape_detection import efficient_RANSAC

    point_set = Point_set_3()
    point_set.add_normal_map()
    for point, normal in zip(points, normals):
        point_set.insert(
            Point_3(*(float(v) for v in point)), Vector_3(*(float(v) for v in normal))
        )
    shape_map = point_set.add_int_map("shape")
    return list(efficient_RANSAC(point_set, shape_map, **options))


@pytest.fixture(scope="module")
def live_cylinder_info() -> str:
    """One real cylinder info string from a fresh in-process RANSAC run."""
    pytest.importorskip("CGAL.CGAL_Shape_detection")
    numpy = pytest.importorskip("numpy")

    rng = numpy.random.default_rng(LIVE_SEED)
    theta = rng.uniform(0.0, 2.0 * numpy.pi, CYLINDER_POINT_COUNT)
    height = rng.uniform(0.0, 30.0, CYLINDER_POINT_COUNT)
    normals = numpy.stack(
        [numpy.cos(theta), numpy.sin(theta), numpy.zeros(CYLINDER_POINT_COUNT)], axis=1
    )
    points = numpy.stack(
        [
            CYLINDER_TRUE_RADIUS_MM * numpy.cos(theta),
            CYLINDER_TRUE_RADIUS_MM * numpy.sin(theta),
            height,
        ],
        axis=1,
    )
    points += normals * rng.normal(0.0, LIVE_SIGMA_MM, (CYLINDER_POINT_COUNT, 1))

    infos = _detect(
        points,
        normals,
        min_points=100,
        epsilon=0.2,
        cluster_epsilon=3.0,
        normal_threshold=0.9,
        planes=False,
        cylinders=True,
    )
    assert len(infos) == 1, f"expected one cylinder, got {infos!r}"
    return infos[0]


@pytest.fixture(scope="module")
def live_plane_info() -> str:
    """One real plane info string from a fresh in-process RANSAC run."""
    pytest.importorskip("CGAL.CGAL_Shape_detection")
    numpy = pytest.importorskip("numpy")

    rng = numpy.random.default_rng(LIVE_SEED)
    normals = numpy.tile([0.0, 0.0, 1.0], (PLANE_POINT_COUNT, 1))
    points = numpy.stack(
        [
            rng.uniform(-20.0, 20.0, PLANE_POINT_COUNT),
            rng.uniform(-20.0, 20.0, PLANE_POINT_COUNT),
            numpy.full(PLANE_POINT_COUNT, PLANE_TRUE_Z_MM),
        ],
        axis=1,
    )
    points += normals * rng.normal(0.0, LIVE_SIGMA_MM, (PLANE_POINT_COUNT, 1))

    infos = _detect(
        points,
        normals,
        min_points=100,
        epsilon=0.2,
        cluster_epsilon=5.0,
        normal_threshold=0.9,
        planes=True,
    )
    assert len(infos) == 1, f"expected one plane, got {infos!r}"
    return infos[0]


def test_live_cylinder_string_still_matches_the_frozen_format(
    live_cylinder_info: str,
) -> None:
    """Upstream format drift detector: the live string must still parse."""
    assert shape_kind(live_cylinder_info) == "cylinder"
    parse_cylinder(live_cylinder_info, "cylinder_0")


def test_live_cylinder_round_trip_recovers_the_radius(live_cylinder_info: str) -> None:
    """WI-1 acceptance: radius recovered within 1 percent of ground truth."""
    fit = parse_cylinder(live_cylinder_info, "cylinder_0")
    error_pct = abs(fit.radius_mm - CYLINDER_TRUE_RADIUS_MM) / CYLINDER_TRUE_RADIUS_MM * 100.0
    assert error_pct < 1.0, f"radius {fit.radius_mm} mm from {live_cylinder_info!r}"


def test_live_cylinder_axis_and_inliers(live_cylinder_info: str) -> None:
    fit = parse_cylinder(live_cylinder_info, "cylinder_0")
    assert _angle_deg(fit.axis_dir, (0.0, 0.0, 1.0)) < 1.0
    # The axis passes through the origin in xy; CGAL reports some point on it.
    assert math.hypot(fit.axis_point[0], fit.axis_point[1]) < 0.1
    assert 0.8 * CYLINDER_POINT_COUNT <= fit.inlier_count <= CYLINDER_POINT_COUNT


def test_live_plane_round_trip_recovers_the_offset(live_plane_info: str) -> None:
    """Guards the plus sign convention against a real fit, both normal signs."""
    fit = parse_plane(live_plane_info, "plane_0")
    assert _angle_deg(fit.normal, (0.0, 0.0, 1.0)) < 1.0
    # CGAL may orient the normal either way, so compare the unsigned offset and
    # then check the point itself sits at the true height.
    assert abs(_signed_offset(fit)) == pytest.approx(PLANE_TRUE_Z_MM, abs=0.1)
    assert fit.point[2] == pytest.approx(PLANE_TRUE_Z_MM, abs=0.1)
    assert 0.8 * PLANE_POINT_COUNT <= fit.inlier_count <= PLANE_POINT_COUNT
