# Stack notes

Recorded by WI-0 on 2026-08-19 after the smoke gate passed.
This file is the source of truth for import paths, binary paths and versions.
If something here disagrees with a plan document, this file is what actually runs.

## Environment

Repo: /Users/gurucharan/Documents/personal/scan2cad
Virtual environment: /Users/gurucharan/Documents/personal/scan2cad/.venv
Created with: uv venv --python 3.12 .venv
uv version: 0.11.27
Python: 3.12.13

Never call a bare python3 in this project.
The system interpreters are 3.9 and 3.14 and neither has the wheel set.
Always use .venv/bin/python and .venv/bin/pytest.

## Installed versions

The install command that produced this set:

    uv pip install --python .venv/bin/python numpy "open3d==0.19.*" cgal \
        "opencv-python>=4.13,<5" scipy trimesh "build123d==0.11.*" pytest

Resulting versions:

numpy 2.5.2
open3d 0.19.0
cgal 6.0.1.post202410241521
opencv-python 4.14.0.94
scipy 1.18.0
trimesh 5.0.0
build123d 0.11.1
pytest 9.1.1

requirements.txt was frozen from this venv after the smoke gate passed.

## Smoke gate

The gate that blocks every other work item, and it passes:

    .venv/bin/python -c "import open3d, numpy, cv2, cv2.aruco, build123d; from CGAL import CGAL_Shape_detection; print('ok')"

Notes on that line.
The plain opencv-python wheel already ships cv2.aruco, so opencv-contrib-python
was not needed. Do not add it; it would fight the existing install.
The CGAL Efficient RANSAC entry point lives at CGAL.CGAL_Shape_detection.
The bare "import CGAL" in PLAN.md section 2 also works but imports nothing useful.

## CGAL Efficient RANSAC, as actually installed

Working import line:

    from CGAL.CGAL_Shape_detection import efficient_RANSAC

The module exposes exactly three public names: CGAL, efficient_RANSAC, region_growing.

Verified call signature:

    efficient_RANSAC(point_set, shape_map, min_points=1, epsilon=-1,
                     cluster_epsilon=-1, normal_threshold=0.9, probability=0.01,
                     planes=True, cones=False, cylinders=False, spheres=False,
                     tori=False)

point_set is a CGAL.CGAL_Point_set_3.Point_set_3 that must have a normal map.
shape_map is an int property map created with point_set.add_int_map("shape").
After the call, shape_map.get(index) gives the shape index for each point, so
inlier sets come from the map, not from the return value.
The return value is a plain Python list of shape info strings, one per shape.

Supporting imports used to build the input:

    from CGAL.CGAL_Kernel import Point_3, Vector_3
    from CGAL.CGAL_Point_set_3 import Point_set_3

## Live shape info strings, captured 2026-08-19

These are real outputs from this exact wheel, for WI-1 to parse.
Watch the whitespace: it is not uniform, and it is not what the CGAL docs show.

Cylinder, from an 800-point synthetic cylinder of radius 12.5 mm with 0.1 mm noise:

    Type: cylinder center: (-0.0686792, 0.0335444, 6.52789) axis: (-0, 0, 1) radius:12.5214 #Pts: 800

Plane, from a 600-point synthetic plane at z = 5 mm with 0.05 mm noise:

    Type: plane (-0.00247502, 0.00212651, 0.999995)x - -4.97749= 0 #Pts: 593

Parser gotchas visible above.
There is no space after "radius:".
There is no space before "=" in the plane string.
The plane offset can appear as a double negative, "- -4.97749", when the signed
distance is negative.
An axis component can be printed as "-0".
The plane string has no "center:" or "normal:" labels at all: the parenthesised
triple is the unit normal, and the scalar is d in the form n dot x - d = 0.

The cylinder radius recovered above was 12.5214 mm against a true 12.5 mm,
an error of 0.17 percent, which clears the WI-3 acceptance bar of 1 percent.

## FreeCAD

The binary is NOT in Contents/MacOS. That directory holds only the GUI app.

Working path:

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd

Verified with a one-line Part script; it printed:

    freecad ok 1.1.3 faces 6

FreeCAD version 1.1.3, libs 1.1.3R20260725.
FreeCADCmd runs on its own bundled Python, not the project venv.
Scripts for it live in scripts/ and must not import scan2cad.
scripts/check_freecad_smoke.py is the liveness check, wired into make smoke.
