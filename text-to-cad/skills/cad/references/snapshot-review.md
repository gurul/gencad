# Snapshot review

Read this file when choosing visual checks for saved STEP/STP or mesh outputs.
Use `cadgen step snapshot` for STEP, or the corresponding `stl`, `3mf` or `glb`
snapshot command for meshes (see [mesh exports](supported-exports.md)). The
CAD topology, selection and motion controls below apply to STEP; clipping applies
to every 3D input, and exploding to a STEP or a GLB of several parts.

## Policy

Every created or visibly updated part or assembly gets at least one reviewed
PNG snapshot of its STEP, or its mesh when no STEP is declared. Passing geometry
checks does not waive this visual review. Use the format's snapshot command.
For a STEP pose or clip frame, pass `--kinematics` and/or
`--animation CLIP --time SECONDS`. A motion review may additionally need video;
see [kinematics](kinematics.md#reviewing-motion).

Skip saved snapshots only when no visible geometry was created or updated, or no valid artifact exists:

- pure format/export requests where geometry is unchanged
- source changes that do not alter visible geometry
- inspection-only tasks (for example direct measurement questions) that create or update nothing
- failed Python or STEP generation before a valid artifact exists

When skipping, report the reason and the deterministic evidence that still ran.

Do not loop on snapshots. Rerender only when a source repair changed visible geometry or when a specific visual finding needs confirmation.

## Packet sizing

Choose views that expose the features being checked. One may be enough;
add an opposing view for hidden exterior features, an orthographic view for
a pattern or silhouette, or a clipped view for internal geometry. No fixed set of
views proves every face or feature is correct.

## Small packet

For example, a four-view comparison can use one JSON job:

```json
{
  "input": "models/part.step",
  "mode": "view",
  "outputs": [
    { "path": "/tmp/render/iso.png", "camera": "iso" },
    { "path": "/tmp/render/iso_opposite.png", "camera": { "direction": [-1, 1, -0.8] } },
    { "path": "/tmp/render/top_ortho.png", "camera": "top" },
    { "path": "/tmp/render/front_ortho.png", "camera": "front" }
  ],
  "output": { "viewLabels": true, "padding": 0.12, "sizeProfile": "diagnostic" }
}
```

Use only the views relevant to the design. Opposed isometric views reveal more
exterior faces, but neither they nor orthographic views reveal all occluded geometry.

Set `input` to the saved STEP/STP artifact using a relative or absolute path
(documents only: run a `.py` model first). With no explicit display settings,
snapshots use the `solid` preset, Light appearance and an orthographic isometric
camera. Every mode defaults to 1600x1200 (the `diagnostic` profile). Job `mode`
is `view` or `list`; display presets are a separate choice.

`--size-profile` (`output.sizeProfile` in a job) is one of exactly these names;
anything else is refused with this list:

| Profile | Size |
| --- | --- |
| `simple` | 1200x900 |
| `simple-square` | 1024x1024 |
| `diagnostic` (default), `labeled` | 1600x1200 |
| `assembly` | 1800x1200 |
| `assembly-large` | 1920x1440 |
| `presentation`, `contact-sheet` | 2400x1600 |
| `presentation-large` | 2800x1800 |

`--width`/`--height` (an output's `width`/`height` in a job) override the profile
with a whole number of pixels from 1 to 8192; a larger request is refused rather
than clamped. With `--job` they size every output in the packet.

`--display` takes one of the Viewer's six Display modes, each drawn at its own
defaults: `solid` (the default: shaded, with edge linework), `shaded` (the same
surfaces, no edges), `parts` (Solid with each part its own colour), `xray`
(translucent surfaces with occluded edges visible), `hidden-line` (linework with
occluded edges suppressed), and `wireframe` (edges only); they use the shared
projection, orthographic by default. `--grid` draws the measuring grid (red X and
green Y axes) under the model in any mode; it is off by default. `--preview` draws
Preview's photographic look instead, in perspective with studio lighting, at
Preview's defaults; it draws no grid and is view mode only.

```bash
cadgen step snapshot STEP/part.step tmp/review.png --display hidden-line --grid
cadgen step snapshot STEP/part.step tmp/review.png --preview
cadgen step snapshot STEP/part.step tmp/review.png --display display.json --camera front
```

`--display` (and a job's `display`) also takes the Viewer's display object, inline
or as a JSON file: `mode`, boolean `grid`, `appearance` (`light`, the CLI default,
or `dark`), `camera` (`projection`: `orthographic` or `perspective`; `focalLength`:
20–200 mm), and the shared tools `clip` and `exploded`. A mode has no settings of
its own, and anything else is refused.

`--camera` (or a job's top-level or per-output `camera`) sets pose and framing
(`preset`, `position`, `target`, `up`, `direction`, `zoom`,
`orthographicHalfHeight`); projection and focal length belong in
`display.camera`. Every 3D input takes `clip` (`at` in the file's own unit), and
`exploded` takes a STEP or a GLB of several parts. `shaded`, `xray`, `hidden-line`
and `wireframe` are STEP-only; meshes and robot descriptions take `solid` or
`parts`, `--grid`, or `--preview`. DXF uses `--appearance` and has no scene display
modes.

`camera` is a preset (`front`, `back`, `left`, `right`, `top`, `bottom`, `iso`),
an `azimuth:elevation` pair, or a camera object. `output` takes `sizeProfile`,
`padding` (0–0.15), `renderScale` (1–3) and the booleans `viewLabels`,
`tightFrame` and `transparent`. Top-level `timeoutSeconds` is a positive number
and `scale` is `cad` or `urdf`. Unknown keys and out-of-range values are refused.

For close macro views in normal CAD, a JSON job can set `quality.tessellation` to
`{"chordTolerance": 0.0005, "angleTolerance": 0.10}`. Chord tolerance is
relative to each component's bounding diagonal; angle tolerance is radians.
These positive numeric overrides retessellate the exact STEP surfaces and use
separate shared-cache entries. They do not change the STEP geometry or a model's
declared mesh-export tolerances. Use them only when visible faceting needs finer
sampling; lower tolerances cost more memory and render time. `chordTolerance`
must be at least `0.00001` and `angleTolerance` at least `0.005` — finer than
that exhausts the renderer instead of improving the image, and the job is
refused.
Existing mesh documents cannot be retessellated this way. The explicit top-level
sampling request works in every display mode. When it is omitted, `--preview` draws
at Preview's final LOD.


### Flags and job keys

A JSON job's keys are the flags without their dashes, and the job is the only
place some shapes exist. `--animation CLIP --time SECONDS` is ONE request, so a
job carries it as one `animation` object — `time` is not a top-level job key:

```json
{
  "input": "models/arm.step",
  "kinematics": "open",
  "animation": { "clip": "demo", "time": 2.0 },
  "outputs": [{ "path": "/tmp/render/demo_t2.png", "camera": "iso" }]
}
```

`clip` names a clip embedded in the document sidecar's animation and is required;
`time` is seconds, finite and >= 0, defaulting to 0. A bare clip name is the
FLAG's spelling, not the job's: `"animation": "demo"` is refused, as is any key
the job does not support — the error lists the supported set.

A `"video"` object beside it renders the clip's SPAN into the `.mp4` or `.gif`
the single output names, instead of one frame: `{"fps": 30, "seconds": <what is
left of the clip>, "start": 0, "quality": "review", "loop": true}`, every key
optional and every other key refused. It needs `animation`, refuses an
`animation.time`, refuses a `start` past the end of the clip, and needs ffmpeg
installed. See `kinematics.md`, "Rendering the whole clip".

In a JSON job these two flags are the one exception to "job key = flag name without dashes": they nest under a job-level `selection` object, and a top-level `"hide"` or `"focus"` is rejected as an unknown key. Selection applies to the whole job, not to one output — to hide or focus parts for a single view, give that view its own job in a `jobs` array.

```json
{
  "input": "STEP/assembly.step",
  "mode": "view",
  "selection": { "hide": ["#o1.3", "#o1.4"] },
  "outputs": [{ "path": "tmp/render/without_covers.png", "camera": "iso" }]
}
```

`"selection": { "focus": ["#o1.2"] }` is the `--focus` form; `focus` and `hide` are the only selection keys. Every other flag keeps the plain rule (`--kinematics` → `"kinematics"`, `--animation CLIP --time S` → `"animation": {"clip": ..., "time": ...}`).

With `--job FILE`, other flags override every job in it; there is no stdin form.
A TARGET given with `--job` replaces every job's `input`, so one job file renders
the same views over another model; OUT is ignored, and the jobs' outputs name
the files:

```bash
cadgen snapshot STEP/bracket_v2.step --job views.job.json
```

### Annotations and Quick Edit views

`--annotation FILE` (a job's `annotation`: a path or the object) draws a person's ink
over the model as they drew it in the CAD Viewer: each mark sits on its part,
follows it when the view explodes or poses the model, and is cut by a clip.
A DXF annotation lies on the drawing plane; `--mode list` takes none.

A Quick Edit prompt carries a snapshot packet captured only when Copy, Queue or
Send is pressed. Up to 1 KiB of compact UTF-8 JSON is included directly in the
prompt; larger packets are saved to a temporary `.snapshot.json` and named by
absolute path. Save inline JSON to a temporary `.snapshot.json` before calling
`cadgen snapshot --job <file>`; the CLI takes a file path. Render and inspect supplied
annotations before editing. A view without annotations is optional context: render it
only when useful to the request; its presence alone does not require inspection.
The `jobs` list includes the current view and every distinct drawn view with
remaining ink. A matching drawn view uses the exact current framing in the export;
otherwise `current view` is appended. Text, selections and measurements without
ink still capture the current view. Shared `input`, inline `annotation` and
`measurements` live at the top level once. An individual job can override any
shared field (whole-value replacement, not a merge); empty `marks` or `measurements`
suppress shared marks. Captured 3D views preserve projection and lens. No PNGs are
rendered or attached at handoff. Input and output paths are absolute, so the packet
can be replayed from another working folder. Annotation and measurement chips do not
export individual references; their data travels in the snapshot packet. The job's `measurements` are
the distances they measured, each `{start, end, label, color}`. Read these from the
JSON when interpreting the prompt: endpoints are world coordinates in the model's
units, and `label` is the displayed value and unit. These are reference dimensions,
not constraints applied to the CAD model. They are drawn over every
view as the viewer drew them; a label starting `≈` was measured on a mesh's triangles and
is approximate. A Quick Edit from any 3D file replays: a robot's job carries its
`jointValues` and the parts hidden in its Links panel (`selection.hide`), a GLB's or a
3MF's its `display.clip`, and a multi-part GLB's its `display.exploded`. `cadgen snapshot --job <job
file>` renders those views again: after an edit, run it to see the change from
where the person looked, with their annotation still on it. Add a TARGET to aim the
same views at another document.

## Clipped views

Use the viewer's Clip setting to reveal internal geometry in a normal view snapshot.
`display.clip` takes `enabled`, `axis` (`x`, `y` or `z`), `at` in the file's own unit
(a STEP's millimetres; a GLB's, URDF's and SDF's metres; a 3MF's declared unit), and
`invert`. The cut stays capped and uses the same scene as the viewer.

```bash
cadgen step snapshot STEP/housing.step tmp/cut.png --camera back --display '{"clip":{"enabled":true,"axis":"y","at":12.5}}'
```

OUT's extension picks the format: a view writes `.png`, and a video writes
`.mp4` or `.gif`. Other extensions are refused instead of writing PNG bytes under them.

## Output paths

Name the file and you get that file:

```bash
cadgen step snapshot STEP/bracket.step tmp/review.png
# then Read tmp/review.png
```

OUT (and an output's `path` in a JSON packet) is written exactly as given,
relative to the working directory. Check the command's exit before reading. A
refused request — an unknown key or value, a setting this kind of input cannot
take, the wrong door, conflicting options, an unknown pose, clip or joint name —
leaves an existing file untouched, for every job in a packet. Once the request is
accepted the target is cleared before anything is built, so a failed build or
render (and an occurrence ref the model does not have, which needs the built
tree to check) leaves no file; successful output is written atomically.
Reuse `tmp/review.png` during iteration, or name before/after images when both
are needed for comparison.

Pass a directory (`tmp/` as OUT, or an output `path` that is one) only when the name does not matter: a timestamped name is generated inside it, and that is the one case where you read the path from the `saved snapshot:` line.

## Targeted additions

Add views only when the brief or a failure mode calls for them:

- reference-image reproduction: one snapshot from the reference image's viewpoint for side-by-side comparison
- `display.clip` with a camera facing the cut: shell, bore, internal cavity, passage, blind hole, enclosure, or wall/floor relationship (see [Clipped views](#clipped-views))
- `display.mode: "solid"`: shaded CAD view with visible edge linework
- `display.mode: "shaded"`: shaded surfaces without the edge overlay
- `display.mode: "xray"`: translucent surfaces with hidden/occluded edges visible
- `display.mode: "hidden-line"`: line-focused review with occluded edges suppressed
- `display.mode: "wireframe"`: edge-only review for internal overlap or interference
- `display.grid: true`: a measuring grid under the model in any display mode, for reading size and placement at a glance
- labeled or annotated review: use supported CAD Viewer refs, selections, screenshots, or GUI review links

Exploded or labeled review is an intent, not a render mode. Satisfy it through supported CAD Viewer mechanisms, supported JSON job settings, or the GUI link.

## Diagnostic review

Visual review is diagnostic, not authoritative. Convert every visual concern into a follow-up geometry check before using it as a validation claim:

- hole pattern appears asymmetric -> measure hole centers and compare offsets
- lid, child part, or occurrence appears offset -> inspect frames and mating deltas
- gusset, boss, standoff, rib, or plate may be floating -> inspect solid count, labels, connectivity, contact, or relevant distances
- cavity, bore, or blind hole looks wrong -> review a clipped view, then measure wall thickness, depth, or through-condition
- repeated pattern looks uneven -> measure pattern centers, angular spacing, or occurrence frames

Final reports name what the snapshots showed, or the documented skip reason, and which deterministic checks support any visual finding. The PNGs are for your review; the user sees the model in the viewer, so attach one only when they ask for an image.
