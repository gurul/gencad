import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runAnnotateScenario } from '../../../harness/annotateScenario.mjs';
import { serveStepHarness } from '../../../harness/stepScenario.mjs';

// Annotate under the frame that ships it: the STEP renderer, over the committed
// two-part fixture. It is a kit tool, so the scenario itself
// (`harness/annotateScenario.mjs`) knows nothing about STEP.

test('Annotate puts ink into the model that orbits with it, undoes, redoes, recolours and clears, stays when Annotate is left — where Select picks, haloes and deletes it — and goes when the model updates', async (t) => {
  const harness = await serveStepHarness(t);
  await runAnnotateScenario(await harness.open());
});


test('on a narrow view Annotate\'s controls are two aligned rows, and on a phone the menu of a chevron after its tile', async (t) => {
  const harness = await serveStepHarness(t);
  const { page, pane, errors } = await harness.open();
  await page.waitForFunction(() => window.cadHarness.a.controller?.readState().loading === false);
  await pane.getByRole('button', { name: 'Annotate', exact: true }).click();
  const controls = pane.getByRole('toolbar', { name: 'Annotation controls', exact: true });
  for (const width of [960, 768]) {
    await page.setViewportSize({ width, height: 600 });
    await page.waitForFunction(() => {
      const buttons = [...document.querySelectorAll('[aria-label="Annotation controls"] button')].map(button => button.getBoundingClientRect().top);
      return buttons.length === 14 && buttons[7] > buttons[0];
    });
    const layout = await controls.evaluate(row => {
      const buttons = [...row.querySelectorAll('button')].map(button => button.getBoundingClientRect());
      return { count: buttons.length, top: buttons.map(box => box.top), x: buttons.map(box => box.left) };
    });
    assert.equal(layout.count, 14);
    assert.ok(layout.top.slice(0, 7).every(y => y === layout.top[0]), `${width}px: seven tools on the first row`);
    assert.ok(layout.top.slice(7).every(y => y === layout.top[7]) && layout.top[7] > layout.top[0], `${width}px: seven settings/actions on the second row`);
    assert.deepEqual(layout.x.slice(0, 7), layout.x.slice(7), `${width}px: the two rows align`);
  }
  // A phone: no row under the strip; the chevron after Annotate's tile holds its controls.
  await page.setViewportSize({ width: 390, height: 700 });
  await controls.waitFor({ state: 'detached' });
  await pane.getByRole('button', { name: 'Annotation settings', exact: true }).click();
  const menu = page.getByRole('menu', { name: 'Annotation settings', exact: true });
  await menu.getByRole('menuitemradio', { name: 'Rectangle', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[data-cad-toolbar] [aria-label="Annotate"] svg')?.getAttribute('class')?.includes('lucide-square'));
  assert.deepEqual(errors, []);
});
