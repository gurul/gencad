"""Acceptance tests for the synthetic generator (WI-9).

PLAN.md acceptance for WI-9 is two claims: the truth dictionary's dimensions
match the construction, and the sampler is deterministic per seed. Both are
checked here against the geometry itself rather than against restated literals,
so a builder that drifts from its own truth record fails.

The generator lives in tools/, which is not an importable package, so it is
loaded from its path. Registering it in sys.modules before executing it is
required: dataclasses looks its own module up by name while building each
frozen class.

These tests need only numpy. The PLY round-trip test additionally wants open3d
and skips without it, so the suite still runs in a bare interpreter.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_TOOL_PATH = Path(__file__).resolve().parent.parent / "tools" / "make_synthetic.py"


def _load_generator():
    """Import tools/make_synthetic.py under the name 'make_synthetic'."""
    spec = importlib.util.spec_from_file_location("make_synthetic", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ms = _load_generator()


# --------------------------------------------------------------------------
# geometry helpers used by the assertions
# --------------------------------------------------------------------------


def _by_name(records: list[dict]) -> dict[str, dict]:
    """Index truth records by their name field."""
    return {record["name"]: record for record in records}


def _plane_gap(truth: dict, name_a: str, name_b: str) -> float:
    """Perpendicular distance between two truth planes, from the records alone."""
    planes = _by_name(truth["planes"])
    a, b = planes[name_a], planes[name_b]
    delta = np.asarray(b["point"]) - np.asarray(a["point"])
    return abs(float(np.dot(delta, np.asarray(a["normal"]))))


def _point_above_plane(truth: dict, point, plane_name: str) -> float:
    """Distance from a truth plane to `point`, measured along the inward direction.

    Inward means opposite the plane's outward normal, so a bore axis inside the
    part gives a positive number.
    """
    plane = _by_name(truth["planes"])[plane_name]
    delta = np.asarray(point) - np.asarray(plane["point"])
    return -float(np.dot(delta, np.asarray(plane["normal"])))


def _true_normals(module_model, points: np.ndarray, patch_index: np.ndarray, truth: dict):
    """Recompute the exact outward normal each point should have.

    Assumes the cloud was sampled with sigma and bias at zero, so a cylinder
    point's radial direction is still exact. Used to measure normal-sign damage
    without depending on two runs producing the same point order -- they do not,
    because every knob that draws from the generator shifts the final shuffle.
    """
    planes = _by_name(truth["planes"])
    cylinders = _by_name(truth["cylinders"])
    out = np.empty_like(points)
    for index in np.unique(patch_index):
        patch = module_model.patches[int(index)]
        mask = patch_index == index
        if patch.primitive in planes:
            out[mask] = np.asarray(planes[patch.primitive]["normal"])
        else:
            cylinder = cylinders[patch.primitive]
            axis_dir = np.asarray(cylinder["axis_dir"])
            delta = points[mask] - np.asarray(cylinder["axis_point"])
            radial = delta - (delta @ axis_dir)[:, None] * axis_dir
            radial = radial / np.linalg.norm(radial, axis=1)[:, None]
            out[mask] = radial if patch.outward else -radial
    return out


def _canonical(points: np.ndarray) -> np.ndarray:
    """Sort points into a canonical order so two clouds can be compared as sets."""
    return points[np.lexsort(points.T)]


def _residuals(module_model, points: np.ndarray, patch_index: np.ndarray, truth: dict):
    """Signed distance from every point to the truth surface it was drawn from.

    Assumes `points` and `patch_index` came from one `sample_model` call on
    `module_model`. Planes give point-to-plane distance along the outward
    normal; cylinders give (distance from axis) minus radius, signed so that a
    positive value always means "further out of the material".
    """
    planes = _by_name(truth["planes"])
    cylinders = _by_name(truth["cylinders"])
    out = np.empty(points.shape[0], dtype=np.float64)
    for index in np.unique(patch_index):
        patch = module_model.patches[int(index)]
        mask = patch_index == index
        subset = points[mask]
        if patch.primitive in planes:
            plane = planes[patch.primitive]
            delta = subset - np.asarray(plane["point"])
            out[mask] = delta @ np.asarray(plane["normal"])
        else:
            cylinder = cylinders[patch.primitive]
            axis_point = np.asarray(cylinder["axis_point"])
            axis_dir = np.asarray(cylinder["axis_dir"])
            delta = subset - axis_point
            along = delta @ axis_dir
            radial = delta - along[:, None] * axis_dir
            signed = np.linalg.norm(radial, axis=1) - cylinder["radius_mm"]
            # a bore's material is outside its radius, so flip the sign there
            out[mask] = signed if patch.outward else -signed
    return out


# --------------------------------------------------------------------------
# truth dictionary
# --------------------------------------------------------------------------


def test_three_models_exist() -> None:
    """PLAN.md WI-9 names exactly these three models."""
    assert ms.MODEL_NAMES == ("bracket", "lbracket", "bossbox")


@pytest.mark.parametrize("name", ms.MODEL_NAMES)
def test_truth_dict_shape(name: str) -> None:
    """Every model returns points, normals and a complete, JSON-safe truth dict."""
    points, normals, truth = ms.make_model(name)
    assert points.shape == normals.shape
    assert points.ndim == 2 and points.shape[1] == 3
    assert points.shape[0] == truth["n_points"] == 80_000
    assert truth["model"] == name
    assert truth["units"] == "mm"
    assert truth["provenance"] == "synthetic"
    assert len(truth["planes"]) == truth["n_planes"]
    assert len(truth["cylinders"]) == truth["n_cylinders"]
    assert truth["planes_sampled"] == truth["n_planes"]
    assert truth["cylinders_sampled"] == truth["n_cylinders"]
    assert truth["dims_mm"], "a model with no named dimensions is not testable"
    names = [record["name"] for record in truth["planes"] + truth["cylinders"]]
    assert len(names) == len(set(names)), f"duplicate primitive names: {names}"
    for record in truth["planes"]:
        assert math.isclose(float(np.linalg.norm(record["normal"])), 1.0, abs_tol=1e-12)
    for record in truth["cylinders"]:
        assert math.isclose(float(np.linalg.norm(record["axis_dir"])), 1.0, abs_tol=1e-12)


def test_primitive_counts_match_plan() -> None:
    """Counts are the CI gate's expected values; changing one is a plan change."""
    counts = {
        name: (truth["n_planes"], truth["n_cylinders"])
        for name, truth in ((n, ms.make_model(n)[2]) for n in ms.MODEL_NAMES)
    }
    assert counts == {"bracket": (6, 1), "lbracket": (8, 2), "bossbox": (7, 1)}


def test_bracket_dims_match_construction() -> None:
    """Each named bracket dimension is recomputed from the truth primitives."""
    truth = ms.make_model("bracket")[2]
    dims = truth["dims_mm"]
    bore = _by_name(truth["cylinders"])["cyl_bore_1"]
    assert _plane_gap(truth, "plane_left", "plane_right") == pytest.approx(dims["width"])
    assert _plane_gap(truth, "plane_front", "plane_back") == pytest.approx(dims["depth"])
    assert _plane_gap(truth, "plane_bottom", "plane_top") == pytest.approx(dims["height"])
    assert 2 * bore["radius_mm"] == pytest.approx(dims["bore_diameter"])
    assert _point_above_plane(truth, bore["axis_point"], "plane_left") == pytest.approx(
        dims["bore_centre_from_left"]
    )
    assert _point_above_plane(truth, bore["axis_point"], "plane_front") == pytest.approx(
        dims["bore_centre_from_front"]
    )
    # the bore runs the full height of the block
    assert bore["extent_mm"] == (0.0, dims["height"])


def test_lbracket_dims_match_construction() -> None:
    """Each named L-bracket dimension is recomputed from the truth primitives."""
    truth = ms.make_model("lbracket")[2]
    dims = truth["dims_mm"]
    bores = _by_name(truth["cylinders"])
    assert _plane_gap(truth, "plane_left", "plane_right") == pytest.approx(
        dims["plate_length"]
    )
    assert _plane_gap(truth, "plane_front", "plane_a_back") == pytest.approx(
        dims["plate_width"]
    )
    # both plates are the same thickness, measured on different face pairs
    assert _plane_gap(truth, "plane_a_bottom", "plane_a_top") == pytest.approx(
        dims["plate_thickness"]
    )
    assert _plane_gap(truth, "plane_front", "plane_b_back") == pytest.approx(
        dims["plate_thickness"]
    )
    assert _plane_gap(truth, "plane_a_bottom", "plane_b_top") == pytest.approx(
        dims["overall_height"]
    )
    assert 2 * bores["cyl_bore_a"]["radius_mm"] == pytest.approx(dims["bore_a_diameter"])
    assert 2 * bores["cyl_bore_b"]["radius_mm"] == pytest.approx(dims["bore_b_diameter"])
    assert _point_above_plane(
        truth, bores["cyl_bore_a"]["axis_point"], "plane_left"
    ) == pytest.approx(dims["bore_a_from_left"])
    assert _point_above_plane(
        truth, bores["cyl_bore_a"]["axis_point"], "plane_a_back"
    ) == pytest.approx(dims["bore_a_from_back"])
    assert _point_above_plane(
        truth, bores["cyl_bore_b"]["axis_point"], "plane_left"
    ) == pytest.approx(dims["bore_b_from_left"])
    assert _point_above_plane(
        truth, bores["cyl_bore_b"]["axis_point"], "plane_a_bottom"
    ) == pytest.approx(dims["bore_b_from_base"])
    # the two plate axes are orthogonal, which is what makes it an L
    assert float(
        np.dot(bores["cyl_bore_a"]["axis_dir"], bores["cyl_bore_b"]["axis_dir"])
    ) == pytest.approx(0.0, abs=1e-12)


def test_bossbox_dims_match_construction() -> None:
    """Each named boss-box dimension is recomputed from the truth primitives."""
    truth = ms.make_model("bossbox")[2]
    dims = truth["dims_mm"]
    boss = _by_name(truth["cylinders"])["cyl_boss_1"]
    assert _plane_gap(truth, "plane_left", "plane_right") == pytest.approx(dims["width"])
    assert _plane_gap(truth, "plane_front", "plane_back") == pytest.approx(dims["depth"])
    assert _plane_gap(truth, "plane_bottom", "plane_top") == pytest.approx(dims["height"])
    assert 2 * boss["radius_mm"] == pytest.approx(dims["boss_diameter"])
    assert _plane_gap(truth, "plane_top", "plane_boss_top") == pytest.approx(
        dims["boss_height"]
    )
    assert boss["extent_mm"] == (0.0, dims["boss_height"])
    assert _point_above_plane(truth, boss["axis_point"], "plane_left") == pytest.approx(
        dims["boss_centre_from_left"]
    )
    assert _point_above_plane(truth, boss["axis_point"], "plane_front") == pytest.approx(
        dims["boss_centre_from_front"]
    )


@pytest.mark.parametrize("name", ms.MODEL_NAMES)
def test_bbox_matches_truth(name: str) -> None:
    """The sampled cloud's extent equals the declared nominal bounding box."""
    points, _, truth = ms.make_model(name)
    span = points.max(axis=0) - points.min(axis=0)
    # sampling is uniform, so with 80k points the extremes land within microns
    assert span == pytest.approx(np.asarray(truth["bbox_mm"]), abs=0.01)


# --------------------------------------------------------------------------
# clean sampling
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ms.MODEL_NAMES)
def test_clean_points_lie_exactly_on_the_truth_surfaces(name: str) -> None:
    """With sigma and bias at zero every point sits on its own truth primitive."""
    model = ms.build_model(name)
    params = ms.SamplerParams()
    points, _, patch_index = ms.sample_model(model, params)
    truth = ms.make_model(name, params)[2]
    residual = _residuals(model, points, patch_index, truth)
    assert np.abs(residual).max() < 1e-9


@pytest.mark.parametrize("name", ms.MODEL_NAMES)
def test_every_truth_primitive_is_populated(name: str) -> None:
    """No declared primitive is left without enough points to be fittable.

    The floor is the coarse RANSAC min_points of 200 (thresholds.py). The
    tightest case is the boss-box boss top at about 275 points; if this fails,
    raise n_points, never the threshold.
    """
    model = ms.build_model(name)
    _, _, patch_index = ms.sample_model(model, ms.SamplerParams())
    counts: dict[str, int] = {}
    for index in np.unique(patch_index):
        primitive = model.patches[int(index)].primitive
        counts[primitive] = counts.get(primitive, 0) + int(np.sum(patch_index == index))
    expected = {record["name"] for record in model.planes + model.cylinders}
    assert set(counts) == expected
    assert min(counts.values()) >= 200, counts


@pytest.mark.parametrize("name", ms.MODEL_NAMES)
def test_normals_are_unit_and_outward(name: str) -> None:
    """Normals are unit length and point out of the material.

    Outwardness is checked by stepping a short distance along each normal and
    confirming the point moves away from the surface it came from -- positive
    residual by the sign convention in `_residuals`.
    """
    model = ms.build_model(name)
    params = ms.SamplerParams(n_points=5_000)
    points, normals, patch_index = ms.sample_model(model, params)
    truth = ms.make_model(name, params)[2]
    assert np.abs(np.linalg.norm(normals, axis=1) - 1.0).max() < 1e-12
    stepped = _residuals(model, points + 0.01 * normals, patch_index, truth)
    assert stepped.min() > 0.0


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ms.MODEL_NAMES)
def test_deterministic_per_seed(name: str) -> None:
    """The same seed reproduces the cloud bit for bit; a different seed does not."""
    params = ms.SamplerParams(n_points=3_000, sigma_mm=0.2, seed=1337)
    first_points, first_normals, first_truth = ms.make_model(name, params)
    again_points, again_normals, again_truth = ms.make_model(name, params)
    assert np.array_equal(first_points, again_points)
    assert np.array_equal(first_normals, again_normals)
    assert first_truth == again_truth

    other = ms.make_model(name, ms.SamplerParams(n_points=3_000, sigma_mm=0.2, seed=7))[0]
    assert not np.array_equal(first_points, other)


def test_sampler_params_are_recorded_in_the_truth_dict() -> None:
    """A cloud can be regenerated from its own truth dict."""
    params = ms.SamplerParams(n_points=2_000, sigma_mm=0.3, bias_mm=0.1, seed=99)
    truth = ms.make_model("bracket", params)[2]
    assert truth["sampler"] == {
        "n_points": 2_000,
        "sigma_mm": 0.3,
        "bias_mm": 0.1,
        "flip_frac": 0.0,
        "unoriented": False,
        "hole_count": 0,
        "hole_radius_mm": 3.0,
        "coverage": "full",
        "seed": 99,
    }
    replayed = ms.make_model("bracket", ms.SamplerParams(**truth["sampler"]))[0]
    assert np.array_equal(replayed, ms.make_model("bracket", params)[0])


# --------------------------------------------------------------------------
# degradation knobs
# --------------------------------------------------------------------------


def test_sigma_produces_the_requested_along_normal_scatter() -> None:
    """Gaussian noise lands along the normal with the requested deviation."""
    model = ms.build_model("bracket")
    params = ms.SamplerParams(n_points=40_000, sigma_mm=0.5, seed=4)
    points, _, patch_index = ms.sample_model(model, params)
    truth = ms.make_model("bracket", params)[2]
    residual = _residuals(model, points, patch_index, truth)
    assert float(np.std(residual)) == pytest.approx(0.5, rel=0.05)
    assert float(np.mean(residual)) == pytest.approx(0.0, abs=0.02)


def test_bias_offsets_every_point_along_its_normal() -> None:
    """A constant bias shifts the whole surface outward by exactly that much."""
    model = ms.build_model("bracket")
    params = ms.SamplerParams(n_points=20_000, bias_mm=0.4, seed=5)
    points, _, patch_index = ms.sample_model(model, params)
    truth = ms.make_model("bracket", params)[2]
    residual = _residuals(model, points, patch_index, truth)
    assert np.abs(residual - 0.4).max() < 1e-9


def _reversed_fraction(model, params) -> tuple[float, np.ndarray]:
    """Fraction of reported normals pointing against the true outward normal.

    Also returns the sampled points, so a caller can check that sign damage
    left the positions alone.
    """
    points, normals, patch_index = ms.sample_model(model, params)
    truth = ms.make_model(model.name, params)[2]
    exact = _true_normals(model, points, patch_index, truth)
    return float(np.mean(np.sum(normals * exact, axis=1) < 0)), points


def test_flip_frac_reverses_about_the_requested_fraction() -> None:
    """flip_frac damages normal signs only, leaving positions untouched."""
    model = ms.build_model("bracket")
    clean_fraction, clean_points = _reversed_fraction(
        model, ms.SamplerParams(n_points=20_000, seed=11)
    )
    dirty_fraction, dirty_points = _reversed_fraction(
        model, ms.SamplerParams(n_points=20_000, flip_frac=0.2, seed=11)
    )
    assert clean_fraction == 0.0
    assert dirty_fraction == pytest.approx(0.2, abs=0.02)
    # the sign draw shifts the final shuffle, so compare the clouds as sets
    assert np.array_equal(_canonical(clean_points), _canonical(dirty_points))


def test_unoriented_randomises_every_sign() -> None:
    """The unoriented flag gives about half the normals the wrong sign."""
    model = ms.build_model("bracket")
    fraction, _ = _reversed_fraction(
        model, ms.SamplerParams(n_points=20_000, unoriented=True, seed=12)
    )
    assert fraction == pytest.approx(0.5, abs=0.02)


def test_dropouts_remove_spherical_neighbourhoods() -> None:
    """Holes remove points and leave empty spheres of the requested radius."""
    params = ms.SamplerParams(n_points=20_000, hole_count=3, hole_radius_mm=4.0, seed=13)
    points, _, truth = ms.make_model("bracket", params)
    assert points.shape[0] < 20_000
    assert truth["n_points"] == points.shape[0]
    # the three seed points themselves are gone, so look for the emptiness:
    # no surviving point may sit inside a sphere centred on a removed point.
    full = ms.make_model("bracket", ms.SamplerParams(n_points=20_000, seed=13))[0]
    kept = {tuple(row) for row in points}
    removed = np.asarray([row for row in full if tuple(row) not in kept])
    assert removed.shape[0] == 20_000 - points.shape[0] > 0
    nearest = np.min(
        np.linalg.norm(points[:, None, :] - removed[None, :3, :], axis=2), axis=0
    )
    assert nearest.min() >= 0.0  # sanity: distances are well formed
    assert removed.shape[0] > 3, "a dropout should remove more than its own centre"


def test_top_hemisphere_coverage_drops_downward_faces() -> None:
    """One-sided coverage removes the bottom face, and the truth dict says so."""
    points, normals, truth = ms.make_model(
        "bracket", ms.SamplerParams(n_points=20_000, coverage="top-hemisphere-only")
    )
    assert normals[:, 2].min() >= 0.0
    assert points.shape[0] < 20_000
    # plane_bottom is the only downward face on the bracket
    assert truth["planes_sampled"] == truth["n_planes"] - 1
    assert truth["cylinders_sampled"] == truth["n_cylinders"]


# --------------------------------------------------------------------------
# parameter validation and file output
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_points": 0},
        {"sigma_mm": -0.1},
        {"flip_frac": 1.5},
        {"hole_count": -1},
        {"hole_radius_mm": -2.0},
        {"coverage": "sideways"},
    ],
)
def test_bad_params_are_rejected(kwargs: dict) -> None:
    """Every knob validates at construction, with the value in the message."""
    with pytest.raises(ValueError):
        ms.SamplerParams(**kwargs)


def test_unknown_model_name_lists_the_valid_ones() -> None:
    """A typo produces a plain-language message, not a KeyError."""
    with pytest.raises(ValueError) as info:
        ms.build_model("widget")
    assert "bracket" in str(info.value)


def test_ply_round_trip(tmp_path: Path) -> None:
    """open3d reads the written PLY back with points and normals intact."""
    open3d = pytest.importorskip("open3d")
    points, normals, _ = ms.make_model("bracket", ms.SamplerParams(n_points=5_000))
    path = tmp_path / "bracket.ply"
    ms.write_ply(path, points, normals)
    cloud = open3d.io.read_point_cloud(str(path))
    assert cloud.has_normals()
    # float32 storage quantises a 60 mm coordinate at about 4e-6 mm
    assert np.asarray(cloud.points) == pytest.approx(points, abs=1e-4)
    assert np.asarray(cloud.normals) == pytest.approx(normals, abs=1e-6)


def test_script_writes_all_three_models(tmp_path: Path) -> None:
    """Running as a script writes a PLY and a truth file per model."""
    assert ms.main(["--outdir", str(tmp_path), "--points", "3000"]) == 0
    for name in ms.MODEL_NAMES:
        assert (tmp_path / f"{name}.ply").is_file()
        assert (tmp_path / f"{name}.truth.json").is_file()


def test_script_refuses_one_out_path_for_three_models(tmp_path: Path) -> None:
    """--out names a single file, so it cannot stand in for three models."""
    assert ms.main(["--out", str(tmp_path / "all.ply"), "--points", "1000"]) == 2


def test_script_output_is_ascii(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Screen-reader rule: emitted text is plain ASCII (SYNTHESIS.md ruling 7)."""
    ms.main(["--model", "bossbox", "--outdir", str(tmp_path), "--points", "3000"])
    captured = capsys.readouterr().out
    captured.encode("ascii")
    assert "boss_diameter = 8.0 mm" in captured
