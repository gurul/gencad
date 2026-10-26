import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useStepPreviewMotion } from '../../../../dist/renderers/step/workbench/useStepPreviewMotion.js';

const parameters = [{ id: 'hinge', type: 'number', defaultValue: 5, min: -90, max: 90 }];
const definition = { parameters, parameterMap: { hinge: parameters[0] }, defaultParameterValues: { hinge: 5 },
  manifest: { poses: { open: { hinge: 80 } } } };
const clips = { turn: { id: 'turn', duration: 4, loop: true, update() {} } };
beforeEach(() => {
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1);
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("Preview's pose and routine are its own, on its own clock, and every opening starts at rest", () => {
  const { result, rerender } = renderHook(({ open }) => useStepPreviewMotion({ definition, clips, open }), { initialProps: { open: true } });
  expect(result.current.parameterValues).toEqual({ hinge: 5 });
  expect(result.current.animationControls.playing).toBe(false);
  act(() => result.current.positionControls.onApplyPose('open'));
  expect(result.current.parameterValues).toEqual({ hinge: 80 });
  act(() => result.current.animationControls.onPlayToggle());
  expect(result.current.animationControls.playing).toBe(true);
  act(() => result.current.clock.setAnimationClock(2));
  expect(result.current.animationControls.clock).toBe(result.current.clock);

  // Closed and opened again: the model as authored, the routine at rest at its start.
  rerender({ open: false });
  rerender({ open: true });
  expect(result.current.parameterValues).toEqual({ hinge: 5 });
  expect(result.current.animationControls.playing).toBe(false);
  expect(result.current.animationControls.activeClipId).toBe('turn');
  expect(result.current.clock.getAnimationClock()).toBe(0);
});
