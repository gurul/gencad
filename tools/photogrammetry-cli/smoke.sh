#!/bin/bash
#
# Acceptance smoke test for photogrammetry-cli.
#
# Builds the tool, checks that it prints usage, then reconstructs Apple's
# 36 image Rock36 sample set and verifies the resulting OBJ reads back through
# Open3D with a non-empty triangle count. Open3D is the reader scan2cad uses,
# so an OBJ that trimesh likes but Open3D does not is still a failure here.
#
# Assumes it is run from anywhere; it resolves its own directory. The sample
# set is downloaded once and cached in CACHE below.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
CACHE="${TMPDIR:-/tmp}/scan2cad-photogrammetry-smoke"
VENV_PYTHON="$REPO/.venv/bin/python"
SAMPLE_URL="https://docs-assets.developer.apple.com/published/8ca2a2cfae7e/CreatingAPhotogrammetryCommandLineApp.zip"
BINARY="$HERE/.build/release/photogrammetry-cli"

echo "Cache directory: $CACHE"
mkdir -p "$CACHE"

echo "Step 1. Build."
(cd "$HERE" && swift build -c release)
test -x "$BINARY" || { echo "FAIL: binary was not produced"; exit 1; }

echo "Step 2. Usage."
"$BINARY" --help | grep -q "photogrammetry-cli" || { echo "FAIL: usage text missing"; exit 1; }
echo "Usage prints."

echo "Step 3. Sample image set."
IMAGES="$CACHE/rock36"
if [ ! -d "$IMAGES" ]; then
    if [ ! -f "$CACHE/sample.zip" ]; then
        echo "Downloading Apple sample, about 280 MB, once only."
        curl -sSL -o "$CACHE/sample.zip" "$SAMPLE_URL"
    fi
    unzip -q -o "$CACHE/sample.zip" -d "$CACHE/apple"
    unzip -q -o "$CACHE/apple/Data/Rock36Images.zip" -d "$IMAGES"
fi
COUNT=$(find "$IMAGES" -type f -iname "*.HEIC" | wc -l | tr -d ' ')
echo "Sample images: $COUNT"
test "$COUNT" -gt 0 || { echo "FAIL: no sample images"; exit 1; }

echo "Step 4. Reconstruct at preview detail."
OUT="$CACHE/out"
rm -rf "$OUT"
"$BINARY" "$IMAGES" "$OUT/rock36.obj" --detail preview 2>/dev/null

test -f "$OUT/rock36.usdz" || { echo "FAIL: no usdz written"; exit 1; }
test -f "$OUT/rock36.obj" || { echo "FAIL: no obj written"; exit 1; }
echo "Wrote usdz and obj."

echo "Step 5. Read the OBJ back through Open3D."
if [ ! -x "$VENV_PYTHON" ]; then
    echo "SKIP: no venv at $VENV_PYTHON, cannot check the Open3D read."
    echo "PASS (build and reconstruction only)."
    exit 0
fi
"$VENV_PYTHON" - "$OUT/rock36.obj" <<'PY'
import sys
import open3d as o3d

path = sys.argv[1]
mesh = o3d.io.read_triangle_mesh(path)
triangles = len(mesh.triangles)
print("Open3D triangles: %d" % triangles)
if triangles < 1000:
    print("FAIL: Open3D read the OBJ as empty or near empty.")
    raise SystemExit(1)
print("Open3D read the mesh.")
PY

echo "PASS."
