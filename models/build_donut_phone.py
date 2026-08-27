"""Donut phone: a torus-bodied rotary telephone.

Torus donut (R60/r25) on a round pedestal, rotary dial rising through the
donut hole (10 finger holes + hub), two saddle posts cradling a classic
handset across the top, and tangent-laid sprinkles on the glaze line.
"""
import math
import os
import FreeCAD as App
import Part
from FreeCAD import Vector

OUT = os.path.dirname(os.path.abspath(__file__))

R = 60.0        # torus major radius
r = 25.0        # torus minor radius
HOLE = R - r    # donut hole radius = 35

# --- body: donut on a pedestal ---------------------------------------------
donut = Part.makeTorus(R, r)
donut.translate(Vector(0, 0, r))

pedestal = Part.makeCylinder(70.0, 5.0)

# --- rotary dial in the donut hole ------------------------------------------
dial_base = Part.makeCylinder(33.0, 15.0, Vector(0, 0, 5))
dial_plate = Part.makeCylinder(30.0, 6.0, Vector(0, 0, 20))
for k in range(10):
    a = 2 * math.pi * k / 10
    hole = Part.makeCylinder(
        5.5, 10.0, Vector(20 * math.cos(a), 20 * math.sin(a), 19))
    dial_plate = dial_plate.cut(hole)
hub = Part.makeCylinder(8.0, 6.0, Vector(0, 0, 26))
finger_stop = Part.makeBox(4.0, 10.0, 8.0, Vector(24.0, -20.0, 26.0))

# --- cradle posts with saddle notches ---------------------------------------
posts = []
for sx in (-1, 1):
    post = Part.makeBox(12.0, 16.0, 26.0, Vector(sx * 48 - 6, -8, 38))
    notch = Part.makeCylinder(
        8.5, 20.0, Vector(sx * 48 - 10, 0, 64), Vector(1, 0, 0))
    posts.append(post.cut(notch))

# --- handset ----------------------------------------------------------------
handle = Part.makeCylinder(
    8.0, 110.0, Vector(-55, 0, 64), Vector(1, 0, 0))
caps = [Part.makeSphere(8.0, Vector(sx * 55, 0, 64)) for sx in (-1, 1)]
ears = [Part.makeCone(15.0, 10.0, 14.0, Vector(sx * 62, 0, 52))
        for sx in (-1, 1)]
handset = handle.multiFuse(caps + ears)

# --- sprinkles: capsules laid tangent on the upper glaze --------------------
def sprinkle(theta_deg, phi_deg, roll_deg):
    th, ph = math.radians(theta_deg), math.radians(phi_deg)
    d = R + (r - 0.8) * math.cos(ph)
    p = Vector(d * math.cos(th), d * math.sin(th),
               r + (r - 0.8) * math.sin(ph))
    t1 = Vector(-math.sin(th), math.cos(th), 0)                    # along ring
    t2 = Vector(-math.sin(ph) * math.cos(th),                      # along tube
                -math.sin(ph) * math.sin(th), math.cos(ph))
    rl = math.radians(roll_deg)
    axis = t1 * math.cos(rl) + t2 * math.sin(rl)
    body = Part.makeCylinder(1.6, 8.0, p - axis * 4.0, axis)
    return body.multiFuse([Part.makeSphere(1.6, p - axis * 4.0),
                           Part.makeSphere(1.6, p + axis * 4.0)])

SPRINKLES = [(35, 55, 20), (60, 70, -35), (82, 45, 60), (108, 62, 10),
             (130, 50, -50), (152, 72, 30), (208, 58, -20), (230, 46, 45),
             (252, 68, -60), (275, 52, 15), (300, 63, -40), (322, 48, 55),
             (345, 70, 0), (95, 78, 90)]
sprinkles = [sprinkle(*s) for s in SPRINKLES]

# --- assemble ----------------------------------------------------------------
body = donut.multiFuse(
    [pedestal, dial_base, dial_plate, hub, finger_stop] + posts + sprinkles)
phone = body.fuse(handset)

# sanity: one solid each, handset floats clear of the glaze
assert body.isValid() and handset.isValid() and phone.isValid()
ear_bottom = 52.0
glaze_top_at_ear = r + math.sqrt(r * r - (62.0 - R) ** 2)
print("clearance ear/glaze: %.1f mm" % (ear_bottom - glaze_top_at_ear))
bb = phone.BoundBox
print("bounds: x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f"
      % (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax))

doc = App.newDocument("donut_phone")
for name, shape in (("Body", body), ("Handset", handset), ("Phone", phone)):
    o = doc.addObject("Part::Feature", name)
    o.Shape = shape
doc.recompute()
doc.saveAs(os.path.join(OUT, "donut_phone.FCStd"))
Part.export([doc.getObject("Phone")], os.path.join(OUT, "donut_phone.step"))
print("wrote donut_phone.FCStd + donut_phone.step")
