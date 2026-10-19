import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";

import { robotOf, parseArmUrdf } from "../urdf/__tests__/robotFixtures.js";
import { createRobotScene } from "../urdf/robotScene.js";
import { createGlbScene } from "./glbScene.js";
import { createMeshScene } from "./meshScene.js";
import { isSharedGeometry, releaseGeometry, shareGeometry } from "./sharedGeometry.js";

// What a renderer frees when a geometry is disposed: every attribute (and the index) it holds then.
function freedOnDispose(geometry) {
  const freed = [];
  geometry.addEventListener("dispose", () => {
    if (geometry.index) freed.push(geometry.index);
    freed.push(...Object.values(geometry.attributes));
  });
  return freed;
}
const meshes = root => { const list = []; root.traverse(object => { if (object.isMesh) list.push(object); }); return list; };
const look = (materialSettings = {}) => ({ materialSettings: { defaultColor: "#ff0000", fillColors: ["#ff0000"],
  overrideSourceColors: true, ...materialSettings }, authored: false, surface: { style: "shaded", opacity: 1 } });

test("a shared geometry draws its source's buffers, owns what it copies, and releases only that", () => {
  const source = new THREE.BoxGeometry(1, 1, 1);
  source.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(source.attributes.position.count * 3), 3));
  const shared = shareGeometry(THREE, source, { own: ["color"] });
  assert.equal(isSharedGeometry(shared), true);
  assert.equal(shared.index, source.index);
  assert.equal(shared.attributes.position, source.attributes.position, "one buffer, uploaded once by a renderer drawing both");
  assert.notEqual(shared.attributes.color, source.attributes.color, "an attribute it rewrites is its own");
  const freed = freedOnDispose(shared);
  releaseGeometry(shared);
  assert.deepEqual(freed, [shared.attributes.color], "only its own attribute is freed");
  assert.equal(source.attributes.position.array.length > 0, true);
  assert.ok(source.index && source.attributes.position, "the source keeps everything");
});

test("a mesh scene's sibling: its own meshes, materials and look over the same buffers, released first", () => {
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const scene = createMeshScene(THREE, [{ name: "a", geometry, color: "#00ff00", paletteIndex: 0 }]);
  const sibling = scene.createSibling();
  const [own] = meshes(scene.object3D), [theirs] = meshes(sibling.object3D);
  assert.notEqual(theirs, own);
  assert.equal(theirs.geometry.attributes.position, own.geometry.attributes.position);
  assert.notEqual(theirs.material, own.material);
  const before = own.material.color.getHex();
  sibling.setSurfaceLook(look());
  assert.equal(own.material.color.getHex(), before, "the sibling's look dresses its own materials alone");
  const freed = freedOnDispose(theirs.geometry);
  sibling.dispose();
  assert.deepEqual(freed, [], "the source's buffers are not the sibling's to free");
  scene.dispose();
});

test("a GLB scene's sibling wears the file's authored materials, whatever the source's look did, and frees nothing of the document", () => {
  const sceneRoot = new THREE.Group();
  const texture = new THREE.Texture();
  const authored = new THREE.MeshStandardMaterial({ color: "#336699", map: texture });
  const body = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), authored);
  const skinned = new THREE.SkinnedMesh(new THREE.BoxGeometry(1, 1, 1), authored);
  const bone = new THREE.Bone();
  skinned.add(bone);
  skinned.bind(new THREE.Skeleton([bone]));
  sceneRoot.add(body, skinned);
  const document = { scene: sceneRoot, clips: [], cadRootMatrix: new THREE.Matrix4().toArray(),
    restBounds: { min: [0, 0, 0], max: [1, 1, 1] }, animatedBounds: null };
  const scene = createGlbScene(THREE, document);
  scene.setSurfaceLook(look());
  const sibling = scene.createSibling();
  const copies = meshes(sibling.object3D);
  assert.equal(copies.length, 2);
  for (const copy of copies) {
    assert.notEqual(copy.material, authored);
    assert.equal(copy.material.color.getHexString(), "336699", "authored, not the source's look");
    assert.equal(copy.material.map, texture, "textures are the document's, shared");
  }
  assert.equal(copies[0].geometry.attributes.position, body.geometry.attributes.position);
  assert.notEqual(copies[1].skeleton, skinned.skeleton, "a skin is bound to the sibling's own bones");
  assert.equal(sibling.document.scene, sibling.object3D.children[0], "its routine plays on its own copy");
  let textureDisposed = false;
  texture.addEventListener("dispose", () => { textureDisposed = true; });
  const freed = freedOnDispose(copies[0].geometry);
  sibling.dispose();
  assert.deepEqual([freed, textureDisposed], [[], false]);
  scene.dispose();
});

test("a robot scene's sibling is posed apart, over the same buffers", () => {
  const robot = robotOf(parseArmUrdf());
  const scene = createRobotScene(THREE, robot);
  const sibling = scene.createSibling();
  const own = meshes(scene.object3D), theirs = meshes(sibling.object3D);
  assert.equal(theirs.length, own.length);
  assert.equal(theirs[0].geometry.attributes.position, own[0].geometry.attributes.position);
  const joint = robot.description.joints.find(candidate => candidate.type === "revolute" || candidate.type === "continuous");
  sibling.setJointValues({ [joint.name]: 1 });
  assert.notEqual(sibling.jointValue(joint.name), scene.jointValue(joint.name), "posing the sibling leaves the source as it was");
  const freed = freedOnDispose(theirs[0].geometry);
  sibling.dispose();
  assert.deepEqual(freed, []);
  scene.dispose();
});
