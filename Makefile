# scan2cad build targets.
#
# Everything runs through .venv explicitly. Do not rely on an activated shell
# and never call a bare `python`: the system interpreters on this Mac are 3.9
# and 3.14, and neither carries the pinned wheel set.

PY      := .venv/bin/python
PYTEST  := .venv/bin/pytest
FREECAD := /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd

.PHONY: venv smoke test sweep demo clean

## venv: create .venv with uv and install the frozen wheel set
venv:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.txt
	uv pip install --python $(PY) -e .

## smoke: the gate that blocks every other work item
smoke:
	$(PY) -c "import open3d, numpy, cv2, cv2.aruco, build123d; from CGAL import CGAL_Shape_detection; print('ok')"
	$(FREECAD) scripts/check_freecad_smoke.py

## test: the full pytest suite, including the noise-zero end-to-end gate
test:
	$(PYTEST) -q

## sweep: characterisation run; writes out/sweep_report.txt. Not a test.
sweep:
	mkdir -p out
	$(PY) scripts/sweep_noise.py

## demo: synthetic bracket end to end, report to stdout, skeleton and STEP to out/
demo:
	mkdir -p out
	$(PY) tools/make_synthetic.py --model bracket --seed 1337 --out out/bracket.ply
	$(PY) -m scan2cad.cli draft out/bracket.ply -o out/bracket_skeleton.py --step out/bracket_ref.step

clean:
	rm -rf out .pytest_cache
	find src tools tests scripts -name __pycache__ -type d -exec rm -rf {} +
