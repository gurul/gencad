import assert from 'node:assert/strict';
import test from 'node:test';

import { lookSubjectForReference } from './lookAtReference.js';

/** A STEP face or edge as what a double-click looks at: its kind from its topology row, its points from the proxy. */

// One square face (two triangles at z = 8) and one straight edge, in the proxy's arrays.
const selectorRuntime = { proxy: {
  facePositions: Float32Array.from([0, 0, 8, 10, 0, 8, 10, 10, 8, 0, 10, 8]),
  faceIndices: Uint32Array.from([0, 1, 2, 0, 2, 3]),
  edgePositions: Float32Array.from([0, 0, 8, 10, 0, 8, 10, 10, 8]),
  edgeIndices: Uint32Array.from([0, 1, 1, 2]),
} };
const face = pickData => ({ selectorType: 'face', pickData: { selectorType: 'face', triangleStart: 0, triangleCount: 2, ...pickData } });
const edge = pickData => ({ selectorType: 'edge', pickData: { selectorType: 'edge', segmentStart: 0, segmentCount: 1, ...pickData } });

test("a planar face is a plane by its normal; a cylinder's side a cylinder by its axis, origin and radius; any other face free", () => {
  const plane = lookSubjectForReference(null, selectorRuntime, face({ surfaceType: 'plane', normal: [0, 0, 1] }));
  assert.equal(plane.kind, 'plane');
  assert.deepEqual(plane.normal, [0, 0, 1]);
  assert.equal(plane.points.length, 6);
  const cylinder = lookSubjectForReference(null, selectorRuntime, face({ surfaceType: 'cylinder', params: { axis: [0, 0, 1], origin: [5, 5, 0], radius: 5 } }));
  assert.deepEqual([cylinder.kind, cylinder.axis, cylinder.origin, cylinder.radius], ['cylinder', [0, 0, 1], [5, 5, 0], 5]);
  assert.equal(lookSubjectForReference(null, selectorRuntime, face({ surfaceType: 'bsplinesurface' })).kind, 'free');
});

test('a straight edge is a line, a circle a circle by its axis and centre; a row without them is read off its polyline', () => {
  const line = lookSubjectForReference(null, selectorRuntime, edge({ curveType: 'line', params: { direction: [1, 0, 0], origin: [0, 0, 8] } }));
  assert.deepEqual([line.kind, line.direction, line.points], ['line', [1, 0, 0], [[0, 0, 8], [10, 0, 8]]]);
  const circle = lookSubjectForReference(null, selectorRuntime, edge({ curveType: 'circle', params: { axis: [0, 0, 1], center: [5, 5, 8], radius: 5 } }));
  assert.deepEqual([circle.kind, circle.axis, circle.center], ['circle', [0, 0, 1], [5, 5, 8]]);
  assert.equal(lookSubjectForReference(null, selectorRuntime, edge({ curveType: 'line' })).kind, 'line', 'no params: straight by its points');
  const bent = lookSubjectForReference(null, selectorRuntime, edge({ curveType: 'bsplinecurve', segmentCount: 2 }));
  assert.equal(bent.kind, 'free');
});
