"""Acceptance tests for the plain-text report (WI-5).

The scene under test is hand-built here rather than fitted, so these tests run
with no dependency on the IO, RANSAC, or frame stages: a golden-file check
plus the format rules from PLAN.md WI-5 and SYNTHESIS.md section 7.

The golden file is the contract for wording and ordering. If a change to
report.py is deliberate, read the new output aloud first, then update
tests/golden/report_bracket.txt in the same commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scan2cad.primitives import CylinderFit, PlaneFit, SceneModel, SnapRecord
from scan2cad.report import DIMENSION_LINE_RE, render_report
from scan2cad.thresholds import COARSE, FINE

GOLDEN = Path(__file__).resolve().parent / "golden" / "report_bracket.txt"

# The scene below is the PLAN.md worked example: a 60.1 by 40.0 by 20.2 mm
# bracket with a single 12.5 mm through-bore, deliberately built with the
# untidy numbers a real fit would produce.
_IDENTITY_FRAME = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


def _bracket_scene() -> SceneModel:
    """A hand-built SceneModel standing in for a fitted 60 by 40 by 20 bracket."""
    planes = [
        PlaneFit(
            name="plane_bottom",
            point=(30.0, 20.0, 0.0),
            normal=(0.0, 0.0, -1.0),
            inlier_count=7300,
            rms_mm=0.3,
            extent=(-30.0, 30.0, -20.0, 20.0),
        ),
        PlaneFit(
            name="plane_top",
            point=(30.0, 20.0, 20.2),
            normal=(0.0, 0.0, 1.0),
            inlier_count=6900,
            rms_mm=0.28,
            extent=(-30.0, 30.0, -20.0, 20.0),
        ),
        PlaneFit(
            name="plane_left",
            point=(0.0, 20.0, 10.0),
            normal=(-1.0, 0.0, 0.0),
            inlier_count=4100,
            rms_mm=0.25,
            extent=(-20.0, 20.0, -10.0, 10.0),
        ),
        PlaneFit(
            name="plane_right",
            point=(60.1, 20.0, 10.0),
            normal=(1.0, 0.0, 0.0),
            inlier_count=4050,
            rms_mm=0.26,
            extent=(-20.0, 20.0, -10.0, 10.0),
        ),
        PlaneFit(
            name="plane_front",
            point=(30.0, 0.0, 10.0),
            normal=(0.0, -1.0, 0.0),
            inlier_count=5200,
            rms_mm=0.31,
            extent=(-30.0, 30.0, -10.0, 10.0),
        ),
        PlaneFit(
            name="plane_back",
            point=(30.0, 40.0, 10.0),
            normal=(0.0, 1.0, 0.0),
            inlier_count=5100,
            rms_mm=0.29,
            extent=(-30.0, 30.0, -10.0, 10.0),
        ),
    ]
    cylinders = [
        CylinderFit(
            name="cyl_bore_1",
            axis_point=(15.1, 20.0, 0.0),
            axis_dir=(0.0, 0.0, 1.0),
            radius_mm=6.25,
            extent_mm=(0.0, 20.2),
            inlier_count=3100,
            rms_mm=0.2,
        )
    ]
    snaps = [
        SnapRecord(
            dim_name="cyl_bore_1_axis",
            raw=89.2,
            snapped=90.0,
            deviation=0.8,
            rule="axis-align 5deg",
        ),
        SnapRecord(
            dim_name="height",
            raw=20.23,
            snapped=20.2,
            deviation=-0.03,
            rule="length-round 0.1mm within 2xRMS",
        ),
        SnapRecord(
            dim_name="cyl_bore_1_radius",
            raw=6.2372,
            snapped=6.25,
            deviation=0.0128,
            rule="radius-cluster 2xRMS",
        ),
    ]
    return SceneModel(
        frame=_IDENTITY_FRAME,
        planes=planes,
        cylinders=cylinders,
        snaps=snaps,
        provenance="synthetic",
    )


def _bracket_report() -> str:
    return render_report(
        _bracket_scene(),
        units_note="input read as millimetres",
        regime=COARSE,
    )


def _dimension_lines(text: str) -> list[str]:
    """Lines that state a named dimension, identified the way the gate does."""
    return [line for line in text.splitlines() if DIMENSION_LINE_RE.search(line)]


def test_golden_file_matches() -> None:
    """The report is byte-for-byte what was reviewed by ear."""
    assert GOLDEN.exists(), f"missing golden file: {GOLDEN}"
    assert _bracket_report() == GOLDEN.read_text(encoding="utf-8")


def test_report_is_pure_ascii() -> None:
    """SYNTHESIS.md section 7: no unicode symbols anywhere in emitted text."""
    text = _bracket_report()
    text.encode("ascii")  # raises UnicodeEncodeError on any non-ASCII character
    assert all(ord(character) < 127 for character in text)


def test_non_ascii_input_is_rejected_not_emitted() -> None:
    """A non-ASCII name from an upstream stage fails loudly, it is not printed."""
    scene = _bracket_scene()
    bad = SceneModel(
        frame=scene.frame,
        planes=scene.planes,
        cylinders=scene.cylinders,
        snaps=scene.snaps,
        provenance="synthetic — dash",
    )
    with pytest.raises(ValueError, match="non-ASCII"):
        render_report(bad)


def test_every_dimension_line_matches_the_gate_regex() -> None:
    """PLAN.md WI-5 acceptance: `= [0-9.]+ mm.*RMS` on every dimension line."""
    lines = _dimension_lines(_bracket_report())
    assert len(lines) == 5  # width, depth, height, bore diameter, bore length
    for line in lines:
        assert re.search(r"= [0-9.]+ mm.*RMS", line), line


def test_every_dimension_line_ends_with_its_uncertainty_tag() -> None:
    """No dimension may be spoken without its residual and its point count."""
    for line in _dimension_lines(_bracket_report()):
        assert re.search(r"RMS [0-9.]+ mm, [0-9]+ points\.$", line), line


def test_no_tables_and_no_ascii_art() -> None:
    """Screen-reader rule: nothing that only makes sense laid out in columns."""
    for line in _bracket_report().splitlines():
        assert "\t" not in line
        assert "|" not in line
        assert "  " not in line, f"column padding in: {line!r}"
        assert not re.search(r"[-=+*_]{3,}", line), f"rule or ASCII art in: {line!r}"


def test_one_fact_per_line_and_short_lines() -> None:
    """Every non-empty line is a single sentence ending in a period."""
    for line in _bracket_report().splitlines():
        if not line:
            continue
        assert line.endswith("."), line
        assert len(line) <= 100, f"line too long to hear in one breath: {line!r}"


def test_overview_reports_bounding_box_and_counts() -> None:
    text = _bracket_report()
    assert "Object bounding box 60.1 by 40.0 by 20.2 mm." in text
    assert "Found 6 planes and 1 cylinder." in text
    assert "Provenance: synthetic." in text


def test_dimension_order_is_stable_by_frame_axis() -> None:
    """Planes are ordered by frame axis, then position; cylinders by radius."""
    names = [line.split(" =")[0] for line in _dimension_lines(_bracket_report())]
    assert names == [
        "width",
        "depth",
        "height",
        "cyl_bore_1_diameter",
        "cyl_bore_1_length",
    ]


def test_gap_uncertainty_combines_both_planes() -> None:
    """height uses the quadrature sum of the two residuals and both counts."""
    line = next(
        line for line in _dimension_lines(_bracket_report()) if line.startswith("height")
    )
    # sqrt(0.30^2 + 0.28^2) = 0.410..., 7300 + 6900 = 14200
    assert line.endswith("RMS 0.4 mm, 14200 points.")


def test_relations_name_the_snap_that_produced_them() -> None:
    text = _bracket_report()
    assert (
        "cyl_bore_1 axis is perpendicular to plane_bottom, snapped from 89.2 degrees, "
        "deviation 0.8 degrees." in text
    )
    assert "cyl_bore_1 center is 15.1 mm from plane_left and 20.0 mm from plane_front." in text


def test_snap_log_is_verbatim_and_unrounded() -> None:
    """The snap log shows the change; rounding it to one decimal would hide it."""
    text = _bracket_report()
    assert (
        "height: raw 20.23, snapped 20.2, deviation -0.03, "
        "rule length-round 0.1mm within 2xRMS." in text
    )
    assert (
        "cyl_bore_1_radius: raw 6.2372, snapped 6.25, deviation 0.0128, "
        "rule radius-cluster 2xRMS." in text
    )


def test_every_snap_record_appears() -> None:
    text = _bracket_report()
    for snap in _bracket_scene().snaps:
        assert f"{snap.dim_name}: raw " in text


def test_caveats_carry_the_embargoed_claims_list() -> None:
    text = _bracket_report()
    assert "This report is a scan draft, not a measurement record." in text
    assert "No accuracy claim of the form plus or minus X millimetres" in text
    assert "Synthetic results verify plumbing only." in text
    assert "sub-millimetre claim is made here, ever." in text


def test_threshold_overrides_are_echoed() -> None:
    """PLAN.md section 3: an override may never be applied silently."""
    text = render_report(
        _bracket_scene(),
        regime=FINE,
        overrides={"ransac_epsilon_mm": 0.15, "angular_snap_deg": 2.0},
    )
    assert "Threshold regime: fine." in text
    assert "Threshold override: angular_snap_deg set to 2.0." in text
    assert "Threshold override: ransac_epsilon_mm set to 0.15." in text
    assert "No threshold overrides were used." not in text


def test_no_overrides_says_so() -> None:
    assert "No threshold overrides were used." in _bracket_report()


def test_empty_scene_still_renders_a_usable_report() -> None:
    """A scan that fitted nothing must still speak, and must not crash."""
    text = render_report(
        SceneModel(frame=(), planes=[], cylinders=[], snaps=[], provenance="synthetic")
    )
    assert "No primitives were fitted, so there is no bounding box." in text
    assert "Found 0 planes and 0 cylinders." in text
    assert "No dimensions could be derived from the fitted primitives." in text
    assert "No relations could be derived from the fitted primitives." in text
    assert "No values were snapped." in text
    assert "Section 5. Caveats." in text


def test_unfitted_frame_is_declared_not_assumed() -> None:
    """Without a frame the report says so instead of implying an alignment."""
    scene = _bracket_scene()
    unframed = SceneModel(
        frame=(),
        planes=scene.planes,
        cylinders=scene.cylinders,
        snaps=scene.snaps,
        provenance="photogrammetry-mesh",
    )
    text = render_report(unframed)
    assert "No object frame was fitted" in text
    assert "Provenance: photogrammetry-mesh." in text


def test_sections_appear_once_and_in_order() -> None:
    text = _bracket_report()
    headings = [line for line in text.splitlines() if line.startswith("Section ")]
    assert headings == [
        "Section 1. Overview.",
        "Section 2. Dimensions.",
        "Section 3. Relations.",
        "Section 4. Snap log.",
        "Section 5. Caveats.",
    ]


def test_report_is_deterministic() -> None:
    assert _bracket_report() == _bracket_report()
