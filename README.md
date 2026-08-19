# gencad

**Parametric CAD from a prompt** — headless FreeCAD wired to a coding agent
over MCP, plus the render tooling that lets the agent *see* what it modeled.

An LLM can write solid FreeCAD Python, but generative CAD only converges when
the loop is closed: build the solid, render it, look at the render, fix the
script, repeat. gencad packages that loop:

```
agent ──(MCP)──▶ gencad server ──▶ freecadcmd (FreeCAD headless)
  ▲                                        │
  └──── section render PNGs ◀──────────────┘
```

## What's here

- **`server/gencad_mcp.py`** — a zero-dependency MCP server (stdlib only,
  stdio transport) exposing two tools:
  - `freecad_run` — execute a parametric build script inside `freecadcmd`
  - `freecad_render_section` — slice any solid in a `.FCStd` with a plane and
    render a filled cross-section PNG (material vs. void by containment
    parity), so hole patterns, wall thicknesses and debossed text can be
    visually verified before anything is printed
- **`tools/render_section.py`** — the renderer itself; also usable standalone
  inside `freecadcmd`
- **`text-to-cad/`** — [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad)
  as a submodule, pinned to its `main` releases: a library of agent skills for
  CAD, CAE and CAM (CAD generation with STEP/STL/3MF export, a local CAD
  Viewer, DXF drawings, URDF/SRDF/SDF robot descriptions, G-code slicing,
  off-the-shelf STEP part sourcing, and more). It complements the MCP loop
  above: gencad closes the build/render/inspect cycle, text-to-cad supplies
  the surrounding fabrication and hand-off workflows. Install its skills into
  an agent with `npx skills add earthtojake/text-to-cad`, or point the skills
  CLI at the checked-out `text-to-cad/skills/` directory. Update the pin with
  `git submodule update --remote text-to-cad`.
- **`scan2cad/`** — the scan side of the loop: a screen-reader-native
  describe-and-draft CLI. A phone-scanned mesh goes in; out come a
  plain-language geometry report, an editable build123d script with named,
  uncertainty-tagged dimensions, and STEP reference surfaces. The scan is the
  draft, the caliper is the truth. Own venv (Python 3.12 only), own README,
  morning capture protocol in `scan2cad/docs/MORNING_PROTOCOL.md`, and a
  zero-dependency Mac PhotogrammetrySession CLI in
  `scan2cad/tools/photogrammetry-cli/`.

## Setup

1. Install [FreeCAD](https://www.freecad.org) (the app bundles Python with
   numpy + matplotlib — no pip installs needed).
2. Register the server with your agent. For Claude Code, add to `.mcp.json`:

```json
{
  "mcpServers": {
    "gencad": {
      "command": "python3",
      "args": ["/path/to/gencad/server/gencad_mcp.py"]
    }
  }
}
```

If `freecadcmd` isn't at the macOS default path, set `GENCAD_FREECADCMD`.

## Built with this loop: the claude-pet case

The enclosure for [claude-pet](https://github.com/gurul/claude-pet) — an
ESP32-S3 desk buddy around the Freenove display board — is parametric FreeCAD
Python authored and iterated exactly this way; the scripts live in that repo's
[`case/`](https://github.com/gurul/claude-pet/tree/main/case) directory.

![claude-pet shell render](https://raw.githubusercontent.com/gurul/claude-pet/main/docs/assets/shell-render.png)

Details the build/render/inspect loop carried: PCB-seating bosses biased
0.3 mm short of the derived board plane for preload, blind Ø4.0 × 6.8 mm bores
for M3 heat-set inserts, front-entry countersunk screws riding D-trimmed guide
standoffs through the PCB holes, a WS2812 glow window with BOOT/RESET
pokeholes — and a 1.2 mm "gauge" plate carrying just the board's hole grid, so
the footprint gets test-printed and verified against the physical PCB before
committing to full shells.

## License

MIT
