import React, { useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import FloatingToolBar from '../../../../../dist/renderers/kit/tools/FloatingToolBar.js';
import { MeasureIcon, SelectIcon, SelectModeMenu, STEP_SELECT_DEFAULT } from '../../../../../dist/renderers/step/components/workbench/SelectionModes.js';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const badges = (root: Element) => [...root.querySelectorAll('svg[data-tool-icon-base]')].map(icon =>
  `${icon.getAttribute('data-tool-icon-base')}:${icon.querySelector('[data-tool-icon-badge]')?.getAttribute('data-tool-icon-badge') ?? ''}`);
const menu = () => document.querySelector('[role=menu]')!;
const glyphs = (root: Element) => [...root.querySelectorAll('svg[data-mode-glyph]')].map(icon => icon.getAttribute('data-mode-glyph'));
const filterItems = () => [...document.querySelectorAll('[data-select-filter]')].map(item => [item.textContent, item.getAttribute('aria-checked')]);
const groupItems = () => screen.getAllByRole('menuitemcheckbox').filter(item => !item.hasAttribute('data-select-filter')).map(item => item.textContent);
const tick = (user: ReturnType<typeof userEvent.setup>, id: string) => user.click(document.querySelector<HTMLElement>(`[data-select-filter="${id}"]`)!);

function Menu({ initial, assembly, posable, onChange = () => {}, onConnectedChange = () => {} }: {
  initial: readonly string[], assembly: boolean, posable: boolean, onChange?(filter: readonly string[]): void,
  onConnectedChange?(id: string, checked: boolean): void }) {
  const [value, setValue] = useState(initial);
  return <SelectModeMenu value={value} onChange={(next: readonly string[]) => { setValue(next); onChange(next); }}
    assembly={assembly} posable={posable} connected={{ edgeChain: true, tangentFaces: true }} onConnectedChange={onConnectedChange} />;
}

it('Select\'s selection filter is the strip\'s chevron: Select all over a checkbox per kind, each on its own, and it stays open', async () => {
  const user = userEvent.setup();
  const change = vi.fn(), connectedChange = vi.fn();
  // A STEP opens with every kind ticked, Parts too, which a part file's menu does not offer.
  expect(STEP_SELECT_DEFAULT).toEqual(['parts', 'faces', 'edges', 'position', 'annotation', 'measurement']);
  render(<Menu initial={STEP_SELECT_DEFAULT} assembly={false} posable onChange={change} onConnectedChange={connectedChange} />);
  const button = screen.getByRole('button', { name: 'Selection filter: everything' });
  // The button is the strip's narrow chevron beside the tool, as a design tool's toolbar has it.
  expect([glyphs(button), !!button.querySelector('svg.lucide-chevron-down'), button.classList.contains('w-3'),
    button.getAttribute('data-select-filter-trigger')]).toEqual([[], true, true, 'all']);
  await user.click(button);
  expect(menu().getAttribute('aria-label')).toBe('Selection filter');
  // Headed by its name; no Parts outside an assembly, Position because the file has joints.
  const label = menu().querySelector('[data-slot=dropdown-menu-label]')!;
  expect([label.textContent, label.compareDocumentPosition(menu().querySelector('[data-select-filter]')!) & Node.DOCUMENT_POSITION_FOLLOWING])
    .toEqual(['Selection filter', Node.DOCUMENT_POSITION_FOLLOWING]);
  expect(filterItems()).toEqual([['Select all', 'true'], ['Faces', 'true'], ['Edges', 'true'],
    ['Position', 'true'], ['Annotations', 'true'], ['Measurement', 'true']]);
  // Faces, Edges and the two grouping options each their own glyph.
  expect(glyphs(menu())).toEqual(['faces', 'edges', 'groupEdges', 'groupFaces']);
  expect(badges(document.body)).toEqual([]);
  // Faces and Edges ticked: both grouping options apply, after a rule.
  expect(groupItems()).toEqual(['Group edges', 'Group faces']);
  // Each kind on its own; the menu stays open, so several change in one go, and Select all is a dash.
  await tick(user, 'edges');
  expect(change).toHaveBeenLastCalledWith(['parts', 'faces', 'position', 'annotation', 'measurement']);
  await tick(user, 'annotation');
  await tick(user, 'measurement');
  expect(screen.getByRole('button', { name: 'Selection filter: Faces, Position' })).toBeTruthy();
  expect(filterItems()[0]).toEqual(['Select all', 'mixed']);
  expect(!!document.querySelector('[data-select-filter=all] svg.lucide-minus')).toBe(true);
  // Faces grows by tangency only: Group edges does nothing here, so it is not offered.
  expect(groupItems()).toEqual(['Group faces']);
  await user.click(screen.getByRole('menuitemcheckbox', { name: 'Group faces' }));
  expect(connectedChange).toHaveBeenCalledWith('tangentFaces', false);
  // Every kind can go; Select all ticks them all, and pressed again, none.
  await tick(user, 'faces');
  await tick(user, 'position');
  expect([screen.getByRole('button', { name: 'Selection filter: nothing' }).getAttribute('data-select-filter-trigger'),
    filterItems()[0][1], groupItems()]).toEqual(['parts', 'false', []]);
  await tick(user, 'all');
  expect(change).toHaveBeenLastCalledWith(['faces', 'edges', 'position', 'annotation', 'measurement']);
  expect(screen.getByRole('button', { name: 'Selection filter: everything' })).toBeTruthy();
  await tick(user, 'all');
  expect(change).toHaveBeenLastCalledWith([]);
  expect(screen.getByRole('menu')).toBeTruthy();
});

it('an assembly offers Parts, a file with no joints offers no Position, and with no topology ticked nothing groups', async () => {
  const user = userEvent.setup();
  render(<Menu initial={['parts', 'annotation']} assembly posable={false} />);
  await user.click(screen.getByRole('button', { name: 'Selection filter: Parts, Annotations' }));
  expect(filterItems().map(([label]) => label)).toEqual(['Select all', 'Parts', 'Faces', 'Edges', 'Annotations', 'Measurement']);
  expect([groupItems(), menu().querySelectorAll('[role=separator]').length]).toEqual([[], 1]);
});

it('the strip shows Select as the plain pointer and Measure as its ruler, and opens no menu', async () => {
  const user = userEvent.setup();
  const select = vi.fn();
  render(<FloatingToolBar tools={[
    { id: 'select', label: 'Select', active: true, icon: <SelectIcon aria-hidden="true" />, onSelect: select },
    { id: 'measure', label: 'Measure', active: false, icon: <MeasureIcon aria-hidden="true" />, onSelect: () => {} }]} />);
  const button = screen.getByRole('button', { name: 'Select', exact: true });
  expect(button.querySelector('[data-select-mode]')).toBeNull();
  expect(badges(document.body)).toEqual(['select:', 'measure:']);
  await user.click(button);
  expect(select).toHaveBeenCalledOnce();
  expect(screen.queryByRole('menu')).toBeNull();
});
