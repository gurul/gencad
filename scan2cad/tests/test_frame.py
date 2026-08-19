"""Unit tests for the frame, snapping and merging stage (WI-4).

Everything here is built from hand-written primitives, so the tests run without
CGAL, without open3d and without any other work item's module. The two
properties the acceptance criteria name -- the triad survives a 3 degree
perturbation, and nothing is ever snapped silently or outside tolerance -- are
tested directly, plus the merging and naming rules the report depends on.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from scan2cad.frame import (
    FrameError,
    align_and_snap,
    cluster_plane_normals,
    dominant_frame,
)
from scan2cad.primitives import CylinderFit, PlaneFit, SceneModel
from scan2cad.thresholds import COARSE, FINE

# The worked example everywhere else in the repo uses: a 60 by 40 by 20 mm
# block. Inlier counts are chosen so the z faces are the largest cluster and
# the x faces the second largest, which makes the recovered triad the world
# axes and the test assertions readable.
BLOCK = (60.0, 40.0, 20.0)
_FACE_INLIERS = {
    "bottom": 7000,
    "top": 6900,
    "left": 5200,
    "right": 5100,
    "front": 4100,
    "back": 4050,
}
_RMS_MM = 0.3


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _unit(vec) -> tuple[float, float, float]:
    array = np.asarray(vec, dtype=np.float64)
    array = array / float(np.linalg.norm(array))
    return (float(array[0]), float(array[1]), float(array[2]))


def _rotate(vec, axis, degrees: float) -> tuple[float, float, float]:
    """Rotate `vec` about `axis` by `degrees` (Rodrigues), returning a unit vector."""
    v = np.asarray(vec, dtype=np.float64)
    k = np.asarray(axis, dtype=np.float64)
    k = k / float(np.linalg.norm(k))
    theta = math.radians(degrees)
    rotated = (
        v * math.cos(theta)
        + np.cross(k, v) * math.sin(theta)
        + k * float(np.dot(k, v)) * (1.0 - math.cos(theta))
    )
    return _unit(rotated)


def _angle_deg(a, b) -> float:
    dot = float(np.dot(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _block_planes(
    height_mm: float = BLOCK[2],
    tilts: dict[str, tuple[tuple[float, float, float], float]] | None = None,
) -> list[PlaneFit]:
    """Six outward-facing faces of a block, optionally tilted face by face.

    `tilts` maps a face name to (rotation axis, degrees). Points are the face
    centres, so the centroid of the six is the block centre. Names are the
    index names the fitter would produce, in the order the faces are listed.
    """
    width, depth = BLOCK[0], BLOCK[1]
    faces = [
        ("bottom", (width / 2, depth / 2, 0.0), (0.0, 0.0, -1.0), (-30.0, 30.0, -20.0, 20.0)),
        ("top", (width / 2, depth / 2, height_mm), (0.0, 0.0, 1.0), (-30.0, 30.0, -20.0, 20.0)),
        ("left", (0.0, depth / 2, height_mm / 2), (-1.0, 0.0, 0.0), (-20.0, 20.0, -10.0, 10.0)),
        ("right", (width, depth / 2, height_mm / 2), (1.0, 0.0, 0.0), (-20.0, 20.0, -10.0, 10.0)),
        ("front", (width / 2, 0.0, height_mm / 2), (0.0, -1.0, 0.0), (-30.0, 30.0, -10.0, 10.0)),
        ("back", (width / 2, depth, height_mm / 2), (0.0, 1.0, 0.0), (-30.0, 30.0, -10.0, 10.0)),
    ]
    tilts = tilts or {}
    planes: list[PlaneFit] = []
    for index, (face, point, normal, extent) in enumerate(faces):
        if face in tilts:
            axis, degrees = tilts[face]
            normal = _rotate(normal, axis, degrees)
        planes.append(
            PlaneFit(
                name=f"plane_{index}",
                point=point,
                normal=_unit(normal),
                inlier_count=_FACE_INLIERS[face],
                rms_mm=_RMS_MM,
                extent=extent,
            )
        )
    return planes


def _cylinder(
    name: str = "cylinder_0",
    axis_point=(15.0, 20.0, 10.0),
    axis_dir=(0.0, 0.0, 1.0),
    radius_mm: float = 6.25,
    extent_mm=(-10.0, 10.0),
    inlier_count: int = 3100,
    rms_mm: float = 0.2,
) -> CylinderFit:
    return CylinderFit(
        name=name,
        axis_point=axis_point,
        axis_dir=_unit(axis_dir),
        radius_mm=radius_mm,
        extent_mm=extent_mm,
        inlier_count=inlier_count,
        rms_mm=rms_mm,
    )


def _records_named(scene: SceneModel, dim_name: str) -> list:
    return [snap for snap in scene.snaps if snap.dim_name == dim_name]


def _plane(scene: SceneModel, name: str) -> PlaneFit:
    for plane in scene.planes:
        if plane.name == name:
            return plane
    raise AssertionError(f"no plane named {name} in {[p.name for p in scene.planes]}")


# ---------------------------------------------------------------------------
# clustering and triad recovery
# ---------------------------------------------------------------------------


def test_clustering_pairs_opposite_faces() -> None:
    """Opposite faces of a block are one direction seen twice, so one cluster."""
    clusters = cluster_plane_normals(_block_planes(), COARSE.angular_snap_deg)
    assert [sorted(members) for members in clusters] == [[0, 1], [2, 3], [4, 5]]


def test_clustering_does_not_chain_across_the_tolerance() -> None:
    """Complete linkage: 4 degree steps never add up to one 8 degree cluster."""
    planes = [
        PlaneFit("plane_0", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 100, 0.1, (0.0, 1.0, 0.0, 1.0)),
        PlaneFit("plane_1", (0.0, 0.0, 1.0), _rotate((0, 0, 1), (1, 0, 0), 4.0), 100, 0.1, (0.0, 1.0, 0.0, 1.0)),
        PlaneFit("plane_2", (0.0, 0.0, 2.0), _rotate((0, 0, 1), (1, 0, 0), 8.0), 100, 0.1, (0.0, 1.0, 0.0, 1.0)),
    ]
    clusters = cluster_plane_normals(planes, COARSE.angular_snap_deg)
    assert sorted(len(members) for members in clusters) == [1, 2]


def test_triad_is_the_world_frame_for_an_axis_aligned_block() -> None:
    frame = dominant_frame(_block_planes(), [], COARSE)
    assert frame is not None
    assert frame.x_axis == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)
    assert frame.y_axis == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
    assert frame.z_axis == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    assert frame.origin == pytest.approx((30.0, 20.0, 10.0), abs=1e-12)
    assert frame.supported == (True, True, True)


def test_triad_survives_a_three_degree_perturbation() -> None:
    """PLAN.md WI-4 acceptance: triad recovery under 3 degree perturbation.

    Each face is tilted 3 degrees, in opposite senses within a pair, so no two
    opposite faces cluster and the triad has to be built from single faces.
    """
    tilts = {
        "bottom": ((1.0, 0.0, 0.0), 3.0),
        "top": ((1.0, 0.0, 0.0), -3.0),
        "left": ((0.0, 0.0, 1.0), 3.0),
        "right": ((0.0, 0.0, 1.0), -3.0),
        "front": ((1.0, 0.0, 0.0), 3.0),
        "back": ((1.0, 0.0, 0.0), -3.0),
    }
    frame = dominant_frame(_block_planes(tilts=tilts), [], COARSE)
    assert frame is not None
    assert frame.supported == (True, True, True)
    assert _angle_deg(frame.z_axis, (0.0, 0.0, 1.0)) <= 3.1
    assert _angle_deg(frame.x_axis, (1.0, 0.0, 0.0)) <= 3.1
    assert _angle_deg(frame.y_axis, (0.0, 1.0, 0.0)) <= 4.5


def test_triad_is_orthonormal_and_right_handed() -> None:
    tilts = {"top": ((1.0, 1.0, 0.0), 2.0), "right": ((0.0, 0.0, 1.0), 2.0)}
    frame = dominant_frame(_block_planes(tilts=tilts), [], COARSE)
    assert frame is not None
    x, y, z = (np.asarray(axis, dtype=np.float64) for axis in frame.axes())
    for axis in (x, y, z):
        assert float(np.linalg.norm(axis)) == pytest.approx(1.0, abs=1e-12)
    assert float(np.dot(x, y)) == pytest.approx(0.0, abs=1e-12)
    assert float(np.dot(y, z)) == pytest.approx(0.0, abs=1e-12)
    assert float(np.dot(z, x)) == pytest.approx(0.0, abs=1e-12)
    assert np.cross(x, y) == pytest.approx(z, abs=1e-12)


def test_no_primitives_means_no_frame() -> None:
    assert dominant_frame([], [], COARSE) is None
    scene = align_and_snap([], [], thresholds=COARSE)
    assert scene.frame == ()
    assert scene.planes == [] and scene.cylinders == [] and scene.snaps == []


def test_a_cylinder_alone_still_defines_an_axis() -> None:
    """A bore-only scan gets a Z from the bore, and no invented X or Y."""
    frame = dominant_frame([], [_cylinder(axis_dir=(0.0, 0.0, 1.0))], COARSE)
    assert frame is not None
    assert frame.z_axis == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    assert frame.supported == (False, False, True)


# ---------------------------------------------------------------------------
# angular snapping
# ---------------------------------------------------------------------------


def test_plane_normal_inside_tolerance_is_snapped_and_recorded() -> None:
    tilts = {"back": ((1.0, 0.0, 0.0), 3.0)}
    scene = align_and_snap(_block_planes(tilts=tilts), [], thresholds=COARSE)
    back = _plane(scene, "plane_back")
    assert back.normal == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)

    records = _records_named(scene, "plane_back_normal")
    assert len(records) == 1
    record = records[0]
    assert record.raw == pytest.approx(3.0, abs=1e-9)
    assert record.snapped == 0.0
    assert record.deviation == pytest.approx(-3.0, abs=1e-9)
    assert record.rule == "axis-align 5deg"


def test_plane_normal_outside_tolerance_is_left_alone() -> None:
    """A face 8 degrees off axis stays 8 degrees off axis, with no record."""
    tilts = {"back": ((1.0, 0.0, 0.0), 8.0)}
    planes = _block_planes(tilts=tilts)
    scene = align_and_snap(planes, [], thresholds=COARSE)
    tilted = [p for p in scene.planes if p.name.startswith("plane_") and p.name[6:].isdigit()]
    assert [p.normal for p in tilted] == [planes[5].normal]
    assert not [snap for snap in scene.snaps if "normal" in snap.dim_name]


def test_fine_regime_refuses_a_three_degree_snap() -> None:
    """The frozen fine regime allows 1 degree, so a 3 degree face is not moved."""
    tilts = {"back": ((1.0, 0.0, 0.0), 3.0)}
    planes = _block_planes(tilts=tilts)
    scene = align_and_snap(planes, [], thresholds=FINE)
    assert planes[5].normal in [plane.normal for plane in scene.planes]
    assert not [snap for snap in scene.snaps if snap.dim_name.endswith("_normal")]


def test_cylinder_axis_is_snapped_and_recorded() -> None:
    cylinder = _cylinder(axis_dir=_rotate((0, 0, 1), (1, 0, 0), 1.4))
    scene = align_and_snap(_block_planes(), [cylinder], thresholds=COARSE)
    assert scene.cylinders[0].axis_dir == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    records = _records_named(scene, "cylinder_0_axis")
    assert len(records) == 1
    assert records[0].raw == pytest.approx(1.4, abs=1e-9)
    assert records[0].rule == "axis-align 5deg"


def test_unsupported_axes_are_never_snapped_to() -> None:
    """With one normal cluster only Z is real, so nothing snaps to the filler X.

    The frame still has to be a triad, but X and Y are completions, not
    evidence, and pulling a bore onto one would invent structure the scan never
    showed.
    """
    planes = [
        PlaneFit("plane_0", (0.0, 0.0, 0.0), (0.0, 0.0, -1.0), 7000, 0.3, (-30.0, 30.0, -20.0, 20.0)),
        PlaneFit("plane_1", (0.0, 0.0, 20.0), (0.0, 0.0, 1.0), 6900, 0.3, (-30.0, 30.0, -20.0, 20.0)),
    ]
    sideways = _cylinder(axis_dir=_rotate((1, 0, 0), (0, 0, 1), 3.0))
    scene = align_and_snap(planes, [sideways], thresholds=COARSE)
    assert scene.frame[0] is not None
    assert scene.cylinders[0].axis_dir == pytest.approx(sideways.axis_dir, abs=1e-12)
    assert not [snap for snap in scene.snaps if snap.dim_name.endswith("_axis")]


# ---------------------------------------------------------------------------
# lengths: gaps and diameters
# ---------------------------------------------------------------------------


def test_gap_inside_tolerance_is_rounded_and_both_faces_move() -> None:
    scene = align_and_snap(_block_planes(height_mm=20.23), [], thresholds=COARSE)
    bottom = _plane(scene, "plane_bottom")
    top = _plane(scene, "plane_top")
    gap = abs(
        float(np.dot(np.asarray(top.point) - np.asarray(bottom.point), np.asarray(top.normal)))
    )
    assert gap == pytest.approx(20.2, abs=1e-9)
    assert bottom.point[2] == pytest.approx(0.015, abs=1e-9)
    assert top.point[2] == pytest.approx(20.215, abs=1e-9)

    records = _records_named(scene, "gap_plane_bottom_plane_top")
    assert len(records) == 1
    assert records[0].raw == pytest.approx(20.23, abs=1e-9)
    assert records[0].snapped == pytest.approx(20.2, abs=1e-9)
    assert records[0].deviation == pytest.approx(-0.03, abs=1e-9)
    assert records[0].rule == "length-round 0.1mm within 2xRMS"


def test_gap_is_not_rounded_when_the_move_exceeds_tolerance() -> None:
    """A very tight fit earns a very tight tolerance, and 0.03 mm is too far."""
    planes = [
        PlaneFit(plane.name, plane.point, plane.normal, plane.inlier_count, 0.005, plane.extent)
        for plane in _block_planes(height_mm=20.23)
    ]
    scene = align_and_snap(planes, [], thresholds=COARSE)
    top = _plane(scene, "plane_top")
    assert top.point[2] == pytest.approx(20.23, abs=1e-12)
    assert not [snap for snap in scene.snaps if snap.dim_name.startswith("gap_")]


def test_fine_regime_uses_its_flat_tolerance_in_the_rule_text() -> None:
    """The fine regime allows 0.5 mm regardless of residual, and says so."""
    scene = align_and_snap(_block_planes(height_mm=20.23), [], thresholds=FINE)
    records = _records_named(scene, "gap_plane_bottom_plane_top")
    assert len(records) == 1
    assert records[0].snapped == pytest.approx(20.2, abs=1e-9)
    assert records[0].rule == "length-round 0.1mm within 0.5mm"


def test_diameter_is_rounded_onto_the_grid_not_the_radius() -> None:
    """A 12.4744 mm bore becomes 12.5, not 12.4: the diameter is the dimension."""
    cylinder = _cylinder(radius_mm=6.2372, rms_mm=0.3)
    scene = align_and_snap(_block_planes(), [cylinder], thresholds=COARSE)
    assert scene.cylinders[0].radius_mm == pytest.approx(6.25, abs=1e-12)
    records = _records_named(scene, "cylinder_0_diameter")
    assert len(records) == 1
    assert records[0].raw == pytest.approx(12.4744, abs=1e-9)
    assert records[0].snapped == pytest.approx(12.5, abs=1e-9)
    assert records[0].rule == "length-round 0.1mm within 2xRMS"


def test_diameter_is_not_rounded_beyond_tolerance() -> None:
    cylinder = _cylinder(radius_mm=6.2372, rms_mm=0.001)
    scene = align_and_snap(_block_planes(), [cylinder], thresholds=COARSE)
    assert scene.cylinders[0].radius_mm == pytest.approx(6.2372, abs=1e-12)
    assert not [snap for snap in scene.snaps if "diameter" in snap.dim_name]


# ---------------------------------------------------------------------------
# radius clustering and concentric merging
# ---------------------------------------------------------------------------


def test_equal_radius_bores_are_given_one_radius() -> None:
    """Two holes from one drill are one dimension the user edits once."""
    first = _cylinder(name="cylinder_0", axis_point=(15.0, 20.0, 10.0), radius_mm=2.51, rms_mm=0.1, inlier_count=1000)
    second = _cylinder(name="cylinder_1", axis_point=(45.0, 20.0, 10.0), radius_mm=2.49, rms_mm=0.1, inlier_count=1000)
    scene = align_and_snap(_block_planes(), [first, second], thresholds=COARSE)
    assert len(scene.cylinders) == 2
    radii = {round(cylinder.radius_mm, 9) for cylinder in scene.cylinders}
    assert radii == {2.5}
    assert len(_records_named(scene, "cylinder_0_radius")) == 1
    assert len(_records_named(scene, "cylinder_1_radius")) == 1
    assert _records_named(scene, "cylinder_0_radius")[0].rule == "radius-cluster 2xRMS"


def test_different_radii_are_left_apart() -> None:
    first = _cylinder(name="cylinder_0", axis_point=(15.0, 20.0, 10.0), radius_mm=2.5, rms_mm=0.1)
    second = _cylinder(name="cylinder_1", axis_point=(45.0, 20.0, 10.0), radius_mm=4.0, rms_mm=0.1)
    scene = align_and_snap(_block_planes(), [first, second], thresholds=COARSE)
    assert sorted(round(c.radius_mm, 6) for c in scene.cylinders) == [2.5, 4.0]
    assert not [snap for snap in scene.snaps if snap.dim_name.endswith("_radius")]


def test_concentric_patches_merge_into_one_bore() -> None:
    """One bore fitted as two patches comes back as one bore spanning both."""
    lower = _cylinder(
        name="cylinder_0", axis_point=(15.0, 20.0, 4.0), extent_mm=(-4.0, 4.0),
        radius_mm=6.25, inlier_count=2000, rms_mm=0.2,
    )
    upper = _cylinder(
        name="cylinder_1", axis_point=(15.0, 20.0, 16.0), extent_mm=(-4.0, 4.0),
        radius_mm=6.25, inlier_count=1000, rms_mm=0.2,
    )
    scene = align_and_snap(_block_planes(), [lower, upper], thresholds=COARSE)
    assert len(scene.cylinders) == 1
    merged = scene.cylinders[0]
    assert merged.name == "cylinder_0"
    assert merged.inlier_count == 3000
    assert merged.extent_mm[1] - merged.extent_mm[0] == pytest.approx(20.0, abs=1e-9)
    assert merged.axis_point[2] == pytest.approx(10.0, abs=1e-9)
    records = _records_named(scene, "cylinder_0_axis_offset")
    assert len(records) == 1
    assert records[0].rule == "concentric-merge 2xRMS, absorbed cylinder_1"


def test_parallel_but_offset_bores_do_not_merge() -> None:
    first = _cylinder(name="cylinder_0", axis_point=(15.0, 20.0, 10.0))
    second = _cylinder(name="cylinder_1", axis_point=(45.0, 20.0, 10.0))
    scene = align_and_snap(_block_planes(), [first, second], thresholds=COARSE)
    assert len(scene.cylinders) == 2
    assert not [snap for snap in scene.snaps if "axis_offset" in snap.dim_name]


# ---------------------------------------------------------------------------
# semantic names
# ---------------------------------------------------------------------------


def test_block_faces_get_semantic_names() -> None:
    scene = align_and_snap(_block_planes(), [], thresholds=COARSE)
    assert {plane.name for plane in scene.planes} == {
        "plane_left",
        "plane_right",
        "plane_front",
        "plane_back",
        "plane_bottom",
        "plane_top",
    }
    assert _plane(scene, "plane_top").normal == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    assert _plane(scene, "plane_bottom").normal == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)


def test_ambiguous_faces_keep_their_index_names() -> None:
    """Two upward faces at different heights: neither one is "the top"."""
    planes = _block_planes()
    extra = PlaneFit(
        name="plane_6",
        point=(30.0, 20.0, 12.0),
        normal=(0.0, 0.0, 1.0),
        inlier_count=900,
        rms_mm=0.3,
        extent=(-10.0, 10.0, -10.0, 10.0),
    )
    scene = align_and_snap([*planes, extra], [], thresholds=COARSE)
    names = {plane.name for plane in scene.planes}
    assert "plane_top" not in names
    assert {"plane_1", "plane_6"} <= names
    assert {"plane_bottom", "plane_left", "plane_right", "plane_front", "plane_back"} <= names


def test_snap_records_follow_the_semantic_renaming() -> None:
    """A record emitted against plane_5 must end up naming plane_back."""
    tilts = {"back": ((1.0, 0.0, 0.0), 3.0)}
    scene = align_and_snap(_block_planes(tilts=tilts, height_mm=20.23), [], thresholds=COARSE)
    names = {plane.name for plane in scene.planes}
    assert names == {
        "plane_left",
        "plane_right",
        "plane_front",
        "plane_back",
        "plane_bottom",
        "plane_top",
    }
    assert scene.snaps
    for snap in scene.snaps:
        assert not re.search(r"plane_\d", snap.dim_name), snap
        assert any(name in snap.dim_name for name in names), snap


# ---------------------------------------------------------------------------
# the no-silent-snapping property
# ---------------------------------------------------------------------------


def _messy_scene_inputs() -> tuple[list[PlaneFit], list[CylinderFit]]:
    """A block whose every face is a little off, with a bore fitted twice."""
    tilts = {
        "bottom": ((1.0, 0.0, 0.0), 2.0),
        "top": ((1.0, 0.0, 0.0), -2.0),
        "left": ((0.0, 0.0, 1.0), 2.0),
        "right": ((0.0, 0.0, 1.0), -2.0),
        "front": ((0.0, 0.0, 1.0), 1.5),
        "back": ((0.0, 0.0, 1.0), -1.5),
    }
    planes = _block_planes(height_mm=20.23, tilts=tilts)
    cylinders = [
        _cylinder(
            name="cylinder_0",
            axis_point=(15.0, 20.0, 5.0),
            axis_dir=_rotate((0, 0, 1), (1, 0, 0), 1.0),
            radius_mm=6.2372,
            extent_mm=(-5.0, 5.0),
            inlier_count=2000,
            rms_mm=0.3,
        ),
        _cylinder(
            name="cylinder_1",
            axis_point=(15.02, 20.0, 15.0),
            axis_dir=(0.0, 0.0, 1.0),
            radius_mm=6.24,
            extent_mm=(-5.0, 5.0),
            inlier_count=1500,
            rms_mm=0.3,
        ),
    ]
    return planes, cylinders


def _closest_input_plane(target: PlaneFit, candidates: list[PlaneFit]) -> PlaneFit:
    return min(
        candidates,
        key=lambda plane: (
            _angle_deg(plane.normal, target.normal)
            + float(np.linalg.norm(np.asarray(plane.point) - np.asarray(target.point)))
        ),
    )


def test_every_mutation_carries_a_snap_record() -> None:
    """PLAN.md ground rule 6, tested as a property rather than case by case."""
    planes, cylinders = _messy_scene_inputs()
    scene = align_and_snap(planes, cylinders, thresholds=COARSE)

    for plane in scene.planes:
        source = _closest_input_plane(plane, planes)
        if _angle_deg(plane.normal, source.normal) > 1e-9:
            assert _records_named(scene, f"{plane.name}_normal"), plane.name
        moved = float(np.linalg.norm(np.asarray(plane.point) - np.asarray(source.point)))
        if moved > 1e-9:
            assert [
                snap
                for snap in scene.snaps
                if snap.dim_name.startswith("gap_") and plane.name in snap.dim_name
            ], plane.name

    merged = scene.cylinders[0]
    assert len(scene.cylinders) == 1
    for kind in ("axis", "radius", "axis_offset", "diameter"):
        assert _records_named(scene, f"{merged.name}_{kind}"), kind


def test_every_snap_record_is_traceable_to_a_primitive() -> None:
    """A record names a surviving primitive, or one a merge record accounts for."""
    planes, cylinders = _messy_scene_inputs()
    scene = align_and_snap(planes, cylinders, thresholds=COARSE)
    names = {primitive.name for primitive in (*scene.planes, *scene.cylinders)}
    absorbed = {
        snap.rule.rsplit(" ", 1)[-1]
        for snap in scene.snaps
        if snap.rule.startswith("concentric-merge")
    }
    assert absorbed == {"cylinder_1"}
    for snap in scene.snaps:
        assert any(name in snap.dim_name for name in names | absorbed), snap.dim_name


def test_snap_deviation_is_always_snapped_minus_raw() -> None:
    planes, cylinders = _messy_scene_inputs()
    scene = align_and_snap(planes, cylinders, thresholds=COARSE)
    assert scene.snaps
    for snap in scene.snaps:
        assert snap.deviation == pytest.approx(snap.snapped - snap.raw, abs=1e-12)


def test_output_is_ascii_and_deterministic() -> None:
    planes, cylinders = _messy_scene_inputs()
    first = align_and_snap(planes, cylinders, thresholds=COARSE)
    second = align_and_snap(planes, cylinders, thresholds=COARSE)
    assert first == second
    for snap in first.snaps:
        assert snap.dim_name.isascii() and snap.rule.isascii()
    for primitive in (*first.planes, *first.cylinders):
        assert primitive.name.isascii()


def test_nothing_is_snapped_at_all_when_the_fit_is_already_exact() -> None:
    scene = align_and_snap(_block_planes(), [_cylinder()], thresholds=COARSE)
    assert scene.snaps == []


# ---------------------------------------------------------------------------
# input validation and downstream agreement
# ---------------------------------------------------------------------------


def test_duplicate_names_are_rejected() -> None:
    planes = _block_planes()
    clashing = [planes[0], *[p for p in planes[1:]], planes[0]]
    with pytest.raises(FrameError):
        align_and_snap(clashing, [], thresholds=COARSE)


def test_non_ascii_names_are_rejected() -> None:
    planes = _block_planes()
    # Written as an escape so this test file itself stays pure ASCII.
    bad = [
        PlaneFit(
            "plane_\u00e9", planes[0].point, planes[0].normal, 10, 0.1, planes[0].extent
        )
    ]
    with pytest.raises(FrameError):
        align_and_snap(bad, [], thresholds=COARSE)


def test_scene_renders_through_the_report() -> None:
    """The names this stage invents are the names the report reads back.

    Light integration only: it proves the snap log and the dimension lines
    agree about what things are called, which is the contract WI-5 depends on.
    """
    report = pytest.importorskip("scan2cad.report")
    planes, cylinders = _messy_scene_inputs()
    scene = align_and_snap(planes, cylinders, thresholds=COARSE)
    text = report.render_report(scene, units_note="input read as millimetres", regime=COARSE)
    text.encode("ascii")
    assert "height = 20.2 mm, gap between plane_bottom and plane_top" in text
    assert "cylinder_0_diameter = 12.5 mm" in text
    for snap in scene.snaps:
        assert f"{snap.dim_name}: raw " in text
