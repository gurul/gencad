# geofield-bracket (submodule)

`geofield-bracket/` is a **git submodule** pointing at
[connorkapoor/geofield-bracket](https://github.com/connorkapoor/geofield-bracket),
pinned at commit `18b74b7` (`v0.1.0-3-g18b74b7`). Licensed AGPL-3.0 — see its
bundled `LICENSE`. Credit to [@connorkapoor](https://github.com/connorkapoor).

## What it provides

Verified generative engineering for shelf brackets: give it a bounding box and
a load case, and it designs a bracket that fits and holds, predicts stress in
milliseconds, and certifies the winner with a real finite-element solve. A
single learned latent encodes geometry, physics and manufacturability at once;
every field is read out of that latent as a continuous function of space. No
CAD kernel, no meshes inside the model, everything local.

## Why it sits here

gencad's loop is *scripted*: an agent writes a parametric build script, renders
it, inspects it, iterates. geofield-bracket is the *generative* counterpart —
the geometry comes out of a learned field rather than a script, and a solver
certifies it rather than an eyeball. Keeping it alongside makes the two loops
comparable on the same bench: gencad can export a `.step` for a part
geofield-bracket proposed, and render or section it with `tools/render_*.py`.

## Submodule, not vendored

`text-to-cad/` is vendored (files copied in, patched, synced by
`scripts/pull-text-to-cad.sh` — see [vendoring.md](vendoring.md)). This one is
a submodule instead, for two reasons:

- **No local patches.** Vendoring exists so gencad-specific edits can survive
  upstream churn. There are none here — it is consumed as-is.
- **License separation.** gencad is MIT; geofield-bracket is AGPL-3.0. A
  submodule keeps the two trees and their histories distinct rather than
  copying AGPL sources into an MIT repo.

## Working with it

```bash
# fresh clone of gencad — populate the submodule
git submodule update --init --recursive

# or clone both at once
git clone --recurse-submodules https://github.com/gurul/gencad.git

# move the pin to upstream main
git -C geofield-bracket fetch origin
git -C geofield-bracket checkout origin/main
git add geofield-bracket && git commit -m "Bump geofield-bracket pin"
```

The submodule has its own `requirements.txt`, `Makefile` and `pytest.ini` —
run it from inside `geofield-bracket/`, in its own environment. Nothing in
gencad's setup installs it.
