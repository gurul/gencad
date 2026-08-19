# scan2cad morning report

Written overnight, 2026-08-19.
Read this first. It is short. The details live in docs/.

## What you asked for

An ultrathink swarm: research across search, papers, open source, and the leap codebase.
Cross-validated by adversarial agents assuming everything is unnecessary.
A plan built from the wreckage, then executed overnight.

## What the swarm decided

Seven researchers, six bad cops, one architect. Full record in docs/VERDICTS.md and docs/PLAN.md.

The original scan-to-CAD pipeline died in review, component by component.
LeapDepth cannot be extended for scanning. No poses, no confidence, smoothed millimetre depth. Killed.
ARKit pose logging: drifts 20 to 40 mm per second of motion. Killed.
The LiDAR fusion leg: measured plus or minus 10 mm with a 5 cm feature floor. Killed.
COLMAP: nothing for it to do tonight, kept as a gated contingency.
Automatic B-rep assembly: unsolved in the literature, already sold by Backflip for 20 dollars a month. Killed.
Sub-millimetre and press-fit claims: embargoed until real captures are measured.

What survived is sharper than what entered.
scan2cad is a screen-reader-native describe-and-draft tool.
A phone-scanned mesh goes in.
A plain-language geometry report comes out, one fact per line.
An editable build123d script comes out beside it, every dimension named and uncertainty-tagged.
STEP reference surfaces export for CAD use.
The scan is the draft. The caliper is the truth.
It does not compete with Backflip. It competes with silence: no incumbent produces output a blind maker can read.

## What was built and verified

The repo is at ~/Documents/personal/scan2cad. Four commits. 284 tests, all passing, re-run and confirmed after the build agents finished.

The pipeline: mesh or point cloud, then CGAL Efficient RANSAC for planes and cylinders, then dominant-frame fitting and snapping with a full audit log, then the report and the build123d skeleton and STEP.
The noise-zero gate: all three synthetic parts recovered exactly, every dimension within max of 0.05 mm and 0.1 percent, declared before any run.
The noise sweep, frozen thresholds, no overrides possible: at sigma 0.1 mm, 29 of 30 runs pass. At sigma 0.5 mm, 9 of 30. At sigma 1.0 mm, none.
Most failures at higher noise are spurious extra primitives, not wrong dimensions. Failed runs often still recovered dimensions within 0.1 mm.
Degraded smoke, reported as findings, not tuned away: single-sided coverage and flipped normals hurt badly. Details in out/sweep_report_degraded.txt.

A bonus beyond the plan: tools/photogrammetry-cli is a working Mac command line around Apple PhotogrammetrySession, built and smoke-tested tonight.
It reconstructed Apple's 36-photo sample in 21 seconds, converted to OBJ, and the mesh ran through scan2cad describe end to end.
So the chain has already digested one real photogrammetry mesh, not only synthetics.

## What to do this morning

Follow docs/MORNING_PROTOCOL.md. Numbered steps, written for working alone.
The short version:
Print out/reference_part.stl and caliper its five known dimensions.
Photograph a real object with the stock camera, sixty to eighty stills.
Reconstruct with tools/photogrammetry-cli, then run scan2cad describe and draft.
Compare the report to your caliper numbers. That comparison is the first legitimate accuracy figure this project will ever have.
Then scan one object you actually care about and judge whether the report and the skeleton let you act on it. That is the success metric.

## Known rough edges

The overview bounding box over-reports on organic meshes when spurious cylinders are fitted. Noted in the fixer log; harmless on prismatic parts.
CGAL RANSAC cannot be seeded from Python, so fits are reproducible in structure but not digit for digit. gate_repeat covers this.
The mat audit tool exists and passes synthetic tests, but the printed mat itself must be caliper-corrected before it is trusted. Step 1 of the protocol.

## What this build must not be said to do

No plus or minus X millimetre claims about iPhone scans. No press-fit claims. No Backflip comparisons on accuracy.
Every emitted dimension is a draft until a caliper or a datasheet overwrites it.
