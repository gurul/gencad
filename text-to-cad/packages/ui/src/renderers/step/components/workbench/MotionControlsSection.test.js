import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPositionSection } from './MotionControlsSection.js';
import PoseControlsSection from './PoseControlsSection.js';
import { KinematicsPoseRow, NO_PRESET_VALUE } from '../../../kit/inspector/kinematicsControls.jsx';
import { FileSheetSliderField } from '../../../kit/inspector/FileSheet.js';
import { elements } from '../../../../../scripts/reactHarness.mjs';

// A definition as the main motion hook holds it: one parameter and one named pose.
const parameters = [{ id: 'hinge', label: 'Hinge', type: 'number', unit: 'deg', min: 0, max: 90, defaultValue: 0 }];
const definition = { url: '/hinge.step.json', parameters, parameterMap: new Map(parameters.map(parameter => [parameter.id, parameter])),
  defaultParameterValues: { hinge: 0 }, manifest: { poses: { rest: { hinge: 0 } } } };

test('Position is poses and joints: without a pose runtime there is no section', () => {
  assert.equal(buildPositionSection(), null);
  for (const props of [{ poseRuntime: { definition } }, { poseRuntime: { error: 'Invalid joints' } }]) {
    const section = buildPositionSection(props);
    assert.equal(section.id, 'position');
    assert.equal(section.title, 'Position');
    assert.deepEqual(elements(section.content).filter(node => node.type === PoseControlsSection).length, 1);
  }
});

test('one global Reset calls the coordinated host command', () => {
  const calls = [];
  const pose = { definition, onResetMotion: () => calls.push('both'), onResetParameters: () => calls.push('wrong') };
  const section = buildPositionSection({ poseRuntime: pose });
  const controls = elements(section.content).find(node => node.type === PoseControlsSection);
  const header = elements(PoseControlsSection(controls.props)).find(node => node.type === KinematicsPoseRow);
  header.props.onReset();
  assert.deepEqual(calls, ['both']);
  // The Pose row's Default is the only way back: no X to hand the panel, and no heading button.
  assert.equal('onReset' in section, false, 'no X of its own');
  assert.equal('actions' in section, false, 'no Reset button of its own');
});

test("the pose row and the joints are ONE section's rows, with no section of their own; the pose row, with Default, leads any joints", () => {
  const rows = def => elements(PoseControlsSection({ runtime: { definition: def } }));
  const kinds = def => rows(def).filter(node => [KinematicsPoseRow, FileSheetSliderField].includes(node.type)).map(node => node.type);
  assert.deepEqual(kinds(definition), [KinematicsPoseRow, FileSheetSliderField]);
  assert.deepEqual(kinds({ ...definition, parameters: [] }), [KinematicsPoseRow]);
  // With no named pose, the row still offers Default: the way back to the opening pose.
  assert.deepEqual(kinds({ ...definition, manifest: { poses: {} } }), [KinematicsPoseRow, FileSheetSliderField]);
});

test('animation-owned authored values do not claim a named position, and parameters stay editable', () => {
  const onParameterChange = () => {};
  const content = PoseControlsSection({ runtime: { definition, parameterValues: { hinge: 0 }, positionActive: false, onParameterChange } });
  const nodes = elements(content);
  assert.equal(nodes.find(node => node.type === KinematicsPoseRow).props.activeValue, NO_PRESET_VALUE);
  assert.equal(nodes.find(node => node.type === FileSheetSliderField).props.disabled, undefined);
  assert.equal(nodes.some(node => node.props.title === 'Transition'), false);
});
