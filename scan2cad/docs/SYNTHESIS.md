# Synthesis rulings (main-loop, 2026-08-19 overnight)

These rulings resolve the differences between the kill-review verdicts (docs/VERDICTS.md)
and the rebuild plan (docs/PLAN.md). Where they conflict, THIS file wins, then PLAN.md.

1. Product identity is fixed as the kill-review's surviving sentence: a screen-reader-native
   describe-and-draft tool -- mesh in, plain-language geometry report + editable
   named-dimension build123d script out, STEP for reference surfaces. Scan = draft,
   caliper/datasheet = truth. No precision claims, ever (see PLAN.md section 7 embargo list).

2. WI-11 (ChArUco mat audit) is KEPT despite kill-product's "skip ChArUco anything",
   because it is an independent AUDIT tool for the morning scale cross-check and the
   COLMAP contingency gate -- not a pipeline stage, not a pose source, and nothing in
   the two-channel accuracy model depends on it. It is the FIRST thing dropped on friction:
   if it costs more than ~1 hour of agent time, stub it (write the printable board PNG +
   a SKIPPED note in docs/CONTINGENCIES.md) and move on.

3. venv: `uv venv --python 3.12 .venv` (uv 0.11.x is installed; bare python3 is 3.9/3.14 traps).
   Install: `uv pip install --python .venv/bin/python numpy "open3d==0.19.*" cgal
   "opencv-python>=4.13,<5" scipy trimesh "build123d==0.11.*" pytest`.
   If `import cv2.aruco` fails, add `opencv-contrib-python<5` instead of opencv-python.
   Freeze requirements.txt from the venv that passes the smoke gate. The smoke gate
   (PLAN.md section 2) blocks everything.

4. Directory is ~/Documents/personal/scan2cad (this repo, git). Never touch
   ~/Documents/personal/leap-input (its .venv is SDK-pinned) or gencad except read-only.

5. WI-14 (Apple PhotogrammetrySession Mac CLI build) runs last, timeboxed 45 min,
   skippable; failure is a MORNING_PROTOCOL.md note, not a build failure.

6. Threshold freeze is real: thresholds.py values are set once at creation (PLAN.md section 3)
   and no later agent may edit them to make a test or sweep pass. The noise-0 e2e
   tolerance is max(0.05 mm, 0.1%) -- declared before any run; failures are findings.

7. All emitted text (report, docs, MORNING_REPORT) is screen-reader-first: short lines,
   one fact per line, no tables, no ASCII art, no unicode symbols beyond plain punctuation.
