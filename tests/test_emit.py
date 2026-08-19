"""Tests for the build123d skeleton emitter (PLAN.md WI-6).

The acceptance bar for this work item is behavioural, not cosmetic: the emitted
script must actually run under the project venv's build123d and write a STEP.
So the central test writes the script to a temporary directory, executes it in
a subprocess with the same interpreter that runs pytest, and looks at what
landed on disk. The FreeCAD face-count check runs on top of that when FreeCAD
is installed and is skipped, loudly, when it is not.

These tests depend only on `primitives.py`, which is frozen, so they run before
the fitting and frame stages exist.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scan2cad.emit_build123d import (
    VERIFY_MARKER,
    emit_script,
    plane_uv_basis,
    write_script,
)
from scan2cad.primitives import CylinderFit, PlaneFit, SceneModel, SnapRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_step_freecad.py"

# A 60 x 40 x 20 mm block with one 12.5 mm diameter through bore: the WI-9
# BRACKET, hand-built here so this file needs no generator and no fitter.
_BLOCK = (60.0, 40.0, 20.0)


def _load_check_module():
    """Import scripts/check_step_freecad.py by path.

    It lives outside the package on purpose (it must be runnable by FreeCAD's
    own interpreter), so it is loaded by file location rather than by name.
    """
    spec = importlib.util.spec_from_file_location("check_step_freecad", CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before executing: dataclasses resolves a class's annotations via
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plane(name: str, point, normal, *, half_u: float, half_v: float,
           rms: float = 0.03, pts: int = 14200) -> PlaneFit:
    """Build a PlaneFit centred on `point` with a symmetric footprint."""
    return PlaneFit(
        name=name,
        point=point,
        normal=normal,
        inlier_count=pts,
        rms_mm=rms,
        extent=(-half_u, half_u, -half_v, half_v),
    )


def _bracket_scene() -> SceneModel:
    """Six box faces plus one through bore, in millimetres, already snapped."""
    width, depth, height = _BLOCK
    planes = [
        _plane("plane_bottom", (30.0, 20.0, 0.0), (0.0, 0.0, -1.0),
               half_u=width / 2, half_v=depth / 2),
        _plane("plane_top", (30.0, 20.0, 20.2), (0.0, 0.0, 1.0),
               half_u=width / 2, half_v=depth / 2),
        _plane("plane_left", (0.0, 20.0, 10.0), (-1.0, 0.0, 0.0),
               half_u=depth / 2, half_v=height / 2, rms=0.05, pts=9100),
        _plane("plane_right", (60.1, 20.0, 10.0), (1.0, 0.0, 0.0),
               half_u=depth / 2, half_v=height / 2, rms=0.05, pts=9050),
        _plane("plane_front", (30.0, 0.0, 10.0), (0.0, -1.0, 0.0),
               half_u=width / 2, half_v=height / 2, rms=0.04, pts=11000),
        _plane("plane_back", (30.0, 40.0, 10.0), (0.0, 1.0, 0.0),
               half_u=width / 2, half_v=height / 2, rms=0.04, pts=10900),
    ]
    cylinders = [
        CylinderFit(
            name="cyl_bore_1",
            axis_point=(15.1, 20.0, 0.0),
            axis_dir=(0.0, 0.0, 1.0),
            radius_mm=6.25,
            extent_mm=(0.0, 20.2),
            inlier_count=3100,
            rms_mm=0.06,
        )
    ]
    snaps = [
        SnapRecord("height", 20.23, 20.2, -0.03, "round 0.1mm within 2xRMS"),
        SnapRecord("cyl_bore_1_axis", 89.2, 90.0, 0.8, "axis-align 5deg"),
    ]
    frame = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    return SceneModel(
        frame=frame,
        planes=planes,
        cylinders=cylinders,
        snaps=snaps,
        provenance="synthetic",
    )


@pytest.fixture(scope="module")
def bracket() -> SceneModel:
    return _bracket_scene()


@pytest.fixture(scope="module")
def bracket_text(bracket: SceneModel) -> str:
    return emit_script(bracket, source="tests/hand_built_bracket")


# --------------------------------------------------------------------------
# static properties of the emitted text
# --------------------------------------------------------------------------


def test_emitted_script_is_ascii_and_parses(bracket_text: str) -> None:
    """SYNTHESIS.md ruling 7: ASCII only. And it must be valid Python."""
    bracket_text.encode("ascii")
    ast.parse(bracket_text)


def test_header_carries_the_two_channel_disclaimer(bracket_text: str) -> None:
    """The draft-versus-truth framing is not optional decoration."""
    head = bracket_text.split('"""')[1]
    assert "SCAN DRAFT" in head
    assert "caliper" in head
    assert "Provenance: synthetic" in head
    assert "NOT a solid" in head
    assert "Thresholds: frozen defaults" in head


def test_every_named_dimension_line_is_marked_for_verification(bracket_text: str) -> None:
    """Every `name = number  # ...` line ends with the caliper marker."""
    assignment = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*) = (-?[0-9][0-9.eE+-]*)  # (.*)$")
    found = 0
    for line in bracket_text.splitlines():
        match = assignment.match(line)
        if match is None:
            continue
        found += 1
        assert match.group(3).endswith(VERIFY_MARKER), line
    assert found >= 10, "expected a dimension per primitive plus the snap log"


def test_snap_log_dimensions_show_raw_snapped_and_deviation(bracket_text: str) -> None:
    """No silent snapping (PLAN.md ground rule 6) reaches into the script too."""
    line = next(l for l in bracket_text.splitlines() if l.startswith("height = "))
    assert line.startswith("height = 20.2  #")
    assert "fitted 20.23" in line
    assert "snapped 20.2" in line
    assert "dev -0.03" in line
    assert "rule round 0.1mm within 2xRMS" in line
    # "height" names no primitive, so no residual is attributed to it. Guessing
    # which face's RMS applies would be exactly the kind of quiet fabrication
    # the two-channel model exists to prevent.
    assert re.search(r"RMS [0-9]", line) is None
    assert "pts" not in line


def test_snap_dimension_inherits_the_residual_of_the_primitive_it_names(
    bracket_text: str,
) -> None:
    """A snap named after a primitive carries that primitive's fit quality."""
    line = next(l for l in bracket_text.splitlines() if l.startswith("cyl_bore_1_axis = "))
    assert "RMS 0.06 mm" in line
    assert "3100 pts" in line


def test_no_executed_solid_or_boolean(bracket_text: str) -> None:
    """Solids, extrudes and Booleans may appear only inside comments."""
    tree = ast.parse(bracket_text)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden = {"Box", "Cylinder", "extrude", "Part", "loft", "revolve"}
    assert not (called & forbidden), f"emitted executable solid geometry: {called & forbidden}"
    # Solid.make_cylinder is allowed: it is scaffolding for the lateral face,
    # and the compound that reaches STEP holds faces only.
    assert "reference_surfaces = Compound(children=reference_faces)" in bracket_text


def test_assembly_hints_are_comments_only(bracket_text: str) -> None:
    """Hints teach the next edit; they never run."""
    hint_lines = [l for l in bracket_text.splitlines() if "HINT:" in l]
    assert hint_lines
    assert all(l.startswith("#") for l in hint_lines)
    assert any("plane_bottom parallel plane_top" in l for l in hint_lines)
    assert any("cyl_bore_1" in l for l in hint_lines)


def test_threshold_overrides_are_echoed(bracket: SceneModel) -> None:
    """An overridden run must announce itself in the file it produced."""
    text = emit_script(bracket, overrides={"ransac_epsilon_mm": 0.25})
    assert "Thresholds were overridden" in text
    assert "ransac_epsilon_mm = 0.25" in text


def test_output_is_byte_stable(bracket: SceneModel) -> None:
    """Same SceneModel in, same bytes out -- otherwise diffs are noise."""
    assert emit_script(bracket) == emit_script(bracket)


def test_degenerate_primitive_is_refused(bracket: SceneModel) -> None:
    """A zero-area footprint is an upstream bug and must not be papered over."""
    broken = SceneModel(
        frame=bracket.frame,
        planes=[PlaneFit("plane_0", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 500, 0.1,
                         (0.0, 0.0, -5.0, 5.0))],
        cylinders=[],
        snaps=[],
        provenance="synthetic",
    )
    with pytest.raises(ValueError, match="degenerate footprint"):
        emit_script(broken)


def test_plane_uv_basis_is_right_handed_and_orthonormal() -> None:
    """The shared plane-coordinate convention the extents are measured in."""
    for normal in [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0),
                   (0.5773502692, 0.5773502692, 0.5773502692)]:
        u, v = plane_uv_basis(normal)
        assert abs(sum(a * a for a in u) - 1.0) < 1e-9
        assert abs(sum(a * a for a in v) - 1.0) < 1e-9
        assert abs(sum(a * b for a, b in zip(u, v))) < 1e-9
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        assert all(abs(c - n) < 1e-9 for c, n in zip(cross, normal))


# --------------------------------------------------------------------------
# the acceptance test: the script actually runs and writes a STEP
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def executed_skeleton(bracket: SceneModel, tmp_path_factory) -> tuple[Path, Path]:
    """Write the skeleton, run it under this venv, return (script, step)."""
    work = tmp_path_factory.mktemp("skeleton")
    script = write_script(bracket, work / "bracket_skeleton.py",
                          source="tests/hand_built_bracket")
    step = work / "bracket_ref.step"
    completed = subprocess.run(
        [sys.executable, str(script), str(step)],
        capture_output=True,
        text=True,
        cwd=work,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"emitted skeleton failed:\nstdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    assert "reference surfaces only" in completed.stdout
    return script, step


def test_emitted_script_runs_and_writes_a_step(executed_skeleton) -> None:
    """The WI-6 acceptance criterion: exit 0 and a nonempty STEP on disk."""
    _script, step = executed_skeleton
    assert step.is_file(), "the skeleton did not write the STEP it promised"
    assert step.stat().st_size > 0
    assert step.read_text(encoding="utf-8", errors="replace").lstrip().startswith("ISO-10303")


def test_step_face_count_in_freecad(executed_skeleton, bracket: SceneModel) -> None:
    """FreeCAD must see exactly one face per fitted primitive.

    Skipped with a clear reason when FreeCAD is not installed; a skip is not a
    pass, and the skip message says which binary was missing.
    """
    _script, step = executed_skeleton
    check = _load_check_module()
    expected = len(bracket.planes) + len(bracket.cylinders)
    result = check.check_step(step, expected)
    if result.status == "skipped":
        pytest.skip(result.message)
    assert result.ok, result.message
    assert result.faces == expected, result.message
