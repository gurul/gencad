import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import PreviewChrome from '../../../../dist/renderers/kit/tools/PreviewChrome.js';

afterEach(cleanup);
it('keeps editor controls hidden throughout Preview and restores them on exit', () => {
  const { container, rerender } = render(<PreviewChrome active><button>Tool</button></PreviewChrome>);
  const chrome = container.querySelector('[data-preview-chrome]')!;
  expect(chrome.hasAttribute('hidden')).toBe(true);
  expect(chrome.hasAttribute('inert')).toBe(true);
  fireEvent.pointerMove(document.body);
  expect(screen.queryByRole('button', { name: 'Tool' })).toBeNull();
  rerender(<PreviewChrome active={false}><button>Tool</button></PreviewChrome>);
  expect(chrome.hasAttribute('hidden')).toBe(false);
  expect(chrome.hasAttribute('inert')).toBe(false);
  expect(screen.getByRole('button', { name: 'Tool' })).toBeTruthy();
});

it("puts Preview's own controls in its corner, and its panel under them, only while it is up", () => {
  const view = render(<PreviewChrome active end={<button>Exit preview</button>} panel={<div data-testid="settings" />} />);
  expect(screen.getByRole('button', { name: 'Exit preview' }).closest('[data-preview-corner]')).not.toBeNull();
  expect(screen.getByTestId('settings').closest('[data-preview-panel]')).not.toBeNull();
  view.rerender(<PreviewChrome active={false} end={<button>Exit preview</button>} panel={<div data-testid="settings" />} />);
  expect(view.container.querySelector('[data-preview-controls]')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Exit preview' })).toBeNull();
});
