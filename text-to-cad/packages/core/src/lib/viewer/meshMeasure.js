// Measure on a family's scene: a GLB, a 3MF or a robot. Such a file is triangles, so a point is
// snapped to what the triangle under the pointer has — one of its corners, a point on one of its
// sides, or the point on its face — and a length between two is the distance between two points
// of the mesh, in the file's unit (`sceneUnits.js`). It is APPROXIMATE: a tessellated curve's
// width across two facets is not its diameter, and every reading says so (`approximate`).
//
// Pure maths on plain arrays; the triangle and the projection are the caller's. A pick is the
// shape a STEP's Measure pick has (`measurement.js`): `{ point, snapKind, referenceId }`, plus the
// units it is read in.

import { closestPointOnSegment, isFinitePoint } from "./measurement.js";

/** How near, in CSS pixels, the pointer must be to a corner, then to a side, to snap to it. */
export const MESH_SNAP_VERTEX_PX = 10;
export const MESH_SNAP_EDGE_PX = 7;

/**
 * The triangle a ray hit, in the scene's (world) coordinates: three's intersection of a mesh,
 * through the mesh's own deformation (skin, morph targets) and its world matrix.
 *
 * @param {import("three").Intersection} hit
 * @returns {number[][] | null}
 */
export function hitTriangle(hit) {
  const { object, face } = hit || {};
  if (!object?.isMesh || !face || typeof object.getVertexPosition !== "function") return null;
  return [face.a, face.b, face.c].map(index => {
    const point = object.getVertexPosition(index, hit.point.clone());
    return point.applyMatrix4(object.matrixWorld).toArray();
  });
}

const key = point => point.map(value => value.toPrecision(7)).join(",");

/**
 * Where a Measure pick lands on `hit`: the triangle's corner nearest the pointer when it is within
 * `MESH_SNAP_VERTEX_PX`, else the nearest point on one of its sides within `MESH_SNAP_EDGE_PX`,
 * else the point on the face ("surface").
 *
 * @param {{ id: string, point: number[], triangle: number[][] } | null} hit  The scene's pick, the
 *   triangle in scene coordinates.
 * @param {{ x: number, y: number }} pointer  CSS pixels, in the frame `project` answers in.
 * @param {(point: number[]) => ({ x: number, y: number } | null)} project  Scene → CSS pixels.
 * @param {import("./sceneUnits.js").SceneUnits} units
 */
export function meshMeasurePick(hit, pointer, project, units) {
  const point = hit?.point;
  const triangle = hit?.triangle;
  if (!isFinitePoint(point) || !Array.isArray(triangle) || triangle.length !== 3) return null;
  const pick = (snapPoint, snapKind, target) => ({ point: [...snapPoint], snapKind, referenceId: `${hit.id}:${target}`, units, approximate: true });
  const screen = candidate => {
    const at = project(candidate);
    return at ? Math.hypot(at.x - pointer.x, at.y - pointer.y) : Infinity;
  };
  let best = null;
  for (const corner of triangle) {
    const distance = screen(corner);
    if (distance <= MESH_SNAP_VERTEX_PX && (!best || distance < best.distance)) best = { corner, distance };
  }
  if (best) return pick(best.corner, "vertex", `v${key(best.corner)}`);
  let side = null;
  for (let index = 0; index < 3; index += 1) {
    const start = triangle[index], end = triangle[(index + 1) % 3];
    const nearest = closestPointOnSegment(point, start, end);
    const distance = nearest ? screen(nearest) : Infinity;
    if (distance <= MESH_SNAP_EDGE_PX && (!side || distance < side.distance)) {
      side = { nearest, distance, target: `e${[key(start), key(end)].sort().join("|")}` };
    }
  }
  if (side) return pick(side.nearest, "edge", side.target);
  return pick(point, "surface", "s");
}
