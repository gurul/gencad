# Snapshots

## Display modes

`--display` takes a mode, the Viewer's Display modes: `solid` (the default:
shaded, with the model's CAD edges), `shaded` (the same surfaces, no edges),
`parts` (Solid with each part its own colour), `xray`, `hidden-line` or
`wireframe`. Each is drawn at its own defaults: a mode has nothing else to set.
`--grid` draws the measuring grid under the model in any mode; it is off by
default. The grid has minor and major lines at round steps sized to the model, a
red X axis and a green Y axis, and fades out around the origin.

`--display` also takes a JSON object, or a JSON file path, in the Viewer's
display shape: `mode`, `grid` (a boolean), `appearance` (`light`, the CLI's
default, or `dark`), `camera` (`projection`, `focalLength`), `clip` and
`exploded`. Anything else is refused. A job's `display` is the same object.

`--preview` (a job's `"preview": true`) draws Preview's photographic look
instead of the display mode: studio lighting, floor and environment, in
perspective, at Preview's defaults. It draws no grid, and is view mode only.

```bash
cadgen step snapshot part.step review.png --display xray --grid
cadgen step snapshot part.step review.png --preview
cadgen step snapshot part.step review.png --display '{"mode":"parts","appearance":"dark"}' --camera front
```

`clip.partColors` defaults to true: caps take normal part base colors, excluding
hover/selection tints, and stay opaque even for transparent parts. False restores
uniform amber caps. Textures and vertex-color variation are not sampled; a mesh
with several materials uses its first material color.

A clip keeps the part of a model on the lower side of a plane across
`axis` (`x`, `y` or `z`), or the upper side with `invert`, and fills the cut
faces. The plane stands at `at`, its coordinate on the axis in the FILE's unit in
the model's own frame — a STEP's millimetres (the numbers `--mode list` prints as
bounds), a GLB's, a URDF's and an SDF's metres, a 3MF's declared unit, an STL's
own numbers — or, without `at`, through the middle of the model at rest. Every 3D
input takes one, as the viewer's Clip cuts every 3D file. A camera facing
the cut (`right`, `back` or `top`; `left`, `front` or `bottom` inverted) draws a
section view. `--camera` or a job/output `camera` specifies pose and framing;
`display.camera` specifies projection and focal length (20–200 mm). Preview
uses perspective; the display modes use the shared projection, orthographic by
default.

The `shaded`, `xray`, `hidden-line` and `wireframe` modes are told apart by a CAD
model's topology edges, and apply to STEP/STP inputs only. `exploded` moves parts
apart: a STEP assembly's, or a GLB's rigid nodes (a GLB of one is refused as it
renders, saying so); an STL, a 3MF or a robot description refuses it by name. A
mesh or a robot description (STL, 3MF, GLB, URDF, SRDF, SDF) takes `solid`, or
`parts` (each object, mesh or link its own colour; a file of one part is drawn in
Solid, as the Viewer offers Parts only for several), with `--grid` and `clip`, or
`--preview`, and refuses unsupported settings by name before anything is rendered. A robot job's `selection.hide` takes its part ids (a
Quick Edit's view names the parts the Links panel hid); `focus` is a STEP's.

## Meshes and robot descriptions

A GLB, an STL, a 3MF and a URDF, SRDF or SDF are drawn with the scene the CAD
Viewer draws for them: the snapshot's page and the viewer build it with the same
code, dress it in the same look for the same display settings, and pose it the
same way. A snapshot therefore cannot show one of these files differently from the
viewer; only the camera framing, the image size and the encoding are the
snapshot's own.

- A GLB is its own glTF scene: nodes, skins, morph targets and authored
  materials, drawn where its skins and morph weights put them. `solid` wears the
  viewer's surface over its colours, maps and opacity; `--preview` shows the finish
  the file authored. Its clips play in the viewer's preview: a snapshot draws the file
  at rest, lights and grounds it on the box its clips sweep, as the viewer does,
  and refuses `--animation` and `--video`.
- An STL is one object and a 3MF one per object (and per material within one),
  each in its colour. They author no finish: `solid` wears the viewer's surface and
  `--preview` the studio's.
- A robot is drawn where the viewer opens it: every joint at its default, then an
  SRDF's `home` group state, with the joints `--joint-values` names on top. A
  colour the description gives a visual wins over the colours its link mesh
  carries, and a link mesh that cannot be loaded fails the snapshot rather than
  leaving the link out.
- The ground is sized from the rest placement, so a pose never rescales it; only
  the floor's height follows a posed robot down.
- `--mode list` lists what the scene drew, one row per mesh: a `ref` naming it,
  its `name`, its triangle and vertex counts, and its bounds as drawn. A robot's
  rows run down its tree from the root link. A GLB's ref is its node, `#n12` (the
  file's `nodes[12]`), as a Quick Edit names it; a 3MF's is its object's place in the
  build, `#o2.1`; a robot's is its part id. `--focus` and `--hide` are STEP-only (a
  robot job's `selection.hide` takes its part ids).

## Drawings

A `.dxf` is not rendered in a scene at all, so `cadgen dxf snapshot` is the
narrowest door of the seven. It draws the whole drawing, fitted to the image and
head on, in the pens the file declares — the same picture the CAD Viewer's DXF
pane shows, from the same server-side payload, through the same drawing code.
What the viewer cannot show, the CLI does not render.

```bash
cadgen dxf snapshot plate.dxf review.png
cadgen dxf snapshot plate.dxf review.png --appearance dark --width 1600 --height 1000
```

It takes `TARGET`, `OUT`, `--job`, `--appearance` (`light`, the default, or
`dark`), `--width`/`--height`, `--size-profile`, `--debug` and `--json`, plus
`output.renderScale` and `output.transparent` in a job. An entity with no pen of
its own (ACI 7) is painted in the appearance's foreground on its background, so
`--appearance` is the whole of a drawing's display.

Everything that describes a scene is gone from the door rather than accepted and
ignored, and gone is not silent. `--camera`, `--display`, `--mode` and
`--view-labels` are out of the signature and out of `--help`, and passing one is
refused by name — what the flag meant, why a flat drawing has no such thing, and
what to pass instead — rather than reported as an unrecognized argument. A job
(or `cadgen snapshot` routing a `.dxf`) that carries a `camera` other than a plan view,
any `display` key but `appearance`, `mode` other than `view`,
`scale`, an output `label`/`viewLabel`, or `output.padding`, `output.viewLabels`
or `output.tightFrame` is refused by name with what a drawing is — in the same
words, because the flag and the job key are one request arriving two ways.

What a job may add is what the viewer's DXF pane shows and a Quick Edit's views
carry. A `camera` that is the drawing's **plan view** — looking straight down at
the sheet, `up` +Y — frames the window it names in place of the fit:

```json
{"input": "plate.dxf", "camera": {"target": [50, 30, 0], "position": [50, 30, 120], "up": [0, 1, 0],
  "orthographicHalfHeight": 30}, "outputs": [{"path": "window.png", "width": 1600, "height": 900}]}
```

(centred on 50, 30, 30 drawing units above and below the centre). An `annotation`
whose marks lie on the sheet (on no part, their points `x, y, 0` in drawing
coordinates) is drawn over the drawing, as the pane drew it. A Quick Edit prompt on a DXF writes
exactly this job.

## Requests and OUT

A request is accepted or refused before anything is built or deleted. Every
refusal that can be decided from the request, the input's kind and the files
beside it — unknown keys and values, a setting the input's kind cannot take, the
wrong door, conflicting options, an SRDF with no single paired URDF, an unknown
pose, clip or joint name — leaves an existing OUT untouched, for every job in a
packet. Only then is OUT cleared, so a failed build or render leaves no file
rather than the previous one. Occurrence refs are the one request check that
needs the built tree, so they are checked after the clear.

OUT's extension decides the encoding, and no job key does: view mode writes
`.png`, a video `.mp4` or `.gif`. Any other
extension is refused.

A job comes from `--job FILE` or from `TARGET OUT` and the flags; there is no
stdin form. With `--job`, each flag given overrides that setting in every job of
the packet, and `--width`/`--height` size every output. A TARGET given with
`--job` replaces every job's `input`: the same views over another model (a
revision, a sibling). OUT is ignored with `--job`; the jobs' outputs say where
the files go.

A `.snapshot.json` file can hold one job, a list of jobs, or a `jobs` envelope.
The envelope accepts shared `input` and `annotation` defaults:

```json
{
  "input": "/path/model.step",
  "annotation": { "units": "mm", "marks": [] },
  "jobs": [
    { "camera": "iso", "outputs": [{ "path": "/tmp/iso.png" }] },
    { "camera": "top", "annotation": { "units": "mm", "marks": [] }, "outputs": [{ "path": "/tmp/top.png" }] }
  ]
}
```

An omitted job field inherits its shared value. A present job field replaces the
whole value: lists and annotation objects are never merged. Use an
annotation object with `marks: []` to suppress shared marks for a job.
Per-job input paths and annotation file references still work. CLI flags override
both shared and per-job values. Other envelope fields are refused. The extension
is descriptive; `--job FILE` still reads existing `.job.json` files.

## Annotations

A job's `annotation` (the `--annotation` flag sets it on every job) is ink drawn over
the model: an annotation JSON file's path, resolved as a job's `input` is, or the
annotation object itself. Quick Edit captures a packet at Copy, Queue or
Send, with annotation inline at the top, the current view and distinct drawn views
(`cadgen.viewer.prompt_files`). Up to 1024 compact UTF-8 bytes is returned inline
in the prompt; larger packets are saved as one `.snapshot.json`. To render inline
JSON, save it to a temporary file first: `--job` takes a file path. No separate
annotation file or image is written.
Annotation chips do not copy or write separate files.
Snapshot reads the packet and hands the object to
the page, which draws it with the viewer's own code: what an agent renders is
what the person drew. `--mode list` takes no annotation; a drawing's (DXF) lies on
its sheet (see [Drawings](#drawings)).

```json
{ "units": "mm",
  "parts": { "o1.6.2.7": { "placement": [16 numbers, a 4x4 matrix in column order] } },
  "marks": [ { "id": "1", "kind": "stroke", "part": "o1.6.2.7", "placement": "surface",
               "view": "view 1", "points": [x, y, z, ...], "color": "#ff2d55", "opacity": 1,
               "width": 2, "widths": [...], "closed": false, "group": "g1",
               "touches": [{ "part": "o1.6.2.7" }] } ] }
```

- `marks[]`: `id` unique; `kind` is `stroke` (a line, `width` screen pixels at
  any zoom, `widths` the pen's share of it per point, `closed`), `area` (a fill: its outline's `outline` points, then the
  points inside it, which `triangles` index three at a time) or `text` (`text`
  at `fontPx` on screen, `points` its label's four corners). `color` is
  `#rrggbb`; `opacity` 0..1.
- `part` is the occurrence id the mark is fixed to, and its `points` (x, y, z
  triples) are in that part's own frame: the mark follows the part wherever the
  job puts it (exploded, posed), hides when it is hidden and is cut by the clip.
  A part the model no longer has falls back to `parts[id].placement`, where it
  was when the annotation was made. `part: null` is in model coordinates. A mesh or
  robot scene has no occurrence ids, so its marks take those fallbacks.
- `placement` (drawn on the model, or in space), `view` (the label of the view
  it was drawn in), `group` and `touches` (the parts under it as it was drawn)
  describe the mark and draw nothing.
- A stroke is as heavy against the image's height as it was against a viewer
  900 pixels tall.

Every field is checked before the model loads, and a refusal names the annotation
file and the mark (`ink.annotation.json: annotation: marks[2].color must be a #rrggbb
colour`). An unknown field is refused, never read as a default.

## Sizes

An output is sized by `--size-profile` (`output.sizeProfile`) — `simple`
1200x900, `simple-square` 1024x1024, `diagnostic` 1600x1200 (the default),
`labeled` 1600x1200, `assembly` 1800x1200, `assembly-large` 1920x1440,
`presentation` 2400x1600, `presentation-large` 2800x1800, `contact-sheet`
2400x1600 — or by `--width`/`--height`, whole pixels from 1 to 8192. An unknown
profile or a size outside that range is refused, never clamped.
`output.padding` is 0–0.15, `output.renderScale` 1–3, and `timeoutSeconds` a
positive number, checked when the job is resolved.

## The browser

A snapshot renders in Playwright's headless Chromium shell, which is a download of
its own (about 100 MB) into Playwright's browser cache. The first snapshot on a
machine downloads it and then renders, saying so on stderr; later snapshots reuse
it. One cadgen command installs it at a time (a lock in the state directory, beside
`settings.json`), and a snapshot started while another installs it waits for that
install rather than launching a half-unpacked browser. A browser that does not
start for any other reason has its install checked (which finishes one a killed
command left half done) and is launched once more before the snapshot fails with
the launch's own error.
Where the fix is not cadgen's to make, the failure names the command: no network
for the download, or a Linux host without the browser's system libraries
(`sudo … -m playwright install-deps chromium`, which needs root and apt).

## Diagnostics

`cadgen step snapshot part.step review.png --debug --json` adds diagnostics to
`SnapshotResult.debug`; without `--json` each entry prints as one `debug: {…}` line
after the saved paths. The same flag is available on the other snapshot doors
and as `debug=True` in Python. Every diagnostic entry identifies its input;
artifact-resolution information remains alongside `stageTimings`: a STEP entry's
`stepArtifact` names the `documentHash`, `tree` and store `view` it rendered,
their `componentCount` and `occurrenceCount`, and whether a `selectorIndex` was
composed. Normal results keep their file, warning and aggregate timing fields.

Still view renders report these measured browser durations in milliseconds:

| Field | Measured work |
| --- | --- |
| `loadSourceMs` | Source fetch, cached-mesh decoding or tessellation, and source composition |
| `preparePoseMs` | Requested animation loading/frame resolution and kinematics runtime preparation |
| `buildModelMs` | Render context and model/display-record construction |
| `prepareViewportMs` | Viewport, renderer and scene setup; this is not a draw |
| `waitViewportMs` | Waiting for the prepared viewport's asynchronous readiness |
| `captureMs` | Entire capture call, including readiness and all output stages below |

Exact-surface packages also report `stageTimings.sourceLoad`. Counts distinguish
`componentCount`, `cacheBatchCount`, `cacheHitCount` and `cacheMissCount`.
Measured durations are `probeMs` (metadata), `cacheReadMs` (bounded body fetch
and integrity validation), `cacheDecodeMs` (component views and metadata),
`meshBuildMs` (owned render arrays), and `composeMs` (occurrence composition).
Misses additionally measure `surfaceReadMs` (fetch and parse), `tessellateMs`
and `cacheWriteMs`. Miss-stage times sum per-component intervals across the
small concurrent pool, so they can overlap; absent stages are omitted.

`stageTimings.outputs` contains one measured entry per image, in output order,
with its `path` and these durations:

| Field | Measured work |
| --- | --- |
| `updateModelMs` | Output sizing, model pose/effects, exploded placement, topology edges and line resolution |
| `frameCameraMs` | Camera selection/fitting, including visible-vertex tight framing when enabled, and the camera's depth range when there is no studio |
| `prepareStudioMs` | Camera depth and photographic studio setup; absent without a studio |
| `drawSubmitMs` | The renderer's synchronous draw call |
| `encodeImageMs` | Image readback, optional view label and PNG/data-URL encoding |

WebGL submission may return before GPU work finishes. `encodeImageMs` can
include waiting for that work; these fields are browser wall times, not GPU
profiler measurements. `captureMs` contains `waitViewportMs` and the output
stages, so do not add those overlapping durations together.

Only stages actually reported by the runtime are included. List and
video results do not invent still-image measurements. Invalid/nonfinite
values and image payloads are excluded from diagnostic output. Measurements
belong to one render call and cannot carry over from a previous job.

The ordinary `timings.total_ms` covers the render packet, including browser
startup, shutdown and writing its outputs. Input resolution happens before
that interval. The browser stages cover narrower work and need not add up to
that total or to the complete CLI process time. Use this attribution to choose
a targeted profile; a small model's stage proportions do not establish where
a larger assembly spends its time.

Photographic snapshots (`--preview`) are Preview at its defaults: the floor
stands at the document's Z=0 plane, matte, and the lighting is Preview's Final
quality. Preview's own settings (lighting, background, floor) are the Viewer's
alone; a snapshot has none to set.

A Preview still is the Viewer's converged picture: 32 samples of its studio frame, a
fraction of a pixel apart, with ambient occlusion in the seams and recesses and the key
light's shadows as soft as its softbox. On a GPU that adds a fraction of
a second to the render; a video's frames, and a renderer that runs in software, draw one
sample each.
