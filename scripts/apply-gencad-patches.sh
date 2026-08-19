#!/usr/bin/env bash
# (Re)apply gencad's local patches to the vendored text-to-cad tree.
# Idempotent — safe to run any number of times. With --revert, removes the
# patches and returns the tree to pristine upstream; pull-text-to-cad.sh
# wraps its upstream apply in revert/reapply so patches never conflict.
# Add future gencad patches to vendored files here, between markers.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

python3 - "$@" <<'PYEOF'
import re
import sys

revert = "--revert" in sys.argv[1:]

path = "text-to-cad/skills/cad-viewer/scripts/viewer/dist/index.html"
src = open(path).read()
# strip existing patch block: marker form, or the pre-marker legacy form
src = re.sub(r"[ \t]*<!-- gencad:patch-start -->.*?<!-- gencad:patch-end -->\n",
             "", src, flags=re.S)
src = re.sub(r"[ \t]*<!-- gencad patch:.*?</style>\n", "", src, flags=re.S)

block = """    <!-- gencad:patch-start -->
    <!-- gencad patch: hide upstream community links in the header; full credit
         to earthtojake/text-to-cad remains in the gencad README and LICENSE -->
    <style>
      a[href*="discord.gg"],
      a[href*="github.com/earthtojake"] {
        display: none !important;
      }
    </style>
    <!-- gencad:patch-end -->
"""
if not revert:
    m = re.search(r'^[ \t]*<script type="module"', src, flags=re.M)
    if not m:
        sys.exit("no module script tag in " + path)
    src = src[:m.start()] + block + src[m.start():]

open(path, "w").write(src)
print(("reverted" if revert else "applied") + " gencad patches: " + path)
PYEOF
