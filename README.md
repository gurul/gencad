# scan2cad

A screen-reader-native describe-and-draft tool.

You give it a phone-scanned mesh.
It gives you a plain-language geometry report you can listen to.
It also gives you an editable build123d script with named dimensions.
It exports STEP reference surfaces for inspection, not printable solids.

The scan is the draft. The caliper is the truth.

## The two-channel accuracy model

Channel one is the scan. It is fast, it is complete, and it is approximate.
Every scan-derived number is a draft.
Every draft number carries its raw fitted value, its snapped value, the
deviation between them, the fit residual, and the inlier count.
Every named dimension in the emitted script is marked VERIFY WITH CALIPER.

Channel two is the caliper or the datasheet. It is slow, it is partial, and it
is correct. You overwrite the drafted numbers with it.

The tool never claims sub-millimetre accuracy.
It never claims a press fit or a mating fit.
It does not compete with CAD tools on precision. It competes with silence.

## What it does not do

It does not do silent snapping. Every changed number is logged.
It does not build solids, run Booleans, or trim and sew surfaces.
Assembly suggestions are emitted as commented-out hints only.
It fits planes and cylinders. That is the whole primitive vocabulary.

## Quickstart

Create the environment. This uses uv and Python 3.12.

    make venv

Run the smoke gate. It must print ok before anything else is worth running.

    make smoke

Run the tests.

    make test

Describe a mesh.

    .venv/bin/python -m scan2cad.cli describe mesh.obj --units m

Draft a script and a STEP file from a mesh.

    .venv/bin/python -m scan2cad.cli draft mesh.obj -o part_skeleton.py --step part_ref.step

Photogrammetry meshes arrive in metres, so pass --units m for them.
Synthetic meshes are in millimetres.
For a file from tools/make_synthetic.py, pass --provenance synthetic.
That defaults the units to millimetres and marks the report as synthetic.
The report always prints which assumption it used.

## Layout

src/scan2cad holds the package.
tools holds standalone helpers that are not pipeline stages.
scripts holds characterisation and validation runners, which are not tests.
tests holds the suite; tests/test_e2e_noise0.py is the gate that matters.
out holds generated artefacts and is not tracked by git.
docs holds the plan, the verdicts, the rulings, and the stack notes.

Read docs/STACK_NOTES.md before touching the environment.
It records the working import paths and the FreeCAD binary path.

## STEP export

The primary STEP path is build123d's own exporter, written by the emitted
skeleton script.
FreeCADCmd is used only to validate the resulting file, via
scripts/check_step_freecad.py.
The gencad MCP bridge is the documented alternate STEP path. It is not wired up.
