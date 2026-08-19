# Decisions

This is the condensed decision record for scan2cad.
It states what was killed, what survived, and why, in one block per verdict.

The long form lives in docs/VERDICTS.md.
The rulings that override everything live in docs/SYNTHESIS.md.
The build specification lives in docs/PLAN.md.
Where this file and those disagree, SYNTHESIS wins, then PLAN, then VERDICTS,
then this file.

Read the permanent rejection list and the embargoed claims list at the end
before writing any new code or any new sentence about this project.

## Verdict 1. The whole product, descoped

The original product was a phone scan to parametric CAD pipeline whose only
possible differentiator was precision, and the metrology killed that outright.
iPhone LiDAR is plus or minus 10 millimetres with a feature floor around 5
centimetres and machine learning hallucinated depth between roughly 576 real
points; TrueDepth shows 1.8 to 4.5 millimetres of flatness error; ARKit drifts
20 to 40 millimetres per second.
A thirty dollar caliper delivers plus or minus 0.02 millimetres, three orders
of magnitude better than anything this pipeline could ever emit.
What defeated the total kill was accessibility, and only accessibility.
Every incumbent, paid or free, terminates in an artefact a blind user cannot
read: Backflip is a visual Fusion add in, Paramesh emits opaque STEP, Polycam
and KIRI emit meshes for visual editors.
There is one task the caliper and datasheet workflow genuinely cannot do for
this user, which is perceiving the shape of an unknown object, and sighted
makers solve it by looking.
So the product survives as perception tooling, not as reverse engineering CAD:
mesh in, plain language geometry report plus an editable build123d script with
named uncertainty tagged dimensions, STEP reference surfaces out.
Accepting that scan values are one to ten millimetre drafts deletes eighty
percent of the original scope, because the entire precision stack existed only
to chase a number the product no longer needs.

## Verdict 2. Custom iPhone capture, killed

The premise was a rewritten capture app logging 12 megapixel stills alongside
ARKit poses, and the poses are the part that is dead on the evidence.
ARKit VIO drifts 20 to 40 millimetres per second with discontinuous
relocalisation jumps, so its poses are worse than useless at precision
fidelity, and at coarse fidelity Stray Scanner already supplies ARKit poses,
depth and confidence for free with zero engineering.
The two places ARKit poses could actually plug into COLMAP are the two places
they do damage: pose_prior_mapper is position only with manual database
insertion and open stability bugs, and known pose triangulation would freeze
the drift into the reconstruction permanently.
The rewrite framing was a sunk cost mirage, because ARKit cannot coexist with
LeapDepth's AVCaptureSession, so the capture core would be replaced wholesale
and only about 150 to 200 lines of user interface shell and parser tests are
reusable at all.
It was also physically untestable on the night of the build: no phone, no
signing, no device deployment.
What survives is a written capture protocol rather than an app, which is step 5
of docs/MORNING_PROTOCOL.md, plus one evidence gated contingency ticket for an
autofocus lock shim over Apple's Object Capture sample.

## Verdict 3. COLMAP and GLOMAP, killed for the build night, kept as a gate

On the night of the build every input COLMAP needs was missing and every output
it produces was redundant, so installing 23 brew dependencies to run structure
from motion against zero real photographs produced zero decision relevant
information.
Dense multi view stereo is rejected permanently and not merely deferred,
because the downstream engine is CGAL Efficient RANSAC fitting planes and
cylinders to an oriented normal surface, which Apple's PhotogrammetrySession
already provides for free, so patch match on a CPU adds hours for no benefit.
The pose prior configurations are rejected permanently for the reasons in
verdict 2.
What defeats the total kill is that both cheap alternatives are exposed to the
same optics problem: mat based PnP inherits 5 to 22 micrometre per shot
distortion variation plus roughly 0.2 percent mat print error straight into
scale, and PhotogrammetrySession is a black box with no published accuracy
specification, so it may silently miss.
The one capability nothing else in the stack replicates is sparse structure
from motion with per image intrinsics refinement and mat corners as ground
control points, so COLMAP survives in exactly that configuration and nothing
else, behind the GeometrySource interface, activated only by a measured
failure.
The architecture of record is therefore PhotogrammetrySession as the black box
geometry and scale source, mat PnP demoted to an independent audit, and COLMAP
sparse held behind the step 10 caliper gate.

## Verdict 4. LiDAR and TSDF fusion leg, killed

This leg cannot see the subject matter: the user's parts are enclosures with
1.6 to 3 millimetre walls, 2 to 6 millimetre screw bosses and 8 to 12
millimetre port cutouts, and every one of those features sits an order of
magnitude below the sensor's roughly 5 centimetre feature floor.
TSDF fusion cannot repair that, only launder it, because averaging attacks
random noise while the dominant errors here are systematic, namely machine
learning hallucinated edges and bias, and pose correlated, namely VIO drift and
relocalisation jumps that smear ghost surfaces into the volume.
Confidence filtering is worse than nothing, because it filters on the depth
model's confidence in its own hallucination: it removes the honest holes and
keeps the confident fabrications.
Accessibility cuts against this leg rather than for it, because a sighted user
glances at a fused mesh and sees mush, whereas a screen reader user receives
named dimensions as fact, so a confidently wrong geometry source is an
accessibility hazard and the one failure mode this product must never have.
Every residual role is dominated: coarse context geometry goes to
PhotogrammetrySession's free metric mesh at zero adapter cost, and a future
scale prior would consume a roughly 50 line Stray Scanner pose CSV parser, not
a TSDF volume.
The kill is enforced architecturally rather than by discipline: the fitting
stage accepts one cloud or mesh of photogrammetry or synthetic provenance, with
no source enumeration and no fusion hook, and tests/test_no_dead_imports.py
fails the build if TSDF or integration code reappears in src.
open3d stays installed purely as a mesh and point cloud utility library.

## Verdict 5. The B-Rep middle, descoped to a thin middle

Automated primitive soup to watertight B-Rep is a research problem, not an
engineering task: the state of the art, HoLa, reaches only 82 to 84 percent
validity on synthetic data, Point2CAD is licence dead with dead dependencies,
and ComplexGen needs CUDA, Gurobi, Mosek and Windows on an arm64 Mac.
Constraint inference is vacuous at this noise level, because you cannot
statistically separate designed parallel from measured two degrees off when
sensor angular uncertainty swamps design intent, so every inference engine
degenerates into threshold snapping, which is about fifty lines rather than a
solver.
Rebuilding a funded company's flagship feature overnight, worse, is not a
strategy: Backflip went generally available at twenty dollars a month selling
exactly this automated middle, and reviewers already report it missing knob
notches and thin walls.
For this user the human in the loop is not a workaround to be automated away,
it is the accessible interface: an emitted script with named dimensions and
datums is the product, and typing one extrude line costs less than the trust
deficit of an untested Boolean.
So the middle survives as three stages and no more: fit planes and cylinders
with per primitive residual and inlier count, extract a dominant orthogonal
frame with reported snapping and concentric or equal radius merging, and emit a
script skeleton with datums, named dimensions and commented assembly hints.
Constraint graphs, trimming, sewing and all executed Booleans or extrudes are
killed, and no stub file exists for them, because a stub signals intent to
build it later.

## Verdict 6. Synthetic validation, descoped to plumbing verification

A synthetic dimensional error report validates the pipeline against the noise
model we wrote ourselves from the metrology table, which is circular.
The real failure modes are structurally unsimulatable with independent
identically distributed noise plus a bias term: LiDAR depth is hallucinated
between real points by a learned prior that invents planes and erases edges,
TrueDepth error is spatially correlated warp, ARKit drift is temporally
correlated with discontinuous jumps, and photogrammetry's dominant threat is
optical image stabilisation and autofocus intrinsics instability between shots.
Reporting a millimetre figure from a virtual bracket would be exactly the sin
the literature commits, and it would anchor a decision on fiction.
The second danger is overfitting: agents left alone overnight will tune RANSAC
epsilon, normal estimation radius and cluster thresholds until the synthetic
bracket passes, and every threshold tuned to our own generator is a regression
planted for real data.
What defeats the full kill is that the chain from points to normals to RANSAC
to parsing to build123d to STEP had never once executed end to end, and finding
interface bugs at nine in the morning would burn the scarcest resource, which
is the user's capture session.
So a thin harness survives as plumbing verification and a permanent regression
suite, never as accuracy evidence: a noise zero gate that proves the code path
and the algorithmic ceiling, and a small noise multi seed sweep that proves the
thresholds are not knife edged.
Thresholds are frozen in src/scan2cad/thresholds.py before the sweep runs and
may not be tuned to make it pass; degraded mesh failures are recorded as
findings.

## Permanently rejected

These are closed. They do not come back in a later version, and no future work
item may quietly reintroduce them.

ARKit pose logging as an input to this pipeline.
Mat based PnP poses dominate it at precision fidelity and Stray Scanner
supplies free ARKit poses at coarse fidelity, so it has no remaining role.

COLMAP pose_prior_mapper integration.
Position only priors, manual database insertion, open stability bugs, and a
prior source that drifts 20 to 40 millimetres per second.

Frozen pose triangulation with point_triangulator.
Deterministic, and deterministically bakes VIO drift into every triangulated
point.

CPU dense multi view stereo.
Hours of computation to feed a primitive fitter that does not benefit from it,
on a machine with no CUDA.

LiDAR derived geometry anywhere in the dimension fitting stage.
A 10 millimetre systematic bias against a 0.2 to 0.4 millimetre print fit
tolerance is a 25 to 50 times specification miss, and TSDF averaging cannot
remove systematic hallucination or pose drift.

Silent snapping.
Any stage that replaces a fitted number with a tidier one emits a SnapRecord
carrying the raw value, the snapped value, the deviation and the rule.
A tidy number with no audit trail is a lie about data.

Also permanently rejected, from the same verdicts: pairwise constraint graph
solving, executed Booleans, trimming and sewing, and simulators of hallucinated
depth, correlated warp, pose drift or intrinsics jitter.

## Embargoed claims

These sentences may not appear in the report, in the emitted script, in
out/MORNING_REPORT.md, in the README, or in any commit message.
This list is restated in screen-reader form from docs/PLAN.md section 7 and is
binding. Restated, not quoted: PLAN.md writes each item as one long line, and
the screen-reader rule in docs/SYNTHESIS.md ruling 7 asks for one fact per
line, so each item below is the same prohibition broken into short sentences.
Every item of the PLAN list is present. Where the two differ in wording they do
not differ in meaning, and PLAN.md section 7 is the authority.

No sentence of the form "the pipeline achieves plus or minus X millimetres".
Synthetic numbers are plumbing verification only.
The iPhone accuracy claim is embargoed until real capture audits exist, which
means until step 8 of docs/MORNING_PROTOCOL.md has been performed.

No press fit claim, no mating fit claim, no sub millimetre claim, ever.
The two channel model makes them unnecessary by design.

No claim of competing with Backflip on accuracy.
This product competes with silence, because no accessible alternative exists.
It does not compete with CAD tools on precision.

No implication that scan dimensions are trustworthy.
Every emitted dimension is a draft until it is overwritten from a caliper
reading or a datasheet.

No hiding of degraded mesh failures.
They are reported as findings. They are not tuned away and they are not
omitted from the report.

Every synthetic result carries the caption: plumbing verification only,
synthetic noise model, not predictive of iPhone accuracy.
