"""Tests for io_mesh: loading, sampling, unit conversion, normals, determinism.

Every fixture is built here with open3d and written to a pytest tmp_path, so
the suite needs no checked-in binary assets and no other work item's module.
Sampling defaults to the cheap uniform sampler where the test only needs points
to exist; the poisson-disk default path gets its own smaller test, because it
costs roughly a second per 10k points.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import open3d as o3d
import pytest

from scan2cad.io_mesh import (
    DEFAULT_UNITS,
    LoadedCloud,
    load_cloud,
    set_seed,
)

# Box dimensions used by every fixture, in the file's own units.
BOX_MM = (60.0, 40.0, 20.0)


def _box_mesh(scale: float = 1.0) -> o3d.geometry.TriangleMesh:
    """Return a box of BOX_MM times `scale`, with vertex normals computed."""
    mesh = o3d.geometry.TriangleMesh.create_box(
        width=BOX_MM[0] * scale, height=BOX_MM[1] * scale, depth=BOX_MM[2] * scale
    )
    mesh.compute_vertex_normals()
    return mesh


def _write_mesh(tmp_path: Path, suffix: str, scale: float = 1.0) -> Path:
    """Write a box mesh to tmp_path with the given suffix and return the path."""
    path = tmp_path / f"box{suffix}"
    assert o3d.io.write_triangle_mesh(str(path), _box_mesh(scale))
    return path


def _write_point_cloud(tmp_path: Path, count: int, seed: int = 5) -> Path:
    """Write a PLY holding a bare point cloud sampled from the box mesh."""
    path = tmp_path / "cloud.ply"
    set_seed(seed)
    cloud = _box_mesh().sample_points_uniformly(number_of_points=count)
    cloud.normals = o3d.utility.Vector3dVector(np.empty((0, 3)))
    assert o3d.io.write_point_cloud(str(path), cloud)
    return path


def _extents(cloud: LoadedCloud) -> np.ndarray:
    """Return the axis-aligned bounding-box side lengths of the loaded points."""
    return cloud.points.max(axis=0) - cloud.points.min(axis=0)


@pytest.mark.parametrize("suffix", [".ply", ".obj", ".stl"])
def test_loads_every_supported_mesh_type(tmp_path: Path, suffix: str) -> None:
    """PLY, OBJ, and STL meshes all load, get sampled, and carry unit normals."""
    path = _write_mesh(tmp_path, suffix)
    cloud = load_cloud(path, units="mm", sample_count=3000, sample_method="uniform")

    assert cloud.was_mesh
    assert cloud.point_count == 3000
    assert cloud.points.shape == (3000, 3)
    assert cloud.points.dtype == np.float64
    assert cloud.normals.shape == (3000, 3)
    lengths = np.linalg.norm(cloud.normals, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-9)
    assert np.allclose(_extents(cloud), BOX_MM, atol=1.0)


def test_millimetre_file_is_not_rescaled(tmp_path: Path) -> None:
    """units='mm' leaves the coordinates alone."""
    path = _write_mesh(tmp_path, ".ply")
    cloud = load_cloud(path, units="mm", sample_count=2000, sample_method="uniform")
    assert np.allclose(_extents(cloud), BOX_MM, atol=1.0)


def test_metre_file_is_scaled_to_millimetres(tmp_path: Path) -> None:
    """A file authored in metres comes back a thousand times larger, in mm."""
    path = _write_mesh(tmp_path, ".ply", scale=1e-3)  # 0.060 x 0.040 x 0.020 m
    cloud = load_cloud(path, units="m", sample_count=2000, sample_method="uniform")
    assert np.allclose(_extents(cloud), BOX_MM, atol=1.0)


def test_default_units_are_metres() -> None:
    """Photogrammetry meshes arrive in metres, so that is the unstated default."""
    assert DEFAULT_UNITS == "m"


def test_units_assumption_is_ascii_and_states_the_unit(tmp_path: Path) -> None:
    """The report prints this sentence verbatim, so it must be plain ASCII."""
    path = _write_mesh(tmp_path, ".ply", scale=1e-3)
    cloud = load_cloud(path, units="m", sample_count=1000, sample_method="uniform")

    sentence = cloud.units_assumption
    assert sentence.isascii()
    assert "metres" in sentence
    assert "1000" in sentence
    assert "triangle mesh" in sentence
    assert sentence.endswith(".")


def test_same_seed_gives_identical_arrays(tmp_path: Path) -> None:
    """Two loads with one seed are bit-identical; the e2e gate depends on this."""
    path = _write_mesh(tmp_path, ".ply")
    kwargs = dict(units="mm", sample_count=2000, sample_method="uniform")
    first = load_cloud(path, seed=1337, **kwargs)
    second = load_cloud(path, seed=1337, **kwargs)

    assert np.array_equal(first.points, second.points)
    assert np.array_equal(first.normals, second.normals)


def test_different_seed_gives_a_different_sample(tmp_path: Path) -> None:
    """The seed really drives the sampler, rather than being ignored."""
    path = _write_mesh(tmp_path, ".ply")
    kwargs = dict(units="mm", sample_count=2000, sample_method="uniform")
    assert not np.array_equal(
        load_cloud(path, seed=1337, **kwargs).points,
        load_cloud(path, seed=99, **kwargs).points,
    )


def test_poisson_sampling_is_deterministic(tmp_path: Path) -> None:
    """The default blue-noise sampler is seeded too, not only the cheap one."""
    path = _write_mesh(tmp_path, ".ply")
    first = load_cloud(path, units="mm", sample_count=1500, seed=1337)
    second = load_cloud(path, units="mm", sample_count=1500, seed=1337)
    assert np.array_equal(first.points, second.points)


def test_point_cloud_input_is_used_whole(tmp_path: Path) -> None:
    """A PLY with no triangles loads as a cloud and keeps all of its points."""
    path = _write_point_cloud(tmp_path, count=2500)
    cloud = load_cloud(path, units="mm", sample_count=80_000)

    assert not cloud.was_mesh
    assert cloud.point_count == 2500
    assert "point cloud" in cloud.units_assumption


def test_large_point_cloud_is_subsampled_reproducibly(tmp_path: Path) -> None:
    """A cloud larger than sample_count is cut down, identically every time."""
    path = _write_point_cloud(tmp_path, count=4000)
    first = load_cloud(path, units="mm", sample_count=1200, seed=1337)
    second = load_cloud(path, units="mm", sample_count=1200, seed=1337)

    assert first.point_count == 1200
    assert np.array_equal(first.points, second.points)


def test_normals_are_consistently_oriented(tmp_path: Path) -> None:
    """Normals on one face agree with each other after orientation propagation.

    A box face is flat, so every normal sampled from it must be parallel; the
    failure this catches is per-point sign flipping, which would leave the
    fitter with a face whose normals cancel.
    """
    path = _write_mesh(tmp_path, ".ply")
    cloud = load_cloud(path, units="mm", sample_count=4000, sample_method="uniform")

    # Points within 1 mm of the z = 20 face, away from the edges.
    top = (
        (cloud.points[:, 2] > BOX_MM[2] - 1.0)
        & (cloud.points[:, 0] > 5.0)
        & (cloud.points[:, 0] < BOX_MM[0] - 5.0)
        & (cloud.points[:, 1] > 5.0)
        & (cloud.points[:, 1] < BOX_MM[1] - 5.0)
    )
    assert top.sum() > 50
    z_component = cloud.normals[top, 2]
    assert np.all(np.abs(z_component) > 0.9)
    assert np.all(np.sign(z_component) == np.sign(z_component[0]))


def test_provenance_is_carried_through(tmp_path: Path) -> None:
    """A synthetic file can be labelled as such and never looks like a scan."""
    path = _write_mesh(tmp_path, ".ply")
    cloud = load_cloud(
        path,
        units="mm",
        sample_count=1000,
        sample_method="uniform",
        provenance="synthetic",
    )
    assert cloud.provenance == "synthetic"


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """A typo in the path fails by name, not as an empty cloud."""
    with pytest.raises(FileNotFoundError, match="no such scan file"):
        load_cloud(tmp_path / "absent.ply")


def test_unsupported_suffix_is_refused(tmp_path: Path) -> None:
    """Unknown file types are named in the message, with the supported list."""
    path = tmp_path / "scan.xyz"
    path.write_text("0 0 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported scan file type"):
        load_cloud(path)


def test_unknown_units_are_refused(tmp_path: Path) -> None:
    """There is no inches path, and asking for one is an error, not a guess."""
    path = _write_mesh(tmp_path, ".ply")
    with pytest.raises(ValueError, match="unknown units"):
        load_cloud(path, units="inch")  # type: ignore[arg-type]


def test_unknown_provenance_is_refused(tmp_path: Path) -> None:
    """Provenance is limited to the two strings the frozen data model allows."""
    path = _write_mesh(tmp_path, ".ply")
    with pytest.raises(ValueError, match="unknown provenance"):
        load_cloud(path, units="mm", provenance="guessed")


def test_unknown_sample_method_is_refused(tmp_path: Path) -> None:
    """A misspelled sampler fails loudly rather than silently falling back."""
    path = _write_mesh(tmp_path, ".ply")
    with pytest.raises(ValueError, match="unknown sample method"):
        load_cloud(path, units="mm", sample_method="poison")  # type: ignore[arg-type]


def test_empty_file_is_refused(tmp_path: Path) -> None:
    """A PLY with neither triangles nor points is a plain-language error."""
    # open3d refuses to write a zero-point cloud, so the header is hand-written.
    path = tmp_path / "empty.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 0\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no triangles and no points"):
        load_cloud(path, units="mm")


def test_too_few_points_to_estimate_normals(tmp_path: Path) -> None:
    """Three points cannot carry a neighbourhood, and the message says so."""
    path = tmp_path / "tiny.ply"
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.eye(3))
    assert o3d.io.write_point_cloud(str(path), cloud)
    with pytest.raises(ValueError, match="at least 4 are needed"):
        load_cloud(path, units="mm")


def test_set_seed_returns_a_numpy_generator() -> None:
    """set_seed hands back the generator used for point-cloud subsampling."""
    rng = set_seed(1337)
    assert isinstance(rng, np.random.Generator)
    assert rng.random() == set_seed(1337).random()
