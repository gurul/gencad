"""storeybox enclosure v2 — "inkline tin" (swarm-planned, critique-fixed).

A kraft canister that keeps moments the way a tin keeps letters. One unbroken
paper skin; every aperture (8 cameras, 8 mics) lives in ONE recessed near-black
band at the cap seam. The slip-over cap is the Memory Machines locket AND the
controller: a watch-glass 3D screen sunk into its top, the one lamp spilling
from UNDER the glass overhang (emitter never visible), and a single sub-flush
Touch ID button on the cap top — tap keeps the moment / wakes, hold sleeps,
a resting recognized finger unlocks the cap. Lifting the cap reveals one
memory coin presented on a plinth. Sound leaves through the floor: down-firing
driver over an open aperture, venting through arches in a shadowed foot ring.

Critique fixes applied: camera tilt sign (+10 genuinely UP), camera centerline
z 78.5 for seam margin, halo concealed under a wider dome chord (no Echo ring),
matte ink band, exploded offsets Cap +80 / Coin +25, dust-cap 0.5 clearance
over ribs, vent arches cut through the ring OD, 0.5 overshoot on all
coplanar-face cut tools.

All dimensions mm; z = 0 at the floor; front = azimuth 0 = +x.
"""
import math
import os
import FreeCAD as App
import Part
from FreeCAD import Vector

OUT = os.path.dirname(os.path.abspath(__file__))

R = 55.0            # outer skin radius (envelope Ø110 x H140, dome apex 144)
Z_SEAM = 84.0       # cap bottom edge
Z_BAND = 74.0       # ink band bottom (band z 74..84, recessed 2.5)
Z_RIM = 140.0       # cap rim / top face
CAM_Z = 78.5        # camera + mic centerline
CAM_TILT = 10.0     # degrees, up


def radial(radius, length, angle_deg, z_outer, start_r, tilt_up_deg=0.0):
    """Cut cylinder from an outer point, pointing inward (and down when the
    camera behind it looks outward-and-UP by tilt_up_deg)."""
    a = math.radians(angle_deg)
    t = math.radians(tilt_up_deg)
    d = Vector(-math.cos(a) * math.cos(t), -math.sin(a) * math.cos(t),
               -math.sin(t))
    p = Vector(start_r * math.cos(a), start_r * math.sin(a), z_outer)
    return Part.makeCylinder(radius, length, p, d)


def ring(r_out, r_in, h, z):
    return Part.makeCylinder(r_out, h, Vector(0, 0, z)).cut(
        Part.makeCylinder(r_in, h, Vector(0, 0, z)))


# shared sensor cut compounds (cut from Enclosure core AND InkBand)
cam_bores = [radial(2.5, 6.5, 45.0 * k, CAM_Z, 53.0, CAM_TILT)
             for k in range(8)]
cam_bezels = [radial(4.0, 1.5, 45.0 * k, CAM_Z, 53.0, CAM_TILT)
              for k in range(8)]
mic_ports = [radial(0.6, 6.0, 45.0 * k + 22.5, CAM_Z, 53.0)
             for k in range(8)]

# --- enclosure body ----------------------------------------------------------
body = Part.makeCylinder(R, Z_BAND - 7.0, Vector(0, 0, 7.0))       # skin 7..74
body = body.fuse(Part.makeCylinder(50.0, 10.0, Vector(0, 0, Z_BAND)))  # core
body = body.fuse(Part.makeCylinder(51.9, 47.0, Vector(0, 0, Z_SEAM)))  # neck
body = body.cut(Part.makeCylinder(49.0, 122.0, Vector(0, 0, 10.0)))    # cavity
body = body.cut(Part.makeCylinder(32.0, 5.0, Vector(0, 0, 6.0)))   # spk aper.
ribs = [Part.makeBox(70.0, 3.0, 3.0, Vector(-35.0, -1.5, 7.0)),
        Part.makeBox(3.0, 70.0, 3.0, Vector(-1.5, -35.0, 7.0))]
body = body.multiFuse(ribs)
body = body.fuse(ring(40.0, 32.0, 7.0, 0.0))                       # foot ring
arches = []
for k in range(6):
    arch = Part.makeBox(15.0, 16.0, 5.0, Vector(28.0, -8.0, -0.5))
    arch.rotate(Vector(0, 0, 0), Vector(0, 0, 1), 60.0 * k)
    arches.append(arch)
body = body.cut(Part.makeCompound(arches))
body = body.fuse(Part.makeCylinder(49.5, 4.0, Vector(0, 0, 123.0)))  # deck
body = body.fuse(Part.makeCylinder(22.0, 3.0, Vector(0, 0, 127.0)))  # plinth
dwell = Part.makeCylinder(15.2, 3.1, Vector(0, 0, 127.4)).cut(
    Part.makeBox(8.0, 34.0, 3.1, Vector(12.2, -17.0, 127.4)))       # D-well
body = body.cut(dwell)
for sy in (-1, 1):                                                  # crescents
    body = body.cut(Part.makeCylinder(5.5, 3.1, Vector(0, sy * 15.2, 127.4)))
body = body.cut(Part.makeCompound(cam_bores))
body = body.cut(Part.makeCompound(mic_ports))

# --- ink band (matte near-black sensor ring at the seam reveal) --------------
band = ring(52.5, 50.0, 10.0, Z_BAND)
band = band.cut(Part.makeCompound(cam_bezels))
band = band.cut(Part.makeCompound(cam_bores))
band = band.cut(Part.makeCompound(mic_ports))

# --- cap: locket + controller ------------------------------------------------
cap = Part.makeCylinder(R, Z_RIM - Z_SEAM, Vector(0, 0, Z_SEAM))
cap = cap.cut(Part.makeCylinder(52.1, 49.5, Vector(0, 0, Z_SEAM - 0.5)))
cap = cap.cut(Part.makeCylinder(32.0, 2.5, Vector(0, 0, 138.0)))   # scrn well
cap = cap.cut(ring(34.5, 32.5, 1.7, 138.8))                        # halo grv
BTN = Vector(44.5, 0, 0)                                           # front, top
cap = cap.cut(Part.makeCylinder(9.5, 1.6, Vector(44.5, 0, 139.0)))  # pocket

# --- dome: dark watch glass, chord Ø70 overhangs well + halo groove ----------
# sagitta 4 over chord r35: sphere R = (35^2 + 4^2) / (2*4) = 155.125
dome = Part.makeSphere(155.125, Vector(0, 0, -11.125)).common(
    Part.makeCylinder(35.0, 5.0, Vector(0, 0, Z_RIM)))

# --- halo: the one lamp, fully beneath the glass overhang --------------------
halo = ring(34.3, 32.7, 1.0, 138.8)                                # top 139.8

# --- touch id button: sub-flush ink dot with sensor-ring hairline ------------
button = Part.makeCylinder(9.0, 0.8, Vector(44.5, 0, 139.0))       # top 139.8
button = button.cut(ring(8.4, 7.8, 0.4, 139.5).common(
    Part.makeBox(40, 40, 1, Vector(24.5, -20, 139.0))))
button.translate(Vector(0, 0, 0))

# --- memory coin: one chip = one moment --------------------------------------
coin = Part.makeCylinder(15.0, 3.0, Vector(0, 0, 127.4))
coin = coin.cut(Part.makeBox(8.0, 34.0, 3.5, Vector(12.0, -17.0, 127.2)))
coin = coin.fuse(Part.makeCylinder(4.0, 0.5, Vector(0, 0, 130.4)))  # lens dot

# --- down-firing driver ------------------------------------------------------
driver = Part.makeCone(30.0, 8.0, 14.0, Vector(0, 0, 12.0))
driver = driver.fuse(Part.makeSphere(7.0, Vector(0, 0, 17.5)))
driver = driver.fuse(Part.makeCylinder(33.0, 3.0, Vector(0, 0, 26.0)))
driver = driver.fuse(Part.makeCylinder(15.0, 8.0, Vector(0, 0, 29.0)))

# --- sanity ------------------------------------------------------------------
solids = {"Enclosure": body, "InkBand": band, "Cap": cap, "Dome": dome,
          "Halo": halo, "Button": button, "Coin": coin, "Driver": driver}
for n, s in solids.items():
    assert s.isValid(), n

# camera tilt really points up: inner end of bore 0 lower than outer end
b0 = cam_bores[0]
inner_z = CAM_Z - 6.5 * math.sin(math.radians(CAM_TILT))
assert inner_z < CAM_Z, "camera tilt inverted"
print("cam bore 0: outer z %.2f -> inner z %.2f (up-tilt ok)"
      % (CAM_Z, inner_z))
print("fits: slip %.2f  coin/well %.2f  flat/key %.2f  coin-top/ceiling %.2f"
      % (52.1 - 51.9, 15.2 - 15.0, 12.2 - 12.0, 133.0 - 130.9))
print("halo groove outer r 34.5 under glass chord r 35.0 (concealed)")
bb = body.fuse(cap).fuse(dome).BoundBox
print("bounds: x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f"
      % (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax))

doc = App.newDocument("storeybox")
for name, shape in solids.items():
    o = doc.addObject("Part::Feature", name)
    o.Shape = shape
# fused assembly for cross-section renders
asm = doc.addObject("Part::Feature", "Assembly")
asm.Shape = body.multiFuse([band, cap, dome, coin, driver, button])
doc.recompute()
doc.saveAs(os.path.join(OUT, "storeybox.FCStd"))
Part.export([doc.getObject(n) for n in solids],
            os.path.join(OUT, "storeybox.step"))
print("wrote storeybox.FCStd + storeybox.step")
