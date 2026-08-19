"""Guard against the killed legs of the project creeping back into src/.

PLAN.md ground rules 2, 3, 4 and 8 kill the iOS/ARKit capture leg, the COLMAP
leg, the LiDAR/TSDF fusion leg and the sensor-realistic simulators. Those legs
die by absence, not by stub files, so the enforcement is a grep: no module
under src/ may mention them at all, in code or in comments.

The banned word "integration" specifically catches open3d's TSDF integration
module. If a future docstring genuinely needs the English word, rephrase it --
the ban is cheaper to keep absolute than to make clever.

Assumes this file lives in <repo>/tests/ and the package lives in <repo>/src/.
It reads source files only, so it runs with no third-party dependency and
passes before any other work item exists.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

# Tokens that must not occur anywhere under src/, matched case-insensitively
# on word boundaries so that "stray" is banned but "strayed" would not be a
# surprising false negative -- nothing legitimate in this codebase uses either.
BANNED_TOKENS = (
    "integration",
    "TSDF",
    "colmap",
    "pose_prior",
    "ARKit",
    "stray",
)

_BANNED_RE = re.compile(
    "|".join(rf"\b{re.escape(token)}\b" for token in BANNED_TOKENS),
    re.IGNORECASE,
)


def _python_sources() -> list[Path]:
    """Return every .py file under src/, sorted for stable failure output."""
    return sorted(SRC_DIR.rglob("*.py"))


def test_src_directory_exists() -> None:
    """The package tree must be present; an empty grep is not a pass."""
    assert SRC_DIR.is_dir(), f"missing source directory: {SRC_DIR}"
    assert _python_sources(), f"no python sources found under {SRC_DIR}"


def test_no_dead_imports() -> None:
    """No module under src/ mentions a killed capture, fusion or SfM leg."""
    hits: list[str] = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = _BANNED_RE.search(line)
            if match:
                rel = path.relative_to(SRC_DIR.parent)
                hits.append(f"{rel}:{lineno}: banned token {match.group(0)!r}: {line.strip()}")

    assert not hits, (
        "killed pipeline legs referenced in src/ (see PLAN.md ground rules 2, 3, 4, 8):\n"
        + "\n".join(hits)
    )


def test_frozen_thresholds_header_present() -> None:
    """thresholds.py must carry its FROZEN banner, unedited.

    SYNTHESIS.md ruling 6 forbids retuning the thresholds to make a run pass.
    The banner is the visible half of that contract; this test is the other.
    """
    text = (SRC_DIR / "scan2cad" / "thresholds.py").read_text(encoding="utf-8")
    assert "FROZEN 2026-08-19T" in text
    assert "do not tune to pass the sweep" in text
