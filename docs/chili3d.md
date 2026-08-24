# chili3d as the human viewer

[chili3d](https://github.com/xiangechen/chili3d) is an open-source
(AGPL-3.0) browser CAD application built on TypeScript and a WebAssembly
port of OpenCascade — the same geometry kernel FreeCAD uses. That kernel
match matters: a `.step` exported by a gencad build script opens in chili3d
as the *same* B-rep, not a tessellated approximation.

## Where it fits in the gencad loop

```
agent ──▶ freecadcmd build ──▶ .FCStd / .step
                                   │
             render_section / render_iso   (agent's eyes)
                                   │
                               chili3d      (human's eyes)
```

The render tools exist so the *agent* can see what it modeled. chili3d is
the complementary stop for the *human*: zero-install, no Python env, no
local server — just [chili3d.com](https://chili3d.com) in a browser tab.

## Importing a model

1. Open [chili3d.com](https://chili3d.com) → **New Document**.
2. **Import** (ribbon, far right) → pick the exported `.step`
   (also accepts `.stl`, `.iges`, `.brep`, `.glb`, and friends).
3. Each STEP solid arrives as its own item in the tree — toggle
   visibility per part, orbit (Shift+Middle), measure, section, or run
   boolean edits on the live shapes.

## Agent-driven import (browser automation)

chili3d's Import button opens a native file picker, which browser
automation tooling cannot drive. The workaround that works: patch
`HTMLInputElement.prototype.click` to a no-op for `type="file"` inputs
*before* clicking Import, so the dynamically created input stays in the
DOM instead of opening the dialog — then set its files directly with the
automation tool's file-upload primitive:

```js
window.__captured = [];
const orig = HTMLInputElement.prototype.click;
HTMLInputElement.prototype.click = function () {
  if (this.type === 'file') {
    this.id ||= 'captured-file-input-' + window.__captured.length;
    if (!this.isConnected) document.body.appendChild(this);
    window.__captured.push(this.id);
    return;                       // swallow the native dialog
  }
  return orig.apply(this, arguments);
};
window.showOpenFilePicker = undefined;  // block the FS Access API path too
```

Click Import, find the captured input by id, upload the `.step` to it —
chili3d's change handler fires and the model loads.

## Running it locally

`chili3d/` is a **git submodule** pointing at
[xiangechen/chili3d](https://github.com/xiangechen/chili3d), pinned at
`c5b8047c` (v0.7.0 line, `0.2.0-679-gc5b8047c`). AGPL-3.0 — see its bundled
`LICENSE`. Credit to [@xiangechen](https://github.com/xiangechen) and the
chili3d contributors.

The hosted app at [chili3d.com](https://chili3d.com) stays the fast path — no
install, no server. The checkout is for when you want a pinned version that
does not move under you, offline work, or a build with local modifications.

```bash
# fresh clone of gencad — populate the submodules
git submodule update --init --recursive

cd chili3d
npm install
npm run dev        # http://localhost:8080
```

The prebuilt WebAssembly OpenCascade module ships in the repo, so `npm run
build:wasm` (CMake, emsdk) is only needed to rebuild the kernel from source.
Everything above — import flow, automation workaround — applies unchanged to
the local server; only the URL differs.

To move the pin:

```bash
git -C chili3d fetch origin && git -C chili3d checkout origin/main
git add chili3d && git commit -m "Bump chili3d pin"
```

## Notes

- chili3d is a young project (v0.7 at time of writing); it is a viewer and
  light editor here, not the source of truth. The parametric build script
  stays canonical.
- Submodule rather than vendored, for the same reasons as
  [geofield-bracket](geofield-bracket.md): no local patches to preserve, and
  it keeps the AGPL-3.0 tree distinct from gencad's MIT one. Contrast
  [vendoring.md](vendoring.md), where `text-to-cad/` *is* patched and so is
  copied in.
- gencad's setup installs none of this. The submodule has its own npm
  dependency tree; `npm install` inside `chili3d/` is opt-in.
