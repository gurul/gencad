import { hitTriangle } from "../viewer/meshMeasure.js";
import { scheduleRuntimeRaycastBvh } from "../viewer/raycastBvh.js";
import { createSceneHighlight } from "../viewer/sceneHighlight.js";
import { UNITLESS_SCENE_UNITS, threeMfSceneUnits } from "../viewer/sceneUnits.js";
import { createSurfaceLook } from "../viewer/surfaceLook.js";
import { buildMeshObjects } from "./meshObjects.js";
import { releaseGeometry, shareGeometry } from "./sharedGeometry.js";

function boundsOf(THREE, objects) {
  const box = new THREE.Box3();
  for (const { geometry } of objects) {
    if (!geometry.boundingBox) geometry.computeBoundingBox();
    box.union(geometry.boundingBox);
  }
  if (box.isEmpty()) return { min: [0, 0, 0], max: [0, 0, 0] };
  return { min: box.min.toArray(), max: box.max.toArray() };
}

/**
 * A mesh file's scene (`../viewer/sceneContract.js`): one `Mesh` per object of the
 * file, and nothing else. A triangle mesh authors no finish, so it wears the viewer's
 * surface in Solid and the studio's in Render; all a file can say is an object's
 * colour, which "Original" keeps. An object without one is marked
 * `userData.cadSourceColor = false` and takes the viewer's surface colour.
 *
 * @param {typeof import("three")} THREE
 * @param {import("./meshObjects.js").MeshObject[]} objects  `buildMeshObjects`.
 *   The scene owns their geometries from here on (a sibling's share its source's: `createSibling`).
 * @param {{ units?: import("../viewer/sceneUnits.js").SceneUnits }} [options]  What the file measures in.
 * @returns {import("../viewer/sceneContract.js").KitScene & { meshCount: number }}
 *   A 3MF's objects (those with a `path`) are picked, named and lit by their place in its build:
 *   `o2.1`, the second build item's first component, as a STEP names an occurrence.
 */
export function createMeshScene(THREE, objects, { units = UNITLESS_SCENE_UNITS } = {}) {
  const root = new THREE.Group();
  root.name = "mesh-document";
  const materials = objects.map((object) => {
    const material = new THREE.MeshPhysicalMaterial({ color: object.color || 0xffffff, side: THREE.DoubleSide });
    material.userData.cadSourceColor = Boolean(object.color);
    const mesh = new THREE.Mesh(object.geometry, material);
    mesh.name = object.name;
    mesh.castShadow = true;
    // Where "Color by part" deals this object its palette colour.
    mesh.userData.cadFillIndex = object.paletteIndex;
    if (object.path) mesh.userData.objectPath = `o${object.path.join(".")}`;
    // What Annotate hangs a mark on, here and in a snapshot (`annotation.js`).
    mesh.userData.partId = mesh.userData.objectPath || `mesh:${root.children.length}`;
    root.add(mesh);
    return material;
  });
  const look = createSurfaceLook(THREE, root);
  const ink = createSceneHighlight(THREE, look);
  const bounds = boundsOf(THREE, objects);
  // A 3MF's objects, by their place in the build; an object of several materials is several meshes.
  const records = root.children.map(mesh => ({ mesh }));
  const byPath = new Map();
  for (const record of records) {
    const path = record.mesh.userData.objectPath;
    if (path) byPath.set(path, [...(byPath.get(path) || []), record]);
  }
  const pickable = records.filter(record => record.mesh.userData.objectPath).map(record => record.mesh);
  // A name several objects share is told apart by the object's place.
  const nameCounts = new Map();
  for (const [path, [{ mesh }]] of byPath) nameCounts.set(mesh.name || path, (nameCounts.get(mesh.name || path) || 0) + 1);
  // An object the file left unnamed has only its reader's stand-in ("3mf:2"): it is named by its place.
  const objectName = (path, name) => (!name || /^3mf:\d+$/.test(name) ? `Object ${path}` : nameCounts.get(name) > 1 ? `${name} (${path})` : name);
  if (pickable.length) scheduleRuntimeRaycastBvh({ displayRecords: records }, { deferUntilRaycast: true });
  const raycaster = new THREE.Raycaster();
  let lastLook = null;
  let clipPlanes = [];
  let highlight = { hovered: [], selected: [] };
  const recordsFor = paths => paths.flatMap(path => byPath.get(path) || []);
  const applyHighlight = () => ink.apply(lastLook, { hovered: recordsFor(highlight.hovered), selected: recordsFor(highlight.selected) }, clipPlanes);
  let disposed = false;
  return {
    meshCount: objects.length,
    object3D: root,
    bounds,
    restBounds: bounds,
    units,
    // Nothing here was authored, so Render is a look like any other: the studio's
    // surface over the same colours, never a finish "kept".
    setSurfaceLook(next) {
      if (disposed) return;
      lastLook = next ? { ...next, authored: false } : null;
      applyHighlight();
    },
    setClipPlanes(planes) {
      if (disposed) return;
      clipPlanes = Array.isArray(planes) ? planes : [];
      look.setClipPlanes(clipPlanes);
    },
    /** Whether `path` (`o2.1`) is a 3MF object of this file. */
    hasPart: path => byPath.has(path),
    /** A 3MF object, as Quick Edit's chip says it: its name, and its place in the build. */
    describePart(path) {
      const records = byPath.get(path);
      if (!records) return null;
      const places = path.slice(1).split(".");
      const count = records.reduce((sum, { mesh }) => sum + Math.floor((mesh.geometry.index?.count ?? mesh.geometry.getAttribute("position").count) / 3), 0);
      return { name: objectName(path, records[0].mesh.name), facts: [
        { label: "Build item", value: places.length > 1 ? `${places[0]}, component ${places.slice(1).join(".")}` : places[0] },
        { label: "Triangles", value: count.toLocaleString("en-US") }
      ] };
    },
    /** Light 3MF objects: `hovered` and `selected` are their places. */
    setHighlight({ hovered = [], selected = [] } = {}) {
      if (disposed) return;
      highlight = { hovered: hovered.filter(path => byPath.has(path)), selected: selected.filter(path => byPath.has(path)) };
      applyHighlight();
    },
    // A 3MF's object under the ray, and the triangle hit; an STL picks nothing.
    pick(ray) {
      if (disposed || !pickable.length) return null;
      raycaster.ray.copy(ray);
      // The first surface Clip has not cut away.
      const hit = raycaster.intersectObjects(pickable, false).find(candidate => clipPlanes.every(plane => plane.distanceToPoint(candidate.point) >= 0));
      if (!hit) return null;
      const path = hit.object.userData.objectPath;
      return { id: path, name: objectName(path, hit.object.name), point: hit.point.toArray(), triangle: hitTriangle(hit) };
    },
    /**
     * A second scene of the same file (the viewer's Preview beside its editor): its own meshes,
     * materials and look over this scene's geometry (`sharedGeometry.js`). This scene stays the
     * geometry's owner, so the sibling is disposed first.
     */
    createSibling() {
      return createMeshScene(THREE, objects.map(object => ({ ...object, geometry: shareGeometry(THREE, object.geometry) })), { units });
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      root.removeFromParent();
      ink.dispose();
      look.dispose();
      for (const material of materials) material.dispose();
      for (const { geometry } of objects) releaseGeometry(geometry);
    }
  };
}

/**
 * An STL's or a 3MF's scene from its decode (`loadRenderMeshByUrl`), or null when the
 * file holds no triangles. The ONE builder of a mesh file's scene: the viewer's mesh
 * renderer and the snapshot CLI's headless stage both call it, so neither can draw an
 * STL or a 3MF the other does not.
 *
 * @param {typeof import("three")} THREE
 * @param {object} meshData  `buildMeshDataFromStlBuffer` / `buildMeshDataFrom3MfBuffer` output.
 */
export function buildMeshScene(THREE, meshData) {
  const objects = buildMeshObjects(THREE, meshData);
  // A 3MF says the unit its numbers are in; an STL says none.
  const units = meshData?.unit ? threeMfSceneUnits(meshData.unit) : UNITLESS_SCENE_UNITS;
  return objects.length ? createMeshScene(THREE, objects, { units }) : null;
}
