"""Planetary gearset: sun 12T + 3 planets 18T + internal ring 48T, module 2.

Involute profiles from first principles. Ring fixed, sun in, carrier out
=> 1 + z_r/z_s = 5:1 reduction. Sun bored for an N20 motor D-shaft.
"""
import math
import os
import FreeCAD as App
import Part
from FreeCAD import Vector

OUT = os.path.dirname(os.path.abspath(__file__))

M = 2.0                     # module (mm)
PA = math.radians(20.0)     # pressure angle
H = 8.0                     # face width
BL = 0.15                   # tangential backlash per mesh (mm)
ZS, ZP, ZR = 12, 18, 48     # sun / planet / ring teeth
A = M * (ZS + ZP) / 2.0     # center distance = 30

assert ZR == ZS + 2 * ZP, "planetary geometry"
assert (ZS + ZR) % 3 == 0, "equal-spacing assembly condition"


def involute(x):
    return math.tan(x) - x


def gear_face(z, addendum=1.0, dedendum=1.25, thin=0.0, steps=10):
    """Involute spur profile as a Face, one tooth centered at angle 0.

    thin > 0 shaves tooth flanks (backlash); < 0 thickens (for cutters).
    Below the base circle the flank falls back to a radial line.
    """
    r = M * z / 2.0
    rb = r * math.cos(PA)
    ra = r + addendum * M
    rf = r - dedendum * M

    def beta(rr):
        rr = max(rr, rb)
        phi = math.acos(rb / rr)
        return (math.pi / (2 * z) + involute(PA) - involute(phi)
                - thin / (2.0 * r))

    if rf < rb:
        radii = [rf] + [rb + (ra - rb) * i / steps for i in range(steps + 1)]
    else:
        radii = [rf + (ra - rf) * i / (steps + 1) for i in range(steps + 2)]

    pts = []
    for k in range(z):
        ang = 2 * math.pi * k / z
        for rr in radii:
            pts.append((rr, ang - beta(rr)))
        for rr in reversed(radii):
            pts.append((rr, ang + beta(rr)))
        pts.append((rf, ang + math.pi / z))         # root arc midpoint
    vs = [Vector(rr * math.cos(t), rr * math.sin(t), 0) for rr, t in pts]
    vs.append(vs[0])
    return Part.Face(Part.makePolygon(vs))


# --- sun: 12T with N20 D-shaft bore (3mm shaft, 2.5mm across flat) ------
sun = gear_face(ZS, thin=BL).extrude(Vector(0, 0, H))
bore = Part.makeCylinder(1.60, H)                   # 0.1 dia clearance
flat = Part.makeBox(3.4, 3.4, H, Vector(1.05, -1.7, 0))
sun = sun.cut(bore.cut(flat))

# --- planets: 18T, plain 3.2 bore for M3 pins ---------------------------
PSI = [90.0, 210.0, 330.0]   # positions where 0-phase planets mesh exactly
planets = []
for psi in PSI:
    p = gear_face(ZP, thin=BL).extrude(Vector(0, 0, H))
    p = p.cut(Part.makeCylinder(1.6, H))
    rad = math.radians(psi)
    p.translate(Vector(A * math.cos(rad), A * math.sin(rad), 0))
    planets.append(p)

# --- ring: disk minus a thickened 48T cutter, internal teeth ------------
cutter = gear_face(ZR, addendum=1.25, dedendum=1.0, thin=-BL)
cutter = cutter.extrude(Vector(0, 0, H))
ring = Part.makeCylinder(60.0, H).cut(cutter)
for i in range(6):
    a = math.radians(60 * i + 30)
    ring = ring.cut(Part.makeCylinder(
        1.7, H, Vector(55 * math.cos(a), 55 * math.sin(a), 0)))
ring.rotate(Vector(0, 0, 0), Vector(0, 0, 1), 180.0 / ZR)  # half-pitch phase

# --- verify: validity + zero interference at every mesh -----------------
solids = [("Sun", sun), ("Ring", ring)] + [
    ("Planet%d" % (i + 1), p) for i, p in enumerate(planets)]
for name, s in solids:
    assert s.isValid(), name + " invalid"
worst = 0.0
for i, p in enumerate(planets):
    for other, s in (("sun", sun), ("ring", ring)):
        v = p.common(s).Volume
        worst = max(worst, v)
        print("mesh planet%d-%s interference: %.6f mm^3" % (i + 1, other, v))
assert worst < 1e-6, "gears interfere"

doc = App.newDocument("planetary")
for name, s in solids:
    o = doc.addObject("Part::Feature", name)
    o.Shape = s
train = doc.addObject("Part::Feature", "Train")
train.Shape = sun.fuse([ring] + planets)
doc.recompute()
doc.saveAs(os.path.join(OUT, "planetary.FCStd"))
Part.export([train], os.path.join(OUT, "planetary.step"))

print("ratio sun->carrier (ring fixed): %.1f:1" % (1 + ZR / ZS))
print("OK planetary saved")
