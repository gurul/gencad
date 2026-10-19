import assert from "node:assert/strict";
import test from "node:test";

import { measureLabelText, measurementMark } from "./measureDimension.js";
import { measurementFromPicks } from "./measurement.js";
import { meshMeasurePick } from "./meshMeasure.js";
import { GLB_SCENE_UNITS, threeMfSceneUnits } from "./sceneUnits.js";

// A camera looking straight down at a 100-unit triangle, one pixel a unit.
const project = ([x, y]) => ({ x, y });
const hit = { id: "n3", point: [40, 30, 0], triangle: [[0, 0, 0], [100, 0, 0], [0, 100, 0]] };

test("a pick on a triangle snaps to its corner, else to its side, else stays on its face", () => {
  const mm = threeMfSceneUnits("millimeter");
  assert.deepEqual(meshMeasurePick({ ...hit, point: [4, 3, 0] }, { x: 4, y: 3 }, project, mm), {
    point: [0, 0, 0], snapKind: "vertex", referenceId: "n3:v0.000000,0.000000,0.000000", units: mm, approximate: true });
  const side = meshMeasurePick({ ...hit, point: [40, 3, 0] }, { x: 40, y: 3 }, project, mm);
  assert.deepEqual([side.snapKind, side.point], ["edge", [40, 0, 0]]);
  const face = meshMeasurePick(hit, { x: 40, y: 30 }, project, mm);
  assert.deepEqual([face.snapKind, face.point], ["surface", [40, 30, 0]]);
  assert.equal(meshMeasurePick({ id: "n3", point: [1, 1, 1] }, { x: 1, y: 1 }, project, mm), null, "no triangle, no pick");
});

test("a mesh's length is in its file's unit and says it is approximate, wherever it is read", () => {
  // A GLB's scene is in millimetres; its file is in metres.
  const a = meshMeasurePick({ ...hit, point: [0.5, 0.5, 0] }, { x: 0.5, y: 0.5 }, project, GLB_SCENE_UNITS);
  const b = meshMeasurePick({ ...hit, point: [99.5, 0.5, 0] }, { x: 99.5, y: 0.5 }, project, GLB_SCENE_UNITS);
  const measurement = measurementFromPicks(a, b);
  assert.deepEqual([measurement.euclidean, measurement.unit, measurement.approximate, measurement.perpendicular], [0.1, "m", true, null]);
  assert.equal(measureLabelText(measurement), "≈ 0.1000 m");
  assert.equal(measurementMark({ pickA: a, pickB: b, measurement, colorIndex: 0 }).label, "≈ 0.1000 m", "what a snapshot draws and a job carries");
  assert.equal(measureLabelText(measurementFromPicks({ point: [0, 0, 0] }, { point: [3, 4, 0] })), "5.00 mm", "a STEP's stays exact");
});

test("a 3MF's declared unit is one of the 3MF unit names", () => {
  assert.throws(() => threeMfSceneUnits("furlong"), /micron, millimeter, centimeter, inch, foot, meter/);
});
