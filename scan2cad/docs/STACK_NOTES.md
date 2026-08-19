# Stack notes

Recorded by WI-0 on 2026-08-19 after the smoke gate passed.
This file is the source of truth for import paths, binary paths and versions.
If something here disagrees with a plan document, this file is what actually runs.

## Environment

Repo: /Users/gurucharan/Documents/personal/gencad/scan2cad
Virtual environment: /Users/gurucharan/Documents/personal/gencad/scan2cad/.venv
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

## Addendum from WI-1, 2026-08-19: plane sign convention

Appended by the WI-1 agent (params.py). This corrects a reading of the plane
string above that WI-3 would otherwise get backwards.

The plane text reads "(n)x - D= 0" but the actual convention is

    n dot x + D = 0

so the signed offset along the printed normal is -D, and the plane point
closest to the origin is -D times n.

Evidence, from exact noise-free synthetic planes run through this wheel:

    plane through z = +5, normal +z   ->  Type: plane (0, 0, -1)x - 5= 0
    plane through z = -5, normal +z   ->  Type: plane (0, 0, -1)x - -5= 0
    plane through (0,0,10), n=(0.6,0,0.8) -> Type: plane (0.6, -3.68087e-15, 0.8)x - -8= 0

The third case settles it: 0.8 * 10 = 8, and the printed scalar is -8.
Reading the text at face value would put every plane on the wrong side of the
origin, which is a silent geometry error, so params.py owns this conversion
and nothing downstream should re-derive it.

Two further facts WI-3 needs.

The printed normal sign is arbitrary. CGAL flips it relative to the input
normals as it pleases, so orientation must come from the inlier normals, not
from the string.

The shapes are minimal-sample fits, not least-squares refits. A 600-point
plane at z = 5 with 0.05 mm noise came back at 4.937 mm, an error far larger
than a least-squares fit of 600 points would give, and the normal was tilted
by 0.003 rad. WI-3 should treat the parsed parameters as a seed and recompute
plane and cylinder parameters from the inliers before reporting RMS.

Other shape kinds, captured for the parser's rejection tests:

    Type: sphere center: (1, 2, 3) radius:10 #Pts: 600
    Type: cone apex: (...) axis: (...) angle:0.523599 #Pts: 800
    Type: torus center(...) axis(...) major radius = 20 minor radius = 5 #Pts: 998

Note the torus string has no colon after "center" and "axis".

## Addendum from WI-3, 2026-08-19: shape map, refits, shared plane basis

Appended by the WI-3 agent (ransac_cgal.py). Three facts downstream work items
need and must not re-derive.

1. The shape map is read by point index and holds -1 for unassigned points.

       shape_map.get(i) for i in range(point_set.size())

   The value is the position of that point's shape in the returned info list,
   so info index and shape index are the same number. Verified live: a run over
   800 plane points plus 300 random junk points gave Counter({0: 800, -1: 300}).

2. The reported primitive parameters are NOT CGAL's. CGAL returns minimal-sample
   fits, so ransac_cgal.py recomputes every plane (total least squares from the
   inlier covariance) and every cylinder (geometric Gauss-Newton over axis
   direction, axis position and radius, seeded from the inlier normals and an
   algebraic circle fit) from the inlier set in numpy. Measured on the WI-3
   acceptance case, a 4000-point 12.5 mm cylinder at 0.1 mm noise: radius error
   0.0006 to 0.014 percent over eight seeds, against CGAL's own 0.17 percent.
   The noise-zero gate's reproducibility comes from this refit, not from CGAL,
   whose generator is unseeded.

3. The (u, v) plane basis is a shared convention, duplicated on purpose in
   ransac_cgal.plane_uv_basis and emit_build123d.plane_uv_basis so the fitter
   does not import the emitter. tests/test_ransac_cgal.py asserts the two agree
   for six normals. The rule: helper is the world axis least aligned with the
   normal, u = normalize(helper cross normal), v = normal cross u.

   PlaneFit.extent is measured relative to PlaneFit.point, which is the inlier
   centroid, so the four numbers straddle zero and are not world coordinates.
   CylinderFit.extent_mm is likewise relative to axis_point, which sits at the
   projection of the inlier centroid onto the axis.

   Cylinder axis sign is arbitrary in CGAL, so ransac_cgal canonicalises it:
   the component of largest magnitude is made positive. Plane normal sign is
   taken from the mean inlier normal, so a closed scan gets outward normals.
