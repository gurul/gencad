import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { serveStepHarness } from '../harness/stepScenario.mjs';

// Fixes from a QA pass over the STEP renderer, pinned in a real browser over the committed
// fixture (`__fixtures__/step`, served by `renderers/harness/stepScenario.mjs`): its base staged
// alone as the single-part STEP cadgen writes.

let lone;
const cleanups = [];
before(async () => { lone = await serveStepHarness({ after: cleanup => cleanups.push(cleanup) }, { singlePart: true }); });
after(async () => { for (const cleanup of cleanups.reverse()) await cleanup(); });

const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
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

async function open(server) {
  const view = await server.open();
  const { page, pane } = view;
  await pane.locator('[aria-busy="false"] > div > canvas').first().waitFor();
  await page.waitForFunction(() => window.cadHarness.a.controller?.readState().loading === false);
  await pane.locator('[data-cad-toolbar]').getByRole('button', { name: 'Select', exact: true }).waitFor();
  // The opening fit at rest, the same camera two frames running: `at` projects from it.
  await page.waitForFunction(() => {
    const camera = JSON.stringify(window.__cadCamera());
    const still = window.__lastCamera === camera;
    window.__lastCamera = camera;
    return still;
  }, null, { polling: 'raf' });
  await settle(page);
  const box = await pane.locator('[data-cad-surface] canvas').first().boundingBox();
  return {
    ...view, box,
    at: projector(await page.evaluate(() => window.__cadCamera()), box),
    state: () => page.evaluate(() => window.cadHarness.a.controller.readState()),
    tool: name => pane.locator('[data-cad-toolbar]').getByRole('button', { name, exact: true }),
  };
}

test('a single-part STEP names a picked face after its part, by the name the view gives it', async () => {
  const view = await open(lone);
  const { page, pane, at, errors } = view;
  // What is picked is Quick Edit's: a chip each, by its words, and its card on a rest of the pointer.
  const refs = pane.locator('[data-quick-edit-refs]');
  const chips = () => refs.locator('[data-quick-edit-ref] > button:first-child').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label')));
  const chipCard = async label => {
    await refs.getByRole('button', { name: label, exact: true }).hover();
    const card = page.locator('[data-quick-edit-ref-card]').filter({ has: page.getByText(label, { exact: true }) });
    await card.waitFor();
    return card;
  };
  // Main's fixture has an XCAF label entry; the viewer names the part from its file.
  assert.equal(lone.fixture.view.occurrences[0].name, '=>[0:1:1:2]');
  // A single part has no Explode, as it has no tree: one part separates nothing.
  assert.equal(await view.tool('Explode').count(), 0, 'no Explode for a part file');
  assert.equal(await view.tool('Clip').count(), 1, 'Clip stays');
  // A single part has no tree under Select (its one row would be all of it), and no panel in its
  // place: Select's menu is the chevron after its button on the strip, on All, with no
  // Parts (a part is one thing) and no Position (nothing moves).
  assert.equal(await pane.locator('[data-tool-panel][aria-label="Model tree"]').count(), 0, 'no tree for a part file');
  assert.equal(await pane.getByRole('region', { name: 'Select', exact: true }).count(), 0, 'and no Select card');
  await pane.locator('[data-cad-toolbar]').getByRole('button', { name: 'Selection filter: everything', exact: true }).click();
  assert.deepEqual(await page.locator('[role=menu][aria-label="Selection filter"] [data-select-filter]').allInnerTexts(),
    ['All', 'Faces', 'Edges']);
  await page.keyboard.press('Escape');
  await page.locator('[role=menu]').waitFor({ state: 'detached' });
  // Its faces load once Select is up: picking everything, a press picks one.
  await page.mouse.click(...at([6, 6, 5]));
  await page.waitForFunction(() => /\.f\d+$/.test(window.cadHarness.a.controller.readState().selectedReferenceIds.join()));
  const face = (await view.state()).selectedReferenceIds[0].split('|').at(-1);
  const ordinal = face.replace(/^.*\.f/, '');
  assert.deepEqual(await chips(), [`hinge_base · face ${ordinal}`], 'the chip is the part, by its own name rather than the file\'s, and the kind');
  assert.match((await (await chipCard(`hinge_base · face ${ordinal}`)).innerText()).replace(/\s+/g, ' '), new RegExp(`^hinge_base · face ${ordinal} ID \\S+ Area `),
    'and its card is the face\'s area');
  // A second face of the part joins the first in one chip, and its card names each the same way.
  await page.keyboard.down('Shift');
  await page.mouse.click(...at([10, 0, 0]));
  await page.keyboard.up('Shift');
  await page.waitForFunction(() => window.cadHarness.a.controller.readState().selectedReferenceIds.length === 2);
  assert.deepEqual(await chips(), ['hinge_base · 2 faces']);
  const card = await chipCard('hinge_base · 2 faces');
  const rows = await card.locator('[data-info-row]').evaluateAll(nodes => nodes.map(node => node.innerText.replace(/\s+/g, ' ').trim()));
  const faceRows = rows.filter(row => !row.startsWith('ID '));
  assert.equal(faceRows.length, 2, `a row a face: ${rows}`);
  assert.ok(faceRows.every(row => /^face \d+ [\d,.]+ mm²$/.test(row)), `the card's rows: ${rows}`);
  assert.deepEqual(errors, []);
});
