import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { resolveCadEdgeSettings, resolveCadGridSettings } from "./cadInk.js";
import { GRID_LINE_DEFAULTS } from "../lib/viewer/stageGrid.js";
import { buildCadEdgeSegmentTexture, CadEdgeInstances } from "./cadEdgeInstances.js";
import { screenSpaceLineDeviceResolution, syncScreenSpaceLineMaterialResolution } from "./renderEdges.js";

test("fixed CAD classes retain distinct restrained device-pixel ink at every pixel ratio", () => {
  const classes = resolveCadEdgeSettings().classes;
  assert.deepEqual(Object.values(classes).map((style) => style.thickness), [1, 0.65, 0.8, 0]);
  const segments = buildCadEdgeSegmentTexture(THREE, {
    positions: new Float32Array([0, 0, 0, 1, 0, 0]), indices: new Uint32Array([0, 1])
  }, [{ classId: "feature", segmentStart: 0, segmentCount: 1 }]);
  const set = new CadEdgeInstances(THREE, { segments, classStyles: Object.entries(classes).map(([classId, style]) => ({ ...style, classId, color: new THREE.Color(style.color) })) });
  for (const dpr of [1, 2, 3]) {
    const resolution = screenSpaceLineDeviceResolution({ getPixelRatio: () => dpr }, 800, 600);
    syncScreenSpaceLineMaterialResolution(set.materials, resolution.width, resolution.height);
    for (const [index, classId] of ["feature", "tangent", "seam"].entries()) {
      const width = set.uniforms.cadClassWidth.value.getComponent(index);
      const effectiveDeviceWidth = width * 600 * dpr / set.uniforms.resolution.value.y;
      assert.equal(effectiveDeviceWidth, classes[classId].thickness);
      assert.ok(effectiveDeviceWidth / dpr <= 1 / dpr);
    }
  }
  set.dispose();
  segments.texture.dispose();
});

test("edge color is configurable while widths stay fixed and grid adapts to appearance", () => {
  const edges = resolveCadEdgeSettings({ color: "#ff0000", thickness: 6 });
  assert.equal(edges.thickness, 1);
  assert.equal(edges.color, "#ff0000");
  assert.equal(new Set(["feature", "tangent", "seam"].map((id) => edges.classes[id].color)).size, 1);
  assert.equal(new Set(Object.values(resolveCadEdgeSettings().classes).map(style => style.color)).size, 3);
  for (const colorMode of ["light", "dark"]) {
    const grid = resolveCadGridSettings({ enabled: true, density: 4 }, { colorMode });
    assert.equal(grid.enabled, true);
    assert.equal(grid.density, 4, "a view's grid density reaches the grid");
    assert.equal(resolveCadGridSettings({ enabled: true }, { colorMode }).density, 1, "and is 1 unless a view sets it");
    assert.equal(grid.opacity, GRID_LINE_DEFAULTS[colorMode].opacity);
  }
  // The lines adapt to the backdrop, and so do the red X and green Y axes.
  const [light, dark] = ["light", "dark"].map(colorMode => resolveCadGridSettings({ enabled: true }, { colorMode }));
  for (const name of ["color", "xAxisColor", "yAxisColor"]) assert.notEqual(light[name], dark[name], name);
});


test("an explicit grid colour is every line's but the axes', which stay red and green", () => {
  for (const colorMode of ["light", "dark"]) {
    const grid = resolveCadGridSettings({ enabled: true, color: "#123456", opacity: 0 }, { colorMode });
    assert.deepEqual({ ...grid, xAxisColor: undefined, yAxisColor: undefined },
      { enabled: true, color: "#123456", opacity: 0, density: 1, xAxisColor: undefined, yAxisColor: undefined });
    assert.notEqual(grid.xAxisColor, "#123456");
    assert.notEqual(grid.yAxisColor, "#123456");
  }
});
