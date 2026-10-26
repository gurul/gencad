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
const groupItems = () => screen.queryAllByRole('menuitemcheckbox').map(item => item.textContent);
const choose = (user: ReturnType<typeof userEvent.setup>, id: string) => user.click(document.querySelector<HTMLElement>(`[data-select-filter="${id}"]`)!);
const open = (user: ReturnType<typeof userEvent.setup>) => user.click(document.querySelector<HTMLElement>('[data-select-filter-trigger]')!);

function Menu({ initial, assembly, posable, onChange = () => {}, onConnectedChange = () => {} }: {
  initial: readonly string[], assembly: boolean, posable: boolean, onChange?(filter: readonly string[]): void,
  onConnectedChange?(id: string, checked: boolean): void }) {
  const [value, setValue] = useState(initial);
  return <SelectModeMenu value={value} onChange={(next: readonly string[]) => { setValue(next); onChange(next); }}
    assembly={assembly} posable={posable} connected={{ edgeChain: true, tangentFaces: true }} onConnectedChange={onConnectedChange} />;
}

it('Select\'s menu is the strip\'s chevron: one choice of what a click takes, All or one kind alone', async () => {
  const user = userEvent.setup();
  const change = vi.fn(), connectedChange = vi.fn();
  // A STEP opens on All: Parts too, which a part file's menu offers no mode of its own.
  expect(STEP_SELECT_DEFAULT).toEqual(['parts', 'faces', 'edges', 'position', 'annotation', 'measurement']);
  render(<Menu initial={STEP_SELECT_DEFAULT} assembly={false} posable onChange={change} onConnectedChange={connectedChange} />);
  const button = screen.getByRole('button', { name: 'Selection filter: everything' });
  // The button is the strip's narrow chevron beside the tool, as a design tool's toolbar has it.
  expect([glyphs(button), !!button.querySelector('svg.lucide-chevron-down'), button.classList.contains('w-3'),
    button.getAttribute('data-select-filter-trigger')]).toEqual([[], true, true, 'all']);
  await user.click(button);
  expect(menu().getAttribute('aria-label')).toBe('Selection filter');
  // Headed "Pick"; no Parts outside an assembly, Position because the file has joints; one chosen.
  const label = menu().querySelector('[data-slot=dropdown-menu-label]')!;
  expect([label.textContent, label.compareDocumentPosition(menu().querySelector('[data-select-filter]')!) & Node.DOCUMENT_POSITION_FOLLOWING])
    .toEqual(['Pick', Node.DOCUMENT_POSITION_FOLLOWING]);
  expect(screen.getAllByRole('menuitemradio').length).toBe(4);
  expect(filterItems()).toEqual([['All', 'true'], ['Faces', 'false'], ['Edges', 'false'], ['Position', 'false']]);
  // All is the pointer; Faces and Edges, and the two grouping options, each their own glyph.
  expect(glyphs(menu())).toEqual(['select', 'faces', 'edges', 'groupEdges', 'groupFaces']);
  // All picks faces and edges: both grouping options apply, after a rule.
  expect(groupItems()).toEqual(['Group edges', 'Group faces']);
  await user.click(screen.getByRole('menuitemcheckbox', { name: 'Group faces' }));
  expect(connectedChange).toHaveBeenCalledWith('tangentFaces', false);
  // A choice is the kind alone, and puts the menu away; the chevron names it.
  await choose(user, 'faces');
  expect(change).toHaveBeenLastCalledWith(['faces']);
  expect(screen.queryByRole('menu')).toBeNull();
  expect(screen.getByRole('button', { name: 'Selection filter: Faces' }).getAttribute('data-select-filter-trigger')).toBe('faces');
  // Faces grows by tangency only: Group edges does nothing here, so it is not offered.
  await open(user);
  expect(groupItems()).toEqual(['Group faces']);
  await choose(user, 'position');
  expect(change).toHaveBeenLastCalledWith(['position']);
  await open(user);
  expect(groupItems()).toEqual([]);
  await choose(user, 'all');
  expect(change).toHaveBeenLastCalledWith(STEP_SELECT_DEFAULT);
});

it('an assembly offers Parts, and a file with no joints no Position', async () => {
  const user = userEvent.setup();
  render(<Menu initial={['parts']} assembly posable={false} />);
  await user.click(screen.getByRole('button', { name: 'Selection filter: Parts' }));
  expect(filterItems()).toEqual([['All', 'false'], ['Parts', 'true'], ['Faces', 'false'], ['Edges', 'false']]);
  expect([groupItems(), menu().querySelectorAll('[role=separator]').length]).toEqual([[], 0]);
});

it('the strip badges Select and Measure with the kind they pick alone, and none for All', () => {
  render(<FloatingToolBar tools={[
    { id: 'select', label: 'Select', active: true, icon: <SelectIcon mode="faces" aria-hidden="true" />, onSelect: () => {} },
    { id: 'measure', label: 'Measure', active: false, icon: <MeasureIcon mode="vertex" aria-hidden="true" />, onSelect: () => {} },
    { id: 'other', label: 'Other', active: false, icon: <MeasureIcon mode="all" aria-hidden="true" />, onSelect: () => {} }]} />);
  expect(badges(document.body)).toEqual(['select:faces', 'measure:points', 'measure:']);
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
