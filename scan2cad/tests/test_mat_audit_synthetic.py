"""Synthetic validation of the ChArUco mat scale audit (WI-11).

Everything here is synthetic: exact corner projections through a known pinhole
camera, plus iid Gaussian pixel noise. That proves the scale arithmetic and the
board plumbing, and it proves nothing whatsoever about real capture accuracy
(PLAN.md ground rule 7).

The audit tool lives in tools/, which is not an installed package, so this file
puts tools/ on sys.path rather than relying on the pytest pythonpath setting
that covers src/ only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import mat_audit  # noqa: E402

# Pre-declared acceptance thresholds from PLAN.md section 4, WI-11.
CLEAN_TOLERANCE_PCT = 0.1
NOISE_1PX_TOLERANCE_PCT = 0.5

# The scale the self test has to recover: a reconstruction expressed in metres.
RECON_MM_PER_UNIT = 1000.0
# A deliberately imperfect print, of the size a home printer really produces.
TRUE_CORRECTION = 1.002


def _scale_error_pct(pixel_noise_px: float, seed: int) -> float:
    """Recover the known scale from synthetic views and return the error in percent."""
    board = mat_audit.make_board()
    camera_matrix = mat_audit.default_camera_matrix()
    dist = np.zeros(5)
    views, centres = mat_audit.synthesize_views(
        board,
        camera_matrix,
        true_correction=TRUE_CORRECTION,
        pixel_noise_px=pixel_noise_px,
        seed=seed,
    )
    poses = [
        mat_audit.solve_board_pose(
            label, ids, pts, camera_matrix, dist, board, correction=TRUE_CORRECTION
        )
        for label, ids, pts in views
    ]
    recon = {
        label: tuple(c / RECON_MM_PER_UNIT for c in centre)
        for label, centre in centres.items()
    }
    audit = mat_audit.estimate_scale(poses, recon)
    return abs(audit.scale_mm_per_unit - RECON_MM_PER_UNIT) / RECON_MM_PER_UNIT * 100.0


def test_board_specification_is_the_frozen_one() -> None:
    assert mat_audit.DICT_NAME == "DICT_5X5_1000"
    assert (mat_audit.SQUARES_X, mat_audit.SQUARES_Y) == (7, 5)
    assert mat_audit.SQUARE_MM == 20.0
    assert mat_audit.MARKER_MM == 15.0
    assert mat_audit.NOMINAL_SPAN_MM == 140.0


def test_object_points_are_planar_and_correction_scales_them() -> None:
    board = mat_audit.make_board()
    obj = mat_audit.board_object_points_mm(board)
    assert obj.shape == (mat_audit.N_CORNERS, 3)
    assert np.allclose(obj[:, 2], 0.0)
    span = obj[:, 0].max() - obj[:, 0].min()
    assert span == pytest.approx(
        (mat_audit.SQUARES_X - 2) * mat_audit.SQUARE_MM, abs=1e-6
    )
    corrected = mat_audit.board_object_points_mm(board, 1.01)
    assert np.allclose(corrected, obj * 1.01)


def test_object_points_reject_a_nonsense_correction() -> None:
    board = mat_audit.make_board()
    with pytest.raises(ValueError):
        mat_audit.board_object_points_mm(board, 0.0)


def test_scale_recovery_is_exact_on_clean_synthetic_views() -> None:
    assert _scale_error_pct(0.0, seed=1337) < CLEAN_TOLERANCE_PCT


def test_scale_recovery_survives_one_pixel_of_noise() -> None:
    errors = [_scale_error_pct(1.0, seed=s) for s in (1337, 7, 42, 101, 2024)]
    worst = max(errors)
    assert worst < NOISE_1PX_TOLERANCE_PCT, f"worst scale error {worst:.3f} percent"


def test_degradation_curve_stays_inside_the_declared_band() -> None:
    curve = mat_audit.run_self_test(seed=1337)
    assert [n for n, _ in curve] == [0.0, 0.3, 0.5, 1.0]
    by_noise = dict(curve)
    assert by_noise[0.0] < CLEAN_TOLERANCE_PCT
    assert by_noise[0.3] < CLEAN_TOLERANCE_PCT
    assert by_noise[1.0] < NOISE_1PX_TOLERANCE_PCT


def test_reported_scale_tracks_the_caliper_correction() -> None:
    """A 1 percent bigger printed mat implies a 1 percent bigger world."""
    board = mat_audit.make_board()
    camera_matrix = mat_audit.default_camera_matrix()
    dist = np.zeros(5)
    views, centres = mat_audit.synthesize_views(
        board, camera_matrix, true_correction=1.0, pixel_noise_px=0.0, seed=5
    )
    recon = {label: tuple(c / 1000.0 for c in centre) for label, centre in centres.items()}
    scales = []
    for correction in (1.0, 1.01):
        poses = [
            mat_audit.solve_board_pose(
                label, ids, pts, camera_matrix, dist, board, correction=correction
            )
            for label, ids, pts in views
        ]
        scales.append(mat_audit.estimate_scale(poses, recon).scale_mm_per_unit)
    assert scales[1] / scales[0] == pytest.approx(1.01, rel=1e-6)


def test_pose_solve_refuses_too_few_corners() -> None:
    board = mat_audit.make_board()
    with pytest.raises(ValueError, match="need at least"):
        mat_audit.solve_board_pose(
            "short",
            np.arange(4, dtype=np.int32),
            np.zeros((4, 2)),
            mat_audit.default_camera_matrix(),
            np.zeros(5),
            board,
        )


def test_scale_needs_two_shared_cameras() -> None:
    board = mat_audit.make_board()
    camera_matrix = mat_audit.default_camera_matrix()
    views, centres = mat_audit.synthesize_views(
        board, camera_matrix, pixel_noise_px=0.0, seed=3
    )
    poses = [
        mat_audit.solve_board_pose(
            label, ids, pts, camera_matrix, np.zeros(5), board
        )
        for label, ids, pts in views
    ]
    only_one = {poses[0].label: centres[poses[0].label]}
    with pytest.raises(ValueError, match="at least two images"):
        mat_audit.estimate_scale(poses, only_one)


def test_printable_board_is_a4_at_300_dpi_and_carries_its_span(tmp_path: Path) -> None:
    import cv2

    out = tmp_path / "charuco_a4.png"
    info = mat_audit.render_printable_board(out)
    raw = out.read_bytes()
    assert raw.startswith(b"\x89PNG")
    # 300 dpi is 11811 pixels per metre, written into the pHYs chunk so that a
    # print dialog can offer a true 100 percent scale.
    assert b"pHYs" in raw
    assert struct_ppm(raw) == 11811
    assert b"scan2cad ChArUco scale mat" in raw
    assert f"{info['rendered_span_mm']:.2f} mm".encode("latin-1") in raw

    page = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    assert page is not None
    assert page.shape == (3508, 2480)
    # The rounding to whole pixels costs less than a tenth of a millimetre; the
    # caliper correction step absorbs it, but it must not be worse than that.
    assert abs(info["rendered_span_mm"] - mat_audit.NOMINAL_SPAN_MM) < 0.2


def test_rendered_board_is_detectable(tmp_path: Path) -> None:
    """The printed mat must survive a round trip through the detector."""
    import cv2

    out = tmp_path / "charuco_a4.png"
    mat_audit.render_printable_board(out)
    page = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    board = mat_audit.make_board()
    ids, pts = mat_audit.detect_corners(page, board)
    assert ids.shape[0] == mat_audit.N_CORNERS
    assert pts.shape == (mat_audit.N_CORNERS, 2)


def struct_ppm(png_bytes: bytes) -> int:
    """Return the pixels-per-metre recorded in a PNG's pHYs chunk.

    Assumes the chunk exists; used by the printable-board test only.
    """
    import struct

    index = png_bytes.index(b"pHYs")
    return int(struct.unpack(">I", png_bytes[index + 4 : index + 8])[0])
