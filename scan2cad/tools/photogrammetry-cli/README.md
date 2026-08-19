# photogrammetry-cli

A small Mac command line front end for RealityKit's PhotogrammetrySession.
It turns a folder of photographs into a metric scaled mesh that
`scan2cad describe` and `scan2cad draft` can read.

This is scan2cad's own tool, not Apple's HelloPhotogrammetry sample. It was
written against the RealityFoundation interface shipped in the macOS SDK, and
it differs from the sample in three ways that matter to this project: it has
no external package dependencies, it converts to OBJ for you, and its output
is plain ASCII with one fact per line so a screen reader can follow it.

## Requirements

- Apple silicon. PhotogrammetrySession refuses to run otherwise, and the tool
  says so and exits with code 3.
- macOS 14 or later, with Xcode or the command line tools installed.

## Build

    swift build -c release

The binary lands at `.build/release/photogrammetry-cli`. There are no package
dependencies, so this works with no network access.

## Use

    .build/release/photogrammetry-cli INPUT_FOLDER OUTPUT_PATH [options]

`INPUT_FOLDER` holds the capture images and nothing else. HEIC and JPEG both
work.

`OUTPUT_PATH` ends in `.usdz` or `.obj`. Give OBJ output its own folder: it
writes three files side by side.

Options:

- `--detail` one of `preview`, `reduced`, `medium`, `full`, `raw`.
  Default `medium`. Use `preview` for a fast first look.
- `--sensitivity` one of `normal`, `high`. Default `normal`.
  Use `high` on matte objects with little surface texture.
- `--ordering` one of `unordered`, `sequential`. Default `unordered`.
  `sequential` is a speed hint, correct only for a single steady orbit.

Exit codes: 0 success, 2 usage error, 3 unsupported hardware, 4 session
failure.

## Two findings worth knowing

Both of these were found by running the thing, and both are worked around in
the code rather than left for the user.

**RealityKit writes USDZ and nothing else.** A `modelFile` request whose URL
ends in `.obj`, `.usda`, `.usd`, or which names a directory, is rejected with
`PhotogrammetrySession.Error.invalidOutput` before any processing starts.
Asking this tool for `.obj` therefore reconstructs to a sibling `.usdz` first
and converts it with Model I/O. Both files are kept.

**Model I/O's MTL sidecar makes Open3D read the OBJ as empty.** Model I/O
writes physically based material keys (`ao`, `subsurface`, `metallic`,
`roughness`, `sheen` and friends) plus a `map_Kd` pointing inside the USDZ
archive. Open3D reads OBJ through ASSIMP, whose MTL parser aborts on those
keys, warns, and then returns a mesh with zero points and zero triangles. The
OBJ geometry is perfectly fine; only the sidecar is at fault. This tool
rewrites the sidecar with standard `Ka`/`Kd`/`Ks`/`d`/`illum` keys and drops
the unreachable texture reference. Material names are preserved so the OBJ's
`usemtl` lines still resolve.

If you ever convert a USDZ to OBJ by some other route and scan2cad reports
that the file contains no triangles, suspect the MTL, not the OBJ.

## Smoke test

`smoke.sh` builds the tool, downloads Apple's 36 image sample set once, and
reconstructs it. It checks that the OBJ is non empty when read back through
Open3D, which is the reader scan2cad uses.

    ./smoke.sh

It needs about 280 MB of download on first run and roughly 20 seconds of
reconstruction after that. The download is cached under the scratch directory
the script prints.
