import React, { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ModelingTreeView from '../../../../../dist/renderers/step/components/workbench/ModelingTree.js';
import { useStepPanels } from '../../../../../dist/renderers/step/components/workbench/StepPanels.js';
import { useModelTools } from '../../../../../dist/renderers/kit/tools/model-effects/ModelTools.js';
import { buildPositionSection } from '../../../../../dist/renderers/step/components/workbench/MotionControlsSection.js';
import FloatingToolBar from '../../../../../dist/renderers/kit/tools/FloatingToolBar.js';
import ToolPanel from '../../../../../dist/renderers/kit/tools/ToolPanel.js';
import FileSidebar from '../../../../../dist/renderers/kit/tools/FileSidebar.js';

// The STEP renderer's sections in the file sidebar — an assembly's Model tree, Position — and the
// panels of its tools in the tool stack (Explode, Clip), each where it is decided, under what holds
// them. The viewport that picks and draws is the browser suite's (`StepRenderer.browser.test.mjs`).

// jsdom lays nothing out: the stack's column and the sidebar's room are given a height, and a panel its own style's size.
const STACK_HEIGHT = 600;
const restores: (() => void)[] = [];
function override(target: object, key: string, descriptor: PropertyDescriptor) {
  const previous = Object.getOwnPropertyDescriptor(target, key);
  Object.defineProperty(target, key, { configurable: true, ...descriptor });
  restores.push(() => previous ? Object.defineProperty(target, key, previous) : delete (target as any)[key]);
}
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  override(HTMLElement.prototype, 'clientHeight', { get(this: HTMLElement) { return this.hasAttribute('data-cad-tool-stack') || this.hasAttribute('data-file-sidebar-room') ? STACK_HEIGHT : 0; } });
  override(Element.prototype, 'scrollIntoView', { value() {} });
  for (const name of ['setPointerCapture', 'releasePointerCapture']) override(Element.prototype, name, { value() {} });
  override(Element.prototype, 'hasPointerCapture', { value: () => false });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); while (restores.length) restores.pop()!(); });

// An assembly: a hinge of a base and an arm, and a pin beside it.
const partNode = (id: string, name: string) => ({ id, nodeType: 'part', name, leafPartIds: [id], children: [] });
const stepRoot = { id: 'document', nodeType: 'assembly', name: 'fixture', children: [
  { id: 'o1.1', nodeType: 'assembly', name: 'hinge', children: [partNode('o1.1.1', 'base'), partNode('o1.1.2', 'arm')] }, partNode('o1.2', 'pin')] };

const rows = () => [...document.querySelectorAll('[aria-label="Modeling tree"] button')].map(button => button.getAttribute('aria-label'))
  .filter(label => /^(?:Select|Expand|Collapse) /.test(label || ''));
const locks = () => [...document.querySelectorAll<HTMLElement>('[aria-label="Modeling tree"] [data-disclosure-locked]')].map(mark => mark.dataset.disclosureLocked);
// The Model tree section; the sidebar's sections on screen, and the stack's panels.
const features = () => document.querySelector<HTMLElement>('section[data-tool-panel][aria-label="Model tree"]')!;
const sections = () => [...document.querySelectorAll<HTMLElement>('[data-cad-file-sidebar] section[data-tool-panel]')].filter(node => !node.hidden).map(node => node.getAttribute('aria-label'));

/** The layout a host keeps, applying what the stack writes back. */
function useLayout(initial: any = { panels: {}, collapsed: {} }) {
  const [layout, setLayout] = useState<any>(initial);
  return [layout, (patch: any) => setLayout((current: any) => ({ ...current, ...(typeof patch === 'function' ? patch(current) : patch) }))] as const;
}
// `mobile`: a phone's sidebar, one tile opening its panel (`phone`).
function Features({ mode = 'all', mobile = false }) {
  const [layout, change] = useLayout();
  const [expanded, setExpanded] = useState<string[]>([]);
  // The shell hands the sidebar the viewer's layout (`RendererShell.jsx`).
  return <FileSidebar layout={layout} onLayoutChange={change} phone={mobile}>
    <ModelingTreeView stepRoot={stepRoot} active mode={mode} onLoadTopology={() => {}}
      partControls={{ isAssemblyView: true, expandedTreeNodeIds: expanded,
        onToggleTreeNode: (id: string) => setExpanded(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]) }} />
  </FileSidebar>;
}

it("the geometry Select picks shapes the tree: Parts, Faces or Edges alone every assembly open, locked; all of it the person's own tree again", () => {
  const view = render(<Features />);
  // All: the tree is the person's own — open the hinge. A part is a leaf.
  expect(rows()).toEqual(['Expand hinge', 'Select hinge', 'Select pin']);
  fireEvent.click(screen.getByRole('button', { name: 'Expand hinge' }));
  expect(rows()).toEqual(['Collapse hinge', 'Select hinge', 'Select base', 'Select arm', 'Select pin']);
  expect(locks()).toEqual([]);
  // Parts, Faces and Edges: every assembly open, and no disclosure to press.
  for (const mode of ['parts', 'faces', 'edges']) {
    view.rerender(<Features mode={mode} />);
    expect(rows()).toEqual(['Select hinge', 'Select base', 'Select arm', 'Select pin']);
    expect(locks()).toEqual(['open']);
  }
  // All: the tree the person left — the hinge open — and unlocked.
  view.rerender(<Features mode="all" />);
  expect(rows()).toEqual(['Collapse hinge', 'Select hinge', 'Select base', 'Select arm', 'Select pin']);
  expect(locks()).toEqual([]);
});

it("Model tree is its filter over its tree — Select's modes are the strip's — opened by its tile, closed by its X or the tile again, never folding, its search kept while closed", async () => {
  const user = userEvent.setup();
  render(<Features />);
  const tile = within(screen.getByRole('group', { name: 'File sidebar' })).getByRole('button', { name: 'Model tree' });
  // Open: its tile pressed, the panel out with the section in it. Closing, the panel slides away with it.
  const open = () => [tile.getAttribute('aria-pressed'), document.querySelector('[data-cad-file-sidebar]')!.hasAttribute('data-open')];
  // None is open as the file opens; the tile opens it.
  expect([sections(), open(), features().hasAttribute('data-sidebar-closed')]).toEqual([['Model tree'], ['false', false], true]);
  await user.click(tile);
  expect([open(), features().hasAttribute('data-sidebar-closed')]).toEqual([['true', true], false]);
  // Its head: the search box and the section's X; no heading, nothing to fold.
  const head = features().querySelector<HTMLElement>('[data-sidebar-head]')!;
  const search = within(head).getByRole('textbox', { name: 'Filter model' }) as HTMLInputElement;
  expect([head.querySelector('[data-tool-panel-heading]'), search.getAttribute('placeholder')]).toEqual([null, 'Filter…']);
  expect([...head.querySelectorAll('button')].map(button => button.getAttribute('aria-label'))).toEqual(['Close model tree']);
  expect(within(features()).queryByRole('button', { name: /^(?:Collapse|Expand) features$/ })).toBeNull();
  await user.type(search, 'ba');
  expect(within(features()).getByRole('status').textContent).toMatch(/match/);
  // Its X closes it; the tile opens it again, as it was left; a second press of the tile closes it.
  await user.click(within(head).getByRole('button', { name: 'Close model tree' }));
  expect(open()).toEqual(['false', false]);
  await user.click(tile);
  expect([open(), search.value]).toEqual([['true', true], 'ba']);
  await user.click(tile);
  expect(open()).toEqual(['false', false]);
});

it("Model tree is as tall as its rows, on desktop and phone alike: no cap, scroller or grip of its own, its rows scrolling with the sidebar", () => {
  for (const mobile of [true, false]) {
    render(<Features mobile={mobile} />);
    expect([features().style.maxHeight, features().querySelector('[role=separator]')]).toEqual(['', null]);
    expect(features().querySelector('[data-radix-scroll-area-viewport]')).toBeNull();
    expect(features().closest('[data-file-sidebar-scroller]')).not.toBeNull();
    cleanup();
  }
});

// What Select shows (`StepPanels.js`): an assembly's tree; a part file has no tree, its one row
// being all there would be, and nothing else — its modes are the strip's. What is picked is
// Quick Edit's, as chips (`StepReferenceSection.test.tsx`): no panel of the stack shows it.
const face = { id: 'o1.1.1.f2', normalizedSelector: 'o1.1.1.f2', selectorType: 'face', occurrenceId: 'o1.1.1', pickData: { surfaceType: 'plane', area: 20 } };
function SelectPanels({ assembly = false, references = [] as any[] }) {
  const partRoot = { id: '__step_model__', nodeType: 'part', name: 'hinge.step', leafPartIds: ['__model__'], children: [] };
  return useStepPanels({ selectActive: true, selectedEntry: { file: '/models/hinge.step' }, isAssemblyView: assembly,
    stepTreeRoot: assembly ? stepRoot : partRoot, selectedReferences: references });
}
function Panels(props: any) {
  const [layout, change] = useLayout();
  return <FileSidebar layout={layout} onLayoutChange={change}><SelectPanels {...props} /></FileSidebar>;
}

it("a part file with no joints has no section, picked or not; an assembly its tree", () => {
  const view = render(<Panels />);
  expect(sections()).toEqual([]);
  // A pick changes nothing here.
  view.rerender(<Panels references={[face]} />);
  expect(sections()).toEqual([]);
  view.unmount();
  render(<Panels assembly references={[face]} />);
  expect(sections()).toEqual(['Model tree']);
});

// ---- Explode and Clip ---------------------------------------------------------------------------

const neutral = () => ({ exploded: { enabled: false, amount: 0 }, clip: { enabled: false, axis: 'x', invert: false } });
const part = (id: string) => ({ id, bounds: { min: [0, 0, 0], max: [10, 10, 10] } });
let viewSettings = neutral();
/** Select, Measure, Explode and Clip on a strip over a stack, and the Display settings they write — as the STEP surface composes them. */
function Workbench() {
  const [view, setView] = useState(neutral);
  const [selectedTool, setTool] = useState('references');
  viewSettings = view;
  const store = { patch: (patch: any) => setView(current => ({
    exploded: { ...current.exploded, ...patch.exploded },
    clip: { ...current.clip, ...patch.clip } })) };
  const modelTools = useModelTools({ view, features: { settings: ['exploded', 'clip'] }, store,
    mesh: { parts: [part('a'), part('b')], bounds: { min: [0, 0, 0], max: [10, 10, 10] } }, disabled: false, selectedTool, onSelect: setTool });
  const own = (id: string, label: string) => ({ id, label, active: selectedTool === id, icon: <span>{label[0]}</span>, onSelect: () => setTool(id) });
  return <>
    <FloatingToolBar tools={[own('references', 'Select'), own('measure', 'Measure'), ...modelTools.tools]} />
    {modelTools.subToolbar}
  </>;
}
const tool = (name: string) => within(screen.getByRole('group', { name: 'Interaction tools' })).getByRole('button', { name });
const pressed = () => within(screen.getByRole('group', { name: 'Interaction tools' })).getAllByRole('button')
  .filter(button => button.getAttribute('aria-pressed') === 'true').map(button => button.getAttribute('aria-label'));
const row = (name: string) => screen.queryByRole('toolbar', { name });
const subRows = () => screen.queryAllByRole('toolbar').map(node => node.getAttribute('aria-label'));
const slider = (name: string) => screen.getByRole('slider', { name });
// What a row says, left to right: its lead, its value, its actions and its Reset.
const reads = (name: string) => [...row(name)!.querySelectorAll('[data-model-tool-amount], button[aria-label]')]
  .map(node => node.getAttribute('aria-label') || node.textContent);
// Whether its Reset can take anything away.
const resettable = (name: string, tool: string) => !within(row(name)!).getByRole('button', { name: `Reset ${tool}` }).hasAttribute('disabled');

it('Explode and Clip open neutral, each one row under the strip with its amount and a Reset, idle until set; only the tool in hand has one, and an effect stays on the model without it', async () => {
  const user = userEvent.setup({ pointerEventsCheck: 0 });
  render(<Workbench />);
  await user.click(tool('Explode'));
  expect([pressed(), subRows()]).toEqual([['Explode'], ['Explode controls']]);
  // One rule only, parting the tools that pick from the model's effects (this strip has no view controls).
  expect(screen.getByRole('group', { name: 'Interaction tools' }).querySelectorAll('[role=separator][data-strip-rule]')).toHaveLength(1);
  // A row of its own, no panel of a stack: its slider, its amount, its Reset (idle).
  expect([row('Explode controls')!.hasAttribute('data-cad-sub-toolbar'), row('Explode controls')!.closest('[data-tool-panel], [data-cad-tool-stack]')]).toEqual([true, null]);
  expect([reads('Explode controls'), resettable('Explode controls', 'explode')]).toEqual([['0%', 'Reset explode'], false]);
  // No rule parts a row: lead, slider, value, actions, Reset; Explode's lead is its name.
  expect([row('Explode controls')!.querySelector('[role=separator]'), row('Explode controls')!.firstElementChild!.textContent]).toEqual([null, 'Explode']);
  expect(slider('Explode amount').getAttribute('aria-valuenow')).toBe('0');
  expect(viewSettings.exploded.enabled).toBe(false);
  fireEvent.keyDown(slider('Explode amount'), { key: 'End' });
  expect([viewSettings.exploded, reads('Explode controls'), resettable('Explode controls', 'explode')])
    .toEqual([{ enabled: true, amount: 1 }, ['100%', 'Reset explode'], true]);
  await user.click(tool('Clip'));
  // Only the tool in hand is lit, and has its row: the applied Explode stays on the model.
  expect([pressed(), subRows(), viewSettings.exploded.enabled]).toEqual([['Clip'], ['Clip controls'], true]);
  const clip = row('Clip controls')!;
  expect([viewSettings.clip.enabled, reads('Clip controls'), resettable('Clip controls', 'clip')]).toEqual([false, ['Clip axis: X', '0%', 'Reset clip'], false]);
  expect(clip.querySelector('[role=separator]')).toBeNull();
  // Its axis, a dropdown that holds its settings too, ONE slider (no typed value) and its value.
  // Changing the axis stays neutral.
  expect(within(clip).queryByLabelText('Clip amount value')).toBeNull();
  const reverse = async () => {
    await user.click(row('Clip controls')!.querySelector<HTMLElement>('[data-clip-axis]')!);
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'Reverse' }));
    await user.keyboard('{Escape}');
  };
  // An axis chosen keeps the menu open.
  await user.click(clip.querySelector<HTMLElement>('[data-clip-axis]')!);
  for (const axis of ['Y', 'Z', 'X']) {
    await user.click(screen.getByRole('menuitemradio', { name: axis }));
    expect(within(clip).getByRole('button', { name: `Clip axis: ${axis}` }).textContent).toBe(axis);
    expect(['aria-valuemin', 'aria-valuemax', 'aria-valuenow'].map(name => slider('Clip amount').getAttribute(name))).toEqual(['0', '100', '0']);
    expect(viewSettings.clip.enabled).toBe(false);
  }
  await user.keyboard('{Escape}');
  fireEvent.keyDown(slider('Clip amount'), { key: 'ArrowRight' });
  expect(viewSettings.clip.enabled).toBe(true);
  fireEvent.keyDown(slider('Clip amount'), { key: 'Home' });
  expect(viewSettings.clip.enabled).toBe(false);
  fireEvent.keyDown(slider('Clip amount'), { key: 'PageUp' });
  const share = clip.querySelector('[data-model-tool-amount]')!.textContent;
  expect([viewSettings.clip.enabled, share, resettable('Clip controls', 'clip')]).toEqual([true, expect.stringMatching(/^\d+%$/), true]);
  // Reverse (the axis dropdown's) turns the cut round, the same share of the model cut away.
  await reverse();
  expect([viewSettings.clip.invert, clip.querySelector('[data-model-tool-amount]')!.textContent]).toEqual([true, share]);
  await reverse();
  expect([viewSettings.clip.invert, clip.querySelector('[data-model-tool-amount]')!.textContent]).toEqual([false, share]);
  // A second press on the tool in hand does nothing.
  await user.click(tool('Clip'));
  expect([pressed(), subRows()]).toEqual([['Clip'], ['Clip controls']]);
  // Select is the tool again: no row at all, both effects on the model.
  await user.click(tool('Select'));
  expect([pressed(), subRows(), viewSettings.exploded.enabled, viewSettings.clip.enabled]).toEqual([['Select'], [], true, true]);
  // A press on Clip takes it up again as it is: the cut is set.
  await user.click(tool('Clip'));
  expect([pressed(), viewSettings.clip.enabled, resettable('Clip controls', 'clip')]).toEqual([['Clip'], true, true]);
  // Reset takes the cut away and leaves Clip the tool, neutral, its Reset idle.
  await user.click(within(row('Clip controls')!).getByRole('button', { name: 'Reset clip' }));
  expect([pressed(), viewSettings.clip.enabled, resettable('Clip controls', 'clip')]).toEqual([['Clip'], false, false]);
  // Explode, taken up again, is at the amount it was left at; its Reset takes it away.
  await user.click(tool('Explode'));
  expect(slider('Explode amount').getAttribute('aria-valuenow')).toBe('100');
  await user.click(within(row('Explode controls')!).getByRole('button', { name: 'Reset explode' }));
  expect([viewSettings.exploded.enabled, reads('Explode controls'), resettable('Explode controls', 'explode')]).toEqual([false, ['0%', 'Reset explode'], false]);
  // A neutral Clip starts neutral when taken up, and leaves nothing when put down.
  await user.click(tool('Clip'));
  expect([viewSettings.clip.enabled, viewSettings.clip.invert]).toEqual([false, false]);
  await user.click(tool('Select'));
  expect([subRows(), pressed()]).toEqual([[], ['Select']]);
});

// ---- Position ------------------------------------------------------------------------------------

const parameters = [{ id: 'hinge', label: 'hinge', type: 'number', unit: 'deg', min: -180, max: 180, defaultValue: 0 }];
const hinge = { url: '/hinge.step.json', parameters, parameterMap: { hinge: parameters[0] }, defaultParameterValues: { hinge: 0 }, manifest: { poses: { open: { hinge: 90 } } } };
/** STEP's Position section as the file sidebar draws it (`StepPanels.js`) over a pose runtime. */
function Position() {
  const [values, setValues] = useState<Record<string, number>>({ hinge: 0 });
  const [activePose, setActivePose] = useState('');
  const [layout, change] = useLayout();
  const runtime = { definition: hinge, parameterValues: values, activePose,
    onApplyPose: (name: string) => { setActivePose(name); setValues({ hinge: (hinge.manifest.poses as any)[name].hinge }); },
    onResetMotion: () => { setActivePose(''); setValues({ hinge: 0 }); },
    onParameterChange: (id: string, value: number) => { setActivePose(''); setValues(current => ({ ...current, [id]: value })); } };
  const position = buildPositionSection({ poseRuntime: runtime })!;
  return <FileSidebar layout={layout} onLayoutChange={change}>
    <ToolPanel id="position" title={position.title} label="Position controls" fit="details">{position.content}</ToolPanel>
  </FileSidebar>;
}

it("Position's Pose is the body's first row — Default, then the named poses — its Reset the heading's, and every joint's slider is named", async () => {
  const user = userEvent.setup({ pointerEventsCheck: 0 });
  render(<Position />);
  const panel = screen.getByRole('region', { name: 'Position controls' });
  const head = panel.querySelector<HTMLElement>('[data-sidebar-head]')!;
  const pose = () => within(panel.querySelector<HTMLElement>('[data-tool-panel-body] [data-pose-row]')!).getByRole('button', { name: /^Pose: / });
  const reset = () => within(head).getByRole('button', { name: 'Reset position' }) as HTMLButtonElement;
  const value = within(panel).getByLabelText('hinge slider value') as HTMLInputElement;
  // The heading: its name, then Reset (idle at Default) and the section's X; the pose a full-width row under it.
  expect([within(head).getByRole('heading').textContent, [...head.querySelectorAll('button')].map(button => button.getAttribute('aria-label'))])
    .toEqual(['Position', ['Reset position', 'Close position']]);
  expect([pose().getAttribute('aria-label'), pose().hasAttribute('data-pose-menu'), reset().disabled]).toEqual(['Pose: Default', true, true]);
  expect(panel.querySelector('[data-position-header]')).toBeNull();
  expect(within(panel).getAllByRole('slider').map(thumb => thumb.getAttribute('aria-label'))).toEqual(['hinge']);
  const choose = async (name: string) => {
    await user.click(pose());
    const menu = document.querySelector<HTMLElement>('[role=menu][aria-label="Pose"]')!;
    await user.click(within(menu).getByRole('menuitemradio', { name }));
  };
  await user.click(pose());
  expect(within(document.querySelector<HTMLElement>('[role=menu][aria-label="Pose"]')!).getAllByRole('menuitemradio')
    .map(item => [item.textContent, item.getAttribute('aria-checked')])).toEqual([['Default', 'true'], ['open', 'false']]);
  await user.keyboard('{Escape}');
  await choose('open');
  expect([value.value, pose().getAttribute('aria-label'), reset().disabled]).toEqual(['90.0°', 'Pose: open', false]);
  await choose('Default');
  expect([value.value, pose().getAttribute('aria-label')]).toEqual(['0.00°', 'Pose: Default']);
  // A joint set by hand is Custom; Reset puts it back.
  await user.clear(value);
  await user.type(value, '25{Enter}');
  expect(pose().getAttribute('aria-label')).toBe('Pose: Custom');
  await user.click(reset());
  expect([value.value, pose().getAttribute('aria-label'), reset().disabled]).toEqual(['0.00°', 'Pose: Default', true]);
});
