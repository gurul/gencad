"""THE CI GATE: the whole chain on noiseless synthetic parts (WI-10).

This is the one test the night is not allowed to drop (PLAN.md section 8). It
runs the real command line as a subprocess -- `scan2cad draft INPUT -o
skeleton.py --step ref.step` -- on all three synthetic models at sigma zero and
pinned seed 1337, and checks every link in the chain:

  make_synthetic -> PLY -> io_mesh -> ransac_cgal -> frame -> report
                                                          -> emit_build123d
                                                          -> build123d -> STEP

THE TOLERANCE, PRE-DECLARED
---------------------------
A named dimension passes when its error against the construction truth is
within `max(0.05 mm, 0.1 percent of the true value)`. That number was written
into `thresholds.py` (`e2e_tolerance_mm`) before any end-to-end run existed and
is binding: SYNTHESIS.md ruling 6 forbids moving it to make this file green. A
dimension outside it is a finding to report, not a threshold to tune.

Both the raw fitted value and the snapped value must clear the tolerance. If
only the snapped value were checked, snapping could hide a bad fit by rounding
it onto the right answer.

WHAT IS AND IS NOT A NAMED DIMENSION
------------------------------------
The named dimensions of the part are the lines of report section 2 and the
`gap_*`, `*_diameter` and `*_length` entries of the emitted skeleton's NAMED
DIMENSIONS block. The `plane_*_width` and `plane_*_height` entries are not:
the emitter labels them "observed footprint across the plane, not a part
dimension", because a face's footprint is what the scan happened to cover.
`plane_*_normal` and `cylinder_*_axis` are angles in degrees, checked by the
frame tests, not lengths.

Dimensions are matched against the truth as a SET, not by name. The fitted
frame is the object's own, recovered from its largest faces, so which physical
gap the report calls "width" depends on which face won; asserting names would
be asserting an accident. Two things are asserted instead, and together they
are stronger than name matching:

  soundness     every dimension the report emits is a real dimension of the
                part, within tolerance. No invented numbers.
  completeness  every dimension in REQUIRED_MM is found by some reported
                dimension. Nothing important is silently missing.

Report values are printed to one decimal. Every true value in this file is a
multiple of 0.1 mm, so rounding a correct fit lands exactly on the truth and
cannot manufacture a pass or a failure; the full-precision check runs against
the skeleton's raw `fitted` numbers anyway.

RUNTIME
-------
Three subprocess runs over 80,000-point clouds, each of which also executes its
own emitted skeleton in a second subprocess. Budget two to five minutes for
this file. It is a gate, not a unit test.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scan2cad.report import DIMENSION_LINE_RE
from scan2cad.thresholds import E2E_TOLERANCE_ABS_MM, E2E_TOLERANCE_REL, e2e_tolerance_mm

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "tools" / "make_synthetic.py"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_step_freecad.py"

# Pinned by PLAN.md WI-10. Changing either of these changes what the gate is.
GATE_SEED = 1337
GATE_POINTS = 80_000
GATE_SIGMA_MM = 0.0

MODELS = ("bracket", "lbracket", "bossbox")

# Every length a section 2 line may legitimately report, per model, taken from
# the construction geometry in tools/make_synthetic.py.
#
# bracket   60 x 40 x 20 block, 12.5 mm bore through the 20 mm height.
# lbracket  50 mm long; base plate 30 mm wide and 4 mm thick; upright 30 mm
#           tall, so 34 mm overall and 26 mm between the upright's back face
#           and the base plate's back face; two 5 mm bores through 4 mm plate.
# bossbox   80 x 50 x 25 shell, 8 mm boss 6 mm tall, so 31 mm over the boss.
#
# A face-gap dimension is the distance between some pair of parallel faces, and
# every such pair on these parts is listed. A cylinder contributes its diameter
# and the axial span of its surface.
TRUE_MM: dict[str, tuple[float, ...]] = {
    "bracket": (60.0, 40.0, 20.0, 12.5),
    "lbracket": (50.0, 34.0, 30.0, 26.0, 4.0, 5.0),
    "bossbox": (80.0, 50.0, 31.0, 25.0, 6.0, 8.0),
}

# Dimensions the gate insists on finding. These are the ones a person would ask
# for first: the overall size of the part and the size of every hole or boss.
REQUIRED_MM: dict[str, tuple[float, ...]] = {
    "bracket": (60.0, 40.0, 20.0, 12.5),
    "lbracket": (50.0, 5.0),
    "bossbox": (80.0, 50.0, 8.0),
}

# Skeleton NAMED DIMENSIONS entries that are lengths of the part itself.
_PART_DIMENSION_SUFFIXES = ("_diameter", "_length")
_PART_DIMENSION_PREFIX = "gap_"

_NAMED_DIMENSION_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*) = (?P<value>-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)"
    r"\s+#\s+(?P<comment>.*)$"
)
_FITTED_RE = re.compile(
    r"fitted (?P<raw>-?[0-9.eE+-]+), snapped (?P<snapped>-?[0-9.eE+-]+)"
)
_REPORT_DIMENSION_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*) = (?P<value>[0-9]+(?:\.[0-9]+)?) mm,"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load_generator():
    """Import tools/make_synthetic.py under the name 'make_synthetic'.

    tools/ is not a package. The module must be registered in sys.modules
    before it executes, because dataclasses looks its own module up by name
    while building each frozen class.
    """
    spec = importlib.util.spec_from_file_location("make_synthetic", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_step_checker():
    """Import scripts/check_step_freecad.py by path, for its `check_step`.

    scripts/ is not a package, and the module must be in sys.modules before it
    executes: it defines a frozen dataclass, and dataclasses resolves the
    class's own module by name while building it.
    """
    spec = importlib.util.spec_from_file_location("check_step_freecad", CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cli_command() -> list[str]:
    """Return the argv prefix that runs the installed command line.

    Prefers the console script next to the running interpreter, which is what a
    user types, and falls back to running the module, which works in a venv
    where the package is on the path but not installed.
    """
    console = Path(sys.executable).with_name("scan2cad")
    if console.is_file():
        return [str(console)]
    return [sys.executable, "-m", "scan2cad.cli"]


def _requires_wheels() -> None:
    """Skip when the heavy wheels are absent; the gate needs the real chain."""
    pytest.importorskip("open3d", reason="the end-to-end gate needs open3d")
    pytest.importorskip("CGAL.CGAL_Shape_detection", reason="the gate needs CGAL")
    pytest.importorskip("build123d", reason="the gate needs build123d")


def _within_tolerance(value: float, truth: float) -> bool:
    """True when `value` matches `truth` inside the pre-declared gate tolerance."""
    return abs(value - truth) <= e2e_tolerance_mm(truth)


def _matching_truth(value: float, truths: tuple[float, ...]) -> float | None:
    """Return the true dimension `value` matches, or None if it matches none."""
    for truth in truths:
        if _within_tolerance(value, truth):
            return truth
    return None


def _report_dimensions(report: str) -> dict[str, float]:
    """Return the name-to-value map of report section 2.

    Assumes `report` is a full rendered report. Section 2 runs from its heading
    to the next heading; only lines of the documented dimension shape are
    returned, so a stray sentence in the section does not become a dimension.
    """
    lines = report.splitlines()
    try:
        start = lines.index("Section 2. Dimensions.") + 1
    except ValueError:  # pragma: no cover - a report without dimensions
        return {}
    values: dict[str, float] = {}
    for line in lines[start:]:
        if line.startswith("Section "):
            break
        match = _REPORT_DIMENSION_RE.match(line)
        if match is not None:
            values[match.group("name")] = float(match.group("value"))
    return values


@dataclass(frozen=True)
class _NamedDimension:
    """One NAMED DIMENSIONS entry of an emitted skeleton.

    `assigned` is the number bound to the Python name -- the snapped value the
    user will edit. `raw` is the value the fit actually produced, recovered from
    the comment, and is None for an entry the emitter did not snap (a cylinder's
    axial span, for instance, is reported as observed).
    """

    name: str
    assigned: float
    raw: float | None


def _named_dimensions(skeleton: str) -> list[_NamedDimension]:
    """Return the part-length entries of a skeleton's NAMED DIMENSIONS block.

    Assumes `skeleton` is the text of an emitted script. Footprint entries
    (`plane_*_width`, `plane_*_height`) are excluded: the emitter itself marks
    them "not a part dimension". Angle entries are excluded because they are
    degrees, not millimetres.
    """
    found: list[_NamedDimension] = []
    for line in skeleton.splitlines():
        match = _NAMED_DIMENSION_RE.match(line)
        if match is None:
            continue
        name = match.group("name")
        is_part_dimension = name.startswith(_PART_DIMENSION_PREFIX) or name.endswith(
            _PART_DIMENSION_SUFFIXES
        )
        if not is_part_dimension:
            continue
        if "not a part dimension" in match.group("comment"):
            continue
        fitted = _FITTED_RE.search(match.group("comment"))
        found.append(
            _NamedDimension(
                name=name,
                assigned=float(match.group("value")),
                raw=float(fitted.group("raw")) if fitted is not None else None,
            )
        )
    return found


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateRun:
    """Everything one `scan2cad draft --step` run produced, for the assertions."""

    model: str
    truth: dict
    stdout: str
    report: str
    skeleton: str
    step_path: Path


def _run_gate(model: str, workspace: Path) -> GateRun:
    """Generate `model` at sigma zero and drive the whole chain through the CLI.

    Assumes the heavy wheels are importable. The cloud is written to a real PLY
    first, so the gate exercises the file reader and the unit assumption rather
    than handing arrays straight to the fitter.

    Raises AssertionError with the command's own stderr when the CLI exits
    non-zero, because a gate that fails silently is worse than no gate.
    """
    generator = _load_generator()
    params = generator.SamplerParams(
        n_points=GATE_POINTS, sigma_mm=GATE_SIGMA_MM, seed=GATE_SEED
    )
    points, normals, truth = generator.make_model(model, params)

    ply = workspace / f"{model}.ply"
    generator.write_ply(ply, points, normals)
    (workspace / f"{model}.truth.json").write_text(
        json.dumps(truth, indent=2) + "\n", encoding="ascii"
    )

    skeleton_path = workspace / f"{model}_skeleton.py"
    step_path = workspace / f"{model}_ref.step"
    completed = subprocess.run(
        _cli_command()
        + [
            "draft",
            str(ply),
            "--provenance",
            "synthetic",
            "--units",
            "mm",
            "--seed",
            str(GATE_SEED),
            "--points",
            str(GATE_POINTS),
            "-o",
            str(skeleton_path),
            "--step",
            str(step_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"scan2cad draft failed on {model} with exit code "
        f"{completed.returncode}:\n{completed.stderr}"
    )
    stdout = completed.stdout
    report = stdout.split("\nSkeleton written to ")[0]
    return GateRun(
        model=model,
        truth=truth,
        stdout=stdout,
        report=report,
        skeleton=skeleton_path.read_text(encoding="ascii"),
        step_path=step_path,
    )


@pytest.fixture(scope="module")
def gate_runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, GateRun]:
    """Run the chain once per model and share the results across the assertions.

    Module scoped because each run costs a minute; the assertions below are
    read-only views of the same three runs, so re-running per test would triple
    the gate's cost without testing anything new.
    """
    _requires_wheels()
    workspace = tmp_path_factory.mktemp("e2e_noise0")
    return {model: _run_gate(model, workspace) for model in MODELS}


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def test_the_declared_tolerance_is_the_frozen_one() -> None:
    """The gate tolerance is read from thresholds.py, never restated locally.

    This test exists so that an edit to the frozen numbers cannot slip past as
    a green run: max(0.05 mm, 0.1 percent) is what SYNTHESIS.md ruling 6 froze.
    """
    assert E2E_TOLERANCE_ABS_MM == 0.05
    assert E2E_TOLERANCE_REL == 0.001
    assert e2e_tolerance_mm(12.5) == 0.05
    assert e2e_tolerance_mm(100.0) == pytest.approx(0.1)


@pytest.mark.parametrize("model", MODELS)
def test_primitive_counts_match_the_construction(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """Exactly the faces and cylinders the part was built with, no more, no less."""
    run = gate_runs[model]
    lines = run.skeleton.splitlines()
    planes = [line for line in lines if line.startswith("datum_plane_")]
    axes = [line for line in lines if line.startswith("axis_")]
    # The overview sentence says "1 cylinder" but "2 cylinders", so the count is
    # matched and the noun left alone.
    found = re.search(r"^Found (\d+) planes? and (\d+) cylinders?\.$", run.report, re.M)
    assert found is not None, run.report.splitlines()[:8]
    assert (int(found.group(1)), int(found.group(2))) == (
        run.truth["n_planes"],
        run.truth["n_cylinders"],
    ), run.report
    assert len(planes) == run.truth["n_planes"], run.skeleton
    assert len(axes) == run.truth["n_cylinders"], run.skeleton


@pytest.mark.parametrize("model", MODELS)
def test_every_reported_dimension_is_a_real_dimension(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """Soundness: nothing in report section 2 is a number the part does not have."""
    run = gate_runs[model]
    truths = TRUE_MM[model]
    reported = _report_dimensions(run.report)
    assert reported, f"report for {model} has no dimensions:\n{run.report}"
    for name, value in reported.items():
        assert _matching_truth(value, truths) is not None, (
            f"{model}: reported {name} = {value} mm matches no true dimension "
            f"of {truths} within max(0.05 mm, 0.1 percent)"
        )


@pytest.mark.parametrize("model", MODELS)
def test_required_dimensions_are_all_present(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """Completeness: the dimensions a person asks for first are all recovered."""
    run = gate_runs[model]
    reported = _report_dimensions(run.report)
    values = list(reported.values())
    for truth in REQUIRED_MM[model]:
        assert any(_within_tolerance(value, truth) for value in values), (
            f"{model}: no reported dimension is within "
            f"{e2e_tolerance_mm(truth)} mm of the true {truth} mm; "
            f"the report gave {reported}"
        )


@pytest.mark.parametrize("model", MODELS)
def test_raw_and_snapped_skeleton_dimensions_are_both_in_tolerance(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """The full-precision check, on the numbers the emitted script binds.

    Both the raw fit and the snapped value are held to the tolerance, so a
    dimension cannot pass by having been rounded onto the right answer.
    """
    run = gate_runs[model]
    truths = TRUE_MM[model]
    dimensions = _named_dimensions(run.skeleton)
    assert dimensions, f"{model}: the skeleton named no part dimensions"
    for dimension in dimensions:
        truth = _matching_truth(dimension.assigned, truths)
        assert truth is not None, (
            f"{model}: {dimension.name} = {dimension.assigned} mm matches no "
            f"true dimension of {truths}"
        )
        if dimension.raw is not None:
            assert _within_tolerance(dimension.raw, truth), (
                f"{model}: {dimension.name} was fitted at {dimension.raw} mm, "
                f"outside {e2e_tolerance_mm(truth)} mm of the true {truth} mm, "
                f"and only snapping brought it to {dimension.assigned}"
            )


@pytest.mark.parametrize("model", MODELS)
def test_report_passes_the_format_rules(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """Screen-reader rules: ASCII only, five sections, every dimension line tagged."""
    run = gate_runs[model]
    report = run.report
    assert report.isascii(), "the report contains a non-ASCII character"
    for heading in (
        "Section 1. Overview.",
        "Section 2. Dimensions.",
        "Section 3. Relations.",
        "Section 4. Snap log.",
        "Section 5. Caveats.",
    ):
        assert heading in report, f"{model}: report is missing {heading!r}"

    assert "Provenance: synthetic." in report
    assert "Verify them with a caliper or a datasheet." in report
    # The embargo list (PLAN.md section 7) must survive into every report.
    assert "No accuracy claim of the form plus or minus X millimetres" in report
    assert "Synthetic results verify plumbing only." in report

    lines = report.splitlines()
    start = lines.index("Section 2. Dimensions.") + 1
    seen = 0
    for line in lines[start:]:
        if line.startswith("Section "):
            break
        if not line.strip():
            continue
        assert DIMENSION_LINE_RE.search(line), (
            f"{model}: dimension line does not carry its residual: {line!r}"
        )
        seen += 1
    assert seen >= 2, f"{model}: only {seen} dimension lines"


@pytest.mark.parametrize("model", MODELS)
def test_skeleton_ran_and_wrote_a_step(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """The emitted script is executable code, not a claim: it produced the STEP."""
    run = gate_runs[model]
    assert run.skeleton.isascii()
    assert "VERIFY WITH CALIPER" in run.skeleton
    assert "NAMED DIMENSIONS" in run.skeleton
    # Ground rule 5 and WI-6(f): assembly hints are comments, and no solid is
    # constructed anywhere in the executable part of the file -- not even as
    # scaffolding whose faces are harvested afterwards. Reading the parsed tree
    # rather than the line prefixes is the point: a line-prefix check passes
    # happily on `_solid_x = Solid.make_cylinder(...)`.
    tree = ast.parse(run.skeleton)
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.alias):
            used.add(node.asname or node.name)
    forbidden = {
        "Box",
        "Cylinder",
        "Solid",
        "Part",
        "make_box",
        "make_cylinder",
        "extrude",
        "loft",
        "revolve",
        "cut",
        "fuse",
        "intersect",
    }
    assert not used & forbidden, f"{model}: executed solid geometry {sorted(used & forbidden)}"

    assert run.step_path.is_file(), f"{model}: no STEP file was written"
    head = run.step_path.read_text(encoding="latin-1")[:120]
    assert head.startswith("ISO-10303-21"), f"{model}: not a STEP file"
    assert "STEP written to" in run.stdout
    assert "not a solid" in run.stdout


@pytest.mark.parametrize("model", MODELS)
def test_freecad_opens_the_step_with_the_right_face_count(
    model: str, gate_runs: dict[str, GateRun]
) -> None:
    """FreeCAD's kernel reads the STEP and counts one face per fitted primitive.

    Skipped rather than failed when FreeCAD is not installed: the check could
    not run, and a check that could not run is never a pass.
    """
    run = gate_runs[model]
    checker = _load_step_checker()
    expected = int(run.truth["n_planes"]) + int(run.truth["n_cylinders"])
    result = checker.check_step(run.step_path, expected)
    if result.status == "skipped":
        pytest.skip(result.message)
    assert result.ok, f"{model}: {result.message}"
    assert result.faces == expected
