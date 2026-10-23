# pcbtools — headless KiCad layout automation

The electrical counterpart of gencad's CAD loop: a small toolkit that lets
an agent (or a script) take a KiCad board from *placed* to *routed and
DRC-clean* without opening a GUI. Dump the board to JSON, plan routes
against an independent clearance oracle, write only verified copper back,
measure with KiCad's own DRC, repeat until zero.

```
dump_board ──▶ geometry.json ──▶ route ──▶ routes.json ──▶ write_board
     ▲                             │  ▲                        │
     │                       clearance oracle                  ▼
     └──────────────── drc (kicad-cli, ground truth) ◀─────────┘
```

`converge.py` runs that loop end to end.

## Requirements

- **KiCad 8+** (developed against KiCad 10.0.5). `drc.py` and
  `converge.py` call `kicad-cli pcb drc --format json`, which first shipped
  in KiCad 8.0 ([release notes](https://www.kicad.org/blog/2024/02/Version-8.0.0-Released/)). The scripts that need the
  `pcbnew` bindings re-execute themselves under KiCad's bundled Python
  automatically (`kicad_env.py`; override with `KICAD_PYTHON` /
  `KICAD_CLI`).
- **numpy** for `route.py` only (obstacle rasterisation). Everything else
  is stdlib.
- `KICAD_PYTHON` must point at a Python that can import `pcbnew`. The
  re-exec happens at most once (guarded by `PCBTOOLS_REEXEC`); if `pcbnew`
  is still missing, the script exits with an error instead of looping.

Tests (pure Python, no KiCad needed):
`uvx --with pytest --with numpy pytest pcbtools/tests -q`.

## Quick start

```bash
# one-shot: route every unconnected net until DRC reports zero
# (--layers must name copper layers the board has; this is a 4-layer board)
python pcbtools/converge.py board.kicad_pcb --layers F.Cu,In2.Cu,B.Cu

# or step by step
python pcbtools/dump_board.py board.kicad_pcb -o geometry.json
python pcbtools/drc.py board.kicad_pcb -g geometry.json --airwires air.json
python pcbtools/route.py geometry.json air.json -o routes.json
python pcbtools/write_board.py board.kicad_pcb routes.json -g geometry.json
python pcbtools/drc.py board.kicad_pcb          # ground truth again

# JLCPCB assembly files
python pcbtools/jlc_export.py board.kicad_pcb --map parts.csv --dnp ANT1
python pcbtools/jlc_export.py board.kicad_pcb --lcsc-field LCSC  # BOM from a footprint field
```

## The tools

| Tool | Runs under | Does |
|---|---|---|
| `dump_board.py` | KiCad python (auto) | board → `geometry.json`: pads, drilled holes, tracks, vias, keep-out rule areas, footprint copper graphics, zones, auto-detected origin + outline (circle or rect) |
| `clearance.py` | any python | pure-math legality oracle over the dump: `seg_clear`, `via_clear`, `check_path` — shares no code with the router, so it also catches the router's bugs |
| `route.py` | any python + numpy | rasterised multi-layer A* with random-restart ordering, multiple width/via classes (`--classes 0.2:0.5,0.127:0.4`), endpoint snapping onto real net copper, and the oracle as a hard acceptance gate |
| `write_board.py` | KiCad python (auto) | apply verified routes + small ops (rip near a point, move/flip a footprint, add a via), refill zones, save — in one SWIG-safe pass. An unknown copper layer is an error and nothing is saved |
| `drc.py` | any python | `kicad-cli pcb drc` → error counts by type + airwire list in the dump's coordinate frame; exit 0 only on fully clean |
| `converge.py` | any python | the measure → dump → route → apply loop, route-first so a plan is never applied to a board it wasn't computed against; `routes.json` is deleted before each round and a router crash stops the loop |
| `jlc_export.py` | any python (KiCad python for `--lcsc-field`) | JLCPCB-format CPL from `kicad-cli` pos output, and BOM from a refs/mpn/lcsc mapping CSV or from a footprint field (`--lcsc-field`) |

## Model fidelity — what the oracle knows

These are the gaps that, when missing, produce boards that look routed
and fail DRC; each is modelled because omitting it once produced exactly
that failure:

- **Drilled holes block every layer.** SMD pads exist only on their own
  face, but a PTH/NPTH barrel obstructs inner-layer tracks and vias too.
- **Through-hole pads carry inner-layer copper.** The dump lists each inner
  layer a pad is on (`"In1.Cu"`) beside `"F"`/`"B"`, so an inner-layer track
  cannot cross an annular ring. Limit: the inner ring uses the front pad's
  bounding box, which is wrong for padstacks with a different inner size.
- **Cell-centre sampling lies by up to half a cell diagonal**, so every
  mask margin carries that slop; the checker then re-verifies the exact
  polyline.
- **Via diameters are per-class.** A path planned with 0.4 mm vias must
  be *checked* at 0.4 mm — verifying at the default silently rejects
  (or worse, accepts) the wrong geometry.
- **A via is never legal just because it lands on the goal.** Layer
  changes are refused wherever the via mask says no, destination
  included.
- **Keep-outs come from the board**, not from configuration: rule areas
  — including those inside footprints, such as a module's antenna keep-out
  — are dumped with their polygons and respected per layer. Tracks and vias
  must stay half their width plus clearance away, not just keep their
  centreline out.
- **Footprint copper graphics** (printed coils, logos) are obstacles;
  nets that legitimately connect to them are exempted with
  `--exempt-gfx-nets`. Rectangles, circles (as 32-gons) and polygons are
  dumped as their outline edges; other shapes are skipped with a warning.
  Limit: a filled shape is only its outline, so a via fully inside a large
  filled polygon is not caught.
- **Net names keep their brackets.** Bus nets such as `/DATA[0]` parse
  intact from DRC output, and an airwire whose net cannot be resolved is
  reported failed rather than dropped.
- **Custom pads** (primitive-based, e.g. printed coils) report
  primitive-spanning bounding boxes; the dump records the anchor so the
  oracle doesn't treat the whole structure as one giant pad.

## Practical notes

- **Keep the `.kicad_pro` next to the `.kicad_pcb`.** DRC reads design
  rules from the project file; a board copied without it is judged
  against KiCad's defaults and drowns in spurious width/clearance
  errors.
- KiCad's SWIG bindings invalidate their containers after `Add`/`Remove`;
  `write_board.py` snapshots first, mutates second, and never
  re-enumerates. Keep that discipline in any script you add.
- Zone fills are obstacles only via DRC (the loop's ground truth), not in
  the oracle — pour connectivity, thermal spokes and island removal are
  KiCad's job. Set island removal to *always* on plane zones or stitch
  orphan islands, or DRC will report zone-to-zone airwires no track can
  fix.
- The router treats already-accepted routes as obstacles for every later
  net inside a pass; between passes, `converge.py` re-dumps so the board
  file itself is the single source of truth.
- Unroutable nets are usually placement problems. The honest fixes are a
  `move_footprint` op (with `side` to flip) or widening the board — not
  shaving clearances.
