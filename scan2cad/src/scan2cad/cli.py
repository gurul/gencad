"""The scan2cad command line: describe and draft (WI-8).

This module is the join point of the whole pipeline. It owns no geometry of its
own; it wires the stages together in the one fixed order and turns every
failure into a plain sentence a screen reader can read out:

    file -> sources.FileMeshSource -> ransac_cgal.fit_primitives
         -> frame.align_and_snap -> report.render_report
                                 -> emit_build123d.write_script

Two commands:

    scan2cad describe INPUT
        Print the plain-language geometry report on stdout. Nothing is written.

    scan2cad draft INPUT -o skeleton.py [--step out.step]
        Print the same report on stdout and write the editable build123d
        skeleton to the named file. With --step, the skeleton is then executed
        in a subprocess -- proving the emitted script actually runs -- and the
        STEP file it writes is moved to the requested path.

Every threshold in `thresholds.py` can be overridden from the command line, and
every override is echoed in the report and in the header of the emitted script
(PLAN.md section 3): a run that did not use the frozen defaults always says so
out loud. Overriding a threshold on the command line is not tuning the frozen
values, which stay as they are on disk (SYNTHESIS.md ruling 6).

Exit codes, all documented because a screen-reader user cannot skim a stack
trace:

    0  success
    2  bad command line (argparse)
    3  the input could not be read or fitted
    4  fewer than MIN_PRIMITIVES primitives were found; nothing to describe
    5  the emitted skeleton failed to run, or the STEP was not produced

All output is ASCII (SYNTHESIS.md ruling 7). Errors go to stderr, the report to
stdout, so `scan2cad describe part.ply > report.txt` keeps the two apart.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from scan2cad.emit_build123d import DEFAULT_STEP_NAME, write_script
from scan2cad.frame import FrameError, align_and_snap
from scan2cad.io_mesh import (
    DEFAULT_SAMPLE_COUNT,
    DEFAULT_SEED,
    PROVENANCE_MESH,
    PROVENANCE_SYNTHETIC,
    LoadedCloud,
)
from scan2cad.primitives import SceneModel
from scan2cad.ransac_cgal import DEFAULT_PROBABILITY, FitError, RansacResult, fit_primitives
from scan2cad.report import render_report
from scan2cad.sources import FileMeshSource
from scan2cad.thresholds import DEFAULT_REGIME, REGIMES, Thresholds, get_regime

__all__ = ["main", "run_pipeline", "PipelineOutput"]

PROG = "scan2cad"

# Below this many primitives there is no object to talk about: one plane is a
# tabletop, and the honest answer is that the scan failed, not a report with a
# single line in it. PLAN.md WI-8 fixes the number.
MIN_PRIMITIVES = 2

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_TOO_FEW = 4
EXIT_DRAFT = 5

# Command-line override name -> Thresholds field it replaces. The keys are the
# names echoed in the report and in the emitted script header, so they read as
# words rather than as argparse destinations.
_OVERRIDE_FIELDS: dict[str, str] = {
    "angular snap degrees": "angular_snap_deg",
    "dimensional snap millimetres": "dim_snap_mm",
    "dimensional snap RMS factor": "dim_snap_rms_factor",
    "RANSAC epsilon millimetres": "ransac_epsilon_mm",
    "RANSAC cluster epsilon millimetres": "ransac_cluster_epsilon_mm",
    "RANSAC normal threshold": "ransac_normal_threshold",
    "RANSAC minimum points": "ransac_min_points",
}


class CliError(Exception):
    """A failure with a plain-language message and an exit code.

    Assumes `message` is one or more complete ASCII sentences; `main` prints it
    to stderr verbatim and returns `code`. Raised instead of calling sys.exit
    so the pipeline stays importable and testable.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the input, sampling and threshold flags shared by both commands.

    Assumes `parser` is a subcommand parser. Threshold flags default to None so
    that "not given" is distinguishable from "given the frozen value", which is
    what makes the override echo honest.
    """
    parser.add_argument(
        "input",
        metavar="INPUT",
        help="scan file to read: PLY, OBJ, or STL",
    )
    parser.add_argument(
        "--units",
        choices=("mm", "m"),
        default=None,
        help=(
            "what the numbers in the file mean; default is metres for a "
            "photogrammetry mesh and millimetres for synthetic provenance"
        ),
    )
    parser.add_argument(
        "--provenance",
        choices=(PROVENANCE_MESH, PROVENANCE_SYNTHETIC),
        default=PROVENANCE_MESH,
        help=(
            "where the file came from; synthetic results are plumbing "
            "verification only (default: " + PROVENANCE_MESH + ")"
        ),
    )
    parser.add_argument(
        "--regime",
        choices=tuple(sorted(REGIMES)),
        default=DEFAULT_REGIME,
        help=f"frozen threshold preset to use (default: {DEFAULT_REGIME})",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=DEFAULT_SAMPLE_COUNT,
        help=f"points to sample from a mesh (default: {DEFAULT_SAMPLE_COUNT})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"random seed for sampling (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--probability",
        type=float,
        default=DEFAULT_PROBABILITY,
        help=(
            "RANSAC stopping probability; lower is slower and more thorough "
            f"(default: {DEFAULT_PROBABILITY})"
        ),
    )

    group = parser.add_argument_group(
        "threshold overrides",
        "Every override given here is echoed in the report and in the emitted "
        "script. The frozen defaults in thresholds.py are never changed.",
    )
    group.add_argument("--angular-snap-deg", type=float, default=None,
                       help="angular snap tolerance in degrees")
    group.add_argument("--dim-snap-mm", type=float, default=None,
                       help="flat dimensional snap tolerance in millimetres")
    group.add_argument("--dim-snap-rms-factor", type=float, default=None,
                       help="dimensional snap tolerance as a multiple of per-primitive RMS")
    group.add_argument("--epsilon-mm", type=float, default=None,
                       help="RANSAC epsilon: largest inlier distance in millimetres")
    group.add_argument("--cluster-epsilon-mm", type=float, default=None,
                       help="RANSAC cluster epsilon in millimetres")
    group.add_argument("--normal-threshold", type=float, default=None,
                       help="RANSAC normal agreement threshold, 0 to 1")
    group.add_argument("--min-points", type=int, default=None,
                       help="smallest inlier count a primitive may keep")


def build_parser() -> argparse.ArgumentParser:
    """Return the full argument parser for both commands.

    Kept as a function rather than a module-level object so that tests can
    build a fresh parser, and so importing this module costs nothing.
    """
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Describe a scanned mesh in plain language and draft an editable "
            "build123d script from it. The scan is the draft; the caliper or "
            "the datasheet is the truth. No accuracy claim is made."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    describe = subparsers.add_parser(
        "describe",
        help="print the plain-language geometry report",
        description="Print the plain-language geometry report on standard output.",
    )
    _add_common_arguments(describe)

    draft = subparsers.add_parser(
        "draft",
        help="print the report and write an editable build123d skeleton",
        description=(
            "Print the geometry report and write an editable build123d "
            "skeleton. With --step the skeleton is run in a subprocess and the "
            "STEP file of reference surfaces it writes is kept."
        ),
    )
    _add_common_arguments(draft)
    draft.add_argument(
        "-o",
        "--output",
        required=True,
        help="path for the emitted build123d skeleton script",
    )
    draft.add_argument(
        "--step",
        default=None,
        help=(
            "run the emitted skeleton and keep its STEP file at this path; "
            "the STEP holds reference surfaces only, not a solid"
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# threshold assembly
# ---------------------------------------------------------------------------


def resolve_thresholds(args: argparse.Namespace) -> tuple[Thresholds, dict[str, object]]:
    """Return the thresholds this run uses plus the overrides to echo.

    Assumes `args` came from `build_parser`. Starts from the frozen preset named
    by --regime and applies only the flags that were actually given, so the
    returned dictionary is exactly the set of numbers a reader must be told
    about. Setting one of the two dimensional tolerances clears the other, since
    the frozen `Thresholds` invariant is that exactly one of them is set.

    Raises CliError on a value that cannot mean anything, for example a
    negative tolerance, rather than letting it fail deep inside the fitter.
    """
    base = get_regime(args.regime)
    given: dict[str, object] = {}
    values = {
        "angular snap degrees": args.angular_snap_deg,
        "dimensional snap millimetres": args.dim_snap_mm,
        "dimensional snap RMS factor": args.dim_snap_rms_factor,
        "RANSAC epsilon millimetres": args.epsilon_mm,
        "RANSAC cluster epsilon millimetres": args.cluster_epsilon_mm,
        "RANSAC normal threshold": args.normal_threshold,
        "RANSAC minimum points": args.min_points,
    }
    for label, value in values.items():
        if value is None:
            continue
        if isinstance(value, (int, float)) and value <= 0.0:
            raise CliError(
                f"scan2cad: the override {label} must be greater than zero, "
                f"but {value} was given.",
                EXIT_USAGE,
            )
        given[label] = value

    if (
        "dimensional snap millimetres" in given
        and "dimensional snap RMS factor" in given
    ):
        raise CliError(
            "scan2cad: choose either a flat dimensional snap in millimetres or "
            "a multiple of the residual, not both.",
            EXIT_USAGE,
        )

    updates: dict[str, object] = {
        _OVERRIDE_FIELDS[label]: value for label, value in given.items()
    }
    # Whichever dimensional tolerance was given clears the other one, so the
    # frozen invariant that exactly one of the two is set survives an override.
    # The two branches read the original `given`, not `updates`, because the
    # first branch would otherwise put the second branch's key into `updates`
    # and both fields would end up None.
    if "dimensional snap millimetres" in given:
        updates["dim_snap_rms_factor"] = None
    if "dimensional snap RMS factor" in given:
        updates["dim_snap_mm"] = None
    if "ransac_min_points" in updates:
        updates["ransac_min_points"] = int(updates["ransac_min_points"])

    return replace(base, **updates), given


def _units_for(args: argparse.Namespace) -> str:
    """Return the unit assumption for this run.

    A file records no unit, so one is assumed and always printed. --units wins.
    Failing that, a photogrammetry mesh is metres because that is what
    PhotogrammetrySession emits, and a file declared synthetic is millimetres
    because tools/make_synthetic.py authors in millimetres.
    """
    if args.units is not None:
        return str(args.units)
    return "mm" if args.provenance == PROVENANCE_SYNTHETIC else "m"


# ---------------------------------------------------------------------------
# the pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineOutput:
    """Everything one describe-or-draft run produced, for the caller to use.

    Assumes the run reached the report stage; a run that failed earlier raises
    CliError instead. Held as a small object rather than a tuple so that a test
    or a future caller can reach the intermediate stages without re-running the
    fit, which takes most of the wall clock.
    """

    cloud: LoadedCloud
    fit: RansacResult
    scene: SceneModel
    report_text: str
    thresholds: Thresholds
    overrides: dict[str, object]


def run_pipeline(args: argparse.Namespace) -> PipelineOutput:
    """Load, fit, align and describe the input named by `args`.

    Assumes `args` carries the common flags added by `_add_common_arguments`.
    This is the whole pipeline in one place and in one fixed order; both
    commands call it and differ only in what they do with the result.

    Raises CliError, already carrying its exit code and its plain-language
    message, for an unreadable input, a fitter that could not run, a frame
    stage that refused the primitive names, or a scan that yielded fewer than
    MIN_PRIMITIVES primitives.
    """
    thresholds, overrides = resolve_thresholds(args)
    source = FileMeshSource(
        path=args.input,
        units=_units_for(args),  # type: ignore[arg-type]
        sample_count=int(args.points),
        seed=int(args.seed),
        provenance=str(args.provenance),
    )

    try:
        cloud = source.load_cloud()
    except (FileNotFoundError, ValueError) as exc:
        raise CliError(f"scan2cad: {exc}", EXIT_INPUT) from exc

    try:
        fit = fit_primitives(
            cloud.points,
            cloud.normals,
            thresholds=thresholds,
            probability=float(args.probability),
        )
    except FitError as exc:
        raise CliError(f"scan2cad: {exc}", EXIT_INPUT) from exc

    if fit.primitive_count < MIN_PRIMITIVES:
        raise CliError(_too_few_message(fit, thresholds), EXIT_TOO_FEW)

    try:
        scene = align_and_snap(
            fit.planes,
            fit.cylinders,
            thresholds=thresholds,
            provenance=cloud.provenance,
        )
    except FrameError as exc:
        raise CliError(f"scan2cad: {exc}", EXIT_INPUT) from exc

    report_text = render_report(
        scene,
        units_note=cloud.units_assumption.rstrip("."),
        regime=thresholds,
        overrides=overrides or None,
    )
    return PipelineOutput(cloud, fit, scene, report_text, thresholds, overrides)


def _too_few_message(fit: RansacResult, thresholds: Thresholds) -> str:
    """Explain a scan that produced nothing to describe, and what to try next.

    Assumes `fit.primitive_count` is below MIN_PRIMITIVES. The advice names the
    two knobs that actually change this outcome, because "fitting failed" on its
    own leaves a listener with nowhere to go.
    """
    lines = [
        f"scan2cad: only {fit.primitive_count} primitives were found, and at "
        f"least {MIN_PRIMITIVES} are needed to describe an object.",
        f"The scan had {fit.point_count} points, of which "
        f"{fit.assigned_point_count} joined a shape and "
        f"{fit.fitted_point_count} survived into a fitted surface.",
    ]
    for reason in fit.dropped:
        lines.append(f"Dropped shape: {reason}")
    lines += [
        "Two things usually cause this.",
        "First, the units may be wrong: pass --units mm or --units m to match "
        "the file.",
        "Second, the fit may be too strict for this scan: raise "
        f"--epsilon-mm above {thresholds.ransac_epsilon_mm} or lower "
        f"--min-points below {thresholds.ransac_min_points}.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# the draft command's subprocess step
# ---------------------------------------------------------------------------


def _run_skeleton(script_path: Path, step_path: Path) -> str:
    """Execute the emitted skeleton so that it writes `step_path`.

    Assumes `script_path` exists and takes its STEP destination as the first
    command-line argument, which is what `emit_build123d` emits. The script is
    run with the same interpreter that is running scan2cad, so it picks up the
    project venv's build123d without any path juggling.

    The STEP is written to a temporary directory first and then moved into
    place, so a failed run never leaves a stale or half-written file at the
    path the user asked for. Returns the script's stdout for the caller to
    print. Raises CliError with the script's own error output on failure.
    """
    with tempfile.TemporaryDirectory(prefix="scan2cad_step_") as workspace:
        staged = Path(workspace) / step_path.name
        completed = subprocess.run(
            [sys.executable, str(script_path), str(staged)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise CliError(
                "scan2cad: the emitted skeleton did not run to completion.\n"
                f"It exited with code {completed.returncode}.\n"
                "The script itself said:\n"
                + (completed.stderr.strip() or "nothing on its error output."),
                EXIT_DRAFT,
            )
        if not staged.is_file():
            raise CliError(
                "scan2cad: the emitted skeleton ran but wrote no STEP file.",
                EXIT_DRAFT,
            )
        step_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(step_path))
    return completed.stdout


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _command_describe(args: argparse.Namespace, stream: TextIO) -> int:
    """Run the pipeline and print the report. Writes nothing to disk."""
    output = run_pipeline(args)
    stream.write(output.report_text)
    return EXIT_OK


def _command_draft(args: argparse.Namespace, stream: TextIO) -> int:
    """Run the pipeline, print the report, and write the skeleton script.

    With --step the skeleton is also executed, which is the only proof worth
    having that the emitted script runs: it is generated code, and code that
    has never been run is a claim, not a deliverable.
    """
    output = run_pipeline(args)
    stream.write(output.report_text)

    script_path = Path(args.output)
    step_name = Path(args.step).name if args.step else DEFAULT_STEP_NAME
    try:
        written = write_script(
            output.scene,
            script_path,
            source=output.cloud.source_path,
            step_path=step_name,
            overrides=output.overrides or None,
        )
    except (ValueError, OSError) as exc:
        raise CliError(f"scan2cad: the skeleton could not be written: {exc}", EXIT_DRAFT) from exc

    stream.write("\n")
    stream.write(f"Skeleton written to {written}.\n")
    stream.write("Edit its named dimensions from your caliper, then rerun it.\n")

    if args.step:
        step_path = Path(args.step)
        script_output = _run_skeleton(written, step_path)
        for line in script_output.splitlines():
            stream.write(line + "\n")
        stream.write(f"STEP written to {step_path.resolve()}.\n")
        stream.write(
            "The STEP holds reference surfaces only. It is not a solid and "
            "not printable.\n"
        )
    return EXIT_OK


_COMMANDS = {"describe": _command_describe, "draft": _command_draft}


def _quiet_open3d() -> None:
    """Silence open3d's informational chatter on stderr.

    open3d prints a warning whenever its mesh reader is handed a file that
    turns out to hold only vertices, which is exactly what `io_mesh` does on
    purpose for every PLY point cloud: a PLY extension does not say whether the
    file is a mesh, so the mesh reader is tried first and its result rejected.
    The message is therefore expected, not diagnostic, and reading it aloud
    before every report would be noise. Real failures still raise.

    A missing or restructured open3d is ignored: quieting a library is never a
    reason to fail a run.
    """
    try:
        import open3d as o3d

        o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)
    except Exception:  # pragma: no cover - cosmetic only
        pass


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return the process exit code.

    Assumes `argv` excludes the program name, as `sys.argv[1:]` does. Returns
    rather than exits, so the whole CLI is callable from a test in-process; the
    module footer converts the return value into a real exit status.

    Every failure that is not a bug prints one or more plain ASCII sentences to
    stderr and returns a documented non-zero code. A KeyboardInterrupt returns
    the shell's usual 130 with a short line, because a scan of a large mesh
    takes long enough that people do interrupt it.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    _quiet_open3d()

    try:
        return _COMMANDS[args.command](args, sys.stdout)
    except CliError as exc:
        print(exc.message, file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("scan2cad: interrupted before the report was finished.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
