# Morning protocol

This is the physical checklist for the morning after the overnight build.
It is written to be listened to, one step at a time.
Each step is a numbered instruction with the reason for it stated plainly.

Two things to know before you start.
Everything scan2cad prints is a draft, plus or minus the residual it states.
The caliper and the datasheet are the only trusted numbers in this project.

Run every command from the repo root, which is
/Users/gurucharan/Documents/personal/scan2cad.
Always use the venv interpreter, .venv/bin/python, never a bare python3.

Steps 2, 5, 6, 7 and 8 are the spine of the morning.
If time is short, do only those, in that order.

## Step 1. Print the mat

Print the file out/charuco_a4.png at one hundred percent scale.
Turn off fit to page and turn off any scale to fit option in the print dialog.
Tape the sheet flat to something rigid, such as a clipboard or a board.
A curled sheet bends the geometry and quietly ruins the scale check.

The board is seven squares by five squares, 20.0 millimetre nominal squares,
15.0 millimetre markers, dictionary DICT_5X5_1000.

Now the correction factor. Read both options before choosing.

Option A, and the default if you are working alone. Use a correction factor of
1.0 and write that down. A home printer is commonly off by about 0.2 percent,
so this option accepts an error of about 0.2 percent in the step 9 cross check
and nothing else. Step 9 is itself a cross check, not a dependency, so an
option A morning is a complete morning.

Option B, if a sighted person is at hand for one minute. The measurement is a
caliper span between two printed ink edges, which cannot be found by touch, so
it needs sight. Have them measure the long span across the full black grid.
The nominal long span is 139.87 millimetres, across seven squares.
That is not a typo for 140.0. The board is rendered at 300 dots per inch and
one square is rounded to a whole number of pixels, so the file on disk is very
slightly under seven times 20.0 millimetres, and 139.87 is the honest number to
divide by.
Compute the correction factor as measured span divided by 139.87.
Write that number down. You need it again at step 9.

To reprint the mat, or to have the tool state its own span again, run:
.venv/bin/python tools/mat_audit.py board

If out/charuco_a4.png does not exist, the mat audit tool was dropped overnight
under the friction rule in docs/SYNTHESIS.md.
In that case skip this step and skip step 9, and carry on from step 2.
Nothing else in the morning depends on the mat.

## Step 2. Print the reference part

Slice and print out/reference_part.stl.
Print it flat on its largest face. No supports are needed.
Normal quality is fine. This part is a measuring reference, not a display piece.

While it prints, do steps 3 and 4.

When it comes off the bed, take the caliper and measure these five dimensions.
The name is the design name, printed by tools/reference_part.py. scan2cad
speaks different names, because it names what it found rather than what you
meant; step 8 gives the mapping between the two.

block_length, design 60.0 millimetres, the longest edge of the block.
block_width, design 40.0 millimetres, the shorter horizontal edge.
block_height, design 20.0 millimetres, top face to bottom face, away from the
round post.
bore_diameter, design 12.5 millimetres, the through hole, jaws opened inside it.
boss_diameter, design 8.0 millimetres, the outside of the round post on the top.

Write the five measured values into out/ground_truth.txt.
Put one name and one value on each line, for example: block_length 60.14.
Record what you measured, not what you designed.
The printer will miss by a few tenths of a millimetre and that miss is real
geometry that the scan will legitimately see.

To reprint the model or reprint the sheet, run:
.venv/bin/python tools/reference_part.py

## Step 3. Build the photogrammetry command line app

Status as this document was written: the binary WAS built overnight, and it
reconstructed Apple's 36 image sample set end to end in about 20 seconds.
There is nothing to do in this step unless the binary is missing.

The tool is our own, not Apple's sample. It lives at
tools/photogrammetry-cli. It is a plain Swift package with no external
dependencies, so it builds with no network access.

One command settles whether you need this step:
ls tools/photogrammetry-cli/.build/release/photogrammetry-cli

If that prints a path, skip the rest of this step.

If it errors, rebuild it. It takes a few seconds:
cd tools/photogrammetry-cli
swift build -c release

Confirm it runs:
./.build/release/photogrammetry-cli --help

If swift itself is missing, run this once and try again:
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer

There is no signing step and no device involved. It is a Mac command line
tool. It needs Apple silicon; it refuses to run otherwise and says so.

## Step 4. Install Stray Scanner

Install Stray Scanner from the App Store. It is free.
This is a fallback and coarse leg only.
Its exports are not fed to scan2cad and there is no ingest code for them.
Keep the folder it produces in case contingency ticket 3 is ever activated.
See docs/CONTINGENCIES.md for what would activate it.

## Step 5. Capture session

Use the stock Camera app. Do not use a scanning app for this leg.

Turn Live Photos off.
Turn the macro auto switch off in Camera settings.

Put the object on the printed mat, then set the standoff described below and
aim the phone at it. With the object at that standoff and centred, long press
the middle of the screen to lock automatic exposure and automatic focus.
VoiceOver announces AE slash AF Lock when the lock takes, so you do not have to
see the yellow badge to know it worked. If nothing is announced, lift your
finger and press again for longer.
Keep that lock for the whole session.

Light it as a rule rather than as a thing to look at: two or more lamps, or
indirect daylight from a window. Never one bare bulb and never one hard
spotlight. One hard source makes shadows that move across the object as you
orbit, and photogrammetry reads a moving shadow as moving geometry.

Judge shine by touch, not by eye. If the object feels glass smooth or polished
under a fingertip, dust it with chalk or cover it with masking tape. When in
doubt, dust it: chalk on a matte object costs nothing, and a specular surface
has no stable texture and photogrammetry will fail on it.

Stand off about 25 to 30 centimetres and hold that distance.
Walk three orbit rings around the object.
Ring one is low, near the level of the table.
Ring two is at chest height.
Ring three is high, looking down on the object.
Take 20 to 30 photographs on each ring, in small steps, with heavy overlap.
Aim for 60 to 80 photographs in total.

AirDrop the photographs to the Mac as HEIC.
Put them in one folder with nothing else in it.

## Step 6. Reconstruct

Run the photogrammetry command line app on the photo folder.

Replace PHOTOS with the folder holding your photographs. Give the output its
own empty folder, because OBJ output writes three files side by side:

tools/photogrammetry-cli/.build/release/photogrammetry-cli PHOTOS out/scan/mesh.obj --detail medium

You do not need a separate converter. RealityKit itself writes USDZ only, so
the tool reconstructs to mesh.usdz and then converts that to mesh.obj for you.
You end up with mesh.usdz, mesh.obj and mesh.mtl. scan2cad reads the OBJ.

Useful options, none of them required:
--detail preview is the fastest and is the right choice for a first look.
--detail medium is the default and the one to trust.
--sensitivity high helps on matte objects with little surface texture.
--ordering sequential is a speed hint, correct only for one steady orbit.

The tool speaks as it works: it prints progress every ten percent, names each
file it writes, and reports skipped photographs. If it fails it prints one
line starting with the word error and exits non zero.

Expect a metric scaled mesh whose units are metres.

Sanity check the mesh without opening it, by counting what is in it:
grep -c "^v " mesh.obj
grep -c "^f " mesh.obj
A usable reconstruction of a palm sized object has tens of thousands of both.
A few hundred, or zero, means the reconstruction failed; that is the machine
readable half of the step 11 gate.

## Step 7. Run the tool

First listen to the description:
.venv/bin/python -m scan2cad.cli describe mesh.obj --units m

Then produce the editable script and the reference STEP file:
.venv/bin/python -m scan2cad.cli draft mesh.obj -o part_skeleton.py --step part_ref.step

The units flag matters. Photogrammetry meshes arrive in metres.
Synthetic meshes are in millimetres.
The report always states which assumption it used, so check that line first.

Listen to the whole report before judging it.
Pay attention to the snap log section. Every number the tool tidied is listed
there with its raw value, its snapped value, and the deviation between them.

## Step 8. First real accuracy audit

This is the most important step of the morning.

Take the five reference part dimensions out of the report.
Compare each one against your caliper values in out/ground_truth.txt.
Write down the actual error for each of the five.

The names differ on the two sides, so here is the mapping. scan2cad names what
it found; the design names come from tools/reference_part.py.

block_length, design 60.0, is the largest of the three gap dimensions the
report calls width, depth and height.
block_width, design 40.0, is the middle one of those three.
block_height, design 20.0, is the smallest of those three.
bore_diameter, design 12.5, is the LARGER of the two lines ending in
_diameter.
boss_diameter, design 8.0, is the SMALLER of the two lines ending in
_diameter.

The report calls the three gaps width, depth and height in the order of the
object frame it fitted, and which physical edge wins which name depends on
which face the fitter saw best. Match them by size, as above, not by name.
If only one _diameter line appears, the scan found only one of the two round
features; record that as a miss, it is a real result.

Expect errors somewhere in the range of one to ten millimetres.
That is the draft band this product was designed around.
It is not a failure. It is the number this project has never had until now.

Whatever comes out of this step is the first legitimate accuracy figure the
project has ever produced. Record it honestly, including if it is bad.

## Step 9. Scale cross check

Skip this step if you skipped step 1.

Do not try to choose photographs in which the mat is visible. You cannot check
that without sight, and you do not have to: the tool names every image it could
not use. Pass it a generous handful, say ten to fifteen files, for example the
first five file names from each of the three orbit rings, and let it report
which ones it found the mat in.

The audit needs camera intrinsics, so first write a small JSON file with the
keys fx, fy, cx, cy, all in pixels, for example out/intrinsics.json.
Take those from whatever the photogrammetry app reports, or compute them from
the EXIF focal length and the sensor size.
If you cannot get intrinsics in a couple of minutes, skip this step. It is a
cross check, not a dependency.

Then run, all on one line:
.venv/bin/python tools/mat_audit.py audit PHOTOS --intrinsics out/intrinsics.json --mat-scale-correction FACTOR

Replace PHOTOS with the ten to fifteen file names.
Replace FACTOR with the number you wrote down at step 1, which is 1.0 if you
took option A there.

What you get, and what to do with it.

The tool prints one line per image. An unusable image says so by name and is
skipped. A usable one gives its mat corner count, its reprojection error in
pixels, and the true distance in millimetres from that camera to the mat.
Two facts to listen for. First, that at least a few images were usable at all:
if fewer than two were, the mat was not detected and this cross check cannot be
made this morning. Second, that the camera distances land near the standoff you
actually held, which was 250 to 300 millimetres; a set of distances far from
that means the intrinsics are wrong, not that the mesh is.

That is as far as the default path goes, and it is enough to tell you whether
the mat was captured well enough to be worth trusting.

Going further needs camera positions from the reconstruction, passed with
--recon-poses. The file is JSON, mapping each image file name to that camera's
centre in the reconstruction's own units, like this:
{"IMG_0001.HEIC": [0.12, -0.03, 0.41], "IMG_0002.HEIC": [0.15, -0.01, 0.40]}
Given those, the tool reports the implied millimetres per reconstruction unit,
which for a metric mesh in metres should read near 1000.

Apple's PhotogrammetrySession does not publish its camera poses, so this branch
is for COLMAP, which writes them in images.txt, and it belongs to contingency 2
rather than to this morning. Do not go looking for iPhone camera poses; there
are none to find.

This is an independent check. It is not part of the pipeline and it does not
feed the pipeline. It only tells you whether to believe the mesh scale.

The tool also has a self test that needs no photographs and no mat:
.venv/bin/python tools/mat_audit.py self-test
That prints a synthetic scale recovery curve. It says nothing at all about real
capture accuracy, and it is not evidence for step 10.

## Step 10. Decision gate, COLMAP

Do nothing here unless the evidence demands it.

Open the gate only if the photogrammetry scale error exceeds 0.3 millimetres,
or 0.3 percent, on the roughly 100 millimetre reference dimensions from step 8.

If and only if that happens, spend 30 minutes on brew install colmap and run
sparse structure from motion only, with the mat corners as ground control
points. The full ticket is contingency 2 in docs/CONTINGENCIES.md.

If the gate does not open, do not install COLMAP. Time spent there is time not
spent on step 13.

## Step 11. Decision gate, autofocus lock shim

Do nothing here unless the evidence demands it.

The gate has two halves and both must be true. Every part of it is a number or
an exit code, so none of it needs sight.

Half one, the reconstruction failed. Any one of these counts:
the photogrammetry app exited non zero or printed an error;
the OBJ vertex or face counts from step 6 are in the hundreds or are zero;
scan2cad exited non zero saying that fewer than two primitives were found.

Half two, the failure is attributable to focus or exposure hunting rather than
to coverage or to a shiny surface. Measure it:
.venv/bin/python tools/frame_sharpness.py PHOTOS/*.HEIC
That prints one sharpness number per frame and then names every frame far
below the session median. If a third or more of the session is named, focus
hunting is the explanation and the gate is open. If none or a handful are
named, the frames were sharp and the problem is elsewhere; delete the named
frames, reconstruct again, and do not open the gate.

If and only if both halves hold, read contingency 1 in docs/CONTINGENCIES.md.

## Step 12. Optional Backflip baseline

This one is your call and it costs twenty dollars a month.

If you want a comparison point, upload the same mesh to Backflip.
Note what feature tree it emits.
Note which small features it silently gets wrong or misses entirely.

This is for the decision record only.
Nothing from it enters the pipeline.

## Step 13. The real test

Scan one object you actually care about.
Choose something unknown or non prismatic, such as an unfamiliar bracket or a
housing you do not have a drawing for.
Do not choose a part that already has a datasheet. A datasheet part proves
nothing, because the datasheet already beat the scanner.

Run steps 5 through 7 on it.
Then answer one question: did the report and the skeleton script let you act on
that object.

That answer is the success metric for this entire project.
Everything else in this repository is machinery in service of that one question.
