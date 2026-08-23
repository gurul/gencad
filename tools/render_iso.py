"""Isometric shaded render — runs inside freecadcmd, driven by GENCAD_ISO_ARGS.

Tessellates named objects from a .FCStd and renders a lambert-shaded 3D view
to PNG. Enough to *see* the modeled part; not a raytracer.

Args (JSON file pointed to by $GENCAD_ISO_ARGS):
  fcstd_path, out_png,
  objects: [{name, color (hex), translate ([x,y,z], optional),
             alpha (optional)}],
  elev (default 18), azim (default -55), figsize (default 10),
  bg (default "#ffffff"), zoom (default 1.0)
"""
import json
import os

import FreeCAD as App
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

args = json.load(open(os.environ["GENCAD_ISO_ARGS"]))
doc = App.openDocument(args["fcstd_path"])

elev = args.get("elev", 18)
azim = args.get("azim", -55)
light = np.array([0.35, -0.55, 0.75])
light = light / np.linalg.norm(light)

fig = plt.figure(figsize=(args.get("figsize", 10),) * 2)
ax = fig.add_subplot(111, projection="3d")
ax.set_proj_type("ortho")

# view direction (ortho) for back-face culling — interior faces that point
# away from the camera are dropped, which removes most painter-sort bleed
el, az = np.radians(elev), np.radians(azim)
view = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az),
                 np.sin(el)])

# one collection for the whole scene so matplotlib's painter sort is global
all_pts, tris, cols = [], [], []
for spec in args["objects"]:
    obj = doc.getObject(spec["name"])
    if obj is None:
        raise SystemExit("no object named %r" % spec["name"])
    shape = obj.Shape.copy()
    t = spec.get("translate")
    if t:
        shape.translate(App.Vector(*t))
    verts, facets = shape.tessellate(0.12)
    v = np.array([[p.x, p.y, p.z] for p in verts])
    all_pts.append(v)
    base = np.array(matplotlib.colors.to_rgb(spec["color"]))
    for f in facets:
        tri = v[list(f)]
        n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n = n / ln
        if np.dot(n, view) <= 0.02:      # back-face cull
            continue
        shade = 0.35 + 0.65 * max(0.0, float(np.dot(n, light)))
        tris.append(tri)
        cols.append(np.clip(base * shade, 0, 1))
ax.add_collection3d(
    Poly3DCollection(tris, facecolors=cols, edgecolors="none"))

pts = np.vstack(all_pts)
c = (pts.min(0) + pts.max(0)) / 2
r = (pts.max(0) - pts.min(0)).max() / 2 / args.get("zoom", 1.0)
ax.set_xlim(c[0] - r, c[0] + r)
ax.set_ylim(c[1] - r, c[1] + r)
ax.set_zlim(c[2] - r, c[2] + r)
ax.set_box_aspect((1, 1, 1))
ax.view_init(elev=elev, azim=azim)
ax.set_axis_off()
fig.patch.set_facecolor(args.get("bg", "#ffffff"))

fig.savefig(args["out_png"], dpi=170, bbox_inches="tight",
            facecolor=fig.get_facecolor())
print("wrote %s" % args["out_png"])
