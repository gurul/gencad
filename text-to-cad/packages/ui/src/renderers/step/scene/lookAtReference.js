import { edgeGeometryFromSegments } from "@text-to-cad/core/lib/viewer/measurement.js";
import * as THREE from "three";
import {
  buildEdgeLinePositionsFromProxy, buildFaceFillGeometryFromDisplayMeshes, referenceExplodedViewMatrix
} from "@text-to-cad/core/lib/viewer/referenceGeometry.js";
import { planeOfPoints } from "../../kit/camera/lookAt.js";

// A face or edge of a STEP as a look-at subject (`kit/camera/lookAt.js`): what a double-click on it
// under Select turns the view square to. Its kind and axes come from its topology row (`pickData`:
// `surfaceType`/`curveType`, `normal`, `params`), its points from the selector proxy's mesh and
// polylines — where it sits at rest, then moved as Explode has moved its part — or, where the proxy
// keeps no face vertices, from the display meshes, as the face's highlight is drawn.

const lower = value => String(value || "").trim().toLowerCase();
const triplet = value => (Array.isArray(value) && value.length >= 3 && value.slice(0, 3).every(Number.isFinite) ? value.slice(0, 3).map(Number) : null);

// Explode's offset of the part, applied to points (and, without its translation, to directions).
function placer(matrix) {
  const e = matrix?.elements;
  if (!e || e.length !== 16) return { point: p => p, direction: d => d };
  return {
    point: ([x, y, z]) => [e[0] * x + e[4] * y + e[8] * z + e[12], e[1] * x + e[5] * y + e[9] * z + e[13], e[2] * x + e[6] * y + e[10] * z + e[14]],
    direction: ([x, y, z]) => [e[0] * x + e[4] * y + e[8] * z, e[1] * x + e[5] * y + e[9] * z, e[2] * x + e[6] * y + e[10] * z],
  };
}

function facePoints(selectorRuntime, pickData) {
  const proxy = selectorRuntime?.proxy || {};
  const start = Number(pickData.triangleStart || 0), count = Number(pickData.triangleCount || 0);
  const arrayLike = value => ArrayBuffer.isView(value) || Array.isArray(value);
  if (!arrayLike(proxy.facePositions) || !arrayLike(proxy.faceIndices) || count <= 0) return [];
  const points = [];
  for (const vertex of Array.prototype.slice.call(proxy.faceIndices, start * 3, (start + count) * 3)) {
    points.push([proxy.facePositions[vertex * 3], proxy.facePositions[vertex * 3 + 1], proxy.facePositions[vertex * 3 + 2]]);
  }
  return points;
}

// The face's vertices as the display meshes draw it: where it is on screen, Explode and pose included.
function displayedFacePoints(runtime, reference) {
  const geometry = runtime ? buildFaceFillGeometryFromDisplayMeshes(runtime, THREE, reference) : null;
  const position = geometry?.getAttribute("position");
  const points = [];
  for (let index = 0; position && index < position.count; index += 1) points.push([position.getX(index), position.getY(index), position.getZ(index)]);
  geometry?.dispose();
  return points;
}

function edgePoints(segments) {
  const points = [];
  for (let index = 0; segments && index + 5 < segments.length; index += 6) {
    if (index === 0) points.push([segments[0], segments[1], segments[2]]);
    points.push([segments[index + 3], segments[index + 4], segments[index + 5]]);
  }
  return points;
}

/**
 * @returns {import("../../kit/camera/lookAt.js").LookSubject | null}
 */
export function lookSubjectForReference(runtime, selectorRuntime, reference) {
  const pickData = reference?.pickData;
  if (!pickData) return null;
  const place = placer(runtime ? referenceExplodedViewMatrix(runtime, reference) : null);
  const params = pickData.params || {};
  if (lower(pickData.selectorType || reference.selectorType) === "face") {
    const proxied = facePoints(selectorRuntime, pickData).map(place.point);
    const points = proxied.length ? proxied : displayedFacePoints(runtime, reference);
    if (!points.length) return null;
    const surface = lower(pickData.surfaceType);
    const normal = triplet(pickData.normal) || triplet(params.axis);
    const planeOrigin = triplet(params.origin) || triplet(pickData.center);
    if ((surface === "plane" || surface === "planar") && normal) {
      return { kind: "plane", normal: place.direction(normal), ...(planeOrigin ? { origin: place.point(planeOrigin) } : {}), points };
    }
    const axis = triplet(params.axis), origin = triplet(params.origin), radius = Number(params.radius);
    if (surface === "cylinder" && axis && origin && radius > 0) {
      return { kind: "cylinder", axis: place.direction(axis), origin: place.point(origin), radius, points };
    }
    return { kind: "free", points };
  }
  const segments = buildEdgeLinePositionsFromProxy(selectorRuntime, reference);
  const points = edgePoints(segments).map(place.point);
  if (!points.length) return null;
  const curve = lower(pickData.curveType);
  const direction = triplet(params.direction), axis = triplet(params.axis), center = triplet(params.center);
  if (curve === "line" && direction) return { kind: "line", direction: place.direction(direction), points };
  if ((curve === "circle" || curve === "ellipse") && axis && center) return { kind: "circle", axis: place.direction(axis), center: place.point(center), points };
  // A row that does not say (no params, or an older export's surface-type names: "plane" for a
  // line, "cylinder" for a circle): what the polyline is, as Measure reads it. A curve the row
  // names otherwise (a B-spline) is free, whatever three of its points would fit.
  if (curve && !["line", "circle", "ellipse", "plane", "cylinder"].includes(curve)) return { kind: "free", points };
  const shape = edgeGeometryFromSegments(segments);
  if (shape?.kind === "line" && shape.direction) return { kind: "line", direction: place.direction(shape.direction), points };
  if (shape?.kind === "arc" && shape.center) {
    const span = Math.max(...points.map(point => Math.hypot(...point.map((c, i) => c - points[0][i]))));
    const flat = planeOfPoints(points, Math.max(span * 0.01, 1e-6));
    if (flat) return { kind: "circle", axis: flat.normal, center: place.point(shape.center), points };
  }
  return { kind: "free", points };
}
