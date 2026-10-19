import React, { useRef, useState } from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { animationRenderFrame, buildDefaultAnimationState, findAnimationClip } from '@text-to-cad/core/common/animationClock.js';
import { createAnimationClock } from '../../../../dist/renderers/step/workbench/animationClockStore.js';
import { useStepMotionControls } from '../../../../dist/renderers/step/workbench/useStepMotionControls.js';

const parameters = [
  { id: 'hinge', type: 'number', defaultValue: 5, min: -90, max: 90 },
  { id: 'slide', type: 'number', defaultValue: 2, min: 0, max: 100 },
];
const definition = { parameters, parameterMap: Object.fromEntries(parameters.map(p => [p.id, p])),
  defaultParameterValues: { hinge: 5, slide: 2 }, manifest: { poses: { open: { hinge: 80 }, closed: { hinge: -20, slide: 7 } } } };
const clips = { turn: { id: 'turn', duration: 4, loop: true, update() {} }, close: { id: 'close', duration: 2, loop: false, update() {} } };
let frames: Map<number, FrameRequestCallback>;
beforeEach(() => {
  frames = new Map(); let id = 0;
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frames.set(++id, callback); return id; });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(id => { frames.delete(id); });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function advance(ms = 100) {
  const queued = [...frames.values()]; frames.clear();
  act(() => queued.forEach(frame => frame(performance.now() + ms)));
}
// The host's side: which motion each claim named.
function setup(initialClips: any = clips) {
  const clock = createAnimationClock();
  const used: string[] = [];
  const host = { onUse: (motion: string) => used.push(motion) };
  const hook = renderHook(({ modelClips }) => {
    const [animation, setAnimation] = useState(buildDefaultAnimationState(modelClips));
    const [values, setValues] = useState(definition.defaultParameterValues);
    const [pose, setPose] = useState('');
    const animationRef = useRef(animation), valuesRef = useRef(values), revision = useRef(0);
    const commands = useStepMotionControls({ selectedStepModuleDefinition: definition,
      selectedAnimationClips: modelClips, selectedActiveAnimationClip: findAnimationClip(modelClips, animation.activeClipId),
      animationState: animation, animationStateRef: animationRef, setAnimationState: setAnimation,
      stepModuleParameterValuesRef: valuesRef, setStepModuleParameterValues: setValues,
      setAppliedStepPoseName: setPose, motionRevisionRef: revision, clock, host });
    return { ...commands, animation, values, pose, animationRef, valuesRef,
      frame: animationRenderFrame({ ...animation, clip: findAnimationClip(modelClips, animation.activeClipId) }) };
  }, { initialProps: { modelClips: initialClips } });
  return { ...hook, clock, used };
}

// The transport preferences the Playback settings set: not the defaults, so keeping them shows.
const preferences = { activeClipId: 'close', speed: 2, loopEnabled: true };
const pickPreferences = (result: any) => act(() => {
  result.current.handleAnimationClipSelect('close'); result.current.handleAnimationSpeedChange(2); result.current.handleAnimationLoopToggle(true);
});

it('a parameter edit stops live playback, keeps its transport preferences, resets its clock, and rejects an already queued frame', () => {
  const { result, clock } = setup();
  pickPreferences(result);
  act(() => result.current.handleAnimationPlayToggle()); advance();
  expect(clock.getAnimationClock()).toBeGreaterThan(0);
  const stale = [...frames.values()];
  act(() => result.current.handleStepModuleParameterChange('hinge', 30));
  expect(result.current.animation).toEqual({ ...preferences, enabled: false, playing: false, elapsedSec: 0 });
  expect(result.current.frame).toBeNull();
  expect(result.current.values).toEqual({ hinge: 30, slide: 2 });
  act(() => stale.forEach(frame => frame(performance.now() + 1000)));
  expect(clock.getAnimationClock()).toBe(0);
  expect(result.current.values.hinge).toBe(30);
  // The next play is the routine the person chose, as they set it up, from its start.
  act(() => result.current.handleAnimationPlayToggle());
  expect(result.current.animation).toEqual({ ...preferences, enabled: true, playing: true, elapsedSec: 0 });
});

it('putting the routine down keeps the transport preferences too', () => {
  const { result, clock } = setup();
  pickPreferences(result);
  act(() => result.current.handleAnimationPlayToggle()); advance();
  act(() => result.current.releaseAnimation());
  expect(result.current.animation).toEqual({ ...preferences, enabled: false, playing: false, elapsedSec: 0 });
  expect(clock.getAnimationClock()).toBe(0);
});

const routineCommands = (result: any): Record<string, () => void> => ({
  play: () => result.current.handleAnimationPlayToggle(), scrub: () => result.current.handleAnimationScrub(1),
  restart: () => result.current.handleAnimationRestart(),
});

it.each(['play', 'scrub', 'restart'])("%s in the tools view is a use of the routine: it plays from the model at rest, and the host takes Explode off", command => {
  const { result, used } = setup();
  act(() => result.current.handleApplyPose('open'));
  act(() => routineCommands(result)[command]());
  expect([result.current.values.hinge, result.current.pose, result.current.animation.enabled]).toEqual([5, '', true]);
  expect(used).toEqual(['position', 'animation']);
});

it.each(['clip', 'speed', 'loop'])('%s is how the routine plays, not a use of it: the pose and Explode stay', command => {
  const { result, used } = setup();
  act(() => result.current.handleApplyPose('open'));
  act(() => {
    const actions: Record<string, () => void> = {
      clip: () => result.current.handleAnimationClipSelect('close'),
      speed: () => result.current.handleAnimationSpeedChange(2), loop: () => result.current.handleAnimationLoopToggle(false),
    };
    actions[command]();
  });
  expect(result.current.values.hinge).toBe(80);
  expect(result.current.pose).toBe('open');
  expect(result.current.frame).toBeNull();
  expect(used).toEqual(['position']);
});

it('numeric edits leave the named pose behind, and successive batched edits preserve each other', () => {
  const { result } = setup();
  act(() => result.current.handleApplyPose('open'));
  expect(result.current.pose).toBe('open');
  act(() => { result.current.handleStepModuleParameterChange('hinge', 12); result.current.handleStepModuleParameterChange('slide', 22); });
  expect(result.current.values).toEqual({ hinge: 12, slide: 22 });
  expect(result.current.pose).toBe('');
});

it('selecting a named position after paused scrubbing resets animation and applies a complete preset', () => {
  const { result, clock } = setup();
  act(() => result.current.handleAnimationScrub(2));
  act(() => result.current.handleApplyPose('closed'));
  expect(result.current.values).toEqual({ hinge: -20, slide: 7 });
  expect(result.current.pose).toBe('closed'); expect(result.current.frame).toBeNull();
  expect(clock.getAnimationClock()).toBe(0);
  act(() => result.current.handleApplyPose('open'));
  expect(result.current.values).toEqual({ hinge: 80, slide: 2 });
});

it('parameter paste participates in the same ownership/reset contract', () => {
  const { result, clock } = setup();
  act(() => result.current.handleAnimationPlayToggle()); advance();
  act(() => result.current.applyStepModuleParameterValues({ hinge: 500, slide: 40, unknown: 9 }));
  expect(result.current.values).toEqual({ hinge: 90, slide: 40 });
  expect(result.current.frame).toBeNull(); expect(clock.getAnimationClock()).toBe(0);
});

it.each(['playback', 'position'])('global motion reset clears %s and all pending producers without claiming animation time zero', state => {
  const { result, clock } = setup();
  if (state === 'playback') {
    pickPreferences(result);
    act(() => result.current.handleAnimationPlayToggle());
    advance();
  } else { act(() => result.current.handleApplyPose('closed')); }
  const stale = [...frames.values()];
  act(() => result.current.resetMotion());
  act(() => stale.forEach(frame => frame(performance.now() + 500)));
  expect(result.current.values).toEqual(definition.defaultParameterValues);
  expect(result.current.pose).toBe(''); expect(result.current.frame).toBeNull();
  // Reset is Position's: it puts the model at rest and stops the routine, and leaves the routine's
  // transport preferences as the person set them.
  expect(result.current.animation).toEqual({ ...(state === 'playback' ? preferences : buildDefaultAnimationState(clips)),
    enabled: false, playing: false, elapsedSec: 0 });
  expect(clock.getAnimationClock()).toBe(0);
});

it('rapid animation → parameters → animation plays again from zero, from the model at rest', () => {
  const { result, clock } = setup();
  act(() => result.current.handleAnimationPlayToggle()); advance();
  act(() => { result.current.handleStepModuleParameterChange('hinge', 45); result.current.handleAnimationPlayToggle(); });
  expect(result.current.values).toEqual({ hinge: 5, slide: 2 });
  expect(result.current.animation.playing).toBe(true); expect(clock.getAnimationClock()).toBe(0);
  advance(500); expect(clock.getAnimationClock()).toBeGreaterThan(0);
});

it('invalid stale selections do not reset the valid owner, and parameter-only files still work', () => {
  const { result } = setup(null);
  act(() => result.current.handleStepModuleParameterChange('hinge', 30));
  act(() => { result.current.handleAnimationPlayToggle(); result.current.handleApplyPose('missing'); result.current.handleStepModuleParameterChange('missing', 4); });
  expect(result.current.values.hinge).toBe(30);
  expect(result.current.animation.enabled).toBe(false);
  act(() => result.current.resetMotion()); expect(result.current.values).toEqual(definition.defaultParameterValues);
});

it('an unmounted view leaves no frame queued', () => {
  const { result, unmount } = setup();
  act(() => result.current.handleApplyPose('open'));
  act(() => result.current.handleAnimationPlayToggle());
  expect(frames.size).toBe(1);
  unmount(); expect(frames.size).toBe(0);
});

it('repeated animation adjustments do not rewrite unchanged authored parameter values', () => {
  const { result } = setup();
  act(() => result.current.handleAnimationScrub(1));
  const values = result.current.values;
  act(() => { result.current.handleAnimationScrub(2); result.current.handleAnimationSpeedChange(2); });
  expect(result.current.values).toBe(values);
});

it('every pose write lands at once and asks for no frame: a value, a named pose, Reset', () => {
  const { result } = setup();
  // A slider, a typed number and a Pose knob all arrive as a parameter change.
  act(() => result.current.handleStepModuleParameterChange('hinge', 47));
  expect(result.current.values).toEqual({ hinge: 47, slide: 2 });
  act(() => result.current.handleApplyPose('closed'));
  expect(result.current.values).toEqual({ hinge: -20, slide: 7 });
  act(() => result.current.handleResetStepModuleParameters());
  expect(result.current.values).toEqual({ hinge: 5, slide: 2 });
  expect(frames.size).toBe(0);
});

it('Position used puts the routine at rest, and each use tells the host to take Explode off', () => {
  const { result, used } = setup();
  act(() => result.current.handleAnimationScrub(2));
  act(() => result.current.handleStepModuleParameterChange('slide', 9));
  expect(result.current.values).toEqual({ hinge: 5, slide: 9 });
  expect(result.current.frame).toBeNull();
  expect(used).toEqual(['animation', 'position']);
});
