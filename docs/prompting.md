# Prompting the loop

gencad gives an agent hands (`freecad_run`) and eyes (`freecad_render_section`,
`render_iso.py`). What it cannot give it is your intent. Everything below is
about the half of generative CAD that lives on your side of the prompt: how to
state a part, how to bound what the agent may decide, how to report something
that looks wrong, and what to demand before a file goes to a slicer.

The framing owes a lot to Peter's ([@Peter05704721](https://x.com/Peter05704721))
write-up of designing a magnetic XIAO enclosure with an agent driving Fusion
360 over MCP, which is the same loop with a different kernel. The mechanics
below are gencad's.

## 1. Confirm the hands before the head

Start the session by asking for something you can check, not for a "connected".

> The gencad MCP server should be registered. List the tools you have, run a
> trivial `freecad_run` that prints the FreeCAD version and exits, and tell me
> the absolute path you'll write `.FCStd` files to. Say what's missing rather
> than working around it.

A version print through `freecadcmd` proves the whole chain — MCP transport,
`GENCAD_FREECADCMD`, the kernel — in one call. Agents that skip this spend the
next twenty minutes writing scripts against a server that never started, and
report progress the whole way.

## 2. Describe the use, not the object

"Make me an enclosure" leaves nearly everything undecided. The same board wants
a different shell depending on whether it sits on a desk, is held, or is worn.
State what goes inside, where it lives, what plugs into it, and what gets
pressed:

> Design an enclosure for a XIAO, a LiPo, and a power board. The power board's
> button must be operable from outside so I can switch it on and off while it's
> worn. USB-C has to stay reachable without opening the case.

"Operable from outside" gives the agent a reason to think about button travel
and how the press actuates the switch. "Leave a hole" does not.

Hand over whatever ground truth you already have — STEP files, mechanical
drawings, caliper measurements. If you have a mesh scan instead, that is what
[`scan2cad/`](../scan2cad/) is for: it turns the scan into a dimensioned report
and an editable build123d script with the uncertain numbers tagged as uncertain,
which is a far better prompt input than the mesh.

## 3. Say where the agent is free, and what "better" means

Most useful prompts name three things: what is fixed, what the agent may
choose, and how to break ties.

> Board outlines and connector positions are fixed — derive them from the STEP.
> You choose the battery, the internal layout, and the mounting method.
> Prioritise smallest overall volume, then tool-free disassembly. If going
> smaller would stop the USB plug seating or the button travelling, tell me the
> tradeoff before you take it.

That last clause is the one that pays. "As small as possible" has physical
limits, and an agent without permission to surface a conflict will quietly
resolve it by shaving the thing you cared about.

## 4. Report problems as observations, with a render

You do not need to know the cause. You need to say what you see, where, and
what you expected:

> In this section render at z = 6 mm, both connectors are buried in the PCB
> solid. I expect them sitting on its top face. Check their placement
> reference.

The pattern is **this is doing X, I expect Y, check this position or
dimension**. The render supplies the location; your words supply the
discrepancy. "The model is wrong" makes the agent guess whether you mean
appearance, dimensions, or assembly position, and it will usually guess wrong.

Two gencad-specific notes:

- **Sections beat isometrics for fit.** `freecad_render_section` fills material
  vs. void by containment parity, so a wall that reads as solid in a shaded view
  shows up as the 0.4 mm sliver it actually is. Use `render_iso.py` for "are the
  parts in the right places", sections for "is this dimension real".
- **Imported component origins are the classic trap.** A vendor STEP's origin is
  frequently not its mounting surface, so the part sinks into the board and
  every height derived from it is wrong by a constant. If several dimensions are
  off by the same amount, suspect a datum, not the arithmetic.

For a human look at the same file, export STEP and open it in
[chili3d](chili3d.md) — same OpenCascade kernel, so it is the identical B-rep,
with orbit, measure and section.

## 5. State manufacturing constraints in the first prompt

These change the geometry, so they belong up front, not in review:

> This will be FDM printed on a Bambu Lab X1C, 0.4 mm nozzle, PETG. Split it
> into a body and a lid that assemble without supports, leave clearance for the
> boards, plugs and button travel, and keep no wall or retaining feature below
> what that setup can print. Choose the clearances and wall thicknesses
> yourself, and ask if you're missing something essential.

Retrofitting printability onto a finished solid is a redesign. Stating it early
costs one sentence.

## 6. Make review checks describe use, not existence

"Check the model" gets you a list of files that exist. Ask instead for the
actions the part has to survive:

> Before I slice this: can the button both actuate and release the switch
> through its full travel? Can a USB-C plug insert fully, with its overmould?
> Do the battery wires have room to bend? Would any screw contact a component?
> For each answer, say whether it comes from the model or needs a physical test.

That last split is the important one. It stops "verified" from covering
conclusions the geometry cannot actually support — press-fits, magnet retention,
anything involving a real cable's stiffness.

## 7. Agree how a change will be checked before it is made

> Make the fix in a copy and keep the current `.FCStd`. Then: list what you
> changed, re-render sections through every feature the change touches, reopen
> the saved file and confirm the geometry is what the script intended, and
> finish with two lists — resolved, and still needs a physical fit test.

Re-rendering only the feature you edited is how a fix that breaks a neighbouring
wall ships. Reopening the saved file is how you catch a script that succeeded
against an in-memory document and wrote something else to disk.

## 8. Ask for the deliverables you actually want

Be explicit, because the defaults differ per format:

- **`.FCStd`** — keep editing in FreeCAD.
- **`.step`** — neutral solid for a colleague, a CAM shop, or chili3d.
- **per-part `.stl`** — slicing. One file per printed part, printed parts only:
  no PCBs, batteries, magnets or fasteners in the print exports.

If you want wall thickness, clearance and fit to update together, ask for it in
those words. A script that builds solids from literals looks parametric and is
not; you want the driving dimensions declared once at the top and every feature
derived from them.

## 9. The whole thing, as one starting prompt

```
gencad MCP should be live. First: list your tools, run a trivial freecad_run
that prints the FreeCAD version, and tell me where you'll write files.

Then design <part> to house <contents>, used <where/how>. Fixed: <outlines,
connector positions, mating hardware>. Yours to choose: <layout, fasteners,
non-critical dimensions>. Priorities, in order: <smallest / stiffest /
serviceable>.

Manufacturing: <process, machine, nozzle, material>. Split it for printing
without supports, and derive clearances and wall thicknesses from that setup.

Build it as a parametric script — driving dimensions declared once at the top.
After each build, section-render every feature you added and read the render
before moving on. Tell me the tradeoff before you sacrifice <the thing you
care about>.
```

Everything after that is the loop the rest of this repo exists to run: build,
render, look, fix. Your job is to say what would count as done.
