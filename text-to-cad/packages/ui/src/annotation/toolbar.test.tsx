import React from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { useAnnotationSession } from './session.js';
import { ANNOTATION_COLORS, AnnotationToolbar, annotationColors } from './toolbar.jsx';
import { SUB_TOOLBAR_WIDTH_CLASS } from '../renderers/kit/tools/SubToolbar.jsx';

afterEach(cleanup);

let session: ReturnType<typeof useAnnotationSession>;
const history = { canUndo: false, canRedo: false, undo() {}, redo() {} };
function Panel({ colorScheme = 'light' }: { colorScheme?: 'light' | 'dark' }) {
  session = useAnnotationSession(true);
  return <AnnotationToolbar annotation={session} history={history} colorScheme={colorScheme} />;
}

it("Annotate's controls, two rows at the sub-toolbars' one width: every tool a button, over what is drawn next as dropdowns, placement among them, then Undo, Redo and Clear", async () => {
  render(<Panel />);
  const row = screen.getByRole('toolbar', { name: 'Annotation controls' });
  const label = (element: Element) => element.getAttribute('role') === 'separator' ? '|' : element.getAttribute('aria-label');
  // No rule between the halves: they are two rows, one over the other, whatever the view's width.
  expect([...row.querySelectorAll('[role=group], [role=separator]')].map(label))
    .toEqual(['Annotation tools', 'Annotation style', 'Annotation history']);
  expect(row.className.split(/\s+/)).toEqual(expect.arrayContaining(['flex-col', ...SUB_TOOLBAR_WIDTH_CLASS.split(/\s+/)]));
  expect([...row.children].map(child => child.getAttribute('role') === 'group' ? child.getAttribute('aria-label')
    : [...child.querySelectorAll('[role=group]')].map(group => group.getAttribute('aria-label')).join(' + ')))
    .toEqual(['Annotation tools', 'Annotation style + Annotation history']);
  expect(within(screen.getByRole('group', { name: 'Annotation tools' })).getAllByRole('button').map(button => button.getAttribute('aria-label')))
    .toEqual(['Pen', 'Line', 'Arrow', 'Rectangle', 'Ellipse', 'Text', 'Eraser']);
  expect(within(screen.getByRole('group', { name: 'Annotation history' })).getAllByRole('button').map(button => button.getAttribute('aria-label')))
    .toEqual(['Undo', 'Redo', 'Clear annotations']);
  const settings = screen.getByRole('group', { name: 'Annotation style' });
  expect(within(settings).getAllByRole('button').map(button => button.getAttribute('aria-label')))
    .toEqual(['Color', 'Stroke width', 'Line style', 'Placement']);
  expect(session.placement).toBe('surface');
  fireEvent.pointerDown(within(settings).getByRole('button', { name: 'Placement' }), { button: 0, ctrlKey: false });
  const menu = await screen.findByRole('menu', { name: 'Placement' });
  expect(within(menu).getAllByRole('menuitemradio').map(item => [item.getAttribute('aria-label'), item.getAttribute('aria-checked')]))
    .toEqual([['Draw on surface', 'true'], ['Draw on plane', 'false']]);
  fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'Draw on plane' }));
  expect(session.placement).toBe('space');
});

it('Stroke width and Line style are rows of glyphs, each named, the current one marked', async () => {
  render(<Panel />);
  const choices = async (name: string) => {
    fireEvent.pointerDown(screen.getByRole('button', { name }), { button: 0, ctrlKey: false });
    const menu = await screen.findByRole('menu', { name });
    return { menu, items: [...menu.querySelectorAll('[data-style-option]')].map(item =>
      [item.getAttribute('aria-label'), item.getAttribute('data-style-option'), item.hasAttribute('data-checked'), item.textContent]) };
  };
  const width = await choices('Stroke width');
  expect(width.items).toEqual([['Thin', '1', false, ''], ['Medium', '2', true, ''], ['Bold', '4', false, '']]);
  fireEvent.click(within(width.menu).getByRole('menuitem', { name: 'Bold' }));
  expect(session.strokeWidth).toBe(4);
  const dash = await choices('Line style');
  expect(dash.items.map(([label, value, checked, text]) => [value, checked, text])).toEqual([['solid', true, ''], ['dashed', false, ''], ['dotted', false, '']]);
  fireEvent.click(within(dash.menu).getByRole('menuitem', { name: dash.items[1][0]! }));
  expect(session.strokeStyle).toBe('dashed');
});

it('the colours are the neons and the one neutral that reads against the viewer: white in dark mode, black in light', () => {
  const labels = (scheme: 'light' | 'dark') => annotationColors(scheme).map(option => option.label);
  const neons = ANNOTATION_COLORS.slice(0, 7).map(option => option.label);
  expect([labels('dark'), labels('light')]).toEqual([[...neons, 'White'], [...neons, 'Black']]);
});

it('Color is a grid of the scheme\'s swatches, the current one marked, then a custom colour from the system picker', async () => {
  render(<Panel colorScheme="dark" />);
  const open = async () => {
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Color' }), { button: 0, ctrlKey: false });
    return screen.findByRole('menu', { name: 'Color' });
  };
  let menu = await open();
  const neons = ANNOTATION_COLORS.slice(0, 7).map(option => option.label);
  expect(within(menu).getAllByRole('menuitem').map(item => item.getAttribute('aria-label'))).toEqual([...neons, 'White', 'Custom color']);
  expect([...menu.querySelectorAll('[data-checked]')].map(item => item.getAttribute('aria-label'))).toEqual(['Neon red']);
  fireEvent.click(within(menu).getByRole('menuitem', { name: 'Neon green' }));
  expect(session.color).toBe('#39ff14');
  menu = await open();
  expect([...menu.querySelectorAll('[data-checked]')].map(item => item.getAttribute('aria-label'))).toEqual(['Neon green']);
  // The picker's colour is taken as it closes.
  const picker = document.querySelector<HTMLInputElement>('input[type=color][data-color-picker]')!;
  picker.value = '#123456';
  fireEvent.change(picker);
  expect(session.color).toBe('#123456');
});
