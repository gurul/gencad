"""FROZEN 2026-08-19T01:16 -- do not tune to pass the sweep.

Every number in this module was declared before any noise sweep or end-to-end
run existed. SYNTHESIS.md ruling 6 makes the freeze binding: no later agent may
edit a value here to make a test or a sweep pass. A run that fails against
these numbers is a finding to be reported honestly, not a threshold to move.

Units: millimetres for lengths, degrees for angles.

Regimes:
  coarse (default) -- angular snap 5.0 deg, dimensional snap 2.0 x per-primitive RMS
  fine             -- angular snap 1.0 deg, dimensional snap 0.5 mm

Any CLI override of these values must be echoed in the report and in the
emitted build123d script, so a reader can always tell that a run was not made
with the frozen defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

FROZEN_AT = "2026-08-19T01:16"

# Snapped lengths are rounded to this grid, and only when the rounding stays
# inside the regime's dimensional tolerance.
SNAP_ROUND_MM = 0.1

# Pre-declared end-to-end tolerance for the noise-zero CI gate: a named
# dimension passes if its error is within max(0.05 mm, 0.1 percent of nominal).
# Declared 2026-08-19, before the first run (SYNTHESIS.md ruling 6).
E2E_TOLERANCE_ABS_MM = 0.05
E2E_TOLERANCE_REL = 0.001

# Pre-declared pass criterion for the characterisation sweep: a named dimension
# passes if its error is within max(3 x sigma, 0.5 mm).
SWEEP_TOLERANCE_SIGMA_FACTOR = 3.0
SWEEP_TOLERANCE_FLOOR_MM = 0.5


@dataclass(frozen=True)
class Thresholds:
    """One frozen regime preset.

    Exactly one of `dim_snap_rms_factor` and `dim_snap_mm` is set; the other is
    None. The coarse regime scales its dimensional tolerance with the measured
    residual of each primitive, so a badly fitted feature is not snapped as
    confidently as a well fitted one. The fine regime uses a flat tolerance.
    Use `dimensional_tolerance_mm` rather than reading the fields directly.
    """

    name: str
    angular_snap_deg: float
    dim_snap_rms_factor: float | None
    dim_snap_mm: float | None
    ransac_epsilon_mm: float
    ransac_cluster_epsilon_mm: float
    ransac_normal_threshold: float
    ransac_min_points: int

    def dimensional_tolerance_mm(self, rms_mm: float) -> float:
        """Largest change a snap may make to a length, for a primitive of this RMS.

        Assumes `rms_mm` is the per-primitive residual reported by the fitter
        (non-negative). In the fine regime the argument is ignored.
        """
        if self.dim_snap_mm is not None:
            return self.dim_snap_mm
        assert self.dim_snap_rms_factor is not None
        return self.dim_snap_rms_factor * max(rms_mm, 0.0)


COARSE = Thresholds(
    name="coarse",
    angular_snap_deg=5.0,
    dim_snap_rms_factor=2.0,
    dim_snap_mm=None,
    ransac_epsilon_mm=0.5,
    ransac_cluster_epsilon_mm=2.0,
    ransac_normal_threshold=0.9,
    ransac_min_points=200,
)

FINE = Thresholds(
    name="fine",
    angular_snap_deg=1.0,
    dim_snap_rms_factor=None,
    dim_snap_mm=0.5,
    ransac_epsilon_mm=0.2,
    ransac_cluster_epsilon_mm=2.0,
    ransac_normal_threshold=0.9,
    ransac_min_points=200,
)

REGIMES: dict[str, Thresholds] = {"coarse": COARSE, "fine": FINE}
DEFAULT_REGIME = "coarse"


def get_regime(name: str = DEFAULT_REGIME) -> Thresholds:
    """Return the frozen preset called `name`.

    Raises ValueError with the available names rather than KeyError, so a CLI
    typo produces a plain-language message.
    """
    try:
        return REGIMES[name]
    except KeyError:
        raise ValueError(
            f"unknown regime {name!r}; available regimes are: "
            + ", ".join(sorted(REGIMES))
        ) from None


def e2e_tolerance_mm(nominal_mm: float) -> float:
    """Noise-zero gate tolerance for a dimension whose true value is `nominal_mm`."""
    return max(E2E_TOLERANCE_ABS_MM, E2E_TOLERANCE_REL * abs(nominal_mm))


def sweep_tolerance_mm(sigma_mm: float) -> float:
    """Sweep pass tolerance at sampling noise `sigma_mm`."""
    return max(SWEEP_TOLERANCE_SIGMA_FACTOR * abs(sigma_mm), SWEEP_TOLERANCE_FLOOR_MM)
