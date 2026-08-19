"""The one seam between capture and geometry (WI-7).

A GeometrySource answers a single question: what points and normals is this
run about, and where did they come from. Everything upstream of that question
-- cameras, reconstruction software, file formats -- stays on the far side of
this seam, and everything downstream sees only arrays plus a provenance string.

There are exactly two backends in the project's plan, and only the first has
code:

Production path. A mesh file produced by Apple's PhotogrammetrySession from a
still-photo capture session, reconstructed on the Mac and handed over as OBJ,
PLY, or STL in metres. That is `FileMeshSource`, and it also serves synthetic
parts written by tools/make_synthetic.py when told units="mm" and
provenance="synthetic".

Contingency slot. A sparse structure-from-motion backend using the printed mat
corners as ground-control points, specified in docs/CONTINGENCIES.md ticket 2.
It is gated on morning evidence -- a caliper audit showing the production path
misses scale -- and no code for it exists tonight. If it is ever built, it
implements this Protocol and nothing else in the pipeline changes.

There is deliberately no backend enum and no fusion hook (PLAN.md ground rule
4): the input contract is one file from one source, and a registry of
imaginary backends would be an invitation to grow legs the project has killed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from scan2cad.io_mesh import (
    DEFAULT_SAMPLE_COUNT,
    DEFAULT_SEED,
    DEFAULT_UNITS,
    PROVENANCE_MESH,
    LoadedCloud,
    SampleMethod,
    Units,
    load_cloud,
)


@runtime_checkable
class GeometrySource(Protocol):
    """Anything that can produce one scan's points, normals, and provenance."""

    def load(self) -> tuple[np.ndarray, np.ndarray, str]:
        """Return (points_mm, unit_normals, provenance).

        Implementations must return points in millimetres and unit-length
        normals, both as (N, 3) float64 arrays of equal length, and a
        provenance string the frozen data model accepts ("synthetic" or
        "photogrammetry-mesh"). Loading must be deterministic: the same source
        object loaded twice returns identical arrays.
        """
        ...


@dataclass(frozen=True)
class FileMeshSource:
    """One scan file on disk, read through `io_mesh.load_cloud`.

    Assumes `path` names a PLY, OBJ, or STL holding a single object, and that
    `units` truthfully says what its numbers mean -- the file does not record
    this and it is never inferred from the geometry. All work happens in
    `load`; constructing a source touches no disk.
    """

    path: str | Path
    units: Units = DEFAULT_UNITS
    sample_count: int = DEFAULT_SAMPLE_COUNT
    seed: int = DEFAULT_SEED
    sample_method: SampleMethod = "poisson"
    provenance: str = PROVENANCE_MESH

    def load_cloud(self) -> LoadedCloud:
        """Load the file and return the full record, including the unit sentence.

        Use this rather than `load` when the caller has to print what was
        assumed, which the report always does.
        """
        return load_cloud(
            self.path,
            units=self.units,
            sample_count=self.sample_count,
            seed=self.seed,
            sample_method=self.sample_method,
            provenance=self.provenance,
        )

    def load(self) -> tuple[np.ndarray, np.ndarray, str]:
        """Return (points_mm, unit_normals, provenance) for this file."""
        cloud = self.load_cloud()
        return cloud.points, cloud.normals, cloud.provenance
