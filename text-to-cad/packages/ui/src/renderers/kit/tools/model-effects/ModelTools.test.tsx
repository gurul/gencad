import React, { useState, useSyncExternalStore } from 'react';
import { createViewSettingsStore } from '../../../../../dist/renderers/kit/view-settings/viewSettingsStore.js';
import { resolveViewSettings } from '@text-to-cad/core/common/viewSettings.js';
import { act, cleanup, fireEvent, render, renderHook, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useModelTools } from '../../../../../dist/renderers/kit/tools/model-effects/ModelTools.js';

beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const neutral = () => resolveViewSettings({});

it('only the tool in hand has its row under the strip, an applied effect leaving none behind; taken up again it is as it was, unset it starts neutral; only the tool in hand is lit', () => {
  const props = { view: neutral(), features: { settings: ['exploded', 'clip'] }, store: { patch: vi.fn() },
    mesh: null, disabled: false, selectedTool: 'references', onSelect: vi.fn() };
  const { result, rerender } = renderHook(options => useModelTools(options), { initialProps: props });
  const active = () => result.current.tools.filter(tool => tool.active).map(tool => tool.id);
  // The tool's row on screen, by its name.
  const shown = () => { const view = render(<>{result.current.subToolbar}</>); const names = [...view.container.querySelectorAll('[role=toolbar][data-cad-sub-toolbar]')]
    .map(row => row.getAttribute('aria-label')); view.unmount(); return names; };
  act(() => result.current.tools.find(tool => tool.id === 'exploded').onSelect());
  expect(props.onSelect).toHaveBeenCalledWith('exploded');
  expect(props.store.patch).toHaveBeenLastCalledWith({ exploded: { enabled: false, amount: 0 } });
  rerender({ ...props, selectedTool: 'exploded' });
  expect([active(), shown()]).toEqual([['exploded'], ['Explode controls']]);
  // A second press on the tool in hand does nothing.
  act(() => result.current.tools.find(tool => tool.id === 'exploded').onSelect());
  expect(props.onSelect).toHaveBeenCalledOnce();
  // Applied, then put down: the effect stays on the model, and nothing of it on screen.
  const applied = { ...props, view: { ...neutral(), exploded: { enabled: true, amount: .4 } } };
  rerender({ ...applied, selectedTool: 'references' });
  expect([active(), shown()]).toEqual([[], []]);
  // Taken up again it is as it was: nothing is patched.
  props.store.patch.mockClear();
  act(() => result.current.tools.find(tool => tool.id === 'exploded').onSelect());
  expect(props.store.patch).not.toHaveBeenCalled();
});

it('a clip at zero keeps its row while in hand, and no tool leaves one behind', () => {
  const props = { view: { ...neutral(), clip: { ...neutral().clip, enabled: true, at: 5 } },
    features: { settings: ['clip'] }, store: { patch: vi.fn() }, mesh: null, disabled: false, selectedTool: 'clip', onSelect: vi.fn() };
  const { result, rerender } = renderHook(options => useModelTools(options), { initialProps: props });
  const kept = () => { const view = render(<>{result.current.subToolbar}</>); const count = view.container.querySelectorAll('[role=toolbar][data-cad-sub-toolbar]').length; view.unmount(); return count; };
  expect(kept()).toBe(1);
  rerender({ ...props, view: neutral() });
  expect(kept()).toBe(1);
  rerender({ ...props, view: neutral(), selectedTool: 'display' });
  expect(kept()).toBe(0);
});

it('offers Explode and Clip on every STEP, a single part too, and idles them while the model loads', () => {
  const part = (id: string) => ({ id, bounds: { min: [0, 0, 0], max: [1, 1, 1] } });
  const props = { view: neutral(), features: { settings: ['exploded', 'clip'] }, store: { patch: vi.fn() },
    mesh: null as null | object, disabled: true, selectedTool: 'references', onSelect: vi.fn() };
  const { result, rerender } = renderHook(options => useModelTools(options), { initialProps: props });
  const offered = () => result.current.tools.map(tool => `${tool.id}:${tool.disabled}`);
  // Loading, idle; then every STEP has both, a single part too (its Explode separates nothing).
  expect(offered()).toEqual(['exploded:true', 'clip:true']);
  rerender({ ...props, disabled: false, mesh: { parts: [part('a')] } });
  expect(offered()).toEqual(['exploded:false', 'clip:false']);
  rerender({ ...props, disabled: false, mesh: { parts: [part('a'), part('b')] } });
  expect(offered()).toEqual(['exploded:false', 'clip:false']);
});

it('Clip\'s axis dropdown holds its settings: the axes as one row of radio items, a rule, then Part colors and Reverse; all kept across tools and by Reset, which only takes the cut away; both persist in the display', async () => {
  const user = userEvent.setup({ pointerEventsCheck: 0 });
  const store = createViewSettingsStore();
  function Harness() {
    const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot);
    const [selectedTool, onSelect] = useState('references');
    const tools = useModelTools({ view: snapshot.scene.view, features: { settings: ['clip'] }, store,
      mesh: { bounds: { min: [0, 0, 0], max: [10, 10, 10] } }, disabled: false, selectedTool, onSelect });
    return <><button onClick={() => onSelect('references')}>Select</button>
      {tools.tools.map(tool => <button key={tool.id} onClick={tool.onSelect}>{tool.label}</button>)}{tools.subToolbar}</>;
  }
  render(<Harness />);
  const clip = () => store.getSnapshot().scene.view.clip;
  const takeUp = (name: string) => user.click(screen.getByRole('button', { name, exact: true }));
  const axisButton = () => screen.getByRole('toolbar', { name: 'Clip controls' }).querySelector<HTMLElement>('[data-clip-axis]')!;
  // The menu is named by its trigger, as every dropdown here is.
  const menu = () => screen.getByRole('menu', { name: /^Clip axis: [XYZ]$/ });
  const item = (name: string) => screen.getByRole('menuitemcheckbox', { name });
  const ticks = () => ['Part colors', 'Reverse'].map(name => item(name).getAttribute('aria-checked'));
  // What the menu holds, top to bottom: the three axes (one group), then the two settings — no heading.
  const reads = () => [...menu().querySelectorAll('[role=menuitemradio], [role=menuitemcheckbox], [data-slot=dropdown-menu-label]')]
    .map(node => `${node.getAttribute('role')}:${node.getAttribute('aria-label') || node.textContent}:${node.getAttribute('aria-checked')}`);
  const share = () => screen.getByRole('toolbar', { name: 'Clip controls' }).querySelector('[data-model-tool-amount]')!.textContent;
  await takeUp('Clip');
  // The row: axis, slider, amount, Reset — Explode's shape, no checkbox and no other button.
  const row = screen.getByRole('toolbar', { name: 'Clip controls' });
  expect([...row.querySelectorAll('[data-model-tool-amount], button[aria-label]')].map(node => node.getAttribute('aria-label') || node.textContent))
    .toEqual(['Clip axis: X', '0%', 'Reset clip']);
  expect(within(row).queryByRole('checkbox')).toBeNull();
  // By keyboard: Enter opens it on the axis in hand; Space on a setting ticks it and leaves it open.
  axisButton().focus();
  await user.keyboard('{Enter}');
  expect(reads()).toEqual(['menuitemradio:X:true', 'menuitemradio:Y:false', 'menuitemradio:Z:false',
    'menuitemcheckbox:Part colors:true', 'menuitemcheckbox:Reverse:false']);
  expect(within(menu()).getByRole('group', { name: 'Clip axis' })).toBeTruthy();
  expect(document.activeElement?.textContent).toBe('X');
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}');
  expect(document.activeElement).toBe(item('Part colors'));
  await user.keyboard(' ');
  await user.click(item('Reverse'));
  // An axis chosen keeps the menu open, the button reads it; none of them applies a cut.
  await user.click(screen.getByRole('menuitemradio', { name: 'Y' }));
  expect([reads(), axisButton().textContent, clip().enabled, clip().axis, clip().partColors, clip().invert]).toEqual([
    ['menuitemradio:X:false', 'menuitemradio:Y:true', 'menuitemradio:Z:false', 'menuitemcheckbox:Part colors:false', 'menuitemcheckbox:Reverse:true'],
    'Y', false, 'y', false, true]);
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('menu')).toBeNull();
  // A cut: Reverse turns it round keeping its share.
  fireEvent.keyDown(screen.getByRole('slider', { name: 'Clip amount' }), { key: 'PageUp' });
  const cut = share();
  expect([clip().enabled, cut]).toEqual([true, expect.stringMatching(/^[1-9]\d*%$/)]);
  await user.click(axisButton());
  await user.click(item('Reverse'));
  expect([clip().invert, share(), clip().enabled]).toEqual([false, cut, true]);
  await user.click(item('Reverse'));
  await user.keyboard('{Escape}');
  // Put down and taken up again, all as it was.
  await takeUp('Select');
  await takeUp('Clip');
  expect([clip().enabled, clip().axis, clip().partColors, clip().invert, share()]).toEqual([true, 'y', false, true, cut]);
  // Reset: the amount back at zero, nothing else; an unset Clip taken up again changes nothing either.
  await user.click(screen.getByRole('button', { name: 'Reset clip' }));
  expect([clip().enabled, clip().axis, clip().partColors, clip().invert, share()]).toEqual([false, 'y', false, true, '0%']);
  await takeUp('Select');
  await takeUp('Clip');
  expect([clip().axis, clip().partColors, clip().invert]).toEqual(['y', false, true]);
  await user.click(axisButton());
  expect(ticks()).toEqual(['false', 'true']);
  // Both persist in the display as stored, and a restored display reads them back; validation stays strict.
  const stored = store.getSnapshot().display.clip;
  expect([stored.partColors, stored.invert]).toEqual([false, true]);
  expect(createViewSettingsStore(store.getSnapshot().display).getSnapshot().scene.view.clip).toMatchObject({ axis: 'y', partColors: false, invert: true });
  expect(() => createViewSettingsStore({ clip: { reverse: true } })).toThrow();
  expect(() => createViewSettingsStore({ clip: { partColors: 'false' } })).toThrow();
  expect(createViewSettingsStore().getSnapshot().scene.view.clip).toMatchObject({ partColors: true, invert: false });
});
