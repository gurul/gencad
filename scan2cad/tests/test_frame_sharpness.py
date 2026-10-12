"""tools/frame_sharpness.py must not clear a session that is uniformly soft.

The tool compares each frame with the session median. When every frame is
equally out of focus, no frame stands out, and the tool must say that it
cannot tell -- not that focus is ruled out.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np

TOOL = Path(__file__).resolve().parent.parent / "tools" / "frame_sharpness.py"

WARNING = "It cannot detect a session where every frame is equally out of focus."
FALSE_ALL_CLEAR = "Focus hunting is not the explanation"


def _load_tool():
    spec = importlib.util.spec_from_file_location("frame_sharpness", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_frames(directory: Path, blur_sigma: float, count: int = 6) -> list[str]:
    rng = np.random.default_rng(7)
    names = []
    for index in range(count):
        texture = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)
        if blur_sigma > 0:
            texture = cv2.GaussianBlur(texture, (0, 0), blur_sigma)
        path = directory / f"frame_{index:02d}.png"
        assert cv2.imwrite(str(path), texture)
        names.append(str(path))
    return names


def test_uniformly_blurred_session_prints_the_limitation(tmp_path, capsys):
    tool = _load_tool()
    (tmp_path / "sharp").mkdir()
    (tmp_path / "blurred").mkdir()
    sharp = _write_frames(tmp_path / "sharp", 0.0)
    blurred = _write_frames(tmp_path / "blurred", 6.0)

    assert tool.main(sharp) == 0
    sharp_out = capsys.readouterr().out
    assert tool.main(blurred) == 0
    blurred_out = capsys.readouterr().out

    # The blur is real: the blurred session's median is far below the sharp one.
    def median(text: str) -> float:
        line = next(l for l in text.splitlines() if l.startswith("Median sharpness:"))
        return float(line.split(":")[1].strip().rstrip("."))

    assert median(blurred_out) < 0.1 * median(sharp_out)

    # No frame stands out within the blurred session ...
    assert "No frame is far below the session median." in blurred_out
    # ... and the tool says it cannot see uniform misfocus, instead of
    # clearing focus as the explanation.
    assert WARNING in blurred_out
    assert FALSE_ALL_CLEAR not in blurred_out
