"""Tests for the GeometrySource seam and its one concrete backend.

WI-7's acceptance is nominally the end-to-end test; these are the cheap checks
that the Protocol is satisfied, that the tuple contract holds, and that the
seam stays a seam -- one file, one source, no backend registry.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import open3d as o3d
import pytest

from scan2cad import sources
from scan2cad.io_mesh import LoadedCloud
from scan2cad.sources import FileMeshSource, GeometrySource


@pytest.fixture
def box_ply(tmp_path: Path) -> Path:
    """Write a 60 by 40 by 20 millimetre box mesh and return its path."""
    mesh = o3d.geometry.TriangleMesh.create_box(width=60.0, height=40.0, depth=20.0)
    mesh.compute_vertex_normals()
    path = tmp_path / "box.ply"
    assert o3d.io.write_triangle_mesh(str(path), mesh)
    return path


def _source(path: Path, **overrides: object) -> FileMeshSource:
    """Build a fast, fully specified FileMeshSource over `path`."""
    kwargs: dict[str, object] = dict(
        units="mm", sample_count=2000, seed=1337, sample_method="uniform"
    )
    kwargs.update(overrides)
    return FileMeshSource(path, **kwargs)  # type: ignore[arg-type]


def test_file_mesh_source_satisfies_the_protocol(box_ply: Path) -> None:
    """The concrete backend is a GeometrySource by structure, not by inheritance."""
    assert isinstance(_source(box_ply), GeometrySource)


def test_load_returns_points_normals_provenance(box_ply: Path) -> None:
    """load() is the three-tuple the Protocol promises, in millimetres."""
    points, normals, provenance = _source(box_ply).load()

    assert points.shape == (2000, 3)
    assert normals.shape == (2000, 3)
    assert points.dtype == np.float64
    assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-9)
    assert provenance == "photogrammetry-mesh"
    extents = points.max(axis=0) - points.min(axis=0)
    assert np.allclose(extents, (60.0, 40.0, 20.0), atol=1.0)


def test_loading_twice_is_deterministic(box_ply: Path) -> None:
    """The same source object loaded twice returns identical arrays."""
    source = _source(box_ply)
    first, _, _ = source.load()
    second, _, _ = source.load()
    assert np.array_equal(first, second)


def test_load_cloud_exposes_the_unit_assumption(box_ply: Path) -> None:
    """The report needs the full record, not only the three-tuple."""
    cloud = _source(box_ply).load_cloud()

    assert isinstance(cloud, LoadedCloud)
    assert cloud.units_assumption.isascii()
    assert "millimetres" in cloud.units_assumption
    assert cloud.source_path == str(box_ply)


def test_synthetic_provenance_can_be_declared(box_ply: Path) -> None:
    """A synthetic part is labelled at the source, not guessed downstream."""
    _, _, provenance = _source(box_ply, provenance="synthetic").load()
    assert provenance == "synthetic"


def test_source_is_frozen(box_ply: Path) -> None:
    """A source cannot be mutated between describing a run and running it."""
    source = _source(box_ply)
    with pytest.raises(Exception):
        source.units = "m"  # type: ignore[misc]


def test_constructing_a_source_touches_no_disk(tmp_path: Path) -> None:
    """Construction is free; the missing file only surfaces on load()."""
    source = FileMeshSource(tmp_path / "absent.ply")
    with pytest.raises(FileNotFoundError):
        source.load()


def test_there_is_exactly_one_backend() -> None:
    """The seam stays a seam: no backend enum, no registry, no second class.

    PLAN.md ground rule 4 kills the multi-source design outright. This test is
    the tripwire: adding a second concrete source here should be a deliberate
    act that fails a test first.
    """
    concrete = [
        name
        for name, obj in vars(sources).items()
        if isinstance(obj, type)
        and obj.__module__ == sources.__name__
        and obj is not GeometrySource
    ]
    assert concrete == ["FileMeshSource"]
