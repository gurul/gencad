"""Locate KiCad's CLI and bundled Python; re-exec scripts under pcbnew.

KiCad ships its own Python with the ``pcbnew`` bindings; the system Python
cannot import it. Any script that needs ``pcbnew`` calls :func:`ensure_pcbnew`
first — if the import fails, the script re-executes itself under KiCad's
interpreter transparently, so every tool here runs from a plain shell.

Overrides:
  KICAD_PYTHON   path to KiCad's python3
  KICAD_CLI      path to kicad-cli
"""
import os
import shutil
import subprocess
import sys

_MAC_APP = "/Applications/KiCad/KiCad.app/Contents"
_CANDIDATE_PYTHONS = [
    os.environ.get("KICAD_PYTHON", ""),
    _MAC_APP + "/Frameworks/Python.framework/Versions/Current/bin/python3",
    "/usr/lib/kicad/bin/python3",
]
_CANDIDATE_CLIS = [
    os.environ.get("KICAD_CLI", ""),
    _MAC_APP + "/MacOS/kicad-cli",
    shutil.which("kicad-cli") or "",
]


def kicad_python():
    for p in _CANDIDATE_PYTHONS:
        if p and os.path.exists(p):
            return p
    return None


def kicad_cli():
    for p in _CANDIDATE_CLIS:
        if p and os.path.exists(p):
            return p
    raise RuntimeError("kicad-cli not found; set KICAD_CLI")


def ensure_pcbnew():
    """Import and return pcbnew, re-executing under KiCad's Python if needed."""
    try:
        import pcbnew  # noqa: F401
        return __import__("pcbnew")
    except ImportError:
        pass
    py = kicad_python()
    if py is None or os.path.realpath(py) == os.path.realpath(sys.executable):
        raise RuntimeError(
            "pcbnew bindings unavailable; install KiCad or set KICAD_PYTHON")
    os.execv(py, [py] + sys.argv)


def run_cli(*args, **kw):
    """Run kicad-cli with the given arguments; returns CompletedProcess."""
    return subprocess.run([kicad_cli(), *args], capture_output=True,
                          text=True, **kw)
