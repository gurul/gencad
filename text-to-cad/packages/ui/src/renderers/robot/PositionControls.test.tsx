import React from 'react';
import { act, cleanup, fireEvent, render as mount, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PositionControls from '../../../dist/renderers/robot/PositionControls.js';
import { createPoseStore } from '../../../dist/renderers/robot/poseStore.js';
import FileSidebar from '../../../dist/renderers/kit/tools/FileSidebar.js';
import ToolPanel from '../../../dist/renderers/kit/tools/ToolPanel.js';

Object.assign(globalThis, { React });
// The slider primitive measures its thumb.
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(cleanup);

const joint = (name: string, type: string, extra = {}) => ({ name, type, parentLink: 'base', childLink: `${name}_link`, axis: [0, 0, 1], defaultValueDeg: 0, minValueDeg: -90, maxValueDeg: 90, ...extra });
const description = {
  joints: [joint('shoulder', 'revolute'), joint('lift', 'prismatic', { minValueDeg: 0, maxValueDeg: 0.3 }), joint('mount', 'fixed'),
    joint('follower', 'revolute', { mimic: { joint: 'shoulder', multiplier: 1, offset: 0 } })],
  srdf: { groupStates: [{ name: 'raised', group: 'arm', jointValuesByName: { shoulder: Math.PI / 4, lift: 0.2 } }] },
};
const render = (controls: React.ReactElement) => mount(<FileSidebar layout={{ panels: {}, collapsed: {} }} onLayoutChange={() => {}}>
  <ToolPanel id="position" title="Position" label="Position controls" fit="details">{controls}</ToolPanel>
</FileSidebar>);
const poseLabel = () => screen.getByRole('button', { name: /^Pose: / }).getAttribute('aria-label');
const field = (name: string, unit: string) => screen.getByRole('textbox', { name: `${name} value in ${unit}` }) as HTMLInputElement;

it('opens on the pose row, full width over a slider per joint a person can drive, and Reset in the section\'s heading', () => {
  const pose = createPoseStore(description);
  render(<PositionControls pose={pose}/>);
  // One section's rows: the Position section around them is the panel's.
  expect(screen.getAllByRole('heading').map(heading => heading.textContent)).toEqual(['Position']);
  expect(poseLabel()).toBe('Pose: Default');
  // The pose is the body's first row, not the heading's.
  expect([document.querySelector('[data-sidebar-head] [data-pose-menu]'), document.querySelector('[data-tool-panel-body] [data-pose-row] [data-pose-menu]') !== null]).toEqual([null, true]);
  expect([field('shoulder', 'deg').value, field('lift', 'm').value]).toEqual(['0°', '0 m']);
  expect(screen.queryByRole('textbox', { name: /mount|follower/ })).toBeNull();
  // Reset is the heading's, idle at the default pose, and takes a moved joint back.
  const reset = screen.getByRole('button', { name: 'Reset position' });
  expect([reset.closest('[data-sidebar-head]') !== null, (reset as HTMLButtonElement).disabled]).toEqual([true, true]);
  act(() => { pose.write(pose.joints[0], 30); });
  expect([poseLabel(), (reset as HTMLButtonElement).disabled]).toEqual(['Pose: Custom', false]);
  fireEvent.click(reset);
  expect([pose.getSnapshot().values, poseLabel()]).toEqual([{ shoulder: 0, lift: 0 }, 'Pose: Default']);
  // Each thumb is named for its joint, as its number field is.
  expect(screen.getAllByRole('slider').map(thumb => thumb.getAttribute('aria-label'))).toEqual(['shoulder', 'lift']);
});

it('a plain description has no pose row, and one with nothing to move says so', () => {
  render(<PositionControls pose={createPoseStore({ joints: [joint('shoulder', 'revolute')] })}/>);
  expect(poseLabel()).toBe('Pose: Default');
  expect(field('shoulder', 'deg').value).toBe('0°');
  cleanup();
  render(<PositionControls pose={createPoseStore({ joints: [joint('mount', 'fixed')] })}/>);
  expect(screen.getByText('No movable joints.')).toBeTruthy();
});

it('follows the pose store, and writes to it: a typed value is clamped, and a reset shows the defaults', () => {
  const pose = createPoseStore(description);
  render(<PositionControls pose={pose}/>);
  act(() => { pose.write(pose.joints[0], 30); });
  expect(field('shoulder', 'deg').value).toBe('30°');
  fireEvent.change(field('lift', 'm'), { target: { value: '5' } });
  fireEvent.blur(field('lift', 'm'));
  expect(pose.getSnapshot().values.lift).toBe(0.3);
  act(() => { pose.selectGroupState(pose.groupStates[0]); });
  expect(poseLabel()).toBe('Pose: raised');
  act(() => { pose.reset(); });
  expect(pose.getSnapshot().values).toEqual({ shoulder: 0, lift: 0 });
  expect(poseLabel()).toBe('Pose: Default');
});
