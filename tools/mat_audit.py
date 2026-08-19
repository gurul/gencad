"""ChArUco mat scale audit -- a standalone AUDIT tool, not a pipeline stage.

What this is for (SYNTHESIS.md ruling 2): the morning scale cross-check. A
printed ChArUco mat of known physical size sits under the scanned object. This
tool detects the mat in a handful of the capture stills, solves each camera
pose against the mat with the user's intrinsics, and reports the metric scale
implied by the mat -- so the reconstruction's own scale can be checked against
an independent ruler.

What this is NOT, and may never become:
  - not a pipeline stage: nothing under src/scan2cad imports this file
  - not a pose source: the poses computed here are never fed to a fitter
  - not part of the accuracy model: the two-channel model (scan is a draft,
    caliper is truth) does not depend on any number produced here

Board specification, fixed by PLAN.md section 4 (WI-11) and not tunable:
  dictionary DICT_5X5_1000, 7 by 5 squares, 20 mm square, 15 mm marker.

Units: millimetres everywhere. Pixel coordinates are floats in image space.

Scale definition used throughout: `scale_mm_per_unit` is the number of true
millimetres per one unit of the reconstruction's coordinate system. A
photogrammetry mesh that is already metric in metres has a true scale of
1000.0 mm per unit; one that is metric in millimetres has 1.0.

The caliper correction (`--mat-scale-correction FACTOR`) is measured span
divided by nominal span of the printed mat. Home printers are commonly off by
about 0.2 percent, which is the same order as the errors this tool is meant to
detect, so the correction is mandatory in the morning and defaults to 1.0 only
so that synthetic self-tests can run without it.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

# --- frozen board specification -------------------------------------------

DICT_NAME = "DICT_5X5_1000"
SQUARES_X = 7
SQUARES_Y = 5
SQUARE_MM = 20.0
MARKER_MM = 15.0

# Nominal span measured with a caliper in the morning: the full width of the
# black-and-white grid, 7 squares across.
NOMINAL_SPAN_MM = SQUARES_X * SQUARE_MM

PRINT_DPI = 300
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

# Chessboard inner corners; the quantity solvePnP actually consumes.
N_CORNERS = (SQUARES_X - 1) * (SQUARES_Y - 1)

# Minimum inner corners for a usable pose. Four is the algebraic minimum for a
# planar PnP; eight keeps a single bad detection from dominating a pose.
MIN_CORNERS_FOR_POSE = 8


# --- results ---------------------------------------------------------------


@dataclass(frozen=True)
class BoardPose:
    """One camera pose solved against the mat.

    Assumes the image points came from `detect_corners` (or a synthetic
    projector) and are expressed in the same pixel convention as the supplied
    intrinsics. `camera_center_mm` is the camera centre in the mat's own
    coordinate frame, already multiplied by the caliper correction, so it is in
    true millimetres. `reproj_rms_px` is the RMS reprojection residual over the
    corners used; it is the only honest quality signal this tool has.
    """

    label: str
    rvec: tuple[float, float, float]
    tvec_mm: tuple[float, float, float]
    camera_center_mm: tuple[float, float, float]
    n_corners: int
    reproj_rms_px: float


@dataclass(frozen=True)
class ScaleAudit:
    """The scale implied by the mat, compared against a reconstruction.

    `scale_mm_per_unit` is the median over all camera pairs of (mat-derived
    distance in mm) / (reconstruction distance in reconstruction units). The
    median is used rather than the mean because one mis-detected board in a
    five-image set would otherwise move the answer.

    `spread_pct` is (max - min) / median over the pairs, in percent. It is the
    tool's self-consistency check: a small spread means the pairs agree, it
    does not mean the answer is right.
    """

    scale_mm_per_unit: float
    spread_pct: float
    n_pairs: int
    pair_scales: tuple[tuple[str, str, float], ...]


# --- board construction ----------------------------------------------------


def make_board() -> cv2.aruco.CharucoBoard:
    """Build the frozen ChArUco board object.

    Assumes opencv 4.13 or newer, where CharucoBoard takes a (cols, rows) size
    tuple and the CharucoDetector class exists.
    """
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICT_NAME))
    return cv2.aruco.CharucoBoard(
        (SQUARES_X, SQUARES_Y), SQUARE_MM, MARKER_MM, dictionary
    )


def board_object_points_mm(
    board: cv2.aruco.CharucoBoard, correction: float = 1.0
) -> np.ndarray:
    """Return the (N_CORNERS, 3) chessboard corner coordinates in true mm.

    Assumes `correction` is measured span over nominal span for the actual
    printed sheet. The board's own coordinates are nominal, so the whole plane
    is scaled by the correction to become true millimetres.
    """
    if not np.isfinite(correction) or correction <= 0.0:
        raise ValueError(f"mat scale correction must be positive, got {correction!r}")
    return np.asarray(board.getChessboardCorners(), dtype=np.float64) * float(correction)


# --- printable board -------------------------------------------------------


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    """Serialise one PNG chunk with its CRC."""
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _png_with_metadata(png_bytes: bytes, dpi: int, text: dict[str, str]) -> bytes:
    """Insert pHYs (physical resolution) and tEXt chunks after IHDR.

    Assumes `png_bytes` is a well-formed PNG whose first chunk is a standard
    13-byte IHDR, which is what cv2.imwrite produces. The pHYs chunk is what
    makes a print dialog offer a true 100 percent scale; the tEXt chunks carry
    the nominal span so the file is self-describing if it is ever mailed around
    without this repository.
    """
    ihdr_end = 8 + 4 + 4 + 13 + 4
    px_per_metre = int(round(dpi / 0.0254))
    extra = _png_chunk(b"pHYs", struct.pack(">IIB", px_per_metre, px_per_metre, 1))
    for key, value in text.items():
        extra += _png_chunk(
            b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1")
        )
    return png_bytes[:ihdr_end] + extra + png_bytes[ihdr_end:]


def _draw_caption(
    page: np.ndarray, lines: list[str], x: int, y: int, max_width_px: int
) -> None:
    """Draw ASCII caption lines under the board, sized to fit the page width.

    Assumes `lines` are plain ASCII. The font scale is chosen from the widest
    line so that nothing runs off the sheet; the caption is printed matter, not
    screen output, and it repeats the facts a reader needs while holding the
    caliper.
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    widest = max(cv2.getTextSize(line, font, 1.0, 2)[0][0] for line in lines)
    scale = min(2.0, max_width_px / float(widest))
    step = int(cv2.getTextSize("Mg", font, scale, 2)[0][1] * 2.0)
    for i, line in enumerate(lines):
        cv2.putText(
            page, line, (x, y + step * (i + 1)), font, scale, 0, 2, cv2.LINE_AA
        )


def render_printable_board(out_path: Path, dpi: int = PRINT_DPI) -> dict[str, float]:
    """Write the printable A4 mat and return its measured-on-paper geometry.

    Assumes the printer is told to print at 100 percent with no fit-to-page.
    One square is rounded to a whole number of pixels, so the rendered span is
    a few hundredths of a millimetre away from the geometric nominal; the
    returned `rendered_span_mm` is the honest number to compare a caliper
    against, and it is also stamped into the PNG metadata and the caption.

    Returns a dict with keys: rendered_span_mm, nominal_span_mm, square_mm, dpi.
    """
    px_per_mm = dpi / 25.4
    square_px = int(round(SQUARE_MM * px_per_mm))
    board_w = square_px * SQUARES_X
    board_h = square_px * SQUARES_Y
    rendered_span_mm = board_w / px_per_mm

    board = make_board()
    grid = board.generateImage((board_w, board_h))

    page_w = int(round(A4_WIDTH_MM * px_per_mm))
    page_h = int(round(A4_HEIGHT_MM * px_per_mm))
    if board_w > page_w or board_h > page_h:
        raise ValueError("board does not fit on A4 at this dpi")
    page = np.full((page_h, page_w), 255, dtype=np.uint8)
    x0 = (page_w - board_w) // 2
    y0 = int(round(25.0 * px_per_mm))
    page[y0 : y0 + board_h, x0 : x0 + board_w] = grid

    lines = [
        f"scan2cad ChArUco scale mat. {DICT_NAME}.",
        f"{SQUARES_X} by {SQUARES_Y} squares, {SQUARE_MM:.0f} mm square,"
        f" {MARKER_MM:.0f} mm marker.",
        "Print at 100 percent. Do not fit to page.",
        f"Nominal span across {SQUARES_X} squares: {rendered_span_mm:.2f} mm.",
        "Measure that span with a caliper.",
        "Correction is measured span divided by nominal span.",
    ]
    _draw_caption(page, lines, x0, y0 + board_h + int(12 * px_per_mm), page_w - 2 * x0)

    ok, buf = cv2.imencode(".png", page)
    if not ok:
        raise RuntimeError("failed to encode the board PNG")
    meta = {
        "Title": "scan2cad ChArUco scale mat",
        "Description": (
            f"{DICT_NAME} {SQUARES_X}x{SQUARES_Y} squares, {SQUARE_MM:.1f} mm square, "
            f"{MARKER_MM:.1f} mm marker, rendered span {rendered_span_mm:.2f} mm "
            f"at {dpi} dpi. Print at 100 percent."
        ),
        "Software": "scan2cad tools/mat_audit.py",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_png_with_metadata(buf.tobytes(), dpi, meta))
    return {
        "rendered_span_mm": rendered_span_mm,
        "nominal_span_mm": NOMINAL_SPAN_MM,
        "square_mm": square_px / px_per_mm,
        "dpi": float(dpi),
    }


# --- detection and pose ----------------------------------------------------


def detect_corners(
    image: np.ndarray, board: cv2.aruco.CharucoBoard
) -> tuple[np.ndarray, np.ndarray]:
    """Detect ChArUco inner corners in one image.

    Assumes `image` is a grayscale or BGR uint8 array of a scene containing the
    printed mat. Returns (ids of shape (N,), image points of shape (N, 2)) with
    N possibly zero; partial detections are normal and usable, the caller
    decides whether N is enough.
    """
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    detector = cv2.aruco.CharucoDetector(board)
    corners, ids, _marker_corners, _marker_ids = detector.detectBoard(gray)
    if ids is None or corners is None or len(ids) == 0:
        return np.zeros((0,), dtype=np.int32), np.zeros((0, 2), dtype=np.float64)
    return (
        np.asarray(ids, dtype=np.int32).reshape(-1),
        np.asarray(corners, dtype=np.float64).reshape(-1, 2),
    )


def solve_board_pose(
    label: str,
    corner_ids: np.ndarray,
    image_points: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    board: cv2.aruco.CharucoBoard,
    correction: float = 1.0,
) -> BoardPose:
    """Solve one camera pose against the mat.

    Assumes `corner_ids` index the board's chessboard corners and
    `image_points` are the matching pixel coordinates, both in detection order.
    Intrinsics are the user's own: this tool never estimates focal length,
    because a focal length fitted from the same corners would make the scale
    check circular.

    Raises ValueError if fewer than MIN_CORNERS_FOR_POSE corners are supplied
    or if solvePnP fails to converge.
    """
    corner_ids = np.asarray(corner_ids, dtype=np.int32).reshape(-1)
    image_points = np.asarray(image_points, dtype=np.float64).reshape(-1, 2)
    if corner_ids.shape[0] != image_points.shape[0]:
        raise ValueError("corner ids and image points must have the same length")
    if corner_ids.shape[0] < MIN_CORNERS_FOR_POSE:
        raise ValueError(
            f"{label}: only {corner_ids.shape[0]} mat corners found, "
            f"need at least {MIN_CORNERS_FOR_POSE}"
        )
    obj = board_object_points_mm(board, correction)[corner_ids]
    ok, rvec, tvec = cv2.solvePnP(
        obj.astype(np.float64),
        image_points.astype(np.float64),
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        raise ValueError(f"{label}: pose solve failed on {corner_ids.shape[0]} corners")
    projected, _ = cv2.projectPoints(obj, rvec, tvec, camera_matrix, dist_coeffs)
    residual = projected.reshape(-1, 2) - image_points
    rms = float(np.sqrt(np.mean(np.sum(residual * residual, axis=1))))
    rot, _ = cv2.Rodrigues(rvec)
    centre = (-rot.T @ tvec.reshape(3, 1)).reshape(3)
    return BoardPose(
        label=label,
        rvec=tuple(float(v) for v in rvec.reshape(3)),
        tvec_mm=tuple(float(v) for v in tvec.reshape(3)),
        camera_center_mm=(float(centre[0]), float(centre[1]), float(centre[2])),
        n_corners=int(corner_ids.shape[0]),
        reproj_rms_px=rms,
    )


def estimate_scale(
    poses: list[BoardPose], recon_centers: dict[str, tuple[float, float, float]]
) -> ScaleAudit:
    """Compare mat-derived camera geometry against a reconstruction's own.

    Assumes `recon_centers` maps a pose label to that camera's centre in the
    reconstruction's coordinate units (any units, any origin, any rotation --
    only inter-camera distances are used, so a rigid transform between the two
    frames cancels out).

    Raises ValueError if fewer than two labels are shared, or if a camera pair
    is degenerate (coincident centres in either frame).
    """
    shared = [p for p in poses if p.label in recon_centers]
    if len(shared) < 2:
        raise ValueError(
            "need at least two images present in both the mat poses and the "
            "reconstruction poses to compare scale"
        )
    ratios: list[tuple[str, str, float]] = []
    for a, b in combinations(shared, 2):
        d_mm = float(
            np.linalg.norm(
                np.array(a.camera_center_mm) - np.array(b.camera_center_mm)
            )
        )
        d_unit = float(
            np.linalg.norm(
                np.array(recon_centers[a.label], dtype=np.float64)
                - np.array(recon_centers[b.label], dtype=np.float64)
            )
        )
        if d_mm <= 0.0 or d_unit <= 0.0:
            raise ValueError(
                f"cameras {a.label} and {b.label} are coincident in one frame"
            )
        ratios.append((a.label, b.label, d_mm / d_unit))
    values = np.array([r[2] for r in ratios], dtype=np.float64)
    median = float(np.median(values))
    spread = float((values.max() - values.min()) / median * 100.0)
    return ScaleAudit(
        scale_mm_per_unit=median,
        spread_pct=spread,
        n_pairs=len(ratios),
        pair_scales=tuple(ratios),
    )


# --- synthetic validation --------------------------------------------------


def default_camera_matrix(
    width: int = 4032, height: int = 3024, focal_px: float = 3200.0
) -> np.ndarray:
    """A plausible phone-camera intrinsic matrix for synthetic work only.

    Assumes a pinhole camera with square pixels and a centred principal point.
    Real runs must pass the user's measured intrinsics; this exists so the
    self-test has a known ground truth to recover.
    """
    return np.array(
        [[focal_px, 0.0, width / 2.0], [0.0, focal_px, height / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rotation from mat frame to camera frame for a camera at `eye`.

    Assumes the camera is not directly above the target along the world up
    axis, which would make the up vector degenerate; the synthetic poses are
    chosen off-axis for that reason.
    """
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    up_hint = np.array([0.0, 0.0, 1.0])
    right = np.cross(forward, up_hint)
    norm = np.linalg.norm(right)
    if norm < 1e-9:
        raise ValueError("degenerate synthetic camera pose: looking along world up")
    right = right / norm
    down = np.cross(forward, right)
    return np.stack([right, down, forward], axis=0)


def synthesize_views(
    board: cv2.aruco.CharucoBoard,
    camera_matrix: np.ndarray,
    true_correction: float = 1.0,
    pixel_noise_px: float = 0.0,
    seed: int = 1337,
    n_views: int = 5,
) -> tuple[list[tuple[str, np.ndarray, np.ndarray]], dict[str, tuple[float, float, float]]]:
    """Project the mat's corners through known pinhole cameras.

    This is the whole of tonight's validation: no rendered images, no detector,
    just exact corner projections plus iid Gaussian pixel noise, so that the
    scale recovery is tested in isolation from detection quality.

    Assumes a lens-distortion-free camera. Returns (views, true camera centres)
    where each view is (label, corner ids, image points in pixels) and the
    centres are in true millimetres in the mat frame.
    """
    rng = np.random.default_rng(seed)
    obj = board_object_points_mm(board, true_correction)
    target = obj.mean(axis=0)
    views: list[tuple[str, np.ndarray, np.ndarray]] = []
    centres: dict[str, tuple[float, float, float]] = {}
    for i in range(n_views):
        angle = 2.0 * np.pi * i / n_views
        radius = 180.0 + 20.0 * i
        height = 240.0 + 30.0 * ((i % 3) - 1)
        eye = target + np.array(
            [radius * np.cos(angle), radius * np.sin(angle), height]
        )
        rot = _look_at(eye, target)
        tvec = -rot @ eye
        projected, _ = cv2.projectPoints(
            obj,
            cv2.Rodrigues(rot)[0],
            tvec.reshape(3, 1),
            camera_matrix,
            np.zeros(5),
        )
        pts = projected.reshape(-1, 2)
        if pixel_noise_px > 0.0:
            pts = pts + rng.normal(0.0, pixel_noise_px, size=pts.shape)
        label = f"synthetic_{i:02d}"
        views.append((label, np.arange(obj.shape[0], dtype=np.int32), pts))
        centres[label] = (float(eye[0]), float(eye[1]), float(eye[2]))
    return views, centres


def run_self_test(
    noise_levels: tuple[float, ...] = (0.0, 0.3, 0.5, 1.0),
    true_correction: float = 1.002,
    recon_mm_per_unit: float = 1000.0,
    seed: int = 1337,
) -> list[tuple[float, float]]:
    """Recover a known scale from synthetic views at several pixel-noise levels.

    Assumes the reconstruction is metric-in-metres by default, so the scale to
    recover is 1000.0 mm per unit. Returns a list of (pixel noise, relative
    scale error in percent), which is the degradation curve WI-11 asks for.
    """
    board = make_board()
    camera_matrix = default_camera_matrix()
    dist = np.zeros(5)
    curve: list[tuple[float, float]] = []
    for noise in noise_levels:
        views, centres = synthesize_views(
            board,
            camera_matrix,
            true_correction=true_correction,
            pixel_noise_px=noise,
            seed=seed,
        )
        poses = [
            solve_board_pose(
                label, ids, pts, camera_matrix, dist, board, correction=true_correction
            )
            for label, ids, pts in views
        ]
        recon = {
            label: tuple(c / recon_mm_per_unit for c in centre)
            for label, centre in centres.items()
        }
        audit = estimate_scale(poses, recon)
        err_pct = abs(audit.scale_mm_per_unit - recon_mm_per_unit) / recon_mm_per_unit * 100.0
        curve.append((noise, err_pct))
    return curve


# --- command line ----------------------------------------------------------


def _load_intrinsics(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a camera intrinsics JSON file.

    Assumes the file holds fx, fy, cx, cy and an optional "dist" list of up to
    five distortion coefficients in OpenCV order.
    """
    data = json.loads(path.read_text())
    camera_matrix = np.array(
        [
            [float(data["fx"]), 0.0, float(data["cx"])],
            [0.0, float(data["fy"]), float(data["cy"])],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist = np.array(data.get("dist", [0.0] * 5), dtype=np.float64).reshape(-1, 1)
    return camera_matrix, dist


def _cmd_board(args: argparse.Namespace) -> int:
    info = render_printable_board(Path(args.out), dpi=args.dpi)
    print("Wrote the printable ChArUco mat.")
    print(f"File: {args.out}")
    print(f"Dictionary: {DICT_NAME}")
    print(f"Grid: {SQUARES_X} by {SQUARES_Y} squares.")
    print(f"Square: {SQUARE_MM:.1f} mm nominal. Marker: {MARKER_MM:.1f} mm nominal.")
    print(f"Print resolution: {int(info['dpi'])} dots per inch.")
    print("Print at 100 percent scale. Do not fit to page.")
    print(f"Nominal span across {SQUARES_X} squares: {info['rendered_span_mm']:.2f} mm.")
    print("Measure that span with the caliper after printing.")
    print("Correction factor is measured span divided by nominal span.")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    board = make_board()
    camera_matrix, dist = _load_intrinsics(Path(args.intrinsics))
    poses: list[BoardPose] = []
    print("ChArUco mat scale audit.")
    print("This is an audit tool. Its numbers never enter the fitting pipeline.")
    print(f"Mat scale correction applied: {args.mat_scale_correction:.5f}.")
    for image_path in args.images:
        path = Path(image_path)
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            print(f"Image {path.name}: could not be read. Skipped.")
            continue
        ids, pts = detect_corners(image, board)
        try:
            pose = solve_board_pose(
                path.name,
                ids,
                pts,
                camera_matrix,
                dist,
                board,
                correction=args.mat_scale_correction,
            )
        except ValueError as exc:
            print(f"Image {path.name}: {exc}. Skipped.")
            continue
        poses.append(pose)
        distance = float(np.linalg.norm(np.array(pose.camera_center_mm)))
        print(
            f"Image {path.name}: {pose.n_corners} mat corners, "
            f"reprojection RMS {pose.reproj_rms_px:.2f} pixels, "
            f"camera {distance:.1f} mm from the mat origin."
        )
    if len(poses) < 2:
        print("Fewer than two usable images. No scale can be reported.")
        return 1
    if not args.recon_poses:
        print("No reconstruction poses given, so no scale ratio was computed.")
        print("Camera distances above are in true millimetres from the mat.")
        print("Pass --recon-poses to compare against the reconstruction scale.")
        return 0
    recon_raw = json.loads(Path(args.recon_poses).read_text())
    recon = {k: tuple(float(v) for v in val) for k, val in recon_raw.items()}
    try:
        audit = estimate_scale(poses, recon)
    except ValueError as exc:
        print(f"Scale comparison failed: {exc}")
        return 1
    print(f"Camera pairs compared: {audit.n_pairs}.")
    print(f"Implied scale: {audit.scale_mm_per_unit:.4f} mm per reconstruction unit.")
    print(f"Agreement spread across pairs: {audit.spread_pct:.2f} percent.")
    print("A metric mesh in metres should read close to 1000 mm per unit.")
    print("A metric mesh in millimetres should read close to 1 mm per unit.")
    print("A large spread means the mat detections disagree, not that the mesh is wrong.")
    return 0


def _cmd_self_test(args: argparse.Namespace) -> int:
    print("Synthetic scale recovery self test.")
    print("Fully synthetic. This says nothing about real capture accuracy.")
    curve = run_self_test(seed=args.seed)
    for noise, err_pct in curve:
        print(f"Pixel noise {noise:.1f} px: scale error {err_pct:.4f} percent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        description=(
            "ChArUco mat scale audit. Standalone audit tool, not a pipeline stage."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_board = sub.add_parser("board", help="write the printable A4 mat PNG")
    p_board.add_argument("--out", default="out/charuco_a4.png")
    p_board.add_argument("--dpi", type=int, default=PRINT_DPI)
    p_board.set_defaults(func=_cmd_board)

    p_audit = sub.add_parser("audit", help="audit scale from images of the mat")
    p_audit.add_argument("images", nargs="+")
    p_audit.add_argument(
        "--intrinsics", required=True, help="JSON with fx, fy, cx, cy and optional dist"
    )
    p_audit.add_argument(
        "--recon-poses",
        default=None,
        help="JSON mapping image file name to camera centre in reconstruction units",
    )
    p_audit.add_argument(
        "--mat-scale-correction",
        type=float,
        default=1.0,
        help="caliper measured span divided by nominal span of the printed mat",
    )
    p_audit.set_defaults(func=_cmd_audit)

    p_self = sub.add_parser("self-test", help="synthetic scale recovery curve")
    p_self.add_argument("--seed", type=int, default=1337)
    p_self.set_defaults(func=_cmd_self_test)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
