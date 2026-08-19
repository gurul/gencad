"""Print one sharpness number per capture frame, so a blind user can judge focus.

Why this exists: docs/MORNING_PROTOCOL.md step 11 decides whether to open the
autofocus-lock contingency. That decision was originally written as "the
reconstruction visibly fails" and "look for blurry frames", which is not a test
a user working without sight can run. This tool turns the blur half of it into a
number per file.

What the number is. The variance of the Laplacian of the greyscale image: a
standard, crude focus measure. High means lots of fine detail, low means smooth,
which usually means out of focus or motion blurred. It is NOT calibrated and the
absolute value is meaningless -- a textured object scores higher than a smooth
one at the same focus. Only the spread within one capture session means
anything, which is why the summary reports each frame against the median of the
session.

HEIC files, which is what an iPhone AirDrops, are not readable by OpenCV. On
macOS they are converted through `sips` into a temporary JPEG first. If `sips`
is missing the file is reported as unreadable and skipped, by name.

Usage:

    .venv/bin/python tools/frame_sharpness.py PHOTOS/*.HEIC

Reading the output: frames flagged "far below the session median" are the
candidates for focus or exposure hunting. A handful is normal. If a third of the
session is flagged, that is the evidence step 11 asks for.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

# A frame scoring below this fraction of the session median is called out. It is
# a reporting threshold for a human, not a pipeline parameter: nothing downstream
# reads it, and it never changes a fitted number.
LOW_FRACTION = 0.4

# Extensions OpenCV cannot open on this Mac and that `sips` can convert.
_NEEDS_CONVERSION = (".heic", ".heif")


def _read_grey(path: Path) -> np.ndarray | None:
    """Return the image at `path` as greyscale, converting HEIC if needed.

    Returns None when the file cannot be read at all, so the caller can name it
    and carry on rather than aborting a session of eighty photographs on one
    bad file.
    """
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is not None:
        return image
    if path.suffix.lower() not in _NEEDS_CONVERSION:
        return None
    with tempfile.TemporaryDirectory() as work:
        jpeg = Path(work) / (path.stem + ".jpg")
        try:
            subprocess.run(
                ["sips", "-s", "format", "jpeg", str(path), "--out", str(jpeg)],
                capture_output=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if not jpeg.is_file():
            return None
        return cv2.imread(str(jpeg), cv2.IMREAD_GRAYSCALE)


def sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian of `image`. Assumes a single-channel array."""
    return float(cv2.Laplacian(image, cv2.CV_64F).var())


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 if at least one frame was measured."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", nargs="+")
    args = parser.parse_args(argv)

    print("Frame sharpness. Higher is sharper. The scale is arbitrary.")
    print("Only the spread within one capture session means anything.")
    scores: list[tuple[str, float]] = []
    for name in args.images:
        path = Path(name)
        image = _read_grey(path)
        if image is None:
            print(f"{path.name}: could not be read. Skipped.")
            continue
        value = sharpness(image)
        scores.append((path.name, value))
        print(f"{path.name}: {value:.1f}")

    if not scores:
        print("No frames could be measured.")
        return 1

    values = [value for _name, value in scores]
    median = statistics.median(values)
    print(f"Frames measured: {len(scores)}.")
    print(f"Median sharpness: {median:.1f}.")
    low = [name for name, value in scores if value < LOW_FRACTION * median]
    if not low:
        print("No frame is far below the session median.")
        print("Focus hunting is not the explanation for a bad reconstruction.")
        return 0
    print(f"Frames far below the median: {len(low)} of {len(scores)}.")
    for name in low:
        print(f"Soft frame: {name}.")
    print("Delete those frames and reconstruct again before opening any gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
