# SCAN2CAD -- DEFINITIVE OVERNIGHT BUILD PLAN

**Product sentence (fixed, non-negotiable):** a screen-reader-native describe-and-draft tool that turns any phone-scanned mesh into a plain-language geometry report and an editable named-dimension build123d script, where the scan is the draft and the caliper is the truth.

## 0. Ground rules encoding the verdicts (implementation agents may not deviate)

1. **Two-channel accuracy model.** Every scan-derived number is a draft tagged with uncertainty and a `# VERIFY WITH CALIPER/DATASHEET` marker. The pipeline never claims, needs, or is tuned for sub-mm accuracy.
2. **No iOS/Swift capture code. No ARKit. No LeapDepth.** Zero lines.
3. **No COLMAP.** Do not `brew install colmap`. No pose_prior code, no MVS code. COLMAP exists only as a documented contingency slot.
4. **No LiDAR/TSDF leg.** No Stray Scanner ingest, no confidence filtering, no `open3d...integration` import anywhere in `src/`. Input contract is single-source: one mesh/point-cloud file of photogrammetry-or-synthetic provenance. No source enum, no fusion hook. (open3d stays as a mesh utility library only.)
5. **Thin middle only.** Planes + cylinders. Dominant-orthogonal-frame snapping + concentric/equal-radius clustering. No pairwise constraint graphs, no trim/sew, no executed Booleans/extrudes. Assembly hints are comments.
6. **No silent snapping.** Every named dimension carries raw fitted value, snapped value, deviation, RMS residual, inlier count.
7. **Synthetic results are claim-limited.** They prove the code path runs and isn't knife-edge fragile. They never prove iPhone accuracy. Thresholds are frozen before the noise sweep and may not be re-tuned to make it pass.
8. **No sensor-realistic simulators** (LiDAR hallucination, TrueDepth warp, VIO drift, OIS jitter). Named TODO comments only; do not create stub files for killed stages.

## 1. Repo layout (new directory `~/Documents/personal/gencad/scan2cad`)

```
scan2cad/
  README.md # product sentence, two-channel model, quickstart
  requirements.txt # exact pins (see venv recipe)
  Makefile # venv, test, sweep, demo targets
  src/scan2cad/
    __init__.py
    primitives.py # frozen dataclasses (spec below)
    thresholds.py # FROZEN defaults + regime presets, timestamped
    io_mesh.py # load PLY/OBJ/STL, sample, estimate+orient normals
    ransac_cgal.py # CGAL Efficient RANSAC wrapper (planes+cylinders)
    params.py # CGAL param-string parser
    frame.py # dominant frame, snapping, radius/concentric merge
    report.py # plain-text screen-reader geometry report
    emit_build123d.py # skeleton script emitter
    sources.py # GeometrySource protocol (~30 lines)
    cli.py # `scan2cad describe` / `scan2cad draft`
  tools/
    make_synthetic.py # virtual brackets + parametric degradation
    mat_audit.py # ChArUco PnP scale audit (standalone, not in pipeline)
    reference_part.py # build123d model of the morning ground-truth part -> STL
  tests/
    test_params.py # parser unit tests (live-fixture + frozen strings)
    test_frame.py
    test_emit.py # emitted script compiles & runs
    test_e2e_noise0.py # THE CI GATE
    test_no_dead_imports.py # greps src/ for integration/TSDF/colmap/ARKit refs
    test_mat_audit_synthetic.py
  scripts/
    sweep_noise.py # characterization, NOT pytest; writes out/sweep_report.txt
    check_step_freecad.py # FreeCADCmd validation helper
  docs/
    MORNING_PROTOCOL.md
    DECISIONS.md # the six verdicts, condensed, with embargoed-claims list
    CONTINGENCIES.md # three gated tickets (below)
  out/ # gitignored: STEP files, sweep reports, demo skeletons
```

## 2. venv recipe

```bash
mkdir -p ~/Documents/personal/gencad/scan2cad && cd ~/Documents/personal/gencad/scan2cad
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install numpy "open3d==0.19.*" "cgal==6.0.1.*" \
    "build123d==0.11.1" opencv-contrib-python pytest
```

Pin `requirements.txt` from `pip freeze` of THIS venv after the smoke import passes. If the `cgal` wheel name/version differs from tonight's already-verified smoke-test venv, copy the exact pins from that venv (`pip freeze`) -- the verified wheel set is the source of truth, not PyPI guesswork. Smoke gate before any other work item proceeds:

```bash
.venv/bin/python -c "import open3d, numpy, cv2.aruco, build123d; import CGAL; print('ok')"
```

FreeCAD fallback emitter: verify `/Applications/FreeCAD.app/Contents/MacOS/FreeCADCmd` (1.1.3) responds; used only by `check_step_freecad.py`. The gencad MCP bridge is documented in README as the alternate STEP path; not wired tonight.

## 3. Shared data model (freeze this in the first hour; everything downstream depends on it)

`src/scan2cad/primitives.py`:

```python
@dataclass(frozen=True)
class PlaneFit:
    name: str # "plane_0" -> semantic rename in frame stage
    point: tuple[float, float, float]
    normal: tuple[float, float, float] # unit
    inlier_count: int
    rms_mm: float
    extent: tuple[float, float, float, float] # 2D bbox in plane coords (u_min,u_max,v_min,v_max)

@dataclass(frozen=True)
class CylinderFit:
    name: str
    axis_point: tuple[float, float, float]
    axis_dir: tuple[float, float, float] # unit
    radius_mm: float
    extent_mm: tuple[float, float] # inlier span along axis
    inlier_count: int
    rms_mm: float

@dataclass(frozen=True)
class SnapRecord:
    dim_name: str
    raw: float
    snapped: float
    deviation: float
    rule: str # e.g. "axis-align 5deg", "radius-cluster 2xRMS"

@dataclass(frozen=True)
class SceneModel:
    frame: tuple # origin + orthonormal triad
    planes: list[PlaneFit]
    cylinders: list[CylinderFit]
    snaps: list[SnapRecord]
    provenance: str # "synthetic" | "photogrammetry-mesh"
```

`thresholds.py` -- regime presets, frozen with a `FROZEN 2026-08-19T<hh:mm> -- do not tune to pass the sweep` header comment:
- `coarse` (default): angular snap 5.0 deg, dimensional snap 2.0 x per-primitive RMS
- `fine`: angular snap 1.0 deg, dimensional snap 0.5 mm
- RANSAC: epsilon 0.5 mm, cluster_epsilon 2.0 mm, normal_threshold 0.9, min_points 200 (coarse); epsilon 0.2 mm (fine). All overridable via CLI flags; overrides always echoed in report and emitted script.

## 4. Ordered work items

**WI-0 -- Scaffold + venv + smoke gate** (sequential, blocks everything)
- Deliverables: repo tree above, `requirements.txt`, `Makefile` (`make venv`, `make test`, `make sweep`, `make demo`), `primitives.py`, `thresholds.py`, `test_no_dead_imports.py`.
- Acceptance: smoke import passes; `test_no_dead_imports.py` passes (asserts no occurrence of `integration`, `TSDF`, `colmap`, `pose_prior`, `ARKit`, `import ARKit`, `stray` in `src/`).
- Size: ~120 lines + Makefile. ~30-45 min.

**WI-1 -- CGAL param-string parser** (`params.py`, `test_params.py`)
- Goal: parse Efficient RANSAC shape `.info()` strings for plane and cylinder into `PlaneFit`/`CylinderFit` (extent fields filled later from inliers). Handles scientific notation, negative components, variable whitespace. Rejects sphere/cone/torus strings with a clear error (they are not fitted, but the parser must not crash on them).
- Tests: (a) frozen-string fixtures hand-written now; (b) a live fixture generated at test time by running CGAL RANSAC on a 500-point synthetic cylinder -- catches upstream format drift.
- Acceptance: `pytest tests/test_params.py` green; round-trip on live fixture recovers radius within 1%.
- Size: ~150 src + ~120 test lines. ~1 h.

**WI-2 -- Mesh/cloud IO + normals** (`io_mesh.py`)
- Goal: load PLY/OBJ/STL via open3d; if mesh, sample N points (default 80k, poisson-disk); estimate normals (hybrid KDTree radius = 4 x median NN distance) and orient via `orient_normals_consistent_tangent_plane(k=30)`; unit conversion flag `--units mm|m` (photogrammetry meshes arrive in meters -- default assume meters for mesh files, mm for synthetic; always print the assumption in the report).
- Acceptance: loads a synthetic PLY and an OBJ, returns cloud with unit normals, deterministic under fixed seed.
- Size: ~130 lines. ~1 h.

**WI-3 -- CGAL RANSAC wrapper** (`ransac_cgal.py`) -- depends on WI-1, WI-2
- Goal: run Efficient RANSAC restricted to planes + cylinders; parse via `params.py`; compute per-primitive RMS residual and inlier count in numpy from inlier indices; fill plane 2D extents and cylinder axial extents from inliers; drop primitives with inlier_count < min_points.
- Acceptance: recovers the smoke-test case (12.5 mm cylinder, 0.1 mm noise) to <1% radius error; returns typed dataclasses only.
- Size: ~170 lines. ~1.5 h.

**WI-4 -- Frame + snapping + merging** (`frame.py`, `test_frame.py`) -- depends on WI-3
- Goal: cluster plane normals (agglomerative on angular distance, threshold = angular snap), select dominant orthogonal triad (largest-inlier plane defines Z; best near-perpendicular cluster defines X; Y = Z x X, re-orthogonalized); snap plane normals and cylinder axes to frame axes when within angular tolerance; merge cylinders into concentric/equal-radius groups when axis distance < dimensional tolerance and radius delta < dimensional tolerance; snap opposite-parallel plane gaps and radii to 0.1 mm-rounded values ONLY when within dimensional tolerance. Every action emits a `SnapRecord`. Semantic renaming: after frame alignment, planes become `plane_top/bottom/left/right/front/back` where unambiguous, else keep index names.
- Explicitly out of scope: pairwise constraint graph, any solver.
- Acceptance: unit tests on hand-built primitive sets -- triad recovery under 3-degree perturbation; no snap applied when deviation exceeds tolerance; every mutation has a SnapRecord.
- Size: ~220 src + ~150 test lines. ~2 h.

**WI-5 -- Plain-text report** (`report.py`) -- depends on primitives.py only (parallel after WI-0; integration after WI-4)
- Goal: screen-reader-native report. Rules: one fact per line; no tables, no ASCII art, no unicode symbols; stable ordering (planes by frame axis then position, cylinders by radius); millimeters with one decimal; every dimension line ends with its uncertainty tag. Sections: 1) Overview ("Object bounding box 60.1 by 40.0 by 20.2 mm. Found 6 planes and 2 cylinders. Provenance: synthetic. All dimensions are scan drafts, plus or minus the stated residual -- verify with caliper."); 2) Dimensions ("height = 20.2 mm, gap between plane_top and plane_bottom, RMS 0.3 mm, 14200 points"); 3) Relations ("cyl_bore_1 axis is perpendicular to plane_top, snapped from 89.2 degrees, deviation 0.8 degrees"; "cyl_bore_1 center is 15.1 mm from plane_left and 20.0 mm from plane_front"); 4) Snap log (every SnapRecord verbatim); 5) Caveats (fixed text from the embargo list).
- Acceptance: golden-file test on a hand-built SceneModel; zero non-ASCII characters; every dimension line matches the regex `= [0-9.]+ mm.*RMS`.
- Size: ~220 lines. ~1.5 h.

**WI-6 -- build123d skeleton emitter** (`emit_build123d.py`, `test_emit.py`) -- depends on primitives.py (parallel after WI-0; integration after WI-4)
- Goal: emit a standalone Python script containing: (a) header docstring with the two-channel disclaimer and provenance; (b) NAMED DIMENSIONS block -- `height = 20.2 # fitted 20.23, snapped 20.2 (dev 0.03), RMS 0.3 mm, 14200 pts -- VERIFY WITH CALIPER`; (c) datum construction in build123d (Plane objects from frame + offsets, Axis objects for cylinders); (d) reference-surface geometry: bounded planar faces sized to fitted extents and cylindrical faces over fitted axial extents, collected into a Compound labeled per primitive; (e) STEP export of that compound (`export_step(compound, "part_ref.step")`) -- reference surfaces for inspection, explicitly commented "NOT a solid, NOT printable"; (f) commented assembly hints only -- e.g. `# HINT: plane_top parallel plane_bottom, gap 20.2 -> box height? Uncomment and edit: # part = Box(width, depth, height)` -- never executed code for solids or Booleans.
- Acceptance: emitted script for a hand-built SceneModel executes under the venv's build123d 0.11.1 with exit 0 and writes a STEP; `check_step_freecad.py` opens it in FreeCADCmd and asserts face count == plane count + cylinder count.
- Size: ~260 src + ~120 test lines. ~2-2.5 h.

**WI-7 -- GeometrySource interface** (`sources.py`) -- after WI-2
- Goal: ~30-line Protocol: `load() -> (points, normals, provenance)`. One concrete `FileMeshSource`. Docstring documents: production path = Apple PhotogrammetrySession output file; contingency slot = COLMAP sparse + mat GCP (docs/CONTINGENCIES.md ticket 2). No other backends, no enums.
- Acceptance: covered implicitly by e2e test. Size: ~40 lines. ~15 min.

**WI-8 -- CLI** (`cli.py`) -- after WI-2/5/6/7
- Goal: `scan2cad describe INPUT [--units ...] [--regime coarse|fine] [threshold overrides]` -> report to stdout. `scan2cad draft INPUT -o skeleton.py [--step out.step]` -> report to stdout, skeleton to file; `--step` executes the emitted skeleton in a subprocess (proving it runs) and moves the STEP. Exit nonzero with a plain-language message if <2 primitives found.
- Acceptance: both commands run end-to-end on a synthetic bracket in the e2e test.
- Size: ~150 lines. ~1 h.

**WI-9 -- Synthetic generator** (`tools/make_synthetic.py`) -- parallel after WI-0
- Goal: three ground-truth models with exact known dims, returned as (points, normals, truth-dict): (1) BRACKET: 60 x 40 x 20 mm block with one 12.5 mm through-bore; (2) LBRACKET: two orthogonal 50 x 30 x 4 plates, two 5 mm bores; (3) BOSSBOX: 80 x 50 x 25 shell exterior with one 8 mm outer-diameter boss (cylinder + top plane). Sampler parameters: `sigma_mm` (iid Gaussian along normal), `bias_mm` (constant offset along normal), `flip_frac` (fraction of normals randomly flipped), `unoriented` (bool: randomize all normal signs), `hole_count/hole_radius_mm` (spherical dropouts), `coverage` (full | top-hemisphere-only), `seed`. NO simulation of hallucinated depth, correlated warp, pose drift, or intrinsics jitter -- a single block comment names these as prohibited TODOs per DECISIONS.md.
- Acceptance: truth-dict dims match construction; deterministic per seed.
- Size: ~260 lines. ~2 h.

**WI-10 -- E2E gate + noise sweep + degradation smoke** -- after everything above
- `tests/test_e2e_noise0.py` (THE CI GATE): for all three models at sigma=0, pinned seed 1337: full chain via CLI (`draft --step`); assert primitive counts exactly match truth; every named dimension within pre-declared tolerance **max(0.05 mm, 0.1%)** (declared here, now, before any run -- not tunable); skeleton executes; FreeCADCmd opens the STEP with correct face count; report passes the format regexes.
- `scripts/sweep_noise.py`: sigma in {0.1, 0.5, 1.0} mm x 10 fresh random seeds x 3 models, thresholds read from frozen `thresholds.py` with NO overrides accepted (the script has no threshold flags at all); pre-declared pass criterion per run: correct primitive count and all dims within max(3 x sigma, 0.5 mm); output `out/sweep_report.txt` = pass-rate distribution per (model, sigma) + per-dim error percentiles, headed by the mandatory caption: "PLUMBING VERIFICATION ONLY -- synthetic noise model; NOT predictive of iPhone accuracy."
- Degradation smoke (same script, `--degraded`): flip_frac 0.2, unoriented, holes x 3, top-hemisphere coverage, each at sigma 0.5 -- outcomes recorded honestly (expected: some fail; failures are findings, not bugs to tune away).
- Time-pressure rule (per verdict): if the night runs short, drop the sweep first; the noise=0 gate is dropped last.
- Size: ~200 test + ~180 script lines. ~2 h runtime-inclusive.

**WI-11 -- ChArUco mat scale audit** (`tools/mat_audit.py`, `test_mat_audit_synthetic.py`) -- fully parallel, independent
- Goal (audit tool, NOT a pipeline stage, NOT a pose source): given images of a scene containing a ChArUco board (spec fixed here: `cv2.aruco.DICT_5X5_1000`, 7 x 5 squares, 20 mm nominal square, 15 mm marker), detect corners, solvePnP with provided intrinsics, and output the implied metric scale factor between the image set's reconstruction units and true mm, with `--mat-scale-correction FACTOR` applied (FACTOR = caliper-measured span / nominal span, entered in the morning). Tonight's validation is fully synthetic: render board corner projections through a known pinhole camera at 5 poses, add 0.3 px Gaussian pixel noise, recover scale.
- Acceptance: scale recovery error < 0.1% on clean synthetic; < 0.5% at 1.0 px noise; report degradation curve. Also emits `out/charuco_a4.png` (the printable board, 300 DPI, with nominal span in the filename metadata and in MORNING_PROTOCOL.md).
- Size: ~220 src + ~100 test lines. ~2 h.

**WI-12 -- Reference part model** (`tools/reference_part.py`) -- parallel, independent
- Goal: build123d script producing `out/reference_part.stl` + `.step`: 60 x 40 x 20 mm block, 12.5 mm through-bore at (15, 20) from the corner, 8 mm x 5 mm tall boss at (45, 20). Five named ground-truth dims printed to stdout for the morning caliper sheet.
- Acceptance: STL exports; dims echo matches construction.
- Size: ~60 lines. ~20 min.

**WI-13 -- Docs + morning decision report** -- docs parallelizable now; final report assembly is the last sequential item
- `docs/DECISIONS.md`: the six verdicts condensed to one paragraph each + the permanent-rejection list (ARKit poses, pose_prior_mapper, frozen-pose triangulation, dense MVS, LiDAR-in-fitting, silent snapping) + the embargoed-claims list (section 7 below).
- `docs/CONTINGENCIES.md`: three tickets, each with an explicit evidence gate (section 6 below).
- `docs/MORNING_PROTOCOL.md`: full contents in section 5 below.
- Final `out/MORNING_REPORT.md` assembled after WI-10: what was built, test results with mandatory captions, kill rationale one-pager (plus or minus 10 mm LiDAR vs 0.2-0.4 mm print tolerance; 5 cm floor vs 2 mm walls), the day's decision gates, and the protocol pointer. This report is prose for the user's screen reader: short lines, no tables.

**WI-14 (best-effort, timeboxed 45 min, may be skipped without affecting the gate) -- Apple PhotogrammetrySession Mac CLI**
- Goal: de-risk the morning by building Apple's "Creating a Photogrammetry Command-Line App" sample on this Mac (Mac-side Swift, no device, no signing -- this does not violate the iOS kill). Smoke it on Apple's downloadable sample image set if fetchable; otherwise stop at a successful build.
- Acceptance: binary exists and prints usage. On any friction past 45 min, abandon and note in MORNING_PROTOCOL.md that the user builds it in the morning (Xcode project, one Build command).

## 5. MORNING_PROTOCOL.md contents (the user's physical steps tomorrow)

Written as numbered spoken-friendly steps:

1. **Print the mat.** Print `out/charuco_a4.png` at 100% scale (no fit-to-page). Tape it flat to something rigid. With the caliper, measure the long span across the full black grid (nominal span printed in the doc, e.g. 140.0 mm across 7 squares). Compute correction = measured / nominal. Write it down. (~0.2% print error is expected; this step removes it.)
2. **Print the reference part.** Slice and print `out/reference_part.stl`. While it prints, do steps 3-4. After printing, caliper-measure the five named dims (list with expected values in the doc) and record them in `out/ground_truth.txt`.
3. **Build the photogrammetry CLI** if WI-14 didn't finish (Xcode, open sample project, Build).
4. **Install Stray Scanner** (free, App Store) -- fallback/coarse-leg only; its exports are NOT fed to scan2cad; keep the folder in case contingency ticket 3 ever activates.
5. **Capture session (photogrammetry stills).** Stock Camera app. Live Photos OFF. Macro auto-switch OFF. Long-press for AE/AF lock on the object. Object sits on the mat. Even diffuse light; if the object is shiny, dust with chalk or cover with masking tape. Standoff about 25-30 cm. Three orbit rings -- low, chest-height, high -- 20 to 30 photos each, small steps, overlap heavy. 60-80 photos total. AirDrop to the Mac as HEIC.
6. **Reconstruct.** Run the photogrammetry CLI on the photo folder -> mesh (request OBJ if the API offers it; else USDZ and convert). Expected: metric-scaled mesh, meters.
7. **Run the tool.** `scan2cad describe mesh.obj --units m`, then `scan2cad draft mesh.obj -o part_skeleton.py --step part_ref.step`. Listen to the report.
8. **First real accuracy audit.** Compare the report's five reference-part dims against `ground_truth.txt`. Expect errors in the plus or minus 1-10 mm draft band; record actuals. This is the first legitimate accuracy number the project has ever had.
9. **Scale cross-check.** Run `tools/mat_audit.py` on 5 of the stills with the correction factor from step 1; compare its scale against the PhotogrammetrySession mesh scale.
10. **Decision gate -- COLMAP** (contingency 2): only if PhotogrammetrySession scale error exceeds 0.3 mm / 0.3% on the ~100 mm reference dims -> spend 30 min on `brew install colmap`, sparse-only, mat corners as GCP.
11. **Decision gate -- AF-lock shim** (contingency 1): only if reconstruction visibly fails or errors are attributable to focus/exposure hunting.
12. **Optional Backflip baseline** ($20/mo, user's call): upload the same mesh, note what feature tree it emits and what small features it silently misses; for the decision record, not for the pipeline.
13. **The real test:** scan one object the user actually cares about (an unknown bracket or housing, not an ESP32 part with a datasheet) and judge whether the report + skeleton let them act on it. That is the success metric.

## 6. Contingency tickets (docs/CONTINGENCIES.md -- no code tonight)

1. **AF-lock still-capture shim.** Fork Apple's Object Capture sample; lock `lensPosition`, disable `geometricDistortionCorrection`, embed `AVCameraCalibrationData` per shot. No ARKit, no streaming, no LeapDepth core (only its ~150-200 UI-shell/parser-test lines are noted as reusable). GATE: morning evidence that stock-camera AE/AF-locked bursts break COLMAP/PhotogrammetrySession or blow the error budget.
2. **COLMAP sparse + GCP backend.** Sparse SfM with per-image intrinsics refinement, mat corners as ground-control points, behind `GeometrySource`. Never pose_prior_mapper, never known-pose triangulation, never dense MVS. GATE: step-10 caliper audit failure.
3. **Stray Scanner pose-CSV parser** (~50 lines). GATE: contingency 2 active AND a scale prior measurably needed.

## 7. What tonight's build MUST NOT claim (verbatim into DECISIONS.md and MORNING_REPORT.md)

- No sentence of the form "the pipeline achieves plus or minus X mm" -- synthetic numbers are plumbing verification only; the iPhone-accuracy claim is embargoed until step-8 real-capture audits exist.
- No press-fit, mating-fit, or sub-mm claims, ever -- the two-channel model makes them unnecessary by design.
- No claim of competing with Backflip on accuracy; the product competes with silence (no accessible alternative exists), not with CAD tools.
- No implication that scan dims are trustworthy: every emitted dimension is a draft until overwritten from caliper or datasheet.
- Degraded-mesh failures are reported as findings, not hidden and not tuned away.

## 8. Parallelization plan

```
WI-0 (sequential gate: scaffold + venv + primitives.py + thresholds.py)
  |
  +-- Track A (core, sequential): WI-1 -> WI-3 -> WI-4 -> [join] WI-8
  +-- Track B: WI-2 -> WI-7 (joins WI-8)
  +-- Track C: WI-5 (report) \ start from frozen (joins WI-8)
  +-- Track D: WI-6 (emitter) / dataclasses (joins WI-8)
  +-- Track E: WI-9 (synthetic generator) (joins WI-10)
  +-- Track F: WI-11 (mat audit) -- fully independent
  +-- Track G: WI-12 (reference part) -- fully independent
  +-- Track H: WI-13 docs (protocol/decisions/contingencies) -- fully independent
  +-- Track I: WI-14 (timeboxed, skippable)
Then sequential: WI-8 (CLI) -> WI-10 (e2e gate, then sweep, then degraded smoke)
              -> WI-13 final MORNING_REPORT.md assembly
```

Up to 6 agents concurrently after WI-0 (A, B/C/D as three, E, F, G+H combined). Estimated totals: ~2,400 src/test lines; critical path about WI-0 -> WI-1 -> WI-3 -> WI-4 -> WI-8 -> WI-10 -> report about 8-9 h; parallel tracks fit inside it. If time runs short: drop WI-14 first, then the noise sweep, then degraded smoke; the noise=0 gate, the emitter, the report, and MORNING_PROTOCOL.md are never dropped.