"""Aubade — a dawn-knocker.

A sunrise alarm that does two things for the 30 minutes before sunrise: an
edge-lit disc brightens from black to full, and a hammer inside the plinth
knocks on the table, slowly at first and then faster and faster.

FORM
  A translucent disc rises out of a wedge plinth. The plinth's front wall is
  the horizon line, so what shows above it is a sun cresting. The disc is
  buried 16 mm into the plinth and lit from BELOW, on its bottom edge, by two
  LED troughs — edge-lit, so there is no visible emitter anywhere, just a limb
  that blooms. The disc leans back 12 degrees, both because that is the angle a
  face on a pillow reads it at and because it makes the sun look like it is
  still rising.

MECHANISM
  One motor, one moving assembly. An N20 gearmotor turns a 3-lobe cam. The cam
  lifts a rocker arm; when the lobe passes, the arm falls and the hammer post
  on its long end drops through a port in the base plate and strikes the table.
  Tap rate = RPM x 3, so "faster and faster" is a PWM ramp on one motor and
  nothing else. The strike is gravity, not drive, so a stalled motor cannot
  hammer the table.

  Lever: pivot at y=+22, follower at y=+6, hammer at y=-10. A 3.0 mm cam rise
  under a 16 mm follower arm becomes 6.0 mm of lift at the 32 mm hammer arm.
  Overall 118 x 62 x 139 mm; the sun stands 79 mm above the horizon line.

  Oval windows in both side walls frame the cam so the movement is visible —
  symmetric, so it reads as designed rather than as a vent.

DIMENSIONS AND WHAT IS ACTUALLY KNOWN
  Everything in PART INTERFACES below is a nominal from a catalogue listing,
  NOT from calipers on the part in hand. gencad's contribution is the
  build/render/inspect loop, not the numbers — see the claude-pet precedent in
  the README, where every load-bearing dimension came from a human with a
  board, a datasheet and a caliper. Print the GAUGE plate first, check it
  against the real motor and the real board, then correct these and re-run.
  The shell dimensions are design choices and are not in question.
"""
import math
import os

import FreeCAD as App
import Part
from FreeCAD import Vector

OUT = os.path.dirname(os.path.abspath(__file__))

# --- print / fit constants --------------------------------------------------
WALL = 2.4          # 6 perimeters at 0.4 mm — opaque enough for the horizon
CLR = 0.4           # sliding clearance, FDM
BORE_CLR = 0.15     # press/pin clearance

# --- PART INTERFACES — verify with calipers before printing shells ----------
MOTOR_L = 24.0      # N20 gearmotor: can + gearbox along the shaft axis
MOTOR_W = 12.0
MOTOR_H = 10.0
SHAFT_D = 3.0       # Ø3 output shaft, D-flat
BOARD_L = 22.5      # ESP32-C3 SuperMini
BOARD_W = 18.0
USB_W = 9.5         # USB-C receptacle opening
USB_H = 3.6

# --- the sun ----------------------------------------------------------------
DISC_R = 48.0
DISC_T = 6.0        # translucent, printed in 3 walls / 15% gyroid
TILT = 12.0         # degrees leaning back (+Y is back, -Y is front)
BURIED = 16.0       # how deep the disc sits below the horizon line

# --- the plinth -------------------------------------------------------------
PW = 118.0          # width
PD = 62.0           # depth
# 60, not the 52 this started at. The internal stack is floor + cam + rocker
# swing + LED trough + buried disc, and at 52 the cam grazed the base plate
# with 0.00 mm to spare while the lifted arm came within 1 mm of the troughs.
# Eight more millimetres buys clearance everywhere and costs nothing visually.
PH = 60.0           # height = the horizon line
CORNER = 10.0
FLOOR = 3.0         # base plate thickness

DISC_BOT = PH - BURIED              # 44.0
DISC_CZ = DISC_BOT + DISC_R         # 92.0 — disc centre before tilt

# --- the movement -----------------------------------------------------------
CAM_Y, CAM_Z = 6.0, 16.0            # motor axis / cam centre
CAM_BASE_R = 8.0
CAM_RISE = 3.0
CAM_LOBES = 3
CAM_W = 10.0
# Lobes sit at 30/150/270 degrees, so a VALLEY points straight up. Without the
# phase they sat at 0/120/240 and the flank of the 120 lobe stood 1.53 mm
# proud of the base circle directly under the follower — the modelled "rest"
# position was one the cam could not actually reach, which the interference
# check caught as 141 mm^3 of rocker inside cam.
CAM_PHASE = math.pi / 6
PIVOT_Y = 22.0
PIN_D = 3.0
ARM_W = 12.0                        # across X
ARM_T = 4.0                         # arm bar thickness
HAMMER_Y = -10.0
HAMMER_D = 8.0
FOOT_H = 3.0                        # silicone bumpers
FOOT_SINK = 1.5                     # recessed into the base plate
TABLE_Z = -(FOOT_H - FOOT_SINK)     # -1.5 — the table, in part coordinates

CAM_TOP_R = CAM_BASE_R + CAM_RISE   # 11.0
FOLLOWER_ARM = PIVOT_Y - CAM_Y      # 16.0
HAMMER_ARM = PIVOT_Y - HAMMER_Y     # 32.0
HAMMER_LIFT = CAM_RISE * HAMMER_ARM / FOLLOWER_ARM   # 6.0
PAD_R = 3.0
# Where the follower pad touches the cam at rest: the top of the base circle.
CONTACT_Z = CAM_Z + CAM_BASE_R      # 24.0
# The BAR sits 1.5 mm above that, so only the pad ever touches the cam.
#
# This gap is not cosmetic. A lobe is a circle of radius 5.5 whose centre is
# 5.5 out from the axis, so its crown reaches CAM_Z + 5.5*sin(30) + 5.5 =
# 24.25 — a quarter of a millimetre ABOVE the base-circle top, and nowhere
# near the lobe's own radial tip. With the bar's flat underside at 24.0 it
# fouled that crown on every revolution: 10.98 mm^3, at rest, in a mechanism
# that had otherwise passed. The pad's round nose clears it by 4.0 mm.
ARM_BOT = CONTACT_Z + 1.5           # 25.5
# DERIVED, not chosen. Setting this by hand is what put the pin bore at z=30
# while the arm occupied 22..26 — the bore missed the arm entirely, so the
# rocker had no pivot hole and the plinth's posts held nothing. The pin passes
# through the bar, so it is the middle of the bar, by construction.
PIVOT_Z = ARM_BOT + ARM_T / 2       # 26.0
# Angle the arm swings when a lobe arrives under the follower. Negative about
# +X because the follower is on the -Y side of the pivot and has to rise.
LIFT_DEG = -math.degrees(math.atan2(CAM_RISE, FOLLOWER_ARM))


def rrect(w, d, h, r, cx, cy, z):
    """Rounded-rectangle prism, centred on (cx, cy), rising from z.

    Built from four corner cylinders and two crossing boxes rather than
    makeFillet: fillets on a shape this compound fail silently on some edge
    sets, and a build that half-succeeds is worse than one that never used
    them. This construction is always valid.
    """
    parts = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(Part.makeCylinder(
                r, h, Vector(cx + sx * (w / 2 - r), cy + sy * (d / 2 - r), z)))
    parts.append(Part.makeBox(w - 2 * r, d, h,
                              Vector(cx - (w / 2 - r), cy - d / 2, z)))
    parts.append(Part.makeBox(w, d - 2 * r, h,
                              Vector(cx - w / 2, cy - (d / 2 - r), z)))
    return parts[0].multiFuse(parts[1:])


def oval(w, h, depth, cx, cz, y):
    """Stadium-shaped prism lying along Y — the movement window cutter."""
    r = h / 2
    body = Part.makeBox(w - h, h, depth, Vector(cx - (w - h) / 2, y, cz - r))
    caps = [Part.makeCylinder(r, depth, Vector(cx + sx * (w - h) / 2, y, cz),
                              Vector(0, 1, 0)) for sx in (-1, 1)]
    return body.multiFuse(caps)


def lean(shape):
    """Tilt a shape back about the horizon line, as the disc is mounted."""
    s = shape.copy()
    s.rotate(Vector(0, 0, PH), Vector(1, 0, 0), -TILT)
    return s


# ============================================================================
# 1. The sun disc, and the slot that holds it
# ============================================================================
# Built lying along Y (the disc faces front and back), then leaned back. The
# slot is cut with an OVERSIZED COPY of the disc itself rather than with a
# straight pocket — the disc's buried edge is a circular arc through a tilted
# plane, and cutting with the mating solid is the only way to get that shape
# right without deriving it.
disc = Part.makeCylinder(DISC_R, DISC_T, Vector(0, -DISC_T / 2, DISC_CZ),
                         Vector(0, 1, 0))
disc = lean(disc)

slot = Part.makeCylinder(DISC_R + CLR, DISC_T + 2 * CLR,
                         Vector(0, -DISC_T / 2 - CLR, DISC_CZ), Vector(0, 1, 0))
slot = lean(slot)

# The grip boss: material around the buried arc so the slot is 16 mm deep
# instead of 2.4. Sits above the LED troughs so it never shadows the edge.
# Depth 36 centred at y=6, not 30 at y=8. The disc is leaning, so its buried
# arc rakes forward as it descends — at the bottom of the slot it sits near
# y=-6, which a 30 deep boss centred at 8 only just reached.
boss = rrect(74.0, 36.0, BURIED, 6.0, 0.0, 6.0, DISC_BOT)


# ============================================================================
# 2. The plinth
# ============================================================================
shell = rrect(PW, PD, PH, CORNER, 0.0, 0.0, 0.0)
cavity = rrect(PW - 2 * WALL, PD - 2 * WALL, PH - WALL - FLOOR,
               CORNER - WALL, 0.0, 0.0, FLOOR)
plinth = shell.cut(cavity).fuse(boss)

# Movement windows — one per side wall, framing the cam.
#
# Depth 8, not 40. A 40 mm cutter reaches x=+/-19 from each wall, and the motor
# cradle lives at x=-37..-7 — the left window sliced the cradle open. The
# cutter only has to pierce a 2.4 mm wall; anything past that is cutting air at
# best and structure at worst.
for sx in (-1, 1):
    win = oval(34.0, 17.0, 8.0, 0.0, 22.0, -4.0)
    win.rotate(Vector(0, 0, 0), Vector(0, 0, 1), 90)
    win.translate(Vector(sx * (PW / 2 - 2.0), 0, 0))
    plinth = plinth.cut(win)

# Hammer port. Ø16 for an Ø8 post: the post swings on a 32 mm arm, so 6 mm of
# vertical travel is only 0.56 mm of horizontal wander — the clearance is for
# assembly and for a silicone boot, not for the arc.
plinth = plinth.cut(Part.makeCylinder(8.0, FLOOR + 4, Vector(0, HAMMER_Y, -1)))

# USB-C, rear wall, behind the board.
plinth = plinth.cut(Part.makeBox(USB_W, 3 * WALL, USB_H,
                                 Vector(31.0 - USB_W / 2, PD / 2 - WALL * 1.5, 7.0)))

# Two LED troughs firing UP at the disc's buried edge. Split left/right with a
# gap at the centre because the rocker arm swings through x = -6..+6 — one
# continuous strip across the middle would be struck by the arm every tap.
TROUGH_Z = 35.0
TROUGH_BOX = (27.0, 12.0, 5.0)      # outer
TROUGH_POCKET = (23.0, 8.0, 5.0)    # inner — 2 mm walls, fits an 8 mm strip
for sx in (-1, 1):
    w, d, h = TROUGH_BOX
    plinth = plinth.fuse(Part.makeBox(
        w, d, h, Vector(sx * 9.0 - (0 if sx > 0 else w), 1.0, TROUGH_Z)))
    pw, pd, ph = TROUGH_POCKET
    plinth = plinth.cut(Part.makeBox(
        pw, pd, ph, Vector(sx * 11.0 - (0 if sx > 0 else pw), 3.0, TROUGH_Z + 1.0)))

# Motor cradle: a pocket the can drops into, open-topped so it is captured by
# the lid strap rather than needing to slide in axially past the cam.
cradle = rrect(MOTOR_L + 6.0, MOTOR_W + 2 * WALL, MOTOR_H / 2 + WALL, 3.0,
               -22.0, CAM_Y, CAM_Z - MOTOR_H / 2 - WALL)
plinth = plinth.fuse(cradle)
# Height 10, NOT MOTOR_H + 20. The +20 was meant to leave the pocket open at
# the top for drop-in assembly, but it started at z=11 and therefore reached
# z=41 — straight up through the LEFT LED trough at 35..40, taking its floor
# out. The right trough was untouched, because the motor is on the left. Every
# printed clearance still read fine; the y=6 section render is what showed it.
# The pocket only ever has to span the cradle, whose walls stop at z=16.
plinth = plinth.cut(Part.makeBox(MOTOR_L + CLR, MOTOR_W + CLR, 10.0,
                                 Vector(-22.0 - (MOTOR_L + CLR) / 2,
                                        CAM_Y - (MOTOR_W + CLR) / 2,
                                        CAM_Z - MOTOR_H / 2)))

# Pivot posts for the rocker pin — one each side of the arm.
for sx in (-1, 1):
    post = Part.makeCylinder(4.5, PIVOT_Z - FLOOR + 4.5,
                             Vector(sx * (ARM_W / 2 + CLR + 4.5), PIVOT_Y, FLOOR))
    plinth = plinth.fuse(post)
    plinth = plinth.cut(Part.makeCylinder(
        (PIN_D + BORE_CLR) / 2, 12.0,
        Vector(sx * (ARM_W / 2 + CLR) - sx * 1.0, PIVOT_Y, PIVOT_Z),
        Vector(sx, 0, 0)))

# Board bosses — M2 self-tap, right half, low, clear of the windows.
# Centred at y=17 with a 2.5 mm boss, not y=19 with a 3.0: at the original
# numbers the rear pair reached y=33.25 and stood 2.25 mm proud of the back
# wall, which the bounding-box print caught as y max 33.2 on a 62 deep plinth.
BOARD_CY = 17.0
for dx, dy in ((-BOARD_W / 2, -BOARD_L / 2), (BOARD_W / 2, -BOARD_L / 2),
               (-BOARD_W / 2, BOARD_L / 2), (BOARD_W / 2, BOARD_L / 2)):
    c = Vector(31.0 + dx, BOARD_CY + dy, FLOOR)
    plinth = plinth.fuse(Part.makeCylinder(2.5, 4.0, c))
    plinth = plinth.cut(Part.makeCylinder(0.8, 5.0, c))

# Feet. A tripod centred as near the hammer as the footprint allows, so the
# strike reaction pushes straight down through the support polygon instead of
# rocking the plinth off a corner.
for fx, fy in ((-46.0, -20.0), (46.0, -20.0), (0.0, 22.0)):
    plinth = plinth.cut(Part.makeCylinder(5.0, FOOT_SINK, Vector(fx, fy, 0)))

plinth = plinth.cut(slot)


# ============================================================================
# 3. The cam — 3 lobes, base R8, rise 3.0
# ============================================================================
# Lobes are offset circles fused to the base circle, not a spline: a circle of
# radius (base + rise) / 2 whose centre sits (base + rise) / 2 out from the
# axis is tangent-continuous with the base circle at its flanks, so the
# follower is never asked to climb a step.
cam = Part.makeCylinder(CAM_BASE_R, CAM_W,
                        Vector(-CAM_W / 2, CAM_Y, CAM_Z), Vector(1, 0, 0))
lobe_r = (CAM_BASE_R + CAM_RISE) / 2
for k in range(CAM_LOBES):
    a = 2 * math.pi * k / CAM_LOBES + CAM_PHASE
    cam = cam.fuse(Part.makeCylinder(
        lobe_r, CAM_W,
        Vector(-CAM_W / 2, CAM_Y + lobe_r * math.cos(a),
               CAM_Z + lobe_r * math.sin(a)), Vector(1, 0, 0)))
cam = cam.cut(Part.makeCylinder((SHAFT_D + BORE_CLR) / 2, CAM_W + 2,
                                Vector(-CAM_W / 2 - 1, CAM_Y, CAM_Z),
                                Vector(1, 0, 0)))
# D-flat, so the cam cannot creep round the shaft under load.
cam = cam.cut(Part.makeBox(CAM_W + 2, 2.0, SHAFT_D,
                           Vector(-CAM_W / 2 - 1, CAM_Y + SHAFT_D / 2 - 0.85,
                                  CAM_Z - SHAFT_D / 2)))


# ============================================================================
# 4. The rocker — follower, pivot, hammer
# ============================================================================
# Modelled at REST, i.e. follower down on the cam's base circle, hammer tip on
# the table. That is the position that has to be checked, because it is the one
# where the tip either reaches the table or does not.
arm = Part.makeBox(ARM_W, PIVOT_Y - HAMMER_Y + 8.0, ARM_T,
                   Vector(-ARM_W / 2, HAMMER_Y - 4.0, ARM_BOT))
# Follower pad: a rounded nose so the contact patch rolls along the lobe flank
# rather than digging a corner into it.
pad = Part.makeCylinder(PAD_R, ARM_W,
                        Vector(-ARM_W / 2, CAM_Y, CONTACT_Z + PAD_R),
                        Vector(1, 0, 0))
arm = arm.fuse(pad)
# Hammer post + dome tip. The tip bottoms out exactly on the table plane.
post = Part.makeCylinder(HAMMER_D / 2, ARM_BOT - TABLE_Z - HAMMER_D / 2,
                         Vector(0, HAMMER_Y, TABLE_Z + HAMMER_D / 2))
tip = Part.makeSphere(HAMMER_D / 2, Vector(0, HAMMER_Y, TABLE_Z + HAMMER_D / 2))
rocker = arm.multiFuse([post, tip])
rocker = rocker.cut(Part.makeCylinder(
    (PIN_D + BORE_CLR) / 2, ARM_W + 2,
    Vector(-ARM_W / 2 - 1, PIVOT_Y, PIVOT_Z), Vector(1, 0, 0)))
# Return-spring post: gravity alone is a soft knock, a light extension spring
# from here to the base plate makes it a crisp one.
rocker = rocker.fuse(Part.makeCylinder(
    1.5, 4.0, Vector(0, HAMMER_Y + 6.0, ARM_BOT + ARM_T)))


# ============================================================================
# 5. Checks — the things that are actually load-bearing
# ============================================================================
for name, s in (("Plinth", plinth), ("Disc", disc), ("Cam", cam),
                ("Rocker", rocker)):
    assert s.isValid(), "%s is not a valid solid" % name
    assert s.Volume > 0, "%s has no volume" % name

bb = plinth.BoundBox
print("plinth bounds  x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f"
      % (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax))
db = disc.BoundBox
print("disc bounds    x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f"
      % (db.XMin, db.XMax, db.YMin, db.YMax, db.ZMin, db.ZMax))
print("overall height %.1f mm   sun above horizon %.1f mm"
      % (db.ZMax, db.ZMax - PH))

# The cam must clear the base plate it spins above.
print("cam lobe / base-plate gap   %.2f mm"
      % ((CAM_Z - CAM_TOP_R) - FLOOR))
# The crown of a lobe, which is NOT the lobe's radial tip — see ARM_BOT.
_lobe_c = (CAM_BASE_R + CAM_RISE) / 2
_cam_top = max([CAM_Z + CAM_BASE_R] + [
    CAM_Z + _lobe_c * math.sin(2 * math.pi * k / CAM_LOBES + CAM_PHASE) + _lobe_c
    for k in range(CAM_LOBES)])
print("cam crown %.2f / arm bar %.2f -> %.2f mm" % (_cam_top, ARM_BOT, ARM_BOT - _cam_top))
# The hammer must reach the table at rest, and lift clear of it on a lobe.
print("hammer tip at rest z        %.2f mm (table at %.2f)"
      % (rocker.BoundBox.ZMin, TABLE_Z))
print("hammer lift on lobe         %.2f mm" % HAMMER_LIFT)
# The arm swings through the middle of the plinth; the LED troughs must not.
print("arm top / LED trough gap    %.2f mm"
      % (TROUGH_Z - (ARM_BOT + ARM_T + CAM_RISE)))
# The disc's buried edge must sit above the troughs to be lit, not shadowed.
print("disc edge / LED top gap     %.2f mm" % (DISC_BOT - (TROUGH_Z + 4.0)))
# The two LED troughs are mirror images, so any difference between them is
# something else having eaten one of them. This is the check that would have
# caught the motor pocket immediately instead of a section render catching it.
_tv = []
for sx in (-1, 1):
    w, d, h = TROUGH_BOX
    probe = Part.makeBox(w, d, h, Vector(sx * 9.0 - (0 if sx > 0 else w),
                                         1.0, TROUGH_Z))
    _tv.append(plinth.common(probe).Volume)
print("LED trough volume L/R       %.1f / %.1f mm^3  (delta %.1f)"
      % (_tv[0], _tv[1], abs(_tv[0] - _tv[1])))
assert abs(_tv[0] - _tv[1]) < 1.0, "LED troughs are not mirror images"
# The pin has to actually pass through the bar it pivots.
print("pivot bore inside arm       %s"
      % ("yes" if ARM_BOT < PIVOT_Z < ARM_BOT + ARM_T else "NO"))
# Interference, at BOTH ends of the swing. Checking rest only is how a
# mechanism passes CAD and jams on the bench: rest is the position the arm is
# drawn in, and every collision it has is somewhere else.
lifted = rocker.copy()
lifted.rotate(Vector(0, PIVOT_Y, PIVOT_Z), Vector(1, 0, 0), LIFT_DEG)
print("arm swing %.2f deg   hammer tip lifted to z %.2f"
      % (abs(LIFT_DEG), lifted.BoundBox.ZMin))
for pos, r in (("rest", rocker), ("lift", lifted)):
    for other_name, other in (("plinth", plinth), ("cam", cam), ("disc", disc)):
        v = r.common(other).Volume
        flag = "  <-- COLLIDES" if v > 0.001 else ""
        print("interference %s rocker/%-6s  %8.3f mm^3%s"
              % (pos, other_name, v, flag))

# Tap rate the ramp has to cover, from the lobe count.
for rpm in (10, 40, 120):
    print("motor %3d rpm -> %.1f taps/s" % (rpm, rpm * CAM_LOBES / 60.0))


# ============================================================================
# 6. Gauge plate — print this FIRST
# ============================================================================
# 1.2 mm of plastic carrying only the interfaces that are guesses: the motor
# pocket, the shaft bore, the board hole grid and the USB window. Costs ten
# minutes and catches every wrong number above before a 9-hour shell print.
gauge = Part.makeBox(78.0, 46.0, 1.2, Vector(-39.0, -23.0, 0))
gauge = gauge.cut(Part.makeBox(MOTOR_L + CLR, MOTOR_W + CLR, 4.0,
                               Vector(-30.0, -8.0, -1)))
gauge = gauge.cut(Part.makeCylinder((SHAFT_D + BORE_CLR) / 2, 4.0,
                                    Vector(-2.0, -2.0, -1)))
gauge = gauge.cut(Part.makeBox(USB_W, USB_H, 4.0, Vector(8.0, 12.0, -1)))
for dx, dy in ((-BOARD_W / 2, -BOARD_L / 2), (BOARD_W / 2, -BOARD_L / 2),
               (-BOARD_W / 2, BOARD_L / 2), (BOARD_W / 2, BOARD_L / 2)):
    gauge = gauge.cut(Part.makeCylinder(1.0, 4.0, Vector(22.0 + dx, dy, -1)))


# ============================================================================
# 7. Write
# ============================================================================
# One compound carrying every part in its assembled position. Exists so the
# section renderer can cut the whole machine at once — sectioning the plinth
# alone shows a nice hollow box and tells you nothing about whether the cam,
# the arm and the hammer actually fit inside it.
assembly = Part.makeCompound([plinth, disc, cam, rocker])

doc = App.newDocument("aubade")
for name, shape in (("Plinth", plinth), ("Disc", disc), ("Cam", cam),
                    ("Rocker", rocker), ("Gauge", gauge),
                    ("Assembly", assembly)):
    o = doc.addObject("Part::Feature", name)
    o.Shape = shape
doc.recompute()
doc.saveAs(os.path.join(OUT, "aubade.FCStd"))
Part.export([doc.getObject(n) for n in ("Plinth", "Disc", "Cam", "Rocker")],
            os.path.join(OUT, "aubade.step"))
Part.export([doc.getObject("Gauge")], os.path.join(OUT, "aubade_gauge.step"))
print("wrote aubade.FCStd + aubade.step + aubade_gauge.step")
