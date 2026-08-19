"""Acceptance tests for the command line (WI-8).

PLAN.md acceptance for WI-8 is that both commands run end to end on a synthetic
bracket. That is the last test in this file, and it is the real one: it writes a
small noiseless bracket cloud, runs `describe` and then `draft --step` through
`cli.main`, and checks the report, the emitted skeleton and the STEP file that
the skeleton itself produced in a subprocess.

The bracket used here carries 9,000 points rather than the 80,000 the sweep and
the noise-zero gate use. The whole cloud is exact at sigma zero, so a smaller
sample fits the same primitives; it exists so that this file runs in seconds
instead of minutes, since normal estimation dominates the wall clock. The
end-to-end gate with the full cloud is WI-10's, not this file's.

Everything above that test needs no CGAL, no build123d and no open3d: argument
parsing, threshold overrides and the plain-language failure messages are pure
Python and are checked directly, so the CLI's contract stays under test even on
a machine where the heavy wheels are missing.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from scan2cad import cli
from scan2cad.thresholds import COARSE, FINE

_ROOT = Path(__file__).resolve().parent.parent
_TOOL_PATH = _ROOT / "tools" / "make_synthetic.py"

# Small enough to keep this file fast, large enough that the bore keeps well
# over the frozen 200-point minimum: the bore is about nine percent of the
# bracket's surface area, so 9,000 points leave it roughly 800.
_TEST_POINTS = 9_000


def _load_generator():
    """Import tools/make_synthetic.py under the name 'make_synthetic'.

    tools/ is not a package. Registering the module in sys.modules before
    executing it is required because dataclasses looks its own module up by
    name while building each frozen class.
    """
    spec = importlib.util.spec_from_file_location("make_synthetic", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# argument parsing and threshold overrides (no heavy dependencies)
# ---------------------------------------------------------------------------


def _parse(argv: list[str]):
    return cli.build_parser().parse_args(argv)


def test_no_command_prints_help_and_fails() -> None:
    assert cli.main([]) == cli.EXIT_USAGE


def test_describe_defaults_to_the_frozen_coarse_regime() -> None:
    thresholds, overrides = cli.resolve_thresholds(_parse(["describe", "part.ply"]))
    assert thresholds == COARSE
    assert overrides == {}


def test_regime_flag_selects_the_frozen_fine_preset() -> None:
    thresholds, overrides = cli.resolve_thresholds(
        _parse(["describe", "part.ply", "--regime", "fine"])
    )
    assert thresholds == FINE
    assert overrides == {}


def test_overrides_are_applied_and_reported() -> None:
    """An override changes the run and is named in the echo, per PLAN.md 3."""
    args = _parse(
        ["describe", "part.ply", "--angular-snap-deg", "2.5", "--epsilon-mm", "0.3"]
    )
    thresholds, overrides = cli.resolve_thresholds(args)
    assert thresholds.angular_snap_deg == 2.5
    assert thresholds.ransac_epsilon_mm == 0.3
    assert overrides == {
        "angular snap degrees": 2.5,
        "RANSAC epsilon millimetres": 0.3,
    }
    # The frozen preset itself is untouched (SYNTHESIS.md ruling 6).
    assert COARSE.angular_snap_deg == 5.0
    assert COARSE.ransac_epsilon_mm == 0.5


def test_flat_dimensional_snap_clears_the_rms_factor() -> None:
    """The frozen invariant is that exactly one dimensional field is set."""
    thresholds, _overrides = cli.resolve_thresholds(
        _parse(["describe", "part.ply", "--dim-snap-mm", "0.4"])
    )
    assert thresholds.dim_snap_mm == 0.4
    assert thresholds.dim_snap_rms_factor is None
    assert thresholds.dimensional_tolerance_mm(1.0) == 0.4


def test_rms_factor_override_clears_the_flat_snap() -> None:
    thresholds, _overrides = cli.resolve_thresholds(
        _parse(["describe", "part.ply", "--regime", "fine", "--dim-snap-rms-factor", "3"])
    )
    assert thresholds.dim_snap_rms_factor == 3.0
    assert thresholds.dim_snap_mm is None


def test_both_dimensional_snaps_at_once_is_refused() -> None:
    args = _parse(
        ["describe", "part.ply", "--dim-snap-mm", "0.4", "--dim-snap-rms-factor", "2"]
    )
    with pytest.raises(cli.CliError) as excinfo:
        cli.resolve_thresholds(args)
    assert excinfo.value.code == cli.EXIT_USAGE
    assert "not both" in excinfo.value.message


def test_a_nonpositive_override_is_refused_with_a_sentence() -> None:
    args = _parse(["describe", "part.ply", "--epsilon-mm", "0"])
    with pytest.raises(cli.CliError) as excinfo:
        cli.resolve_thresholds(args)
    assert excinfo.value.code == cli.EXIT_USAGE
    assert "greater than zero" in excinfo.value.message


def test_units_default_by_provenance() -> None:
    """A mesh is assumed metric in metres; a synthetic part in millimetres."""
    assert cli._units_for(_parse(["describe", "part.ply"])) == "m"
    assert (
        cli._units_for(_parse(["describe", "part.ply", "--provenance", "synthetic"]))
        == "mm"
    )
    assert (
        cli._units_for(_parse(["describe", "part.ply", "--units", "mm"])) == "mm"
    )


def test_missing_file_exits_with_a_plain_sentence(capsys: pytest.CaptureFixture) -> None:
    code = cli.main(["describe", str(_ROOT / "out" / "no_such_scan.ply")])
    captured = capsys.readouterr()
    assert code == cli.EXIT_INPUT
    assert "no such scan file" in captured.err
    assert captured.err.isascii()
    assert captured.out == ""


def test_unsupported_file_type_exits_with_a_plain_sentence(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    bad = tmp_path / "scan.txt"
    bad.write_text("not a mesh\n", encoding="ascii")
    code = cli.main(["describe", str(bad)])
    captured = capsys.readouterr()
    assert code == cli.EXIT_INPUT
    assert "unsupported scan file type" in captured.err


def test_draft_requires_an_output_path() -> None:
    with pytest.raises(SystemExit):
        _parse(["draft", "part.ply"])


# ---------------------------------------------------------------------------
# the end-to-end run: PLAN.md WI-8 acceptance
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bracket_ply(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A noiseless synthetic bracket written as a PLY point cloud.

    Module-scoped: generating and writing the cloud is cheap, but every test
    that loads it pays for normal estimation, so it is built once.
    """
    generator = _load_generator()
    params = generator.SamplerParams(n_points=_TEST_POINTS, sigma_mm=0.0, seed=1337)
    points, normals, truth = generator.make_model("bracket", params)
    directory = tmp_path_factory.mktemp("bracket")
    path = directory / "bracket.ply"
    generator.write_ply(path, points, normals)
    (directory / "bracket.truth.json").write_text(
        json.dumps(truth, indent=2) + "\n", encoding="ascii"
    )
    return path


def _truth_of(ply: Path) -> dict:
    return json.loads(ply.with_suffix(".truth.json").read_text(encoding="ascii"))


def _dimension_values(report: str) -> dict[str, float]:
    """Pull `name = value mm` pairs out of a rendered report."""
    found: dict[str, float] = {}
    for line in report.splitlines():
        match = re.match(r"^([a-zA-Z0-9_]+) = ([0-9.]+) mm", line)
        if match:
            found[match.group(1)] = float(match.group(2))
    return found


def _require_pipeline_wheels() -> None:
    """Skip an end-to-end test when the heavy wheels are absent.

    Called inside each test rather than at module level on purpose: a
    module-level skip would take the pure-Python argument and message tests
    down with it, and those are exactly the ones worth keeping on a bare
    interpreter.
    """
    pytest.importorskip("open3d", reason="the end-to-end run needs open3d")
    pytest.importorskip("CGAL", reason="the end-to-end run needs the CGAL wheel")


def test_describe_runs_end_to_end_on_a_synthetic_bracket(
    bracket_ply: Path, capsys: pytest.CaptureFixture
) -> None:
    """`describe` prints a full report for a sigma-zero bracket.

    The dimension check is deliberately loose compared with the noise-zero gate
    (WI-10 owns that, at max(0.05 mm, 0.1 percent) on the full 80,000-point
    cloud): here the claim is only that the wiring carries real numbers through,
    on a cloud a tenth the size.

    Every face gap the report DOES name must match the construction truth, but
    the test does not require all three of them. See the finding recorded in
    `test_primitive_counts_match_construction_truth`: CGAL's shape detection is
    unseeded and sometimes relabels one or two faces of the bracket, which is
    an upstream defect this test refuses to hide and equally refuses to
    restate as an expected count.
    """
    _require_pipeline_wheels()
    code = cli.main(
        ["describe", str(bracket_ply), "--provenance", "synthetic"]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.err

    report = captured.out
    assert report.isascii()
    for heading in (
        "Section 1. Overview.",
        "Section 2. Dimensions.",
        "Section 3. Relations.",
        "Section 4. Snap log.",
        "Section 5. Caveats.",
    ):
        assert heading in report
    assert "Provenance: synthetic." in report
    assert "Threshold regime: coarse." in report
    assert "No threshold overrides were used." in report
    assert "Verify them with a caliper or a datasheet." in report

    dims = _dimension_values(report)
    truth = _truth_of(bracket_ply)["dims_mm"]
    nominal = [truth["width"], truth["depth"], truth["height"]]
    # The frame is the object's, not the world's (frame.py docstring), so a
    # reported gap is matched against the set of true gaps, not by name. How
    # MANY gaps survive is not asserted here, only that each one is true: the
    # fitter loses between zero and two of the bracket's faces from run to run
    # (see the finding below), and restating that count would make this test
    # a coin toss instead of a statement about the wiring.
    gaps = [dims[name] for name in ("width", "depth", "height") if name in dims]
    assert gaps, f"no face gap at all was reported: {dims}"
    for gap in gaps:
        assert any(
            abs(gap - true_value) < 0.1 for true_value in nominal
        ), f"reported gap {gap} mm matches no true dimension of {nominal}"

    bore = [value for name, value in dims.items() if name.endswith("_diameter")]
    assert any(
        abs(value - truth["bore_diameter"]) < 0.1 for value in bore
    ), f"no fitted diameter near the {truth['bore_diameter']} mm bore: {bore}"


def test_primitive_counts_match_construction_truth(bracket_ply: Path) -> None:
    """The bracket should fit as exactly 6 planes and 1 cylinder.

    This was an expected failure until 2026-08-19. CGAL Efficient RANSAC draws
    from an unseeded generator, and about one run in three relabelled a face of
    the noiseless bracket as a cylinder of several thousand millimetres radius,
    giving 5 planes and 3 cylinders instead of 6 and 1. The cause was in the
    fitter, not here: it accepted a cylinder hypothesis the points could not
    support. `ransac_cgal` now refits a cylinder that bends less than the RANSAC
    epsilon across its own inliers as the plane it really is, so the count is
    stable and the expected-failure marker has come off. See that module's
    docstring for the other two consolidation rules.
    """
    _require_pipeline_wheels()
    args = cli.build_parser().parse_args(
        ["describe", str(bracket_ply), "--provenance", "synthetic"]
    )
    output = cli.run_pipeline(args)
    truth = _truth_of(bracket_ply)
    assert len(output.scene.planes) == truth["n_planes"]
    assert len(output.scene.cylinders) == truth["n_cylinders"]


def test_draft_writes_a_skeleton_and_a_step(
    bracket_ply: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`draft --step` emits a skeleton, runs it, and keeps the STEP it wrote.

    Running the emitted script is the point of --step: generated code that has
    never been executed is a claim, not a deliverable. The STEP is produced by
    the skeleton in a subprocess, not by scan2cad, so its existence proves the
    emitted file works under the project's build123d.
    """
    _require_pipeline_wheels()
    pytest.importorskip("build123d", reason="running the skeleton needs build123d")

    skeleton = tmp_path / "bracket_skeleton.py"
    step = tmp_path / "bracket_ref.step"
    code = cli.main(
        [
            "draft",
            str(bracket_ply),
            "--provenance",
            "synthetic",
            "-o",
            str(skeleton),
            "--step",
            str(step),
        ]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.err

    assert "Section 2. Dimensions." in captured.out
    assert f"Skeleton written to {skeleton.resolve()}." in captured.out
    assert "not a solid" in captured.out

    assert skeleton.is_file()
    text = skeleton.read_text(encoding="ascii")
    assert text.isascii()
    assert "VERIFY WITH CALIPER" in text
    assert "NAMED DIMENSIONS" in text
    # Ground rule 5: hints are comments, never executed solids or Booleans.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("part = ")

    assert step.is_file()
    head = step.read_text(encoding="latin-1")[:200]
    assert head.startswith("ISO-10303-21")


def test_draft_without_step_leaves_no_step_behind(
    bracket_ply: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Without --step the skeleton is written but never executed."""
    _require_pipeline_wheels()
    skeleton = tmp_path / "quiet_skeleton.py"
    code = cli.main(
        [
            "draft",
            str(bracket_ply),
            "--provenance",
            "synthetic",
            "-o",
            str(skeleton),
        ]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.err
    assert skeleton.is_file()
    assert list(tmp_path.glob("*.step")) == []


def test_too_few_primitives_exits_with_advice(
    bracket_ply: Path, capsys: pytest.CaptureFixture
) -> None:
    """A run that finds nothing says so in words, and says what to try.

    A millimetre part read as metres is a thousand times too large for the
    frozen RANSAC epsilon, which is the most common way this happens for real.
    """
    _require_pipeline_wheels()
    code = cli.main(["describe", str(bracket_ply), "--units", "m"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_TOO_FEW
    assert "at least 2 are needed" in captured.err
    assert "--units mm" in captured.err
    assert captured.err.isascii()
