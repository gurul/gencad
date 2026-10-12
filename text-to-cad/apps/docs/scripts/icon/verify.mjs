import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { AnimationMixer, Quaternion, Vector3 } from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const bytes = await readFile(new URL('../../public/icon/icon.glb', import.meta.url));
const gltf = await new GLTFLoader().parseAsync(
  bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '',
);
const meshes = [];
gltf.scene.traverse(object => { if (object.isMesh) meshes.push(object); });
assert.equal(meshes.length, 21, 'twenty prongs and one solid hub');
assert.equal(gltf.animations.length, 1);
assert.equal(gltf.animations[0].name, 'UnisonGrowth');
assert.equal(gltf.animations[0].duration, 80);
const prongs = meshes.filter(mesh => mesh.morphTargetInfluences?.length);
assert.equal(prongs.length, 20);
assert(prongs.every(prong => prong.morphTargetInfluences[0] === 0), 'default icon uses long prongs');
const vertexKey = point => point.toArray().map(value => value.toFixed(6)).join(',');
const corePositions = meshes.find(mesh => mesh.name === 'Core').geometry.getAttribute('position');
const coreVertices = Array.from({ length: corePositions.count }, (_, i) =>
  vertexKey(new Vector3().fromBufferAttribute(corePositions, i)));
const coreKeys = new Set(coreVertices);
const coreFaces = new Set();
for (let i = 0; i < coreVertices.length; i += 3) {
  coreFaces.add(coreVertices.slice(i, i + 3).sort().join('|'));
}
const attachedFaces = new Set();

let triangleCount = 0;
for (const mesh of meshes) {
  const geometry = mesh.geometry;
  const positions = geometry.getAttribute('position');
  const target = geometry.morphAttributes.position?.[0];
  if (target) {
    const displacements = Array.from({ length: positions.count }, (_, i) => {
      const delta = new Vector3().fromBufferAttribute(target, i);
      if (!geometry.morphTargetsRelative) delta.sub(new Vector3().fromBufferAttribute(positions, i));
      return delta;
    });
    const moving = displacements.filter(delta => delta.length() > 1e-6);
    const attachment = new Set();
    for (let i = 0; i < positions.count; i++) {
      const key = vertexKey(new Vector3().fromBufferAttribute(positions, i));
      if (coreKeys.has(key)) {
        attachment.add(key);
        assert(displacements[i].length() < 1e-7, 'shared hub perimeter stays fixed throughout motion');
      }
    }
    assert.equal(attachment.size, 3, 'prong attaches to an entire triangular hub face');
    attachedFaces.add([...attachment].sort().join('|'));
    assert(moving.length > 0 && moving.length < positions.count, 'fixed root and moving crown');
    for (const delta of moving) {
      assert(Math.abs(delta.length() - 1.25) < 1e-6, 'trunk retracts by 1.25 units');
      assert(delta.distanceTo(moving[0]) < 1e-6, 'entire crown translates rigidly without stretching');
    }
    const restRadii = Array.from({ length: positions.count }, (_, i) =>
      new Vector3().fromBufferAttribute(positions, i).length());
    const shortRadii = Array.from({ length: positions.count }, (_, i) =>
      new Vector3().fromBufferAttribute(positions, i).add(displacements[i]).length());
    assert(Math.max(...shortRadii) < Math.max(...restRadii) * 0.65,
      'contracted prong is substantially stubbier than the default');
  }
  triangleCount += positions.count / 3;
  for (const amount of [0, 0.25, 0.5, 0.75, 1]) {
    const vertices = Array.from({ length: positions.count }, (_, i) => {
      const p = new Vector3().fromBufferAttribute(positions, i);
      if (target) {
        const delta = new Vector3().fromBufferAttribute(target, i);
        if (!geometry.morphTargetsRelative) delta.sub(p);
        p.addScaledVector(delta, amount);
      }
      assert(p.toArray().every(Number.isFinite), `${mesh.name}: finite vertices`);
      return p;
    });
    const key = p => p.toArray().map(n => n.toFixed(5)).join(',');
    const edges = new Map();
    let volume = 0;
    for (let i = 0; i < vertices.length; i += 3) {
      const [a, b, c] = vertices.slice(i, i + 3);
      const cross = b.clone().sub(a).cross(c.clone().sub(a));
      assert(cross.length() > 1e-7, `${mesh.name}: no degenerate triangle at ${amount}`);
      volume += a.dot(b.clone().cross(c)) / 6;
      for (const [from, to] of [[a, b], [b, c], [c, a]]) {
        const f = key(from), t = key(to);
        const edge = [f, t].sort().join('|');
        const entry = edges.get(edge) ?? { count: 0, winding: 0 };
        entry.count++;
        entry.winding += f < t ? 1 : -1;
        edges.set(edge, entry);
      }
    }
    assert(volume > 0, `${mesh.name}: outward normals and positive volume`);
    for (const edge of edges.values()) {
      assert.equal(edge.count, 2, `${mesh.name}: closed manifold at ${amount}`);
      assert.equal(edge.winding, 0, `${mesh.name}: consistent face winding`);
    }
  }
}
assert.deepEqual(attachedFaces, coreFaces, 'all hub faces meet prongs flushly, with shared edges and no exposed strips');

// Verify the single unison clip, including continuous motion and its loop.
const mixer = new AnimationMixer(gltf.scene);
const icon = gltf.scene.getObjectByName('Icon');
const referenceRotation = icon.quaternion.clone();
mixer.stopAllAction();
mixer.clipAction(gltf.animations[0]).play();
const growthTracks = gltf.animations[0].tracks.filter(track => track.name.includes('morphTargetInfluences'));
assert.equal(growthTracks.length, 20);
for (const track of growthTracks) {
  assert.deepEqual(track.values, growthTracks[0].values, 'identical unison timing');
  for (let i = 1; i < track.values.length; i++) {
    assert(Math.abs(track.values[i] - track.values[i - 1]) > 1e-8, 'no holds in unison');
  }
}
for (let cycle = 0; cycle < 10; cycle++) {
  for (const [phase, expected] of [[0, 0], [2, 0.5], [4, 1], [6, 0.5], [8, 0]]) {
    mixer.setTime(cycle * 8 + phase);
    for (const prong of prongs) {
      assert(Math.abs(prong.morphTargetInfluences[0] - expected) < 1e-6, 'ten complete unison cycles');
    }
  }
}
for (const time of [0, 20, 40, 60, 80]) {
  mixer.setTime(time);
  const expected = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), 2 * Math.PI * time / 80)
    .multiply(referenceRotation);
  assert(icon.quaternion.angleTo(expected) < 0.001, `full orbit at ${time}s`);
}
console.log(`Verified GLB: ${meshes.length} closed meshes, ${triangleCount} triangles, flush roots, rigid crowns, ten contractions per seamless full orbit.`);
