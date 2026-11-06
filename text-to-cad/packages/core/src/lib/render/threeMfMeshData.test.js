import assert from "node:assert/strict";
import test from "node:test";

import { buildMeshDataFromThreeMfGroup } from "./threeMfMeshData.js";

class FakeVector3 {
  set(x, y, z) {
    this.x = x;
    this.y = y;
    this.z = z;
    return this;
  }

  applyMatrix4() {
    return this;
  }

  applyMatrix3() {
    return this;
  }

  normalize() {
    return this;
  }
}

class FakeMatrix3 {
  getNormalMatrix() {
    return this;
  }
}

function fakeAttribute(values) {
  return {
    itemSize: 3,
    count: values.length / 3,
    getX: (index) => values[index * 3],
    getY: (index) => values[index * 3 + 1],
    getZ: (index) => values[index * 3 + 2],
  };
}

function assertArrayAlmostEqual(actual, expected, epsilon = 1e-6) {
  assert.equal(actual.length, expected.length);
  for (let index = 0; index < actual.length; index += 1) {
    assert.ok(
      Math.abs(Number(actual[index]) - Number(expected[index])) <= epsilon,
      `index ${index}: expected ${expected[index]}, got ${actual[index]}`
    );
  }
}

test("buildMeshDataFromThreeMfGroup normalizes 3MF meshes to viewer mesh data", () => {
  const mesh = {
    isMesh: true,
    name: "fixture",
    material: null,
    matrixWorld: null,
    updateWorldMatrix() {},
    geometry: {
      getIndex: () => null,
      getAttribute: (name) => {
        if (name === "position") {
          return fakeAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0]);
        }
        if (name === "normal") {
          return fakeAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1]);
        }
        return null;
      },
      computeVertexNormals() {},
    },
  };
  const group = {
    updateWorldMatrix() {},
    traverse(callback) {
      callback(mesh);
    },
  };

  const meshData = buildMeshDataFromThreeMfGroup(
    { Matrix3: FakeMatrix3, Vector3: FakeVector3 },
    group
  );

  assert.deepEqual([...meshData.vertices], [0, 0, 0, 1, 0, 0, 0, 1, 0]);
  assert.deepEqual([...meshData.indices], [0, 1, 2]);
  assert.deepEqual([...meshData.normals], [0, 0, 1, 0, 0, 1, 0, 0, 1]);
  assert.deepEqual([...meshData.colors], []);
  assert.deepEqual(meshData.bounds, { min: [0, 0, 0], max: [1, 1, 0] });
  assert.equal(meshData.parts.length, 1);
  assert.equal(meshData.parts[0].name, "fixture");
  assert.equal(meshData.has_source_colors, false);
});

test("buildMeshDataFromThreeMfGroup preserves 3MF material colors", () => {
  const mesh = {
    isMesh: true,
    name: "colored fixture",
    material: {
      color: {
        r: 0.25,
        g: 0.5,
        b: 0.75,
        getHexString: () => "4080bf",
      },
    },
    matrixWorld: null,
    updateWorldMatrix() {},
    geometry: {
      getIndex: () => null,
      getAttribute: (name) => {
        if (name === "position") {
          return fakeAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0]);
        }
        if (name === "normal") {
          return fakeAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1]);
        }
        return null;
      },
      computeVertexNormals() {},
    },
  };
  const group = {
    updateWorldMatrix() {},
    traverse(callback) {
      callback(mesh);
    },
  };

  const meshData = buildMeshDataFromThreeMfGroup(
    { Matrix3: FakeMatrix3, Vector3: FakeVector3 },
    group
  );

  assert.deepEqual([...meshData.colors], [0.25, 0.5, 0.75, 0.25, 0.5, 0.75, 0.25, 0.5, 0.75]);
  assert.equal(meshData.has_source_colors, true);
  assert.equal(meshData.sourceColor, "#4080bf");
  assert.equal(meshData.parts[0].color, "#4080bf");
});

test("buildMeshDataFromThreeMfGroup treats generated default material as uncolored", () => {
  const mesh = {
    isMesh: true,
    name: "default fixture",
    material: {
      name: "Default",
      color: {
        r: 0.4677837961,
        g: 0.5520114015,
        b: 0.6172065624,
        getHexString: () => "b6c4ce",
      },
    },
    matrixWorld: null,
    updateWorldMatrix() {},
    geometry: {
      getIndex: () => null,
      getAttribute: (name) => {
        if (name === "position") {
          return fakeAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0]);
        }
        if (name === "normal") {
          return fakeAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1]);
        }
        return null;
      },
      computeVertexNormals() {},
    },
  };
  const group = {
    updateWorldMatrix() {},
    traverse(callback) {
      callback(mesh);
    },
  };

  const meshData = buildMeshDataFromThreeMfGroup(
    { Matrix3: FakeMatrix3, Vector3: FakeVector3 },
    group
  );

  assert.deepEqual([...meshData.colors], []);
  assert.equal(meshData.has_source_colors, false);
  assert.equal(meshData.sourceColor, "");
  assert.equal(meshData.parts[0].color, "");
});

test("buildMeshDataFromThreeMfGroup keeps authored colors when mixed with generated defaults", () => {
  const defaultRgb = [0.4677837961, 0.5520114015, 0.6172065624];
  const mesh = {
    isMesh: true,
    name: "mixed fixture",
    material: [
      {
        name: "Default",
        color: {
          r: defaultRgb[0],
          g: defaultRgb[1],
          b: defaultRgb[2],
          getHexString: () => "b6c4ce",
        },
      },
      {
        name: "red",
        color: {
          r: 1,
          g: 0,
          b: 0,
          getHexString: () => "ff0000",
        },
      },
    ],
    matrixWorld: null,
    updateWorldMatrix() {},
    geometry: {
      groups: [
        { start: 0, count: 3, materialIndex: 0 },
        { start: 3, count: 3, materialIndex: 1 },
      ],
      getIndex: () => null,
      getAttribute: (name) => {
        if (name === "position") {
          return fakeAttribute([
            0, 0, 0,
            1, 0, 0,
            0, 1, 0,
            1, 0, 0,
            1, 1, 0,
            0, 1, 0,
          ]);
        }
        if (name === "normal") {
          return fakeAttribute([
            0, 0, 1,
            0, 0, 1,
            0, 0, 1,
            0, 0, 1,
            0, 0, 1,
            0, 0, 1,
          ]);
        }
        return null;
      },
      computeVertexNormals() {},
    },
  };
  const group = {
    updateWorldMatrix() {},
    traverse(callback) {
      callback(mesh);
    },
  };

  const meshData = buildMeshDataFromThreeMfGroup(
    { Matrix3: FakeMatrix3, Vector3: FakeVector3 },
    group
  );

  assertArrayAlmostEqual([...meshData.colors], [
    ...defaultRgb,
    ...defaultRgb,
    ...defaultRgb,
    1, 0, 0,
    1, 0, 0,
    1, 0, 0,
  ]);
  assert.equal(meshData.has_source_colors, true);
  assert.equal(meshData.sourceColor, "#ff0000");
  assert.equal(meshData.parts[0].color, "");
  assert.equal(meshData.parts[1].color, "#ff0000");
});

test("a 3MF's objects are known by their place in its build, and its unit is the one its model declares", async () => {
  const THREE = await import("three");
  const { zipSync, strToU8 } = await import("three/examples/jsm/libs/fflate.module.js");
  const { declared3MfUnit } = await import("./threeMfMeshData.js");
  const { buildMeshScene } = await import("./meshScene.js");
  // As three's loader builds it: one child per build item; a component object one child per
  // component; an object's meshes under the object's own group.
  const object = (name) => { const group = new THREE.Group(); group.name = name; group.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial())); return group; };
  const root = new THREE.Group();
  const composite = new THREE.Group();
  composite.add(object("wheel"), object("wheel"));
  root.add(object("frame"), composite);
  const meshData = { ...buildMeshDataFromThreeMfGroup(THREE, root), unit: "inch" };
  // A box is six material groups: six ranges of one object, one place.
  assert.deepEqual([...new Set(meshData.parts.map(part => part.path.join(".")))], ["1", "2.1", "2.2"]);
  const scene = buildMeshScene(THREE, meshData);
  assert.deepEqual(scene.units, { unit: "in", perWorld: 1 });
  assert.deepEqual(["o1", "o2.1", "o2.2"].map(path => scene.describePart(path).name), ["frame", "wheel (o2.1)", "wheel (o2.2)"]);
  assert.deepEqual(scene.describePart("o2.2").facts.map(fact => fact.value), ["2, component 2", "12"]);
  scene.dispose();

  const model = unit => zipSync({ "3D/3dmodel.model": strToU8(`<?xml version="1.0"?>\n<model ${unit} xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/></model>`) });
  assert.deepEqual(await Promise.all([model('unit="inch"'), model("")].map(declared3MfUnit)), ["inch", "millimeter"]);
});
