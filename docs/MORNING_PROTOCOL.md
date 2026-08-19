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

Take the caliper and measure the long span across the full black grid.
The nominal long span is 139.87 millimetres, across seven squares.
That is not a typo for 140.0. The board is rendered at 300 dots per inch and
one square is rounded to a whole number of pixels, so the file on disk is very
slightly under seven times 20.0 millimetres, and 139.87 is the honest number to
divide by.
The board is seven squares by five squares, 20.0 millimetre nominal squares,
15.0 millimetre markers, dictionary DICT_5X5_1000.

Compute the correction factor as measured span divided by 139.87.
Write that number down. You need it again at step 9.
A print error of about 0.2 percent is normal and expected.
This step is the only thing that removes it.

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
The name is what scan2cad will call it. The number is the design intent.

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

Skip this step if the overnight build already produced the binary.
Check docs or the build log first; this item was timeboxed and is allowed to
have been skipped.

If it was not built, open Apple's sample project named
Creating a Photogrammetry Command Line App in Xcode and press Build.
There is no signing step and no device involved. It is a Mac command line tool.
This takes a couple of minutes and needs no code changes.

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
Long press on the object to lock automatic exposure and automatic focus.
Keep that lock for the whole session.

Put the object on the printed mat.
Light it evenly and diffusely. Avoid a single hard lamp and avoid hard shadows.
If the object is shiny, dust it with chalk or cover it with masking tape.
A specular surface has no stable texture and photogrammetry will fail on it.

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
Ask for OBJ output if the tool offers it.
If it only offers USDZ, take USDZ and convert it to OBJ afterwards.
Expect a metric scaled mesh whose units are metres.

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

Expect errors somewhere in the range of one to ten millimetres.
That is the draft band this product was designed around.
It is not a failure. It is the number this project has never had until now.

Whatever comes out of this step is the first legitimate accuracy figure the
project has ever produced. Record it honestly, including if it is bad.

## Step 9. Scale cross check

Skip this step if you skipped step 1.

Choose five of the still photographs from the capture session.
The mat must be visible in all five.

The audit needs camera intrinsics, so first write a small JSON file with the
keys fx, fy, cx, cy, all in pixels, for example out/intrinsics.json.
Take those from whatever the photogrammetry app reports, or compute them from
the EXIF focal length and the sensor size.
If you cannot get intrinsics in a couple of minutes, skip this step. It is a
cross check, not a dependency.

Then run, all on one line:
.venv/bin/python tools/mat_audit.py audit PHOTOS --intrinsics out/intrinsics.json --mat-scale-correction FACTOR

Replace PHOTOS with the five file names.
Replace FACTOR with the number you wrote down at step 1.

Compare the scale the audit implies against the scale of the mesh that the
photogrammetry app produced.
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

Open the gate only if the reconstruction visibly fails, or if the errors you
measured at step 8 are clearly attributable to focus hunting or exposure
hunting between shots.

If and only if that happens, read contingency 1 in docs/CONTINGENCIES.md.
Blurry or badly exposed frames are the symptom to look for.

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
