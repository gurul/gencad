# scan2cad build targets.
#
# Everything runs through .venv explicitly. Do not rely on an activated shell
# and never call a bare `python`: the system interpreters on this Mac are 3.9
# and 3.14, and neither carries the pinned wheel set.

PY      := .venv/bin/python
PYTEST  := .venv/bin/pytest
FREECAD := /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd

.PHONY: venv smoke test gate gate-repeat sweep sweep-degraded demo clean

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

## gate: the noise-zero end-to-end gate on its own, the one test never dropped
gate:
	$(PYTEST) tests/test_e2e_noise0.py -q

## gate-repeat: evidence that the gate's primitive counts are stable; writes
## out/gate_repeat.txt. Run after any change to ransac_cgal.py.
gate-repeat:
	mkdir -p out
	$(PY) scripts/gate_repeat.py --repeats 30

## sweep: characterisation run; writes out/sweep_report.txt. Not a test.
sweep:
	mkdir -p out
	$(PY) scripts/sweep_noise.py

## sweep-degraded: degradation smoke; writes out/sweep_report_degraded.txt
sweep-degraded:
	mkdir -p out
	$(PY) scripts/sweep_noise.py --degraded

## demo: synthetic bracket end to end, report to stdout, skeleton and STEP to out/
demo:
	mkdir -p out
	$(PY) tools/make_synthetic.py --model bracket --seed 1337 --out out/bracket.ply
	$(PY) -m scan2cad.cli draft out/bracket.ply --provenance synthetic -o out/bracket_skeleton.py --step out/bracket_ref.step

clean:
	rm -rf out .pytest_cache
	find src tools tests scripts -name __pycache__ -type d -exec rm -rf {} +
