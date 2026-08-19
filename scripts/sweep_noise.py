"""Noise characterisation sweep and degradation smoke (WI-10).

This is NOT a test. It is a characterisation run: it says how the fitting and
snapping chain behaves as synthetic noise grows, and it is allowed to fail.
Failures are written down as findings. Nothing here may be tuned to make a
number look better -- SYNTHESIS.md ruling 6 freezes every threshold this script
uses, and the script deliberately has no threshold flags at all so that there is
nothing to reach for.

    .venv/bin/python scripts/sweep_noise.py
    .venv/bin/python scripts/sweep_noise.py --degraded

Both write out/sweep_report.txt, headed by the mandatory caption. The report is
prose for a screen reader: short lines, one fact per line, no tables, ASCII only.

WHAT IS SWEPT
-------------
Three models (bracket, lbracket, bossbox) times three noise levels (sigma 0.1,
0.5 and 1.0 mm along the surface normal) times ten seeds: ninety runs.

PRE-DECLARED PASS CRITERION (PLAN.md WI-10, not tunable)
--------------------------------------------------------
A run passes when both hold:

  1. the fit recovers exactly the number of planes and cylinders the model was
     built with, and
  2. every dimension the report prints is a real dimension of the part, and
     every dimension in the required list is found, both within
     max(3 x sigma, 0.5 mm).

DEGRADATION SMOKE (--degraded)
------------------------------
Four honest degradations at sigma 0.5 mm: one fifth of the normals flipped;
normals never consistently oriented; three spherical dropouts; and coverage
from above only. Some of these are expected to fail. That is the point: a
failure here is a finding about where the chain gives up, recorded so the
morning reader knows it, not a bug to tune away.

WHY THIS SCRIPT BYPASSES io_mesh
--------------------------------
`io_mesh.load_cloud` discards whatever normals a file carries and re-estimates
them from the point positions, which is right for a real scan and would quietly
erase exactly the degradations this sweep is meant to measure: a flipped or
unoriented normal would be recomputed into a clean one. So the sweep hands the
generator's own points and normals straight to the fitter. The file-reading and
normal-estimation path is covered instead by the noise-zero gate,
tests/test_e2e_noise0.py, which runs the real command line on a real PLY.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from scan2cad.frame import FrameError, align_and_snap  # noqa: E402
from scan2cad.ransac_cgal import FitError, fit_primitives  # noqa: E402
from scan2cad.report import render_report  # noqa: E402
from scan2cad.thresholds import (  # noqa: E402
    COARSE,
    SWEEP_TOLERANCE_FLOOR_MM,
    SWEEP_TOLERANCE_SIGMA_FACTOR,
    sweep_tolerance_mm,
)

GENERATOR = REPO_ROOT / "tools" / "make_synthetic.py"
DEFAULT_REPORT = REPO_ROOT / "out" / "sweep_report.txt"
# The degradation smoke gets its own file: it answers a different question, and
# overwriting the sweep report with it would lose the noise numbers.
DEFAULT_DEGRADED_REPORT = REPO_ROOT / "out" / "sweep_report_degraded.txt"

# The caption is mandatory and verbatim (PLAN.md WI-10). It heads the report and
# must not be softened, shortened, or moved below the numbers.
CAPTION = (
    "PLUMBING VERIFICATION ONLY -- synthetic noise model; "
    "NOT predictive of iPhone accuracy."
)

MODELS = ("bracket", "lbracket", "bossbox")
SIGMAS_MM = (0.1, 0.5, 1.0)

# Ten seeds, fixed so the sweep is reproducible, and deliberately none of them
# the 1337 the noise-zero gate pins: a sweep that reused the gate's draw would
# be measuring the same cloud three times over.
SEEDS = (2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010)

POINT_COUNT = 80_000

DEGRADED_SIGMA_MM = 0.5

# Every length a report line may legitimately carry, per model, read off the
# construction geometry in tools/make_synthetic.py. Same lists as the gate uses.
TRUE_MM: dict[str, tuple[float, ...]] = {
    "bracket": (60.0, 40.0, 20.0, 12.5),
    "lbracket": (50.0, 34.0, 30.0, 26.0, 4.0, 5.0),
    "bossbox": (80.0, 50.0, 31.0, 25.0, 6.0, 8.0),
}

# The dimensions the sweep insists on finding: overall size, and every hole or
# boss. Errors are reported per entry in this list.
REQUIRED_MM: dict[str, tuple[float, ...]] = {
    "bracket": (60.0, 40.0, 20.0, 12.5),
    "lbracket": (50.0, 5.0),
    "bossbox": (80.0, 50.0, 8.0),
}

_REPORT_DIMENSION_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*) = (?P<value>[0-9]+(?:\.[0-9]+)?) mm,"
)


# ---------------------------------------------------------------------------
# one run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One degradation setting, named for the report.

    `label` is the sentence fragment the report uses. `kwargs` are passed to
    the generator's SamplerParams on top of the model, sigma and seed.
    """

    label: str
    kwargs: dict[str, object] = field(default_factory=dict)


CLEAN = Case("clean sampling")

DEGRADED_CASES = (
    Case("one fifth of normals flipped", {"flip_frac": 0.2}),
    Case("normals never consistently oriented", {"unoriented": True}),
    Case("three spherical dropouts", {"hole_count": 3, "hole_radius_mm": 3.0}),
    Case("coverage from above only", {"coverage": "top-hemisphere-only"}),
)


@dataclass(frozen=True)
class Outcome:
    """What one sweep run produced.

    `errors` maps each required true dimension to the smallest error any
    reported dimension had against it, or None when nothing came close enough
    to be recognisable as that dimension. `problems` holds one plain sentence
    per reason the run failed, and is empty when it passed.
    """

    model: str
    case: str
    sigma_mm: float
    seed: int
    planes: int
    cylinders: int
    true_planes: int
    true_cylinders: int
    errors: dict[float, float | None]
    problems: list[str]

    @property
    def passed(self) -> bool:
        """A run passes only when nothing went wrong; a crash is not a pass."""
        return not self.problems


def _load_generator():
    """Import tools/make_synthetic.py under the name 'make_synthetic'.

    tools/ is not a package, and the module must be registered in sys.modules
    before it executes because dataclasses resolves each frozen class's own
    module by name while building it.
    """
    spec = importlib.util.spec_from_file_location("make_synthetic", GENERATOR)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"cannot import the generator at {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report_dimensions(report: str) -> dict[str, float]:
    """Return the name-to-value map of report section 2.

    Assumes `report` is a rendered report. Only lines of the documented
    dimension shape are returned, so an ordinary sentence inside the section
    never becomes a dimension.
    """
    lines = report.splitlines()
    try:
        start = lines.index("Section 2. Dimensions.") + 1
    except ValueError:
        return {}
    values: dict[str, float] = {}
    for line in lines[start:]:
        if line.startswith("Section "):
            break
        match = _REPORT_DIMENSION_RE.match(line)
        if match is not None:
            values[match.group("name")] = float(match.group("value"))
    return values


def _count_phrase(planes: int, cylinders: int) -> str:
    """Return "6 planes and 1 cylinder", with each noun agreeing with its count."""
    plane_word = "plane" if planes == 1 else "planes"
    cylinder_word = "cylinder" if cylinders == 1 else "cylinders"
    return f"{planes} {plane_word} and {cylinders} {cylinder_word}"


def run_once(
    generator, model: str, sigma_mm: float, seed: int, case: Case
) -> Outcome:
    """Sample `model`, fit it, describe it, and judge the result.

    Assumes CGAL and the generator are importable. Never raises for a bad fit:
    a run that crashes the fitter or the frame stage is recorded as a failed run
    with the exception's own message, because "it fell over at sigma 1.0" is
    exactly the kind of finding this sweep exists to collect.
    """
    params = generator.SamplerParams(
        n_points=POINT_COUNT, sigma_mm=sigma_mm, seed=seed, **case.kwargs
    )
    points, normals, truth = generator.make_model(model, params)

    tolerance = sweep_tolerance_mm(sigma_mm)
    problems: list[str] = []
    errors: dict[float, float | None] = {t: None for t in REQUIRED_MM[model]}

    try:
        fit = fit_primitives(points, normals, thresholds=COARSE)
        scene = align_and_snap(
            fit.planes, fit.cylinders, thresholds=COARSE, provenance="synthetic"
        )
        report = render_report(
            scene, units_note="input read as millimetres", regime=COARSE
        )
    except (FitError, FrameError, ValueError, RuntimeError) as exc:
        problems.append(f"the chain stopped with: {exc}")
        return Outcome(
            model=model,
            case=case.label,
            sigma_mm=sigma_mm,
            seed=seed,
            planes=0,
            cylinders=0,
            true_planes=int(truth["n_planes"]),
            true_cylinders=int(truth["n_cylinders"]),
            errors=errors,
            problems=problems,
        )

    n_planes = len(scene.planes)
    n_cylinders = len(scene.cylinders)
    if n_planes != truth["n_planes"] or n_cylinders != truth["n_cylinders"]:
        problems.append(
            f"found {_count_phrase(n_planes, n_cylinders)}, not "
            f"{_count_phrase(int(truth['n_planes']), int(truth['n_cylinders']))}"
        )

    reported = _report_dimensions(report)
    for name, value in sorted(reported.items()):
        if not any(abs(value - t) <= tolerance for t in TRUE_MM[model]):
            problems.append(
                f"reported {name} = {value} mm, which is no dimension of the part"
            )

    for truth_mm in REQUIRED_MM[model]:
        candidates = [abs(value - truth_mm) for value in reported.values()]
        best = min(candidates) if candidates else None
        if best is not None and best <= tolerance:
            errors[truth_mm] = best
        else:
            problems.append(f"the {truth_mm} mm dimension was not recovered")

    return Outcome(
        model=model,
        case=case.label,
        sigma_mm=sigma_mm,
        seed=seed,
        planes=n_planes,
        cylinders=n_cylinders,
        true_planes=int(truth["n_planes"]),
        true_cylinders=int(truth["n_cylinders"]),
        errors=errors,
        problems=problems,
    )


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def _percentiles(values: list[float]) -> tuple[float, float, float]:
    """Return (median, 90th percentile, worst) of `values`.

    Assumes a non-empty list. The 90th percentile is the nearest-rank value,
    which on ten samples is the ninth smallest -- an honest choice for a sample
    this size, where interpolating would invent precision.
    """
    ordered = sorted(values)
    rank = max(0, math.ceil(0.9 * len(ordered)) - 1)
    return statistics.median(ordered), ordered[rank], ordered[-1]


def _method_lines(case_count: int, run_count: int) -> list[str]:
    """State what was run and under which frozen numbers, one fact per line."""
    return [
        "Method.",
        f"Models swept: {', '.join(MODELS)}.",
        f"Points sampled per run: {POINT_COUNT}.",
        f"Seeds per setting: {len(SEEDS)}, from {SEEDS[0]} to {SEEDS[-1]}.",
        f"Settings swept: {case_count}.",
        f"Runs in total: {run_count}.",
        f"Threshold regime: {COARSE.name}, taken from thresholds.py unchanged.",
        f"RANSAC epsilon: {COARSE.ransac_epsilon_mm} mm.",
        f"RANSAC cluster epsilon: {COARSE.ransac_cluster_epsilon_mm} mm.",
        f"RANSAC normal threshold: {COARSE.ransac_normal_threshold}.",
        f"RANSAC minimum points per shape: {COARSE.ransac_min_points}.",
        f"Angular snap tolerance: {COARSE.angular_snap_deg} degrees.",
        "This script accepts no threshold flags at all.",
        "So no run here can have used anything but the frozen values.",
        "Pass criterion, declared before the first run, in two parts.",
        "One: the fit finds exactly the planes and cylinders the model was built with.",
        "Two: every dimension is within "
        f"{SWEEP_TOLERANCE_SIGMA_FACTOR:.0f} times sigma or "
        f"{SWEEP_TOLERANCE_FLOOR_MM} mm, whichever is larger.",
        "The sweep hands the generator's own points and normals to the fitter.",
        "That is so the normal damage in the degradation smoke is not erased "
        "by re-estimating normals.",
        "The file reading path is covered by the noise-zero gate instead.",
        "Errors below are measured against the report's printed values.",
        "Those are rounded to one decimal place, and may already have been "
        "snapped to the nearest tenth of a millimetre.",
        "A stated error of zero therefore means agreement after that rounding, "
        "not an exact fit.",
        "CGAL's Efficient RANSAC draws from a generator this project cannot seed.",
        "The sampling is reproducible; the fit is not.",
        "Rerunning this sweep moves the pass counts by a few runs either way.",
        "Read the rates as approximate.",
        "Read a single failed run as one draw, not as a verdict.",
    ]


def _pass_rate_lines(outcomes: list[Outcome], group_by_case: bool) -> list[str]:
    """Pass rates, one line per setting, ordered so a listener can follow them.

    Assumes `outcomes` all belong to the same report. Grouped by model, then by
    noise level or degradation, whichever the caller is reporting.
    """
    lines = ["Pass rates."]
    for model in MODELS:
        subset = [o for o in outcomes if o.model == model]
        if not subset:
            continue
        keys = sorted({(o.case if group_by_case else o.sigma_mm) for o in subset},
                      key=str)
        for key in keys:
            runs = [
                o for o in subset
                if (o.case if group_by_case else o.sigma_mm) == key
            ]
            passed = sum(1 for o in runs if o.passed)
            setting = key if group_by_case else f"sigma {key} mm"
            lines.append(
                f"{model} with {setting}: {passed} of {len(runs)} runs passed, "
                f"tolerance {sweep_tolerance_mm(runs[0].sigma_mm)} mm."
            )
    return lines


def _error_lines(outcomes: list[Outcome], group_by_case: bool) -> list[str]:
    """Per-dimension error percentiles, in millimetres, one line per dimension."""
    lines = ["Dimension errors."]
    for model in MODELS:
        subset = [o for o in outcomes if o.model == model]
        if not subset:
            continue
        keys = sorted({(o.case if group_by_case else o.sigma_mm) for o in subset},
                      key=str)
        for key in keys:
            runs = [
                o for o in subset
                if (o.case if group_by_case else o.sigma_mm) == key
            ]
            setting = key if group_by_case else f"sigma {key} mm"
            for truth_mm in REQUIRED_MM[model]:
                measured = [
                    o.errors[truth_mm] for o in runs if o.errors[truth_mm] is not None
                ]
                if not measured:
                    lines.append(
                        f"{model} with {setting}, the {truth_mm} mm dimension: "
                        f"not recovered in any of the {len(runs)} runs."
                    )
                    continue
                median, p90, worst = _percentiles([m for m in measured if m is not None])
                lines.append(
                    f"{model} with {setting}, the {truth_mm} mm dimension: "
                    f"median error {median:.3f} mm, "
                    f"ninetieth percentile {p90:.3f} mm, "
                    f"worst {worst:.3f} mm, "
                    f"recovered in {len(measured)} of {len(runs)} runs."
                )
    return lines


def _failure_lines(outcomes: list[Outcome]) -> list[str]:
    """Every failed run, named, with its reasons. Nothing is summarised away."""
    failures = [o for o in outcomes if not o.passed]
    if not failures:
        return ["Failures.", "None. Every run met the pass criterion."]
    lines = ["Failures.", f"{len(failures)} of {len(outcomes)} runs failed."]
    for outcome in failures:
        for problem in outcome.problems:
            lines.append(
                f"{outcome.model}, {outcome.case}, sigma {outcome.sigma_mm} mm, "
                f"seed {outcome.seed}: {problem}."
            )
    return lines


_CAVEATS = (
    "Caveats.",
    CAPTION,
    "These numbers describe code behaviour on manufactured point clouds.",
    "Those clouds have exact geometry and independent noise.",
    "A real phone scan has correlated error and missing surfaces.",
    "Its scale may be wrong outright. None of that is modelled here, on purpose.",
    "No accuracy claim of the form plus or minus X millimetres follows from this.",
    "Degraded-mesh failures above are findings, not bugs that were tuned away.",
    "Every dimension this tool produces is a draft.",
    "It stays a draft until a caliper or a datasheet overwrites it.",
)


def build_report(outcomes: list[Outcome], degraded: bool) -> str:
    """Assemble the sweep report as ASCII prose for a screen reader.

    Assumes `outcomes` is the full set of runs. The caption comes first, before
    any number, so that a listener cannot hear a pass rate without first hearing
    what it does and does not mean.
    """
    case_count = len(DEGRADED_CASES) * len(MODELS) if degraded else len(SIGMAS_MM) * len(MODELS)
    lines: list[str] = [
        CAPTION,
        "",
        "scan2cad noise sweep report.",
        "Degradation smoke run." if degraded else "Noise sweep run.",
        "",
    ]
    lines += _method_lines(case_count, len(outcomes))
    lines.append("")
    lines += _pass_rate_lines(outcomes, group_by_case=degraded)
    lines.append("")
    lines += _error_lines(outcomes, group_by_case=degraded)
    lines.append("")
    lines += _failure_lines(outcomes)
    lines.append("")
    lines += list(_CAVEATS)
    text = "\n".join(lines) + "\n"
    if not text.isascii():  # pragma: no cover - guards the screen-reader rule
        raise RuntimeError("the sweep report contains a non-ASCII character")
    return text


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser.

    There is no flag here that changes a threshold, and there must never be one:
    a characterisation run whose tolerances can be dialled from the command line
    characterises nothing.
    """
    parser = argparse.ArgumentParser(
        prog="sweep_noise.py",
        description=(
            "Characterise the scan2cad chain against synthetic noise. Writes "
            "out/sweep_report.txt. Not a test: failures are findings."
        ),
    )
    parser.add_argument(
        "--degraded",
        action="store_true",
        help=(
            "run the degradation smoke instead of the noise sweep: flipped "
            "normals, unoriented normals, dropouts and top-only coverage, all "
            f"at sigma {DEGRADED_SIGMA_MM} mm"
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            f"where to write the report (default: {DEFAULT_REPORT}, or "
            f"{DEFAULT_DEGRADED_REPORT} with --degraded)"
        ),
    )
    return parser


def _settings(degraded: bool) -> list[tuple[str, float, Case]]:
    """Return every (model, sigma, case) the requested run covers, in order."""
    if degraded:
        return [
            (model, DEGRADED_SIGMA_MM, case)
            for model in MODELS
            for case in DEGRADED_CASES
        ]
    return [(model, sigma, CLEAN) for model in MODELS for sigma in SIGMAS_MM]


def main(argv: list[str] | None = None) -> int:
    """Run the sweep and write the report. Returns 0 even when runs failed.

    A failing run is a finding, not a broken script, so the exit code reports
    whether the sweep completed, not whether the chain looked good. Progress is
    printed to stderr as it goes, because ninety fits take minutes and silence
    is indistinguishable from a hang.
    """
    args = _build_parser().parse_args(argv)
    generator = _load_generator()

    outcomes: list[Outcome] = []
    settings = _settings(args.degraded)
    total = len(settings) * len(SEEDS)
    done = 0
    for model, sigma, case in settings:
        for seed in SEEDS:
            outcomes.append(run_once(generator, model, sigma, seed, case))
            done += 1
            print(
                f"[{done} of {total}] {model}, {case.label}, sigma {sigma} mm, "
                f"seed {seed}: {'pass' if outcomes[-1].passed else 'FAIL'}",
                file=sys.stderr,
                flush=True,
            )

    report = build_report(outcomes, args.degraded)
    if args.out is not None:
        destination = Path(args.out)
    else:
        destination = DEFAULT_DEGRADED_REPORT if args.degraded else DEFAULT_REPORT
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="ascii")

    passed = sum(1 for o in outcomes if o.passed)
    print(f"Wrote {destination}.")
    print(f"{passed} of {len(outcomes)} runs met the pass criterion.")
    print(CAPTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
