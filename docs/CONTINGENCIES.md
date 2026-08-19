# Contingencies

Three tickets. None of them has any code in this repository and none of them
should acquire any until its gate opens.

A gate is a piece of measured evidence, not an opinion and not a hunch.
If the gate has not opened, the ticket stays closed, no matter how reasonable
it sounds while reading it.

Each ticket states four things: what it is, what it must never become, the
exact evidence that opens it, and what it costs.

## Ticket 1. Autofocus lock still capture shim

What it is.
A small iOS capture shim, forked from Apple's Object Capture sample project.
It locks lensPosition so focus cannot hunt between shots.
It disables geometricDistortionCorrection so the frames are not silently
rewarped.
It embeds AVCameraCalibrationData with every shot, so each photograph carries
its own intrinsics.

Why it might be needed.
Optical image stabilisation and autofocus vary the intrinsics by 5 to 22
micrometres between shots, which is the dominant threat to photogrammetry
accuracy, and neither the stock Camera app nor EXIF data can express or control
it.

What it must never become.
No ARKit, in any form.
No pose logging.
No TCP streaming.
No LeapDepth capture core; only its roughly 150 to 200 lines of user interface
shell and parser tests are noted as reusable material.
It is a capture settings shim of roughly 200 lines, not an application.

The gate.
Morning evidence that stock camera bursts with automatic exposure and
automatic focus locked actually break the reconstruction, or blow the error
budget.
Concretely, step 11 of docs/MORNING_PROTOCOL.md: the reconstruction visibly
fails, or the step 8 errors are clearly attributable to focus or exposure
hunting rather than to scale or to coverage.

Cost if opened.
Roughly 200 lines of Swift over an existing Apple sample, plus a device build.

## Ticket 2. COLMAP sparse structure from motion with ground control points

What it is.
A second geometry backend behind the GeometrySource protocol in
src/scan2cad/sources.py.
Sparse structure from motion only, with per image intrinsics refinement.
The printed mat corners are used as ground control points to fix metric scale.

Why it might be needed.
Self calibrating bundle adjustment is the one capability nothing else in the
stack replicates, and it is the only open and controllable answer if Apple's
PhotogrammetrySession, which is a black box with no published accuracy
specification, turns out to be silently off on scale.

What it must never become.
Never pose_prior_mapper.
Never known pose triangulation from frozen ARKit poses.
Never dense multi view stereo.
All three are permanently rejected in docs/DECISIONS.md, and opening this
ticket does not reopen them.

The gate.
Step 10 of docs/MORNING_PROTOCOL.md, which depends on the step 8 caliper audit.
The gate opens only if PhotogrammetrySession's scale error exceeds 0.3
millimetres, or 0.3 percent, on the roughly 100 millimetre reference part
dimensions.
If the audit passes, do not install COLMAP.

Cost if opened.
About 30 minutes for brew install colmap and its 23 dependencies, plus the
sparse run, plus a small adapter behind GeometrySource.

## Ticket 3. Stray Scanner pose CSV parser

What it is.
A parser of roughly 50 lines for the pose CSV that Stray Scanner exports.
Its only purpose would be to supply a scale prior, or a coverage audit input,
to the COLMAP path.

What it must never become.
Not a pipeline input.
Not a depth ingest, not a confidence filter, not a TSDF stage.
The LiDAR and TSDF leg is dead, and this parser touches poses only.
Nothing it produces may reach the dimension fitting stage.

The gate.
Both of these must be true at once.
Ticket 2 is already open and active.
A scale prior has been measurably shown to be needed, rather than assumed.

Cost if opened.
About 50 lines and an afternoon at most. It is the cheapest of the three and
therefore the easiest one to write for no reason, which is why its gate is a
conjunction.

## Status notes from the overnight build

This section records what the overnight build actually did with the items that
were allowed to be dropped. It is written to be corrected in the morning if it
disagrees with what is on disk.

Mat audit tool. Not stubbed. It shipped in full.
docs/SYNTHESIS.md ruling 2 permitted the ChArUco mat audit to be stubbed if it
cost more than about an hour, and that escape hatch was not used.
tools/mat_audit.py exists, out/charuco_a4.png exists, and step 9 of
docs/MORNING_PROTOCOL.md can be run as written.
Note that the printed board's nominal long span is 139.87 millimetres and not
140.0, because one square rounds to a whole number of pixels at 300 dots per
inch. Divide the caliper reading by 139.87.
The tool remains an audit only. It is not a pose source and it is not a
pipeline stage, so nothing else in the morning depends on it.

Photogrammetry command line app.
This was timeboxed to 45 minutes and is skippable.
If the binary was not built overnight, step 3 of docs/MORNING_PROTOCOL.md tells
you how: open Apple's sample project in Xcode and press Build.
Its absence is a note, never a build failure.
