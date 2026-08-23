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

## Notes

- chili3d is a young project (v0.7 at time of writing); it is a viewer and
  light editor here, not the source of truth. The parametric build script
  stays canonical.
- Self-hosting is straightforward (`npm install && npm run dev` in the
  chili3d repo) if the hosted app is unavailable.
