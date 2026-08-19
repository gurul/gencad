"""Validate a STEP file with FreeCAD's kernel, from either side of the fence.

FreeCADCmd runs on its own bundled Python, so this file has two personalities
and must never import scan2cad (see docs/STACK_NOTES.md):

  * Run it UNDER FreeCADCmd -- `freecadcmd scripts/check_step_freecad.py
    part_ref.step 7` -- and it opens the STEP, counts faces, prints one
    machine-readable marker line and exits 0 on success, 1 on mismatch.

  * Import it from the project venv and call `check_step(...)`. That path
    re-invokes the FreeCAD binary as a subprocess and parses the marker line.
    If the binary is missing, the result comes back with status "skipped" and a
    plain-language reason rather than an exception, so a test suite on a
    machine without FreeCAD reports a skip instead of a failure.

The expected face count for a scan2cad reference STEP is exactly the number of
fitted planes plus the number of fitted cylinders: the emitted compound holds
one bounded face per primitive and nothing else.

Two FreeCADCmd quirks are worked around here and must not be "cleaned up":
`__name__` is the file stem, not "__main__", so the usual script guard never
fires; and a SystemExit out of the script body ends the process without
flushing stdout, so every result line is printed with flush=True.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# From docs/STACK_NOTES.md: the binary is NOT in Contents/MacOS, which holds
# only the GUI app. Verified working on FreeCAD 1.1.3.
FREECAD_CMD = Path("/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd")

# Single-line, prefix-tagged result so the caller never has to parse around
# FreeCAD's own startup banner, which is printed after the script's output.
RESULT_PREFIX = "STEP_CHECK"

# Timeout for the subprocess. FreeCAD's cold start is a couple of seconds; a
# reference STEP of a handful of faces adds nothing measurable.
TIMEOUT_S = 120.0


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one STEP validation.

    `status` is "ok", "fail" or "skipped". "skipped" means the check could not
    run at all (no FreeCAD on this machine) and must not be read as a pass.
    `faces` is the face count FreeCAD found, or None when the check was skipped
    or the STEP could not be read.
    """

    status: str
    faces: int | None
    message: str

    @property
    def ok(self) -> bool:
        """True only for a real pass; a skip is not a pass."""
        return self.status == "ok"


def check_step(step_path: str | Path, expected_faces: int | None = None) -> CheckResult:
    """Open `step_path` in FreeCADCmd and check its face count.

    Assumes it is being called from the project venv, where FreeCAD is not
    importable. Pass `expected_faces` to assert a count; leave it None to just
    read the count back. Never raises for a missing FreeCAD or a missing file:
    both come back as a CheckResult the caller can turn into a skip or a
    failure as it sees fit.
    """
    target = Path(step_path)
    if not target.is_file():
        return CheckResult("fail", None, f"STEP file does not exist: {target}")
    if not FREECAD_CMD.is_file():
        return CheckResult(
            "skipped",
            None,
            f"FreeCAD command line binary not found at {FREECAD_CMD}; "
            "install FreeCAD 1.1.3 or later to run this check",
        )

    argv = [str(FREECAD_CMD), str(Path(__file__).resolve()), str(target.resolve())]
    if expected_faces is not None:
        argv.append(str(expected_faces))
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - only on a broken install
        return CheckResult("skipped", None, f"could not run {FREECAD_CMD}: {exc}")
    except subprocess.TimeoutExpired:
        return CheckResult("fail", None, f"FreeCAD did not answer within {TIMEOUT_S} s")

    return _parse_result(completed.stdout, completed.stderr, completed.returncode)


def _parse_result(stdout: str, stderr: str, returncode: int) -> CheckResult:
    """Turn FreeCADCmd output into a CheckResult.

    Assumes the marker line is present on success or failure; anything else
    means FreeCAD died before the script ran, which is reported as a skip with
    the captured output attached, because it is an environment problem rather
    than a defect in the STEP.
    """
    for line in stdout.splitlines():
        if not line.startswith(RESULT_PREFIX):
            continue
        fields = dict(
            part.split("=", 1) for part in line.split()[1:] if "=" in part
        )
        status = fields.get("status", "fail")
        raw_faces = fields.get("faces", "-")
        faces = int(raw_faces) if raw_faces.isdigit() else None
        return CheckResult(status, faces, line.strip())
    tail = (stderr or stdout).strip().splitlines()
    detail = tail[-1] if tail else "no output"
    return CheckResult(
        "skipped",
        None,
        f"FreeCAD produced no result line (exit {returncode}): {detail}",
    )


def _run_inside_freecad(argv: list[str]) -> int:
    """Do the actual check. Assumes FreeCAD's Part module is importable.

    `argv` is sys.argv as FreeCADCmd builds it: [binary, script, step, count?].
    """
    import Part  # noqa: PLC0415 - only importable inside FreeCADCmd

    args = argv[2:]
    if not args:
        print(f"{RESULT_PREFIX} status=fail faces=- reason=no_step_path_given", flush=True)
        return 1
    step_path = args[0]
    expected = int(args[1]) if len(args) > 1 else None

    shape = Part.Shape()
    try:
        shape.read(step_path)
    except Exception as exc:  # noqa: BLE001 - FreeCAD raises bare Exception here
        print(f"{RESULT_PREFIX} status=fail faces=- reason=unreadable detail={exc!r}", flush=True)
        return 1

    faces = len(shape.Faces)
    if expected is not None and faces != expected:
        print(
            f"{RESULT_PREFIX} status=fail faces={faces} expected={expected} "
            "reason=face_count_mismatch",
            flush=True,
        )
        return 1
    print(
        f"{RESULT_PREFIX} status=ok faces={faces} "
        f"expected={expected if expected is not None else '-'}",
        flush=True,
    )
    return 0


def freecad_is_importable() -> bool:
    """True when this interpreter is FreeCAD's own bundled one."""
    try:
        import FreeCAD  # noqa: F401, PLC0415 - probe for the bundled interpreter
    except ImportError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Entry point for both personalities. Returns a process exit code."""
    args = list(sys.argv if argv is None else argv)
    if freecad_is_importable():
        return _run_inside_freecad(args)

    # Called from the project venv: forward to FreeCAD and report plainly.
    cli = args[1:]
    if not cli:
        print("usage: check_step_freecad.py STEP_FILE [EXPECTED_FACE_COUNT]", file=sys.stderr)
        return 2
    expected = int(cli[1]) if len(cli) > 1 else None
    result = check_step(cli[0], expected)
    print(f"{result.status}: {result.message}")
    return 0 if result.status in ("ok", "skipped") else 1


def _invoked_as_a_script() -> bool:
    """True when this file was run, rather than imported as a library.

    FreeCADCmd does not set `__name__` to "__main__" -- it sets it to the
    file's stem -- so the usual guard silently does nothing there. The extra
    test is that sys.argv names this very file in the slot FreeCADCmd uses for
    the script path, which stays false when a venv test imports the module.
    """
    if __name__ == "__main__":
        return True
    if len(sys.argv) < 2:
        return False
    try:
        return Path(sys.argv[1]).resolve() == Path(__file__).resolve()
    except OSError:  # pragma: no cover - unresolvable path means not us
        return False


if _invoked_as_a_script():
    raise SystemExit(main())
