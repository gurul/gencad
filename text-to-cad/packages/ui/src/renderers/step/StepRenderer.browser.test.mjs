import assert from 'node:assert/strict';
import { after, afterEach, before, test } from 'node:test';
import { PNG } from 'pngjs';
import { parseCadRefToken } from '@text-to-cad/core/lib/cadRefs.js';
import { serveStepHarness } from '../harness/stepScenario.mjs';

// The STEP renderer end to end in a real browser, over the committed two-part
// fixture (`__fixtures__/step`): a coloured base with a bore, a coloured arm, one
// revolute mate, one named pose and one routine. Everything under `renderers/step`
// serves STEP alone, and none of it had a browser test until this one — written
// against the renderer as it is, so the move onto the shared shell has a net.
//
// The rule these assertions are built on: a claim that something REACHED THE
// SCREEN reads the drawn frame — a screenshot of the live canvas — never
// `controller.capture()`, which renders a fresh frame before reading and so
// cannot see a missing repaint.

let harness;
const cleanups = [];
before(async () => { harness = await serveStepHarness({ after: cleanup => cleanups.push(cleanup) }); });
afterEach(async () => { await harness?.closePages(); });
after(async () => { for (const cleanup of cleanups.reverse()) await cleanup(); });

const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
// The camera at rest from one frame to the next: the opening fit, or a camera a test set.
const restingCamera = async page => {
  await page.evaluate(() => { window.__lastCamera = null; });
  await page.waitForFunction(() => {
    const camera = JSON.stringify(window.__cadCamera());
    const still = window.__lastCamera === camera;
    window.__lastCamera = camera;
    return still;
  }, null, { polling: 'raf' });
};
/** The last thing the viewport actually DREW. */
const frame = async (pane) => { await settle(pane.page()); return PNG.sync.read(await pane.locator('[aria-busy] > div > canvas').first().screenshot({ style: '[data-slot=popover-content], [data-slot=dropdown-menu-content], [data-slot=dropdown-menu-sub-content], [data-cad-tool-groups], [data-file-sidebar-room], [data-preview-controls], [aria-label="View cube"] { visibility: hidden !important; }' })); };
// A canvas screenshot also catches what is drawn OVER the canvas: the tool strip
// along the top, the tool stack's panels under it and the file sidebar down the left (hidden for
// the shot: they change with every tool, hover and selection) and the view cube (also hidden for
// the shot). None is the model. Measurements keep the original model band of the 800 × 600 harness
// (an 800 × 564 canvas), so control placement cannot affect part-color counts. Pixel
// counts below are for this band, 385 × 800: half what the tests once measured at 1200 × 720.
const MODEL = { y0: 55, y1: 440 };
function differing(left, right, { x0 = 0, y0 = 0, x1 = left.width, y1 = left.height } = MODEL) {
  let count = 0;
  for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) {
    const offset = (y * left.width + x) * 4;
    if ([0, 1, 2].some(channel => Math.abs(left.data[offset + channel] - right.data[offset + channel]) > 2)) count += 1;
  }
  return count;
}
/** How many pixels of a region are not the backdrop: what is drawn there. */
function painted(image, { x0 = 0, y0 = 0, x1 = image.width, y1 = image.height } = MODEL) {
  const backdrop = [image.data[0], image.data[1], image.data[2]];
  let count = 0;
  for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) {
    const offset = (y * image.width + x) * 4;
    if ([0, 1, 2].reduce((sum, channel) => sum + Math.abs(image.data[offset + channel] - backdrop[channel]), 0) > 12) count += 1;
  }
  return count;
}
const coverage = image => painted(image) / (image.width * (MODEL.y1 - MODEL.y0));
/**
 * Where each part is ON SCREEN, by its own colour: the base is authored blue
 * (#3A6EA5) and the arm orange (#D9772B), so a shaded pixel still belongs to
 * exactly one of them. This is what makes "the parts moved apart" a measurement
 * rather than a guess about total ink.
 */
function partBoxes(image) {
  const boxes = { base: null, arm: null };
  for (let y = MODEL.y0; y < MODEL.y1; y += 1) for (let x = 0; x < image.width; x += 1) {
    const offset = (y * image.width + x) * 4;
    const [red, green, blue] = [image.data[offset], image.data[offset + 1], image.data[offset + 2]];
    if (red + green + blue < 40) continue;
    const part = blue > red + 25 && blue > green + 10 ? 'base' : red > blue + 25 && red > green + 10 ? 'arm' : '';
    if (!part) continue;
    const box = boxes[part] || (boxes[part] = { x0: x, x1: x, y0: y, y1: y, count: 0 });
    box.x0 = Math.min(box.x0, x); box.x1 = Math.max(box.x1, x);
    box.y0 = Math.min(box.y0, y); box.y1 = Math.max(box.y1, y);
    box.count += 1;
  }
  return boxes;
}
/** World point -> page coordinates, from the camera the viewport publishes. */
function projector(camera, box) {
  const sub = (a, b) => a.map((value, index) => value - b[index]);
  const norm = vector => { const length = Math.hypot(...vector); return vector.map(value => value / length); };
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a.reduce((sum, value, index) => sum + value * b[index], 0);
  const forward = norm(sub(camera.target, camera.position));
  const right = norm(cross(forward, camera.up));
  const up = cross(right, forward);
  const halfWidth = camera.halfHeight * (box.width / box.height);
  return point => {
    const offset = sub(point, camera.target);
    return [box.x + (dot(offset, right) / halfWidth * 0.5 + 0.5) * box.width,
      box.y + (0.5 - dot(offset, up) / camera.halfHeight * 0.5) * box.height];
  };
}
const translations = page => page.evaluate(() => Object.fromEntries(window.__cadDisplayRecords().map(record => [record.partId, record.matrix.slice(12, 15)])));
// Where the parts come to rest, no longer where they were (`from`): an explosion turned on has eased
// all the way out. Read on the page's own frames, not on a timer: the ease moves the parts on every
// frame it runs, so a layout unchanged for `still` frames in a row is one the ease has finished
// with. (A timer's two reads can both land between two frames of an ease a slow software renderer
// is still drawing.) It answers that layout.
const restingLayout = (page, from, still = 5) => page.evaluate(({ from, still }) => new Promise((resolve, reject) => {
  const layout = () => Object.fromEntries(window.__cadDisplayRecords().map(record => [record.partId, record.matrix.slice(12, 15)]));
  const same = (a, b) => Object.keys(a).length === Object.keys(b).length
    && Object.keys(a).every(id => b[id] && a[id].every((value, axis) => value === b[id][axis]));
  const deadline = performance.now() + 30_000;
  let last = null, unchanged = 0;
  const frame = () => {
    const now = layout();
    unchanged = last && same(now, last) && !same(now, from) ? unchanged + 1 : 0;
    last = now;
    if (unchanged >= still) resolve(now);
    else if (performance.now() > deadline) reject(new Error(`the parts never came to rest: ${JSON.stringify(now)}`));
    else requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}), { from, still });
/**
 * The drawn frame once it satisfies `reached`, or a failure naming what it never
 * did. A repaint can land a frame or two after the state that asked for it, so a
 * single shot is a race; a poll that runs out is still the missing-repaint bug.
 */
async function frameWhen(view, reached, what) {
  let last;
  // Up to ~8 s: a software renderer's idle-quality repaint can land seconds after the pointer stops.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    last = await view.frame();
    if (reached(last)) return last;
    await view.page.waitForTimeout(200);
  }
  throw new assert.AssertionError({ message: `the drawn frame never ${what}`, actual: false, expected: true, operator: '==' });
}

/**
 * The view at rest: a frame once two in a row are the same. One taken a fixed moment after a
 * change can still be the interactive pass that an idle-quality repaint replaces later, and a
 * baseline like that is one no later frame ever matches.
 */
async function restingFrame(view) {
  let last = await view.frame();
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await view.page.waitForTimeout(200);
    const next = await view.frame();
    if (differing(last, next) === 0) return next;
    last = next;
  }
  throw new assert.AssertionError({ message: 'the drawn frame never came to rest', actual: false, expected: true, operator: '==' });
}

/**
 * Measure picks: each point hovered, then pressed, a frame apart. What they measured is the
 * caller's to await (a ruler in the Measurements list).
 */
async function measurePoints(page, at, ...points) {
  for (const point of points) {
    await page.mouse.move(...at(point));
    await settle(page);
    await page.mouse.click(...at(point));
    await settle(page);
  }
}

// A page over the fixture, its Features open. Preview opens with a still camera (Orbit off), so
// what moves in a frame is the model.
async function open(options = {}) {
  const view = await harness.open(options);
  const { page, pane } = view;
  const ready = async () => {
    await pane.locator('[aria-busy="false"] > div > canvas').first().waitFor();
    await page.waitForFunction(() => window.cadHarness.a.controller?.readState().loading === false);
    // An assembly's Features are the file sidebar's, opened by their tile. The sidebar floats over
    // the viewport: it never narrows it.
    await pane.getByRole('group', { name: 'File sidebar' }).getByRole('button', { name: 'Model tree', exact: true }).click();
    await pane.getByRole('region', { name: 'Model tree', exact: true }).waitFor();
    await restingCamera(page);
    await settle(page);
    const box = await pane.locator('[data-cad-surface] canvas').first().boundingBox();
    return { box, at: projector(await page.evaluate(() => window.__cadCamera()), box) };
  };
  const { box, at } = await ready();
  const opened = {
    ...view, box, at,
    // The page again — the same tab, for a page whose tab record is in sessionStorage.
    reload: async () => { await page.reload(); Object.assign(opened, await ready()); },
    state: () => page.evaluate(() => window.cadHarness.a.controller.readState()),
    display: patch => page.evaluate(next => window.cadHarness.a.controller.setDisplaySettings(next), patch),
    // Preview: in by Preview at the strip's end, out by Exit preview in the navbar; each
    // once its cover has lifted. It opens still (Orbit off), so what moves in a frame is the model.
    enterPreview: async () => {
      await pane.getByRole('button', { name: 'Preview', exact: true }).click();
      await pane.getByRole('button', { name: 'Exit preview', exact: true }).waitFor();
      await page.waitForFunction(() => !document.querySelector('[data-testid="one"] [data-preview-cover]'));
    },
    exitPreview: async () => {
      await pane.getByRole('button', { name: 'Exit preview', exact: true }).click();
      await pane.getByRole('button', { name: 'Preview', exact: true }).waitFor();
      await page.waitForFunction(() => !document.querySelector('[data-testid="one"] [data-preview-cover]'));
    },
    // The file sidebar's tiles, and a section opened by its tile (one at a time), left open if it is.
    tiles: () => pane.locator('[data-file-sidebar-tools] button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label'))),
    openSection: async name => {
      const tile = pane.getByRole('group', { name: 'File sidebar' }).getByRole('button', { name, exact: true });
      if (await tile.getAttribute('aria-pressed') !== 'true') await tile.click();
      await pane.locator(`[data-file-sidebar-tools] button[aria-pressed="true"][aria-label="${name}"]`).waitFor();
    },
    // The routine's transport: the sidebar's Animation section in the tools view, and in Preview
    // (which has no sidebar) its playbar under the model.
    animation: pane.locator('[data-tool-panel][aria-label="Animation"]'),
    playbar: pane.getByRole('toolbar', { name: 'Animation playback', exact: true }),
    // The view's controls, at the strip's end after its rule: Projection, Display, then Preview.
    viewControls: () => pane.locator('[data-cad-toolbar] [data-view-controls] button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label'))),
    // Display is not a tool: its tile, the mode in hand, sits between Projection and Preview at the
    // strip's end, after a rule; its menu is the modes and the Grid switch.
    openDisplay: async (root = pane.locator('[data-cad-toolbar] [data-view-controls]')) => {
      await root.getByRole('button', { name: /^Display mode: / }).click();
      await page.locator('[role=menu][aria-label="Display"]').waitFor();
    },
    tool: name => name === 'Display' ? pane.locator('[data-cad-toolbar] [data-view-controls]').getByRole('button', { name: /^Display mode: / })
      : pane.locator(name === 'Reset' ? '[data-cad-camera-controls]' : '[data-cad-toolbar]').getByRole('button', { name, exact: true }),
    tools: () => pane.locator('[data-cad-toolbar]').getByRole('button')
      .evaluateAll(buttons => buttons.filter(button => !button.closest('[data-view-controls]')).map(button => `${button.getAttribute('aria-label')}:${button.getAttribute('aria-pressed')}`)),
    // The tool stack's panels on screen, top to bottom, by their accessible names.
    stack: () => pane.locator('[data-cad-tool-stack] [data-tool-panel]').evaluateAll(panels => panels
      .filter(panel => panel.getClientRects().length > 0).map(panel => panel.getAttribute('aria-label'))),
    // The file sidebar's sections, top to bottom, the same way. A section draws no box of its own
    // (`display: contents`): one not hidden is on screen.
    sidebar: () => pane.locator('[data-cad-file-sidebar] [data-tool-panel]').evaluateAll(panels => panels
      .filter(panel => !panel.closest('[hidden]')).map(panel => panel.getAttribute('aria-label'))),
    // Select's selection filter is the chevron right after its button on the strip
    // (`SelectionModes.jsx`): a checkbox per kind. `ticks` names those to tick (true) or untick
    // (false); a kind the menu does not offer (Parts in a part file) is passed over.
    setFilter: async ticks => {
      await pane.locator('[data-cad-toolbar] [data-select-filter-trigger]').click();
      const menu = page.locator('[role=menu][aria-label="Selection filter"]');
      for (const [id, wanted] of Object.entries(ticks)) {
        const item = menu.locator(`[data-select-filter="${id}"]`);
        if (await item.count() && (await item.getAttribute('aria-checked') === 'true') !== wanted) await item.click();
      }
      await page.keyboard.press('Escape');
      await menu.waitFor({ state: 'detached' });
    },
    // The geometry Select picks, as the old modes named it: All of it, or Parts, Faces or Edges alone.
    chooseSelectMode: name => opened.setFilter({ parts: name === 'All' || name === 'Parts', faces: name === 'All' || name === 'Faces',
      edges: name === 'All' || name === 'Edges' }),
    selectFilter: () => pane.locator('[data-cad-toolbar] [data-select-filter-trigger]').getAttribute('aria-label'),
    // A part is a leaf of the tree: its row's menu Expands it, which loads its faces and edges for
    // a pick under All, and Collapses it again.
    partMenu: async (name, item) => {
      await pane.getByRole('button', { name: `Select ${name}`, exact: true }).click({ button: 'right' });
      await page.getByRole('menuitem', { name: item, exact: true }).click();
      await page.getByRole('menu').waitFor({ state: 'detached' });
    },
    // What is picked is Quick Edit's to show: a chip each (`ReferenceChips.jsx`), by its words.
    quickEdit: () => pane.getByRole('region', { name: 'Quick Edit', exact: true }),
    chips: () => pane.locator('[data-quick-edit-refs] [data-quick-edit-ref] > button:first-child')
      .evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label'))),
    chip: label => pane.locator('[data-quick-edit-refs]').getByRole('button', { name: label, exact: true }),
    // A chip's card: the pointer rests on the chip, and the card of what it is opens beside it.
    chipCard: async label => {
      await pane.locator('[data-quick-edit-refs]').getByRole('button', { name: label, exact: true }).hover();
      const card = page.locator('[data-quick-edit-ref-card]').filter({ has: page.getByText(label, { exact: true }) });
      await card.waitFor();
      return card;
    },
    // Display's menu: a dropdown, portaled out of the viewer.
    displayPanel: () => page.locator('[role=menu][aria-label="Display"]'),
    rows: () => pane.locator('[aria-label="Modeling tree"]').getByRole('button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label'))
      .filter(label => label?.startsWith('Select ') || label?.startsWith('Expand ') || label?.startsWith('Collapse '))),
    frame: () => frame(pane),
    // What the pointer looks like over the model. Read from the INTERACTIVE
    // canvas: a tool sets the cursor on the viewport host and the canvas
    // inherits it, which three's OrbitControls used to break by pinning
    // `cursor: auto` on the canvas inline (`kit/viewport/useViewerRuntime.js`).
    waitCursor: value => page.waitForFunction(wanted => getComputedStyle(
      document.querySelector('[data-testid="one"] [aria-busy] > div > canvas')).cursor === wanted, value),
  };
  return opened;
}


test('a STEP opens in Select with the tools its sidecar earns, its Model tree, Position and Animation the file sidebar\'s tiles, Select\'s selection filter on the strip, Projection, Display and Preview ending the strip, and paints both authored colours', async () => {
  const view = await open();
  const { page, pane, errors } = view;
  // Select's selection filter is a chevron of its own right after its button, never pressed as a
  // tool is, picking everything as the file opens. Position is no tool: its knobs are Select's.
  assert.deepEqual(await view.tools(), ['Select:true', 'Selection filter: everything:null', 'Annotate:false', 'Measure:false',
    'Explode:false', 'Clip:false'],
    'no Animation tool: routines are the sidebar\'s. Display is a dropdown, not a tool');
  assert.deepEqual(await view.viewControls(), ['Projection: Orthographic', 'Display mode: Solid', 'Preview'],
    'the view\'s controls end the strip: Projection, Display, then Preview');
  assert.equal(await pane.locator('[data-cad-toolbar] [data-strip-rule] + [data-view-controls]').count(), 1, 'after the strip\'s rule');
  assert.equal(await pane.locator('[data-viewer-navbar] [data-view-controls] button').count(), 0, 'nothing of the view in the navbar');
  assert.equal(await pane.getByRole('region', { name: 'Model tree', exact: true }).getByRole('button', { name: /^Selection filter: / }).count(), 0,
    'Select\'s filter is the strip\'s, not the Model tree section\'s');
  assert.equal(await view.displayPanel().count(), 0, 'Display is never where a file opens');
  // The file sidebar holds the Features — an assembly's tree starts open — Position's controls and
  // the routine, a tile each, whatever the tool, with no tabs; Select has nothing in the tool stack.
  assert.deepEqual([await view.sidebar(), await view.stack(), await view.tiles()],
    [['Model tree', 'Position controls', 'Animation'], [], ['Model tree', 'Position', 'Animation']]);
  assert.equal(await pane.getByRole('tab').count(), 0, 'no tabs anywhere');
  // The strip is centred; the sidebar's tiles keep the view's top-left corner, 8px in, its open
  // section's panel under them (the two may overlap the strip).
  const sidebar = pane.locator('aside[data-cad-file-sidebar]');
  // Once the panel has slid in.
  await sidebar.evaluate(node => Promise.all(node.getAnimations().map(animation => animation.finished)));
  const [tilesBox, sidebarBox, toolbar] = await Promise.all([pane.locator('[data-file-sidebar-tools]').boundingBox(), sidebar.boundingBox(), pane.locator('[data-cad-toolbar]').boundingBox()]);
  assert.ok(Math.abs(toolbar.x + toolbar.width / 2 - (view.box.x + view.box.width / 2)) <= 1, 'the strip is centred');
  assert.ok(Math.abs(tilesBox.y - view.box.y - 8) <= 1 && Math.abs(tilesBox.x - view.box.x - 8) <= 1,
    `the tiles keep the corner: ${JSON.stringify({ tilesBox, view: view.box })}`);
  assert.ok(Math.abs(sidebarBox.x - tilesBox.x) <= 1 && sidebarBox.y >= tilesBox.y + tilesBox.height, `the open section hangs under the tiles: ${JSON.stringify({ tilesBox, sidebarBox })}`);
  // The sidebar floats over the viewport: the canvas is the viewer's whole width.
  assert.equal(view.box.width, (await pane.locator('[data-cad-scene-backdrop]').boundingBox()).width);
  const opened = await view.frame();
  assert.ok(coverage(opened) > 0.2, `the opening frame is the model: ${coverage(opened)}`);
  const boxes = partBoxes(opened);
  assert.ok(boxes.base?.count > 2000 && boxes.arm?.count > 1000, `both parts are drawn, each in its own colour: ${JSON.stringify(boxes)}`);
  // A part is a leaf: nothing opens under it.
  assert.deepEqual(await view.rows(), ['Select base', 'Select arm']);
  // The panel opens a tool panel's width and as tall as its section, up to all the room there
  // is; a section has no size of its own. A cap is never a floor: two rows are two rows tall.
  const featuresPanel = pane.getByRole('region', { name: 'Model tree', exact: true });
  const scroller = pane.locator('[data-file-sidebar-scroller]');
  const overflow = () => scroller.evaluate(node => [node.scrollWidth - node.clientWidth, node.scrollHeight - node.clientHeight]);
  assert.equal(Math.round(sidebarBox.width), 164, 'a tool panel\'s width');
  assert.equal(await featuresPanel.evaluate(node => node.style.maxHeight), '', 'the tree has no cap of its own');
  assert.deepEqual(await overflow(), [0, 0], 'the panel is as tall as its section: nothing to scroll');
  // The tree is headed by its search box, then the section's X; nothing folds it, and Select
  // pressed again changes nothing.
  assert.deepEqual(await featuresPanel.locator('[data-sidebar-head]').getByRole('button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label') || button.textContent.trim())),
    ['Close model tree'], 'the tree\'s head: its filter and its X');
  const openedRows = await view.rows();
  await view.tool('Select').click();
  assert.deepEqual([await view.sidebar(), await view.stack(), await view.rows()], [['Model tree', 'Position controls', 'Animation'], [], openedRows]);
  assert.deepEqual(await page.evaluate(() => window.cadHarness.preferences.getSnapshot().toolStack), { panels: {}, collapsed: {} },
    'nothing is stored until a person sizes the panel');
  // Position's pose is the first row of its section, a menu the width of the panel.
  await view.openSection('Position');
  assert.equal(await pane.locator('[data-tool-panel-body] [data-pose-row] [data-pose-menu]').isVisible(), true, 'the Pose menu heads Position\'s body');
  await view.openSection('Model tree');
  // One grip, Quick Edit's, in the panel's bottom-right corner and inside its border: it alone
  // sizes the panel, and no section has one of its own.
  assert.deepEqual(await sidebar.getByRole('separator').evaluateAll(handles => handles.map(handle => handle.getAttribute('aria-label'))), ['Resize file sidebar']);
  const grip = await sidebar.getByRole('separator', { name: 'Resize file sidebar', exact: true }).boundingBox();
  const panelBox = await sidebar.boundingBox();
  assert.ok(Math.abs(grip.x + grip.width - (panelBox.x + panelBox.width - 1)) <= 1 && Math.abs(grip.y + grip.height - (panelBox.y + panelBox.height - 1)) <= 1,
    `the grip fills the corner inside the border: ${JSON.stringify([grip, panelBox])}`);
  // Held shorter than its section, the whole panel scrolls, as one: the tree does not scroll inside it.
  await sidebar.getByRole('separator', { name: 'Resize file sidebar', exact: true }).press('Home');
  await pane.locator('aside[data-cad-file-sidebar][style*="max-height: 64px"]').waitFor();
  const [across, down] = await overflow();
  assert.ok(across === 0 && down > 0, `the panel scrolls its section: ${JSON.stringify([across, down])}`);
  assert.equal(await featuresPanel.locator('[data-tool-panel-body]').evaluate(node => node.scrollHeight > node.clientHeight), false, 'and the tree has nothing of its own to scroll');
  assert.deepEqual(errors, []);
});

test('Select picks parts and faces, a selection outlives Select, and Quick Edit\'s chips name and measure what is picked', async () => {
  const view = await open();
  const { page, pane, at, errors } = view;

  // Hover lights the part under the pointer, and lets go when it leaves.
  const still = await restingFrame(view);
  await page.mouse.move(...at([6, 6, 5]));
  // Over a part the pointer says it can be picked; over the backdrop it does not.
  await view.waitCursor('pointer');
  await frameWhen(view, shot => differing(still, shot) > 2000, 'lit the hovered part');
  await page.mouse.move(view.box.x + view.box.width - 20, view.box.y + view.box.height - 20);
  await view.waitCursor('auto');
  await frameWhen(view, shot => differing(still, shot) === 0, 'came back exactly as it was once the pointer left');

  // In the viewport a press picks ONE face or ONE edge: under All an expanded part's faces are what
  // a press picks. Its faces land after it expands, and a press before they land picks the part:
  // press until a face answers.
  await view.partMenu('base', 'Expand');
  const oneFace = () => page.evaluate(() => { const ids = window.cadHarness.a.controller.readState().selectedReferenceIds;
    return ids.length === 1 && /\.f\d+$/.test(ids[0]); });
  for (let attempt = 0; attempt < 50 && !(await oneFace()); attempt += 1) {
    await page.mouse.click(...at([6, 6, 5]));
    await page.waitForTimeout(100);
  }
  assert.equal(await oneFace(), true, 'a press picks one face of the expanded part');
  // The pick opened Quick Edit with the pick attached, as a chip naming the face by its part and
  // its kind, and the keyboard is in its box.
  const quickEdit = view.quickEdit();
  await quickEdit.locator('[data-quick-edit-ref]').waitFor();
  const pickedFace = (await view.state()).selectedReferenceIds[0].split('|').at(-1);
  assert.deepEqual(await view.chips(), [`base · face ${pickedFace.replace(/^.*\.f/, '')}`]);
  assert.equal(await quickEdit.locator('[data-quick-edit-chip="references"]').count(), 0, 'chips name the references: nothing counts them');
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Describe your changes');
  await page.mouse.click(...at([10, -6, 5]));
  await page.waitForFunction(() => { const ids = window.cadHarness.a.controller.readState().selectedReferenceIds;
    return ids.length === 1 && /\.e\d+$/.test(ids[0]); });
  // Folding the part away unloads its faces, and the pick with them: the tree is as it opened.
  await view.partMenu('base', 'Collapse');
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedReferenceIds.length === 0);

  // Nothing joins the sidebar or the stack, with a selection or without: what is picked is Quick
  // Edit's, a chip each.
  const panels = async () => [await view.sidebar(), await view.stack()];
  assert.deepEqual(await panels(), [['Model tree', 'Position controls', 'Animation'], []]);
  await page.mouse.click(...at([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 1);
  assert.deepEqual((await view.state()).selectedPartIds, ['o1.1']);
  assert.deepEqual(await panels(), [['Model tree', 'Position controls', 'Animation'], []], 'no Reference panel comes with the selection');
  assert.deepEqual(await view.chips(), ['base'], 'the part\'s chip, by its name');
  // Its card, once the pointer rests on the chip: the part's name, its id, then its key
  // measurements — no type, position or material rows.
  const partCard = await view.chipCard('base');
  const partText = (await partCard.innerText()).replace(/\s+/g, ' ').trim();
  assert.match(partText, /^base ID o1\.1 Size 20 × 20 × 10 mm(?: Volume [\d,.]+ mm³)?$/);
  assert.doesNotMatch(partText, /\bType\b|Center|Material|Color/);
  // Compact rows in the card's one face: every value is the UI font at 11px, never monospace, and
  // the name, the id and the key measurements fit it: nothing to scroll to.
  const faces = await partCard.locator('*').evaluateAll(nodes => [...new Set(nodes
    .filter(node => !node.childElementCount && node.textContent.trim())
    .map(node => `${getComputedStyle(node).fontFamily} | ${getComputedStyle(node).fontSize}`))]);
  assert.equal(faces.length, 1, `one face and size: ${faces.join(' / ')}`);
  assert.doesNotMatch(faces[0], /mono/i);
  assert.match(faces[0], /\| 11px$/);
  const rowHeights = await partCard.locator('[data-info-row]').evaluateAll(rows => rows.map(row => row.getBoundingClientRect().height));
  assert.ok(rowHeights.length >= 2 && rowHeights.every(height => height <= 19 * 2), `compact rows, a line or two each: ${rowHeights}`);
  assert.equal(await partCard.locator('[data-slot=scroll-area-viewport]').evaluate(node => node.scrollHeight <= node.clientHeight), true,
    'the card has nothing to scroll to');
  // Features' search box is its head: a tree row's height, its text at the panels' 11px.
  const featuresPanel = pane.getByRole('region', { name: 'Model tree', exact: true });
  const findField = featuresPanel.locator('[data-sidebar-head] [data-slot=tree-filter]');
  assert.equal(Math.round((await findField.boundingBox()).height), 24, 'the search box is a tree row\'s height, the head of the section');
  assert.equal(await featuresPanel.locator('[data-tool-panel-heading]').count(), 0, 'with no heading of its own');
  assert.equal(await pane.getByRole('textbox', { name: 'Filter model', exact: true }).evaluate(node => getComputedStyle(node).fontSize), '11px');
  assert.equal(await pane.getByRole('button', { name: 'Select base', exact: true }).getAttribute('aria-pressed'), 'true', 'the tree row follows the viewport');
  await page.keyboard.down('Shift');
  await page.mouse.click(...at([15, 0, 4]));
  await page.keyboard.up('Shift');
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 2);
  // Two parts: a chip each, in the order they were picked, and nothing that counts them.
  assert.deepEqual(await view.chips(), ['base', 'arm']);
  assert.match((await (await view.chipCard('arm')).innerText()).replace(/\s+/g, ' ').trim(), /^arm ID o1\.2 Size /);
  // The person's pick put the keyboard in Quick Edit's note; Escape in its empty box clears the
  // selection, as it would from the model, and the box goes with it.
  const quickEditBox = view.quickEdit();
  assert.equal(await quickEditBox.locator('[data-quick-edit-chip="references"]').count(), 0);
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Describe your changes');
  assert.equal(await pane.locator('[data-viewport-bottom-actions]').count(), 0, 'nothing sits at the bottom of the view');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 0);
  await quickEditBox.waitFor({ state: 'detached' });

  // A selection outlives Select: another tool shows its own panel, if it has one, and the
  // selection stays, its chip in Quick Edit; the tree stays as it was, whatever the tool.
  await page.mouse.click(...at([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 1);
  await view.tool('Measure').click();
  assert.deepEqual(await panels(), [['Model tree', 'Position controls', 'Animation'], []], 'Measure has no panel (its results are Quick Edit\'s chips); the sidebar stays');
  assert.deepEqual((await view.state()).selectedPartIds, ['o1.1'], 'the selection stays under Measure');
  assert.deepEqual(await view.chips(), ['base'], 'and Quick Edit still carries it');
  await view.tool('Clip').click();
  await view.tool('Select').click();
  assert.deepEqual(await panels(), [['Model tree', 'Position controls', 'Animation'], []], 'Clip\'s panel goes with the tool');
  await pane.getByRole('button', { name: 'Select arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 1);
  assert.deepEqual((await view.state()).selectedPartIds, ['o1.2']);
  // The chip's X drops its pick, and Quick Edit, with nothing left to carry, goes with it.
  await view.quickEdit().getByRole('button', { name: 'Remove arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 0);
  await quickEditBox.waitFor({ state: 'detached' });
  assert.deepEqual(await panels(), [['Model tree', 'Position controls', 'Animation'], []]);

  // What the host can drive: selectors in, selection out, and a clear.
  await page.evaluate(() => window.cadHarness.a.controller.select({ selectors: ['o1.2'] }));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.2');
  const live = await view.state();
  assert.deepEqual([live.selectedReferenceIds, live.hiddenPartIds, live.isolatedPartIds], [[], [], []]);
  // The selection in the prompt grammar the live contract reads (what `viewer-state` hands an
  // agent): a selector of the document on screen, never the renderer's own copy vocabulary.
  assert.deepEqual(live.selection, [{ resource: live.resource, target: { kind: 'cad-selector', selectors: ['o1.2'] }, label: 'arm' }]);
  await page.evaluate(() => window.cadHarness.a.controller.clearSelection());
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 0);
  // And what a host's capture delivers: the snapshot carries the file, the references the selection.
  await page.evaluate(() => window.cadHarness.a.controller.select({ selectors: ['o1.1'] }));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 1);
  await page.evaluate(() => window.cadHarness.capture());
  await page.waitForFunction(() => window.cadHarness.captures.length === 1);
  const captured = await page.evaluate(() => window.cadHarness.captures[0]);
  assert.equal(captured.type, 'image/png');
  assert.ok(captured.size > 100);
  assert.deepEqual(captured.references.map(reference => reference.target),
    [{ kind: 'cad-selector', selectors: ['o1.1'] }], 'the snapshot carries the selection as its references');

  assert.deepEqual(errors, []);
});

test('under Faces or Edges, one press on a part whose faces are not loaded loads that part alone and picks what is under the pointer, and an update keeps the mode', async () => {
  const view = await open();
  const { page, pane, at, errors } = view;
  const mode = name => view.chooseSelectMode(name);
  const selected = () => page.evaluate(() => window.cadHarness.a.controller.readState().selectedReferenceIds);
  // The tree loads a part's faces as its row comes on screen. With a filter that matches
  // nothing, no row is on screen, so under Faces no part has its faces loaded.
  await pane.getByRole('textbox', { name: 'Filter model', exact: true }).fill('zzz');
  await mode('Faces');
  assert.deepEqual([(await view.state()).selectedPartIds, await view.rows()], [[], []]);
  // One press on the base's top face: the base's topology loads — the Features panel says so
  // while it does — and that face is picked, with no second press. The load is quick here, so
  // what the panel showed is recorded as it is drawn.
  await page.evaluate(() => {
    window.__sawLoading = [];
    new MutationObserver(() => {
      for (const status of document.querySelectorAll('[data-testid="one"] [aria-label="Model tree"] [role=status]')) {
        if (status.textContent === 'Loading…') window.__sawLoading.push(window.cadHarness.a.controller.readState().selectedReferenceIds.length);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await page.mouse.click(...at([6, 6, 5]));
  await page.waitForFunction(() => /^topology\|o1\.1\|face\|o1\.1\.f\d+$/.test(window.cadHarness.a.controller.readState().selectedReferenceIds.join()));
  const face = (await selected())[0].split('|').at(-1);
  assert.deepEqual(await page.evaluate(() => window.__sawLoading.slice(0, 1)), [0], 'the Features panel said it was loading, before anything was picked');
  assert.equal(await pane.getByRole('region', { name: 'Model tree', exact: true }).getByText('Loading…').count(), 0, 'and stops once the face is picked');
  assert.equal(await pane.locator('[data-cad-toolbar] [role=status]').count(), 0, 'nothing under the strip says so');
  // Its chip names it by its part as the tree names it and its kind, never by its raw id, which its
  // card shows as its ID, over its area.
  const faceName = `base · face ${face.replace(/^.*\.f/, '')}`;
  assert.deepEqual(await view.chips(), [faceName], 'the chip names the face under the pointer');
  const faceText = (await (await view.chipCard(faceName)).innerText()).replace(/\s+/g, ' ').trim();
  assert.match(faceText, new RegExp(`^${faceName} ID ${face.replace(/\./g, '\\.')} Area [\\d,.]+ mm²$`), 'its card: its ID, then its area');
  assert.doesNotMatch(faceText, /\bType\b|Center|Normal|Material/);
  assert.deepEqual((await view.state()).selectedPartIds, [], 'the mode never falls back to the part');
  // Edges likewise, on the arm, whose topology is still not loaded (the panel says so again):
  // its top edge over the +x face.
  const sawBefore = await page.evaluate(() => window.__sawLoading.length);
  await mode('Edges');
  await page.mouse.click(...at([20, 0, 4]));
  await page.waitForFunction(() => /^topology\|o1\.2\|edge\|o1\.2\.e\d+$/.test(window.cadHarness.a.controller.readState().selectedReferenceIds.join()));
  assert.ok(await page.evaluate(() => window.__sawLoading.length) > sawBefore, 'only the pressed part had loaded');
  const edge = (await selected())[0].split('|').at(-1);
  const edgeName = `arm · edge ${edge.replace(/^.*\.e/, '')}`;
  assert.deepEqual(await view.chips(), [edgeName]);
  const edgeText = (await (await view.chipCard(edgeName)).innerText()).replace(/\s+/g, ' ').trim();
  assert.match(edgeText, new RegExp(`^${edgeName} ID ${edge.replace(/\./g, '\\.')} Length [\\d,.]+ mm$`), 'its length, the one measurement a straight edge has');
  assert.doesNotMatch(edgeText, /\bType\b/);
  // An update of the model keeps the mode, and drops what was picked in the revision before it.
  await view.update();
  assert.equal(await view.selectFilter(), 'Selection filter: Edges, Position, Annotations, Measurement');
  assert.deepEqual(await selected(), []);
  assert.deepEqual(errors, []);
});

// What the one part menu offers, in order, ending in the framing group. That group is
// the viewer's ONLY zoom control — the old Inspector's percentage readout and its menu are
// gone — so it is here, on every tree row, and on the empty-space menu below. It cannot
// contradict the tool in hand: every item returns to Select before it acts.
const ZOOM_SECTION = ['Zoom to fit', 'Zoom to selection'];
const PART_MENU = ['Copy Reference', 'Select', 'Isolate', 'Hide others', 'Hide',
  'Expand', 'Collapse', 'Expand all', 'Collapse all', ...ZOOM_SECTION];

test('a revision that fails to build leaves the model before it on screen, and its tree, to work with', async () => {
  const view = await open();
  const { page, pane, errors } = view;
  const parts = async () => (await view.rows()).filter(label => label.startsWith('Select '));
  assert.deepEqual(await parts(), ['Select base', 'Select arm']);
  await pane.getByRole('button', { name: 'Hide arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().hiddenPartIds.join() === 'o1.2');
  // The file saved again, broken: the card says so over the model the view still shows, and the
  // tree lists that model's parts -- not the bare part a file with no build is listed as. (Their
  // features and faces are its build's, which the broken file has none of.)
  await view.fail();
  await pane.getByRole('alert').waitFor();
  assert.deepEqual(await parts(), ['Select base', 'Select arm']);
  assert.deepEqual((await view.state()).hiddenPartIds, ['o1.2'], 'what was hidden stays hidden');
  // Nothing is coming to replace it, so it is not held as a rebuild is: it is picked from, and the
  // view does not read as loading.
  await pane.getByRole('button', { name: 'Select base', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.1');
  assert.equal((await view.state()).loading, false);
  assert.deepEqual(errors, []);
});

test('hiding a part takes it off the screen, and the viewport menus offer what they can do', async () => {
  const view = await open();
  const { page, pane, at, box, errors } = view;
  const opened = await restingFrame(view);
  await pane.getByRole('button', { name: 'Hide arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().hiddenPartIds.join() === 'o1.2');
  const hidden = await view.frame();
  assert.equal(partBoxes(hidden).arm, null, 'a hidden part is off the screen, not merely off a list');
  assert.ok(partBoxes(hidden).base.count > partBoxes(opened).base.count * 0.9, 'and the rest of the model is still drawn');
  await pane.getByRole('button', { name: 'Reveal arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().hiddenPartIds.length === 0);
  const away = () => page.mouse.move(view.box.x + view.box.width - 20, view.box.y + view.box.height - 20);
  await away();
  await frameWhen(view, shot => differing(opened, shot) === 0, 'came back to what hiding the arm took away');
  // Hover runs the other way too: resting on a tree row lights its part. These frames keep the
  // file sidebar on screen and are read to its right: hiding it for a screenshot is the pointer
  // leaving the row, which on a slow (software) renderer lands before the hover is drawn. (The
  // strip at the top centre is hidden: it is not under the pointer.)
  const canvas = pane.locator('[aria-busy] > div > canvas').first();
  const withSidebar = async () => { await settle(page); return PNG.sync.read(await canvas.screenshot({ style: '[data-cad-tool-groups] { visibility: hidden !important; }' })); };
  const [canvasBox, sidebarBox] = [await canvas.boundingBox(), await pane.locator('[data-cad-file-sidebar]').boundingBox()];
  const rest = await withSidebar();
  const rightOfSidebar = { x0: Math.ceil(sidebarBox.x + sidebarBox.width - canvasBox.x) + 4, y0: 0, x1: rest.width, y1: rest.height };
  await pane.getByRole('button', { name: 'Select arm', exact: true }).hover();
  let lit = 0;
  for (let attempt = 0; attempt < 16 && lit <= 2000; attempt += 1) {
    lit = differing(rest, await withSidebar(), rightOfSidebar);
    if (lit <= 2000) await page.waitForTimeout(200);
  }
  assert.ok(lit > 2000, `the drawn frame lit the part under the hovered row: ${lit} pixels changed`);
  await away();
  await frameWhen(view, shot => differing(opened, shot) === 0, 'and let go of it');

  await page.mouse.click(...at([6, 6, 5]), { button: 'right' });
  await page.getByRole('menu').waitFor();
  assert.deepEqual(await page.getByRole('menuitem').allTextContents(), PART_MENU,
    'the node menu: what can be done to the part under the pointer, then the tree');
  await page.keyboard.press('Escape');
  await page.getByRole('menu').waitFor({ state: 'detached' });
  // Empty space (the bottom centre, clear of the cube) asks about the model as a whole. Nothing is hidden here, so besides
  // the framing group all it can offer is the tree.
  await page.mouse.click(box.x + box.width / 2, box.y + box.height - 30, { button: 'right' });
  await page.getByRole('menu').waitFor();
  assert.deepEqual(await page.getByRole('menuitem').allTextContents(), ['Expand all', 'Collapse all', ...ZOOM_SECTION]);
  await page.keyboard.press('Escape');
  await page.getByRole('menu').waitFor({ state: 'detached' });

  // A tree row carries that same menu, item for item; the viewport's belongs to Select alone.
  await pane.getByRole('button', { name: 'Select base', exact: true }).click({ button: 'right' });
  await page.getByRole('menu').waitFor();
  assert.deepEqual(await page.getByRole('menuitem').allTextContents(), PART_MENU);
  await page.keyboard.press('Escape');
  await page.getByRole('menu').waitFor({ state: 'detached' });
  await away();
  for (const tool of ['Measure', 'Annotate']) {
    await view.tool(tool).click();
    // A menu opens in the render the press causes: two frames on, it would be there.
    await page.mouse.click(...at([6, 6, 5]), { button: 'right' });
    await settle(page);
    assert.equal(await page.getByRole('menu').count(), 0, `${tool} opens no viewport menu over a part`);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height - 30, { button: 'right' });
    await settle(page);
    assert.equal(await page.getByRole('menu').count(), 0, `${tool} opens no viewport menu over empty space`);
    // The browser's own menu is still kept off the canvas, and a secondary drag still pans.
    // (The viewer stops the event's propagation as it prevents it, so what it left
    // behind is read from the event itself rather than from a later listener.)
    assert.equal(await page.evaluate(() => {
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
      document.querySelector('[data-testid="one"] [aria-busy] > div > canvas').dispatchEvent(event);
      return event.defaultPrevented;
    }), true, `${tool} still suppresses the native menu`);
    // And a secondary DRAG is still a pan. (Not under Annotate: that tool locks the
    // view on purpose and the editor takes the drag, which its own test asserts.)
    if (tool === 'Annotate') continue;
    const before = await page.evaluate(() => window.__cadCamera().target);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down({ button: 'right' });
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 60, { steps: 8 });
    await page.mouse.up({ button: 'right' });
    await page.waitForFunction(target => window.__cadCamera().target.some((value, index) => Math.abs(value - target[index]) > 1e-3), before,
      { timeout: 5000 });
  }
  // The tree is the sidebar's, under any tool, and acted from it goes back to Select first —
  // Isolate, which has no selection of its own to make.
  assert.deepEqual(await view.tools(), ['Select:false', 'Selection filter: everything:null', 'Annotate:true', 'Measure:false', 'Explode:false', 'Clip:false']);
  assert.equal(await pane.getByRole('button', { name: 'Select arm', exact: true }).isVisible(), true);
  // A menu goes when the camera moves, and the last pan is still coasting: it opens at rest.
  await pane.getByRole('button', { name: 'Select arm', exact: true }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Isolate', exact: true }).click();
  await page.getByRole('menu').waitFor({ state: 'detached' });
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.join() === 'o1.2');
  assert.deepEqual(await view.tools(), ['Select:true', 'Selection filter: everything:null', 'Annotate:false', 'Measure:false', 'Explode:false', 'Clip:false']);
  await page.keyboard.press('Escape');
  assert.deepEqual(errors, []);
});

test('a library picture is the model on its own, on transparency: the grid a person turned on is not in it', async () => {
  const view = await open();
  const { page, errors } = view;
  const picture = () => page.evaluate(async () => {
    const png = await window.cadHarness.a.controller.thumbnail({ width: 240, height: 180 });
    return Array.from(new Uint8Array(await png.arrayBuffer()));
  });
  const bare = await picture();
  assert.equal(PNG.sync.read(Buffer.from(bare)).data[3], 0, 'its corner is transparent');
  await view.display({ grid: true });
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.grid === true);
  assert.deepEqual(await picture(), bare, 'the same picture with the grid up');
  assert.deepEqual(errors, []);
});

test('the context menu\'s Zoom to selection frames the selection', async () => {
  const view = await open();
  const { page, pane, at, errors } = view;
  const menuItem = name => page.getByRole('menuitem', { name, exact: true });
  // Read off the DRAWN frame: how wide the arm is in the pane. The camera eases, so each claim
  // waits for the picture to arrive rather than sleeping.
  const armWidth = image => { const arm = partBoxes(image).arm; return arm ? arm.x1 - arm.x0 : 0; };
  const fitted = armWidth(await frameWhen(view, shot => armWidth(shot) > 0, 'drew the arm'));
  await pane.getByRole('button', { name: 'Select arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.2');
  await page.mouse.click(...at([6, 6, 5]), { button: 'right' });
  await page.getByRole('menu').waitFor();
  assert.equal(await menuItem('Zoom to selection').getAttribute('aria-disabled'), null, 'a selection enables it');
  await menuItem('Zoom to selection').click();
  await page.getByRole('menu').waitFor({ state: 'detached' });
  await frameWhen(view, shot => coverage(shot) > 0.9, 'filled the pane with what was selected');
  // A selected part wears the selection ink, so its own colour only comes back once the
  // selection is dropped — which moves no camera. THEN the arm can be measured, and it
  // is the arm that the camera was put on.
  await page.evaluate(() => window.cadHarness.a.controller.clearSelection());
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 0);
  await frameWhen(view, shot => armWidth(shot) > fitted * 1.3,
    `framed the selected arm rather than the model (${fitted} wide at the model fit)`);
  assert.deepEqual(errors, []);
});

// Each display mode repaints against Solid: Shaded its edges away, Parts its parts' colours, and
// the edge-made modes at least a tenth of the model band. The grid, at least its lines around the model.
const MIN_REDRAWN = { shaded: 1_000, parts: 10_000, xray: 30_000, 'hidden-line': 30_000, wireframe: 30_000, grid: 5_000 };
test('every Display mode, and the grid, reaches the drawn frame, on the live canvas', async () => {
  const view = await open();
  const { page, errors } = view;
  // Display is the mode in hand, chosen from its tile's menu at the strip's end, then the Grid
  // switch. Render is no mode of it: Render is Preview's.
  await view.tool('Display').click();
  const modes = view.displayPanel();
  assert.deepEqual(await modes.locator('[data-display-mode-option]').evaluateAll(items => items.map(item => item.getAttribute('data-display-mode-option'))),
    ['solid', 'shaded', 'parts', 'xray', 'hidden-line', 'wireframe']);
  assert.deepEqual(await modes.getByRole('menuitemcheckbox').allInnerTexts(), ['Grid']);
  await page.keyboard.press('Escape');
  await modes.waitFor({ state: 'detached' });
  const solid = await restingFrame(view);
  await page.evaluate(() => { window.openingCanvas = document.querySelector('[data-testid="one"] [aria-busy] > div > canvas'); });

  // Each mode draws a different picture, and none of them replaces the canvas.
  const frames = { solid };
  for (const [mode, label] of [['shaded', 'Shaded'], ['parts', 'Parts'], ['xray', 'X-ray'], ['hidden-line', 'Hidden line'], ['wireframe', 'Wireframe']]) {
    await view.tool('Display').click();
    const menu = view.displayPanel();
    await menu.locator(`[data-display-mode-option="${mode}"]`).click();
    await menu.waitFor({ state: 'detached' });
    assert.equal(await view.tool('Display').getAttribute('aria-label'), `Display mode: ${label}`);
    await page.waitForFunction(wanted => {
      const state = window.cadHarness.a.controller.readState();
      return state.display.mode === wanted && !state.loading;
    }, mode);
    frames[mode] = await frameWhen(view, shot => differing(solid, shot) > MIN_REDRAWN[mode], `redrew the model for ${label}`);
  }
  // The grid, switched on in Wireframe from the same menu, which stays open; then off again.
  await view.tool('Display').click();
  await view.displayPanel().getByRole('menuitemcheckbox', { name: 'Grid', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.grid === true);
  assert.equal(await view.displayPanel().count(), 1, 'ticking Grid leaves the menu open');
  frames.grid = await frameWhen(view, shot => differing(frames.wireframe, shot) > MIN_REDRAWN.grid, 'drew the grid under Wireframe');
  await page.keyboard.press('Escape');
  await view.display({ grid: false });
  // Each is its own picture, not merely "not Solid".
  for (const [left, right] of [['shaded', 'parts'], ['parts', 'xray'], ['xray', 'hidden-line'], ['xray', 'wireframe']]) {
    assert.ok(differing(frames[left], frames[right]) > 10_000, `${left} and ${right} are different pictures`);
  }
  // Wireframe is all the CAD edges through the model, Hidden line those in sight: the same lines
  // and the obscured ones besides (never the mesh's triangles), so the two differ by those alone.
  assert.ok(differing(frames['hidden-line'], frames.wireframe) > 2_000 && coverage(frames.wireframe) > coverage(frames['hidden-line']),
    `wireframe draws the edges hidden line hides: ${differing(frames['hidden-line'], frames.wireframe)} px, ${coverage(frames.wireframe)} vs ${coverage(frames['hidden-line'])}`);
  assert.ok(coverage(frames['hidden-line']) < 0.1 && coverage(solid) > 0.3,
    `hidden line is linework over the backdrop and Solid is filled: ${coverage(frames['hidden-line'])} vs ${coverage(solid)}`);
  assert.equal(await page.evaluate(() => window.openingCanvas === document.querySelector('[data-testid="one"] [aria-busy] > div > canvas')), true,
    'a preset edits the live canvas; it never replaces it');
  assert.deepEqual(errors, []);
});

test('Position drives the mate and repaints, a named pose jumps, Select\'s knob is never the camera nor a pick, and the grid keeps the size the rest pose gave it', async () => {
  const view = await open();
  const { page, pane, errors } = view;
  // The grid starts off; this compares its lines, so it is turned on.
  await view.display({ grid: true });
  // Neither Position nor the routines are tools: Position's knobs are Select's while its filter picks
  // Position, as it does when the file opens, and the routines are the sidebar's Animation section.
  const strip = await pane.getByRole('group', { name: 'Interaction tools' }).locator('button').evaluateAll(buttons => buttons
    .filter(button => !button.closest('[data-view-controls]')).map(button => button.getAttribute('aria-label')));
  assert.deepEqual([strip.includes('Animation'), strip.includes('Position')], [false, false]);
  // Position's controls are the file sidebar's, whatever the tool, and add no panel to the stack.
  const panel = pane.getByRole('region', { name: 'Position controls', exact: true });
  assert.deepEqual([await view.sidebar(), await view.stack()], [['Model tree', 'Position controls', 'Animation'], []]);
  await view.openSection('Position');
  assert.deepEqual(await panel.getByRole('heading').allInnerTexts(), ['Position'], 'headed Position');
  const slider = page.getByLabel('hinge slider value', { exact: true });
  const preset = panel.locator('[data-pose-menu]');
  // ONE section: its heading holds Reset beside its name; its body the Pose menu, a full-width row,
  // then the joint. The pose and the joints are no sections of their own.
  assert.equal(await panel.locator('[data-tool-panel-body] [data-pose-row] [data-pose-menu]').count(), 1);
  assert.equal(await panel.locator('[data-sidebar-head]').getByRole('button', { name: 'Reset position', exact: true }).isDisabled(), true, 'Reset, idle at the default pose');
  for (const heading of ['Pose', 'Joints', 'Kinematics']) {
    assert.equal(await panel.getByRole('heading', { name: heading, exact: true }).count(), 0, `no ${heading} heading inside Position`);
  }
  // A section, as the tree is: its content's height, no cap, scroller or grip of its own.
  const positionFit = await panel.evaluate(node => ({ cap: node.style.maxHeight,
    scrolls: node.querySelector('[data-tool-panel-body]').scrollHeight > node.querySelector('[data-tool-panel-body]').clientHeight }));
  assert.deepEqual(positionFit, { cap: '', scrolls: false });
  assert.equal(await pane.getByRole('separator', { name: 'Resize position controls', exact: true }).count(), 0);
  // A compact value field: 24px tall and about five characters wide.
  const field = await slider.boundingBox();
  assert.ok(field.height <= 24 && field.width <= 60, `a compact value field: ${JSON.stringify(field)}`);
  assert.equal((await preset.innerText()).trim(), 'Default');
  assert.equal(await slider.inputValue(), '0.00°');

  await page.mouse.move(view.box.x + view.box.width - 20, view.box.y + view.box.height - 20);
  const rest = await restingFrame(view);
  const restArm = (await translations(page))['o1.2'];
  await slider.fill('60');
  await slider.press('Enter');
  await page.waitForFunction(() => Math.abs(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[13]) > 1);
  // The DRAWN frame moved, not just the matrix: a pose that never asks for a
  // repaint leaves the viewport sitting on the picture before it.
  const posed = await frameWhen(view, shot => differing(rest, shot) > 10_000, 'repainted for the mate the slider drove');

  // The grid runs out past the model and is sized from the REST pose, so
  // swinging the arm cannot rescale it. (The Render studio's floor is held to
  // the same rule under Preview's playing routine, the one motion Preview has.)
  const guides = { x0: 0, x1: Math.floor(rest.width * 0.08) };
  assert.ok(painted(rest, guides) > 500, `the compared strip holds grid lines: ${painted(rest, guides)}`);
  assert.equal(differing(rest, posed, guides), 0, 'the guides beside the model are untouched by a pose');

  // A named pose is a full configuration, applied as a jump.
  await preset.click();
  await page.locator('[role=menu][aria-label="Pose"]').getByRole('menuitemradio', { name: 'open', exact: true }).click();
  await page.waitForFunction(() => /^90(\.0+)?°$/.test(document.querySelector('input[aria-label="hinge slider value"]').value));
  assert.equal((await preset.innerText()).trim(), 'open');
  // Default is the way back.
  await preset.click();
  await page.locator('[role=menu][aria-label="Pose"]').getByRole('menuitemradio', { name: 'Default', exact: true }).click();
  await page.waitForFunction(() => /^0(\.0+)?°$/.test(document.querySelector('input[aria-label="hinge slider value"]').value));
  await page.waitForFunction(rest => JSON.stringify(Array.from(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix.slice(12, 15))) === JSON.stringify(rest), restArm)
    .catch(() => {});
  assert.deepEqual((await translations(page))['o1.2'], restArm, 'Reset puts the mate back where it started');
  await page.mouse.move(view.box.x + view.box.width - 20, view.box.y + view.box.height - 20);
  await frameWhen(view, shot => differing(rest, shot) === 0, 'came back to the rest pose after Reset');

  // Select's knob: one, on the mate's axis, and dragging it is never the camera, nor a pick.
  await page.waitForFunction(() => window.__cadJointHandles().length === 1);
  const [knob] = await page.evaluate(() => window.__cadJointHandles());
  assert.equal(knob.id, 'hinge');
  const pivot = view.at([10, 0, 0]);
  assert.ok(Math.hypot(view.box.x + knob.pivotX - pivot[0], view.box.y + knob.pivotY - pivot[1]) < 4,
    `the knob's pivot is the mate's axis on screen: ${JSON.stringify([knob.pivotX, knob.pivotY])} vs ${JSON.stringify(pivot)}`);
  const camera = await page.evaluate(() => window.__cadCamera());
  // `travel` is the arc the knob may be dragged along, from limit to limit, so
  // following it is a drag toward a value rather than a guess at which way the
  // mate's axis turns on screen.
  assert.ok(knob.travel.length > 8, 'a revolute knob carries its arc');
  await page.mouse.move(view.box.x + knob.x, view.box.y + knob.y);
  await page.mouse.down();
  for (const [x, y] of knob.travel.slice(1, 9)) {
    await page.mouse.move(view.box.x + x, view.box.y + y);
    await settle(page);
  }
  await page.waitForFunction(() => window.__cadJointHandles()[0].value > 15);
  const held = (await page.evaluate(() => window.__cadJointHandles()))[0].value;
  await page.mouse.up();
  await page.waitForTimeout(300);
  assert.equal((await page.evaluate(() => window.__cadJointHandles()))[0].value, held, 'nothing eases behind the drag');
  const after = await page.evaluate(() => window.__cadCamera());
  for (const key of ['position', 'target']) {
    after[key].forEach((value, index) => assert.ok(Math.abs(value - camera[key][index]) < 1e-9, `a knob drag never moves the camera: ${key}[${index}]`));
  }
  await frameWhen(view, shot => differing(rest, shot) > 10_000, 'showed the pose the knob dragged to');
  assert.equal(Number.parseFloat(await slider.inputValue()), Math.round(held * 10) / 10, 'the Position slider follows the knob');
  const picked = async () => (({ selectedPartIds, selectedReferenceIds, isolatedPartIds }) => [selectedPartIds, selectedReferenceIds, isolatedPartIds])(await view.state());
  assert.deepEqual(await picked(), [[], [], []], 'a press on the knob picks nothing under it');
  // Two quick presses on it are the knob's too, never a double-click on the part under it.
  const [dragged] = await page.evaluate(() => window.__cadJointHandles());
  await page.mouse.dblclick(view.box.x + dragged.x, view.box.y + dragged.y);
  await settle(page);
  assert.deepEqual(await picked(), [[], [], []], 'a double-click on the knob isolates nothing');
  // With Position unticked from the filter the knob goes; ticked again it is back.
  await view.setFilter({ position: false });
  await page.waitForFunction(() => window.__cadJointHandles().length === 0);
  await view.setFilter({ position: true });
  await page.waitForFunction(() => window.__cadJointHandles().length === 1);
  assert.deepEqual(errors, []);
});

test("Preview is a still Render showcase: the navbar holds its settings (Orbit, Render's own) and the way out, its playbar plays and pauses the routine without moving the camera or the floor, and leaving restores the pose, the camera and the file's mode", async () => {
  const view = await open();
  const { page, pane, errors } = view;
  // A camera of the person's own, which Preview's must never overwrite.
  await page.evaluate(() => window.cadHarness.a.controller.setCamera({ ...window.cadHarness.a.controller.readState().camera, zoom: 1.6, target: [4, 5, 2] }));
  await restingCamera(page);
  const saved = (await view.state()).camera;
  // The pointer rests on the backdrop: zoomed in, the model runs under the bottom-left corner.
  const away = () => page.mouse.move(view.box.x + view.box.width - 20, view.box.y + view.box.height - 20);
  await away();
  const toolsRest = await restingFrame(view);
  const restArm = (await translations(page))['o1.2'];
  // The routine is no tool: it is the sidebar's Animation section.
  assert.equal(await view.tool('Animation').count(), 0);
  await view.enterPreview();
  // The navbar stays (the way to other files), its view controls now Preview's own: its
  // settings, then the way out; nothing of them stands over the view.
  assert.deepEqual(await pane.locator('[data-viewer-navbar] [data-view-controls] button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label'))),
    ['Preview settings', 'Exit preview']);
  assert.equal(await pane.locator('[data-preview-corner]').count(), 0);
  // The file is in Solid; Preview draws it in Render, on the studio's floor, and still. Its
  // settings are put away as it opens.
  await page.waitForFunction(() => window.__cadStage()?.studioGround, null, { timeout: 10000 });
  assert.equal((await view.state()).display.mode, 'solid', 'the file keeps its own mode');
  assert.equal(await pane.getByRole('region', { name: 'Preview settings' }).count(), 0);
  // The tools and the file sidebar are put away; the routine is its playbar's, centred under the model.
  assert.equal(await pane.getByRole('group', { name: 'Interaction tools' }).isVisible(), false);
  assert.equal(await pane.locator('[data-file-sidebar-room]').isHidden(), true, 'no file sidebar in Preview');
  const bar = view.playbar;
  await bar.waitFor();
  const barBox = await bar.boundingBox();
  assert.ok(Math.abs(barBox.x + barBox.width / 2 - (view.box.x + view.box.width / 2)) <= 1 && barBox.y > view.box.y + view.box.height / 2,
    `the playbar is centred under the model: ${JSON.stringify({ barBox, view: view.box })}`);
  // Autoplay is off by default: entered, the routine waits, at rest.
  await bar.getByRole('button', { name: 'Play animation', exact: true }).waitFor();
  await page.waitForTimeout(300);
  assert.deepEqual((await translations(page))['o1.2'], restArm, 'nothing plays until its play button is pressed');
  // Render's settings are Preview's: the file's own, an edit there drawn in Preview.
  await restingCamera(page);
  const floored = await restingFrame(view);
  await pane.getByRole('button', { name: 'Preview settings', exact: true }).click();
  const settingsPanel = pane.getByRole('region', { name: 'Preview settings' });
  const floor = settingsPanel.getByRole('checkbox', { name: 'Floor', exact: true });
  await floor.click();
  await frameWhen(view, shot => differing(floored, shot) > 100, 'drew Preview without its floor');
  // The display is untouched: Preview's settings are its own.
  assert.equal(JSON.stringify((await view.state()).display).includes('floor'), false);
  await floor.click();
  await settingsPanel.getByRole('button', { name: 'Close preview settings', exact: true }).click();
  await settingsPanel.waitFor({ state: 'detached' });
  await page.waitForFunction(() => window.__cadStage()?.studioGround, null, { timeout: 10000 });
  await restingCamera(page);
  const rest = await restingFrame(view);
  // The playbar: Play, the scrubber and its Playback settings (one routine has no list of
  // routines), which open up from their button.
  assert.deepEqual(await bar.getByRole('button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label'))),
    ['Play animation', 'Playback settings']);
  assert.equal(await bar.getByRole('slider', { name: 'Animation time', exact: true }).count(), 1);
  assert.equal(await pane.getByRole('button', { name: 'Quick Edit' }).count(), 0);
  const settingsButton = bar.getByRole('button', { name: 'Playback settings', exact: true });
  await settingsButton.click();
  const settingsMenu = page.getByRole('menu', { name: 'Playback settings', exact: true });
  assert.deepEqual(await settingsMenu.getByRole('menuitemcheckbox').allInnerTexts(), ['Loop', 'Autoplay']);
  const [menuBox, buttonBox] = await Promise.all([settingsMenu.boundingBox(), settingsButton.boundingBox()]);
  assert.ok(menuBox.y + menuBox.height <= buttonBox.y, 'opening up from its button');
  await page.keyboard.press('Escape');
  await settingsMenu.waitFor({ state: 'detached' });

  // Play and Pause, the camera and the floor still under the routine.
  const still = await page.evaluate(() => ({ camera: window.__cadCamera(), stage: window.__cadStage() }));
  await bar.getByRole('button', { name: 'Play animation' }).click();
  await page.waitForFunction(() => window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[1] > 0.2);
  await frameWhen(view, shot => differing(rest, shot) > 10_000, 'showed the playing routine');
  // The studio's floor is sized and centred from the REST placement, as the grid is: the box the
  // routine swings the arm through is not the floor's.
  await page.waitForFunction(rest => JSON.stringify(window.__cadStage()?.bounds) !== rest, JSON.stringify(still.stage.bounds));
  const playing = await page.evaluate(() => ({ camera: window.__cadCamera(), stage: window.__cadStage() }));
  for (const key of ['position', 'target', 'zoom']) {
    const actual = [].concat(playing.camera[key]), expected = [].concat(still.camera[key]);
    assert.ok(actual.every((value, index) => Math.abs(value - expected[index]) < 1e-8), `the routine never moves the camera: ${key}`);
  }
  assert.deepEqual(playing.stage.studioGround, still.stage.studioGround, 'nor the studio floor');
  await bar.getByRole('button', { name: 'Pause animation' }).click();
  assert.equal(await bar.getByRole('button', { name: 'Play animation', exact: true }).isVisible(), true);
  await bar.getByRole('button', { name: 'Play animation' }).click();
  assert.equal(await bar.getByRole('button', { name: 'Pause animation', exact: true }).isVisible(), true);
  // Orbit, in its settings, starts the camera turning.
  const orbitFrom = await page.evaluate(() => window.__cadCamera().position);
  await pane.getByRole('button', { name: 'Preview settings', exact: true }).click();
  const orbit = settingsPanel.getByRole('checkbox', { name: 'Orbit', exact: true });
  assert.equal(await orbit.getAttribute('aria-checked'), 'false', 'Preview opens still');
  await orbit.click();
  await page.waitForFunction(previous => window.__cadCamera().position.some((value, index) => Math.abs(value - previous[index]) > 1e-3), orbitFrom);
  await orbit.click();

  // Leaving Preview releases its routine, playing or not: the model goes back to the pose it
  // was in, in the tools view's own camera and its own mode, to the pixel.
  await view.exitPreview();
  await page.waitForFunction(() => !window.__cadStage()?.studioGround, null, { timeout: 10000 });
  await page.waitForFunction(rest => JSON.stringify(Array.from(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix.slice(12, 15))) === JSON.stringify(rest), restArm)
    .catch(() => {});
  assert.deepEqual((await translations(page))['o1.2'], restArm);
  const restored = (await view.state()).camera;
  for (const key of ['position', 'target', 'up']) saved[key].forEach((value, index) => assert.ok(Math.abs(value - restored[key][index]) < 1e-6, `the tools view's camera comes back: ${key}`));
  assert.equal(restored.zoom, saved.zoom);
  await away();
  // The pose is back exactly (above); the frame within the few edge pixels a Render pass leaves
  // shaded a level or two differently, as a Render round trip in the tools view does too.
  await frameWhen(view, shot => differing(toolsRest, shot) < 200, 'came back to the rest pose');
  assert.deepEqual(errors, []);
});

test('Preview and the tools view are two states: Preview draws the model as authored, and leaving it drops what was done there and gives the tools view back as it was', async () => {
  const view = await open();
  const { page, pane, errors } = view;
  const away = () => page.mouse.move(view.box.x + view.box.width - 20, view.box.y + 100);
  const arm = async () => (await translations(page))['o1.2'];
  const armAt = expected => page.waitForFunction(at => JSON.stringify(Array.from(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix.slice(12, 15))) === JSON.stringify(at), expected)
    .catch(() => {});
  const restArm = await arm();
  // The model as Preview draws a file opened afresh: the picture every later visit draws too,
  // whatever the tools view holds.
  await away();
  await view.enterPreview();
  const authored = await restingFrame(view);
  await view.exitPreview();

  // Work in the tools view: the arm swung on Position's slider, the base hidden, the arm picked, the
  // model in Wireframe, and a camera of the person's own. (Clip is a motion, as the pose is: it
  // would put the pose back. It is the second round's, below.)
  await view.openSection('Position');
  const slider = page.getByLabel('hinge slider value', { exact: true });
  await slider.fill('60');
  await slider.press('Enter');
  await page.waitForFunction(() => Math.abs(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[13]) > 1);
  const posedArm = await arm();
  await view.openSection('Model tree');
  await pane.getByRole('button', { name: 'Hide base', exact: true }).click();
  await pane.getByRole('button', { name: 'Select arm', exact: true }).click();
  await view.display({ mode: 'wireframe' });
  await page.evaluate(() => window.cadHarness.a.controller.setCamera({ ...window.cadHarness.a.controller.readState().camera, zoom: 1.4, target: [3, 4, 2] }));
  await page.waitForFunction(() => {
    const state = window.cadHarness.a.controller.readState();
    return state.hiddenPartIds.join() === 'o1.1' && state.selectedPartIds.join() === 'o1.2' && state.display.mode === 'wireframe';
  });
  assert.deepEqual(await arm(), posedArm, 'still posed');
  await restingCamera(page);
  const work = await view.state();

  // Preview draws none of it: the arm at rest, the base there, nothing picked, in Render.
  await away();
  await view.enterPreview();
  await armAt(restArm);
  assert.deepEqual(await arm(), restArm, 'Preview poses the model at rest');
  const shown = await frameWhen(view, shot => differing(authored, shot) === 0, 'drew the model as authored');
  assert.ok(partBoxes(shown).base && partBoxes(shown).arm, 'both parts are drawn');

  // What is done in Preview is Preview's: its routine played from its playbar, its camera turned.
  await view.playbar.getByRole('button', { name: 'Play animation' }).click();
  await page.waitForFunction(() => window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[1] > 0.2);
  const orbit = await page.evaluate(() => window.__cadCamera().position);
  await page.mouse.move(view.box.x + view.box.width / 2, view.box.y + view.box.height / 2);
  await page.mouse.down();
  await page.mouse.move(view.box.x + view.box.width / 2 + 90, view.box.y + view.box.height / 2 + 20, { steps: 5 });
  await page.mouse.up();
  await page.waitForFunction(previous => window.__cadCamera().position.some((value, index) => Math.abs(value - previous[index]) > 1e-3), orbit);

  // Leaving drops it, and gives the tools view back as it was left: the pose, the hidden base, the
  // pick, the mode and its camera.
  await view.exitPreview();
  await armAt(posedArm);
  assert.deepEqual(await arm(), posedArm, 'the pose comes back');
  const back = await view.state();
  assert.deepEqual([back.hiddenPartIds, back.selectedPartIds, back.display.mode], [work.hiddenPartIds, work.selectedPartIds, 'wireframe']);
  for (const key of ['position', 'target', 'up']) work.camera[key].forEach((value, index) => assert.ok(Math.abs(value - back.camera[key][index]) < 1e-6, `the tools view's camera comes back: ${key}`));
  assert.equal(back.camera.zoom, work.camera.zoom);
  assert.match(await slider.inputValue(), /^60(\.0+)?°$/);

  // An isolated part and a clip are the tools view's too: Preview draws the whole model, uncut, and
  // leaving finds the part isolated and the model clipped.
  await view.tool('Select').click();
  await view.openSection('Model tree');
  await pane.getByRole('button', { name: 'Reveal base', exact: true }).click();
  await pane.getByRole('button', { name: 'Select arm', exact: true }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Isolate', exact: true }).click();
  await page.getByRole('menu').waitFor({ state: 'detached' });
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.join() === 'o1.2');
  await view.display({ clip: { enabled: true, axis: 'z', invert: false } });
  const clipped = (await view.state()).display.clip;
  await away();
  await view.enterPreview();
  await frameWhen(view, shot => differing(authored, shot) === 0, 'drew the whole model, as authored');
  await view.exitPreview();
  assert.deepEqual([(await view.state()).isolatedPartIds, (await view.state()).display.clip], [['o1.2'], clipped]);
  assert.deepEqual(errors, []);
});

test('one motion at a time: Explode, Clip, Position and the routine replace each other, the one SET off its default putting the others back at rest at once, a tool taken up or a control pressed changing nothing; no knobs over an explosion; a dot on each tile off its default', async () => {
  const view = await open();
  const { page, pane, errors } = view;
  const exploded = () => page.evaluate(() => window.cadHarness.a.controller.readState().display.exploded.enabled === true);
  const clipped = () => page.evaluate(() => window.cadHarness.a.controller.readState().display.clip.enabled === true);
  // A pose off its default or not: what the sidebar's Position section says, whatever the tool.
  const poseReads = text => page.waitForFunction(value => document.querySelector('section[aria-label="Position controls"] [data-pose-menu]')?.textContent.trim() === value, text);
  // Which tiles carry the dot of a value off its default: the strip's tools and the sidebar's sections.
  const dotted = () => pane.locator('[data-cad-toolbar] button:has([data-tool-changed]), [data-file-sidebar-tools] button:has([data-tool-changed])')
    .evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label')));
  const dots = expected => page.waitForFunction(want => JSON.stringify([...document.querySelectorAll('[data-testid="one"] :is([data-cad-toolbar], [data-file-sidebar-tools]) button:has([data-tool-changed])')]
    .map(button => button.getAttribute('aria-label'))) === JSON.stringify(want), expected).catch(async () => assert.deepEqual(await dotted(), expected));
  const slider = page.getByLabel('hinge slider value', { exact: true });
  const pose = async value => {
    await slider.fill(String(value));
    await slider.press('Enter');
  };
  const amount = () => pane.getByRole('slider', { name: 'Explode amount' });
  const explode = async () => {
    await view.tool('Explode').click();
    await amount().press('End');
    await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.exploded.enabled === true);
    await view.tool('Select').click();
  };
  await dots([]);
  // A pose, kept: Select, another tool, leaves it. Position's tile says it is off its default.
  await view.openSection('Position');
  await pose(60);
  await poseReads('Custom');
  await dots(['Position']);
  assert.deepEqual(await view.stack(), []);
  // Explode taken up changes nothing: the pose stays until its amount moves, and then goes back at once.
  await view.tool('Explode').click();
  await amount().waitFor();
  await settle(page);
  await poseReads('Custom');
  await amount().press('End');
  await poseReads('Default');
  assert.equal(await exploded(), true);
  await view.tool('Select').click();
  // An explosion, kept: its panel goes with the tool, the parts stay apart, and its tile has the dot.
  assert.deepEqual([await view.stack(), await exploded()], [[], true]);
  await dots(['Explode']);
  // At rest, Select draws Position's knob; exploded, the parts are not where it would stand, so it
  // draws none until the explosion is gone.
  await page.waitForFunction(() => window.__cadJointHandles?.().length === 0);
  // Position reached for — its section's slider pressed — changes nothing.
  await slider.click();
  await settle(page);
  assert.deepEqual([await exploded(), await page.evaluate(() => window.__cadJointHandles().length)], [true, 0]);
  // Position SET takes Explode off at once, and the knob is back.
  await pose(30);
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.exploded.enabled === false);
  await poseReads('Custom');
  await page.waitForFunction(() => window.__cadJointHandles?.().length === 1);
  await dots(['Position']);
  // Explode used puts the pose back to its default.
  await explode();
  await poseReads('Default');
  // Clip set takes Explode off; and Position used takes Clip off.
  await view.display({ clip: { enabled: true, axis: 'z', invert: false } });
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.exploded.enabled === false);
  await dots(['Clip']);
  await pose(20);
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.clip.enabled === false);
  await poseReads('Custom');
  // The routine played puts the pose's joints back to their defaults (the routine then moves the
  // model); and Clip set rests the routine.
  await view.openSection('Animation');
  await view.animation.getByRole('button', { name: 'Play animation', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[data-testid="one"] input[aria-label="hinge slider value"]')?.value === '0.00°');
  await page.waitForFunction(() => window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[1] > 0.2);
  await view.animation.getByRole('button', { name: 'Pause animation', exact: true }).click();
  await dots(['Animation']);
  assert.equal(await view.animation.getByRole('button', { name: 'Reset animation', exact: true }).isDisabled(), false, 'a frame left on the model');
  await view.display({ clip: { enabled: true, axis: 'z', invert: false } });
  await page.waitForFunction(() => document.querySelector('[data-testid="one"] section[aria-label="Animation"] [aria-label="Reset animation"]')?.disabled === true);
  assert.deepEqual([await clipped(), await exploded()], [true, false]);
  await dots(['Clip']);
  assert.deepEqual(await view.stack(), []);
  assert.deepEqual(errors, []);
});

test("the routine's Speed and Loop are the file's: chosen in the tools view's Animation section, kept in Preview's playbar; and Preview opens still every time, Orbit in its settings starting the camera", async () => {
  const view = await open();
  const { page, pane, errors } = view;
  // Playback settings: the Animation section's in the tools view, the playbar's in Preview.
  let settingsButton = view.animation.getByRole('button', { name: 'Playback settings' });
  const inPreview = () => { settingsButton = view.playbar.getByRole('button', { name: 'Playback settings' }); };
  // The menu's Speed and Loop, as it shows them.
  const settings = async () => {
    await settingsButton.click();
    const menu = page.getByRole('menu', { name: 'Playback settings', exact: true });
    const read = [await menu.getByRole('menuitem', { name: /^Animation speed: / }).getAttribute('aria-label'),
      await menu.getByRole('menuitemcheckbox', { name: 'Loop', exact: true }).getAttribute('aria-checked')];
    await page.keyboard.press('Escape');
    await menu.waitFor({ state: 'detached' });
    return read;
  };
  // Chooses a Speed, and turns Loop over. By keyboard: a menu item still easing in under a loaded
  // software renderer never reads as stable under the pointer.
  const choose = async speed => {
    const menu = page.getByRole('menu', { name: 'Playback settings', exact: true });
    await settingsButton.click();
    await menu.getByRole('menuitem', { name: /^Animation speed: / }).click();
    await page.getByRole('menuitemradio', { name: `${speed}×`, exact: true }).press('Enter');
    await menu.waitFor({ state: 'detached' });
    await settingsButton.click();
    await menu.getByRole('menuitemcheckbox', { name: 'Loop', exact: true }).press('Enter');
    await page.keyboard.press('Escape');
    await menu.waitFor({ state: 'detached' });
  };
  const orbit = pane.getByRole('region', { name: 'Preview settings' }).getByRole('checkbox', { name: 'Orbit', exact: true });
  const previewSettings = () => pane.getByRole('button', { name: 'Preview settings', exact: true }).click();
  await view.openSection('Animation');
  assert.deepEqual(await settings(), ['Animation speed: 1×', 'true'], 'the routine\'s own Speed and Loop');
  await choose(2);
  assert.deepEqual(await settings(), ['Animation speed: 2×', 'false']);
  await view.enterPreview();
  inPreview();
  assert.deepEqual(await settings(), ['Animation speed: 2×', 'false'], 'the file\'s Speed and Loop, in Preview too');
  // Orbit, in its settings, starts the camera turning.
  await previewSettings();
  assert.equal(await orbit.getAttribute('aria-checked'), 'false', 'Preview opens still');
  const still = await page.evaluate(() => window.__cadCamera().position);
  await orbit.click();
  await page.waitForFunction(start => window.__cadCamera().position.some((value, axis) => Math.abs(value - start[axis]) > 1e-6), still);
  await view.exitPreview();

  // The next visit keeps the Speed and Loop chosen, and opens still again.
  await view.enterPreview();
  await previewSettings();
  assert.equal(await orbit.getAttribute('aria-checked'), 'false', 'still again');
  assert.deepEqual(await settings(), ['Animation speed: 2×', 'false'], 'the file\'s Speed and Loop');
  await view.exitPreview();
  assert.deepEqual(errors, []);
});

test('a pose pass React re-runs while a routine plays draws the clock, never the time playback started from', async () => {
  // The pose pass has two callers: the clock per playing tick, and React whenever something the
  // pass reads changes (a detail swap, a progressive publish, a display change). React's copy of
  // the time is where playback STARTED, so a re-run mid-play used to put the model back there for
  // a frame: on a routine that starts at rest, a flash of the rest pose on every re-run.
  const view = await open();
  const { page, pane, errors } = view;
  await view.enterPreview();
  await view.playbar.getByRole('button', { name: 'Play animation' }).click();
  await page.waitForFunction(() => window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[1] > 0.2);
  // Hold the clock where it is: animation frames are queued, not run, so no tick can repaint the
  // pose over whatever React's pass draws. The pass itself is not a frame: a display change
  // reaches it through a task (`afterViewPaint`'s fallback), with frames held.
  const [ticked, rerun] = await page.evaluate(async () => {
    const arm = () => Array.from(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix);
    window.__heldFrames = [];
    window.__releaseFrames = window.requestAnimationFrame;
    window.requestAnimationFrame = callback => { window.__heldFrames.push(callback); return 0; };
    // The tick already queued through the real rAF still runs, in the next frame, and it poses
    // the model synchronously. Wait for that frame, not for a time: on a software-WebGL runner it
    // can land after any fixed wait, and then its tick moves the arm mid-test. A callback asked
    // of the real rAF now runs in that same frame, after the tick; the tick's own next request is
    // held.
    await new Promise(resolve => window.__releaseFrames.call(window, resolve));
    const beforeRerun = arm();
    const grid = window.cadHarness.a.controller.readState().display.grid === true;
    window.cadHarness.a.controller.setDisplaySettings({ grid: !grid });
    await new Promise(resolve => setTimeout(resolve, 600));
    return [beforeRerun, arm()];
  });
  await page.evaluate(() => {
    window.requestAnimationFrame = window.__releaseFrames;
    for (const callback of window.__heldFrames.splice(0)) window.requestAnimationFrame(callback);
  });
  assert.ok(ticked[1] > 0.2, 'the routine had turned the arm away from its start');
  ticked.forEach((value, index) => assert.ok(Math.abs(value - rerun[index]) < 1e-9,
    `React's pass drew the routine where the clock is, not where it started: ${ticked} != ${rerun}`));
  await view.exitPreview();
  assert.deepEqual(errors, []);
});

test('Measure reads a distance between two picks', async () => {
  const view = await open();
  const { page, pane, at, errors } = view;
  // Measure snaps onto exact topology, which arrives with the tree's frontier.
  await view.partMenu('base', 'Expand');
  await view.partMenu('arm', 'Expand');
  await view.tool('Measure').click();
  // It has no panel: what it takes is Quick Edit's, a chip each.
  assert.deepEqual(await view.stack(), []);
  // Measure says what the pointer does over the model: a crosshair, not Select's hand.
  await page.mouse.move(...at([0, 0, 5]));
  await view.waitCursor('crosshair');
  const chip = pane.locator('[data-quick-edit-ref^="measure-"]');
  assert.equal(await chip.count(), 0, 'no results until something is measured');
  await measurePoints(page, at, [0, 0, 5], [15, 0, 4]);
  await chip.waitFor();
  assert.match(await chip.innerText(), /\d+\.\d+ mm/, 'its chip reads a length');
  assert.equal(await chip.count(), 1, 'one ruler');
  // Its X deletes it, and Quick Edit, with nothing left to carry, goes with it.
  await chip.getByRole('button', { name: /^Remove Measurement 1: / }).click();
  await chip.waitFor({ state: 'detached' });
  await view.quickEdit().waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
});

// A STEP is published in PIECES, and each piece lands in a scene the viewport already
// holds: same object, same identity, more in it. The only thing that tells the viewport
// so is `viewport.commitScene()` from the scene sync, and what the viewport sizes from what
// is PLACED — the depth range and the floor's height — is re-read THEN. What it sizes from
// the model's REST box — the framing, the zoom ruler and the grid — was final at the first
// publish: the descriptor declares the whole model's box (`bbox`), so the camera does not
// move while the rest of the model arrives (the owner's report: "the model position jumps
// around a bit as it is rendering").
//
// The committed two-component fixture cannot show this, and neither can any package
// whose second publish is its LAST: the end of a load changes what the viewport is
// mounted with, so it re-adopts the scene for reasons of its own and a deleted commit
// costs nothing. `stageProgressiveFixture` serves the same two shapes as twenty-five
// components, held one batch at a time, so the MIDDLE publish is an in-place change
// with nothing else moving — and it is the one that brings the base.
test('a package that arrives in pieces is framed once, on the box it declares; a publish in the middle of the load re-fits only its depth range and floor', async (t) => {
  const staged = [];
  const staggered = await serveStepHarness({ after: cleanup => staged.push(cleanup) }, { progressive: true });
  t.after(async () => { for (const cleanup of staged.reverse()) await cleanup(); });
  const { page, errors, pane } = await staggered.open({ timeout: 60000 });
  await pane.locator('[aria-busy] > div > canvas').first().waitFor();
  const read = async () => ({ stage: await page.evaluate(() => window.__cadStage()), camera: await page.evaluate(() => window.__cadCamera()) });
  const span = bounds => [0, 1, 2].map(axis => Math.round(bounds.max[axis] - bounds.min[axis]));
  const publishes = () => page.evaluate(() => [window.__cadMeshCost.publishCount, window.__cadMeshCost.loadedComponents, window.__cadMeshCost.final]);
  // The view a publish must not move: where the camera stands and looks, its zoom and frustum, and the grid.
  const sameView = (from, to, what) => {
    for (const key of ['position', 'target', 'up']) from.camera[key].forEach((value, index) => assert.ok(Math.abs(value - to.camera[key][index]) < 1e-6,
      `${what}: camera ${key}[${index}] held (${value} -> ${to.camera[key][index]})`));
    assert.deepEqual([to.camera.zoom, to.camera.halfHeight, to.stage.gridRadius], [from.camera.zoom, from.camera.halfHeight, from.stage.gridRadius],
      `${what}: the zoom, the frustum and the grid held`);
  };

  // BATCH ONE: eight arms, all at the origin, so what is placed is one arm's box whichever
  // eight of them got there first. The rest of the package is still downloading.
  await page.waitForFunction(() => window.__cadMeshCost?.loadedComponents === 8, null, { timeout: 60000 });
  await page.waitForFunction(() => window.__cadStage?.()?.bounds);
  await restingCamera(page);
  const first = await read();
  const firstFrame = await frame(pane);
  assert.deepEqual(await publishes(), [1, 8, false], 'one publish, and the load is not over');
  assert.deepEqual(span(first.stage.bounds), [10, 8, 8], 'the arm, and nothing else, is placed');
  assert.deepEqual(span(first.camera.originalBounds), [20, 20, 10], "but the camera is framed on the whole model's declared box");

  // BATCH TWO, in the MIDDLE of the load: sixteen more components, one of them the base.
  // Nothing else about the viewport changed — same scene, same loading state, same camera
  // request — so every one of these follows from the commit and from nothing else.
  staggered.release('a');
  await page.waitForFunction(() => window.__cadMeshCost?.loadedComponents === 24, null, { timeout: 60000 });
  await page.waitForFunction(width => Math.round(window.__cadStage().bounds.max[0] - window.__cadStage().bounds.min[0]) > width, 10);
  const middle = await read();
  const middleFrame = await frame(pane);
  assert.deepEqual(await publishes(), [2, 24, false], 'a second publish, and STILL not the end of the load');
  assert.deepEqual(span(middle.stage.bounds), [20, 20, 10], 'the base is in the box the stage is fitted to');
  assert.ok(middle.stage.floorZ < first.stage.floorZ,
    `the floor dropped to the model's new underside (${first.stage.floorZ} -> ${middle.stage.floorZ})`);
  assert.ok(middle.camera.far > first.camera.far,
    `the depth range was fitted again (far ${first.camera.far} -> ${middle.camera.far})`);
  sameView(first, middle, 'the second publish');
  // On the DRAWN frame: the base's own authored blue fills a frame it was not in.
  const before = partBoxes(firstFrame), after = partBoxes(middleFrame);
  assert.ok(after.base.count > (before.base?.count || 0) * 5,
    `the base is drawn (${before.base?.count || 0} -> ${after.base.count} pixels of its colour)`);
  assert.ok(differing(firstFrame, middleFrame) > 10_000, 'the picture changed');

  // THE LAST COMPONENT is one more arm on top of the others: the scene is whole, and the
  // camera that framed it whole from the start has nothing to do.
  staggered.release('b');
  await page.waitForFunction(() => window.__cadMeshCost?.final === true, null, { timeout: 60000 });
  await page.waitForFunction(() => window.cadHarness.a.controller?.readState().loading === false, null, { timeout: 60000 });
  await restingCamera(page);
  const whole = await read();
  assert.deepEqual(span(whole.stage.bounds), span(middle.stage.bounds), 'the box it was already fitted to');
  sameView(first, whole, 'the last publish');

  // A descriptor that declares no box is framed on its first batch and once more when it is
  // whole, but that second framing is for a camera NOBODY set: the camera the person set, kept
  // with the tab, is restored through every publish and the completion.
  await page.evaluate(() => window.cadHarness.a.controller.setCamera({
    ...window.cadHarness.a.controller.readState().camera, position: [90, -30, 38], target: [4, 1, 0], zoom: 1.6 }));
  await restingCamera(page);
  const chosen = await page.evaluate(() => window.__cadCamera());
  const chosenFrame = await restingFrame({ page, frame: () => frame(pane) });
  assert.ok(chosen.position.some((value, index) => Math.abs(value - whole.camera.position[index]) > 1),
    'the camera the person set is somewhere the fit never puts it');
  const stored = await page.evaluate(() => JSON.parse(JSON.stringify(window.cadHarness.tabStore.getSnapshot())));

  // Reopened: a fresh page over the same package with no declared box, held in pieces again,
  // carrying what the last session left for this file. (A remount would not do: the client still
  // holds every component it downloaded, so the package would arrive whole in ONE publish and
  // never reach completion as a second framing at all.)
  staggered.hold('a'); staggered.hold('b'); staggered.declare(false);
  const reopened = await staggered.open({ timeout: 60000, record: stored });
  await reopened.pane.locator('[aria-busy] > div > canvas').first().waitFor();
  await reopened.page.waitForFunction(() => window.__cadMeshCost?.loadedComponents === 8, null, { timeout: 60000 });
  staggered.release('a');
  await reopened.page.waitForFunction(() => window.__cadMeshCost?.loadedComponents === 24, null, { timeout: 60000 });
  staggered.release('b');
  await reopened.page.waitForFunction(() => window.__cadMeshCost?.final === true, null, { timeout: 60000 });
  await reopened.page.waitForFunction(() => window.cadHarness.a.controller?.readState().loading === false, null, { timeout: 60000 });
  await restingCamera(reopened.page);
  assert.deepEqual(await reopened.page.evaluate(() => [window.__cadMeshCost.publishCount, window.__cadMeshCost.final]),
    [3, true], 'it arrived in three publishes again, so completion really did reframe');
  const kept = await reopened.page.evaluate(() => window.__cadCamera());
  for (const key of ['position', 'target']) {
    chosen[key].forEach((value, index) => assert.ok(Math.abs(value - kept[key][index]) < 1e-6,
      `${key}[${index}] is the camera the person set, through every publish and the completion`));
  }
  // The picture settles a frame or two after the camera does (level of detail refines on a slow
  // renderer), so it is read until it matches, and a picture that never does still fails.
  let left = Infinity;
  for (let attempt = 0; attempt < 16 && left >= 250; attempt += 1) {
    left = differing(chosenFrame, await frame(reopened.pane));
    if (left >= 250) await reopened.page.waitForTimeout(250);
  }
  assert.ok(left < 250, `reopening shows what the person left on screen: ${left} pixels differ`);
  assert.deepEqual(reopened.errors, []);
  assert.deepEqual(errors, []);
});

// A warm package's open, request by request: where each component probed the shared cache and
// read its body alone (twenty-five of each here), a chunk of components shares a probe and a
// batch of them one read, growing from the loader's first publish of eight.
test('a warm package opens with a probe per chunk and its bodies in batches, and nothing read one component at a time', async (t) => {
  const staged = [];
  const warm = await serveStepHarness({ after: cleanup => staged.push(cleanup) }, { progressive: true, warmCache: true });
  t.after(async () => { for (const cleanup of staged.reverse()) await cleanup(); });
  warm.release('a'); warm.release('b');
  const { page, errors } = await warm.open();
  await page.waitForFunction(() => window.__cadMeshCost?.final === true && window.__cadMeshCost.loadedComponents === 25);
  const sent = pattern => warm.requests.filter(request => pattern.test(request)).length;
  assert.equal(sent(/^POST \/one\/__tess_cache\/probe$/), 3, 'a probe for each chunk: eight, sixteen and the last one');
  assert.equal(sent(/^POST \/one\/__tess_cache\/batch$/), 3, 'a read for each batch: eight, sixteen and the last one');
  assert.equal(sent(/^GET \/one\/__tess_cache\//), 0, 'no body read alone');
  assert.equal(sent(/\/__cad\/surfaces/), 0, 'no surface resolved');
  assert.equal(sent(/^GET \/one\/__cad\/store\?tree=/), 0, 'no surface read');
  assert.deepEqual(errors, []);
});

test('mobile touch: a tap selects, and a two-finger pinch zooms without selecting', async () => {
  const view = await open({ hasTouch: true, timeout: 10000 });
  const { page, pane, errors } = view;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector('[data-viewer-layout]')?.dataset.viewerLayout === 'mobile');
  // The camera takes the phone canvas's shape: points are projected from where it comes to rest.
  await page.waitForFunction(() => {
    const box = document.querySelector('[data-testid="one"] [data-cad-scene-backdrop]').getBoundingClientRect();
    return Math.abs(window.__cadCamera().aspect - box.width / box.height) < 0.01;
  });
  await restingCamera(page);
  await settle(page);
  const touch = await page.context().newCDPSession(page);
  const points = coords => coords.map(([x, y], id) => ({ x, y, id, radiusX: 3, radiusY: 3, force: 1 }));
  const gesture = async frames => {
    await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: points(frames[0]) });
    for (const coords of frames.slice(1)) {
      await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(coords) });
      await settle(page);
    }
    await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await settle(page);
  };
  const sceneBox = await pane.locator('[data-cad-scene-backdrop]').boundingBox();
  const project = projector(await page.evaluate(() => window.__cadCamera()), sceneBox);
  // A tap on a part picks it, with no hover before it.
  await page.touchscreen.tap(...project([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.1');
  await page.evaluate(() => window.cadHarness.a.controller.clearSelection());
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 0);

  // Two fingers that land on the model pinch: the camera zooms, and neither finger is a pick.
  const pinchBefore = (await view.state()).camera;
  const [x, y] = project([6, 6, 5]);
  await gesture([[[x - 50, y], [x + 50, y]], [[x - 80, y], [x + 80, y]], [[x - 90, y], [x + 90, y]]]);
  await page.waitForFunction(zoom => window.cadHarness.a.controller.readState().camera.zoom !== zoom, pinchBefore.zoom);
  // A tap's pick lands in the render its touch causes; two frames on, a pick would be there.
  await settle(page);
  assert.deepEqual([(await view.state()).selectedPartIds, (await view.state()).selectedReferenceIds], [[], []], 'pinching never selects geometry');
  assert.deepEqual(errors, []);
});

test('a click selects at once, and a double-click ends where it did when a click waited: the part isolated, isolation left, or the face copied and kept, on the selection its first click found', async () => {
  // Files are named by their absolute paths, and every copy says so.
  const view = await open({ init: () => { window.__cadPromptDestination = 'clipboard'; } });
  const { page, box, at, errors } = view;
  const selection = () => page.evaluate(() => { const state = window.cadHarness.a.controller.readState();
    return { parts: state.selectedPartIds, refs: state.selectedReferenceIds, isolated: state.isolatedPartIds }; });
  const cleared = () => page.waitForFunction(() => { const state = window.cadHarness.a.controller.readState();
    return state.selectedPartIds.length + state.selectedReferenceIds.length === 0; });
  const copies = () => page.evaluate(() => window.__clipboardWrites.length);
  // Empty space: the bottom centre, under the model, with nothing of the viewer's own in it (the
  // view cube is the bottom-right's, the file sidebar runs down the left).
  const empty = [box.x + box.width / 2, box.y + box.height - 30];
  const opening = (await view.state()).camera;
  await page.evaluate(() => {
    window.__clipboardWrites = [];
    window.cadHarness.a.host.clipboard.writeText = async text => { window.__clipboardWrites.push(text); };
    // A probe timer set at the press, ahead of the viewer's own handlers: it fires before any wait
    // the viewer could start there (the double-click window was 220 ms), however slow the frames.
    window.__selectedByProbe = null;
    document.addEventListener('pointerup', () => {
      window.__selectedByProbe = null;
      setTimeout(() => { window.__selectedByProbe = window.cadHarness.a.controller.readState().selectedPartIds.length > 0; }, 200);
    }, true);
  });
  // A click's selection does not wait to tell it from a double-click.
  await page.mouse.click(...at([15, 0, 4]));
  await page.waitForFunction(() => window.__selectedByProbe !== null);
  assert.equal(await page.evaluate(() => window.__selectedByProbe), true, 'the arm is selected before any double-click window could close');
  assert.deepEqual(await selection(), { parts: ['o1.2'], refs: [], isolated: [] });
  // A click on its chip in Quick Edit copies the pick's reference.
  await view.chip('arm').click();
  await page.waitForFunction(() => window.__clipboardWrites.length === 1);
  assert.equal(await page.evaluate(() => window.__clipboardWrites[0]), '/models/hinge_block.step#o1.2');
  await page.evaluate(() => { window.__clipboardWrites = []; });

  // A double-click on the base isolates it. Its first click picked the base; the double-click
  // put the arm back before isolating — and isolating clears the selection, as it always has.
  await page.mouse.dblclick(...at([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.join() === 'o1.1');
  await settle(page);
  assert.deepEqual(await selection(), { parts: [], refs: [], isolated: ['o1.1'] });
  assert.equal(await copies(), 0, 'a part double-click copies nothing');
  // Inside the isolation, the base picked (under Parts: the isolated part is open, so under All a
  // press there picks a face, which leaving isolation folds away): a double-click on empty space
  // leaves isolation with the base still selected. Its first click cleared the selection; the
  // double-click brought it back.
  await view.chooseSelectMode('Parts');
  await page.mouse.click(...at([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.1');
  await page.mouse.dblclick(...empty);
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.length === 0);
  await settle(page);
  assert.deepEqual(await selection(), { parts: ['o1.1'], refs: [], isolated: [] }, 'leaving isolation keeps the part picked inside it');
  // Shift held through the double-click: a shift-click on empty space never clears, and the
  // double-click still leaves isolation with the selection as it was.
  await page.mouse.dblclick(...at([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.join() === 'o1.1');
  await page.mouse.click(...at([6, 6, 5]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.1');
  await page.keyboard.down('Shift');
  await page.mouse.dblclick(...empty);
  await page.keyboard.up('Shift');
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.length === 0);
  await settle(page);
  assert.deepEqual(await selection(), { parts: ['o1.1'], refs: [], isolated: [] });

  // Under Faces, with both parts' faces loaded (a press on each loads its part's faces and picks
  // one), a double-click copies the face and leaves it selected...
  await view.chooseSelectMode('Faces');
  for (const [point, part] of [[[15, 0, 4], 'o1.2'], [[6, 6, 5], 'o1.1']]) {
    await page.mouse.click(...at(point));
    await page.waitForFunction(id => new RegExp(`\\|${id.replace('.', '\\.')}\\.f\\d+$`).test(window.cadHarness.a.controller.readState().selectedReferenceIds.join()), part);
  }
  await page.keyboard.press('Escape');
  await cleared();
  await page.mouse.dblclick(...at([15, 0, 4]));
  await page.waitForFunction(() => window.__clipboardWrites.length === 1);
  await settle(page);
  const armFace = (await selection()).refs;
  assert.equal(armFace.length, 1, `the double-clicked face is the selection: ${JSON.stringify(armFace)}`);
  assert.match(armFace[0], /\|o1\.2\.f\d+$/);
  assert.match(await page.evaluate(() => window.__clipboardWrites[0]), /^\/models\/hinge_block\.step#o1\.2\.f\d+$/);
  // ...also when it was selected already: the two clicks it is made of do not toggle it off.
  await page.mouse.dblclick(...at([15, 0, 4]));
  await page.waitForFunction(() => window.__clipboardWrites.length === 2);
  await settle(page);
  assert.deepEqual((await selection()).refs, armFace, 'a second double-click keeps the face selected');
  // With Shift, the double-clicked face joins the selection; a second shift double-click keeps it.
  await page.keyboard.down('Shift');
  await page.mouse.dblclick(...at([6, 6, 5]));
  await page.keyboard.up('Shift');
  await page.waitForFunction(() => window.__clipboardWrites.length === 3);
  await settle(page);
  const both = (await selection()).refs;
  assert.equal(both.length, 2, `shift adds the double-clicked face: ${JSON.stringify(both)}`);
  assert.equal(both[0], armFace[0]);
  assert.match(both[1], /\|o1\.1\.f\d+$/);
  await page.keyboard.down('Shift');
  await page.mouse.dblclick(...at([6, 6, 5]));
  await page.keyboard.up('Shift');
  await page.waitForFunction(() => window.__clipboardWrites.length === 4);
  await settle(page);
  assert.deepEqual((await selection()).refs, both, 'a shift double-click on a selected face keeps it');
  assert.deepEqual((await selection()).isolated, [], 'a topology double-click never isolates');
  // A double-click on empty space with no isolation to leave (as on a single-part STEP, whose
  // faces are what a press picks): its first click cleared the selection, and the double-click
  // puts the faces back, copying nothing.
  await page.mouse.dblclick(...empty);
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedReferenceIds.length === 2);
  await settle(page);
  assert.deepEqual((await selection()).refs, both, 'an empty-space double-click keeps the selection its first click found');
  assert.equal(await copies(), 4, 'and copies nothing');
  // ⌘C / Ctrl+C copies the whole selection, both parts' faces, from Quick Edit's empty note as from the view.
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Describe your changes');
  await page.keyboard.press('ControlOrMeta+c');
  await page.waitForFunction(() => window.__clipboardWrites.length === 5);
  const copiedSelection = parseCadRefToken(await page.evaluate(() => window.__clipboardWrites[4]));
  assert.equal(copiedSelection.cadPath, '/models/hinge_block.step');
  assert.deepEqual([...copiedSelection.selectors].sort(), both.map(reference => reference.split('|').at(-1)).sort());

  // Hover is untouched: under Faces the face under the pointer lights, under Edges the edge does.
  await page.keyboard.press('Escape');
  await cleared();
  await page.mouse.move(...empty);
  const faces = await restingFrame(view);
  await page.mouse.move(...at([6, 6, 5]));
  await frameWhen(view, shot => differing(faces, shot) > 200, 'lit the hovered face');
  await page.mouse.move(...empty);
  // Let go: back to the unlit frame, give or take a software renderer's few pixels of noise
  // (the lit face changes hundreds).
  await frameWhen(view, shot => differing(faces, shot) <= 20, 'let go of the hovered face');
  await view.chooseSelectMode('Edges');
  await page.mouse.move(...empty);
  const edges = await restingFrame(view);
  await page.mouse.move(...at([10, 6, 5]));
  await frameWhen(view, shot => differing(edges, shot) > 10, 'lit the hovered edge');
  await page.mouse.move(...empty);
  await frameWhen(view, shot => differing(edges, shot) <= 2, 'let go of the hovered edge');

  // A drag orbits and selects nothing; a right-click opens the menu and selects nothing.
  await view.chooseSelectMode('All');
  await page.mouse.click(...at([15, 0, 4]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.join() === 'o1.2');
  const before = await selection();
  const camera = await page.evaluate(() => window.__cadCamera().position);
  const [x, y] = at([6, 6, 5]);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 120, y + 40, { steps: 6 });
  await page.mouse.up();
  await page.waitForFunction(previous => window.__cadCamera().position.some((value, index) => Math.abs(value - previous[index]) > 1e-3), camera);
  await settle(page);
  assert.deepEqual(await selection(), before, 'a drag is not a click');
  // The orbit endpoint can lie under Quick Edit; open the viewport menu in clear space.
  await page.mouse.click(...empty, { button: 'right' });
  await page.getByRole('menu').waitFor();
  await settle(page);
  assert.deepEqual(await selection(), before, 'a right-click is not a click');
  await page.keyboard.press('Escape');
  await page.getByRole('menu').waitFor({ state: 'detached' });

  // Under Explode, where a pick takes up Select, a double-click on a part isolates it and Explode
  // stays the tool: its first click waits out the double-click window, which the second cancels.
  // (On the opening camera, where `at` projects, and with nothing selected.)
  await page.evaluate(camera => { const controller = window.cadHarness.a.controller; controller.clearSelection(); return controller.setCamera(camera); }, opening);
  await restingCamera(page);
  await view.tool('Explode').click();
  await page.waitForFunction(() => document.querySelector('[data-testid="one"] [data-cad-toolbar] [aria-label="Explode"]')?.getAttribute('aria-pressed') === 'true');
  // The arm: the base's faces, loaded above, are what a press on the base picks now.
  await page.mouse.dblclick(...at([15, 0, 4]));
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.join() === 'o1.2');
  // Past the window (220 ms) a first click that was not cancelled would have taken up Select.
  await page.waitForTimeout(400);
  await settle(page);
  assert.deepEqual((await view.tools()).filter(tool => tool.endsWith(':true')).map(tool => tool.split(':')[0]), ['Explode'], 'the tool stays Explode');
  assert.deepEqual(await selection(), { parts: [], refs: [], isolated: ['o1.2'] });
  assert.deepEqual(errors, []);
});

// ---- the tab ---------------------------------------------------------------------------------
// A page whose tab record is in its own sessionStorage (`?store=session`): a reload of the page is
// a reload of the tab, and a new page is a new tab.
test('a reload of the tab brings back the view — camera, Display, Clip, Explode or the pose, hidden and isolated parts, the tree — and starts afresh: Select, no selection, no measurement', async () => {
  const view = await open({ store: 'session' });
  const { page, pane, at, errors } = view;
  const rest = await translations(page);
  // The tree: expanded; the pose: posed from the sidebar.
  await view.partMenu('base', 'Expand');
  const position = pane.locator('[data-tool-panel][aria-label="Position controls"]');
  const input = position.getByLabel('hinge slider value', { exact: true });
  await view.openSection('Position');
  await input.fill('60'); await input.press('Enter');
  await page.waitForFunction(y => Math.abs(window.__cadDisplayRecords().find(record => record.partId === 'o1.2').matrix[13] - y) > 1, rest['o1.2'][1]);
  const posed = await translations(page);
  await view.openSection('Model tree');
  // A measurement, kept under Select; a part selected in the tree.
  await view.tool('Measure').click();
  const measurements = pane.locator('[data-quick-edit-ref^="measure-"]');
  await measurePoints(page, at, [0, 0, 5], [15, 0, 4]);
  await measurements.waitFor();
  await view.tool('Select').click();
  assert.equal(await measurements.isVisible(), true);
  await pane.getByRole('button', { name: 'Select base', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedPartIds.length === 1);
  // A part hidden, another isolated.
  await pane.getByRole('button', { name: 'Hide arm', exact: true }).click();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().hiddenPartIds.join() === 'o1.2');
  await pane.getByRole('button', { name: 'Select base', exact: true }).dblclick();
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().isolatedPartIds.length === 1);
  // The Display settings, with Explode (Clip, a motion as Explode is, would take it off: it is the
  // last reload's); then the camera.
  await view.display({ mode: 'wireframe', exploded: { enabled: true, amount: 0.3 } });
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.exploded.enabled === true);
  await page.evaluate(() => window.cadHarness.a.controller.setCamera({ ...window.cadHarness.a.controller.readState().camera, position: [60, -20, 25], target: [4, 1, 0], zoom: 1.3 }));
  await page.waitForFunction(() => Object.values(window.cadHarness.state.renderers || {})[0]?.camera?.zoom === 1.3);
  const left = await view.state();
  // Where the explosion put every part once it has eased out, to be found in the same place after the reload.
  const explodedLeft = await restingLayout(page, posed);
  // The tree as isolation shows it: the base's rows, opened.
  const rowsLeft = await view.rows();
  assert.ok(rowsLeft.length > 1, `the tree has the base's rows before the reload: ${rowsLeft.join(', ')}`);
  assert.deepEqual(await page.evaluate(() => Object.keys(sessionStorage)), ['text-to-cad:tab:harness'], 'one record, and nothing else in the tab');

  await view.reload();
  const back = await view.state();
  for (const property of ['position', 'target', 'zoom']) {
    const a = [back.camera[property]].flat(), b = [left.camera[property]].flat();
    assert.ok(a.every((value, index) => Math.abs(value - b[index]) < 1e-6), `the saved camera comes back in place of the fit: ${property} ${JSON.stringify([a, b])}`);
  }
  assert.deepEqual([back.display.mode, Boolean(back.display.clip?.enabled), back.display.exploded.enabled, back.display.exploded.amount],
    ['wireframe', false, true, 0.3], 'the Display settings and Explode come back');
  // An explosion restored on load lays the parts out exactly as the live one did: it is centred on
  // the rest placement, so the restored camera still frames the same picture. It is laid out once
  // the model is drawn again, so it is awaited, on the page's frames.
  const laidOut = await page.waitForFunction(left => {
    const now = Object.fromEntries(window.__cadDisplayRecords().map(record => [record.partId, record.matrix.slice(12, 15)]));
    return Object.keys(left).every(id => now[id] && left[id].every((value, axis) => Math.abs(value - now[id][axis]) < 1e-6));
  }, explodedLeft, { polling: 'raf', timeout: 30_000 }).then(() => true, () => false);
  assert.ok(laidOut, `every exploded part comes back where it was: ${JSON.stringify({ before: explodedLeft, after: await translations(page) })}`);
  assert.deepEqual([back.hiddenPartIds, back.isolatedPartIds.length], [['o1.2'], 1], 'the hidden and the isolated parts come back');
  assert.deepEqual(await view.rows(), rowsLeft, 'the tree comes back as it was, expanded');
  assert.deepEqual([back.selectedPartIds, back.selectedReferenceIds], [[], []], 'the selection does not');
  assert.equal(await measurements.count(), 0, 'nor the measurement');
  // The tool in hand is Select, the default, and it alone is lit: Explode's and Clip's restored
  // effects stay on the model, not lit tools.
  assert.deepEqual((await view.tools()).filter(tool => tool.endsWith(':true')), ['Select:true'], 'and the tool is the default');
  // Explode replaced the pose (one motion at a time): it came back at its default. A pose set now
  // takes Explode off, and comes back on the next reload.
  await input.waitFor({ state: 'attached' });
  assert.equal(await input.inputValue(), '0.00°', 'Explode put the pose back to its default');
  await view.openSection('Position');
  await input.fill('60'); await input.press('Enter');
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().display.exploded.enabled === false);
  // Once the tab's record holds it.
  await page.waitForFunction(() => /"hinge":60\b/.test(sessionStorage.getItem('text-to-cad:tab:harness') || ''));
  await view.reload();
  await input.waitFor({ state: 'attached' });
  assert.equal(await input.inputValue(), '60.0°', 'the pose comes back');
  assert.equal((await view.state()).display.exploded.enabled, false);
  // Clip set puts the pose back at its default, and comes back on the next reload with it.
  await view.display({ clip: { enabled: true, axis: 'x', at: 9 } });
  await page.waitForFunction(() => document.querySelector('[data-testid="one"] input[aria-label="hinge slider value"]')?.value === '0.00°');
  await page.waitForFunction(() => /"clip":\{[^}]*"enabled":true/.test(sessionStorage.getItem('text-to-cad:tab:harness') || ''));
  await view.reload();
  const clipped = await view.state();
  assert.deepEqual([clipped.display.clip.enabled, clipped.display.clip.axis, clipped.display.clip.at, clipped.display.exploded.enabled],
    [true, 'x', 9, false], 'Clip comes back');
  await input.waitFor({ state: 'attached' });
  assert.equal(await input.inputValue(), '0.00°', 'and the pose it put back');
  assert.deepEqual(errors, []);
});
