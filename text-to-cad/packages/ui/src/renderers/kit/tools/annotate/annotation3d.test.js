import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';

import { normalizeAnnotation } from '@text-to-cad/core/common/annotation.js';
import { annotationDocumentOf, mountAnnotations, projectAnnotations } from './annotation3d.js';

/** Annotate's ink in 3D: drawn over one view, projected onto the parts under it, carried with them. */

// A 20 × 20 × 2 slab, part "slab" (top face at z = 0), and a 2 × 2 post, part "post", standing on it
// to z = 10, under an orthographic camera looking straight down: one screen pixel is one unit, and
// screen pixel (x, y) is world (x − 50, 50 − y).
function rig() {
  const scene = new THREE.Scene();
  const modelGroup = new THREE.Group();
  scene.add(modelGroup);
  const part = (id, geometry, z) => {
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
    mesh.userData.partId = id;
    mesh.position.set(0, 0, z);
    modelGroup.add(mesh);
    return mesh;
  };
  const slab = part('slab', new THREE.BoxGeometry(20, 20, 2), -1);
  const post = part('post', new THREE.BoxGeometry(2, 2, 10), 5);
  const camera = new THREE.OrthographicCamera(-50, 50, 50, -50, 0.1, 500);
  camera.position.set(0, 0, 100);
  camera.lookAt(0, 0, 0);
  scene.add(camera);
  scene.updateMatrixWorld(true);
  const renders = { count: 0 };
  const runtime = { THREE, scene, camera, modelGroup, controls: { target: new THREE.Vector3(0, 0, -30) }, modelRadius: 10,
    activeClipPlanes: [], Line2, LineGeometry, LineMaterial, requestRender() { renders.count += 1; } };
  return { runtime, slab, post, renders };
}
const size = { width: 100, height: 100 };
const stroke = (id, points) => ({ kind: 'stroke', id, points: points.map(([x, y]) => ({ x, y })), closed: false, color: '#ff0000', width: 2, opacity: 1, dash: 'solid' });
const along = (from, to, step = 1) => Array.from({ length: Math.round(Math.abs(to - from) / step) + 1 }, (_, index) => from + Math.sign(to - from) * index * step);
const worldOf = (item, part) => Array.from({ length: item.points.length / 3 },
  (_, index) => new THREE.Vector3().fromArray(item.points, index * 3).applyMatrix4(part ? part.matrixWorld : new THREE.Matrix4()));

test('a stroke lies on the part under it, in its frame, two pixels off the face; one over nothing lies in the air at the orbit target', () => {
  const { runtime, slab } = rig();
  const [onSlab, inAir] = projectAnnotations(runtime, [stroke('on', [[42, 55], [45, 55]]), stroke('off', [[5, 5], [10, 5]])], size);
  assert.equal(onSlab.part, 'slab');
  const [start] = worldOf(onSlab, slab);
  assert.ok(Math.abs(start.x + 8) < 1e-6 && Math.abs(start.y + 5) < 1e-6, 'where it was drawn');
  assert.ok(Math.abs(start.z - 2) < 1e-6, `on the face, lifted: ${start.z}`);
  assert.equal(inAir.part, null);
  assert.deepEqual([...inAir.points.slice(0, 3)].map(value => Math.round(value * 1000) / 1000), [-45, 45, -28]);
});

test('a stroke drawn in space lies on the plane just in front of the model, on no part, whatever is under it; one on the model beside it still lands on the model', () => {
  const { runtime, slab } = rig();
  const [inSpace, onModel] = projectAnnotations(runtime, [{ ...stroke('space', [[42, 55], [45, 55]]), placement: 'space' },
    { ...stroke('surface', [[42, 58], [45, 58]]), placement: 'surface' }], size);
  assert.equal(inSpace.part, null);
  assert.equal(inSpace.placement, 'space');
  const plane = item => worldOf(item).map(point => [point.x, point.y, point.z].map(value => Math.round(value * 1000) / 1000));
  // The model's nearest is the post's top (z 10): the plane is two pixels in front of it.
  assert.deepEqual(plane(inSpace)[0], [-8, -5, 12], 'where it was drawn, in front of the model, not on the slab');
  assert.ok(plane(inSpace).every(([, , z]) => z === 12));
  assert.equal(onModel.part, 'slab');
  assert.equal(onModel.placement, 'surface');
  assert.ok(worldOf(onModel, slab).every(point => Math.abs(point.z - 2) < 1e-6));
  // Marks all in space look at no part: nothing under them is read.
  slab.raycast = () => { throw new Error('the parts were read for ink in space'); };
  assert.equal(projectAnnotations(runtime, [{ ...stroke('alone', [[42, 55], [45, 55]]), placement: 'space' }], size)[0].part, null);
});

test('a stroke stands in front of what it crosses, so nothing it was drawn over cuts it, and carries on in the air where it leaves the model', () => {
  const { runtime, slab } = rig();
  // Across the post (screen x 49–51) and off the slab's edge (x 40) to x 30.
  const [item] = projectAnnotations(runtime, [stroke('across', along(58, 30).map(x => [x, 52]))], size);
  assert.equal(item.part, 'slab');
  const world = worldOf(item, slab);
  for (const point of world) {
    // Over the post and within its line's reach of it (half its width and two pixels): in front of its
    // top. Clear of that reach by a segment and a pixel: on the slab, or carried on from it.
    if (Math.abs(point.x) <= 1 + 3) assert.ok(point.z >= 10, `in front of the post at x ${point.x}: ${point.z}`);
    else if (Math.abs(point.x) > 1 + 3 + 2) assert.ok(Math.abs(point.z - 2) < 1e-6, `on the slab at x ${point.x}: ${point.z}`);
  }
});

test('a fill all over a part lies on it; one partly over nothing lies whole on a sheet in front of what it covers; a text mark stands in front of what it covers', () => {
  const { runtime } = rig();
  const outline = points => points.map(([x, y]) => ({ x, y }));
  const [on, partly, card] = projectAnnotations(runtime, [
    // Six pixels and more clear of the post.
    { kind: 'area', id: 'on', outline: outline([[40.5, 57], [42, 57], [42, 59.5]]), color: '#0f0', opacity: 0.35 },
    { kind: 'area', id: 'partly', outline: outline([[42, 42], [30, 42], [30, 46]]), color: '#0f0', opacity: 0.35 },
    { kind: 'text', id: 'card', corners: outline([[46, 46], [54, 46], [54, 54], [46, 54]]), text: 'hi', color: '#000', fontPx: 16 },
  ], size);
  assert.equal(on.part, 'slab');
  assert.ok(on.triangles.length >= 3 && on.outline === 3);
  const zs = item => worldOf(item, runtime.modelGroup.children.find(child => child.userData.partId === item.part)).map(point => point.z);
  assert.ok(zs(on).every(z => Math.abs(z - 2) < 1e-6));
  // Its depth the nearest of all it covers: the slab, beside the post.
  assert.ok(zs(partly).every(z => Math.abs(z - 2) < 1e-6));
  // Over the post's top (z 10): in front of it.
  assert.ok(zs(card).every(z => Math.abs(z - 18) < 1e-6), zs(card).join());
});

test('drawn, ink takes its part\'s place each frame — exploded or posed — hides with it and is cut where the model is; updated, only what changed is redrawn; disposed, the scene is as it was', () => {
  const { runtime, slab } = rig();
  const [first, second] = projectAnnotations(runtime, [stroke('a', [[42, 55], [45, 55]]), stroke('b', [[42, 58], [45, 58]])], size);
  const before = runtime.scene.onBeforeRender;
  const ink = mountAnnotations(runtime);
  ink.update([first]);
  const [line] = ink.group.children.filter(child => child.isLine2);
  ink.update([first, second]);
  const lines = ink.group.children.filter(child => child.isLine2);
  assert.equal(lines.length, 2);
  assert.equal(lines[0], line, 'the mark already drawn keeps its object');
  ink.update([second]);
  assert.deepEqual(ink.group.children.filter(child => child.isLine2), [lines[1]]);
  // What Select picked is haloed behind its ink, and lets go with it.
  ink.update([first, second], [second.id]);
  const halos = () => ink.group.children.filter(child => child.isLine2 && child.renderOrder < lines[1].renderOrder);
  assert.equal(halos().length, 1);
  // What the pointer rests on, fainter; picking it brightens the halo.
  ink.update([first, second], [second.id], [first.id]);
  const opacities = () => halos().map(halo => halo.material.opacity).sort();
  assert.deepEqual(opacities(), [0.25, 0.5]);
  ink.update([first, second], [first.id, second.id], [first.id]);
  assert.deepEqual(opacities(), [0.5, 0.5]);
  ink.update([first, second], []);
  assert.equal(halos().length, 0);
  const drawn = ink.group.children.find(child => child.isLine2 && child !== lines[1]);
  // The part moves (an explode, a pose): the ink goes with it.
  slab.position.set(30, 0, -1);
  runtime.scene.updateMatrixWorld(true);
  runtime.scene.onBeforeRender({}, runtime.scene, runtime.camera, null);
  assert.deepEqual(drawn.matrixWorld.elements, slab.matrixWorld.elements);
  // Clip: the model's planes are the ink's.
  runtime.activeClipPlanes = [new THREE.Plane(new THREE.Vector3(1, 0, 0), 0)];
  runtime.scene.onBeforeRender({}, runtime.scene, runtime.camera, null);
  assert.equal(drawn.material.clippingPlanes, runtime.activeClipPlanes);
  // Hidden: so is its ink.
  slab.visible = false;
  runtime.scene.onBeforeRender({}, runtime.scene, runtime.camera, null);
  assert.equal(drawn.visible, false);
  ink.dispose();
  assert.equal(ink.group.parent, null);
  assert.equal(runtime.scene.onBeforeRender, before);
});

test("an arrow's line and head follow one part together; each mark keeps the view it was drawn in; the annotation writes as an annotation file", () => {
  const { runtime, slab } = rig();
  // The line lies mostly on the slab; the head's wings are over nothing.
  const marks = [
    { ...stroke('line', [[44, 56], [56, 56], [62, 56]]), group: 'arrow', view: 'view 1' },
    { ...stroke('wing', [[61, 57], [64, 59]]), group: 'arrow', view: 'view 1' },
  ];
  const items = projectAnnotations(runtime, marks, size);
  assert.deepEqual(items.map(item => [item.part, item.view, item.group]), [['slab', 'view 1', 'arrow'], ['slab', 'view 1', 'arrow']]);
  assert.deepEqual(items[0].touches.map(touch => touch.part), ['slab']);
  const annotation = normalizeAnnotation(JSON.parse(JSON.stringify(annotationDocumentOf(items))));
  assert.deepEqual(Object.keys(annotation.parts), ['slab']);
  assert.deepEqual(annotation.parts.slab.placement, slab.matrixWorld.toArray());
  assert.deepEqual(annotation.marks.map(mark => [mark.id, mark.kind, mark.part, mark.view]), [['line', 'stroke', 'slab', 'view 1'], ['wing', 'stroke', 'slab', 'view 1']]);
  assert.equal(annotation.marks[0].points.length, items[0].points.length);
});
