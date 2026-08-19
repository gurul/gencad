"""One-line FreeCAD liveness check, run by `make smoke`.

Assumes it is executed by FreeCADCmd (the bundled interpreter), not by the
project venv -- FreeCAD's Part module is not importable from .venv. Prints a
plain-language line and exits nonzero if the bundled kernel is unusable.
"""

import sys

try:
    import FreeCAD
    import Part
except ImportError as exc:  # pragma: no cover - only reachable outside FreeCADCmd
    print(f"FreeCAD not available: {exc}", file=sys.stderr)
    raise SystemExit(1)

box = Part.makeBox(10.0, 10.0, 10.0)
version = ".".join(FreeCAD.Version()[:3])
print(f"freecad ok, version {version}, test box has {len(box.Faces)} faces")
