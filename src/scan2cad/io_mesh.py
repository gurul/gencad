"""Mesh and point-cloud loading, sampling, and normal estimation (WI-2).

The input contract is single-source (PLAN.md ground rule 4): exactly one
mesh-or-point-cloud file, of photogrammetry or synthetic provenance. There is
no source enum, no depth-sensor leg, and no fusion hook. open3d is used here
purely as a mesh utility library.

What this module produces is the only thing the fitting stage ever sees: an
(N, 3) float64 array of points in MILLIMETRES and a matching (N, 3) array of
unit normals, plus a plain sentence recording which unit assumption was made.
That sentence is not decoration -- a photogrammetry mesh arrives in metres and
a synthetic part arrives in millimetres, the file itself never says which, and
a silent factor-of-1000 error is the single most expensive mistake this
pipeline can make. The report prints the assumption every time.

Determinism: every random step is seeded explicitly. `open3d`'s samplers draw
from a library-global generator, so `set_seed` seeds that generator as well as
the numpy generator used for point-cloud subsampling. Two runs of `load_cloud`
with the same file, the same seed, and the same arguments return bit-identical
arrays; this is relied on by the noise-zero end-to-end gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import open3d as o3d

# File types open3d can read for us. Anything else is refused by name rather
# than handed to open3d, which reports an unreadable file as an empty one.
SUPPORTED_SUFFIXES = (".ply", ".obj", ".stl")

# Sampling and normal-estimation constants (PLAN.md WI-2).
DEFAULT_SAMPLE_COUNT = 80_000
DEFAULT_SEED = 1337
NORMAL_RADIUS_NN_FACTOR = 4.0  # search radius = 4 x median nearest-neighbour distance
NORMAL_MAX_NN = 30  # cap on neighbours per hybrid KDTree query
ORIENT_K = 30  # k for orient_normals_consistent_tangent_plane

# Millimetres per unit of the named input unit.
_UNIT_SCALE_MM: dict[str, float] = {"mm": 1.0, "m": 1000.0}

# Photogrammetry meshes arrive metric-scaled in metres, so a file with no other
# information is assumed to be in metres. Synthetic parts are authored in
# millimetres and their caller passes units="mm" explicitly.
DEFAULT_UNITS = "m"

Units = Literal["mm", "m"]
SampleMethod = Literal["poisson", "uniform"]

# Provenance strings allowed by the frozen data model (primitives.SceneModel).
PROVENANCE_MESH = "photogrammetry-mesh"
PROVENANCE_SYNTHETIC = "synthetic"
_ALLOWED_PROVENANCE = (PROVENANCE_MESH, PROVENANCE_SYNTHETIC)

# A normal whose length differs from 1 by more than this is a bug, not noise.
_UNIT_TOL = 1e-6


@dataclass(frozen=True)
class LoadedCloud:
    """One loaded scan, converted to millimetres and carrying unit normals.

    Assumes `points` and `normals` are (N, 3) float64 arrays of the same
    length, that every row of `normals` is unit length, and that `points` is
    already in millimetres. `units_assumption` is a finished sentence written
    for a screen reader; the report prints it verbatim and must not reword it.

    The arrays are plain numpy and are not copied on access: treat them as
    read-only, as every stage downstream does.
    """

    points: np.ndarray
    normals: np.ndarray
    provenance: str
    units_assumption: str
    source_path: str
    was_mesh: bool

    @property
    def point_count(self) -> int:
        """Number of points in the cloud."""
        return int(self.points.shape[0])


def set_seed(seed: int) -> np.random.Generator:
    """Seed open3d's global generator and return a fresh numpy generator.

    Assumes `seed` is a non-negative int. open3d's point samplers have no
    per-call seed argument in 0.19, so seeding the library-global generator
    immediately before sampling is the only way to make sampling repeatable.
    Call this before any open3d sampling call, not once at import time.
    """
    o3d.utility.random.seed(int(seed))
    return np.random.default_rng(int(seed))


def _resolve_input(path: str | Path) -> Path:
    """Return `path` as a Path, checked for existence and a supported suffix.

    Raises FileNotFoundError or ValueError with a plain-language message; both
    messages are ASCII so the CLI can print them to a screen reader unchanged.
    """
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise FileNotFoundError(f"no such scan file: {resolved}")
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported scan file type {suffix or '(none)'}; "
            "supported types are " + ", ".join(SUPPORTED_SUFFIXES)
        )
    return resolved


def _read_geometry(path: Path) -> tuple[o3d.geometry.PointCloud | None, o3d.geometry.TriangleMesh | None]:
    """Read `path` as a triangle mesh if it has faces, else as a point cloud.

    Assumes the suffix has already been checked. A PLY may hold either a mesh
    or a bare cloud and the extension does not distinguish them, so the mesh
    reader runs first and its result is rejected when it has no triangles.
    Returns exactly one non-None member of the pair.
    """
    mesh = o3d.io.read_triangle_mesh(str(path))
    if len(mesh.triangles) > 0:
        return None, mesh

    cloud = o3d.io.read_point_cloud(str(path))
    if len(cloud.points) == 0:
        raise ValueError(
            f"scan file contains no triangles and no points: {path}. "
            "The file may be empty or written in a variant open3d cannot read."
        )
    return cloud, None


def _sample_mesh(
    mesh: o3d.geometry.TriangleMesh,
    sample_count: int,
    seed: int,
    method: SampleMethod,
) -> o3d.geometry.PointCloud:
    """Sample `sample_count` points from `mesh` reproducibly.

    Assumes `mesh` has at least one triangle. "poisson" gives blue-noise
    coverage, which is what the fitter wants because it makes inlier counts
    proportional to area rather than to triangle density; it costs roughly a
    second per 10k points. "uniform" is the cheap alternative used where the
    sample only has to exist, such as unit tests.
    """
    if sample_count < 1:
        raise ValueError(f"sample_count must be at least 1, got {sample_count}")
    set_seed(seed)
    if method == "poisson":
        return mesh.sample_points_poisson_disk(number_of_points=sample_count)
    if method == "uniform":
        return mesh.sample_points_uniformly(number_of_points=sample_count)
    raise ValueError(
        f"unknown sample method {method!r}; expected 'poisson' or 'uniform'"
    )


def _subsample_cloud(
    cloud: o3d.geometry.PointCloud, sample_count: int, seed: int
) -> o3d.geometry.PointCloud:
    """Take a reproducible random subset of `sample_count` points from `cloud`.

    Assumes len(cloud.points) > sample_count. Used only for point-cloud inputs:
    a dense photogrammetry export can carry millions of points, and the fitter's
    cost is superlinear in point count. The subset is drawn without replacement
    from a numpy generator seeded with `seed`, and the indices are sorted so the
    output preserves the file's point order.
    """
    rng = np.random.default_rng(int(seed))
    total = len(cloud.points)
    keep = np.sort(rng.choice(total, size=sample_count, replace=False))
    return cloud.select_by_index(keep.tolist())


def _median_nn_distance(cloud: o3d.geometry.PointCloud) -> float:
    """Median nearest-neighbour distance of `cloud`, in the cloud's own units.

    Assumes the cloud has at least two points. Duplicated points give a zero
    median; in that case the value is replaced by a small fraction of the
    bounding-box diagonal so the normal search radius stays positive. That
    fallback is deliberate and rare -- a zero median means the file is mostly
    duplicate vertices, which the caller will see in the fit residuals anyway.
    """
    distances = np.asarray(cloud.compute_nearest_neighbor_distance(), dtype=np.float64)
    finite = distances[np.isfinite(distances) & (distances > 0.0)]
    if finite.size > 0:
        return float(np.median(finite))

    diagonal = float(np.linalg.norm(cloud.get_max_bound() - cloud.get_min_bound()))
    if diagonal <= 0.0:
        raise ValueError(
            "scan file has zero extent: every point is at the same position"
        )
    return diagonal * 1e-3


def estimate_and_orient_normals(cloud: o3d.geometry.PointCloud) -> float:
    """Estimate and consistently orient the normals of `cloud`, in place.

    Assumes `cloud` holds at least four points, already in millimetres. Any
    normals already on the cloud are discarded and recomputed, so that a mesh
    sample and a bare point cloud reach the fitter through the same path with
    the same neighbourhood definition.

    The hybrid KDTree radius is `NORMAL_RADIUS_NN_FACTOR` times the median
    nearest-neighbour distance, which scales the neighbourhood to the actual
    sampling density instead of to an absolute size guessed in advance.
    Orientation is propagated over a Riemannian graph so that normals on one
    surface agree with each other; this makes inside and outside meaningful for
    a closed scan but does not guarantee outward-facing normals on an open one.

    Returns the search radius used, in millimetres, for the report.
    """
    count = len(cloud.points)
    if count < 4:
        raise ValueError(
            f"scan has only {count} points; at least 4 are needed to estimate normals"
        )

    cloud.normals = o3d.utility.Vector3dVector(np.empty((0, 3), dtype=np.float64))
    radius_mm = NORMAL_RADIUS_NN_FACTOR * _median_nn_distance(cloud)
    cloud.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=radius_mm, max_nn=NORMAL_MAX_NN
        ),
        fast_normal_computation=False,
    )
    # k must stay below the point count; tiny clouds appear only in unit tests.
    cloud.orient_normals_consistent_tangent_plane(k=min(ORIENT_K, count - 1))
    cloud.normalize_normals()
    return radius_mm


def _as_arrays(cloud: o3d.geometry.PointCloud) -> tuple[np.ndarray, np.ndarray]:
    """Return (points, normals) as C-contiguous float64 arrays, normals checked.

    Assumes `cloud` has had its normals estimated. Raises ValueError if any
    normal is not unit length, because a downstream PlaneFit or CylinderFit
    would reject it far from the code that produced it.
    """
    points = np.ascontiguousarray(np.asarray(cloud.points, dtype=np.float64))
    normals = np.ascontiguousarray(np.asarray(cloud.normals, dtype=np.float64))
    if normals.shape != points.shape:
        raise ValueError(
            f"normal count {normals.shape[0]} does not match point count {points.shape[0]}"
        )
    lengths = np.linalg.norm(normals, axis=1)
    if not np.all(np.isfinite(lengths)) or np.max(np.abs(lengths - 1.0)) > _UNIT_TOL:
        raise ValueError(
            "normal estimation produced a non-unit normal; the scan may contain "
            "duplicate or non-finite points"
        )
    return points, normals


def _units_sentence(
    units: Units, was_mesh: bool, source_path: Path, sample_count: int | None
) -> str:
    """Build the ASCII sentence describing what was assumed about this file.

    Assumes `units` is already validated. One fact per clause and no symbols,
    per the screen-reader rule (SYNTHESIS.md ruling 7).
    """
    unit_word = "metres" if units == "m" else "millimetres"
    opening = f"Input file {source_path.name} was read as {unit_word}"
    if units == "m":
        opening += ", then multiplied by 1000 to give millimetres"
    parts = [opening]
    if was_mesh:
        parts.append(f"It is a triangle mesh, sampled to {sample_count} points")
    else:
        parts.append("It is a point cloud, used as supplied")
    parts.append("Normals were estimated and oriented by scan2cad")
    return ". ".join(parts) + "."


def load_cloud(
    path: str | Path,
    *,
    units: Units = DEFAULT_UNITS,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    seed: int = DEFAULT_SEED,
    sample_method: SampleMethod = "poisson",
    provenance: str = PROVENANCE_MESH,
) -> LoadedCloud:
    """Load a PLY, OBJ, or STL scan and return points and normals in millimetres.

    Assumes `path` names one file holding a single object. Meshes are sampled to
    `sample_count` points; point clouds are used whole, or reproducibly
    subsampled to `sample_count` when they are larger than that. `units` says
    what the file's numbers mean and is never guessed from the geometry -- a
    60 mm bracket and a 60 m building are indistinguishable to a reader of raw
    coordinates, so the caller decides and the report says so out loud.

    `seed` makes the whole call reproducible. `provenance` must be one of the
    two strings the frozen data model allows; pass "synthetic" when the file was
    written by tools/make_synthetic.py, so that no synthetic result can later be
    mistaken for evidence about real capture accuracy.

    Raises FileNotFoundError for a missing file and ValueError for an
    unsupported type, an unreadable or empty file, a bad unit or provenance
    name, or a cloud too small or too degenerate to carry normals.
    """
    if units not in _UNIT_SCALE_MM:
        raise ValueError(
            f"unknown units {units!r}; expected one of " + ", ".join(_UNIT_SCALE_MM)
        )
    if provenance not in _ALLOWED_PROVENANCE:
        raise ValueError(
            f"unknown provenance {provenance!r}; expected one of "
            + ", ".join(_ALLOWED_PROVENANCE)
        )

    resolved = _resolve_input(path)
    cloud, mesh = _read_geometry(resolved)
    was_mesh = mesh is not None

    if mesh is not None:
        cloud = _sample_mesh(mesh, sample_count, seed, sample_method)
    else:
        assert cloud is not None
        if len(cloud.points) > sample_count:
            cloud = _subsample_cloud(cloud, sample_count, seed)

    # Scale before estimating normals so that the search radius, and every
    # residual computed from these points later, is already in millimetres.
    scale = _UNIT_SCALE_MM[units]
    if scale != 1.0:
        cloud.scale(scale, center=np.zeros(3))

    estimate_and_orient_normals(cloud)
    points, normals = _as_arrays(cloud)

    return LoadedCloud(
        points=points,
        normals=normals,
        provenance=provenance,
        units_assumption=_units_sentence(
            units, was_mesh, resolved, sample_count if was_mesh else None
        ),
        source_path=str(resolved),
        was_mesh=was_mesh,
    )
