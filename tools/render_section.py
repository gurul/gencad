"""Section renderer — runs inside freecadcmd, driven by GENCAD_SECTION_ARGS.

Slices an object in a .FCStd document with a plane and renders the section to
PNG. `filled` mode paints material vs. void using containment parity, so holes,
slots and debossed text read exactly as they will on the physical part.

Args (JSON file pointed to by $GENCAD_SECTION_ARGS):
  fcstd_path, object_name, axis ("x"|"y"|"z"), offset, out_png,
  filled (default true), window ([min_u, max_u, min_v, max_v], optional)
"""
import json
import os

import FreeCAD as App
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path

args = json.load(open(os.environ["GENCAD_SECTION_ARGS"]))

AXES = {"x": (App.Vector(1, 0, 0), lambda p: (p.y, p.z)),
        "y": (App.Vector(0, 1, 0), lambda p: (p.x, p.z)),
        "z": (App.Vector(0, 0, 1), lambda p: (p.x, p.y))}
normal, project = AXES[args["axis"]]

doc = App.openDocument(args["fcstd_path"])
obj = doc.getObject(args["object_name"])
if obj is None:
    raise SystemExit("no object named %r in %s"
                     % (args["object_name"], args["fcstd_path"]))

wires = obj.Shape.slice(normal, float(args["offset"]))
polys = []
for w in wires:
    n = max(40, min(4000, int(w.Length / 0.15)))
    pts = [project(p) for p in w.discretize(n)]
    polys.append(pts)

fig, ax = plt.subplots(figsize=(11, 11))
if args.get("filled", True):
    paths = [Path(pts) for pts in polys]
    areas = []
    for pts in polys:
        a = 0.0
        for i in range(len(pts) - 1):
            a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
        areas.append(abs(a) / 2)
    for idx in sorted(range(len(polys)), key=lambda i: -areas[i]):
        pts = polys[idx]
        depth = sum(1 for j in range(len(polys))
                    if j != idx and areas[j] > areas[idx]
                    and paths[j].contains_point(pts[0]))
        color = "#e8e4dd" if depth % 2 == 0 else "#2b2b2b"
        ax.fill([p[0] for p in pts], [p[1] for p in pts], color=color,
                zorder=depth, edgecolor="#9a958c", linewidth=0.4)
else:
    for pts in polys:
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "k-", lw=1)

ax.set_aspect("equal")
if args.get("window"):
    u0, u1, v0, v1 = args["window"]
    ax.set_xlim(u0, u1)
    ax.set_ylim(v0, v1)
ax.set_title("%s @ %s=%g" % (args["object_name"], args["axis"],
                             args["offset"]), fontsize=10)
plt.savefig(args["out_png"], dpi=130, bbox_inches="tight", facecolor="white")
print("gencad: wrote", args["out_png"], "(%d wires)" % len(polys))
