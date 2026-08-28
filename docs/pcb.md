# pcb / Zener (external toolchain)

`pcb` is [diodeinc/pcb](https://github.com/diodeinc/pcb) (MIT), a command-line
tool by [Diode Computers](https://diode.computer) for circuit-board projects
written in **Zener** — a Starlark-based language for describing PCB
schematics. pcb builds those designs, manages dependencies, and generates
KiCad layout files. Credit to the Diode team; see the repo for docs and the
language reference.

## What it provides

- **Schematics as code.** A board is a `.zen` file: modules, nets, components
  and the `Board()` declaration are all Starlark, so an agent can author,
  diff and review a schematic the same way it authors a FreeCAD build script.
- **A headless build step.** `pcb build` validates a design with no GUI and
  no KiCad install — the electrical analogue of running a gencad script
  through `freecadcmd`.
- **KiCad output.** `pcb layout` generates KiCad layout files (KiCad 10.x
  required only for this step, not for building/validating Zener).
- **Dependency management.** `@stdlib` generics (resistors, LEDs, …),
  board vs. registry repository shapes, vendoring, and `pcb sync`.
- **Managed toolchains.** The `pcb` launcher downloads and runs the `pcbc`
  toolchain each project requests via `pcb-version` — install with
  `pcb toolchain install latest`, inspect with `pcb toolchain show`.
- **KiCad import.** `pcb import` converts an existing KiCad schematic or
  project into Zener.

## Why it sits here

gencad's loop is mechanical: an agent writes a parametric build script,
renders it, inspects the render, iterates. pcb is the same discipline on the
electrical side — schematic-as-code that an agent can write and validate
headlessly, with a real EDA artifact (a KiCad layout) at the end.

The [claude-pet case](../README.md#built-with-this-loop-the-claude-pet-case)
is where the two sides meet: its enclosure geometry (seating bosses, guide
standoffs, the hole-grid gauge plate) is all derived from the PCB. With the
board itself authored in Zener, both halves of that fit are scripts — the
board's hole grid and outline come from the same kind of source of truth the
enclosure does.

## Toolchain, not submodule

chili3d and geofield-bracket are pinned as submodules because gencad consumes
their *source*. pcb is consumed as an installed CLI, like FreeCAD and KiCad:
its launcher manages versioned toolchains itself, and each project pins the
toolchain it wants via `pcb-version` in its `pcb.toml`. There is nothing
useful to pin in this tree.

## Install

macOS, Linux, or WSL2:

```bash
curl -fsSL https://raw.githubusercontent.com/diodeinc/pcb/main/install.sh | bash
```

Native Windows (experimental — prefer WSL2 if something misbehaves):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/diodeinc/pcb/main/install.ps1 | iex"
```

The Unix installer writes `pcb` to `$HOME/.local/bin` (`PCB_INSTALL_DIR`
overrides). It also registers the `diode://` URL scheme so registry links can
open sandbox layouts in KiCad. `pcb self update` updates the launcher;
`pcb toolchain prune` cleans old downloads.

## Quick start

`blinky.zen`:

```python
# ```pcb
# [workspace]
# pcb-version = "0.4"
# ```

Resistor = Module("@stdlib/generics/Resistor.zen")
Led = Module("@stdlib/generics/Led.zen")

VCC = Power()
GND = Ground()
LED_ANODE = Net()

Resistor(name="R1", value="1kohm", package="0402", P1=VCC, P2=LED_ANODE)
Led(name="D1", package="0402", color="red", A=LED_ANODE, K=GND)
Board(name="blinky", layers=4, layout_path="layout/blinky")
```

```bash
pcb build blinky.zen    # build and validate (no KiCad needed)
pcb layout blinky.zen   # generate the KiCad layout (KiCad 10.x)
```

## Common commands

```bash
pcb new board <NAME> <REPO_URL>               # create a board repository
pcb build [PATHS...]                          # build and validate designs
pcb sync                                      # reconcile imports and dependency manifests
pcb layout <FILE>                             # generate layout files
pcb dfm <FILE> --pdk standard                 # design-for-manufacturability checks
pcb import <KICAD_SCH|KICAD_PRO> <OUTPUT_DIR> # import a KiCad schematic or project
```

A **board repository** holds one board plus its local modules/components; a
**registry repository** holds reusable packages and no board. `pcb help`
covers the rest.

## After `pcb layout`: closing the loop headlessly

`pcb layout` hands you a KiCad project; gencad's
[`pcbtools/`](../pcbtools/README.md) takes it the rest of the way without a
GUI — geometry dump, clearance-oracle routing, DRC-driven convergence, and
JLCPCB export. Together the two make schematic-to-fab a fully scriptable
pipeline.
